import os


class EvaluationBFinalSpec:

    def __init__(self, parser, analyzer, patch_ranker=None):
        self.parser = parser
        self.analyzer = analyzer
        self.patch_ranker = patch_ranker

    def metric_similarity(self, a, b):
        if a == 0 and b == 0:
            return 1.0
        return round(min(a, b) / max(a, b), 3)

    def build_sleecpatch_file(self, use_case, original_sleec, all_patch_results, apply_patch_to_text):
        """
        Select rank-1 patch for each WFI and apply it to original_sleec.
        """

        final_sleec = original_sleec
        selected_patches = []

        grouped = {}

        for patch in all_patch_results:
            issue_id = patch.get("issue_id", "")
            if not issue_id:
                continue

            grouped.setdefault(issue_id, []).append(patch)

        for issue_id, patches in grouped.items():
            verified = [
                p for p in patches
                if p.get("verified") in [True, 1, "1", "true", "True"]
            ]

            if not verified:
                continue

            best_patch = sorted(
                verified,
                key=lambda p: (
                    int(p.get("rank", 999) or 999),
                    -float(p.get("ranking_score", 0) or 0)
                )
            )[0]

            final_sleec = apply_patch_to_text(final_sleec, best_patch)
            selected_patches.append(best_patch)

        folder = os.path.join("results", use_case)
        os.makedirs(folder, exist_ok=True)

        output_path = os.path.join(folder, f"{use_case}_SLEECPATCH.sleec")

        with open(output_path, "w", encoding="utf-8") as f:
            f.write(final_sleec)

        return {
            "output_path": output_path,
            "final_sleec": final_sleec,
            "selected_patches": selected_patches
        }

    def compare_to_original(self, original_path, target_path):
        original = self.parser.parse_file(original_path)["rules"]
        target = self.parser.parse_file(target_path)["rules"]

        original_by_id = {r["id"]: r for r in original}
        target_by_id = {r["id"]: r for r in target}

        all_ids = set(original_by_id.keys()) | set(target_by_id.keys())

        summary = {
            "rules_edited": 0,
            "rules_added": 0,
            "rules_deleted": 0,
            "constraints_added": 0,
            "constraints_removed": 0,
            "defeaters_added": 0,
            "defeaters_removed": 0,
            "actions_changed": 0
        }

        for rid in all_ids:
            before = original_by_id.get(rid)
            after = target_by_id.get(rid)

            if before and not after:
                summary["rules_deleted"] += 1
                continue

            if after and not before:
                summary["rules_added"] += 1
                continue

            change = self.analyzer.analyze_rule_change(before, after)

            if change.get("rule_modified"):
                summary["rules_edited"] += 1

            summary["constraints_added"] += change.get("constraint_added", 0)
            summary["constraints_removed"] += change.get("constraint_removed", 0)
            summary["defeaters_added"] += change.get("defeater_added", 0)
            summary["defeaters_removed"] += change.get("defeater_removed", 0)

            if change.get("action_changed"):
                summary["actions_changed"] += 1

        return summary

    def evaluate(self, use_case, original_path, corrected_path, sleecpatch_path):
        corrected_metrics = self.compare_to_original(original_path, corrected_path)
        sleecpatch_metrics = self.compare_to_original(original_path, sleecpatch_path)

        similarities = {}

        for key in corrected_metrics:
            similarities[key] = self.metric_similarity(
                corrected_metrics[key],
                sleecpatch_metrics[key]
            )

        overall_similarity = round(
            sum(similarities.values()) / len(similarities),
            3
        ) if similarities else 0

        return {
            "use_case": use_case,
            "corrected_vs_original": corrected_metrics,
            "sleecpatch_vs_original": sleecpatch_metrics,
            "similarities": similarities,
            "overall_similarity": overall_similarity
        }