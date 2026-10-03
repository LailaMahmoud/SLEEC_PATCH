import copy
import hashlib
from collections import OrderedDict
import re
import time
import os
import threading
import uuid
from services.sleec_detection_engine import SLEECDetectionEngine, analysis_failures
from services.gpt_patch_engine import GPTPatchEngine
from services.sleec_patch_evaluation_store import SLEECPatchEvaluationStore
from services.repair_operator_selector import RepairOperatorSelector
from services.deterministic_repair_engine import DeterministicRepairEngine
from services.patch_ranker import PatchRanker
from services.use_case_descriptions import get_use_case_description
from services.semantic_patch_validator import SemanticPatchValidator
from services.diagnosis_evidence import diagnosis_for_issue, finding_identity
from services.repair_diagnosis_bridge import RepairDiagnosisBridge
from services.patch_verification_bridge import PatchVerificationBridge
from services.candidate_status import formally_verified, update_candidate_status

class SLEECPatchWorkbenchEngine:

    def __init__(self):
        self.detector = SLEECDetectionEngine()
        self.gpt_patch_engine = GPTPatchEngine()
        self.store = SLEECPatchEvaluationStore()

        self.operator_selector = RepairOperatorSelector()
        self.deterministic_engine = DeterministicRepairEngine()
        self.semantic_validator = SemanticPatchValidator()
        self.patch_ranker = PatchRanker()
        self.detector_cache = OrderedDict()
        self.detector_cache_lock = threading.RLock()
        self.detector_cache_max_entries = int(
            os.environ.get("SLEEC_DETECTOR_CACHE_SIZE", "64")
        )

    def run_detector_cached(self, sleec_text):
        if self.detector_cache_max_entries <= 0:
            result = self.detector.run_text(sleec_text)
            return {**(result if isinstance(result, dict) else {}), "cache_hit": False}

        cache_key = hashlib.sha256(
            str(sleec_text or "").encode("utf-8")
        ).hexdigest()

        with self.detector_cache_lock:
            cached = self.detector_cache.get(cache_key)
            if cached is not None:
                self.detector_cache.move_to_end(cache_key)
                return {**copy.deepcopy(cached), "cache_hit": True}

        result = self.detector.run_text(sleec_text)
        result = {**(result if isinstance(result, dict) else {}), "cache_hit": False}

        # A failed or incomplete analysis is not evidence and must be retried.
        if self.detector_failures(result):
            return result

        with self.detector_cache_lock:
            self.detector_cache[cache_key] = copy.deepcopy(result)

            while len(self.detector_cache) > self.detector_cache_max_entries:
                self.detector_cache.popitem(last=False)

        return result

    def check_sleec_syntax(self, sleec_text):
        # Parsing must not register solver types or require R-prefixed IDs.
        from services.rule_model import rules_from_text
        try:
            rules = rules_from_text(sleec_text)
            if not rules:
                raise ValueError("SLEEC rule block contains no parseable rules.")
            return {"valid": True, "error": "", "rule_count": len(rules)}
        except Exception as exc:
            return {"valid": False, "error": str(exc)}

    def detector_failures(self, analysis):
        return analysis_failures(analysis)

    def verify_edited_sleec(self, original_sleec, edited_sleec, issue):
        from services.rule_model import preserved_requirements
        if not isinstance(original_sleec, str) or not original_sleec.strip() or not isinstance(issue, dict):
            return {"valid": False, "failure_reason": "Original input and selected issue are required."}
        baseline = self.validate_patched_sleec(original_sleec)
        if not baseline["valid"]:
            return {**baseline, "failure_reason": "Original input analysis failed: " + baseline["failure_reason"]}
        before = baseline["analysis"]["structured"]
        kind, value = issue.get("issue_type"), issue.get("value")
        if not isinstance(kind, str) or value not in before.get(kind, []):
            return {"valid": False, "failure_reason": "The selected issue is not in the original diagnosis. Diagnose the input again."}
        validation = self.validate_patched_sleec(edited_sleec)
        if not validation["valid"]:
            return validation
        try:
            preserved_requirements(original_sleec, edited_sleec)
        except Exception as exc:
            return {**validation, "valid": False, "failure_reason": str(exc)}
        report = self.build_regression_report(kind, value, before, validation["analysis"]["structured"])
        passed = report["regression_passed"] is True
        return {**validation, "valid": passed, "regression_report": report,
                "failure_reason": "" if passed else "The selected issue still exists or the edit introduces a new issue.",
                "semantic_review_status": "pending"}

    def validate_patched_sleec(self, patched_sleec):
        syntax = self.check_sleec_syntax(patched_sleec)

        if not syntax.get("valid"):
            return {
                "valid": False,
                "failure_reason": f"SLEEC syntax invalid: {syntax.get('error', '')}",
                "syntax": syntax
            }

        analysis = self.run_detector_cached(patched_sleec)
        failures = self.detector_failures(analysis)

        if failures:
            return {
                "valid": False,
                "failure_reason": f"SLEEC detector failed: {failures}",
                "syntax": syntax,
                "analysis": analysis
            }

        return {
            "valid": True,
            "failure_reason": "",
            "syntax": syntax,
            "analysis": analysis
        }

    def validate_cumulative_sleec(self, original_sleec, final_sleec):
        validation = self.validate_patched_sleec(final_sleec)

        if not validation["valid"]:
            validation["passed"] = False
            return validation

        original_analysis = self.run_detector_cached(original_sleec)
        failures = self.detector_failures(original_analysis)
        if failures:
            return {**validation, "valid": False, "passed": False,
                    "failure_reason": f"Original analysis failed: {failures}"}
        from services.rule_model import preserved_requirements
        try:
            preserved_requirements(original_sleec, final_sleec)
        except Exception as exc:
            return {**validation, "valid": False, "passed": False, "failure_reason": str(exc)}
        before_records = self.issue_records(
            original_analysis.get("structured", {})
        )
        after_records = self.issue_records(
            validation["analysis"].get("structured", {})
        )
        introduced = sorted(set(after_records) - set(before_records))

        if introduced:
            validation["valid"] = False
            validation["passed"] = False
            validation["failure_reason"] = (
                "Cumulative SLEEC-PATCH introduced new WFI fingerprints."
            )
            validation["new_issue_count"] = len(introduced)
            validation["introduced_issues"] = introduced
            return validation

        validation["passed"] = True
        validation["new_issue_count"] = 0
        validation["introduced_issues"] = []
        return validation

    def diagnose(self, sleec_text):
        result = self.run_detector_cached(sleec_text)
        failures = self.detector_failures(result)
        if failures:
            return {"status": "ERROR", "error": f"SLEEC analysis failed: {failures}",
                    "sleec_text": sleec_text, "structured": result.get("structured", {}),
                    "detections": result.get("detections", {}), "issues": [], "issue_count": 0}
        structured = result["structured"]
        issues = []
        metadata = {"original_rules": [], "wfi_artifacts": [], "rule_references": [], "related_rules": [], "diagnoses": {}}
        for kind in self.issue_types():
            for index, value in enumerate(structured.get(kind, [])):
                issue = {"id": f"{kind}_{index + 1}", "issue_type": kind, "value": value, "source": "sleec"}
                for key, default in metadata.items():
                    values = structured.get(key + "_by_type", {}).get(kind, [])
                    issue["diagnosis" if key == "diagnoses" else key] = copy.deepcopy(values[index] if index < len(values) else default)
                issues.append(issue)
        return {"status": "OK", "sleec_text": sleec_text, "structured": structured,
                "detections": result["detections"], "issues": issues, "issue_count": len(issues)}

    def fallback_wfi_detection(self, sleec_text):
        rules = self.sleec_text_to_rules_json(sleec_text)

        result = {
            "conflicts": [],
            "redundancies": [],
            "concerns": [],
            "purpose_blocking": [],
            "situational_conflicts": []
        }

        seen = {}

        for r in rules:
            key = (
                r.get("condition", "").strip(),
                r.get("action", "").strip(),
                r.get("defeater", "").strip()
            )

            if key in seen:
                result["redundancies"].append(
                    self.rule_to_text(seen[key]) + "\n" + self.rule_to_text(r)
                )
            else:
                seen[key] = r

        for i, r1 in enumerate(rules):
            for r2 in rules[i + 1:]:
                same_condition = (
                    r1.get("condition", "").strip()
                    ==
                    r2.get("condition", "").strip()
                )

                opposite_actions = self.opposite_actions(
                    r1.get("action", ""),
                    r2.get("action", "")
                )

                if same_condition and opposite_actions:
                    result["conflicts"].append(
                        self.rule_to_text(r1) + "\n" + self.rule_to_text(r2)
                    )

        return result

    def opposite_actions(self, a, b):
        a = str(a).strip()
        b = str(b).strip()

        return (
            a == f"not {b}"
            or b == f"not {a}"
            or a == f"not{b}"
            or b == f"not{a}"
        )

    def rule_to_text(self, rule):
        text = f'{rule["id"]} when {rule["condition"]} then {rule["action"]}'

        if rule.get("defeater"):
            text += f' unless {{{rule["defeater"]}}}'


        return text



    def sleec_text_to_rules_json(self, sleec_text):
        from services.rule_model import rules_from_text
        return rules_from_text(sleec_text)


    def parse_rule_block(self, rule_text):
        clean = re.sub(r"\s+", " ", str(rule_text or "")).strip()

        match = re.match(
            r"^((?:Rule|R|r)\d+(?:_\d+)?)\s+when\s+(.+?)\s+then\s+(.+)$",
            clean,
            flags=re.IGNORECASE
        )

        if not match:
            return None

        rest = match.group(3).strip()
        action = rest
        defeater = ""

        if re.search(r"\s+unless\s+", rest, flags=re.IGNORECASE):
            action, defeater_rest = re.split(
                r"\s+unless\s+",
                rest,
                maxsplit=1,
                flags=re.IGNORECASE
            )
            defeater = re.split(
                r"\s+then\s+",
                defeater_rest,
                maxsplit=1,
                flags=re.IGNORECASE
            )[0].strip()

        return {
            "id": match.group(1),
            "condition": match.group(2).strip(),
            "action": action.strip(),
            "defeater": self.clean_rule_defeater(defeater),
            "raw": rule_text.strip()
        }

    def clean_rule_defeater(self, defeater):
        defeater = str(defeater or "").strip()

        if defeater.startswith("{") and defeater.endswith("}"):
            return defeater[1:-1].strip()

        return defeater

    def is_rule_start_line(self, stripped_line):
        return re.match(
            r"^(?:Rule|R|r)\d+(?:_\d+)?\s+when\b",
            str(stripped_line or ""),
            flags=re.IGNORECASE
        ) is not None



    def extract_rule_by_id(self, sleec_text, rule_id):
        if not rule_id:
            return ""

        lines = sleec_text.splitlines()
        collected = []
        inside = False

        start_pattern = re.compile(
            rf"^\s*{re.escape(rule_id)}\s+when\s+",
            re.IGNORECASE
        )

        next_rule_pattern = re.compile(
            r"^\s*(r\d+|rule\d+|c\d+)(?:_\d+)?\s+when\s+",
            re.IGNORECASE
        )

        for line in lines:
            stripped = line.strip()

            if start_pattern.match(stripped):
                inside = True
                collected.append(stripped)
                continue

            if inside:
                if next_rule_pattern.match(stripped) or stripped.lower() == "rule_end":
                    break

                if stripped and not stripped.startswith("//"):
                    collected.append(stripped)

        return " ".join(collected).strip()


    def clean_original_rule(self, original_rule, sleec_text, target_rule_id):
        original_rule = str(original_rule or "").strip()

        if target_rule_id:
            extracted = self.extract_rule_by_id(sleec_text, target_rule_id)
            if extracted:
                return extracted

        if len(original_rule) > 600 or "rule_start" in original_rule or "purpose_start" in original_rule:
            return ""

        return original_rule

    def operation_label(self, operation):
        labels = {
            "defeater_introduction": "Add exception",
            "defeater_propagation": "Carry exception forward",
            "purpose_defeater": "Add purpose-specific exception",
            "trigger_refinement": "Narrow trigger context",
            "trigger_strengthening": "Broaden trigger context",
            "defeater_refinement": "Defeater refinement",
            "deadline_refinement": "Deadline refinement",
            "rule_merging": "Merge overlapping rules",
            "rule_decomposition": "Split rule into cases",
            "rule_removal": "Remove redundant rule",
            "event_specialization": "Specialize event",
            "measure_specialization": "Specialize measure",
            "response_refinement": "Response refinement",
            "new_rule_generation": "Add new rule"
        }

        return labels.get(str(operation), str(operation or "Patch"))

    def stakeholder_summary(self, patch, operation_label):
        operation = str(patch.get("operation", ""))
        target = patch.get("target_rule_id") or ", ".join(patch.get("rule_ids", []))
        target_text = f" {target}" if target else ""

        summaries = {
            "defeater_introduction": (
                f"This patch updates rule{target_text} by adding an explicit exception "
                "instead of changing the main obligation."
            ),
            "defeater_propagation": (
                f"This patch updates rule{target_text} by carrying an existing exception "
                "into the repaired rule so the same priority condition is preserved."
            ),
            "purpose_defeater": (
                f"This patch updates rule{target_text} with an exception tied to the "
                "specific purpose that caused the well-formedness issue."
            ),
            "trigger_refinement": (
                f"This patch narrows when rule{target_text} applies, so the rule fires "
                "only in the context relevant to the issue."
            ),
            "trigger_strengthening": (
                f"This patch adds a contextual trigger condition to rule{target_text} "
                "to avoid the problematic case."
            ),
            "rule_merging": (
                f"This patch combines related behavior around rule{target_text} into "
                "one rule with a clearer exception or alternative response."
            ),
            "rule_decomposition": (
                f"This patch splits rule{target_text} into clearer cases so each "
                "condition and response can be inspected separately."
            ),
            "rule_removal": (
                f"This patch removes rule{target_text} because it appears redundant "
                "with another rule."
            )
        }

        return summaries.get(
            operation,
            f"This patch applies '{operation_label}' to address the selected well-formedness issue."
        )

    def review_flags(self, patch):
        flags = []
        operation = str(patch.get("operation", ""))
        text = " ".join([
            str(patch.get("original_rule", "")),
            str(patch.get("proposed_rule", "")),
            str(patch.get("natural_language_explanation", "")),
            str(patch.get("explanation", ""))
        ]).lower()

        if operation in {
            "defeater_introduction",
            "defeater_propagation",
            "purpose_defeater"
        }:
            flags.append("Check that the added exception matches stakeholder intent.")

        if operation in {"trigger_refinement", "trigger_strengthening"}:
            flags.append("Check that the narrowed trigger does not exclude required behavior.")

        if operation == "rule_decomposition":
            flags.append("Check that the split cases still cover the original rule.")

        if any(term in text for term in ["emergency", "alarm", "humanonfloor", "call"]):
            flags.append("Review priority-sensitive emergency behavior.")

        if patch.get("source") == "llm":
            flags.append("Review any newly introduced domain concept.")

        return flags

    def normalize_patch(self, patch, sleec_text=""):
        from services.operator_names import normalize_operators
        from services.boolean_simplifier import simplify_patch
        patch = normalize_operators(patch)
        if patch.get("source") == "deterministic":
            patch = simplify_patch(patch)
        patch_id = patch.get("patch_id") or patch.get("id") or "p_unknown"
        target_rule_id = patch.get("target_rule_id", "")
        operation = patch.get("operation", "N/A")
        operation_label = self.operation_label(operation)

        original_rule = self.clean_original_rule(
            patch.get("original_rule", ""),
            sleec_text,
            target_rule_id
        )

        if sleec_text and target_rule_id:
            from services.rule_model import rules_from_text
            baseline = {r['id']: r['raw'] for r in rules_from_text(sleec_text)}
            ids = [target_rule_id] + patch.get('removed_rule_ids', [])
            if all(rid in baseline for rid in ids):
                original_rule = "\n".join(baseline[rid] for rid in ids)

        return {
            **patch,
            "original_sleec": sleec_text,
            "id": patch_id,
            "patch_id": patch_id,
            "result_id": patch.get("result_id", patch.get("_result_id", "")),
            "source": patch.get("source", "llm"),
            "issue_type": patch.get("issue_type", ""),
            "rule_ids": patch.get("rule_ids", []),
            "target_rule_id": target_rule_id,
            "operation": operation,
            "operation_label": operation_label,
            "stakeholder_summary": self.stakeholder_summary(patch, operation_label),
            "review_flags": self.review_flags(patch),

            # now this is only Rule18, not full DAISY.sleec
            "original_rule": original_rule,

            "proposed_rule": patch.get("proposed_rule", ""),
            "missing_element": patch.get("missing_element", ""),

            # Preserve GPT V2 provenance evidence through normalization so the
            # semantic validator can verify the proposed semantic concept against
            # the permitted source.
            "grounding_evidence": patch.get("grounding_evidence", {}),

            "new_event": (
                patch.get("new_event", "")
                if operation == "semantic_rule_merging"
                else patch.get("new_event", patch.get("missing_element", ""))
            ),
            "new_measure": (
                patch.get("new_measure", "")
                if operation == "semantic_rule_merging"
                else patch.get("new_measure", patch.get("missing_element", ""))
            ),
            "new_capability": (
                patch.get("new_capability", "")
                if operation == "semantic_rule_merging"
                else patch.get("new_capability", patch.get("missing_element", ""))
            ),

            "new_rule": patch.get("new_rule", patch.get("proposed_rule", "")),
            "applicability": patch.get("applicability", {}),
            "natural_language_explanation": patch.get(
                "natural_language_explanation",
                patch.get("explanation", "")
            ),
            "modification_cost": patch.get("modification_cost", 1),
            "new_events_added": patch.get("new_events_added", 0),
            "new_measures_added": patch.get("new_measures_added", 0),
            "new_capabilities_added": patch.get("new_capabilities_added", 0),
            "new_rules_added": patch.get("new_rules_added", 0),
            "defeaters_added": patch.get("defeaters_added", 0),
            "verified": False
        }

    def apply_patch_to_text(self, sleec_text, patch):
        from services.rule_model import apply_rule_patch
        from services.operator_names import normalize_operators
        return apply_rule_patch(sleec_text, normalize_operators(patch))

    def ensure_rule_id(self, original_rule, proposed_rule):
        proposed_rule = proposed_rule.strip()

        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*\s+when\s+", proposed_rule, re.IGNORECASE):
            return proposed_rule

        match = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s+", original_rule.strip(), re.IGNORECASE)

        if match:
            return f"{match.group(1)} {proposed_rule}"

        return proposed_rule

    def replace_rule_by_id(self, sleec_text, target_rule_id, proposed_rule):
        lines = sleec_text.splitlines()
        output = []
        skipping_target = False
        replaced = False

        for line in lines:
            stripped = line.strip()

            if skipping_target:
                if self.is_rule_boundary(stripped):
                    output.append(line)
                    skipping_target = False

                continue

            if self.line_has_rule_id(stripped, target_rule_id):
                output.extend(
                    self.ensure_rule_id(line, proposed_rule).splitlines()
                )
                skipping_target = True
                replaced = True
                continue

            output.append(line)

        return "\n".join(output) if replaced else sleec_text

    def delete_rules_by_id(self, sleec_text, rule_ids):
        lines = sleec_text.splitlines()
        output = []
        skipping_target = False

        for line in lines:
            stripped = line.strip()

            if skipping_target:
                if self.is_rule_boundary(stripped):
                    output.append(line)
                    skipping_target = False

                continue

            if any(self.line_has_rule_id(stripped, rid) for rid in rule_ids):
                skipping_target = True
                continue

            output.append(line)

        return "\n".join(output)

    def line_has_rule_id(self, stripped_line, rule_id):
        if not rule_id:
            return False

        return re.match(
            rf"^{re.escape(str(rule_id))}\s+when\b",
            stripped_line,
            flags=re.IGNORECASE
        ) is not None

    def is_rule_boundary(self, stripped_line):
        if not stripped_line:
            return True

        if stripped_line == "rule_end":
            return True

        if stripped_line.startswith("//"):
            return True

        return re.match(
            r"^[A-Za-z_][A-Za-z0-9_]*\s+when\b",
            stripped_line,
            flags=re.IGNORECASE
        ) is not None

    def target_issue_fixed(
        self,
        issue_type,
        selected_issue_value,
        original_structured,
        new_structured
    ):
        """
        Determine whether the specifically selected WFI has disappeared.

        Verification is based on the stable WFI fingerprint, not:
        - a decrease in the number of WFIs,
        - diagnosis wording changes, or
        - incidental rule IDs appearing in a witness trace.
        """
        issue_type = str(issue_type or "").strip().lower()

        values = original_structured.get(issue_type, [])
        if selected_issue_value not in values:
            return False
        index = values.index(selected_issue_value)
        diagnoses = original_structured.get("diagnoses_by_type", {}).get(issue_type, [])
        selected_fingerprint = self.issue_fingerprint(
            issue_type, selected_issue_value, diagnoses[index] if index < len(diagnoses) else {})

        # Guard: the selected issue must genuinely belong to the
        # original diagnosis.
        original_records = self.issue_records(original_structured)

        if selected_fingerprint not in original_records:
            return False

        # Re-analyzed specification after applying the candidate.
        after_records = self.issue_records(new_structured)

        # The target is fixed only when its stable identity is absent.
        return selected_fingerprint not in after_records

    def issue_types(self):
        return [
            "concerns",
            "conflicts",
            "purpose_blocking",
            "redundancies",
            "situational_conflicts"
        ]

    def normalize_issue_text(self, issue):
        text = str(issue or "")
        text = re.sub(r"-{5,}|\*{5,}", " ", text)
        text = re.sub(r"^\s*.+?\s*:\s*\[\d+\s*,\s*\d+\]\s*$", " ", text, flags=re.MULTILINE)
        text = re.sub(r"\s+", " ", text)
        return text.strip().lower()
    def extract_wfi_id(self, issue_type, issue):
        """
        Extract an explicit WFI identifier when LEGOS provides one.

        Examples:
            concerns         -> c1, c4
            purpose_blocking -> p6, p7

        Returns None when the WFI category has no explicit identifier.
        """
        issue_type = str(issue_type or "").strip().lower()
        text = str(issue or "")

        if issue_type == "concerns":
            match = re.search(
                r"^\s*(c\d+(?:_[A-Za-z0-9]+)*)\b",
                text,
                flags=re.IGNORECASE | re.MULTILINE
            )
            if match:
                return match.group(1).lower()

        if issue_type == "purpose_blocking":
            match = re.search(
                r"Blocked\s+SLEEC\s+purpose:\s*"
                r"(p\d+(?:_[A-Za-z0-9]+)*)\b",
                text,
                flags=re.IGNORECASE | re.DOTALL
            )
            if match:
                return match.group(1).lower()

        return None
    def extract_conflict_rule_pair(self, issue):
        """
        Extract the two primary rules identified by LEGOS for a
        conflict/situational-conflict diagnosis.

        Ignores additional rules that appear later in the causal chain.
        """
        text = str(issue or "")

        rule_pattern = (
            r"((?:Rule|R|r)\d+[A-Za-z]*(?:_[A-Za-z0-9]+)*)\b"
        )

        primary_match = re.search(
            r"For rule:\s*-*\s*" + rule_pattern,
            text,
            flags=re.IGNORECASE | re.DOTALL
        )

        opposing_match = re.search(
            r"Because of the following SLEEC rule:\s*-*\s*" + rule_pattern,
            text,
            flags=re.IGNORECASE | re.DOTALL
        )

        if not primary_match or not opposing_match:
            return []

        return sorted({
            primary_match.group(1).upper(),
            opposing_match.group(1).upper()
        })
    def issue_fingerprint(self, issue_type, issue, diagnosis=None):
        identity = finding_identity(issue_type, issue, diagnosis)
        digest = hashlib.sha256(repr(identity).encode("utf-8")).hexdigest()[:24]
        return f"{issue_type}:{digest}"

    def extract_issue_rule_ids(self, issue):
        """
        Extract SLEEC rule identifiers from a diagnosis/witness.

        Supports examples such as:
            R3
            R14_1
            R11_cont_1
            R4b
            Rule18
            Rule5_1
        """
        return sorted(set(re.findall(
            r"\b(?:Rule|R|r)\d+[A-Za-z]*(?:_[A-Za-z0-9]+)*\b",
            str(issue or ""),
            flags=re.IGNORECASE
        )))

    def issue_summary(self, issue, max_length=220):
        text = re.sub(r"\s+", " ", str(issue or "")).strip()

        if len(text) > max_length:
            return text[:max_length].rstrip() + "..."

        return text

    def issue_records(self, structured):
        records = {}

        for issue_type in self.issue_types():
            diagnoses = structured.get("diagnoses_by_type", {}).get(issue_type, [])
            for index, issue in enumerate(structured.get(issue_type, [])):
                diagnosis = diagnoses[index] if index < len(diagnoses) else {}
                fingerprint = self.issue_fingerprint(issue_type, issue, diagnosis)
                records[fingerprint] = {
                    "fingerprint": fingerprint,
                    "issue_type": issue_type,
                    "summary": self.issue_summary(issue),
                    "rule_ids": diagnosis.get("affected_rule_ids") or self.extract_issue_rule_ids(issue)
                }

        return records

    def issue_counts_by_type(self, records):
        counts = {issue_type: 0 for issue_type in self.issue_types()}

        for record in records.values():
            counts[record["issue_type"]] = counts.get(record["issue_type"], 0) + 1

        return counts

    def build_regression_report(
        self,
        issue_key,
        selected_issue_value,
        original_structured,
        new_structured
    ):
        before_records = self.issue_records(original_structured)
        after_records = self.issue_records(new_structured)

        before_keys = set(before_records)
        after_keys = set(after_records)

        introduced_keys = sorted(after_keys - before_keys)
        resolved_keys = sorted(before_keys - after_keys)
        remaining_keys = sorted(after_keys & before_keys)

        selected_fixed = self.target_issue_fixed(
            issue_key,
            selected_issue_value,
            original_structured,
            new_structured
        )

        introduced = [after_records[key] for key in introduced_keys]
        resolved = [before_records[key] for key in resolved_keys]
        remaining = [after_records[key] for key in remaining_keys]


        return {
            "selected_issue_fixed": selected_fixed,
            "new_issues_introduced": len(introduced) > 0,
            "regression_passed": selected_fixed and len(introduced) == 0,
            "before_issue_count": len(before_records),
            "after_issue_count": len(after_records),
            "new_issue_count": len(introduced),
            "resolved_issue_count": len(resolved),
            "remaining_issue_count": len(remaining),
            "before_counts_by_type": self.issue_counts_by_type(before_records),
            "after_counts_by_type": self.issue_counts_by_type(after_records),
            "new_issues": introduced[:10],
            "resolved_issues": resolved[:10],
            "remaining_issues": remaining[:10]
        }

    def count_issues(self, structured):
        total = 0

        for value in structured.values():
            if isinstance(value, list):
                total += len(value)

        return total

    def patch_metrics(self, patch):
        operation = str(patch.get("operation", "")).strip()

        rules_modified = 1 if operation in [
            "edit",
            "edit_rule",
            "add_defeater",
            "defeater_introduction",
            "defeater_propagation",
            "purpose_defeater",
            "refine_condition",
            "trigger_refinement",
            "trigger_strengthening",
            "rule_merging",
            "rule_decomposition",
            "specialize_condition",
            "add_contextual_constraint",
            "replace_action",
            "refine_vague_predicate",
            "event_specialization",
            "measure_specialization",
            "response_refinement"
        ] else 0

        rules_added = 1 if operation in [
            "add",
            "add_rule",
            "new_rule_generation",
            "rule_decomposition"
        ] else 0

        rules_deleted = 1 if operation in [
            "delete",
            "delete_rule",
            "delete_redundant_rule",
            "rule_removal"
        ] else 0

        defeaters_added = 1 if operation in [
            "add_defeater",
            "defeater_introduction",
            "purpose_defeater"
        ] else 0

        conditions_refined = 1 if operation in [
            "refine_condition",
            "defeater_propagation",
            "trigger_refinement",
            "trigger_strengthening",
            "purpose_defeater",
            "rule_decomposition",
            "specialize_condition",
            "add_contextual_constraint",
            "event_specialization",
            "measure_specialization"
        ] else 0

        actions_refined = 1 if operation in [
            "refine_action",
            "replace_action",
            "response_refinement"
        ] else 0

        capabilities_refined = 1 if operation in [
            "refine_action",
            "replace_action",
            "response_refinement"
        ] else 0

        quantitative = self.patch_ranker.score_patch(patch)
        return {
            "rules_modified": quantitative["rules_edited"],
            "rules_added": quantitative["rules_added"],
            "rules_deleted": quantitative["rules_removed"],
            "defeaters_added": quantitative["new_defeaters"],
            "conditions_refined": conditions_refined or int(operation == "defeater_refinement"),
            "actions_refined": actions_refined or int(operation == "deadline_refinement"),
            "capabilities_refined": capabilities_refined
        }


    def build_final_sleecpatch_file(
        self,
        use_case,
        original_sleec,
        verified_patches,
        original_structured=None,
        issue_key="",
        selected_issue_value="",
        run_id=None
    ):
        final_sleec = original_sleec
        selected_patches = []

        # An exported repair must have the same complete proof as a saved result.
        applicable = [p for p in (verified_patches or []) if formally_verified(p)]

        if applicable:
            selected_patches = [sorted(
                applicable,
                key=lambda p: (
                    int(p.get("rank", 999) or 999),
                    -float(p.get("ranking_score", 0) or 0)
                )
            )[0]]

        for patch in selected_patches:
            final_sleec = self.apply_patch_to_text(final_sleec, patch)

        cumulative = {
            "passed": False,
            "failure_reason": "",
            "regression_report": {}
        }

        validation_gate = self.validate_patched_sleec(final_sleec)
        if validation_gate["valid"] and selected_patches:
            cumulative["passed"] = True

            if original_structured is not None and issue_key:
                final_structured = validation_gate["analysis"].get("structured", {})
                report = self.build_regression_report(
                    issue_key,
                    selected_issue_value,
                    original_structured,
                    final_structured
                )
                cumulative["regression_report"] = report
                cumulative["passed"] = report["regression_passed"]

                if not cumulative["passed"]:
                    cumulative["failure_reason"] = (
                        "Cumulative final specification failed regression verification."
                    )
        else:
            cumulative["failure_reason"] = validation_gate["failure_reason"] or "No formally verified repair is available."

        case_name = re.sub(r"[^A-Za-z0-9_.-]", "_", str(use_case)).strip(".") or "Unknown"
        folder = os.path.join("results", case_name)
        os.makedirs(folder, exist_ok=True)

        file_id = re.sub(r"[^A-Za-z0-9_-]", "_", str(run_id or uuid.uuid4().hex))
        path = os.path.join(folder, f"{case_name}_{file_id}_SLEECPATCH.sleec")

        if cumulative["passed"]:
            with open(path, "w", encoding="utf-8") as f:
                f.write(final_sleec)
        else:
            path = ""

        return {
            "use_case": use_case,
            "path": path,
            "sleec_text": final_sleec,
            "selected_patches": selected_patches,
            "cumulative_verification": cumulative
        }

    def verify_candidate_patch(self, original_sleec, issue, patch):
        patched_sleec = self.apply_patch_to_text(original_sleec, patch)

        validation_gate = self.validate_patched_sleec(patched_sleec)
        if not validation_gate["valid"]:
            patch["patched_sleec"] = patched_sleec
            patch["verified"] = False
            patch["regression_passed"] = False
            patch["failure_reason"] = validation_gate["failure_reason"]
            patch["syntax_validation"] = validation_gate.get("syntax", {})
            patch["verification_inconclusive"] = validation_gate.get("syntax", {}).get("valid") is True
            return {
                "patched_sleec": patched_sleec,
                "target_fixed": False,
                "related_issue": None,
                "regression_report": {},
                "verified": False,
                "new_analysis": validation_gate.get("analysis", {})
            }

        patch["syntax_validation"] = validation_gate.get("syntax", {})
        original_analysis = self.run_detector_cached(original_sleec)
        failures = self.detector_failures(original_analysis)
        if failures:
            patch.update(verified=False, verification_inconclusive=True,
                         failure_reason=f"Original analysis failed: {failures}")
            return {"patched_sleec": patched_sleec, "target_fixed": False, "related_issue": None,
                    "regression_report": {}, "verified": False, "new_analysis": validation_gate["analysis"]}
        original_structured = original_analysis.get("structured", {})
        new_analysis = validation_gate["analysis"]
        new_structured = new_analysis.get("structured", {})

        if isinstance(issue, dict):
            issue_key = issue.get("issue_type", "")
            selected_issue_value = issue.get("value", "")
        else:
            issue_key = patch.get("issue_type", "")
            selected_issue_value = issue

        regression_report = self.build_regression_report(
            issue_key,
            selected_issue_value,
            original_structured,
            new_structured
        )

        target_fixed = regression_report["selected_issue_fixed"]

        related_issue = self.find_related_new_issue(
            patch=patch,
            new_structured=new_structured,
            original_structured=original_structured
        )

        reasons = []
        if not target_fixed:
            reasons.append("The selected issue remains in the patched specification.")
        if regression_report["new_issue_count"]:
            reasons.append("The patch introduces new well-formedness issues.")
        if related_issue and not regression_report["new_issue_count"]:
            reasons.append("The edited rule has an unresolved related issue.")
        patch["failure_reason"] = " ".join(reasons)
        patch["verification_cache_hit"] = new_analysis.get("cache_hit", False)

        return {
            "patched_sleec": patched_sleec,
            "target_fixed": target_fixed,
            "related_issue": related_issue,
            "regression_report": regression_report,
            "verified": regression_report["regression_passed"] and related_issue is None,
            "new_analysis": new_analysis
        }

    def verify_llm_patch_once(
    self,
    original_sleec,
    issue_key,
    selected_issue_value,
    original_structured,
    patch,
    system_description="",
    ):
        # Stakeholder review never substitutes for formal verification.
        # Rejected candidates remain available with their failure evidence.
        current_patch = patch
        authoritative_diagnosis = copy.deepcopy(patch.get("diagnosis", {}))
        syntax_attempts = 0
        validation_gate = None

        while True:
            patched_sleec = self.apply_patch_to_text(original_sleec, current_patch)
            validation_gate = self.validate_patched_sleec(patched_sleec)

            if validation_gate["valid"]:
                patch = current_patch
                break

            current_patch["patched_sleec"] = patched_sleec
            current_patch["failure_reason"] = validation_gate["failure_reason"]
            current_patch["syntax_validation"] = validation_gate.get("syntax", {})

            if validation_gate.get("syntax", {}).get("valid") is True:
                current_patch.update(verified=False, verification_inconclusive=True,
                                     target_fixed=False, regression_report={})
                update_candidate_status(current_patch)
                return None

            if current_patch.get("change") or syntax_attempts >= 2:
                return self._surface_llm_patch(
                    current_patch,
                    patched_sleec,
                    syntax_valid=False,
                    failure_reason=validation_gate["failure_reason"],
                )

            try:
                current_patch = self.gpt_patch_engine.repair_patch_syntax(
                    patch=current_patch,
                    syntax_error=validation_gate["failure_reason"],
                    original_sleec=original_sleec,
                    patched_sleec=patched_sleec
                )
                current_patch = self.normalize_patch(current_patch, original_sleec)
                current_patch["diagnosis"] = copy.deepcopy(authoritative_diagnosis)
                syntax_attempts += 1
            except Exception as exc:
                return self._surface_llm_patch(
                    current_patch,
                    patched_sleec,
                    syntax_valid=False,
                    failure_reason=(
                        f"{validation_gate['failure_reason']}; "
                        f"LLM syntax repair failed: {exc}"
                    ),
                )

        # Parsing and completed detection are prerequisites for the formal check.
        new_analysis = validation_gate["analysis"]
        new_structured = new_analysis.get("structured", {})
        rules_json = self.sleec_text_to_rules_json(original_sleec)
        print("\n========== GPT V2 SEMANTIC CONTEXT ==========")
        print("Description chars:", len(system_description or ""))
        print("Description preview:", (system_description or "")[:200])
        print("Grounding evidence:", patch.get("grounding_evidence"))
        print("=============================================\n")
        semantic_validation = self.semantic_validator.validate(
            sleec_text=original_sleec,
            issue={
                "issue_type": issue_key,
                "value": selected_issue_value
            },
            patch=patch,
            existing_events=self.extract_defined_events(original_sleec),
            existing_measures=self.extract_defined_measures(original_sleec),
            existing_responses=self.extract_rule_actions(rules_json),
            system_description=system_description,
        )

        regression_report = self.build_regression_report(
            issue_key,
            selected_issue_value,
            original_structured,
            new_structured
        )

        target_fixed = regression_report["selected_issue_fixed"]

        related_issue = self.find_related_new_issue(
            patch=patch,
            new_structured=new_structured,
            original_structured=original_structured
        )

        patch["target_fixed"] = target_fixed
        patch["related_issue"] = related_issue
        patch["validation_result"] = new_structured
        patch["syntax_validation"] = validation_gate.get("syntax", {})
        patch["regression_report"] = regression_report
        patch["regression_passed"] = regression_report["regression_passed"]
        patch["semantic_validation"] = semantic_validation
        patch["semantic_validation_passed"] = bool(
            semantic_validation.get("valid")
        )
        patch["vocabulary_grounded"] = bool(
            semantic_validation.get("vocabulary_grounding", {}).get("passed")
        )
        patch["diagnosis_aligned"] = bool(
            semantic_validation.get("diagnosis_alignment", {}).get("passed")
        )
        patch["operator_valid"] = bool(
            semantic_validation.get("operator_validation", {}).get("passed")
        )
        patch["temporal_alignment"] = bool(
            semantic_validation.get("temporal_validation", {}).get("passed")
        )

        # Semantic validation is advisory.
        # It does not determine formal verification.
        semantic_warning = not semantic_validation.get("valid")

        patch["semantic_warning"] = semantic_warning
        patch["semantic_warning_reason"] = (
            "; ".join(semantic_validation.get("errors", []))
            if semantic_warning
            else ""
        )
        print("\n========== LLM FORMAL VERIFICATION DEBUG ==========")
        print("OPERATION:", patch.get("operation"))
        print("TARGET FIXED:", target_fixed)
        print("RELATED ISSUE:", related_issue)
        print("REGRESSION PASSED:", regression_report["regression_passed"])
        print("HAS STRUCTURED CHANGE:", bool(patch.get("change")))
        print("SEMANTIC VALID:", semantic_validation.get("valid"))
        print("SEMANTIC ERRORS:", semantic_validation.get("errors", []))
        print("===================================================\n")
        formally_verified = bool(
        target_fixed
        and related_issue is None
        and regression_report["regression_passed"]
        and (not patch.get("change") or semantic_validation.get("valid") is True)
         )

        if not formally_verified:
            reasons = []

            if not target_fixed:
                reasons.append("target issue not fixed")

            if related_issue:
                reasons.append("introduced related issue on edited rule")

            if regression_report["new_issue_count"]:
                reasons.append("introduced new WFI during regression")
            if patch.get("change") and semantic_validation.get("valid") is not True:
                reasons.extend(semantic_validation.get("errors", ["Structured semantic edit validation failed."]))

            failure_reason = "; ".join(reasons)
        else:
            failure_reason = ""

        return self._surface_llm_patch(
            patch,
            patched_sleec,
            syntax_valid=True,
            formally_verified=formally_verified,
            failure_reason=failure_reason,
        )

    def _surface_llm_patch(
        self,
        patch,
        patched_sleec,
        syntax_valid,
        formally_verified=False,
        failure_reason="",
    ):
        """Store the formal verification status of an LLM patch.

        LLM candidates may still require social-scientist review, but human-review
        status is independent from formal verification. A patch is `verified`
        only when it has passed the formal verification pipeline.
        """
        patch["patched_sleec"] = patched_sleec
        patch["syntax_valid"] = bool(syntax_valid)
        patch["formally_verified"] = bool(formally_verified)
        patch["regression_passed"] = bool(
            patch.get("regression_passed", formally_verified)
        )

        patch["requires_social_scientist_review"] = True

        # IMPORTANT:
        # `verified` means formal verification, not "surface for review".
        patch["verified"] = bool(formally_verified)

        patch["failure_reason"] = failure_reason
        return update_candidate_status(patch)


    def verify_deterministic_patch_iteratively(
        self,
        original_sleec,
        issue_key,
        selected_issue_value,
        original_structured,
        patch,
        depth=0,
        max_depth=3
    ):
        patched_sleec = self.apply_patch_to_text(original_sleec, patch)

        validation_gate = self.validate_patched_sleec(patched_sleec)
        if not validation_gate["valid"]:
            patch["target_fixed"] = False
            patch["related_issue"] = None
            patch["patched_sleec"] = patched_sleec
            patch["validation_result"] = {}
            patch["verification_depth"] = depth
            patch["syntax_validation"] = validation_gate.get("syntax", {})
            patch["regression_report"] = {}
            patch["regression_passed"] = False
            patch["verified"] = False
            patch["failure_reason"] = validation_gate["failure_reason"]
            return None

        new_analysis = validation_gate["analysis"]
        new_structured = new_analysis.get("structured", {})

        regression_report = self.build_regression_report(
            issue_key,
            selected_issue_value,
            original_structured,
            new_structured
        )

        target_fixed = regression_report["selected_issue_fixed"]

        related_issue = self.find_related_new_issue(
            patch=patch,
            new_structured=new_structured,
            original_structured=original_structured
        )

        patch["target_fixed"] = target_fixed
        patch["related_issue"] = related_issue
        patch["patched_sleec"] = patched_sleec
        patch["validation_result"] = new_structured
        patch["verification_depth"] = depth
        patch["syntax_validation"] = validation_gate.get("syntax", {})
        patch["regression_report"] = regression_report
        patch["regression_passed"] = regression_report["regression_passed"]

        if target_fixed and related_issue is None and regression_report["regression_passed"]:
            patch["verified"] = True
            return patch

        if depth >= max_depth:
            patch["verified"] = False
            patch["failure_reason"] = "Maximum deterministic augmentation depth reached"
            return None

        if target_fixed and related_issue:
            followup_patches = self.deterministic_engine.generate(
                issue_type=related_issue["issue_type"],
                selected_issue=related_issue["issue"],
                rules=self.sleec_text_to_rules_json(patched_sleec),
                operators=self.operator_selector.select(
                    issue_type=related_issue["issue_type"],
                    rules=self.sleec_text_to_rules_json(patched_sleec),
                    selected_issue=related_issue["issue"],
                    existing_events=self.extract_defined_events(patched_sleec),
                    existing_measures=self.extract_defined_measures(patched_sleec),
                    existing_responses=self.extract_rule_actions(
                        self.sleec_text_to_rules_json(patched_sleec)
                    )
                ).get("deterministic", []),
                existing_events=self.extract_defined_events(patched_sleec)
            )

            for followup in followup_patches:
                followup = self.normalize_patch(followup, patched_sleec)

                augmented = self.verify_deterministic_patch_iteratively(
                    original_sleec=patched_sleec,
                    issue_key=related_issue["issue_type"],
                    selected_issue_value=related_issue["issue"],
                    original_structured=new_structured,
                    patch=followup,
                    depth=depth + 1,
                    max_depth=max_depth
                )

                if augmented:
                    final_analysis = self.run_detector_cached(augmented["patched_sleec"])
                    final_structured = final_analysis.get("structured", {})
                    final_regression_report = self.build_regression_report(
                        issue_key,
                        selected_issue_value,
                        original_structured,
                        final_structured
                    )

                    if not final_regression_report["regression_passed"]:
                        continue

                    patch["verified"] = True
                    patch["patched_sleec"] = augmented["patched_sleec"]
                    patch["augmented_with"] = augmented
                    patch["augmentation_reason"] = "Fixed related issue involving edited rule"
                    patch["verification_depth"] = depth + 1
                    patch["regression_report"] = final_regression_report
                    patch["regression_passed"] = True
                    return patch

        patch["verified"] = False
        if target_fixed and not regression_report["regression_passed"]:
            patch["failure_reason"] = "Introduced new WFI during regression check"
        else:
            patch["failure_reason"] = "Target not fixed or related issue unresolved"
        return None


    def find_related_new_issue(self, patch, new_structured, original_structured=None):
        edited_rules = set(patch.get("edited_rules", []))
        original_fingerprints = set()

        if original_structured:
            original_fingerprints = set(self.issue_records(original_structured))

        target_rule_id = patch.get("target_rule_id")
        if target_rule_id:
            edited_rules.add(target_rule_id)

        if not edited_rules:
            return None

        for issue_type, issues in new_structured.items():
            if not isinstance(issues, list):
                continue

            for issue in issues:
                fingerprint = self.issue_fingerprint(issue_type, issue)
                if fingerprint in original_fingerprints:
                    continue

                issue_text = str(issue)

                for rule_id in edited_rules:
                    if rule_id and rule_id in issue_text:
                        return {
                            "issue_type": issue_type,
                            "issue": issue,
                            "related_rule": rule_id
                        }

        return None



    def extract_defined_events(self, sleec_text):
        return sorted(set(re.findall(
            r"^\s*event\s+([A-Za-z_][A-Za-z0-9_]*)",
            str(sleec_text),
            flags=re.IGNORECASE | re.MULTILINE
        )))

    def extract_defined_measures(self, sleec_text):
        return sorted(set(re.findall(
            r"^\s*measure\s+([A-Za-z_][A-Za-z0-9_]*)",
            str(sleec_text),
            flags=re.IGNORECASE | re.MULTILINE
        )))

    def extract_rule_actions(self, rules):
        return sorted(set(
            str(rule.get("action", "")).strip()
            for rule in rules
            if str(rule.get("action", "")).strip()
        ))



    def generate_verified_patches(
    self,
    use_case,
    sleec_text,
    issue,
    max_attempts=1
):
        start_total = time.time()
        run_id = uuid.uuid4().hex

        original_analysis = self.run_detector_cached(sleec_text)
        original_structured = original_analysis.get("structured", {})
        failures = self.detector_failures(original_analysis)
        if failures:
            raise RuntimeError(f"Cannot verify repairs: original analysis failed: {failures}")

        issue_type = issue.get("issue_type", "")
        issue_key = issue_type

        if issue_type == "redundancy":
            issue_key = "redundancies"
        elif issue_type == "conflict":
            issue_key = "conflicts"
        elif issue_type == "concern":
            issue_key = "concerns"
        elif issue_type == "purpose":
            issue_key = "purpose_blocking"
        elif issue_type == "situational_conflict":
            issue_key = "situational_conflicts"

        selected_issue_value = issue.get("value", "")
        selected_issue_value = str(selected_issue_value)

        if selected_issue_value not in original_structured.get(issue_key, []):
            raise ValueError("The selected issue is not in the original diagnosis. Diagnose the input again.")
        selected_diagnosis = diagnosis_for_issue(
            original_structured,
            issue_key,
            selected_issue_value,
            issue.get("id")
        )
        issue = {**issue, "issue_type": issue_key, "diagnosis": copy.deepcopy(selected_diagnosis)}
        # ----------------------------------------------------------
        # Bridge formal LEGOS diagnosis to repair generation.
        #
        # The selected detector diagnosis remains authoritative.
        # Repair-derived information is added separately and does
        # not overwrite the formal diagnosis.
        # ----------------------------------------------------------
        diagnosis_bridge = RepairDiagnosisBridge()

        repair_evidence = diagnosis_bridge.build(
            sleec_text=sleec_text,
            issue_type=issue_key,
            issue=issue,
            diagnosis=selected_diagnosis,
        )

        # Use the preserved authoritative diagnosis downstream.
        selected_diagnosis = repair_evidence["diagnosis"]

        print("\n========== REPAIR DIAGNOSIS BRIDGE ==========")
        print("PROVENANCE:",
              repair_evidence.get("diagnosis_provenance"))
        print("SOURCE ID:",
              selected_diagnosis.get("source_id"))
        print("TRACE:",
              selected_diagnosis.get("trace", []))
        print("AFFECTED RULES:",
              selected_diagnosis.get("affected_rule_ids", []))
        print("TARGET RULES:",
              repair_evidence["repair_context"].get(
                  "target_rule_ids", []
              ))
        print("RELATED CANDIDATE RULES:",
              repair_evidence["repair_context"].get(
                  "candidate_related_rule_ids", []
              ))
        print("SEMANTIC RULES:",
              repair_evidence["repair_context"].get(
                  "semantic_rule_ids", []
              ))
        print("=============================================\n")

        print("\n========== SELECTED STRUCTURED DIAGNOSIS ==========")
        print("ISSUE ID:", issue.get("id"))
        print("ISSUE TYPE:", issue_key)
        print("TRACE:", selected_diagnosis.get("trace", []))
        print("AFFECTED RULES:", selected_diagnosis.get("affected_rule_ids", []))
        print("===================================================\n")

        verified_patches = []
        failed_patches = []
        failed_patch_count = 0

        deterministic_candidates = []
        llm_candidates = []

        generation_time = 0
        validation_time = 0
        attempts = 0

        rules_json = self.sleec_text_to_rules_json(sleec_text)
        print("\n========== EXISTING RESPONSES ==========")
        print(self.extract_rule_actions(rules_json))
        print("========================================\n")

        # Load the authoritative case-study description once.
        # It is used for operator selection, GPT generation, and semantic validation.
        description = get_use_case_description(use_case)

        operator_plan = self.operator_selector.select(
            issue_type=issue_key,
            rules=rules_json,
            selected_issue=selected_issue_value,
            existing_events=self.extract_defined_events(sleec_text),
            existing_measures=self.extract_defined_measures(sleec_text),
            existing_responses=self.extract_rule_actions(rules_json),
            system_description=description,
            sleec_text=sleec_text,
            diagnosis=selected_diagnosis
            )
        

        print("\n========== REPAIR OPERATOR SELECTION ==========")
        print("Issue Type:", issue_key)
        print("Deterministic operators:", operator_plan.get("deterministic", []))
        print("LLM operators:", operator_plan.get("llm", []))
        print("Applicability:", operator_plan.get("applicability", {}))
        print("==============================================\n")

        selected_findings = {
            issue_key: [selected_issue_value]
        }

        # ----------------------------------------------------------
        # Resolve repair-target rules from the diagnosis bridge.
        #
        # The bridge is primary because it preserves the exact LEGOS
        # diagnosis and adds repair-derived target information.
        #
        # Text-based rule discovery is retained only as a legacy
        # fallback when the bridge cannot identify any usable rule.
        # ----------------------------------------------------------

        bridge_context = repair_evidence.get("repair_context", {})

        diagnosed_rule_ids = list(dict.fromkeys(
            bridge_context.get("semantic_rule_ids", [])
            or bridge_context.get("target_rule_ids", [])
        ))

        diagnosed_issue_rules = [
            rule
            for rule in rules_json
            if str(rule.get("id", "")).strip() in diagnosed_rule_ids
        ]

        # Legacy fallback: do not lose the old working behaviour.
        if not diagnosed_issue_rules:
            diagnosed_issue_rules = self.operator_selector.find_issue_rules(
                selected_issue_value,
                rules_json
            )

            diagnosed_rule_ids = [
                str(rule.get("id", "")).strip()
                for rule in diagnosed_issue_rules
                if str(rule.get("id", "")).strip()
            ]

        print("\n========== REPAIR TARGET RESOLUTION ==========")
        print("BRIDGE TARGET IDS:",
              bridge_context.get("target_rule_ids", []))
        print("BRIDGE SEMANTIC IDS:",
              bridge_context.get("semantic_rule_ids", []))
        print("FINAL TARGET IDS:",
              diagnosed_rule_ids)
        print("TARGET SOURCE:",
              "bridge" if (
                  bridge_context.get("semantic_rule_ids")
                  or bridge_context.get("target_rule_ids")
              ) else "legacy_fallback")
        print("=============================================\n")

        semantic_ops = operator_plan.get("llm", [])
        llm_patches = []
        gpt_warning = None



        seen_candidate_signatures = set()
        seen_verified_signatures = set()
        seen_failed_signatures = set()

        # -------------------------------
        # Multiple attempts
        # -------------------------------

        while attempts < max_attempts:
            attempts += 1

            start_generation = time.time()

            deterministic_patches = self.deterministic_engine.generate(
                issue_type=issue_key, selected_issue=operator_plan.get("diagnosis", selected_issue_value),
                rules=rules_json, operators=operator_plan.get("deterministic", []),
                existing_events=self.extract_defined_events(sleec_text), sleec_text=sleec_text,
                diagnosis=selected_diagnosis)

            generation_time += time.time() - start_generation

            for i, p in enumerate(deterministic_patches, start=1):
                p["patch_id"] = p.get("patch_id", f"d{i}")
                p["id"] = p.get("id", p["patch_id"])
                p["source"] = "deterministic"
                p["diagnosis"] = copy.deepcopy(selected_diagnosis)

                sig = (
                    p.get("operation"),
                    p.get("target_rule_id"),
                    p.get("proposed_rule"),
                    p.get("missing_element")
                )

                if sig not in seen_candidate_signatures:
                    deterministic_candidates.append(p)
                    seen_candidate_signatures.add(sig)
                    self.store.save_patch_candidate({
                        "run_id": run_id,
                        "use_case": use_case,
                        "issue_id": issue.get("id", ""),
                        "issue_type": issue_key,
                        "attempt": attempts,
                        "candidate_signature": self.patch_signature_text(p),
                        "patch": p
                    })

            patches = deterministic_patches

            for patch in patches:
                normalized_patch = self.normalize_patch(patch, sleec_text)

                if normalized_patch.get("patch_id") == "not_applicable":
                    failed_patch_count += 1
                    normalized_patch["verified"] = False
                    normalized_patch["failure_reason"] = "Patch not applicable"
                    normalized_patch["attempt"] = attempts
                    failed_patches.append(normalized_patch)
                    continue

                patch_signature = (
                    normalized_patch.get("operation"),
                    normalized_patch.get("target_rule_id"),
                    normalized_patch.get("proposed_rule"),
                    normalized_patch.get("missing_element")
                )

                if patch_signature in seen_verified_signatures:
                    continue

                source = normalized_patch.get("source", "")

                print("--------------------------------")
                print("ATTEMPT:", attempts)
                print("SOURCE:", source)
                print("OPERATION:", normalized_patch.get("operation"))
                print("--------------------------------")

                start_validation = time.time()

                if source == "deterministic":
                    verification = self.verify_candidate_patch(
                        original_sleec=sleec_text,
                        issue={
                            "issue_type": issue_key,
                            "value": selected_issue_value,
                        },
                        patch=normalized_patch,
                    )

                    normalized_patch["patched_sleec"] = verification["patched_sleec"]
                    normalized_patch["target_fixed"] = verification["target_fixed"]
                    normalized_patch["related_issue"] = verification["related_issue"]
                    normalized_patch["regression_report"] = verification["regression_report"]
                    normalized_patch["regression_passed"] = bool(
                        verification["regression_report"].get(
                            "regression_passed", False
                        )
                    )
                    normalized_patch["validation_result"] = (
                        verification["new_analysis"].get("structured", {})
                    )
                    normalized_patch["verified"] = bool(verification["verified"])

                    # Synchronize formal verification fields used by the frontend.
                    # This keeps verified/formally_verified/candidate_status consistent
                    # without weakening the formal verification requirements.
                    update_candidate_status(normalized_patch)

                    print("\n========== DETERMINISTIC VERIFICATION ==========")
                    print("PATCH:", normalized_patch.get("patch_id"))
                    print("OPERATION:", normalized_patch.get("operation"))
                    print("VERIFIED:", verification.get("verified"))
                    print("TARGET FIXED:", verification.get("target_fixed"))
                    print("RELATED ISSUE:", verification.get("related_issue"))
                    print("REGRESSION:", verification.get("regression_report"))
                    print("FAILURE REASON:", normalized_patch.get("failure_reason"))
                    print("SYNTAX:", normalized_patch.get("syntax_validation"))
                    print("================================================\n")

                    if verification["verified"]:
                        verified = normalized_patch
                    else:
                        verified = None
                else:
                    verified = self.verify_llm_patch_once(
                        original_sleec=sleec_text,
                        issue_key=issue_key,
                        selected_issue_value=selected_issue_value,
                        original_structured=original_structured,
                        patch=normalized_patch,
                        system_description=description,
                    )

                validation_time += time.time() - start_validation

                if verified and bool(verified.get("verified", False)):
                    verified["attempt"] = attempts
                    verified_patches.append(verified)
                    seen_verified_signatures.add(patch_signature)
                else:
                    if verified:
                        normalized_patch = verified

                    if patch_signature not in seen_failed_signatures:
                        failed_patch_count += 1
                        normalized_patch["verified"] = False
                        normalized_patch["attempt"] = attempts
                        failed_patches.append(normalized_patch)
                        seen_failed_signatures.add(patch_signature)

        # DEVELOPMENT BRANCH: dict-based split, not deterministic-first.
        # Deterministic and LLM operators are generated independently from the
        # operator plan (BASE_DETERMINISTIC_OPERATORS / BASE_LLM_OPERATORS), so
        # GPT runs whenever the plan carries semantic operators -- regardless of
        # whether the deterministic side already produced verified patches.
        if semantic_ops:
            start_generation = time.time()


            print("\n========== USE CASE CONTEXT ==========")
            print("Use case:", use_case)
            print("Description:", description)
            print("======================================\n")

            print(">>> Calling GPT with operators:", semantic_ops)

            try:
                llm_patches = self.gpt_patch_engine.generate_all_patches(
                    rules=[r for r in rules_json if r["id"] in operator_plan.get("target_resolution", {}).get("semantic_rule_ids", [])],
                    structured_findings={issue_key: [operator_plan.get("diagnosis", selected_issue_value)]},
                    repair_operators=semantic_ops,
                    system_description=description,
                    existing_events=self.extract_defined_events(sleec_text),
                    existing_measures=self.extract_defined_measures(sleec_text),
                    existing_responses=self.extract_rule_actions(rules_json)
                )
            except Exception as gpt_error:
                llm_patches = []
                gpt_warning = f"GPT semantic repair generation failed: {gpt_error}"
                print(">>> GPT GENERATION FAILED:", repr(gpt_error))
            print("\n========== GPT RETURNED PATCHES ==========")
            print("COUNT:", len(llm_patches))
            for idx, candidate in enumerate(llm_patches, start=1):
                print(f"\nGPT CANDIDATE {idx}:")
                print(candidate)
            print("==========================================\n")
            # Prepare GPT proposals for formal verification while preserving
            # the exact generated proposal and diagnosis provenance.
            verification_bridge = PatchVerificationBridge()

            materialized = []
            surfaced_llm_candidates = []
            resolution = operator_plan.get("target_resolution", {})

            allowed_rule_ids = resolution.get(
                "semantic_rule_ids",
                resolution.get("rule_ids", [])
            )
            addition_scope = resolution.get("addition_scope")

            for proposal_index, proposal in enumerate(llm_patches, 1):
                proposal = {**proposal, "patch_id": f"g{proposal_index}", "source": "llm"}
                bridge_result = verification_bridge.prepare(
                    sleec_text=sleec_text,
                    candidate=proposal,
                    allowed_rule_ids=allowed_rule_ids,
                    addition_scope=addition_scope,
                    repair_evidence=repair_evidence,
                )

                if bridge_result.get("success"):
                    candidate = bridge_result["executable_patch"]
                    candidate["diagnosis"] = copy.deepcopy(selected_diagnosis)
                    candidate["materialization_status"] = "success"
                    candidate["materialization_error"] = None
                    materialized.append(candidate)
                    surfaced_llm_candidates.append(candidate)

                    print("\n========== PATCH VERIFICATION BRIDGE ==========")
                    print("OPERATION:", proposal.get("operation"))
                    print("TARGET:", proposal.get("target_rule_id"))
                    print("MATERIALIZED: True")
                    print("===============================================\n")

                else:
                    failure = {
                        **proposal,
                        "diagnosis": copy.deepcopy(selected_diagnosis),
                        "verified": False,
                        "failure_stage": "materialization",
                        "failure_reason": bridge_result.get(
                            "materialization", {}
                        ).get(
                            "error",
                            "Unable to materialize semantic repair."
                        ),
                        "generated_candidate": bridge_result.get(
                            "generated_candidate",
                            proposal
                        ),
                        "repair_provenance": bridge_result.get(
                            "provenance",
                            {}
                        ),
                    }

                    failure["materialization_status"] = "failed"
                    failure["materialization_error"] = failure.get(
                        "failure_reason"
                    )
                    failure["formally_verified"] = False
                    failure["candidate_status"] = "materialization_failed"

                    update_candidate_status(failure)

                    self.store.save_patch_candidate({
                        "run_id": run_id,
                        "use_case": use_case,
                        "issue_id": issue.get("id", ""),
                        "issue_type": issue_key,
                        "attempt": attempts,
                        "candidate_signature": self.patch_signature_text(failure),
                        "candidate_status": failure.get(
                            "candidate_status",
                            "materialization_failed"
                        ),
                        "patch": failure,
                    })
                    failed_patches.append(failure)
                    surfaced_llm_candidates.append(failure)
                    failed_patch_count += 1

                    print("\n========== PATCH VERIFICATION BRIDGE ==========")
                    print("OPERATION:", proposal.get("operation"))
                    print("TARGET:", proposal.get("target_rule_id"))
                    print("MATERIALIZED: False")
                    print("ERROR:", failure["failure_reason"])
                    print("===============================================\n")

            llm_patches = materialized
            #llm_patches = materialized

            for i, p in enumerate(surfaced_llm_candidates, start=1):
                p.setdefault("patch_id", f"g{i}")
                p.setdefault("id", p["patch_id"])
                p["source"] = p.get("source", "llm")

            for i, p in enumerate(llm_patches, start=1):
                p.setdefault("patch_id", f"g{i}")
                p.setdefault("id", f"g{i}")
                p["source"] = p.get("source", "llm")

            for i, p in enumerate(llm_patches, start=1):
                p.setdefault("patch_id", f"g{i}")
                p.setdefault("id", f"g{i}")
                p["source"] = p.get("source", "llm")

                self.store.save_patch_candidate({
                    "run_id": run_id,
                    "use_case": use_case,
                    "issue_id": issue.get("id", ""),
                    "issue_type": issue_key,
                    "attempt": attempts,
                    "candidate_signature": self.patch_signature_text(p),
                    "candidate_status": "generated",
                    "patch": p
                })

            llm_candidates.extend(surfaced_llm_candidates)
            generation_time += time.time() - start_generation

            # Only successfully materialized candidates enter LEGOS
            # formal verification. Materialization failures remain visible
            # through llm_candidates/failed_patches.
            for patch in llm_patches:
                normalized_patch = self.normalize_patch(patch, sleec_text)

                if normalized_patch.get("patch_id") == "not_applicable":
                    failed_patch_count += 1
                    normalized_patch["verified"] = False
                    normalized_patch["failure_reason"] = "Patch not applicable"
                    normalized_patch["attempt"] = attempts
                    failed_patches.append(normalized_patch)
                    continue

                patch_signature = (
                    normalized_patch.get("operation"),
                    normalized_patch.get("target_rule_id"),
                    normalized_patch.get("proposed_rule"),
                    normalized_patch.get("missing_element")
                )

                if patch_signature in seen_verified_signatures:
                    continue
                start_validation = time.time()
                print("\n========== ENTERING LLM VERIFICATION ==========")
                print("PATCH ID:", normalized_patch.get("patch_id"))
                print("OPERATION:", normalized_patch.get("operation"))
                print("MISSING ELEMENT:", normalized_patch.get("missing_element"))
                print("PROPOSED RULE:", normalized_patch.get("proposed_rule"))
                print("GROUNDING:", normalized_patch.get("grounding_evidence"))
                print("================================================\n")
                verified = self.verify_llm_patch_once(
                    original_sleec=sleec_text,
                    issue_key=issue_key,
                    selected_issue_value=selected_issue_value,
                    original_structured=original_structured,
                    patch=normalized_patch,
                    system_description=description,
                )
                print("\n========== LLM VERIFICATION RETURN ==========")
                print(verified)
                print("=============================================\n")
                validation_time += time.time() - start_validation

                if verified and bool(verified.get("verified", False)):
                    verified["attempt"] = attempts
                    verified_patches.append(verified)
                    seen_verified_signatures.add(patch_signature)
                else:
                    if verified:
                        normalized_patch = verified

                    if patch_signature not in seen_failed_signatures:
                        failed_patch_count += 1
                        normalized_patch["verified"] = False
                        normalized_patch["attempt"] = attempts
                        failed_patches.append(normalized_patch)
                        seen_failed_signatures.add(patch_signature)

        total_time = time.time() - start_total

        # Publish and persist one authoritative verdict, including failures.
        # These fields must exist even when app.py is used without its wrapper.
        confirmed = []
        for patch in verified_patches:
            update_candidate_status(patch)
            if formally_verified(patch):
                confirmed.append(patch)
            else:
                patch["failure_reason"] = patch.get("failure_reason") or "Formal verification evidence is incomplete."
                failed_patches.append(patch)
                failed_patch_count += 1
        verified_patches = confirmed
        for patch in failed_patches:
            patch["verified"] = False
            update_candidate_status(patch)

        # Rank verified candidates using the paper's quantitative lexicographic costs.
        verified_patches = self.patch_ranker.rank(verified_patches)

        output_file = self.build_final_sleecpatch_file(
            use_case,
            sleec_text,
            verified_patches,
            original_structured=original_structured,
            issue_key=issue_key,
            selected_issue_value=selected_issue_value,
            run_id=run_id
        )

        total_time = time.time() - start_total
        log = {
            "run_id": run_id,
            "input_sha256": hashlib.sha256(sleec_text.encode("utf-8")).hexdigest(),
            "use_case": use_case,
            "issue_id": issue.get("id", ""),
            "issue_type": issue_key,
            "attempts": attempts,
            "max_attempts": max_attempts,
            "failed_patch_count": failed_patch_count,
            "verified_patch_count": len(verified_patches),
            "generation_time_seconds": round(generation_time, 3),
            "validation_time_seconds": round(validation_time, 3),
            "total_time_seconds": round(total_time, 3),
            "successful": len(verified_patches) > 0
        }

        self.store.save_pipeline_run({
            **log,
            "selected_issue": selected_issue_value,
            "repair_operators": operator_plan,
            "original_issue_count": self.count_issues(original_structured),
            "original_structured": original_structured,
            "generated_file_path": output_file.get("path", "")
        })

        for patch in failed_patches + verified_patches:
            self.store.update_patch_candidate({"run_id": run_id, "patch": patch})
            self.store.save_patch_verification({
                "run_id": run_id,
                "use_case": use_case,
                "issue_id": issue.get("id", ""),
                "issue_type": issue_key,
                "attempt": patch.get("attempt", attempts),
                "patch": patch
            })

        for patch in verified_patches:
            metrics = self.patch_metrics(patch)

            self.store.save_result({
                "run_id": run_id,
                "use_case": use_case,
                "issue_id": issue.get("id", ""),
                "issue_type": issue_key,
                "selected_issue": selected_issue_value,

                "attempts": attempts,
                "failed_patch_count": failed_patch_count,
                "verified_patch_count": len(verified_patches),

                "generation_time_seconds": round(generation_time, 3),
                "validation_time_seconds": round(validation_time, 3),
                "total_time_seconds": round(total_time, 3),

                "patch_id": patch.get("patch_id", patch.get("id", "")),
                "id": patch.get("result_id", ""),
                "operation": patch.get("operation", ""),
                "source": patch.get("source", "unknown"),
                "rank": patch.get("rank", 0),
                "ranking_score": patch.get("ranking_score", 0),

                "target_rule_id": patch.get("target_rule_id", ""),
                "original_rule": patch.get("original_rule", ""),
                "proposed_rule": patch.get("proposed_rule", ""),
                "natural_language_explanation": patch.get(
                    "natural_language_explanation",
                    ""
                ),
                "patched_sleec": patch.get("patched_sleec", ""),

                "rules_modified": metrics["rules_modified"],
                "rules_added": metrics["rules_added"],
                "rules_deleted": metrics["rules_deleted"],
                "defeaters_added": metrics["defeaters_added"],
                "conditions_refined": metrics["conditions_refined"],
                "actions_refined": metrics["actions_refined"],
                "capabilities_refined": metrics["capabilities_refined"],

                "verified": formally_verified(patch),

                "expert_similarity": 0,
                "expert_match": False,
                "requires_social_scientist_review": bool(
                    patch.get(
                        "requires_social_scientist_review",
                        str(patch.get("source", "")).lower() == "llm"
                    )
                )
            })

        from services.deployment_frontend_compat import generation_payload
        return generation_payload({
            "status": "OK",
            "selected_issue": issue,
            "repair_operators": operator_plan,
            "deterministic_candidates": deterministic_candidates,
            "llm_candidates": llm_candidates,
            "verified_patches": verified_patches,
            "failed_patches": failed_patches,
            "generated_file": output_file,
            "log": log,
            "gpt_warning": gpt_warning
        })

    def patch_signature_text(self, patch):
        parts = [
            patch.get("operation", ""),
            patch.get("target_rule_id", ""),
            patch.get("proposed_rule", ""),
            patch.get("missing_element", "")
        ]

        return hashlib.sha1(
            "|".join(str(part) for part in parts).encode("utf-8")
        ).hexdigest()

    def extract_rule_from_issue_text(self, text):
        text = str(text).strip()

        match = re.search(
            r"(Rule\d+(?:_\d+)?\s+when\s+.*?then\s+.*)",
            text,
            flags=re.IGNORECASE | re.DOTALL
        )

        if match:
            return match.group(1).strip()

        return text
    def build_rank1_sleecpatch(self, use_case, original_sleec, all_wfi_results):
        final_sleec = original_sleec
        selected_patches = []

        for result in all_wfi_results:
            verified = result.get("verified_patches", [])

            if not verified:
                continue

            ranked = sorted(
                verified,
                key=lambda p: p.get("rank", 999)
            )

            best_patch = ranked[0]
            selected_patches.append(best_patch)

            final_sleec = self.apply_patch_to_text(
                final_sleec,
                best_patch
            )

        validation_gate = self.validate_cumulative_sleec(
            original_sleec,
            final_sleec
        )
        cumulative = {
            "passed": bool(validation_gate.get("valid")),
            "failure_reason": validation_gate.get("failure_reason", ""),
            "new_issue_count": validation_gate.get("new_issue_count", 0),
            "introduced_issues": validation_gate.get("introduced_issues", [])
        }

        folder = os.path.join("results", use_case)
        os.makedirs(folder, exist_ok=True)

        output_path = os.path.join(
            folder,
            f"{use_case}_SLEECPATCH.sleec"
        )

        if cumulative["passed"]:
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(final_sleec)
        else:
            output_path = ""

        return {
            "use_case": use_case,
            "output_path": output_path,
            "selected_patches": selected_patches,
            "final_sleec": final_sleec,
            "cumulative_verification": cumulative
        }
