import re
from typing import List


class SemanticPatchValidator:
    """
    Generic semantic guard for all SLEEC-PATCH use cases.

    No use-case names or domain concepts are hard-coded. Validation uses only
    the active SLEEC specification, diagnosed issue, selected operator, and
    declared vocabulary supplied by the workbench.
    """

    SLEEC_KEYWORDS = {
        "when", "then", "unless", "within", "and", "or", "not", "while",
        "exists", "true", "false"
    }

    def validate(
        self,
        sleec_text: str,
        issue: dict,
        patch: dict,
        existing_events: List[str],
        existing_measures: List[str],
        existing_responses: List[str],
    ) -> dict:
        if patch.get("change") is not None:
            from services.structured_semantic_edit import materialize_semantic_edit
            try:
                proposal = {key: patch[key] for key in ("operation", "target_rule_id", "change", "natural_language_explanation")}
                if patch.get("source_requirement_id"):
                    proposal["source_requirement_id"] = patch["source_requirement_id"]
                resolution = patch.get("target_resolution", {})
                expected = materialize_semantic_edit(sleec_text, proposal, resolution.get("rule_ids", []), resolution.get("addition_scope"))
                if (patch.get("proposed_rule") != expected["proposed_rule"]
                        or patch.get("declaration_text", "") != expected["declaration_text"]):
                    raise ValueError("The patch differs from its validated structured edit.")
                return {"valid": True, "errors": [], "warnings": ["The new meaning and its observability require stakeholder review."],
                        "meaning_verified": False, "validation_basis": "structured_edit"}
            except (ValueError, TypeError, KeyError, AttributeError) as exc:
                return {"valid": False, "errors": [str(exc)], "warnings": [], "meaning_verified": False}
        issue_text = str((issue or {}).get("value", "") or "")
        issue_type = str((issue or {}).get("issue_type", "") or "")
        operation = str(patch.get("operation", "") or "")
        proposed_rule = str(patch.get("proposed_rule", "") or "")
        original_rule = str(patch.get("original_rule", "") or "")

        vocabulary = self._check_vocabulary(
            patch, proposed_rule, original_rule,
            existing_events, existing_measures, existing_responses
        )
        alignment = self._check_diagnosis_alignment(
            issue_text, proposed_rule
        )
        operator = self._check_operator_semantics(
            operation, original_rule, proposed_rule, patch
        )
        temporal = self._check_temporal_alignment(
            issue_text, original_rule, proposed_rule
        )

        errors = []
        warnings = []
        for section in (vocabulary, alignment, operator, temporal):
            errors.extend(section.get("errors", []))
            warnings.extend(section.get("warnings", []))

        valid = all([
            vocabulary["passed"],
            alignment["passed"],
            operator["passed"],
            temporal["passed"],
        ])

        return {
            "valid": valid,
            "issue_type": issue_type,
            "operation": operation,
            "vocabulary_grounding": vocabulary,
            "diagnosis_alignment": alignment,
            "operator_validation": operator,
            "temporal_validation": temporal,
            "errors": errors,
            "warnings": warnings,
        }

    def _check_vocabulary(
        self, patch, proposed_rule, original_rule,
        existing_events, existing_measures, existing_responses
    ):
        existing = {
            str(x).lower()
            for x in (existing_events or []) + (existing_measures or []) + (existing_responses or [])
            if str(x).strip()
        }
        original_symbols = {x.lower() for x in self._symbols(original_rule)}
        proposed_symbols = self._symbols(proposed_rule)

        new_symbols = [
            s for s in proposed_symbols
            if s.lower() not in existing and s.lower() not in original_symbols
        ]

        operation = str(patch.get("operation", "") or "")
        allowed_new = set()
        if operation in {
            "event_specialization", "measure_specialization",
            "capability_refinement", "new_rule_generation"
        }:
            missing = str(
                patch.get("missing_element")
                or patch.get("new_event")
                or patch.get("new_measure")
                or patch.get("new_capability")
                or ""
            ).strip()
            if missing:
                allowed_new.add(missing.lower())

        unsupported = [s for s in new_symbols if s.lower() not in allowed_new]
        missing_declared = [
            s for s in allowed_new
            if s not in {x.lower() for x in proposed_symbols}
        ]

        errors = []
        if unsupported:
            errors.append("Unsupported new vocabulary: " + ", ".join(sorted(set(unsupported))))
        if missing_declared:
            errors.append(
                "Declared semantic element is not used in proposed rule: "
                + ", ".join(sorted(set(missing_declared)))
            )

        warnings = []
        if new_symbols:
            warnings.append("New semantic concept(s): " + ", ".join(sorted(set(new_symbols))))

        return {
            "passed": not errors,
            "new_symbols": sorted(set(new_symbols)),
            "unsupported_new_symbols": sorted(set(unsupported)),
            "errors": errors,
            "warnings": warnings,
        }

    def _check_diagnosis_alignment(self, issue_text, proposed_rule):
        issue_symbols = {
            x.lower()
            for x in self._symbols(issue_text)
        }

        proposed_symbols = {
            x.lower()
            for x in self._symbols(proposed_rule)
        }

        response_tokens = {
            x.lower()
            for x in self._response_symbols(issue_text)
        }

        diagnosis_context = issue_symbols - response_tokens
        shared_context = diagnosis_context & proposed_symbols
        missing_context = diagnosis_context - proposed_symbols

        response_overlap = bool(response_tokens & proposed_symbols)

        if diagnosis_context:
            context_coverage = len(shared_context) / len(diagnosis_context)
        else:
            context_coverage = 1.0

        context_aligned = context_coverage >= 0.50

        passed = (
            context_aligned
            and (response_overlap or not response_tokens)
        )

        errors = []

        if not shared_context and diagnosis_context:
            errors.append(
                "Patch does not preserve the diagnosed context."
            )

        if context_coverage < 0.50:
            errors.append(
                "Diagnosis alignment too weak: "
                f"{context_coverage:.0%} of diagnosed context preserved."
            )

        if response_tokens and not response_overlap:
            errors.append(
                "Patch does not preserve an implicated response/action."
            )

        warnings = []

        if missing_context:
            warnings.append(
                "Diagnosed context not represented in patch: "
                + ", ".join(sorted(missing_context)[:12])
            )

        return {
            "passed": passed,
            "context_coverage": round(context_coverage, 3),
            "shared_diagnosis_symbols": sorted(shared_context),
            "missing_diagnosis_symbols": sorted(missing_context),
            "response_aligned": response_overlap,
            "errors": errors,
            "warnings": warnings,
        }

    def _check_operator_semantics(self, operation, original_rule, proposed_rule, patch):
        errors = []
        warnings = []

        original_condition = self._condition(original_rule)
        proposed_condition = self._condition(proposed_rule)
        original_action = self._action(original_rule)
        proposed_action = self._action(proposed_rule)

        if operation in {"trigger_refinement", "trigger_strengthening"}:
            if not proposed_condition or proposed_condition == original_condition:
                errors.append("Trigger operator did not change the trigger condition.")

        elif operation == "defeater_introduction":
            if "unless" not in proposed_rule.lower():
                errors.append("Defeater introduction produced no explicit defeater.")

        elif operation == "event_specialization":
            missing = str(patch.get("missing_element") or patch.get("new_event") or "").strip()
            if not missing:
                errors.append("Event specialization did not declare a new event.")
            elif missing.lower() not in proposed_rule.lower():
                errors.append("Specialized event is not used in the proposed rule.")
            if original_action and proposed_action and original_action.lower() != proposed_action.lower():
                warnings.append("Event specialization also changed the response.")

        elif operation == "measure_specialization":
            missing = str(patch.get("missing_element") or patch.get("new_measure") or "").strip()
            if not missing:
                errors.append("Measure specialization did not declare a new measure.")
            elif missing.lower() not in proposed_rule.lower():
                errors.append("Specialized measure is not used in the proposed rule.")

        elif operation == "capability_refinement":
            missing = str(patch.get("missing_element") or patch.get("new_capability") or "").strip()
            if not missing:
                errors.append("Capability refinement did not declare a new capability.")
            elif missing.lower() not in proposed_rule.lower():
                errors.append("Refined capability is not used in the proposed rule.")

        elif operation == "new_rule_generation":
            if not proposed_rule.strip():
                errors.append("New-rule generation produced an empty rule.")

        return {"passed": not errors, "errors": errors, "warnings": warnings}

    def _check_temporal_alignment(self, issue_text, original_rule, proposed_rule):
        issue_bounds = self._time_bounds(issue_text)
        original_bounds = self._time_bounds(original_rule)
        proposed_bounds = self._time_bounds(proposed_rule)

        errors = []
        warnings = []

        if issue_bounds:
            if not proposed_bounds:
                errors.append(
                    "Diagnosis contains a temporal constraint, "
                    "but the proposed repair has no temporal constraint."
                )
            else:
                issue_norm = {x.lower() for x in issue_bounds}
                original_norm = {x.lower() for x in original_bounds}
                proposed_norm = {x.lower() for x in proposed_bounds}

                if (
                    original_norm
                    and issue_norm != original_norm
                    and proposed_norm == original_norm
                ):
                    errors.append(
                        "Temporal diagnosis not addressed: "
                        f"diagnosis={issue_bounds}, "
                        f"original={original_bounds}, "
                        f"proposed={proposed_bounds}."
                    )

                elif issue_norm == proposed_norm:
                    warnings.append(
                        "Proposed temporal bound matches the diagnosed temporal context."
                    )
                else:
                    warnings.append(
                        "Temporal diagnosis detected; confirm that the changed "
                        "bound intentionally resolves the diagnosed timing issue."
                    )

        return {
            "passed": not errors,
            "issue_time_bounds": issue_bounds,
            "original_time_bounds": original_bounds,
            "proposed_time_bounds": proposed_bounds,
            "errors": errors,
            "warnings": warnings,
        }

    def _symbols(self, text):
        tokens = re.findall(r"\b[A-Za-z_][A-Za-z0-9_]*\b", str(text or ""))
        result = []
        for token in tokens:
            low = token.lower()
            if low in self.SLEEC_KEYWORDS:
                continue
            if re.fullmatch(r"(?:Rule|R|r|c|C)\d+(?:_\d+)?", token):
                continue
            if low in {"minutes", "minute", "seconds", "second", "hours", "hour"}:
                continue
            result.append(token)
        return list(dict.fromkeys(result))

    def _response_symbols(self, text):
        responses = []
        for m in re.finditer(
            r"\bthen\s+(?:not\s+)?([A-Za-z_][A-Za-z0-9_]*)",
            str(text or ""), flags=re.IGNORECASE
        ):
            responses.append(m.group(1))
        return list(dict.fromkeys(responses))

    def _condition(self, rule):
        m = re.search(r"\bwhen\s+(.+?)\s+then\b", str(rule or ""), flags=re.IGNORECASE)
        return re.sub(r"\s+", " ", m.group(1)).strip() if m else ""

    def _action(self, rule):
        m = re.search(r"\bthen\s+(.+?)(?:\s+unless\s+|$)", str(rule or ""), flags=re.IGNORECASE)
        return re.sub(r"\s+", " ", m.group(1)).strip() if m else ""

    def _time_bounds(self, text):
        return [
            re.sub(r"\s+", " ", m.group(0)).strip()
            for m in re.finditer(
                r"\bwithin\s+\d+(?:\.\d+)?\s+(?:second|seconds|minute|minutes|hour|hours)\b",
                str(text or ""), flags=re.IGNORECASE
            )
        ]
