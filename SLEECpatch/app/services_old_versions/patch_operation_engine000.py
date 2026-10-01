class PatchOperationEngine:

    def apply_patches(self, rules, patches):
        """
        rules: list of dict rules
        patches: list of selected GPT/stakeholder patches
        """

        updated_rules = [
            dict(r)
            for r in rules
        ]

        for patch in patches:

            operation = patch.get(
                "operation",
                ""
            )

            if operation == "edit":
                updated_rules = self.edit_rule(
                    updated_rules,
                    patch
                )

            elif operation == "add":
                updated_rules = self.add_rule(
                    updated_rules,
                    patch
                )

            elif operation == "delete":
                updated_rules = self.delete_rule(
                    updated_rules,
                    patch
                )

            elif operation == "add_defeater":
                updated_rules = self.add_defeater(
                    updated_rules,
                    patch
                )

            elif operation == "refine_condition":
                updated_rules = self.refine_condition(
                    updated_rules,
                    patch
                )

            elif operation == "refine_action":
                updated_rules = self.refine_action(
                    updated_rules,
                    patch
                )

        return updated_rules

    def edit_rule(self, rules, patch):
        rule_ids = patch.get("rule_ids", [])

        for rule in rules:
            if rule["id"] in rule_ids:
                parsed = self.parse_rule_text(
                    patch.get("proposed_rule", "")
                )

                if parsed:
                    rule["condition"] = parsed["condition"]
                    rule["action"] = parsed["action"]
                    rule["defeater"] = parsed["defeater"]

        return rules

    def add_rule(self, rules, patch):
        parsed = self.parse_rule_text(
            patch.get("proposed_rule", "")
        )

        if not parsed:
            return rules

        new_id = self.next_rule_id(rules)

        rules.append({
            "id": new_id,
            "nl_text": patch.get(
                "natural_language_explanation",
                ""
            ),
            "condition": parsed["condition"],
            "action": parsed["action"],
            "defeater": parsed["defeater"]
        })

        return rules

    def delete_rule(self, rules, patch):
        rule_ids = patch.get("rule_ids", [])

        return [
            r for r in rules
            if r["id"] not in rule_ids
        ]

    def add_defeater(self, rules, patch):
        rule_ids = patch.get("rule_ids", [])

        defeater = patch.get(
            "defeater",
            ""
        )

        if not defeater:
            parsed = self.parse_rule_text(
                patch.get("proposed_rule", "")
            )
            if parsed:
                defeater = parsed["defeater"]

        for rule in rules:
            if rule["id"] in rule_ids:
                rule["defeater"] = defeater

        return rules

    def refine_condition(self, rules, patch):
        rule_ids = patch.get("rule_ids", [])

        new_condition = patch.get(
            "new_condition",
            ""
        )

        if not new_condition:
            parsed = self.parse_rule_text(
                patch.get("proposed_rule", "")
            )

            if parsed:
                new_condition = parsed["condition"]

        for rule in rules:
            if rule["id"] in rule_ids:
                rule["condition"] = new_condition

        return rules

    def refine_action(self, rules, patch):
        rule_ids = patch.get("rule_ids", [])

        new_action = patch.get(
            "new_action",
            ""
        )

        if not new_action:
            parsed = self.parse_rule_text(
                patch.get("proposed_rule", "")
            )

            if parsed:
                new_action = parsed["action"]

        for rule in rules:
            if rule["id"] in rule_ids:
                rule["action"] = new_action

        return rules

    def parse_rule_text(self, text):
        """
        Parses:
        when PatientFallen then CallSupport
        when PatientFallen then CallSupport unless {patientNotDeaf}
        """

        import re

        pattern = (
            r"when\\s+(.+?)\\s+then\\s+(.+?)"
            r"(?:\\s+unless\\s+\\{?(.+?)\\}?)?$"
        )

        match = re.search(
            pattern,
            text,
            re.IGNORECASE
        )

        if not match:
            return None

        return {
            "condition": match.group(1).strip(),
            "action": match.group(2).strip(),
            "defeater": match.group(3).strip()
            if match.group(3)
            else ""
        }

    def next_rule_id(self, rules):
        nums = []

        for r in rules:
            rid = str(
                r.get("id", "")
            )

            if rid.startswith("r"):
                try:
                    nums.append(
                        int(rid[1:])
                    )
                except:
                    pass

        next_num = max(nums) + 1 if nums else 1

        return f"r{next_num}"