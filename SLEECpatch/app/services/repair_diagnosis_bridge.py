"""
repair_diagnosis_bridge.py

Bridge between formal SLEEC/LEGOS diagnosis evidence and SLEEC-PATCH
repair generation.

Design principles
-----------------
1. Detector-produced diagnosis is authoritative.
2. Original diagnosis evidence is never overwritten or discarded.
3. AST/repair-derived information is stored separately.
4. diagnosis_for() may be used as a legacy fallback when formal
   diagnosis evidence is unavailable.
5. Deterministic and LLM repair generation receive the same repair
   context.
"""

from copy import deepcopy
from typing import Any, Dict, Optional


class RepairDiagnosisBridge:
    """
    Preserve formal diagnosis evidence and enrich it with repair context.

    The returned structure separates:

        diagnosis
            Formal evidence produced by the detector.

        repair_context
            Information derived for repair generation.

    This prevents inferred repair information from being confused with
    formally diagnosed evidence.
    """

    def build(
        self,
        sleec_text: str,
        issue_type: str,
        issue: Any,
        diagnosis: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:

        issue_value = self._issue_value(issue)
        issue_id = self._issue_id(issue)

        # --------------------------------------------------------------
        # 1. Preserve the detector diagnosis exactly as received.
        # --------------------------------------------------------------

        original_diagnosis = deepcopy(diagnosis or {})

        if original_diagnosis:
            authoritative_diagnosis = deepcopy(original_diagnosis)
            provenance = "detector"

        else:
            # ----------------------------------------------------------
            # Legacy fallback only.
            #
            # diagnosis_for() must NOT replace a detector diagnosis.
            # It is used only when no formal diagnosis was supplied.
            # ----------------------------------------------------------
            authoritative_diagnosis = self._legacy_diagnosis(
                sleec_text=sleec_text,
                issue_type=issue_type,
                issue_value=issue_value,
            )

            provenance = "legacy_reconstructed"

        # --------------------------------------------------------------
        # 2. Build repair information separately.
        # --------------------------------------------------------------

        repair_context = self._build_repair_context(
            sleec_text=sleec_text,
            issue_type=issue_type,
            issue_value=issue_value,
            diagnosis=authoritative_diagnosis,
        )

        # --------------------------------------------------------------
        # 3. Return both.
        #
        # Nothing from the formal diagnosis is replaced by inferred
        # repair information.
        # --------------------------------------------------------------

        return {
            "issue_id": issue_id,
            "issue_type": issue_type,
            "issue_value": issue_value,

            "diagnosis_provenance": provenance,

            # Exact preserved formal diagnosis.
            "diagnosis": authoritative_diagnosis,

            # Repair-derived information.
            "repair_context": repair_context,
        }

    # ==================================================================
    # Repair-context construction
    # ==================================================================

    def _build_repair_context(
        self,
        sleec_text: str,
        issue_type: str,
        issue_value: str,
        diagnosis: Dict[str, Any],
    ) -> Dict[str, Any]:

        context: Dict[str, Any] = {
            "target_rule_ids": [],
            "candidate_related_rule_ids": [],
            "semantic_rule_ids": [],
            "addition_scope": None,

            "parsed_rules": [],
            "target_rules": [],

            "events": [],
            "measures": [],
            "responses": [],

            "triggers": [],
            "conditions": [],
            "defeaters": [],
            "deadlines": [],
        }

        # --------------------------------------------------------------
        # Preserve formally diagnosed rule IDs.
        # --------------------------------------------------------------

        affected_rule_ids = self._unique(
            diagnosis.get("affected_rule_ids", [])
        )

        context["target_rule_ids"] = list(affected_rule_ids)

        # --------------------------------------------------------------
        # Use the existing paper-repair resolution logic as a helper.
        #
        # IMPORTANT:
        # target_resolution receives the authoritative diagnosis.
        # We do not call diagnosis_for() here when detector evidence
        # already exists.
        # --------------------------------------------------------------

        try:
            from services.paper_repairs import target_resolution

            resolution = target_resolution(
                sleec_text,
                issue_type,
                diagnosis,
            )

            if isinstance(resolution, dict):

                resolved_rule_ids = self._unique(
                    resolution.get("rule_ids", [])
                )

                semantic_rule_ids = self._unique(
                    resolution.get(
                        "semantic_rule_ids",
                        resolved_rule_ids,
                    )
                )

                context["target_rule_ids"] = self._unique(
                    context["target_rule_ids"]
                    + resolved_rule_ids
                )

                context["semantic_rule_ids"] = semantic_rule_ids

                context["addition_scope"] = deepcopy(
                    resolution.get("addition_scope")
                )

                # Anything suggested structurally but not formally
                # diagnosed is explicitly labelled as a candidate.
                context["candidate_related_rule_ids"] = [
                    rule_id
                    for rule_id in semantic_rule_ids
                    if rule_id not in affected_rule_ids
                ]

        except Exception as exc:
            # Do not destroy the formal diagnosis because an enrichment
            # helper failed.
            context["resolution_warning"] = str(exc)

        # --------------------------------------------------------------
        # Parse the SLEEC model for structural repair information.
        # --------------------------------------------------------------

        try:
            from services.sleec_parser import parse_sleec_ast

            model = parse_sleec_ast(sleec_text)

            rules = list(
                getattr(
                    getattr(model, "ruleBlock", None),
                    "rules",
                    [],
                )
                or []
            )

            context["parsed_rules"] = rules

            allowed_ids = set(
                context["semantic_rule_ids"]
                or context["target_rule_ids"]
            )

            context["target_rules"] = [
                rule
                for rule in rules
                if getattr(rule, "name", None) in allowed_ids
            ]

            self._extract_rule_structure(
                context,
                context["target_rules"],
            )

        except Exception as exc:
            context["parser_warning"] = str(exc)

        return context

    # ==================================================================
    # Structural extraction
    # ==================================================================

    def _extract_rule_structure(
        self,
        context: Dict[str, Any],
        rules,
    ) -> None:
        """
        Extract useful rule structure without modifying the diagnosis.

        This is intentionally defensive because different parser versions
        may expose slightly different AST attributes.
        """

        triggers = []
        conditions = []
        responses = []
        defeaters = []
        deadlines = []

        for rule in rules:

            rule_id = getattr(rule, "name", None)

            trigger = self._first_attr(
                rule,
                "trigger",
                "condition",
                "when",
            )

            response = self._first_attr(
                rule,
                "response",
                "action",
                "then",
            )

            defeater = self._first_attr(
                rule,
                "defeater",
                "unless",
            )

            deadline = self._first_attr(
                rule,
                "deadline",
                "within",
                "time",
            )

            if trigger is not None:
                triggers.append({
                    "rule_id": rule_id,
                    "value": trigger,
                })

            if response is not None:
                responses.append({
                    "rule_id": rule_id,
                    "value": response,
                })

            if defeater is not None:
                defeaters.append({
                    "rule_id": rule_id,
                    "value": defeater,
                })

            if deadline is not None:
                deadlines.append({
                    "rule_id": rule_id,
                    "value": deadline,
                })

            # Some parser versions distinguish a Boolean condition from
            # the event trigger.
            condition = getattr(rule, "condition", None)

            if condition is not None:
                conditions.append({
                    "rule_id": rule_id,
                    "value": condition,
                })

        context["triggers"] = triggers
        context["conditions"] = conditions
        context["responses"] = responses
        context["defeaters"] = defeaters
        context["deadlines"] = deadlines

    # ==================================================================
    # Legacy diagnosis fallback
    # ==================================================================

    def _legacy_diagnosis(
        self,
        sleec_text: str,
        issue_type: str,
        issue_value: str,
    ) -> Dict[str, Any]:
        """
        Reconstruct a diagnosis only when formal detector evidence was
        not supplied.

        This exists for old persisted runs and backward compatibility.
        """

        try:
            from services.paper_repairs import diagnosis_for

            reconstructed = diagnosis_for(
                sleec_text,
                issue_type,
                issue_value,
            )

            if isinstance(reconstructed, dict):
                result = deepcopy(reconstructed)
            else:
                result = {}

        except Exception as exc:
            result = {
                "affected_rule_ids": [],
                "trace": [],
                "description": issue_value,
                "reconstruction_warning": str(exc),
            }

        result.setdefault("affected_rule_ids", [])
        result.setdefault("trace", [])
        result.setdefault("description", issue_value)

        return result

    # ==================================================================
    # Helpers
    # ==================================================================

    @staticmethod
    def _issue_value(issue: Any) -> str:
        if isinstance(issue, dict):
            return str(issue.get("value", ""))

        return str(issue or "")

    @staticmethod
    def _issue_id(issue: Any) -> str:
        if isinstance(issue, dict):
            return str(issue.get("id", ""))

        return ""

    @staticmethod
    def _unique(values):
        if not values:
            return []

        result = []

        for value in values:
            if value in (None, ""):
                continue

            if value not in result:
                result.append(value)

        return result

    @staticmethod
    def _first_attr(obj, *names):
        for name in names:
            if hasattr(obj, name):
                value = getattr(obj, name)

                if value is not None:
                    return value

        return None