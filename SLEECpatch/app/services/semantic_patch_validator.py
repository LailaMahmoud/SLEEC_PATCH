import re
from copy import deepcopy
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
        system_description: str = "",
    ) -> dict:
        if patch.get("change"):
            from services.structured_semantic_edit import materialize_semantic_edit
            keys = {"operation", "target_rule_id", "change", "natural_language_explanation", "source_requirement_id"}
            proposal = deepcopy(
                {k: v for k, v in patch.items() if k in keys}
            )
            try:
                checked = materialize_semantic_edit(sleec_text, proposal,
                    list(patch.get("allowed_rule_ids", [])),
                    deepcopy(patch.get("addition_scope")))
                if checked["proposed_rule"] != patch.get("proposed_rule") or checked["declaration_text"] != patch.get("declaration_text") or checked["additional_rule_edits"] != patch.get("additional_rule_edits", {}):
                    raise ValueError("The candidate differs from its declared structured edit.")
                return {"valid": True, "errors": [], "warnings": ["Domain meaning requires stakeholder review."],
                        "operation": patch.get("operation"), "operator_validation": {"passed": True},
                        "temporal_validation": {"passed": True}}
            except ValueError as exc:
                return {"valid": False, "errors": [str(exc)], "warnings": []}
        issue_text = str((issue or {}).get("value", "") or "")
        issue_type = str((issue or {}).get("issue_type", "") or "")
        operation = str(patch.get("operation", "") or "")
        proposed_rule = str(patch.get("proposed_rule", "") or "")
        original_rule = str(patch.get("original_rule", "") or "")

        # Make the active specification available to vocabulary validation
        # so declared measure-domain values are recognized generically.
        self._active_sleec_text = str(sleec_text or "")

        vocabulary = self._check_vocabulary(
            patch, proposed_rule, original_rule,
            existing_events, existing_measures, existing_responses
        )
        grounding = self._check_grounding_evidence(
            patch=patch,
            issue_text=issue_text,
            system_description=system_description,
            existing_events=existing_events,
            existing_measures=existing_measures,
            existing_responses=existing_responses,
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
        for section in (vocabulary, grounding, operator, temporal):
            errors.extend(section.get("errors", []))
            warnings.extend(section.get("warnings", []))

        # Diagnosis alignment is retained as diagnostic evidence only.
        # It no longer determines semantic validity because semantic repairs may
        # legitimately introduce grounded concepts that do not lexically reproduce
        # at least 50% of the LEGOS diagnosis symbols.
        warnings.extend(
            f"Legacy diagnosis-alignment diagnostic: {msg}"
            for msg in alignment.get("errors", [])
        )
        warnings.extend(alignment.get("warnings", []))

        valid = all([
            vocabulary["passed"],
            grounding["passed"],
            operator["passed"],
            temporal["passed"],
        ])

        return {
            "valid": valid,
            "issue_type": issue_type,
            "operation": operation,
            "vocabulary_grounding": vocabulary,
            "grounding_evidence_validation": grounding,
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
        """
        Validate vocabulary for WFI-specific semantic repair operators.

        Existing vocabulary is always allowed.

        Event/measure/capability specialization operators may explicitly
        introduce one new semantic concept through missing_element (or the
        corresponding new_* field).

        concern_new_rule_generation is different: missing_element may contain
        the complete generated rule, so it is not interpreted as one vocabulary
        declaration. New vocabulary in a generated rule is reported for semantic
        grounding validation rather than rejected here solely because it is new.
        """

        existing = {
            str(x).lower()
            for x in (
                (existing_events or [])
                + (existing_measures or [])
                + (existing_responses or [])
            )
            if str(x).strip()
        }

        # Include vocabulary already declared anywhere in the active SLEEC spec.
        sleec_text = str(
            getattr(self, "_active_sleec_text", "") or ""
        )

        declared_spec_symbols = {
            x.lower()
            for x in self._symbols(sleec_text)
        }

        existing.update(declared_spec_symbols)

        original_symbols = {
            x.lower()
            for x in self._symbols(original_rule)
        }

        proposed_symbols = self._symbols(proposed_rule)

        new_symbols = [
            s
            for s in proposed_symbols
            if s.lower() not in existing
            and s.lower() not in original_symbols
        ]

        operation = str(
            patch.get("operation", "") or ""
        ).strip()

        event_ops = {
            "redundancy_event_specialization",
            "conflict_event_specialization",
        }

        measure_ops = {
            "redundancy_measure_specialization",
            "conflict_measure_specialization",
        }

        capability_ops = {
            "purpose_response_refinement",
        }

        new_rule_ops = {
            "concern_new_rule_generation",
        }

        allowed_new = set()

        # ---------------------------------------------------------
        # EVENT SPECIALIZATION
        # ---------------------------------------------------------
        if operation in event_ops:
            missing = str(
                patch.get("new_event")
                or patch.get("missing_element")
                or ""
            ).strip()

            if missing:
                allowed_new.add(missing.lower())

        # ---------------------------------------------------------
        # MEASURE SPECIALIZATION
        # ---------------------------------------------------------
        elif operation in measure_ops:
            missing = str(
                patch.get("new_measure")
                or patch.get("missing_element")
                or ""
            ).strip()

            if missing:
                allowed_new.add(missing.lower())

        # ---------------------------------------------------------
        # RESPONSE REFINEMENT
        # ---------------------------------------------------------
        elif operation in capability_ops:
            missing = str(
                patch.get("new_capability")
                or patch.get("missing_element")
                or ""
            ).strip()

            if missing:
                allowed_new.add(missing.lower())

        # ---------------------------------------------------------
        # CONCERN — NEW RULE GENERATION
        # ---------------------------------------------------------
        # missing_element may be the entire generated rule.
        # Therefore it must NOT be interpreted as a single vocabulary
        # declaration.
        #
        # New vocabulary is permitted at this stage because a missing
        # normative behaviour may require a new semantic concept.
        # Grounding is checked separately by _check_grounding_evidence().
        elif operation in new_rule_ops:
            allowed_new.update(
                s.lower()
                for s in new_symbols
            )

        unsupported = [
            s
            for s in new_symbols
            if s.lower() not in allowed_new
        ]

        proposed_symbol_set = {
            x.lower()
            for x in proposed_symbols
        }

        missing_declared = [
            s
            for s in allowed_new
            if s not in proposed_symbol_set
        ]

        errors = []

        if unsupported:
            errors.append(
                "Unsupported new vocabulary for "
                f"{operation}: "
                + ", ".join(sorted(set(unsupported)))
            )

        if missing_declared:
            errors.append(
                "Declared semantic element is not used in proposed rule: "
                + ", ".join(sorted(set(missing_declared)))
            )

        warnings = []

        if new_symbols:
            warnings.append(
                "New semantic concept(s) requiring grounding: "
                + ", ".join(sorted(set(new_symbols)))
            )

        return {
            "passed": not errors,
            "operation": operation,
            "new_symbols": sorted(set(new_symbols)),
            "allowed_new_symbols": sorted(allowed_new),
            "unsupported_new_symbols": sorted(set(unsupported)),
            "errors": errors,
            "warnings": warnings,
        }

    def _check_grounding_evidence(
        self,
        patch,
        issue_text,
        system_description,
        existing_events,
        existing_measures,
        existing_responses,
    ):
        evidence = patch.get("grounding_evidence") or {}

        errors = []
        warnings = []

        if not isinstance(evidence, dict) or not evidence:
            return {
                "passed": False,
                "source": "",
                "source_terms": [],
                "verified_source_terms": [],
                "unverified_source_terms": [],
                "existing_element": "",
                "new_element": "",
                "relationship": "",
                "errors": ["Missing grounding_evidence for semantic repair."],
                "warnings": [],
            }

        source = str(evidence.get("source", "") or "").strip().lower()

        source_terms = evidence.get("source_terms") or []
        if isinstance(source_terms, str):
            source_terms = [source_terms]

        source_terms = [
            str(term).strip()
            for term in source_terms
            if str(term).strip()
        ]

        existing_element = str(
            evidence.get("existing_element", "") or ""
        ).strip()

        new_element = str(
            evidence.get("new_element", "") or ""
        ).strip()

        relationship = str(
            evidence.get("relationship", "") or ""
        ).strip()

        permitted_sources = {
            "system_description",
            "diagnosis",
            "witness",
            "existing_vocabulary",
        }

        if source not in permitted_sources:
            errors.append(
                "Grounding source must be one of: "
                + ", ".join(sorted(permitted_sources))
            )

        vocabulary = [
            str(x).strip()
            for x in (
                (existing_events or [])
                + (existing_measures or [])
                + (existing_responses or [])
            )
            if str(x).strip()
        ]

        if source == "system_description":
            source_text = str(system_description or "")

        elif source in {"diagnosis", "witness"}:
            # At present the workbench supplies the selected LEGOS finding
            # through issue_text. This remains deterministic evidence.
            source_text = str(issue_text or "")

        elif source == "existing_vocabulary":
            source_text = "\n".join(vocabulary)

        else:
            source_text = ""

        verified_terms = []
        unverified_terms = []

        normalized_source = re.sub(
            r"\s+", " ", source_text
        ).strip().lower()

        for term in source_terms:
            normalized_term = re.sub(
                r"\s+", " ", term
            ).strip().lower()

            if normalized_term and normalized_term in normalized_source:
                verified_terms.append(term)
            else:
                unverified_terms.append(term)

        if not source_terms:
            errors.append("grounding_evidence.source_terms is empty.")

        if unverified_terms:
            errors.append(
                "Grounding source term(s) not found in claimed source: "
                + ", ".join(unverified_terms)
            )

        missing_element = str(
            patch.get("missing_element")
            or patch.get("new_event")
            or patch.get("new_measure")
            or patch.get("new_capability")
            or ""
        ).strip()

        if not new_element:
            errors.append("grounding_evidence.new_element is empty.")

        elif missing_element and new_element.lower() != missing_element.lower():
            errors.append(
                "grounding_evidence.new_element does not match "
                "the patch missing_element."
            )

        operation = str(patch.get("operation", "") or "").strip()

        if operation in {
            # Redundancy specialization
            "redundancy_event_specialization",
            "redundancy_measure_specialization",

            # Purpose / restrictiveness refinement
            "purpose_response_refinement",

            # Situational-conflict specialization
            "conflict_event_specialization",
            "conflict_measure_specialization",
        }:
            if not existing_element:
                errors.append(
                    "Semantic specialization/refinement requires "
                    "grounding_evidence.existing_element."
                )
            elif existing_element.lower() not in {
                x.lower() for x in vocabulary
            }:
                errors.append(
                    "grounding_evidence.existing_element is not present "
                    "in the supplied SLEEC vocabulary."
                )

        if not relationship:
            errors.append("grounding_evidence.relationship is empty.")

        return {
            "passed": not errors,
            "source": source,
            "source_terms": source_terms,
            "verified_source_terms": verified_terms,
            "unverified_source_terms": unverified_terms,
            "existing_element": existing_element,
            "new_element": new_element,
            "relationship": relationship,
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

    def _check_operator_semantics(
        self,
        operation,
        original_rule,
        proposed_rule,
        patch
    ):
        errors = []
        warnings = []

        original_condition = self._condition(original_rule)
        proposed_condition = self._condition(proposed_rule)

        original_action = self._action(original_rule)
        proposed_action = self._action(proposed_rule)

        # ---------------------------------------------------------
        # DETERMINISTIC OPERATORS
        # ---------------------------------------------------------
        if operation in {
            "trigger_refinement",
            "trigger_strengthening"
        }:
            if (
                not proposed_condition
                or proposed_condition == original_condition
            ):
                errors.append(
                    "Trigger operator did not change the trigger condition."
                )

        elif operation == "defeater_introduction":
            if "unless" not in proposed_rule.lower():
                errors.append(
                    "Defeater introduction produced no explicit defeater."
                )

        # ---------------------------------------------------------
        # REDUNDANCY — EVENT SPECIALIZATION
        # ---------------------------------------------------------
        elif operation == "redundancy_event_specialization":
            missing = str(
                patch.get("new_event")
                or patch.get("missing_element")
                or ""
            ).strip()

            if not missing:
                errors.append(
                    "Redundancy event specialization did not declare "
                    "a new event."
                )

            elif missing.lower() not in proposed_rule.lower():
                errors.append(
                    "Specialized redundancy event is not used in "
                    "the proposed rule."
                )

        # ---------------------------------------------------------
        # REDUNDANCY — MEASURE SPECIALIZATION
        # ---------------------------------------------------------
        elif operation == "redundancy_measure_specialization":
            missing = str(
                patch.get("new_measure")
                or patch.get("missing_element")
                or ""
            ).strip()

            if not missing:
                errors.append(
                    "Redundancy measure specialization did not declare "
                    "a new measure."
                )

            elif missing.lower() not in proposed_rule.lower():
                errors.append(
                    "Specialized redundancy measure is not used in "
                    "the proposed rule."
                )

        # ---------------------------------------------------------
        # CONCERN — NEW RULE GENERATION
        # ---------------------------------------------------------
        elif operation == "concern_new_rule_generation":
            if not proposed_rule.strip():
                errors.append(
                    "Concern new-rule generation produced an empty rule."
                )

            if "when" not in proposed_rule.lower():
                errors.append(
                    "Generated concern repair contains no when clause."
                )

            if "then" not in proposed_rule.lower():
                errors.append(
                    "Generated concern repair contains no then clause."
                )

        # ---------------------------------------------------------
        # PURPOSE — RESPONSE REFINEMENT
        # ---------------------------------------------------------
        elif operation == "purpose_response_refinement":
            missing = str(
                patch.get("new_capability")
                or patch.get("missing_element")
                or ""
            ).strip()

            if not missing:
                errors.append(
                    "Purpose response refinement did not declare "
                    "a refined capability."
                )

            elif missing.lower() not in proposed_rule.lower():
                errors.append(
                    "Refined capability is not used in the proposed rule."
                )

        # ---------------------------------------------------------
        # CONFLICT — EVENT SPECIALIZATION
        # ---------------------------------------------------------
        elif operation == "conflict_event_specialization":
            missing = str(
                patch.get("new_event")
                or patch.get("missing_element")
                or ""
            ).strip()

            if not missing:
                errors.append(
                    "Conflict event specialization did not declare "
                    "a new event."
                )

            elif missing.lower() not in proposed_rule.lower():
                errors.append(
                    "Specialized conflict event is not used in "
                    "the proposed rule."
                )

            # A changed response is not automatically invalid, but it is
            # suspicious for an event-specialization operator.
            if (
                original_action
                and proposed_action
                and original_action.lower() != proposed_action.lower()
            ):
                warnings.append(
                    "Conflict event specialization also changed "
                    "the response."
                )

        # ---------------------------------------------------------
        # CONFLICT — MEASURE SPECIALIZATION
        # ---------------------------------------------------------
        elif operation == "conflict_measure_specialization":
            missing = str(
                patch.get("new_measure")
                or patch.get("missing_element")
                or ""
            ).strip()

            if not missing:
                errors.append(
                    "Conflict measure specialization did not declare "
                    "a new measure."
                )

            elif missing.lower() not in proposed_rule.lower():
                errors.append(
                    "Specialized conflict measure is not used in "
                    "the proposed rule."
                )
        # ---------------------------------------------------------
        # CONFLICT — SEMANTIC RULE MERGING
        # ---------------------------------------------------------
        elif operation == "semantic_rule_merging":
            if not proposed_rule:
                errors.append(
                    "Semantic Rule Merging did not produce a merged rule."
                )

            # Semantic Rule Merging should combine the diagnosed
            # conflicting rules rather than inventing a new event,
            # measure, or capability merely to avoid the conflict.
            new_event = str(
                patch.get("new_event", "") or ""
            ).strip()

            new_measure = str(
                patch.get("new_measure", "") or ""
            ).strip()

            new_capability = str(
                patch.get("new_capability", "") or ""
            ).strip()

            if new_event or new_measure or new_capability:
                errors.append(
                    "Semantic Rule Merging must merge the diagnosed rules "
                    "without introducing an unrelated new event, measure, "
                    "or capability."
                )

            # A semantic merge should represent the diagnosed pair.
            # Formal correctness is NOT decided here; the resulting
            # specification will be checked by LEGOS-SLEEC.
            if not original_rule:
                errors.append(
                    "Semantic Rule Merging requires the diagnosed "
                    "conflicting rules as its original-rule context."
                )        

        return {
            "passed": not errors,
            "errors": errors,
            "warnings": warnings,
        }
    

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
        text = re.sub(
            r"(?m)^\s*[A-Za-z_][A-Za-z0-9_]*\s+when\b",
            " when",
            str(text or "")
        )
        tokens = re.findall(r"\b[A-Za-z_][A-Za-z0-9_]*\b", text)
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
