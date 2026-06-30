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

    def generate_redundancy_patches(self, selected_issue, rules, operators):
        patches = []
        issue_text = str(selected_issue)

        rule_id = self.extract_rule_id(issue_text)
        original_rule = self.find_rule_text(rule_id, rules) or issue_text

        if "rule_removal" in operators and rule_id:
            patches.append({
                "patch_id": f"d_remove_{rule_id}",
                "id": f"d_remove_{rule_id}",
                "source": "deterministic",
                "operation": "rule_removal",
                "target_rule_id": rule_id,
                "original_rule": original_rule,
                "proposed_rule": "",
                "natural_language_explanation": (
                    f"Remove {rule_id} because it is redundant."
                )
            })

        if "rule_merging" in operators and rule_id:
            patches.append({
                "patch_id": f"d_merge_{rule_id}",
                "id": f"d_merge_{rule_id}",
                "source": "deterministic",
                "operation": "rule_merging",
                "target_rule_id": rule_id,
                "original_rule": original_rule,
                "proposed_rule": original_rule,
                "natural_language_explanation": (
                    f"Merge {rule_id} with the equivalent rule to avoid redundancy."
                )
            })

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
                    "The conflicting action is converted into an explicit defeater."
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
                    "The opposite rule is given an explicit defeater."
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
                    "The trigger is strengthened using contextual information."
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
                    "The two conflicting rules are merged into one rule."
            })

        return patches

    def extract_rule_id(self, text):
        m = re.search(r"\bRule\d+(?:_\d+)?\b", str(text))
        return m.group(0) if m else ""

    def find_rule_text(self, rule_id, rules):
        if not rule_id:
            return ""

        for r in rules:
            if isinstance(r, dict):
                if r.get("id", "") == rule_id:
                    return (
                        r.get("raw")
                        or r.get("text")
                        or f'{r.get("id")} when {r.get("condition", "")} then {r.get("action", "")}'
                    )

            elif isinstance(r, str) and rule_id in r:
                return r

        return ""

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