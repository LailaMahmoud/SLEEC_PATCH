import re
from services.candidate_status import formally_verified


class PatchRanker:

    def __init__(self, semantic_assessor=None):
        # Optional callback for Section-C qualitative assessment.
        # It must be invoked only on patches that already passed formal verification.
        self.semantic_assessor = semantic_assessor

    def rank(self, verified_patches):
        ranked = []

        for patch in verified_patches:
            if not formally_verified(patch):
                continue
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
        if not formally_verified(patch):
            raise ValueError("Only formally verified repairs may be scored.")
        original = str(patch.get("original_rule", ""))
        proposed = str(patch.get("proposed_rule", ""))
        explanation = str(
            patch.get("natural_language_explanation", "")
            or patch.get("explanation", "")
        )

        # Section C: deterministic dimensions.
        structural = self.structural_simplicity(proposed)
        logical = self.logical_simplicity(proposed)

        # Conservative fallback values. If the engine supplies the LLM assessor,
        # these two qualitative dimensions are replaced by the LLM scores.
        semantic = self.semantic_clarity(proposed)
        interp = self.interpretability(
            original_rule=original,
            patched_rule=proposed,
            explanation=explanation
        )
        interpretability = interp["score"]
        semantic_source = "fallback"
        semantic_reason = ""
        interpretability_reason = ""
        issues = list(interp["issues"])

        if self.semantic_assessor is not None:
            try:
                quality = self.semantic_assessor(patch)
                if isinstance(quality, dict) and quality.get("source") == "llm":
                    if quality.get("semantic_clarity") is not None:
                        semantic = self._clamp(float(quality["semantic_clarity"]))
                    if quality.get("interpretability") is not None:
                        interpretability = self._clamp(float(quality["interpretability"]))

                    semantic_reason = str(
                        quality.get("semantic_clarity_reason", "")
                    ).strip()
                    interpretability_reason = str(
                        quality.get("interpretability_reason", "")
                    ).strip()
                    semantic_source = "llm"
                    issues = (
                        [interpretability_reason]
                        if interpretability_reason
                        else []
                    )
            except Exception as exc:
                print("[WARN] LLM patch-quality assessment failed:", exc)

        total = (
            0.25 * structural
            + 0.25 * logical
            + 0.25 * semantic
            + 0.25 * interpretability
        )

        rationale = self.ranking_rationale(
            patch=patch,
            structural=structural,
            logical=logical,
            semantic=semantic,
            interpretability=interpretability,
            interpretability_issues=issues
        )

        patch["interpretability_score"] = interpretability
        patch["interpretability_passed"] = interpretability >= 70
        patch["interpretability_issues"] = issues
        patch["ranking_rationale"] = rationale

        return {
            "structural_simplicity": round(structural, 2),
            "logical_simplicity": round(logical, 2),
            "semantic_clarity": round(semantic, 2),
            "interpretability": round(interpretability, 2),
            "semantic_assessment_source": semantic_source,
            "semantic_clarity_reason": semantic_reason,
            "interpretability_reason": interpretability_reason,
            "interpretability_passed": interpretability >= 70,
            "interpretability_issues": issues,
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

    def split_proposed_rules(self, text):
        text = re.sub(r"\s+", " ", str(text or "")).strip()
        if not text:
            return []
        starts = list(re.finditer(
            r"(?i)(?<!\w)(?:(?:rule|r|c)\d+(?:_\d+)?)\s+when\b", text
        ))
        if len(starts) <= 1:
            return [text] if re.search(r"\bwhen\b.+\bthen\b", text, re.I) else []
        return [
            text[m.start():(starts[i+1].start() if i+1 < len(starts) else len(text))].strip()
            for i, m in enumerate(starts)
        ]

    def max_parenthesis_depth(self, text):
        depth = maximum = 0
        for char in str(text or ""):
            if char == "(":
                depth += 1
                maximum = max(maximum, depth)
            elif char == ")":
                depth = max(0, depth - 1)
        return maximum

    def structural_simplicity(self, rule):
        rules = self.split_proposed_rules(rule)
        if not rules:
            return 0
        scores = []
        for item in rules:
            score = 100
            score -= max(0, len(item.split()) - 20) * 1.5
            score -= len(re.findall(r"\bunless\b", item, re.I)) * 6
            score -= max(0, self.max_parenthesis_depth(item) - 1) * 5
            scores.append(max(0, min(100, score)))
        score = sum(scores) / len(scores)
        score -= max(0, len(rules) - 2) * 8
        return max(0, min(100, score))

    def logical_simplicity(self, rule):
        """
        Deterministic logical-complexity score over the complete repair:
        triggering condition + defeater/UNLESS expression.
        """
        rules = self.split_proposed_rules(rule)
        if not rules:
            return 0

        scores = []
        for item in rules:
            score = 100.0

            condition = self.extract_condition(item)
            defeater = self.extract_defeater(item)
            logical_text = " ".join(
                part for part in (condition, defeater) if part
            )

            boolean_ops = len(
                re.findall(r"\b(?:and|or|not)\b", logical_text, re.I)
            )
            negations = len(re.findall(r"\bnot\b", logical_text, re.I))
            double_negations = len(
                re.findall(r"\bnot\s*(?:\(\s*)?not\b", logical_text, re.I)
            )
            depth = self.max_parenthesis_depth(logical_text)
            logical_tokens = len(logical_text.split())

            score -= boolean_ops * 4
            score -= negations * 2
            score -= double_negations * 15
            score -= max(0, depth - 1) * 6
            score -= max(0, logical_tokens - 14) * 1.5

            scores.append(self._clamp(score))

        return sum(scores) / len(scores)

    def semantic_clarity(self, rule):
        """
        Conservative fallback only. Paper-aligned runs should use the LLM
        semantic assessor supplied by the workbench engine.
        """
        score = 90.0
        vague_terms = [
            "RiskHigh",
            "SituationBad",
            "ConditionMet",
            "SomethingWrong",
            "UserIsOk",
            "NormalState",
            "SpecialCase"
        ]
        for term in vague_terms:
            if term.lower() in str(rule).lower():
                score -= 20
        return self._clamp(score)


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

        # 5. New identifiers relative to this rule are only a fallback warning.
        # Do NOT call them "undefined": they may already be declared in the SLEEC
        # vocabulary. The LLM assessor receives the full declared vocabulary.
        original_terms = set(self.extract_predicates(original_text))
        patched_terms = set(self.extract_predicates(patched_text))
        new_terms = patched_terms - original_terms

        for term in sorted(new_terms, key=str.lower):
            if term.lower() not in explanation_text.lower():
                score -= 5
                issues.append(
                    f"Identifier '{term}' is new relative to the original rule; "
                    "check it against the declared SLEEC vocabulary and repair rationale."
                )

        score = max(score, 0)

        return {
            "score": score,
            "passed": score >= 70,
            "issues": issues
        }

        


    def extract_defeater(self, rule_text):
        text = str(rule_text)
        m = re.search(
            r"\bunless\b(.*)$",
            text,
            flags=re.IGNORECASE | re.DOTALL
        )
        return m.group(1).strip() if m else ""

    @staticmethod
    def _clamp(value):
        return max(0.0, min(100.0, float(value)))


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

        tokens = re.findall(r"\b[A-Za-z_][A-Za-z0-9_]*\b", text)
        keywords = {
            "when", "then", "unless", "within", "and", "or", "not",
            "event", "measure", "rule", "true", "false",
            "second", "seconds", "minute", "minutes", "hour", "hours"
        }
        return [
            token for token in tokens
            if token.lower() not in keywords
            and not re.fullmatch(r"(?:r|rule|c)\d+(?:_\d+)?", token, re.I)
        ]
