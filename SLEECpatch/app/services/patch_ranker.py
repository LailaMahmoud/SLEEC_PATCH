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
        proposed = str(patch.get("proposed_rule", ""))
        explanation = str(patch.get("natural_language_explanation", ""))

        structural = self.structural_simplicity(proposed)
        logical = self.logical_simplicity(proposed)
        semantic = self.semantic_clarity(proposed)
        interpretability = self.interpretability(proposed, explanation)

        total = (
            0.30 * structural
            + 0.30 * logical
            + 0.20 * semantic
            + 0.20 * interpretability
        )

        return {
            "structural_simplicity": round(structural, 2),
            "logical_simplicity": round(logical, 2),
            "semantic_clarity": round(semantic, 2),
            "interpretability": round(interpretability, 2),
            "total_score": round(total, 2)
        }

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

    def interpretability(self, rule, explanation):
        score = 100

        sensitive_terms = [
            "Religion",
            "Gender",
            "Race",
            "Age",
            "Disability"
        ]

        for term in sensitive_terms:
            if term.lower() in rule.lower():
                if term.lower() not in explanation.lower():
                    score -= 25

        if not explanation or len(explanation.split()) < 6:
            score -= 20

        return max(0, min(100, score))