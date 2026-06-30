import re
from collections import defaultdict
from services.evaluation_metrics import EvaluationMetrics



class EvaluationAPatchMatch:

    def __init__(self, parser):
        self.parser = parser
        self.metrics = EvaluationMetrics()

    def normalize(self, text):
        text = str(text or "").lower()
        text = re.sub(r"\s+", " ", text)
        text = text.replace("{", "").replace("}", "")
        return text.strip()

    def patch_matches_corrected(self, patch, corrected_rules):
        operation = patch.get("operation", "")
        target_rule_id = patch.get("target_rule_id", "")
        proposed_rule = patch.get("proposed_rule", "")

        corrected_by_id = {r["id"]: r for r in corrected_rules}
        corrected_rule = corrected_by_id.get(target_rule_id)

        corrected_text = self.normalize(
            "\n".join(r.get("raw", "") for r in corrected_rules)
        )

        proposed_norm = self.normalize(proposed_rule)

        # 1. Exact/near full proposed rule exists
        if proposed_norm and proposed_norm in corrected_text:
            return True

        # 2. Rule removal
        if operation in ["rule_removal", "delete", "remove"]:
            return target_rule_id not in corrected_by_id

        # If target rule does not exist, no more structural comparison possible
        if not corrected_rule:
            return False

        corrected_raw = self.normalize(corrected_rule.get("raw", ""))
        corrected_condition = self.normalize(corrected_rule.get("condition", ""))
        corrected_action = self.normalize(corrected_rule.get("action", ""))
        corrected_defeaters = self.normalize(" ".join(corrected_rule.get("defeaters", [])))

        proposed_parsed = self.parser.parse_rule(proposed_rule)

        if not proposed_parsed:
            return False

        proposed_condition = self.normalize(proposed_parsed.get("condition", ""))
        proposed_action = self.normalize(proposed_parsed.get("action", ""))
        proposed_defeaters = self.normalize(" ".join(proposed_parsed.get("defeaters", [])))

        # 3. Defeater introduction:
        # match if proposed defeater appears in corrected rule
        if operation in ["defeater_introduction", "add_defeater", "purpose_defeater"]:
            if proposed_defeaters and proposed_defeaters in corrected_raw:
                return True

        # 4. Trigger/condition strengthening:
        # match if proposed added condition appears in corrected condition
        if operation in [
            "trigger_strengthening",
            "trigger_refinement",
            "defeater_propagation",
            "rule_decomposition",
            "constraint_added",
            "condition_refinement"
        ]:
            proposed_parts = set(proposed_condition.split())
            corrected_parts = set(corrected_condition.split())

            if proposed_parts and proposed_parts.issubset(corrected_parts):
                return True

        # 5. Capability/action refinement:
        # match if proposed action appears in corrected target rule/action
        if operation in ["capability_refinement", "action_refinement"]:
            if proposed_action and proposed_action in corrected_raw:
                return True

        # 6. New rule generation:
        # match if proposed action and important condition tokens appear somewhere in corrected file
        if operation in ["new_rule_generation", "add_rule"]:
            proposed_tokens = set(proposed_norm.split())
            corrected_tokens = set(corrected_text.split())

            common = proposed_tokens & corrected_tokens

            if len(proposed_tokens) > 0 and len(common) / len(proposed_tokens) >= 0.65:
                return True

        # 7. Event/measure specialization:
        # match if new specialized term appears in corrected file
        if operation in ["event_specialization", "measure_specialization"]:
            proposed_tokens = [
                t for t in proposed_norm.split()
                if len(t) > 4
            ]

            hits = [
                t for t in proposed_tokens
                if t in corrected_text
            ]

            if len(proposed_tokens) > 0 and len(hits) / len(proposed_tokens) >= 0.5:
                return True

        return False

    def evaluate_use_case(self, use_case, corrected_path, generated_patches):
        corrected = self.parser.parse_file(corrected_path)
        corrected_rules = corrected["rules"]

        total_patches = 0
        matching_patches = 0

        wfi_map = defaultdict(list)
        by_operation = defaultdict(lambda: {
            "generated": 0,
            "matched": 0,
            "match_rate": 0
        })

        patch_rows = []

        for patch in generated_patches:
            total_patches += 1

            issue_id = patch.get("issue_id", "")
            operation = patch.get("operation", "unknown")

            matched = self.patch_matches_corrected(
                patch,
                corrected_rules
            )

            if matched:
                matching_patches += 1

            wfi_map[issue_id].append(matched)

            by_operation[operation]["generated"] += 1
            if matched:
                by_operation[operation]["matched"] += 1

            patch_rows.append({
                "use_case": use_case,
                "issue_id": issue_id,
                "patch_id": patch.get("patch_id", ""),
                "operation": operation,
                "target_rule_id": patch.get("target_rule_id", ""),
                "matched_corrected": matched,
                "proposed_rule": patch.get("proposed_rule", "")
            })

        total_wfis = len(wfi_map)
        wfis_with_match = sum(
            1 for matches in wfi_map.values()
            if any(matches)
        )

        for op, values in by_operation.items():
            generated = values["generated"]
            matched = values["matched"]

            values["match_rate"] = round(
                matched / generated,
                3
            ) if generated else 0

        return {
            "use_case": use_case,
            "total_wfis": total_wfis,
            "wfis_with_matching_patch": wfis_with_match,
            "wfi_match_rate": round(
                wfis_with_match / total_wfis,
                3
            ) if total_wfis else 0,
            "total_patches": total_patches,
            "matching_patches": matching_patches,
            "patch_match_rate": round(
                matching_patches / total_patches,
                3
            ) if total_patches else 0,
            "by_operation": dict(by_operation),
            "patch_rows": patch_rows
        }
