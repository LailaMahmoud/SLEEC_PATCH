import copy
import hashlib
from collections import OrderedDict
import re
import time
import os
import threading
import uuid
from services.sleec_detection_engine import SLEECDetectionEngine
from services.gpt_patch_engine import GPTPatchEngine
from services.sleec_patch_evaluation_store import SLEECPatchEvaluationStore
from services.repair_operator_selector import RepairOperatorSelector
from services.deterministic_repair_engine import DeterministicRepairEngine
from services.patch_ranker import PatchRanker


class SLEECPatchWorkbenchEngine:

    def __init__(self):
        self.detector = SLEECDetectionEngine()
        self.gpt_patch_engine = GPTPatchEngine()
        self.store = SLEECPatchEvaluationStore()

        self.operator_selector = RepairOperatorSelector()
        self.deterministic_engine = DeterministicRepairEngine()
        self.patch_ranker = PatchRanker()
        self.detector_cache = OrderedDict()
        self.detector_cache_lock = threading.RLock()
        self.detector_cache_max_entries = int(
            os.environ.get("SLEEC_DETECTOR_CACHE_SIZE", "64")
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

        with self.detector_cache_lock:
            self.detector_cache[cache_key] = copy.deepcopy(result)

            while len(self.detector_cache) > self.detector_cache_max_entries:
                self.detector_cache.popitem(last=False)

        return result

    def diagnose(self, sleec_text):
        result = self.run_detector_cached(sleec_text)

        print("\n========== DETECTOR OUTPUT ==========")
        print(result)
        print("====================================\n")
        structured = result.get("structured", {})
        detections = result.get("detections", {})

        issues = []

        original_rules_by_type = structured.get("original_rules_by_type", {})

        for issue_type, items in structured.items():

            if issue_type == "original_rules_by_type":
                continue

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
                    "source": "sleec"
                })



        if not issues:
            fallback = self.fallback_wfi_detection(sleec_text)

            for issue_type, items in fallback.items():
                for index, item in enumerate(items, start=1):
                    issues.append({
                        "id": f"{issue_type}_{index}",
                        "issue_type": issue_type,
                        "value": item,
                        "source": "fallback"
                    })

            structured.update(fallback)

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
        text = f'{rule["id"]} when {rule["condition"]} then {rule["action"]}'

        if rule.get("defeater"):
            text += f' unless {{{rule["defeater"]}}}'


        return text



    def sleec_text_to_rules_json(self, sleec_text):
        rules = []
        inside_rules = False
        current = ""

        for line in sleec_text.splitlines():
            line = line.strip()

            if not line or line.startswith("//"):
                continue

            if line.lower() == "rule_start":
                inside_rules = True
                continue

            if line.lower() == "rule_end":
                inside_rules = False
                if current:
                    rules.append(current.strip())
                break

            if not inside_rules:
                continue

            if re.match(r"^(r\d+|rule\d+|c\d+)(?:_\d+)?\s+when\s+", line, re.IGNORECASE):
                if current:
                    rules.append(current.strip())
                current = line
            else:
                current += " " + line

        parsed_rules = []

        pattern = re.compile(
            r"^((?:r\d+|rule\d+|c\d+)(?:_\d+)?)\s+when\s+(.+?)\s+then\s+(.+?)(?:\s+unless\s+(.+))?$",
            re.IGNORECASE
        )

        for text in rules:
            match = pattern.search(text)

            if match:
                parsed_rules.append({
                    "id": match.group(1).strip(),
                    "condition": match.group(2).strip(),
                    "action": match.group(3).strip(),
                    "defeater": match.group(4).strip() if match.group(4) else "",
                    "raw": text
                })

        print("RULES PARSED:", len(parsed_rules))

        return parsed_rules

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
            "trigger_strengthening": "Add trigger condition",
            "rule_merging": "Merge overlapping rules",
            "rule_decomposition": "Split rule into cases",
            "rule_removal": "Remove redundant rule",
            "event_specialization": "Specialize event",
            "measure_specialization": "Specialize measure",
            "capability_refinement": "Refine capability",
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
            "target_rule_id": target_rule_id,
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
        operation = patch.get("operation", "")
        original_rule = patch.get("original_rule", "")
        proposed_rule = patch.get("proposed_rule", "")
        target_rule_id = patch.get("target_rule_id", "")
        rule_ids = patch.get("rule_ids", [])

        if not target_rule_id and rule_ids:
            target_rule_id = rule_ids[0]

        delete_operations = [
            "delete",
            "delete_rule",
            "delete_redundant_rule",
            "rule_removal"
        ]

        replace_operations = [
            "edit",
            "edit_rule",
            "add_defeater",
            "defeater_introduction",
            "defeater_propagation",
            "purpose_defeater",
            "trigger_refinement",
            "trigger_strengthening",
            "rule_merging",
            "rule_decomposition",
            "refine_condition",
            "specialize_condition",
            "add_contextual_constraint",
            "replace_action",
            "refine_vague_predicate",
            "refine_action",
            "capability_refinement",
            "event_specialization",
            "measure_specialization"
        ]

        add_operations = [
            "add",
            "add_rule",
            "new_rule_generation"
        ]

        if operation == "event_specialization":
            new_event = patch.get("new_event") or patch.get("missing_element", "")

            if new_event and f"event {new_event}" not in sleec_text:
                sleec_text = sleec_text.replace(
                    "def_end",
                    f"event {new_event}\ndef_end"
                )

        if operation == "measure_specialization":
            new_measure = patch.get("new_measure") or patch.get("missing_element", "")

            if new_measure and f"measure {new_measure}" not in sleec_text:
                sleec_text = sleec_text.replace(
                    "def_end",
                    f"measure {new_measure}:boolean\ndef_end"
                )

        if operation == "capability_refinement":
            new_capability = (
                patch.get("new_capability")
                or patch.get("missing_element")
                or ""
            )

            if new_capability and f"event {new_capability}" not in sleec_text:
                sleec_text = sleec_text.replace(
                    "def_end",
                    f"event {new_capability}\ndef_end"
                )

        if operation in delete_operations:
            ids_to_delete = set(rule_ids)

            if target_rule_id:
                ids_to_delete.add(target_rule_id)

            if not ids_to_delete and original_rule:
                return sleec_text.replace(original_rule, "")

            return self.delete_rules_by_id(sleec_text, ids_to_delete)

        if operation in replace_operations:
            if target_rule_id and proposed_rule:
                patched = self.replace_rule_by_id(
                    sleec_text,
                    target_rule_id,
                    proposed_rule
                )

                if patched != sleec_text:
                    return patched

        if operation in replace_operations:
            if original_rule and proposed_rule and original_rule in sleec_text:
                return sleec_text.replace(
                    original_rule,
                    self.ensure_rule_id(original_rule, proposed_rule)
                )

        if operation in add_operations:
            new_rule = patch.get("new_rule") or proposed_rule

            if new_rule:
                return sleec_text.replace(
                    "rule_end",
                    f"{new_rule}\nrule_end"
                )

        return sleec_text

    def ensure_rule_id(self, original_rule, proposed_rule):
        proposed_rule = proposed_rule.strip()

        if re.match(r"^(r\d+|rule\d+|c\d+)(?:_\d+)?\s+when\s+", proposed_rule, re.IGNORECASE):
            return proposed_rule

        match = re.match(r"^((?:r\d+|rule\d+|c\d+)(?:_\d+)?)\s+", original_rule.strip(), re.IGNORECASE)

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
            r"^(?:Rule|R|r)\d+(?:_\d+)?\s+when\b",
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
        selected_fingerprint = self.issue_fingerprint(issue_type, selected_issue_value)
        after_records = self.issue_records(new_structured)

        if selected_fingerprint in after_records:
            return False

        selected_rule_ids = set(self.extract_issue_rule_ids(selected_issue_value))

        if selected_rule_ids:
            for issue in new_structured.get(issue_type, []):
                after_rule_ids = set(self.extract_issue_rule_ids(issue))

                if selected_rule_ids.issubset(after_rule_ids):
                    return False

        before = original_structured.get(issue_type, [])
        after = new_structured.get(issue_type, [])

        if len(after) < len(before):
            return True

        selected_text = str(selected_issue_value).strip()
        after_text = "\n".join(str(x) for x in after)

        return selected_text not in after_text

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

    def issue_fingerprint(self, issue_type, issue):
        normalized = self.normalize_issue_text(issue)
        digest = hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:16]
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
            for issue in structured.get(issue_type, []):
                fingerprint = self.issue_fingerprint(issue_type, issue)
                records[fingerprint] = {
                    "fingerprint": fingerprint,
                    "issue_type": issue_type,
                    "summary": self.issue_summary(issue),
                    "rule_ids": self.extract_issue_rule_ids(issue)
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


    def build_final_sleecpatch_file(self, use_case, original_sleec, verified_patches):
        final_sleec = original_sleec

        for patch in verified_patches:
            final_sleec = self.apply_patch_to_text(final_sleec, patch)

        folder = os.path.join("results", use_case)
        os.makedirs(folder, exist_ok=True)

        path = os.path.join(folder, f"{use_case}_SLEECPATCH.sleec")

        with open(path, "w", encoding="utf-8") as f:
            f.write(final_sleec)

        return {
            "use_case": use_case,
            "path": path,
            "sleec_text": final_sleec
        }

    def verify_candidate_patch(self, original_sleec, issue, patch):
        patched_sleec = self.apply_patch_to_text(original_sleec, patch)

        original_analysis = self.run_detector_cached(original_sleec)
        original_structured = original_analysis.get("structured", {})
        new_analysis = self.diagnose(patched_sleec)
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
        patched_sleec = self.apply_patch_to_text(original_sleec, patch)

        new_analysis = self.run_detector_cached(patched_sleec)
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
        patched_sleec = self.apply_patch_to_text(original_sleec, patch)

        new_analysis = self.run_detector_cached(patched_sleec)
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
                    related_issue["issue_type"]
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
        operator_plan = self.operator_selector.select(issue_key)

        print("\n========== REPAIR OPERATOR SELECTION ==========")
        print("Issue Type:", issue_key)
        print("Deterministic operators:", operator_plan.get("deterministic", []))
        print("LLM operators:", operator_plan.get("llm", []))
        print("==============================================\n")

        selected_findings = {
            issue_key: [selected_issue_value]
        }

        # -------------------------------
        # GPT is called ONCE per issue
        # -------------------------------

        semantic_ops = operator_plan.get("llm", [])
        llm_patches = []

        if semantic_ops:
            start_generation = time.time()

            print(">>> Calling GPT with operators:", semantic_ops)

            llm_patches = self.gpt_patch_engine.generate_all_patches(
                rules=rules_json,
                structured_findings=selected_findings,
                repair_operators=semantic_ops
            )

            for i, p in enumerate(llm_patches, start=1):
                p["patch_id"] = f"g{i}"
                p["id"] = f"g{i}"
                p["source"] = p.get("source", "llm")
                normalized_preview = self.normalize_patch(p, sleec_text)
                metrics = self.patch_metrics(normalized_preview)
                result_id = self.store.save_result({
                    "use_case": use_case,
                    "issue_id": issue.get("id", ""),
                    "issue_type": issue_key,
                    "selected_issue": selected_issue_value,

                    "attempts": 0,
                    "failed_patch_count": 0,
                    "verified_patch_count": 0,

                    "generation_time_seconds": 0,
                    "validation_time_seconds": 0,
                    "total_time_seconds": 0,

                    "patch_id": normalized_preview.get("patch_id", ""),
                    "operation": normalized_preview.get("operation", ""),
                    "source": "llm",

                    "target_rule_id": normalized_preview.get("target_rule_id", ""),
                    "original_rule": normalized_preview.get("original_rule", ""),
                    "proposed_rule": normalized_preview.get("proposed_rule", ""),
                    "natural_language_explanation": normalized_preview.get(
                        "natural_language_explanation",
                        ""
                    ),
                    "patched_sleec": "",

                    "rules_modified": metrics["rules_modified"],
                    "rules_added": metrics["rules_added"],
                    "rules_deleted": metrics["rules_deleted"],
                    "defeaters_added": metrics["defeaters_added"],
                    "conditions_refined": metrics["conditions_refined"],
                    "actions_refined": metrics["actions_refined"],
                    "capabilities_refined": metrics["capabilities_refined"],

                    "verified": False,
                    "expert_similarity": 0,
                    "expert_match": False,
                    "requires_social_scientist_review": True
                })
                p["_result_id"] = result_id
                p["result_id"] = result_id

                self.store.save_patch_candidate({
                    "run_id": run_id,
                    "use_case": use_case,
                    "issue_id": issue.get("id", ""),
                    "issue_type": issue_key,
                    "attempt": 0,
                    "candidate_signature": self.patch_signature_text(p),
                    "patch": p
                })

            llm_candidates.extend(llm_patches)

            generation_time += time.time() - start_generation

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
                issue_type=issue_key,
                selected_issue=selected_issue_value,
                rules=rules_json,
                operators=operator_plan.get("deterministic", [])
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

            patches = deterministic_patches + llm_patches

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

        total_time = time.time() - start_total

        verified_patches = self.patch_ranker.rank(verified_patches)

        output_file = self.build_final_sleecpatch_file(
            use_case,
            sleec_text,
            verified_patches
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

        self.store.save_pipeline_run({
            **log,
            "selected_issue": selected_issue_value,
            "repair_operators": operator_plan,
            "original_issue_count": self.count_issues(original_structured),
            "original_structured": original_structured,
            "generated_file_path": output_file.get("path", "")
        })

        for patch in failed_patches + verified_patches:
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
                "requires_social_scientist_review": False
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
            "log": log
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

        folder = os.path.join("results", use_case)
        os.makedirs(folder, exist_ok=True)

        output_path = os.path.join(
            folder,
            f"{use_case}_SLEECPATCH.sleec"
        )

        with open(output_path, "w", encoding="utf-8") as f:
            f.write(final_sleec)

        return {
            "use_case": use_case,
            "output_path": output_path,
            "selected_patches": selected_patches,
            "final_sleec": final_sleec
        }
