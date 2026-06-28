import re
from collections import defaultdict


class EvaluationAPatchMatch:

    def __init__(self, parser):
        self.parser = parser

    def normalize(self, text):
        text = str(text or "").lower()
        text = re.sub(r"\s+", " ", text)
        text = text.replace("{", "").replace("}", "")
        return text.strip()

    def patch_matches_corrected(self, patch, corrected_rules):
        operation = patch.get("operation", "")
        target_rule_id = patch.get("target_rule_id", "")
        proposed_rule = patch.get("proposed_rule", "")

        corrected_by_id = {
            r["id"]: r for r in corrected_rules
        }

        corrected_text = self.normalize(
            "\n".join(r.get("raw", "") for r in corrected_rules)
        )

        # 1. rule removal: target rule should not exist in corrected
        if operation in ["rule_removal", "delete", "remove"]:
            return target_rule_id not in corrected_by_id

        # 2. proposed rule exists in corrected
        if proposed_rule:
            return self.normalize(proposed_rule) in corrected_text

        # 3. defeater added exists in corrected target rule
        if operation in ["defeater_introduction", "add_defeater"]:
            corrected_rule = corrected_by_id.get(target_rule_id)
            if corrected_rule:
                patch_defeaters = patch.get("defeaters", [])
                rule_text = self.normalize(corrected_rule.get("raw", ""))

                for d in patch_defeaters:
                    if self.normalize(d) in rule_text:
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