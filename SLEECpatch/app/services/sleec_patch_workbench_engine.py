import copy
import hashlib
from collections import OrderedDict
import re
import time
import os
import threading
import uuid
from services.sleec_detection_engine import SLEECDetectionEngine, analysis_failures
from services.diagnosis_evidence import diagnosis_for_issue, finding_identity
from services.rule_model import rules_from_text, apply_rule_patch, preserved_requirements
from services.evidence_repair import target_resolution
from services.structured_semantic_edit import materialize_semantic_edit
from services.candidate_status import formally_verified, update_candidate_status
from services.gpt_patch_engine import GPTPatchEngine
from services.sleec_patch_evaluation_store import SLEECPatchEvaluationStore
from services.repair_operator_selector import RepairOperatorSelector
from services.deterministic_repair_engine import DeterministicRepairEngine
from services.patch_ranker import PatchRanker
from services.use_case_descriptions import get_use_case_description
from services.semantic_patch_validator import SemanticPatchValidator


class SLEECPatchWorkbenchEngine:

    def __init__(self):
        self.detector = SLEECDetectionEngine()
        self.gpt_patch_engine = GPTPatchEngine()
        self.store = SLEECPatchEvaluationStore()

        self.operator_selector = RepairOperatorSelector()
        self.deterministic_engine = DeterministicRepairEngine()
        self.semantic_validator = SemanticPatchValidator()
        # Section C ranking:
        # structural/logical = deterministic;
        # semantic clarity/interpretability = GPT, after formal verification.
        self.patch_ranker = PatchRanker(
            semantic_assessor=self._assess_patch_quality_for_ranking
        )
        self.detector_cache = OrderedDict()
        self.detector_cache_lock = threading.RLock()
        self.detector_cache_max_entries = int(
            os.environ.get("SLEEC_DETECTOR_CACHE_SIZE", "64")
        )

        # Context supplied to the Section-C quality assessor for the current WFI.
        self._ranking_context = {}

    def _assess_patch_quality_for_ranking(self, patch):
        """
        Called by PatchRanker only for formally verified patches.
        GPT assesses semantic clarity and interpretability; it does not
        re-decide formal correctness.
        """
        context = patch.get("ranking_context", {}) or {}

        quality_patch = dict(patch)
        quality_patch["selected_issue"] = context.get("selected_issue", "")
        quality_patch["issue_type"] = context.get("issue_type", "")
        quality_patch["affected_rules"] = context.get("affected_rules", [])
        quality_patch["diagnosis_context"] = context.get("diagnosis_context", "")

        return self.gpt_patch_engine.assess_patch_quality(
            patch=quality_patch,
            system_description=context.get("system_description", ""),
            existing_events=context.get("existing_events", []),
            existing_measures=context.get("existing_measures", []),
            existing_responses=context.get("existing_responses", [])
        )

    def run_detector_cached(self, sleec_text):
        if self.detector_cache_max_entries <= 0:
            return self.detector.run_text(sleec_text)

        cache_key = hashlib.sha256(
            str(sleec_text or "").encode("utf-8")
        ).hexdigest()

        with self.detector_cache_lock:
            cached = self.detector_cache.get(cache_key)
            if cached is not None:
                self.detector_cache.move_to_end(cache_key)
                return copy.deepcopy(cached)

        result = self.detector.run_text(sleec_text)

        if self.detector_failures(result):
            return result

        with self.detector_cache_lock:
            self.detector_cache[cache_key] = copy.deepcopy(result)

            while len(self.detector_cache) > self.detector_cache_max_entries:
                self.detector_cache.popitem(last=False)

        return result

    def check_sleec_syntax(self, sleec_text):
        try:
            rules = rules_from_text(sleec_text)
            ids = [rule["id"] for rule in rules]
            if len(set(ids)) != len(ids):
                raise ValueError("Rule IDs must be unique.")
            return {"valid": True, "error": "", "rule_count": len(rules)}
        except Exception as exc:
            return {"valid": False, "error": str(exc)}

    def detector_failures(self, analysis):
        return analysis_failures(analysis)

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

        try:
            preserved_requirements(original_sleec, final_sleec)
        except ValueError as exc:
            validation.update(valid=False, passed=False, failure_reason=str(exc))
            return validation

        original_analysis = self.run_detector_cached(original_sleec)
        failures = self.detector_failures(original_analysis)
        if failures:
            return {
                "valid": False,
                "passed": False,
                "failure_reason": f"Original SLEEC analysis failed: {failures}",
                "analysis": original_analysis,
            }
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

    def verify_edited_sleec(self, original_sleec, patched_sleec, issue):
        """Check a human edit against the same target and regression gates as a repair.

        Manual edits are previews, not generated experimental candidates, and
        are not persisted as automatic repair results.
        """
        baseline = self.validate_patched_sleec(original_sleec)
        if not baseline["valid"]:
            return {**baseline, "failure_reason": "Original input: " + baseline["failure_reason"]}
        before = baseline["analysis"].get("structured", {})
        kind, value = issue.get("issue_type"), issue.get("value")
        if kind not in self.issue_types() or value not in before.get(kind, []):
            return {"valid": False, "failure_reason": "The selected issue is not in the original diagnosis. Diagnose the input again."}
        validation = self.validate_cumulative_sleec(original_sleec, patched_sleec)
        if not validation["valid"]:
            return validation
        report = self.build_regression_report(
            kind, value, before, validation["analysis"].get("structured", {})
        )
        passed = report["regression_passed"] is True
        return {
            "valid": passed,
            "failure_reason": "" if passed else "The selected issue still exists or the edit introduces a new issue.",
            "syntax": validation["syntax"],
            "regression_report": report,
            "semantic_review_status": "pending",
        }

    def diagnose(self, sleec_text):
        result = self.run_detector_cached(sleec_text)
        failures = self.detector_failures(result)
        if failures:
            return {
                "status": "ERROR",
                "error": f"SLEEC analysis failed: {failures}",
                "sleec_text": sleec_text,
                "structured": result.get("structured", {}) if isinstance(result, dict) else {},
                "detections": result.get("detections", {}) if isinstance(result, dict) else {},
                "issues": [],
                "issue_count": 0,
            }

        print("\n========== DETECTOR OUTPUT ==========")
        print(result)
        print("====================================\n")
        structured = result.get("structured", {})
        detections = result.get("detections", {})

        issues = []

        original_rules_by_type = structured.get("original_rules_by_type", {})

        for issue_type in self.issue_types():
            items = structured.get(issue_type, [])

            for index, item in enumerate(items, start=1):

                original_rules = []

                if issue_type in original_rules_by_type:
                    rules_list = original_rules_by_type.get(issue_type, [])

                    if index - 1 < len(rules_list):
                        original_rules = rules_list[index - 1]

                issues.append({
                    "id": f"{issue_type}_{index}",
                    "issue_type": issue_type,
                    "value": item,
                    "original_rules": original_rules,
                    "diagnosis": diagnosis_for_issue(structured, issue_type, item, f"{issue_type}_{index}"),
                    "source": "sleec"
                })



        return {
            "status": "OK",
            "sleec_text": sleec_text,
            "structured": structured,
            "detections": detections,
            "issues": issues,
            "issue_count": len(issues)
        }

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
        return rule.get("raw") or self.deterministic_engine.rule_to_text(rule)



    def sleec_text_to_rules_json(self, sleec_text):
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
        return next((rule["raw"] for rule in rules_from_text(sleec_text) if rule["id"] == rule_id), "")


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
            "trigger_strengthening": "Add trigger condition",
            "rule_merging": "Merge overlapping rules",
            "rule_decomposition": "Split rule into cases",
            "rule_removal": "Remove redundant rule",
            "event_specialization": "Specialize event",
            "measure_specialization": "Specialize measure",
            "capability_refinement": "Refine capability",
            "new_rule_generation": "Add new rule",
            "temporal_refinement": "Refine temporal bound"
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
        patch_id = patch.get("patch_id") or patch.get("id") or "p_unknown"
        target_rule_id = patch.get("target_rule_id", "")
        operation = patch.get("operation", "N/A")
        operation_label = self.operation_label(operation)

        original_rule = self.clean_original_rule(
            patch.get("original_rule", ""),
            sleec_text,
            target_rule_id
        )

        return {
            "id": patch_id,
            "patch_id": patch_id,
            "result_id": patch.get("result_id", patch.get("_result_id", "")),
            "source": patch.get("source", "llm"),
            "issue_type": patch.get("issue_type", ""),
            "rule_ids": patch.get("rule_ids", []),
            "diagnosis": copy.deepcopy(patch.get("diagnosis", {})),
            "target_resolution": copy.deepcopy(patch.get("target_resolution", {})),
            "change": copy.deepcopy(patch.get("change")),
            "declaration_text": patch.get("declaration_text", ""),
            "target_rule_id": target_rule_id,
            "source_requirement_id": patch.get("source_requirement_id", ""),
            "operation": operation,
            "operation_label": operation_label,
            "stakeholder_summary": self.stakeholder_summary(patch, operation_label),
            "review_flags": self.review_flags(patch),

            # now this is only Rule18, not full DAISY.sleec
            "original_rule": original_rule,

            "proposed_rule": patch.get("proposed_rule", ""),
            "missing_element": patch.get("missing_element", ""),
            "new_event": patch.get("new_event", patch.get("missing_element", "")),
            "new_measure": patch.get("new_measure", patch.get("missing_element", "")),
            "new_capability": patch.get("new_capability", patch.get("missing_element", "")),
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
        updated = apply_rule_patch(sleec_text, patch)
        if self.check_sleec_syntax(updated)["valid"]:
            preserved_requirements(sleec_text, updated)
            originals = {rule["id"]: rule["raw"] for rule in rules_from_text(sleec_text)}
            after = {rule["id"]: rule["raw"] for rule in rules_from_text(updated)}
            for rule_id, raw in originals.items():
                if rule_id != patch.get("target_rule_id") and after.get(rule_id) != raw:
                    raise ValueError("The repair changed an unrelated rule.")
        return updated

    def normalize_rule_for_comparison(self, text):
        """Normalize rule text only for no-op comparison."""
        return " ".join(str(text or "").split()).strip().lower()

    def is_noop_patch(self, patch):
        """Return True when a candidate makes no executable rule change."""
        original = self.normalize_rule_for_comparison(
            patch.get("original_rule", "")
        )
        proposed = self.normalize_rule_for_comparison(
            patch.get("proposed_rule", "")
        )

        operation = str(patch.get("operation", "")).strip().lower()

        # Empty proposed text is valid only for an explicit removal operation.
        if not proposed:
            return operation != "rule_removal"

        return bool(original and original == proposed)

    def ensure_rule_id(self, original_rule, proposed_rule):
        proposed_rule = proposed_rule.strip()

        if re.match(r"^(r\d+|rule\d+|c\d+)(?:_\d+)?\s+when\s+", proposed_rule, re.IGNORECASE):
            return proposed_rule

        match = re.match(r"^((?:r\d+|rule\d+|c\d+)(?:_\d+)?)\s+", original_rule.strip(), re.IGNORECASE)

        if match:
            return f"{match.group(1)} {proposed_rule}"

        return proposed_rule

    def replace_rule_by_id(self, sleec_text, rule_id, proposed_rule):
        return apply_rule_patch(sleec_text, {"operation": "edit", "target_rule_id": rule_id, "proposed_rule": proposed_rule})

    def delete_rules_by_id(self, sleec_text, rule_ids):
        for rule_id in rule_ids:
            sleec_text = apply_rule_patch(sleec_text, {"operation": "rule_removal", "target_rule_id": rule_id})
        return sleec_text

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
            r"^(?:Rule|R|r)\d+(?:_\d+)?\s+when\b",
            stripped_line,
            flags=re.IGNORECASE
        ) is not None

    def target_issue_fixed(self, issue_type, selected_issue_value, original_structured, new_structured):
        before = original_structured.get(issue_type, [])
        if selected_issue_value not in before:
            return False
        matching = [record for record in self.issue_records(original_structured).values()
                    if record["issue_type"] == issue_type and record["value"] == selected_issue_value]
        after = list(self.issue_records(new_structured).values())
        for selected in matching:
            for remaining in after:
                if remaining["issue_type"] != issue_type:
                    continue
                if selected.get("source_id") and selected["source_id"] == remaining.get("source_id"):
                    return False
                if selected["fingerprint"] == remaining["fingerprint"]:
                    return False
        return bool(matching)

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

    def issue_fingerprint(self, issue_type, issue, diagnosis=None):
        identity = finding_identity(issue_type, issue, diagnosis)
        digest = hashlib.sha1(repr(identity).encode("utf-8")).hexdigest()[:16]
        return f"{issue_type}:{digest}"

    def extract_issue_rule_ids(self, issue):
        return sorted(set(re.findall(
            r"\b(?:Rule|R|r)\d+(?:_\d+)?\b",
            str(issue or "")
        )))

    def issue_summary(self, issue, max_length=220):
        text = re.sub(r"\s+", " ", str(issue or "")).strip()

        if len(text) > max_length:
            return text[:max_length].rstrip() + "..."

        return text

    def issue_records(self, structured):
        records = {}
        for issue_type in self.issue_types():
            for index, issue in enumerate(structured.get(issue_type, []), start=1):
                diagnosis = diagnosis_for_issue(structured, issue_type, issue, f"{issue_type}_{index}")
                fingerprint = self.issue_fingerprint(issue_type, issue, diagnosis)
                records[fingerprint] = {
                    "fingerprint": fingerprint, "issue_type": issue_type,
                    "source_id": diagnosis.get("source_id"), "value": issue,
                    "summary": self.issue_summary(issue),
                    "rule_ids": diagnosis.get("affected_rule_ids", self.extract_issue_rule_ids(issue))
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
            "capability_refinement"
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
            "capability_refinement"
        ] else 0

        capabilities_refined = 1 if operation in [
            "refine_action",
            "replace_action",
            "capability_refinement"
        ] else 0

        return {
            "rules_modified": rules_modified,
            "rules_added": rules_added,
            "rules_deleted": rules_deleted,
            "defeaters_added": defeaters_added,
            "conditions_refined": conditions_refined,
            "actions_refined": actions_refined,
            "capabilities_refined": capabilities_refined
        }


    def build_final_sleecpatch_file(
        self,
        use_case,
        original_sleec,
        verified_patches,
        original_structured=None,
        issue_key="",
        selected_issue_value=""
    ):
        final_sleec = original_sleec
        selected_patches = []
        verified_patches = [patch for patch in verified_patches if formally_verified(patch)]
        if not verified_patches:
            return {"path": "", "cumulative_verification": {"passed": False, "failure_reason": "No formally verified repair is available."}}

        if verified_patches:
            selected_patches = [sorted(
                verified_patches,
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
        if validation_gate["valid"]:
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
            cumulative["failure_reason"] = validation_gate["failure_reason"]

        folder = os.path.join("results", use_case)
        os.makedirs(folder, exist_ok=True)

        path = os.path.join(folder, f"{use_case}_SLEECPATCH.sleec")

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
            return {
                "patched_sleec": patched_sleec,
                "target_fixed": False,
                "related_issue": None,
                "regression_report": {},
                "verified": False,
                "new_analysis": validation_gate.get("analysis", {})
            }

        original_analysis = self.run_detector_cached(original_sleec)
        failures = self.detector_failures(original_analysis)
        if failures:
            patch["verified"] = False
            patch["regression_passed"] = False
            patch["failure_reason"] = f"Original SLEEC analysis failed: {failures}"
            return {
                "patched_sleec": patched_sleec,
                "target_fixed": False,
                "related_issue": None,
                "regression_report": {},
                "verified": False,
                "new_analysis": validation_gate["analysis"],
                "failure_reason": patch["failure_reason"],
            }
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
    patch
):
        current_patch = patch
        diagnosis = copy.deepcopy(patch.get("diagnosis", {}))
        syntax_attempts = 0

        while True:
            try:
                patched_sleec = self.apply_patch_to_text(original_sleec, current_patch)
            except (ValueError, TypeError) as exc:
                current_patch.update(verified=False, failure_reason=str(exc))
                update_candidate_status(current_patch)
                return None
            validation_gate = self.validate_patched_sleec(patched_sleec)

            if validation_gate["valid"]:
                patch = current_patch
                break

            current_patch["patched_sleec"] = patched_sleec
            current_patch["verified"] = False
            current_patch["regression_passed"] = False
            current_patch["failure_reason"] = validation_gate["failure_reason"]
            current_patch["syntax_validation"] = validation_gate.get("syntax", {})
            current_patch["verification_inconclusive"] = bool(validation_gate.get("syntax", {}).get("valid"))
            update_candidate_status(current_patch)

            if validation_gate.get("syntax", {}).get("valid"):
                # Solver/infrastructure failures are not syntax errors for an
                # LLM to repair. Stop before any retry or acceptance.
                return None

            if current_patch.get("change") is not None:
                return None

            if syntax_attempts >= 2:
                return None

            try:
                current_patch = self.gpt_patch_engine.repair_patch_syntax(
                    patch=current_patch,
                    syntax_error=validation_gate["failure_reason"],
                    original_sleec=original_sleec,
                    patched_sleec=patched_sleec
                )
                current_patch["diagnosis"] = copy.deepcopy(diagnosis)
                current_patch = self.normalize_patch(current_patch, original_sleec)
                syntax_attempts += 1
            except Exception as exc:
                current_patch["failure_reason"] = (
                    f"{validation_gate['failure_reason']}; LLM syntax repair failed: {exc}"
                )
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
        patch["syntax_validation"] = validation_gate.get("syntax", {})
        patch["regression_report"] = regression_report
        patch["regression_passed"] = regression_report["regression_passed"]

        if not target_fixed:
            patch["failure_reason"] = "Target issue not fixed"
            return None

        if related_issue:
            patch["failure_reason"] = "Introduced related issue involving edited rule"
            return None

        if not regression_report["regression_passed"]:
            patch["failure_reason"] = "Introduced new WFI during regression check"
            return None

        patch["verified"] = True
        update_candidate_status(patch)
        return patch


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
        try:
            patched_sleec = self.apply_patch_to_text(original_sleec, patch)
        except (ValueError, TypeError) as exc:
            patch.update(verified=False, failure_reason=str(exc))
            update_candidate_status(patch)
            return None

        validation_gate = self.validate_patched_sleec(patched_sleec)
        if not validation_gate["valid"]:
            print("\n========== DETERMINISTIC PATCH REJECTED ==========")
            print("Patch ID:", patch.get("patch_id"))
            print("Operation:", patch.get("operation"))
            print("Target rule:", patch.get("target_rule_id"))
            print("Original rule:", patch.get("original_rule"))
            print("Proposed rule:", patch.get("proposed_rule"))
            print("Failure reason:", validation_gate.get("failure_reason"))
            print("Syntax result:", validation_gate.get("syntax", {}))
            print("==================================================\n")

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
            patch["verification_inconclusive"] = bool(validation_gate.get("syntax", {}).get("valid"))
            update_candidate_status(patch)
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
            update_candidate_status(patch)
            return patch

        if depth >= max_depth:
            patch["verified"] = False
            patch["failure_reason"] = (
                "Selected issue remains after repair" if not target_fixed
                else "Introduced new findings during regression check"
            )
            patch["augmentation_limit_reached"] = True
            update_candidate_status(patch)
            return None

        if target_fixed and related_issue:
            followup_patches = self.deterministic_engine.generate(
                issue_type=related_issue["issue_type"],
                selected_issue=related_issue["issue"],
                diagnosis=related_issue.get("diagnosis", {}),
                sleec_text=patched_sleec,
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
                ).get("deterministic", [])
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
                    final_validation = self.validate_patched_sleec(
                        augmented["patched_sleec"]
                    )

                    if not final_validation["valid"]:
                        print(
                            "Skipping augmented deterministic patch because "
                            "the cumulative SLEEC is invalid:",
                            final_validation.get("failure_reason")
                        )
                        continue

                    final_analysis = final_validation["analysis"]
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

        for issue_type in self.issue_types():
            issues = new_structured.get(issue_type, [])

            for index, issue in enumerate(issues, start=1):
                diagnosis = diagnosis_for_issue(new_structured, issue_type, issue, f"{issue_type}_{index}")
                fingerprint = self.issue_fingerprint(issue_type, issue, diagnosis)
                if fingerprint in original_fingerprints:
                    continue

                issue_text = str(issue)

                for rule_id in edited_rules:
                    if rule_id and (rule_id in diagnosis.get("affected_rule_ids", []) or re.search(rf"(?<!\w){re.escape(rule_id)}(?!\w)", issue_text)):
                        return {
                            "issue_type": issue_type,
                            "issue": issue,
                            "diagnosis": diagnosis_for_issue(new_structured, issue_type, issue, f"{issue_type}_{index}"),
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
        failures = self.detector_failures(original_analysis)
        if failures:
            raise RuntimeError(f"Cannot generate verified patches: original analysis failed: {failures}")
        original_structured = original_analysis.get("structured", {})

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
        # Use evidence from the current server-side analysis, including when a
        # client only sends the legacy finding value. Do not trust posted traces.
        diagnosis = copy.deepcopy(diagnosis_for_issue(
            original_structured, issue_key, selected_issue_value, issue.get("id")
        ))
        issue = {**issue, "diagnosis": diagnosis}

        if issue_key == "redundancies":
            selected_issue_value = self.extract_rule_from_issue_text(selected_issue_value)

        verified_patches = []
        failed_patches = []
        failed_patch_count = 0

        deterministic_candidates = []
        llm_candidates = []

        generation_time = 0
        validation_time = 0
        attempts = 0

        rules_json = self.sleec_text_to_rules_json(sleec_text)
        resolution = target_resolution(sleec_text, issue_key, diagnosis)
        addition_scope = resolution.get("addition_scope")
        resolved_rules = [rule for rule in rules_json if rule["id"] in resolution["rule_ids"]]
        operator_plan = self.operator_selector.select(
            issue_type=issue_key,
            rules=resolved_rules,
            selected_issue=selected_issue_value,
            existing_events=self.extract_defined_events(sleec_text),
            existing_measures=self.extract_defined_measures(sleec_text),
            existing_responses=self.extract_rule_actions(rules_json)
        )

        print("\n========== REPAIR OPERATOR SELECTION ==========")
        print("Issue Type:", issue_key)
        print("Deterministic operators:", operator_plan.get("deterministic", []))
        print("LLM operators:", operator_plan.get("llm", []))
        print("Applicability:", operator_plan.get("applicability", {}))
        print("==============================================\n")

        # Resolve the diagnosed rule(s) before GPT generation so semantic
        # candidates are grounded in the selected issue rather than an
        # unrelated rule from the specification.
        gpt_target_rules = resolved_rules

        target_rule_texts = [
            self.deterministic_engine.rule_to_text(rule)
            for rule in gpt_target_rules
            if isinstance(rule, dict)
        ]
        target_rule_ids = [
            str(rule.get("id", "")).strip()
            for rule in gpt_target_rules
            if isinstance(rule, dict) and str(rule.get("id", "")).strip()
        ]

        finding_context = [selected_issue_value]
        if diagnosis:
            finding_context.append({"diagnosis": diagnosis})
        if target_rule_texts:
            finding_context.append(
                "AFFECTED TARGET RULE(S) — generate the semantic repair only "
                "for these rule(s):\n" + "\n".join(target_rule_texts)
            )
        if addition_scope:
            finding_context.append({"addition_scope": addition_scope})
            finding_context.append(
                "For new_rule_generation, use source_requirement_id from addition_scope, "
                "and target_rule_id=null. Synthesize and justify one new rule using the "
                "diagnosis and domain context. Preserve existing rules. You may explicitly "
                "select deadline={kind: source} to retain the concern's time window."
            )
        else:
            finding_context.append("Edit only a rule marked repair_target; do not select an unrelated rule.")

        selected_findings = {
            issue_key: finding_context
        }

        # Put target rules first and tag them explicitly in the GPT payload.
        # The full specification is still included for context.
        target_id_set = set(target_rule_ids)
        gpt_rules_json = []
        for rule in rules_json:
            enriched = dict(rule)
            enriched["repair_target"] = enriched.get("id") in target_id_set
            if enriched["repair_target"]:
                gpt_rules_json.append(enriched)
        for rule in rules_json:
            if rule.get("id") not in target_id_set:
                enriched = dict(rule)
                enriched["repair_target"] = False
                gpt_rules_json.append(enriched)

        semantic_ops = operator_plan.get("llm", [])
        if not resolved_rules:
            semantic_ops = [op for op in semantic_ops if addition_scope and op == "new_rule_generation"]
            operator_plan["llm"] = semantic_ops
            operator_plan["deterministic"] = []
        operator_plan["target_resolution"] = resolution
        llm_patches = []
        gpt_warning = None

        seen_candidate_signatures = set()
        seen_verified_signatures = set()
        seen_failed_signatures = set()

        # -------------------------------
        # Multiple attempts
        # -------------------------------

        deterministic_attempt_limit = 1
        while attempts < deterministic_attempt_limit:
            attempts += 1

            start_generation = time.time()

            deterministic_patches = self.deterministic_engine.generate(
                issue_type=issue_key,
                selected_issue=selected_issue_value,
                rules=rules_json,
                operators=operator_plan.get("deterministic", []),
                diagnosis=diagnosis,
                sleec_text=sleec_text
            )

            generation_time += time.time() - start_generation

            for i, p in enumerate(deterministic_patches, start=1):
                p["patch_id"] = p.get("patch_id", f"d{i}")
                p["id"] = p.get("id", p["patch_id"])
                p["source"] = p.get("source", "deterministic")

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

                if self.is_noop_patch(normalized_patch):
                    failed_patch_count += 1
                    normalized_patch["verified"] = False
                    normalized_patch["failure_reason"] = "No-op patch: proposed rule is unchanged"
                    normalized_patch["attempt"] = attempts
                    failed_patches.append(normalized_patch)
                    print(
                        ">>> Skipping no-op deterministic patch:",
                        normalized_patch.get("patch_id", normalized_patch.get("id", "unknown"))
                    )
                    continue

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

                # Generic semantic validation for every use case.
                if source == "llm":
                    semantic_validation = self.semantic_validator.validate(
                        sleec_text=sleec_text,
                        issue={
                            "issue_type": issue_key,
                            "value": selected_issue_value
                        },
                        patch=normalized_patch,
                        existing_events=self.extract_defined_events(sleec_text),
                        existing_measures=self.extract_defined_measures(sleec_text),
                        existing_responses=self.extract_rule_actions(rules_json)
                    )

                    normalized_patch["semantic_validation"] = semantic_validation
                    normalized_patch["semantic_validation_passed"] = bool(
                        semantic_validation.get("valid")
                    )
                    normalized_patch["vocabulary_grounded"] = bool(
                        semantic_validation.get("vocabulary_grounding", {}).get("passed")
                    )
                    normalized_patch["diagnosis_aligned"] = bool(
                        semantic_validation.get("diagnosis_alignment", {}).get("passed")
                    )
                    normalized_patch["operator_valid"] = bool(
                        semantic_validation.get("operator_validation", {}).get("passed")
                    )
                    normalized_patch["temporal_alignment"] = bool(
                        semantic_validation.get("temporal_validation", {}).get("passed")
                    )

                    # Semantic validation is advisory for GPT patches.
                    # Every executable GPT candidate still proceeds to formal
                    # SLEEC verification. Semantic concerns are retained for
                    # philosopher/social-scientist review.
                    if not semantic_validation.get("valid"):
                        normalized_patch["semantic_review_status"] = "pass_with_review"
                        normalized_patch["semantic_warnings"] = (
                            semantic_validation.get("errors", [])
                            + semantic_validation.get("warnings", [])
                        )
                    else:
                        normalized_patch["semantic_review_status"] = "pass"
                        normalized_patch["semantic_warnings"] = (
                            semantic_validation.get("warnings", [])
                        )

                    normalized_patch["requires_social_scientist_review"] = True

                    print(
                        "SEMANTIC REVIEW STATUS:",
                        normalized_patch.get("semantic_review_status")
                    )
                    print("SEMANTIC VALID:", semantic_validation.get("valid"))
                    print("SEMANTIC ERRORS:", semantic_validation.get("errors", []))
                    print("SEMANTIC WARNINGS:", semantic_validation.get("warnings", []))

                if source == "deterministic":
                    verified = self.verify_deterministic_patch_iteratively(
                        original_sleec=sleec_text,
                        issue_key=issue_key,
                        selected_issue_value=selected_issue_value,
                        original_structured=original_structured,
                        patch=normalized_patch,
                        depth=0,
                        max_depth=3
                    )
                else:
                    verified = self.verify_llm_patch_once(
                        original_sleec=sleec_text,
                        issue_key=issue_key,
                        selected_issue_value=selected_issue_value,
                        original_structured=original_structured,
                        patch=normalized_patch
                    )

                validation_time += time.time() - start_validation

                if verified:
                    verified["attempt"] = attempts
                    verified_patches.append(verified)
                    seen_verified_signatures.add(patch_signature)
                else:
                    if patch_signature not in seen_failed_signatures:
                        failed_patch_count += 1
                        normalized_patch["verified"] = False
                        normalized_patch["attempt"] = attempts
                        failed_patches.append(normalized_patch)
                        seen_failed_signatures.add(patch_signature)

        # Always generate semantic GPT alternatives when semantic operators apply.
        # Deterministic success must not suppress GPT candidates because all verified
        # alternatives are ranked together for philosopher review.
        if semantic_ops:
            start_generation = time.time()

            description = get_use_case_description(use_case)

            print("\n========== USE CASE CONTEXT ==========")
            print("Use case:", use_case)
            print("Description:", description)
            print("======================================\n")

            print(">>> Calling GPT with operators:", semantic_ops)

            try:
                llm_patches = self.gpt_patch_engine.generate_all_patches(
                    rules=gpt_rules_json,
                    structured_findings=selected_findings,
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

            materialized = []
            for i, proposal in enumerate(llm_patches, start=1):
                try:
                    candidate = materialize_semantic_edit(sleec_text, proposal, target_rule_ids, addition_scope)
                    candidate["target_resolution"] = copy.deepcopy(resolution)
                    materialized.append(candidate)
                except (ValueError, TypeError, KeyError, AttributeError) as exc:
                    rejected = dict(proposal) if isinstance(proposal, dict) else {"raw_proposal": proposal}
                    rejected.update(patch_id=f"g_rejected_{i}", source="llm", verified=False,
                                    candidate_status="rejected", failure_reason=f"Invalid structured edit: {exc}",
                                    diagnosis=copy.deepcopy(diagnosis))
                    llm_candidates.append(rejected)
                    failed_patches.append(rejected)
                    failed_patch_count += 1
                    self.store.save_patch_candidate({"run_id": run_id, "use_case": use_case,
                        "issue_id": issue.get("id", ""), "issue_type": issue_key, "attempt": attempts,
                        "candidate_signature": f"rejected_{i}", "candidate_status": "rejected", "patch": rejected})
            llm_patches = materialized
            for i, p in enumerate(llm_patches, start=1):
                p["diagnosis"] = copy.deepcopy(diagnosis)
                p["patch_id"] = f"g{i}"
                p["id"] = f"g{i}"
                p["source"] = p.get("source", "llm")

                # Ground missing metadata in the diagnosed target rule. Do not
                # silently retarget a generated rule; retain a warning when GPT
                # names a different rule so verification/review remains honest.
                if len(gpt_target_rules) == 1 and not p.get("source_requirement_id"):
                    target_rule = gpt_target_rules[0]
                    expected_id = str(target_rule.get("id", "")).strip()
                    expected_text = self.deterministic_engine.rule_to_text(target_rule)
                    generated_target = str(p.get("target_rule_id", "")).strip()

                    if not generated_target:
                        p["target_rule_id"] = expected_id
                    elif generated_target != expected_id:
                        p["target_mismatch_warning"] = (
                            f"GPT selected {generated_target}; diagnosed target is {expected_id}."
                        )

                    if not str(p.get("original_rule", "")).strip():
                        p["original_rule"] = expected_text

                    p["diagnosed_target_rule_id"] = expected_id
                    p["diagnosed_target_rule"] = expected_text

                elif len(gpt_target_rules) > 1 and not p.get("source_requirement_id"):
                    p["diagnosed_target_rule_ids"] = target_rule_ids
                    p["diagnosed_target_rules"] = target_rule_texts

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

            llm_candidates.extend(llm_patches)
            generation_time += time.time() - start_generation

            for patch in llm_patches:
                normalized_patch = self.normalize_patch(patch, sleec_text)

                if self.is_noop_patch(normalized_patch):
                    failed_patch_count += 1
                    normalized_patch["verified"] = False
                    normalized_patch["failure_reason"] = "No-op patch: proposed rule is unchanged"
                    normalized_patch["attempt"] = attempts
                    failed_patches.append(normalized_patch)
                    print(
                        ">>> Skipping no-op GPT patch:",
                        normalized_patch.get("patch_id", normalized_patch.get("id", "unknown"))
                    )
                    continue

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

                semantic_validation = self.semantic_validator.validate(
                    sleec_text=sleec_text,
                    issue={
                        "issue_type": issue_key,
                        "value": selected_issue_value
                    },
                    patch=normalized_patch,
                    existing_events=self.extract_defined_events(sleec_text),
                    existing_measures=self.extract_defined_measures(sleec_text),
                    existing_responses=self.extract_rule_actions(rules_json)
                )
                normalized_patch["semantic_validation"] = semantic_validation
                normalized_patch["semantic_validation_passed"] = bool(
                    semantic_validation.get("valid")
                )
                normalized_patch["semantic_review_status"] = "pending"
                normalized_patch["semantic_warnings"] = (
                    semantic_validation.get("errors", [])
                    + semantic_validation.get("warnings", [])
                )
                normalized_patch["requires_social_scientist_review"] = True
                normalized_patch["requires_philosopher_review"] = True

                if not semantic_validation.get("valid"):
                    normalized_patch.update(verified=False, failure_reason="Structured semantic edit validation failed: " + "; ".join(semantic_validation.get("errors", [])))
                    failed_patches.append(normalized_patch)
                    failed_patch_count += 1
                    continue

                verified = self.verify_llm_patch_once(
                    original_sleec=sleec_text,
                    issue_key=issue_key,
                    selected_issue_value=selected_issue_value,
                    original_structured=original_structured,
                    patch=normalized_patch
                )
                validation_time += time.time() - start_validation

                if verified:
                    verified["attempt"] = attempts
                    verified_patches.append(verified)
                    seen_verified_signatures.add(patch_signature)
                elif patch_signature not in seen_failed_signatures:
                    failed_patch_count += 1
                    normalized_patch["verified"] = False
                    normalized_patch["attempt"] = attempts
                    failed_patches.append(normalized_patch)
                    seen_failed_signatures.add(patch_signature)

        total_time = time.time() - start_total
        outcomes = {}
        for candidate in failed_patches + verified_patches:
            update_candidate_status(candidate)
            outcomes[candidate.get("patch_id")] = candidate
        for candidate in deterministic_candidates + llm_candidates:
            outcome = outcomes.get(candidate.get("patch_id"))
            if outcome:
                for key in ("candidate_status", "syntax_valid", "formally_verified", "semantic_review_status", "failure_reason", "requires_social_scientist_review"):
                    if key in outcome:
                        candidate[key] = outcome[key]
            else:
                update_candidate_status(candidate)

        # Section C: rank only patches that already passed formal verification.
        # Structural/logical metrics are deterministic.
        # Semantic clarity/interpretability receive the WFI and declared vocabulary.
        affected_rule_ids = diagnosis.get("affected_rule_ids", self.extract_issue_rule_ids(selected_issue_value))
        affected_rules = [
            rule for rule in rules_json
            if str(rule.get("id", "")).lower()
            in {rid.lower() for rid in affected_rule_ids}
        ]

        ranking_context = {
            "use_case": use_case,
            "issue_type": issue_key,
            "selected_issue": selected_issue_value,
            "diagnosis_context": diagnosis or selected_issue_value,
            "affected_rules": affected_rules,
            "system_description": get_use_case_description(use_case),
            "existing_events": self.extract_defined_events(sleec_text),
            "existing_measures": self.extract_defined_measures(sleec_text),
            "existing_responses": self.extract_rule_actions(rules_json)
        }
        self._ranking_context = ranking_context
        for candidate in verified_patches:
            candidate["ranking_context"] = copy.deepcopy(ranking_context)

        verified_patches = self.patch_ranker.rank(verified_patches)

        output_file = self.build_final_sleecpatch_file(
            use_case,
            sleec_text,
            verified_patches,
            original_structured=original_structured,
            issue_key=issue_key,
            selected_issue_value=selected_issue_value
        )

        log = {
            "run_id": run_id,
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
        log["repair_notice"] = (resolution["reason"] if not resolution["rule_ids"] and not addition_scope else
            "No supported repair was generated for this requirement structure." if not deterministic_candidates and not llm_candidates else "")

        self.store.save_pipeline_run({
            **log,
            "input_sha256": hashlib.sha256(sleec_text.encode("utf-8")).hexdigest(),
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

                "verified": True,

                "expert_similarity": 0,
                "expert_match": False,
                "requires_social_scientist_review": (
                    bool(patch.get("requires_social_scientist_review", True))
                )
            })

        return {
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
        }

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
        selected_issues = []

        for result in all_wfi_results:
            verified = [patch for patch in result.get("verified_patches", []) if formally_verified(patch)]

            if not verified:
                continue

            ranked = sorted(
                verified,
                key=lambda p: p.get("rank", 999)
            )

            best_patch = ranked[0]
            selected_patches.append(best_patch)
            selected_issues.append(result.get("selected_issue", {}))

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

        if cumulative["passed"]:
            before = self.run_detector_cached(original_sleec)["structured"]
            after = validation_gate["analysis"]["structured"]
            if not selected_patches or any(not isinstance(issue, dict) or not self.target_issue_fixed(
                    issue.get("issue_type", ""), issue.get("value", ""), before, after) for issue in selected_issues):
                cumulative.update(passed=False, failure_reason="The combined export has no verified selection or leaves a selected issue unresolved.")

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
