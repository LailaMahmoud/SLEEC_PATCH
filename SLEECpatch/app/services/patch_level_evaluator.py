import re
from collections import defaultdict


class PatchLevelEvaluator:
    """
    Evaluation A:
    Checks whether generated SLEEC-PATCH repairs correspond to
    the manually corrected SLEEC specification.
    """

    def __init__(self, parser=None):
        self.parser = parser

    def evaluate(self, use_case, patches, corrected_sleec_text):
        corrected_norm = self.normalize(corrected_sleec_text)

        patch_rows = []
        by_operation = defaultdict(lambda: {
            "generated": 0,
            "matched": 0,
            "match_rate": 0
        })

        wfis = set()
        wfis_with_match = set()
        matching_patches = 0

        for patch in patches:
            issue_id = patch.get("issue_id", "") or patch.get("selected_issue", "")
            operation = patch.get("operation", "unknown")
            proposed_rule = patch.get("proposed_rule", "")

            wfis.add(issue_id)
            by_operation[operation]["generated"] += 1

            matched = self.patch_matches_corrected(
                patch=patch,
                corrected_norm=corrected_norm
            )

            if matched:
                matching_patches += 1
                wfis_with_match.add(issue_id)
                by_operation[operation]["matched"] += 1

            patch_rows.append({
                "use_case": use_case,
                "issue_id": issue_id,
                "patch_id": patch.get("patch_id", patch.get("id", "")),
                "operation": operation,
                "target_rule_id": patch.get("target_rule_id", ""),
                "proposed_rule": proposed_rule,
                "matched_corrected": matched
            })

        for op, stats in by_operation.items():
            generated = stats["generated"]
            stats["match_rate"] = (
                stats["matched"] / generated
                if generated else 0
            )

        total_patches = len(patches)
        total_wfis = len(wfis)

        return {
            "use_case": use_case,
            "total_wfis": total_wfis,
            "wfis_with_matching_patch": len(wfis_with_match),
            "wfi_match_rate": (
                len(wfis_with_match) / total_wfis
                if total_wfis else 0
            ),
            "total_patches": total_patches,
            "matching_patches": matching_patches,
            "patch_match_rate": (
                matching_patches / total_patches
                if total_patches else 0
            ),
            "by_operation": dict(by_operation),
            "patch_rows": patch_rows
        }

    def patch_matches_corrected(self, patch, corrected_norm):
        operation = patch.get("operation", "")
        proposed_rule = patch.get("proposed_rule", "")
        target_rule_id = patch.get("target_rule_id", "")

        proposed_norm = self.normalize(proposed_rule)

        if proposed_norm and proposed_norm in corrected_norm:
            return True

        if operation == "rule_removal":
            return not self.rule_id_exists(target_rule_id, corrected_norm)

        if operation in {
            "defeater_introduction",
            "trigger_strengthening",
            "trigger_refinement",
            "rule_merging",
            "rule_decomposition",
            "event_specialization",
            "measure_specialization",
            "capability_refinement",
            "new_rule_generation"
        }:
            return self.soft_rule_match(proposed_rule, corrected_norm)

        return False

    def soft_rule_match(self, proposed_rule, corrected_norm):
        proposed_tokens = set(self.tokens(proposed_rule))

        if not proposed_tokens:
            return False

        corrected_tokens = set(self.tokens(corrected_norm))

        overlap = len(proposed_tokens & corrected_tokens)
        ratio = overlap / len(proposed_tokens)

        return ratio >= 0.75

    def rule_id_exists(self, rule_id, normalized_text):
        if not rule_id:
            return False

        return self.normalize(rule_id) in normalized_text

    def normalize(self, text):
        text = str(text)
        text = text.lower()
        text = re.sub(r"\s+", " ", text)
        text = re.sub(r"[{}().,;:]", "", text)
        return text.strip()

    def tokens(self, text):
        text = self.normalize(text)
        return re.findall(r"[a-zA-Z_][a-zA-Z0-9_]*", text)