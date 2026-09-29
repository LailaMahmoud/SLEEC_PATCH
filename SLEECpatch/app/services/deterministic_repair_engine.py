"""Deterministic repairs over the parsed specification and its diagnosis."""
import re

from services.evidence_repair import generate_repairs


class DeterministicRepairEngine:
    def generate(self, issue_type, selected_issue, rules, operators, diagnosis=None, sleec_text=None):
        if sleec_text is None:
            raise ValueError("The full SLEEC specification is required for evidence-grounded repairs.")
        return generate_repairs(sleec_text, issue_type, diagnosis or {}, operators)

    def rule_to_text(self, rule):
        if not rule.get("raw"):
            raise ValueError("A parsed rule must retain its original source text.")
        return rule["raw"]

    def find_conflicting_rules(self, selected_issue, rules):
        # Compatibility for callers inspecting an old text-only diagnosis.
        # No action matching or arbitrary opposing-rule fallback.
        return [rule for rule in rules
                if re.search(r"(?<!\\w)" + re.escape(rule["id"]) + r"(?!\\w)", str(selected_issue))]
