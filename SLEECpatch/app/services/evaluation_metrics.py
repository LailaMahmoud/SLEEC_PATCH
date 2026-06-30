import re


class EvaluationMetrics:
    """
    Shared metrics for Evaluation A, B, and C.
    Used to compare ORIGINAL, SLEECPATCH, and SLEEC_CORRECTED specs.
    """

    def normalize(self, text):
        text = str(text or "").lower()
        text = re.sub(r"//.*", " ", text)
        text = re.sub(r"\s+", " ", text)
        text = re.sub(r"[{}().,;:]", " ", text)
        return re.sub(r"\s+", " ", text).strip()

    def tokens(self, text):
        return re.findall(
            r"[a-zA-Z_][a-zA-Z0-9_]*",
            self.normalize(text)
        )

    def similarity(self, a, b):
        a_tokens = set(self.tokens(a))
        b_tokens = set(self.tokens(b))

        if not a_tokens and not b_tokens:
            return 1.0

        if not a_tokens or not b_tokens:
            return 0.0

        return len(a_tokens & b_tokens) / len(a_tokens | b_tokens)

    def extract_rule_id(self, rule_text):
        m = re.search(r"\bRule\d+(?:_\d+)?\b", str(rule_text))
        return m.group(0) if m else ""

    def parse_rules(self, sleec_text):
        """
        Extracts rules from rule_start ... rule_end.
        Returns dict: rule_id -> rule_text
        """
        text = str(sleec_text or "")

        m = re.search(
            r"rule_start(.*?)rule_end",
            text,
            flags=re.IGNORECASE | re.DOTALL
        )

        block = m.group(1) if m else text

        chunks = re.split(
            r"(?=\bRule\d+(?:_\d+)?\b\s+when\s+)",
            block,
            flags=re.IGNORECASE
        )

        rules = {}

        for chunk in chunks:
            chunk = chunk.strip()
            if not chunk:
                continue

            rid = self.extract_rule_id(chunk)
            if rid:
                rules[rid] = re.sub(r"\s+", " ", chunk).strip()

        return rules

    def rule_exists(self, rule_id, sleec_text):
        rules = self.parse_rules(sleec_text)
        return rule_id in rules

    def count_rule_changes(self, original_sleec, revised_sleec):
        original_rules = self.parse_rules(original_sleec)
        revised_rules = self.parse_rules(revised_sleec)

        original_ids = set(original_rules.keys())
        revised_ids = set(revised_rules.keys())

        added = revised_ids - original_ids
        deleted = original_ids - revised_ids
        common = original_ids & revised_ids

        edited = set()

        for rid in common:
            if self.normalize(original_rules[rid]) != self.normalize(revised_rules[rid]):
                edited.add(rid)

        return {
            "rules_added": len(added),
            "rules_deleted": len(deleted),
            "rules_edited": len(edited),
            "added_rule_ids": sorted(added),
            "deleted_rule_ids": sorted(deleted),
            "edited_rule_ids": sorted(edited)
        }

    def count_keyword_changes(self, original_sleec, revised_sleec):
        original = self.normalize(original_sleec)
        revised = self.normalize(revised_sleec)

        return {
            "defeaters_added": max(0, revised.count("unless") - original.count("unless")),
            "defeaters_removed": max(0, original.count("unless") - revised.count("unless")),
            "conditions_added": max(0, revised.count(" and ") - original.count(" and ")),
            "conditions_removed": max(0, original.count(" and ") - revised.count(" and ")),
            "actions_changed": self.estimate_action_changes(original_sleec, revised_sleec)
        }

    def estimate_action_changes(self, original_sleec, revised_sleec):
        original_rules = self.parse_rules(original_sleec)
        revised_rules = self.parse_rules(revised_sleec)

        count = 0

        for rid in set(original_rules.keys()) & set(revised_rules.keys()):
            old_action = self.extract_action(original_rules[rid])
            new_action = self.extract_action(revised_rules[rid])

            if old_action and new_action and self.normalize(old_action) != self.normalize(new_action):
                count += 1

        return count

    def extract_condition(self, rule_text):
        m = re.search(
            r"\bwhen\b(.*?)\bthen\b",
            str(rule_text),
            flags=re.IGNORECASE | re.DOTALL
        )
        return m.group(1).strip() if m else ""

    def extract_action(self, rule_text):
        m = re.search(
            r"\bthen\b(.*)",
            str(rule_text),
            flags=re.IGNORECASE | re.DOTALL
        )

        if not m:
            return ""

        action = m.group(1)

        action = re.split(
            r"\bwithin\b|\bunless\b",
            action,
            flags=re.IGNORECASE
        )[0]

        return action.strip()

    def compare_specs(self, original_sleec, revised_sleec):
        rule_changes = self.count_rule_changes(original_sleec, revised_sleec)
        keyword_changes = self.count_keyword_changes(original_sleec, revised_sleec)

        return {
            **rule_changes,
            **keyword_changes,
            "overall_similarity": round(
                self.similarity(original_sleec, revised_sleec),
                4
            )
        }

    def compare_patch_to_corrected(self, patch, corrected_sleec):
        proposed_rule = patch.get("proposed_rule", "")
        target_rule_id = patch.get("target_rule_id", "")
        operation = patch.get("operation", "")

        corrected_norm = self.normalize(corrected_sleec)
        proposed_norm = self.normalize(proposed_rule)

        exact_match = proposed_norm and proposed_norm in corrected_norm

        if operation == "rule_removal":
            match = not self.rule_exists(target_rule_id, corrected_sleec)
        else:
            match = exact_match or self.similarity(proposed_rule, corrected_sleec) >= 0.75

        return {
            "matched_corrected": match,
            "similarity_to_corrected": round(
                self.similarity(proposed_rule, corrected_sleec),
                4
            )
        }