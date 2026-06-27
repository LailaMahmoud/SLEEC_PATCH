import re


class DeterministicRepairEngine:

    def generate(self, issue_type, selected_issue, rules, operators):
        patches = []

        if issue_type in ["conflicts", "situational_conflicts"]:
            patches.extend(
                self.generate_conflict_patches(
                    issue_type,
                    selected_issue,
                    rules,
                    operators
                )
            )

        if issue_type == "redundancies":
            patches.extend(
                self.generate_redundancy_patches(
                    selected_issue,
                    rules,
                    operators
                )
            )

        return patches

    def generate_conflict_patches(self, issue_type, selected_issue, rules, operators):
        patches = []

        conflict_rules = self.find_conflicting_rules(selected_issue, rules)

        if len(conflict_rules) < 2:
            return patches

        r1 = conflict_rules[0]
        r2 = conflict_rules[1]

        if "defeater_introduction" in operators:
            patches.append({
                "id": "d1",
                "patch_id": "d1",
                "source": "deterministic",
                "issue_type": issue_type,
                "operation": "defeater_introduction",
                "target_rule_id": r1["id"],
                "original_rule": self.rule_to_text(r1),
                "proposed_rule": self.add_defeater(r1, r2["action"]),
                "natural_language_explanation":
                    "The conflicting action is converted into an explicit defeater so this rule is blocked when the opposite action applies."
            })

            patches.append({
                "id": "d2",
                "patch_id": "d2",
                "source": "deterministic",
                "issue_type": issue_type,
                "operation": "defeater_introduction",
                "target_rule_id": r2["id"],
                "original_rule": self.rule_to_text(r2),
                "proposed_rule": self.add_defeater(r2, r1["action"]),
                "natural_language_explanation":
                    "The opposite rule is given an explicit defeater so the two rules no longer fire incompatibly."
            })

        if "trigger_strengthening" in operators:
            patches.append({
                "id": "d3",
                "patch_id": "d3",
                "source": "deterministic",
                "issue_type": issue_type,
                "operation": "trigger_strengthening",
                "target_rule_id": r1["id"],
                "original_rule": self.rule_to_text(r1),
                "proposed_rule": self.strengthen_trigger(r1, r2["action"]),
                "natural_language_explanation":
                    "The trigger is strengthened using an existing conflicting action as a contextual guard."
            })

        if "rule_merging" in operators:
            patches.append({
                "id": "d4",
                "patch_id": "d4",
                "source": "deterministic",
                "issue_type": issue_type,
                "operation": "rule_merging",
                "target_rule_id": r1["id"],
                "original_rule": self.rule_to_text(r1) + "\n" + self.rule_to_text(r2),
                "proposed_rule": self.merge_conflicting_rules(r1, r2),
                "natural_language_explanation":
                    "The two conflicting rules are merged into one rule with an explicit exception."
            })

        return patches

    def generate_redundancy_patches(self, selected_issue, rules, operators):
        patches = []

        redundant_rules = self.find_redundant_rules(selected_issue, rules)

        if len(redundant_rules) < 1:
            return patches

        target = redundant_rules[0]

        if "rule_removal" in operators:
            patches.append({
                "id": "d1",
                "patch_id": "d1",
                "source": "deterministic",
                "issue_type": "redundancies",
                "operation": "rule_removal",
                "target_rule_id": target["id"],
                "original_rule": self.rule_to_text(target),
                "proposed_rule": "",
                "natural_language_explanation":
                    "The redundant rule is removed because it is logically implied by another rule."
            })

        return patches

    def find_conflicting_rules(self, selected_issue, rules):
        text = str(selected_issue)
        found = []

        for rule in rules:
            if rule["id"] in text or rule["action"] in text:
                found.append(rule)

        if len(found) >= 2:
            return found[:2]

        for r1 in rules:
            for r2 in rules:
                if r1["id"] == r2["id"]:
                    continue

                if self.is_opposite_action(r1["action"], r2["action"]):
                    return [r1, r2]

        return []

    def find_redundant_rules(self, selected_issue, rules):
        text = str(selected_issue)

        for rule in rules:
            if rule["id"] in text:
                return [rule]

        for i, r1 in enumerate(rules):
            for r2 in rules[i + 1:]:
                if (
                    r1["condition"] == r2["condition"]
                    and r1["action"] == r2["action"]
                    and r1.get("defeater", "") == r2.get("defeater", "")
                ):
                    return [r2]

        return []

    def is_opposite_action(self, a, b):
        a = str(a).strip()
        b = str(b).strip()

        return (
            a == f"not {b}"
            or b == f"not {a}"
            or a == f"not{b}"
            or b == f"not{a}"
        )

    def add_defeater(self, rule, defeater):
        base = f'{rule["id"]} when {rule["condition"]} then {rule["action"]}'

        if rule.get("defeater"):
            return base + f' unless {{{rule["defeater"]} OR {defeater}}}'

        return base + f' unless {{{defeater}}}'

    def strengthen_trigger(self, rule, context):
        return (
            f'{rule["id"]} when {rule["condition"]} and not {context} '
            f'then {rule["action"]}'
        )

    def merge_conflicting_rules(self, r1, r2):
        return (
            f'{r1["id"]} when {r1["condition"]} then {r1["action"]} '
            f'unless {{{r2["action"]}}}'
        )

    def rule_to_text(self, rule):
        text = f'{rule["id"]} when {rule["condition"]} then {rule["action"]}'

        if rule.get("defeater"):
            text += f' unless {{{rule["defeater"]}}}'

        return text