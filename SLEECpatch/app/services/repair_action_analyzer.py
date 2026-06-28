import re


class RepairActionAnalyzer:

    def split_constraints(self, condition):
        condition = str(condition or "")
        condition = condition.replace("(", " ").replace(")", " ")
        condition = condition.replace("{", "").replace("}", "")

        parts = re.split(r"\s+and\s+|\s+or\s+", condition, flags=re.IGNORECASE)

        return set(
            p.strip()
            for p in parts
            if p.strip()
        )

    def analyze_rule_change(self, before, after):
        before_constraints = self.split_constraints(before.get("condition", ""))
        after_constraints = self.split_constraints(after.get("condition", ""))

        before_defeaters = set(before.get("defeaters", []))
        after_defeaters = set(after.get("defeaters", []))

        return {
            "rule_id": before.get("id") or after.get("id"),
            "rule_modified": before != after,
            "constraint_added": len(after_constraints - before_constraints),
            "constraint_removed": len(before_constraints - after_constraints),
            "defeater_added": len(after_defeaters - before_defeaters),
            "defeater_removed": len(before_defeaters - after_defeaters),
            "action_changed": before.get("action", "") != after.get("action", "")
        }

    def action_type(self, change):
        actions = []

        if change.get("constraint_added", 0) > 0:
            actions.append("constraint_added")

        if change.get("constraint_removed", 0) > 0:
            actions.append("constraint_removed")

        if change.get("defeater_added", 0) > 0:
            actions.append("defeater_added")

        if change.get("defeater_removed", 0) > 0:
            actions.append("defeater_removed")

        if change.get("action_changed"):
            actions.append("action_changed")

        if not actions and change.get("rule_modified"):
            actions.append("edit")

        return actions