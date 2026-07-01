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

    def tokens(self, text):
        return set(re.findall(r"[a-zA-Z_][a-zA-Z0-9_]*", self.normalize(text)))

    def token_overlap(self, left, right):
        left_tokens = self.tokens(left)
        right_tokens = self.tokens(right)

        if not left_tokens:
            return 0

        return len(left_tokens & right_tokens) / len(left_tokens)

    def match_result(self, matched, match_type, confidence, reason):
        return {
            "matched": matched,
            "match_type": match_type,
            "confidence": round(confidence, 3),
            "reason": reason
        }

    def operation_strategy(self, operation):
        mapping = {
            "rule_removal": "rule_removal",
            "delete": "rule_removal",
            "remove": "rule_removal",
            "new_rule_generation": "rule_addition",
            "add_rule": "rule_addition",
            "trigger_refinement": "rule_refinement",
            "trigger_strengthening": "rule_refinement",
            "defeater_propagation": "rule_refinement",
            "rule_decomposition": "rule_refinement",
            "defeater_introduction": "defeater_modification",
            "add_defeater": "defeater_modification",
            "purpose_defeater": "defeater_modification",
            "capability_refinement": "capability_refinement",
            "action_refinement": "response_modification",
            "replace_action": "response_modification",
            "event_specialization": "capability_refinement",
            "measure_specialization": "capability_refinement"
        }

        return mapping.get(str(operation), "other")

    def patch_matches_corrected(self, patch, corrected_rules):
        return self.match_patch_to_corrected(patch, corrected_rules)["matched"]

    def match_patch_to_corrected(self, patch, corrected_rules):
        operation = patch.get("operation", "")
        target_rule_id = patch.get("target_rule_id", "")
        proposed_rule = patch.get("proposed_rule", "")
        original_rule = patch.get("original_rule", "")

        corrected_by_id = {r["id"]: r for r in corrected_rules}
        corrected_rule = corrected_by_id.get(target_rule_id)

        corrected_text = self.normalize(
            "\n".join(r.get("raw", "") for r in corrected_rules)
        )

        proposed_norm = self.normalize(proposed_rule)

        # 1. Exact/near full proposed rule exists
        if proposed_norm and proposed_norm in corrected_text:
            return self.match_result(
                True,
                "exact_rule",
                1.0,
                "The proposed rule text appears in the stakeholder-corrected specification."
            )

        # 2. Rule removal
        if operation in ["rule_removal", "delete", "remove"]:
            if target_rule_id and target_rule_id not in corrected_by_id:
                return self.match_result(
                    True,
                    "rule_removed",
                    1.0,
                    "The generated patch removes a rule that is absent from the corrected specification."
                )

            return self.match_result(
                False,
                "no_match",
                0,
                "The patch removes a rule that still appears in the corrected specification."
            )

        # If target rule does not exist, no more structural comparison possible
        if not corrected_rule:
            overlap = self.token_overlap(proposed_rule, corrected_text)

            if overlap >= 0.65:
                return self.match_result(
                    True,
                    "soft_overlap",
                    overlap,
                    "The target rule is absent, but the proposed patch substantially overlaps with the corrected specification."
                )

            return self.match_result(
                False,
                "no_target_rule",
                overlap,
                "The target rule is not present in the corrected specification and no strong patch overlap was found."
            )

        corrected_raw = self.normalize(corrected_rule.get("raw", ""))
        corrected_condition = self.normalize(corrected_rule.get("condition", ""))
        corrected_action = self.normalize(corrected_rule.get("action", ""))
        corrected_defeaters = self.normalize(" ".join(corrected_rule.get("defeaters", [])))

        proposed_parsed = self.parser.parse_rule(proposed_rule)

        if not proposed_parsed:
            overlap = self.token_overlap(proposed_rule, corrected_raw)

            if overlap >= 0.65:
                return self.match_result(
                    True,
                    "soft_overlap",
                    overlap,
                    "The proposed patch could not be parsed, but its text overlaps strongly with the corrected target rule."
                )

            return self.match_result(
                False,
                "unparseable_patch",
                overlap,
                "The proposed rule could not be parsed for structural comparison."
            )

        proposed_condition = self.normalize(proposed_parsed.get("condition", ""))
        proposed_action = self.normalize(proposed_parsed.get("action", ""))
        proposed_defeaters = self.normalize(" ".join(proposed_parsed.get("defeaters", [])))

        # 3. Defeater introduction:
        # match if proposed defeater appears in corrected rule
        if operation in ["defeater_introduction", "add_defeater", "purpose_defeater"]:
            if proposed_defeaters and proposed_defeaters in corrected_raw:
                return self.match_result(
                    True,
                    "same_defeater",
                    0.9,
                    "The generated patch introduces a defeater that appears in the corrected target rule."
                )

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
                return self.match_result(
                    True,
                    "same_trigger_refinement",
                    0.85,
                    "The generated patch uses trigger/condition terms that are present in the corrected target rule."
                )

        # 5. Capability/action refinement:
        # match if proposed action appears in corrected target rule/action
        if operation in ["capability_refinement", "action_refinement", "replace_action"]:
            if proposed_action and proposed_action in corrected_raw:
                return self.match_result(
                    True,
                    "same_response",
                    0.85,
                    "The generated patch uses a response/action found in the corrected target rule."
                )

        # 6. New rule generation:
        # match if proposed action and important condition tokens appear somewhere in corrected file
        if operation in ["new_rule_generation", "add_rule"]:
            overlap = self.token_overlap(proposed_rule, corrected_text)

            if overlap >= 0.65:
                return self.match_result(
                    True,
                    "soft_overlap",
                    overlap,
                    "The generated new rule substantially overlaps with the corrected specification."
                )

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
                return self.match_result(
                    True,
                    "specialized_term_present",
                    len(hits) / len(proposed_tokens),
                    "The generated specialized event/measure terms appear in the corrected specification."
                )

        if proposed_action and proposed_action == corrected_action:
            return self.match_result(
                True,
                "same_response",
                0.75,
                "The generated patch preserves or selects the same response as the corrected target rule."
            )

        corrected_strategy = self.infer_corrected_strategy(
            original_rule,
            corrected_rule
        )
        patch_strategy = self.operation_strategy(operation)

        if corrected_strategy != "other" and corrected_strategy == patch_strategy:
            return self.match_result(
                True,
                "same_strategy",
                0.6,
                f"The generated patch and corrected rule both use the '{patch_strategy}' strategy."
            )

        overlap = self.token_overlap(proposed_rule, corrected_raw or corrected_text)

        if overlap >= 0.7:
            return self.match_result(
                True,
                "soft_overlap",
                overlap,
                "The proposed patch has high token overlap with the corrected target rule."
            )

        return self.match_result(
            False,
            "no_match",
            overlap,
            "No exact, structural, strategy, or high-overlap correspondence was found."
        )

    def infer_corrected_strategy(self, original_rule, corrected_rule):
        original = self.parser.parse_rule(original_rule) if original_rule else None

        if not original or not corrected_rule:
            return "other"

        original_condition = self.normalize(original.get("condition", ""))
        corrected_condition = self.normalize(corrected_rule.get("condition", ""))
        original_action = self.normalize(original.get("action", ""))
        corrected_action = self.normalize(corrected_rule.get("action", ""))
        original_defeaters = self.normalize(" ".join(original.get("defeaters", [])))
        corrected_defeaters = self.normalize(" ".join(corrected_rule.get("defeaters", [])))

        if corrected_defeaters != original_defeaters:
            return "defeater_modification"

        if corrected_action != original_action:
            return "response_modification"

        if corrected_condition != original_condition:
            return "rule_refinement"

        return "other"

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

            match = self.match_patch_to_corrected(
                patch,
                corrected_rules
            )
            matched = match["matched"]

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
                "match_type": match["match_type"],
                "match_confidence": match["confidence"],
                "match_reason": match["reason"],
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
