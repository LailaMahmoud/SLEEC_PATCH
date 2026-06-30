import re


class PatchRanker:

    def rank(self, verified_patches):
        ranked = []

        for patch in verified_patches:
            scores = self.score_patch(patch)

            patch["ranking"] = scores
            patch["ranking_score"] = scores["total_score"]

            ranked.append(patch)

        ranked.sort(
            key=lambda p: p.get("ranking_score", 0),
            reverse=True
        )

        for index, patch in enumerate(ranked, start=1):
            patch["rank"] = index

        return ranked

    def score_patch(self, patch):
        original = str(patch.get("original_rule", ""))
        proposed = str(patch.get("proposed_rule", ""))
        explanation = str(
            patch.get("natural_language_explanation", "")
            or patch.get("explanation", "")
        )

        structural = self.structural_simplicity(proposed)
        logical = self.logical_simplicity(proposed)
        semantic = self.semantic_clarity(proposed)

        interp = self.interpretability(
            original_rule=original,
            patched_rule=proposed,
            explanation=explanation
        )

        patch["interpretability_score"] = interp["score"]
        patch["interpretability_passed"] = interp["passed"]
        patch["interpretability_issues"] = interp["issues"]

        interpretability = interp["score"]

        total = (
            0.30 * structural
            + 0.30 * logical
            + 0.20 * semantic
            + 0.20 * interpretability
        )

        rationale = self.ranking_rationale(
            patch=patch,
            structural=structural,
            logical=logical,
            semantic=semantic,
            interpretability=interpretability,
            interpretability_issues=interp["issues"]
        )

        patch["ranking_rationale"] = rationale

        return {
            "structural_simplicity": round(structural, 2),
            "logical_simplicity": round(logical, 2),
            "semantic_clarity": round(semantic, 2),
            "interpretability": round(interpretability, 2),
            "interpretability_passed": interp["passed"],
            "interpretability_issues": interp["issues"],
            "rationale": rationale,
            "total_score": round(total, 2)
        }

    def ranking_rationale(
        self,
        patch,
        structural,
        logical,
        semantic,
        interpretability,
        interpretability_issues
    ):
        operation = str(patch.get("operation", ""))
        reasons = []

        if structural >= 85:
            reasons.append("Keeps the repaired rule structurally compact.")
        elif structural < 70:
            reasons.append("Adds structural complexity that should be reviewed.")

        if logical >= 85:
            reasons.append("Uses a relatively simple logical condition.")
        elif logical < 70:
            reasons.append("Uses a more complex condition with several logical parts.")

        if semantic >= 90:
            reasons.append("Avoids vague placeholder concepts.")
        elif semantic < 80:
            reasons.append("May contain a concept that needs clearer domain wording.")

        if interpretability >= 85:
            reasons.append("The rule change is easy to interpret from the explanation.")
        elif interpretability_issues:
            reasons.append(interpretability_issues[0])

        operation_reasons = {
            "defeater_introduction": "Adds an exception while preserving the main rule.",
            "defeater_propagation": "Preserves an existing exception in the repaired rule.",
            "purpose_defeater": "Targets the exception to the affected purpose.",
            "trigger_refinement": "Narrows the rule trigger to avoid the issue.",
            "trigger_strengthening": "Adds context to the trigger instead of changing the response.",
            "rule_decomposition": "Splits the repair into explicit cases for inspection.",
            "rule_merging": "Combines related behavior into a single repaired rule.",
            "rule_removal": "Removes behavior only when the rule appears redundant."
        }

        if operation in operation_reasons:
            reasons.append(operation_reasons[operation])

        return reasons[:4]

    def structural_simplicity(self, rule):
        score = 100

        tokens = rule.split()
        score -= max(0, len(tokens) - 12) * 2

        defeaters = rule.count("unless")
        score -= defeaters * 10

        nested = rule.count("(") + rule.count(")")
        score -= nested * 3

        return max(0, min(100, score))

    def logical_simplicity(self, rule):
        score = 100

        boolean_ops = len(
            re.findall(r"\b(and|or|not)\b", rule, re.IGNORECASE)
        )

        score -= boolean_ops * 8

        if "not not" in rule.lower():
            score -= 20

        match = re.search(
            r"when\s+(.*?)\s+then",
            rule,
            re.IGNORECASE
        )

        if match:
            condition = match.group(1)

            if len(condition.split()) > 8:
                score -= 15

        return max(0, min(100, score))

    def semantic_clarity(self, rule):
        score = 100

        vague_terms = [
            "RiskHigh",
            "SituationBad",
            "ConditionMet",
            "SomethingWrong",
            "UserIsOk",
            "NormalState"
        ]

        for term in vague_terms:
            if term.lower() in rule.lower():
                score -= 25

        return max(0, min(100, score))
    

    #1. Did the patch introduce a new undefined concept?
    #2. Did it add a condition that is redundant with the original trigger?
    #3. Did it make the rule harder to understand?
    #4. Did it change stakeholder intent?
    #5. Did it replace an action with a new action whose meaning is unclear?

    def interpretability(self, original_rule, patched_rule, explanation=""):
        score = 100
        issues = []

        original_text = str(original_rule)
        patched_text = str(patched_rule)
        explanation_text = str(explanation)

        sensitive_terms = [
            "Religion",
            "Gender",
            "Race",
            "Age",
            "Disability"
        ]

        vague_terms = [
            "isEmergency",
            "emergency",
            "critical",
            "serious",
            "urgent",
            "appropriate",
            "reasonable",
            "highRisk",
            "riskLevel",
            "specialCase"
        ]

        # 1. Sensitive terms must be justified
        for term in sensitive_terms:
            if term.lower() in patched_text.lower():
                if term.lower() not in explanation_text.lower():
                    score -= 20
                    issues.append(
                        f"Sensitive term '{term}' is introduced without explicit rationale."
                    )

        # 2. New vague/contextual concepts must be explained
        for term in vague_terms:
            if term.lower() in patched_text.lower() and term.lower() not in original_text.lower():
                if term.lower() not in explanation_text.lower():
                    score -= 20
                    issues.append(
                        f"New contextual concept '{term}' is introduced without explanation."
                    )

        # 3. New condition may weaken original obligation
        original_condition = self.extract_condition(original_text)
        patched_condition = self.extract_condition(patched_text)

        if original_condition and patched_condition:
            if original_condition.lower() in patched_condition.lower():
                original_parts = self.count_conditions(original_condition)
                patched_parts = self.count_conditions(patched_condition)

                if patched_parts > original_parts:
                    score -= 20
                    issues.append(
                        "Patch adds a new trigger condition, which may weaken the original obligation."
                    )

        # 4. Action change must be explained
        original_action = self.extract_action(original_text)
        patched_action = self.extract_action(patched_text)

        if original_action and patched_action and original_action != patched_action:
            if (
                original_action.lower() not in explanation_text.lower()
                or patched_action.lower() not in explanation_text.lower()
            ):
                score -= 20
                issues.append(
                    f"Action changed from '{original_action}' to '{patched_action}' without clear explanation."
                )

        # 5. New predicates must be explained
        original_terms = set(self.extract_predicates(original_text))
        patched_terms = set(self.extract_predicates(patched_text))

        new_terms = patched_terms - original_terms

        for term in new_terms:
            if term.lower() not in explanation_text.lower():
                score -= 10
                issues.append(
                    f"New predicate '{term}' is introduced without explaining its meaning."
                )

        score = max(score, 0)

        return {
            "score": score,
            "passed": score >= 70,
            "issues": issues
        }

        


    def extract_condition(self, rule_text):
        text = str(rule_text)

        m = re.search(
            r"\bwhen\b(.*?)\bthen\b",
            text,
            flags=re.IGNORECASE | re.DOTALL
        )

        return m.group(1).strip() if m else ""


    def extract_action(self, rule_text):
        text = str(rule_text)

        m = re.search(
            r"\bthen\b(.*)",
            text,
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


    def count_conditions(self, condition):
        if not condition:
            return 0

        parts = re.split(
            r"\band\b|\bor\b",
            condition,
            flags=re.IGNORECASE
        )

        return len([p for p in parts if p.strip()])


    def extract_predicates(self, text):
        text = str(text)

        # Captures DetectFire, NotifyUser, isEmergency, AlertUser, etc.
        return re.findall(
            r"\b[A-Za-z_][A-Za-z0-9_]*\b",
            text
        )
