from services.sleec_parser import SLEECParser
from services.repair_action_analyzer import RepairActionAnalyzer


class CorrectedUseCaseComparator:

    def __init__(self):
        self.parser = SLEECParser()
        self.analyzer = RepairActionAnalyzer()

    def compare_files(self, corrected_path, sleecpatch_path):
        corrected = self.parser.parse_file(corrected_path)["rules"]
        sleecpatch = self.parser.parse_file(sleecpatch_path)["rules"]

        corrected_by_id = {r["id"]: r for r in corrected}
        patch_by_id = {r["id"]: r for r in sleecpatch}

        all_ids = sorted(set(corrected_by_id.keys()) | set(patch_by_id.keys()))

        rule_results = []

        for rid in all_ids:
            c = corrected_by_id.get(rid)
            p = patch_by_id.get(rid)

            if c and not p:
                rule_results.append({
                    "rule_id": rid,
                    "corrected_action": ["rule_present"],
                    "sleecpatch_action": ["rule_deleted"],
                    "match": False
                })

            elif p and not c:
                rule_results.append({
                    "rule_id": rid,
                    "corrected_action": ["rule_deleted"],
                    "sleecpatch_action": ["rule_added"],
                    "match": False
                })

            else:
                change = self.analyzer.analyze_rule_change(c, p)

                corrected_action = self.analyzer.action_type(change)
                sleecpatch_action = self.analyzer.action_type(change)

                rule_results.append({
                    "rule_id": rid,
                    "corrected_rule": c["raw"],
                    "sleecpatch_rule": p["raw"],
                    "corrected_action": corrected_action,
                    "sleecpatch_action": sleecpatch_action,
                    "match": corrected_action == sleecpatch_action,
                    "details": change
                })

        return {
            "rule_level": rule_results,
            "summary": self.summary(rule_results)
        }

    def summary(self, rule_results):
        summary = {
            "rules_compared": len(rule_results),
            "action_matches": 0,
            "rules_modified": 0,
            "constraints_added": 0,
            "constraints_removed": 0,
            "defeaters_added": 0,
            "defeaters_removed": 0,
            "actions_changed": 0
        }

        for r in rule_results:
            if r.get("match"):
                summary["action_matches"] += 1

            d = r.get("details", {})
            if d.get("rule_modified"):
                summary["rules_modified"] += 1

            summary["constraints_added"] += d.get("constraint_added", 0)
            summary["constraints_removed"] += d.get("constraint_removed", 0)
            summary["defeaters_added"] += d.get("defeater_added", 0)
            summary["defeaters_removed"] += d.get("defeater_removed", 0)

            if d.get("action_changed"):
                summary["actions_changed"] += 1

        total = summary["rules_compared"]
        summary["action_match_rate"] = round(summary["action_matches"] / total, 3) if total else 0

        return summary