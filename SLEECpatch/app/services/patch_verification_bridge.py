"""
Bridge between generated SLEEC-PATCH candidates and formal verification.

This bridge does not decide whether a repair is correct.
It preserves the generated candidate and prepares an executable patch
for the existing formal verification pipeline.
"""

from copy import deepcopy


class PatchVerificationBridge:

    def prepare(
        self,
        sleec_text,
        candidate,
        allowed_rule_ids=None,
        addition_scope=None,
        repair_evidence=None,
    ):
        original_candidate = deepcopy(candidate or {})

        result = {
            "success": False,
            "stage": "pre_verification",
            "generated_candidate": original_candidate,
            "executable_patch": None,
            "materialization": {
                "required": False,
                "success": False,
                "error": None,
            },
            "provenance": self._build_provenance(
                original_candidate,
                repair_evidence,
            ),
        }

        if not original_candidate:
            result["materialization"]["error"] = (
                "Empty repair candidate."
            )
            return result

        try:
            # Structured semantic LLM candidate.
            if "change" in original_candidate:
                result["materialization"]["required"] = True

                from services.structured_semantic_edit import (
                    materialize_semantic_edit,
                )

                # Preserve exact GPT output. Modify only the executable copy.
                semantic_candidate = deepcopy(original_candidate)

                operation = str(
                    semantic_candidate.get("operation") or ""
                ).strip()

                if operation == "new_rule_generation":
                    # A new rule does not edit an existing rule.
                    semantic_candidate["target_rule_id"] = None

                    authoritative_source_id = None

                    if isinstance(addition_scope, dict):
                        authoritative_source_id = (
                            addition_scope.get("source_id")
                        )

                    if not authoritative_source_id:
                        diagnosis = (
                            (repair_evidence or {}).get("diagnosis", {})
                            or {}
                        )
                        authoritative_source_id = diagnosis.get(
                            "source_id"
                        )

                    generated_source_id = semantic_candidate.get(
                        "source_requirement_id"
                    )

                    # Reject a GPT source that conflicts with the
                    # authoritative selected concern.
                    if (
                        generated_source_id
                        and authoritative_source_id
                        and str(generated_source_id)
                        != str(authoritative_source_id)
                    ):
                        raise ValueError(
                            "GPT new_rule_generation is grounded in "
                            f"{generated_source_id!r}, but the selected "
                            "concern is "
                            f"{authoritative_source_id!r}."
                        )

                    # Compatibility with GPT proposals that omitted the
                    # source ID. Use only the authoritative diagnosis.
                    if (
                        not generated_source_id
                        and authoritative_source_id
                    ):
                        semantic_candidate[
                            "source_requirement_id"
                        ] = authoritative_source_id

                executable = materialize_semantic_edit(
                    sleec_text,
                    semantic_candidate,
                    list(allowed_rule_ids or []),
                    deepcopy(addition_scope),
                )

                if not isinstance(executable, dict):
                    raise ValueError(
                        "Semantic materialization did not return a patch."
                    )

            # Already executable deterministic or legacy candidate.
            else:
                executable = deepcopy(original_candidate)

            result["materialization"]["success"] = True

            executable.setdefault(
                "source",
                original_candidate.get("source", "unknown"),
            )

            executable.setdefault(
                "operation",
                original_candidate.get("operation"),
            )

            if original_candidate.get("target_rule_id") is not None:
                executable.setdefault(
                    "target_rule_id",
                    original_candidate.get("target_rule_id"),
                )

            executable["allowed_rule_ids"] = list(
                allowed_rule_ids or []
            )

            executable["addition_scope"] = deepcopy(
                addition_scope
            )

            # Preserve the exact generated proposal.
            executable["generated_candidate"] = (
                original_candidate
            )

            # Preserve diagnosis/target provenance.
            executable["repair_provenance"] = deepcopy(
                result["provenance"]
            )

            result["executable_patch"] = executable
            result["success"] = True

            return result

        except Exception as exc:
            result["materialization"]["success"] = False
            result["materialization"]["error"] = str(exc)
            return result

    def prepare_deterministic(
        self,
        candidate,
        repair_evidence=None,
    ):
        original_candidate = deepcopy(candidate or {})

        if not original_candidate:
            return {
                "success": False,
                "stage": "pre_verification",
                "generated_candidate": {},
                "executable_patch": None,
                "materialization": {
                    "required": False,
                    "success": False,
                    "error": (
                        "Empty deterministic repair candidate."
                    ),
                },
                "provenance": self._build_provenance(
                    {},
                    repair_evidence,
                ),
            }

        executable = deepcopy(original_candidate)

        executable["generated_candidate"] = (
            original_candidate
        )

        executable["repair_provenance"] = (
            self._build_provenance(
                original_candidate,
                repair_evidence,
            )
        )

        return {
            "success": True,
            "stage": "pre_verification",
            "generated_candidate": original_candidate,
            "executable_patch": executable,
            "materialization": {
                "required": False,
                "success": True,
                "error": None,
            },
            "provenance": deepcopy(
                executable["repair_provenance"]
            ),
        }

    @staticmethod
    def _build_provenance(
        candidate,
        repair_evidence,
    ):
        evidence = repair_evidence or {}
        diagnosis = evidence.get("diagnosis", {})
        context = evidence.get("repair_context", {})

        return {
            "source": candidate.get(
                "source",
                "unknown",
            ),
            "operation": candidate.get("operation"),
            "target_rule_id": candidate.get(
                "target_rule_id"
            ),
            "issue_id": evidence.get("issue_id"),
            "issue_type": evidence.get("issue_type"),
            "issue_value": evidence.get("issue_value"),
            "diagnosis_provenance": evidence.get(
                "diagnosis_provenance"
            ),
            "source_requirement_id": diagnosis.get(
                "source_id"
            ),
            "affected_rule_ids": deepcopy(
                diagnosis.get("affected_rule_ids", [])
            ),
            "target_rule_ids": deepcopy(
                context.get("target_rule_ids", [])
            ),
            "semantic_rule_ids": deepcopy(
                context.get("semantic_rule_ids", [])
            ),
            "candidate_related_rule_ids": deepcopy(
                context.get(
                    "candidate_related_rule_ids",
                    []
                )
            ),
        }
