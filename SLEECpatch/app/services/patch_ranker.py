import re

from sleec.sleecParser import parse_sleec_ast


class PatchRanker:

    def __init__(self, semantic_assessor=None):
        # Optional callback for Section-C qualitative assessment.
        # It must be invoked only on patches that already passed formal verification.
        self.semantic_assessor = semantic_assessor

    def rank(self, verified_patches, original_sleec):
        """Rank formally verified patches by ascending lexicographic cost."""
        ranked = []

        for patch in verified_patches:
            patched_sleec = str(patch.get("patched_sleec", "") or "")
            if not patched_sleec:
                raise ValueError(
                    "Quantitative ranking requires patch['patched_sleec']."
                )

            metrics = self.compute_metrics(
                original_sleec=original_sleec,
                patched_sleec=patched_sleec,
            )

            patch["ranking"] = metrics

            # Legacy storage field only; it does not determine ranking.
            patch["ranking_score"] = 0

            ranked.append(patch)

        ranked.sort(
            key=lambda patch: tuple(
                patch["ranking"]["lexicographic_key"]
            )
        )

        for index, patch in enumerate(ranked, start=1):
            patch["rank"] = index

        return ranked

    def compute_metrics(self, original_sleec, patched_sleec):
        """Compute quantitative metrics from original and patched SLEEC."""
        original_model = parse_sleec_ast(original_sleec)
        patched_model = parse_sleec_ast(patched_sleec)

        original_rules = self._rule_sources(original_model, original_sleec)
        patched_rules = self._rule_sources(patched_model, patched_sleec)

        original_ids = set(original_rules)
        patched_ids = set(patched_rules)

        added_rule_ids = patched_ids - original_ids
        removed_rule_ids = original_ids - patched_ids

        edited_rule_ids = {
            rule_id
            for rule_id in (original_ids & patched_ids)
            if self._normalize_source(original_rules[rule_id])
            != self._normalize_source(patched_rules[rule_id])
        }

        rules_added = len(added_rule_ids)
        rules_removed = len(removed_rule_ids)
        rules_edited = len(edited_rule_ids)

        affected_rule_ids = (
            added_rule_ids
            | removed_rule_ids
            | edited_rule_ids
        )

        rules_affected = len(affected_rule_ids)

        original_events = self._definition_names(
            original_model, {"Event"}
        )
        patched_events = self._definition_names(
            patched_model, {"Event"}
        )

        measure_types = {
            "BoolMeasure",
            "NumMeasure",
            "ScalarMeasure",
        }

        original_measures = self._definition_names(
            original_model, measure_types
        )
        patched_measures = self._definition_names(
            patched_model, measure_types
        )

        new_events = len(patched_events - original_events)
        new_measures = len(patched_measures - original_measures)

        # Count newly introduced defeater structures rather than relying
        # on the net difference in total defeater counts.
        new_defeaters = self._count_new_defeaters(
            original_model,
            original_sleec,
            patched_model,
            patched_sleec,
        )

        new_specification_elements = (
            new_events
            + new_measures
            + new_defeaters
        )

        affected_patched_rules = self._affected_patched_rules(
            patched_model,
            affected_rule_ids,
        )

        # Syntactic metrics are computed only on the affected rules in the
        # simplified patched specification, not on unrelated unchanged rules.
        boolean_operator_count = self._count_boolean_operators(
            affected_patched_rules
        )
        negation_count = self._count_negations(
            affected_patched_rules
        )

        # One syntactic-complexity criterion:
        # Boolean operators plus Boolean negations.
        boolean_expression_complexity = (
            boolean_operator_count + negation_count
        )

        defeater_count = self._count_rule_defeaters(
            affected_patched_rules
        )
        defeater_nesting_depth = self._rule_defeater_depth(
            affected_patched_rules
        )

        lexicographic_key = (
            rules_affected,
            new_specification_elements,
            boolean_expression_complexity,
            defeater_count,
            defeater_nesting_depth,
        )

        return {
            "rules_affected": rules_affected,
            "rules_edited": rules_edited,
            "rules_added": rules_added,
            "rules_removed": rules_removed,
            "new_specification_elements": new_specification_elements,
            "new_events": new_events,
            "new_measures": new_measures,
            "new_defeaters": new_defeaters,
            "boolean_operator_count": boolean_operator_count,
            "negation_count": negation_count,
            "boolean_expression_complexity": boolean_expression_complexity,
            "defeater_count": defeater_count,
            "defeater_nesting_depth": defeater_nesting_depth,
            "lexicographic_key": list(lexicographic_key),
        }

    @staticmethod
    def _normalize_source(text):
        return re.sub(r"\\s+", " ", str(text or "")).strip()

    @staticmethod
    def _rule_sources(model, sleec_text):
        result = {}

        for rule in model.ruleBlock.rules:
            result[str(rule.name)] = sleec_text[
                rule._tx_position:rule._tx_position_end
            ]

        return result

    @staticmethod
    def _affected_patched_rules(model, affected_rule_ids):
        """Return affected rules that exist in the patched specification."""
        return [
            rule
            for rule in model.ruleBlock.rules
            if str(rule.name) in affected_rule_ids
        ]

    @staticmethod
    def _definition_names(model, accepted_types):
        return {
            str(definition.name)
            for definition in model.definitions
            if type(definition).__name__ in accepted_types
        }

    def _count_boolean_operators(self, rules):
        """Count AND/OR Boolean AST nodes in affected rules."""
        total = 0

        for rule in rules:
            total += self._count_boolean_operators_expr(
                getattr(rule, "condition", None)
            )
            total += self._count_response_boolean_operators(
                getattr(rule, "response", None)
            )

        return total

    def _count_boolean_operators_expr(self, node):
        if node is None:
            return 0

        kind = type(node).__name__

        if kind == "BoolBinaryOp":
            return (
                1
                + self._count_boolean_operators_expr(
                    getattr(node, "lhs", None)
                )
                + self._count_boolean_operators_expr(
                    getattr(node, "rhs", None)
                )
            )

        if kind == "Negation":
            return self._count_boolean_operators_expr(
                getattr(node, "expr", None)
            )

        return 0

    def _count_response_boolean_operators(self, response):
        if response is None:
            return 0

        total = 0

        for defeater in getattr(response, "defeater", []) or []:
            total += self._count_boolean_operators_expr(
                getattr(defeater, "expr", None)
            )

            nested = getattr(defeater, "response", None)
            if nested is not None:
                total += self._count_response_boolean_operators(
                    nested
                )

        return total

    def _count_negations(self, rules):
        """Count Boolean NOT nodes in affected rules."""
        total = 0

        for rule in rules:
            total += self._count_negations_expr(
                getattr(rule, "condition", None)
            )
            total += self._count_response_negations(
                getattr(rule, "response", None)
            )

        return total

    def _count_negations_expr(self, node):
        if node is None:
            return 0

        kind = type(node).__name__

        if kind == "Negation":
            return (
                1
                + self._count_negations_expr(
                    getattr(node, "expr", None)
                )
            )

        if kind == "BoolBinaryOp":
            return (
                self._count_negations_expr(
                    getattr(node, "lhs", None)
                )
                + self._count_negations_expr(
                    getattr(node, "rhs", None)
                )
            )

        return 0

    def _count_response_negations(self, response):
        if response is None:
            return 0

        total = 0

        for defeater in getattr(response, "defeater", []) or []:
            total += self._count_negations_expr(
                getattr(defeater, "expr", None)
            )

            nested = getattr(defeater, "response", None)
            if nested is not None:
                total += self._count_response_negations(nested)

        return total

    def _count_new_defeaters(
        self,
        original_model,
        original_sleec,
        patched_model,
        patched_sleec,
    ):
        """Count defeater nodes newly introduced by the patch.

        A modification to an existing defeater is not itself a new
        specification element. Counts are therefore compared per rule.
        """
        original_rules = {
            str(rule.name): rule
            for rule in original_model.ruleBlock.rules
        }

        patched_rules = {
            str(rule.name): rule
            for rule in patched_model.ruleBlock.rules
        }

        total = 0

        for rule_id, patched_rule in patched_rules.items():
            patched_count = self._count_response_defeaters(
                getattr(patched_rule, "response", None)
            )

            original_rule = original_rules.get(rule_id)

            if original_rule is None:
                original_count = 0
            else:
                original_count = self._count_response_defeaters(
                    getattr(original_rule, "response", None)
                )

            total += max(
                0,
                patched_count - original_count,
            )

        return total

    def _count_model_defeaters(self, model):
        """Count all defeaters in a complete SLEEC model."""
        return self._count_rule_defeaters(
            list(model.ruleBlock.rules)
        )

    def _count_rule_defeaters(self, rules):
        """Count defeaters recursively in the supplied rules."""
        return sum(
            self._count_response_defeaters(
                getattr(rule, "response", None)
            )
            for rule in rules
        )

    def _count_response_defeaters(self, response):
        if response is None:
            return 0

        total = 0

        for defeater in getattr(response, "defeater", []) or []:
            total += 1

            nested = getattr(defeater, "response", None)
            if nested is not None:
                total += self._count_response_defeaters(nested)

        return total

    def _rule_defeater_depth(self, rules):
        """Return maximum defeater nesting depth in supplied rules."""
        maximum = 0

        for rule in rules:
            maximum = max(
                maximum,
                self._response_defeater_depth(
                    getattr(rule, "response", None),
                    0,
                ),
            )

        return maximum

    def _response_defeater_depth(self, response, current_depth):
        if response is None:
            return current_depth

        maximum = current_depth

        for defeater in getattr(response, "defeater", []) or []:
            depth = current_depth + 1
            maximum = max(maximum, depth)

            nested = getattr(defeater, "response", None)
            if nested is not None:
                maximum = max(
                    maximum,
                    self._response_defeater_depth(
                        nested,
                        depth,
                    ),
                )

        return maximum

    def score_patch(self, patch):
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
