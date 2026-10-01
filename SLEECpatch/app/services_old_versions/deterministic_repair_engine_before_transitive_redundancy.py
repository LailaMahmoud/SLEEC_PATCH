import re


class DeterministicRepairEngine:

    def generate(self, issue_type, selected_issue, rules, operators, existing_events=None):
        self._events = {str(event) for event in (existing_events or [])}
        patches = []

        if issue_type in ["conflicts", "situational_conflicts"]:
            patches.extend(
                self.generate_conflict_patches(
                    issue_type,
                    selected_issue,
                    rules,
                    operators
                )
            )

        if issue_type == "concerns":
            patches.extend(
                self.generate_concern_patches(
                    selected_issue,
                    rules,
                    operators
                )
            )

        if issue_type == "purpose_blocking":
            patches.extend(
                self.generate_purpose_patches(
                    selected_issue,
                    rules,
                    operators
                )
            )

        if issue_type == "redundancies":
            patches.extend(
                self.generate_redundancy_patches(
                    selected_issue,
                    rules,
                    operators
                )
            )

        if (
            "temporal_refinement" in operators
            and issue_type in {
                "concerns",
                "conflicts",
                "situational_conflicts",
            }
        ):
            temporal_patch = self.generate_temporal_refinement_patch(
                issue_type=issue_type,
                selected_issue=selected_issue,
                rules=rules,
            )
            if temporal_patch:
                patches.append(temporal_patch)

        return self.drop_noop_patches(patches)

    def drop_noop_patches(self, patches):
        """Discard patches that leave the rule unchanged.

        A transform returns the original rule when its context is empty or was
        entirely event-based (no valid deterministic repair). Emitting such a
        no-op wastes a verification slot and, more importantly, would keep the
        issue from falling through to the LLM. Deletions keep their empty body.
        """
        deletions = {
            "rule_removal",
            "delete",
            "delete_rule",
            "delete_redundant_rule",
        }
        kept = []

        for patch in patches:
            operation = str(patch.get("operation", ""))

            if operation in deletions:
                kept.append(patch)
                continue

            proposed = self.normalize_rule_text(patch.get("proposed_rule", ""))
            original = self.normalize_rule_text(patch.get("original_rule", ""))

            if not proposed or proposed == original:
                continue

            kept.append(patch)

        return kept

    def normalize_rule_text(self, text):
        return re.sub(r"\s+", " ", str(text or "")).strip().lower()

    def generate_redundancy_patches(self, selected_issue, rules, operators):
        patches = []
        issue_text = str(selected_issue)

        rule_id = self.extract_rule_id(issue_text)
        target_rule = self.find_rule(rule_id, rules)
        original_rule = (
            self.rule_to_text(target_rule)
            if target_rule
            else issue_text
        )

        # =========================================================
        # 1. RULE REMOVAL
        # =========================================================

        if "rule_removal" in operators:
            redundant_rule, survivor_rule = self.find_redundant_rule_pair(
                selected_issue,
                rules
            )

            if redundant_rule and survivor_rule:
                redundant_id = redundant_rule["id"]
                survivor_id = survivor_rule["id"]

                patches.append({
                    "patch_id": f"d_remove_{redundant_id}",
                    "id": f"d_remove_{redundant_id}",
                    "source": "deterministic",
                    "issue_type": "redundancies",
                    "operation": "rule_removal",
                    "target_rule_id": redundant_id,
                    "original_rule": self.rule_to_text(redundant_rule),
                    "proposed_rule": "",
                    "survivor_rule_id": survivor_id,
                    "natural_language_explanation": (
                        f"Remove {redundant_id} because it duplicates "
                        f"{survivor_id}, which remains in the specification."
                    )
                })

        # =========================================================
        # 2. DEFEATER PROPAGATION
        # =========================================================

        if (
            "defeater_propagation" in operators
            and target_rule
            and target_rule.get("defeater")
        ):
            proposed_rule = self.propagate_defeater(target_rule)

            # None means the formal transformation is not applicable.
            if proposed_rule:
                patches.append({
                    "patch_id": f"d_propagate_{rule_id}",
                    "id": f"d_propagate_{rule_id}",
                    "source": "deterministic",
                    "issue_type": "redundancies",
                    "operation": "defeater_propagation",
                    "target_rule_id": rule_id,
                    "original_rule": original_rule,
                    "proposed_rule": proposed_rule,
                    "natural_language_explanation": (
                        f"Propagate the defeater condition of {rule_id} "
                        "into its trigger according to the transformation "
                        "'when A then B unless C' -> "
                        "'when A and not C then B'."
                    )
                })

        return patches
    def generate_existential_concern_patches(
        self,
        selected_issue,
        rules,
        operators
    ):
        """
        Generate deterministic candidates for existential insufficiencies:

            cX exists E and C

        where:
            E = witnessed undesirable event/capability/state
            C = diagnosis-grounded undesirable context

        Generic across all use cases.

        Deterministic operators:
            1. trigger_strengthening
            2. defeater_introduction
            3. rule_decomposition

        Every returned object is only a CANDIDATE.
        Formal correctness is decided later by LEGOS-SLEEC.
        """
        patches = []

        concern = self.parse_concern(selected_issue)
        condition = self.clean_condition(
            concern.get("condition", "")
        )

        if not condition:
            return patches

        parts = self.split_top_level_and(condition)

        # Existential concern needs:
        #     witnessed capability/event + diagnostic context
        if len(parts) < 2:
            return patches

        witnessed_action = self.clean_condition(parts[0])

        if (
            not witnessed_action
            or self.is_measure_only_expression(witnessed_action)
        ):
            return patches

        bad_context = self.normalize_boolean_expression(
            " and ".join(parts[1:])
        )

        if not bad_context:
            return patches

        producers = self.find_existential_concern_producers(
            witnessed_action,
            rules
        )

        if not producers:
            return patches

        used_rule_ids = {
            str(r.get("id", ""))
            for r in rules
            if isinstance(r, dict)
        }

        desired_action = self.opposite_action(witnessed_action)

        if not desired_action:
            return patches

        for producer in producers:
            rule_id = str(producer.get("id", "")).strip()

            if not rule_id:
                continue

            original_rule = self.rule_to_text(producer)

            # Determine whether the diagnosis context adds usable
            # information to this particular producer.
            usable_context = self.concern_specific_context(
                condition,
                producer.get("condition", "")
            )

            usable_context = self.normalize_boolean_expression(
                usable_context
            )

            # If this producer already handles the diagnosed measure/context,
            # do not manufacture contradictory or redundant candidates.
            if not usable_context:
                continue

            # ----------------------------------------------------------
            # 1. TRIGGER STRENGTHENING
            #
            # exists E and C
            #
            #     when T then E
            #
            # becomes:
            #
            #     when T and NOT(C) then E
            # ----------------------------------------------------------
            if "trigger_strengthening" in operators:
                proposed_rule = self.refine_trigger_against_condition(
                    producer,
                    usable_context
                )

                if (
                    proposed_rule
                    and proposed_rule != original_rule
                ):
                    patches.append({
                        "patch_id": f"d_exist_strengthen_{rule_id}",
                        "id": f"d_exist_strengthen_{rule_id}",
                        "source": "deterministic",
                        "issue_type": "concerns",
                        "operation": "trigger_strengthening",
                        "target_rule_id": rule_id,
                        "target_branch_type": "main",
                        "target_branch_action": producer.get(
                            "action", ""
                        ),
                        "original_rule": original_rule,
                        "proposed_rule": proposed_rule,
                        "natural_language_explanation": (
                            "Strengthen the producer trigger with the "
                            "complement of the diagnosis-grounded "
                            "undesirable context."
                        )
                    })

            # ----------------------------------------------------------
            # 2. DEFEATER INTRODUCTION
            #
            #     when T then E
            #
            # becomes:
            #
            #     when T then E unless C
            # ----------------------------------------------------------
            if "defeater_introduction" in operators:
                proposed_rule = self.add_defeater(
                    producer,
                    usable_context
                )

                if (
                    proposed_rule
                    and proposed_rule != original_rule
                ):
                    patches.append({
                        "patch_id": f"d_exist_defeater_{rule_id}",
                        "id": f"d_exist_defeater_{rule_id}",
                        "source": "deterministic",
                        "issue_type": "concerns",
                        "operation": "defeater_introduction",
                        "target_rule_id": rule_id,
                        "target_branch_type": "main",
                        "target_branch_action": producer.get(
                            "action", ""
                        ),
                        "original_rule": original_rule,
                        "proposed_rule": proposed_rule,
                        "natural_language_explanation": (
                            "Introduce the diagnosis-grounded undesirable "
                            "context as an exception to the producer rule."
                        )
                    })

            # ----------------------------------------------------------
            # 3. RULE DECOMPOSITION
            #
            #     T and C     -> NOT E
            #     T and NOT C -> E
            # ----------------------------------------------------------
            if "rule_decomposition" in operators:
                proposed_rule = self.decompose_rule_for_concern(
                    producer,
                    usable_context,
                    desired_action,
                    used_rule_ids
                )

                if proposed_rule:
                    patches.append({
                        "patch_id": f"d_exist_decompose_{rule_id}",
                        "id": f"d_exist_decompose_{rule_id}",
                        "source": "deterministic",
                        "issue_type": "concerns",
                        "operation": "rule_decomposition",
                        "target_rule_id": rule_id,
                        "target_branch_type": "main",
                        "target_branch_action": producer.get(
                            "action", ""
                        ),
                        "original_rule": original_rule,
                        "proposed_rule": proposed_rule,
                        "natural_language_explanation": (
                            "Decompose the producer into complementary "
                            "diagnosis-grounded cases, preventing the "
                            "witnessed capability in the undesirable case."
                        )
                    })

        return patches
    def generate_concern_patches(self, selected_issue, rules, operators):
        """
        Generate deterministic candidate repairs for an insufficiency / concern.

        Target selection is branch-aware. Whole-rule trigger strengthening and
        decomposition are generated only when the diagnosis is related to the
        rule's main response. If the diagnosis is related to an alternative
        defeater response, only a diagnosis-grounded defeater refinement may
        be attempted.

        Formal correctness is decided later by applying each candidate to the
        complete SLEEC specification and re-running LEGOS-SLEEC.
        """
        patches = []
        concern = self.parse_concern(selected_issue)

        # Existential insufficiencies use the generic producer-based
        # deterministic repair path. This is domain-independent and
        # applies across all use cases.
        is_existential_concern = bool(
            re.search(
                r"\bc\d+(?:_\d+)?\s+exists\b",
                str(selected_issue or ""),
                flags=re.IGNORECASE
            )
        )

        if is_existential_concern:
            return self.generate_existential_concern_patches(
                selected_issue,
                rules,
                operators
            )

        # Standard concerns keep the existing ALMI-compatible path.
        target_context = self.find_best_related_rule_context(
            selected_issue, rules
        )
        if not target_context:
            return patches

        target_rule = target_context["rule"]
        branch_type = target_context["branch_type"]
        branch_action = target_context.get("branch_action", "")
        original_rule = self.rule_to_text(target_rule)

        used_rule_ids = {
            str(r.get("id", ""))
            for r in rules
            if isinstance(r, dict)
        }

        diagnosis_context = (
            concern.get("condition")
            or target_rule.get("condition", "")
            )

        # Existential insufficiency:
        # remove the witnessed capability/state before deriving repair context.
        is_existential_concern = bool(
            re.search(
                r"\bc\d+(?:_\d+)?\s+exists\b",
                str(selected_issue or ""),
                flags=re.IGNORECASE
            )
        )

        if is_existential_concern:
            context = self.concern_specific_context(
                diagnosis_context,
                target_rule.get("condition", "")
            )
        else:
            context = self.specific_context(
                diagnosis_context,
                target_rule.get("condition", "")
            )

        context = self.normalize_boolean_expression(context)

        concern_action = concern.get("action", "").strip()
        desired_action = self.opposite_action(concern_action)
        desired_action = desired_action or target_rule.get("action", "")
        desired_action = self.apply_concern_deadline(
            desired_action,
            concern.get("temporal", "")
        )

        main_branch_target = branch_type == "main"

        # Trigger strengthening changes the main obligation, so it is
        # applicable only when the diagnosed target is the main response.
        if (
            "trigger_strengthening" in operators
            and context
            and main_branch_target
        ):
            proposed_rule = self.strengthen_trigger_with_condition(
                target_rule, context
            )
            if proposed_rule and proposed_rule != original_rule:
                patches.append({
                    "patch_id": f'd_strengthen_{target_rule["id"]}',
                    "id": f'd_strengthen_{target_rule["id"]}',
                    "source": "deterministic",
                    "issue_type": "concerns",
                    "operation": "trigger_strengthening",
                    "target_rule_id": target_rule["id"],
                    "target_branch_type": branch_type,
                    "target_branch_action": branch_action,
                    "original_rule": original_rule,
                    "proposed_rule": proposed_rule,
                    "natural_language_explanation": (
                        "Strengthen the original trigger using additional "
                        "context identified by the WFI diagnosis while "
                        "preserving the original response, temporal "
                        "constraint, and defeater."
                    )
                })

        # Defeater refinement remains available when the diagnosed response
        # is encoded by an existing alternative branch.
        if "defeater_introduction" in operators and context:
            proposed_rule = self.exclude_context_from_defeater(
                target_rule,
                context,
                concern_action
            )
            if proposed_rule and proposed_rule != original_rule:
                patches.append({
                    "patch_id": f'd_concern_defeater_{target_rule["id"]}',
                    "id": f'd_concern_defeater_{target_rule["id"]}',
                    "source": "deterministic",
                    "issue_type": "concerns",
                    "operation": "defeater_introduction",
                    "target_rule_id": target_rule["id"],
                    "target_branch_type": branch_type,
                    "target_branch_action": branch_action,
                    "original_rule": original_rule,
                    "proposed_rule": proposed_rule,
                    "natural_language_explanation": (
                        "Refine the affected rule's defeater using the "
                        "diagnosis-grounded context so the undesirable "
                        "concern response is not enabled in that context."
                    )
                })

        # Decomposition changes the main obligation, so do not apply it
        # blindly to a diagnosed alternative response.
        if (
            "rule_decomposition" in operators
            and context
            and main_branch_target
        ):
            proposed_rule = self.decompose_rule_for_concern(
                target_rule,
                context,
                desired_action,
                used_rule_ids
            )
            if proposed_rule:
                patches.append({
                    "patch_id": f'd_decompose_{target_rule["id"]}',
                    "id": f'd_decompose_{target_rule["id"]}',
                    "source": "deterministic",
                    "issue_type": "concerns",
                    "operation": "rule_decomposition",
                    "target_rule_id": target_rule["id"],
                    "target_branch_type": branch_type,
                    "target_branch_action": branch_action,
                    "original_rule": original_rule,
                    "proposed_rule": proposed_rule,
                    "natural_language_explanation": (
                        "Decompose the diagnosed main obligation into "
                        "distinct diagnosis-grounded specialized rules "
                        "while preserving unaffected semantics."
                    )
                })

        return patches

    def generate_purpose_patches(self, selected_issue, rules, operators):
        """
        Generate deterministic patches for a purpose-blocking
        (restrictiveness) WFI.

        Paper-aligned deterministic operator:
            - defeater_introduction

        Capability refinement is handled separately by the LLM pipeline.
        """

        patches = []

        purpose = self.parse_when_then(selected_issue)

        if not purpose:
            return patches

        purpose_action = str(
            purpose.get("action", "") or ""
        ).strip()

        purpose_condition = str(
            purpose.get("condition", "") or ""
        ).strip()

        if not purpose_action or not purpose_condition:
            return patches

        # ---------------------------------------------------------
        # Find the rule responsible for blocking the desired purpose
        # ---------------------------------------------------------
        #
        # IMPORTANT:
        # The LEGOS diagnosis already identifies the blocking SLEEC rule.
        # That diagnosed rule must be preferred over any whole-specification
        # semantic search. This keeps deterministic repair diagnosis-grounded.
        # ---------------------------------------------------------

        target_rule = None

        # Extract rule IDs explicitly present in the purpose diagnosis.
        #
        # Example:
        #
        #   Blocked SLEEC purpose:
        #   p7 when InformUser and {rulesFollowed}
        #   then not RemindUser within 10 minutes
        #
        #   Because of the following SLEEC rule:
        #   R9_1 when InformUser then RemindUser within 10 minutes
        #
        # The deterministic target must therefore be R9_1.

        diagnosed_rule_ids = self.extract_rule_ids(selected_issue)

        for diagnosed_id in diagnosed_rule_ids:
            for rule in rules:
                rule_id = str(rule.get("id", "") or "").strip()

                if rule_id.lower() == str(diagnosed_id).strip().lower():
                    target_rule = rule
                    break

            if target_rule:
                break

        # Fallback only when the diagnosis does not expose a blocking rule.
        # Deterministic purpose repair must be grounded in the
        # blocking rule explicitly identified by the diagnosis.
        # Do not guess a target from unrelated rules in the specification.

        if not target_rule:
            return patches

        original_rule = self.rule_to_text(target_rule)

        # ---------------------------------------------------------
        # Extract the additional purpose-specific context
        #
        # Example from the paper:
        #
        # Purpose:
        #   HumanOnFloor
        #   and UserUnconscious
        #   and not humanAssents
        #
        # Blocking rule:
        #   HumanOnFloor
        #   and not humanAssents
        #
        # purpose_context:
        #   UserUnconscious
        # ---------------------------------------------------------

        purpose_context = self.specific_context(
            purpose_condition,
            target_rule.get("condition", "")
        )

        if not purpose_context:
            return patches

        # Preserve SLEEC-compatible Boolean structure.
        purpose_context = self.normalize_boolean_expression(
            purpose_context
        )

        if not purpose_context:
            return patches

        # ---------------------------------------------------------
        # Deterministic operator:
        # Defeater Introduction
        # ---------------------------------------------------------

        if "defeater_introduction" not in operators:
            return patches

        proposed_rule = self.add_defeater(
            target_rule,
            purpose_context
        )

        # Do not emit invalid/no-op candidates.
        if not proposed_rule:
            return patches

        if proposed_rule == original_rule:
            return patches

        patches.append({
            "patch_id": (
                f'd_defeater_introduction_{target_rule["id"]}'
            ),
            "id": (
                f'd_defeater_introduction_{target_rule["id"]}'
            ),
            "source": "deterministic",
            "issue_type": "purpose_blocking",
            "operation": "defeater_introduction",
            "target_rule_id": target_rule["id"],
            "original_rule": original_rule,
            "proposed_rule": proposed_rule,
            "natural_language_explanation": (
                "Introduce the diagnosis-grounded purpose context "
                "as a defeater of the blocking rule so that the "
                "intended behaviour remains possible in that context."
            )
        })

        return patches

    def generate_conflict_patches(
        self,
        issue_type,
        selected_issue,
        rules,
        operators
    ):
        """Generate deterministic candidate repairs for diagnosed conflicts.

        Candidate generation does not establish correctness. Every candidate
        must later be applied to the complete SLEEC specification and verified
        by LEGOS-SLEEC.
        """
        patches = []
        conflict_rules = self.find_conflicting_rules(selected_issue, rules)

        if len(conflict_rules) < 2:
            return patches

        r1, r2 = conflict_rules[:2]
        seen = set()

        def append_patch(patch):
            if not patch:
                return
            proposed = self.clean_condition(patch.get("proposed_rule", ""))
            if not proposed:
                return
            operation = patch.get("operation", "")
            original = self.clean_condition(patch.get("original_rule", ""))

            if proposed.lower() == original.lower():
                return
            if operation == "rule_merging":
                source_rules = [
                    self.clean_condition(self.rule_to_text(rule))
                    for rule in (r1, r2)
                ]

                if any(
                    proposed.lower() == source.lower()
                    for source in source_rules
                    if source
                ):
                    return
            key = (operation, proposed.lower())
            if key in seen:
                return
            seen.add(key)
            patches.append(patch)

        # 1. Defeater introduction
        if "defeater_introduction" in operators:
            for target, other, suffix in ((r1, r2, "1"), (r2, r1, "2")):
                context = self.specific_context(
                    other.get("condition", ""),
                    target.get("condition", "")
                )

                context = self.normalize_boolean_expression(context)

                if not context:
                    continue

                # A defeater must contain only valid measure predicates.
                # Events cannot be inserted into an `unless` condition.
                if not self.is_measure_only_expression(context):
                    continue

                proposed = self.add_defeater(target, context)

                if proposed and proposed != self.rule_to_text(target):
                    append_patch({
                        "id": f"d_conflict_exception_{suffix}",
                        "patch_id": f"d_conflict_exception_{suffix}",
                        "source": "deterministic",
                        "issue_type": issue_type,
                        "operation": "defeater_introduction",
                        "target_rule_id": target["id"],
                        "original_rule": self.rule_to_text(target),
                        "proposed_rule": proposed,
                        "natural_language_explanation": (
                            "Add a diagnosis-grounded exception to prevent the "
                            "conflicting obligations from applying simultaneously."
                        )
                    })

        # 2. Trigger refinement
        if "trigger_refinement" in operators:
            for target, other, suffix in ((r1, r2, "1"), (r2, r1, "2")):

                # A SLEEC rule has one triggering event.  Therefore trigger
                # refinement must propagate only contextual measure predicates
                # from the conflicting rule, never its triggering event.
                #
                # Example:
                #   r1: when SmokeDetectorAlarm then A
                #   r2: when HumanOnFloor and not {humanAssents} then not A
                #
                # becomes:
                #   r1E: when SmokeDetectorAlarm and {humanAssents} then A
                context = self.conflict_measure_context(other)

                if not context:
                    continue

                # Propagate the complement of the conflicting rule's contextual
                # measure predicate, following the deterministic trigger-refinement
                # operator.
                complement = self.complement_context(context)

                if not complement:
                    continue

                proposed = self.strengthen_trigger_with_condition(
                    target,
                    complement
                )
                if proposed and proposed != self.rule_to_text(target):
                    append_patch({
                        "id": f"d_conflict_trigger_{suffix}",
                        "patch_id": f"d_conflict_trigger_{suffix}",
                        "source": "deterministic",
                        "issue_type": issue_type,
                        "operation": "trigger_refinement",
                        "target_rule_id": target["id"],
                        "original_rule": self.rule_to_text(target),
                        "proposed_rule": proposed,
                        "natural_language_explanation": (
                            "Refine the rule trigger using the diagnosed conflicting "
                            "context so incompatible obligations cannot apply simultaneously."
                        )
                    })

        # 3. Rule merging
        if "rule_merging" in operators and self.compatible_for_merging(r1, r2):
            proposed = self.merge_conflicting_rules(r1, r2)
            if proposed:
                append_patch({
                    "id": f'd_conflict_merge_{r1["id"]}_{r2["id"]}',
                    "patch_id": f'd_conflict_merge_{r1["id"]}_{r2["id"]}',
                    "source": "deterministic",
                    "issue_type": issue_type,
                    "operation": "rule_merging",
                    "target_rule_id": r1["id"],
                    "rule_ids": [r1["id"], r2["id"]],
                    "original_rule": self.rule_to_text(r1) + "\n" + self.rule_to_text(r2),
                    "proposed_rule": proposed,
                    "natural_language_explanation": (
                        "Merge the diagnosed conflicting rules into one conditional "
                        "rule with an explicit alternative response."
                    )
                })

        return patches

    def extract_rule_id(self, text):
        ids = self.extract_rule_ids(text)

        if not ids:
            return ""

        return ids[0]

    def extract_rule_ids(self, text):
        ids = []

        for match in re.finditer(r"\b(?:Rule|R|r|C|c)\d+[A-Za-z]*(?:_\d+)*\b", str(text)):
            rule_id = match.group(0)

            if rule_id not in ids:
                ids.append(rule_id)

        return ids

    def rule_id_in_text(self, rule_id, text):
        if not rule_id:
            return False

        return re.search(
            rf"(?<![A-Za-z0-9_]){re.escape(str(rule_id))}(?![A-Za-z0-9_])",
            str(text)
        ) is not None

    def find_rule(self, rule_id, rules):
        if not rule_id:
            return None

        for rule in rules:
            if isinstance(rule, dict) and str(rule.get("id", "")).lower() == str(rule_id).lower():
                return rule

        return None

    def find_rule_text(self, rule_id, rules):
        if not rule_id:
            return ""

        rule = self.find_rule(rule_id, rules)

        if rule:
            return self.rule_to_text(rule)

        for r in rules:
            if isinstance(r, str) and rule_id in r:
                return r

        return ""

    def find_conflicting_rules(self, selected_issue, rules):
        text = str(selected_issue)
        mentioned_ids = self.extract_rule_ids(text)
        found = [
            rule
            for rule_id in mentioned_ids
            for rule in rules
            if str(rule.get("id", "")).lower() == str(rule_id).lower()
        ]

        if len(found) >= 2:
            return found[:2]

        found = []

        for rule in rules:
            if self.rule_id_in_text(rule["id"], text) or rule["action"] in text:
                found.append(rule)

        if len(found) >= 2:
            return found[:2]

        # Never guess a conflicting pair from unrelated opposite actions in
        # the complete specification. If the diagnosis cannot ground two rules,
        # deterministic conflict repair is not applicable.
        return []

    def find_related_rule(self, selected_issue, rules):
        """
        Backward-compatible wrapper around branch-aware target selection.
        """
        return self.find_best_related_rule(selected_issue, rules)

    def find_best_related_rule(self, selected_issue, rules):
        """
        Return only the rule for callers that do not need branch metadata.
        """
        match = self.find_best_related_rule_context(selected_issue, rules)
        return match["rule"] if match else None

    def condition_terms(self, condition):
        """
        Extract comparable semantic identifiers from a SLEEC condition.
        Logical/syntactic words and numeric literals are ignored.
        """
        ignored = {
            "and", "or", "not", "when", "then", "unless", "within",
            "eventually", "otherwise", "true", "false",
            "seconds", "second", "minutes", "minute",
            "hours", "hour"
        }

        return {
            token.lower()
            for token in re.findall(
                r"[A-Za-z_][A-Za-z0-9_]*",
                str(condition or "")
            )
            if token.lower() not in ignored
        }

    def normalized_condition(self, condition):
        """
        Normalize whitespace/braces for condition containment comparison while
        preserving the domain vocabulary itself.
        """
        value = self.clean_condition(condition).lower()
        value = value.replace("{", "").replace("}", "")
        value = re.sub(r"\s+", " ", value)
        return value.strip()

    def find_rule_by_action(self, action, rules):
        action = self.normalize_action(action)

        if not action:
            return None

        for rule in rules:
            rule_actions = [rule.get("action", "")]
            rule_actions.extend(self.defeater_actions(rule.get("defeater", "")))

            if any(self.normalize_action(rule_action) == action for rule_action in rule_actions):
                return rule

        return None
    def find_existential_concern_producers(self, action, rules):
        """
        Return all rules whose MAIN response produces the witnessed
        existential concern capability/state with the same polarity.

        Example:
            concern:
                exists UserDriving and {substanceUse}

            eligible producer:
                when X then UserDriving

            not an eligible producer:
                when X then not UserDriving

        Alternative defeater responses are intentionally excluded because
        existential deterministic repairs operate on the main obligation.
        """
        action = str(action or "").strip()

        if not action:
            return []

        capability = self.normalize_action(action)
        polarity = self.is_negative(action)

        producers = []

        for rule in rules:
            if not isinstance(rule, dict):
                continue

            rule_action = str(rule.get("action", "") or "").strip()

            if not rule_action:
                continue

            if self.normalize_action(rule_action) != capability:
                continue

            # Preserve polarity. UserDriving and not UserDriving are
            # different directions for existential repair.
            if self.is_negative(rule_action) != polarity:
                continue

            producers.append(rule)

        return producers
    def find_opposing_rule(self, action, rules):
        action = str(action or "").strip()

        if not action:
            return None

        for rule in rules:
            if self.is_opposite_action(action, rule.get("action", "")):
                return rule

        return self.find_rule_by_action(action, rules)

    def is_opposite_action(self, a, b):
        a = re.split(
            r"\bwithin\b|\bunless\b|\beventually\b|\botherwise\b",
            str(a or "").strip(),
            maxsplit=1,
            flags=re.IGNORECASE
        )[0].strip()
        b = re.split(
            r"\bwithin\b|\bunless\b|\beventually\b|\botherwise\b",
            str(b or "").strip(),
            maxsplit=1,
            flags=re.IGNORECASE
        )[0].strip()

        return (
            a == f"not {b}"
            or b == f"not {a}"
            or a == f"not{b}"
            or b == f"not{a}"
        )

    def add_defeater(self, rule, defeater):
        raw = self.rule_raw(rule)
        condition = self.wrap_group(self.usable_context(defeater))

        if not condition:
            return raw

        # A new exception is stacked as its own 'unless' clause rather than
        # OR-merged into an existing defeater: stacking is always valid SLEEC,
        # whereas merging a bare condition into a defeater that already carries
        # a 'then' response produces malformed text.
        if re.search(r"\bunless\s+" + re.escape(condition), raw, flags=re.IGNORECASE):
            return raw

        return f"{raw} unless {condition}"

    def strengthen_trigger(self, rule, context):
        return self.strengthen_trigger_with_condition(rule, context)

    def strengthen_trigger_with_condition(self, rule, context):
        split = self.split_trigger_body(self.rule_raw(rule))
        context = self.clean_condition(context)

        if not split or not context:
            return self.rule_raw(rule)

        head, trigger, body = split
        return f"{head} when {self.combine_trigger(trigger, context)} then {body}"

    def refine_trigger_against_condition(self, rule, context):
        context = self.specific_context(
            self.clean_condition(context),
            rule.get("condition", "")
        )
        negated = self.negate_group(context)
        split = self.split_trigger_body(self.rule_raw(rule))

        if not split or not negated:
            return self.rule_raw(rule)

        head, trigger, body = split
        return f"{head} when {self.combine_trigger(trigger, negated)} then {body}"

    def complementary_context(self, context):
        context = self.clean_condition(context)
        match = re.fullmatch(
            r"not\s+\{?([A-Za-z_][A-Za-z0-9_]*)\}?",
            context,
            flags=re.IGNORECASE
        )
        return match.group(1) if match else context
    def conflict_measure_context(self, rule):
        """
        Extract only contextual measure predicates from a SLEEC trigger.

        SLEEC trigger structure:
            when EVENT [and MEASURE-CONTEXT...]

        The first component is the triggering event and must never be
        propagated as contextual refinement.

        Example:
            HumanOnFloor and not {humanAssents}
                -> not {humanAssents}
        """
        parts = self.condition_parts(rule.get("condition", ""))

        if len(parts) <= 1:
            return ""

        contextual_parts = [
            part
            for part in parts[1:]
            if self.is_measure_only_expression(part)
        ]

        if not contextual_parts:
            return ""

        return self.normalize_boolean_expression(
            " and ".join(contextual_parts)
        )
    def compatible_for_merging(self, r1, r2):
        """
        Rule merging is applicable only when both diagnosed rules
        have the same triggering event.

        A SLEEC rule contains one triggering event followed optionally
        by constraints on measures. Different triggering events cannot
        be merged.
        """
        if not r1 or not r2:
            return False

        parts1 = self.condition_parts(r1.get("condition", ""))
        parts2 = self.condition_parts(r2.get("condition", ""))

        if not parts1 or not parts2:
            return False

        event1 = self.norm_atom(parts1[0])
        event2 = self.norm_atom(parts2[0])

        return bool(event1 and event2 and event1 == event2)

    def propagate_defeater(self, rule):
        raw = self.rule_raw(rule)
        split = self.split_trigger_body(raw)

        if not split:
            return raw

        head, trigger, body = split
        unless_index = self.top_level_index(body, "unless", 0)

        if unless_index < 0:
            return raw

        primary = body[:unless_index].strip()
        after = body[unless_index + len("unless"):].strip()
        then_index = self.top_level_index(after, "then", 0)

        if then_index >= 0:
            condition = after[:then_index].strip()
            remainder = after[then_index + len("then"):].strip()
            next_unless = self.top_level_index(remainder, "unless", 0)
            kept = remainder[next_unless:].strip() if next_unless >= 0 else ""
        else:
            condition = after.strip()
            kept = ""

        negated = self.negate_group(condition)
        new_body = f"{primary} {kept}".strip() if kept else primary

        return f"{head} when {self.combine_trigger(trigger, negated)} then {new_body}".strip()

    def merge_conflicting_rules(self, r1, r2):
        """
        Merge two conflicting SLEEC rules only when they share the same
        triggering event.

        Expected form:

            r1: when E then A
            r2: when E and C then B

        becomes:

            when E then A unless C then B

        where E is the single shared triggering event and C contains the
        additional measure constraints of the more specific rule.

        Different triggering events are not mergeable.
        """

        if not self.compatible_for_merging(r1, r2):
            return None

        parts1 = self.condition_parts(r1.get("condition", ""))
        parts2 = self.condition_parts(r2.get("condition", ""))

        if not parts1 or not parts2:
            return None

        # The first condition component is the single triggering event.
        event1 = self.norm_atom(parts1[0])
        event2 = self.norm_atom(parts2[0])

        if not event1 or event1 != event2:
            return None

        # Determine which rule is general and which is specialized.
        extra1 = parts1[1:]
        extra2 = parts2[1:]

        if not extra1 and extra2:
            general = r1
            specific = r2
            context_parts = extra2

        elif not extra2 and extra1:
            general = r2
            specific = r1
            context_parts = extra1

        else:
            # This deterministic operator currently handles the precise
            # general-vs-specialized pattern defined for rule merging.
            return None

        context = self.clean_condition(" and ".join(context_parts))

        if not context:
            return None

        general_split = self.split_trigger_body(self.rule_raw(general))
        specific_split = self.split_trigger_body(self.rule_raw(specific))

        if not general_split or not specific_split:
            return None

        general_head, general_trigger, general_body = general_split
        _, _, specific_body = specific_split

        # Do not copy an existing defeater chain from the specialized rule.
        # The alternative response is its primary response only.
        specific_unless = self.top_level_index(specific_body, "unless", 0)

        if specific_unless >= 0:
            alternative = specific_body[:specific_unless].strip()
        else:
            alternative = specific_body.strip()

        if not alternative:
            return None

        return (
            f"{general_head} when {general_trigger} "
            f"then {general_body} "
            f"unless {self.wrap_group(context)} "
            f"then {alternative}"
        ).strip()

    def decompose_conflicting_rule(self, r1, r2):
        split1 = self.split_trigger_body(self.rule_raw(r1))
        context = self.specific_context(
            r2.get("condition", ""), r1.get("condition", "")
        )

        if not split1 or not self.clean_condition(context):
            return self.rule_raw(r1)

        head, trigger, body1 = split1
        split2 = self.split_trigger_body(self.rule_raw(r2))
        body2 = split2[2].strip() if split2 else str(r2.get("action", "")).strip()

        return (
            f"{head}_1 when {self.combine_trigger(trigger, self.negate_group(context))} then {body1}\n"
            f"{head}_2 when {self.combine_trigger(trigger, context)} then {body2}"
        )

    def make_rule_decomposition_patch(self, rule, context, explanation):
        context = self.clean_condition(context)

        return {
            "id": f'd_decompose_{rule["id"]}',
            "patch_id": f'd_decompose_{rule["id"]}',
            "source": "deterministic",
            "issue_type": "decomposition",
            "operation": "rule_decomposition",
            "target_rule_id": rule["id"],
            "original_rule": self.rule_to_text(rule),
            "proposed_rule": self.decompose_rule_by_context(rule, context),
            "natural_language_explanation": explanation
        }

    def decompose_rule_by_context(self, rule, context):
        split = self.split_trigger_body(self.rule_raw(rule))
        context = self.clean_condition(context)

        if not split or not context:
            return self.rule_raw(rule)

        head, trigger, body = split
        return (
            f"{head}_1 when {self.combine_trigger(trigger, context)} then {body}\n"
            f"{head}_2 when {self.combine_trigger(trigger, self.negate_group(context))} then {body}"
        )

    def parse_when_then(self, text):
        match = re.search(
            r"\bwhen\s+(.+?)\s+then\s+(.+?)(?:\n|$)",
            str(text),
            flags=re.IGNORECASE | re.DOTALL
        )

        if not match:
            return {
                "condition": "",
                "action": ""
            }

        action = re.split(
            r"\bwithin\b|\bunless\b|\beventually\b",
            match.group(2),
            flags=re.IGNORECASE
        )[0].strip()

        return {
            "condition": self.clean_condition(match.group(1)),
            "action": action
        }
    def parse_concern(self, text):
        """
        Parse a LEGOS concern / insufficiency diagnosis.

        Supported forms:
            c1 exists CONDITION
            c1 when CONDITION then RESPONSE

        For an 'exists' concern there is no explicit response in the
        concern declaration, so action is left empty.
        """
        text = str(text or "")

        # Standard when ... then ... form.
        parsed = self.parse_when_then(text)
        if parsed.get("condition"):
            return parsed

        # LEGOS existential concern:
        #   c1 exists UserDriving and (not {properlyPlaced})
        match = re.search(
            r"\bc\d+(?:_\d+)?\s+exists\s+(.+?)(?=\s+Concern\s+is\s+raised|\n|$)",
            text,
            flags=re.IGNORECASE | re.DOTALL
        )

        if not match:
            return {
                "condition": "",
                "action": ""
            }

        return {
            "condition": self.clean_condition(match.group(1)),
            "action": ""
        }

    def clean_condition(self, condition):
        condition = str(condition or "").strip()
        condition = condition.replace("\n", " ")
        condition = re.sub(r"\s+", " ", condition)
        condition = condition.strip()
        return condition

    # ------------------------------------------------------------------
    # Verbatim, structure-preserving rule handling.
    #
    # The decomposed condition/action/defeater fields are lossy: the regex
    # captures a single defeater and drops parentheses, so rebuilding rule
    # text from them corrupts scale comparisons ({m} = high) and stacked
    # defeaters. Instead we splice edits onto the faithful verbatim source
    # (rule["raw"]), touching only the trigger/body span an operator changes.
    # ------------------------------------------------------------------

    def rule_raw(self, rule):
        raw = self.clean_condition(rule.get("raw", "") if isinstance(rule, dict) else "")

        if raw:
            return raw

        head = rule.get("id", "") if isinstance(rule, dict) else ""
        cond = self.clean_condition(rule.get("condition", "")) if isinstance(rule, dict) else ""
        action = str(rule.get("action", "")).strip() if isinstance(rule, dict) else ""
        text = f"{head} when {cond} then {action}".strip()
        defeater = self.clean_condition(rule.get("defeater", "")) if isinstance(rule, dict) else ""

        if defeater:
            text += " " + self.format_defeater(defeater)

        return text.strip()

    def top_level_index(self, text, keyword, start=0):
        """Index of a whole-word keyword at parenthesis/brace depth 0, else -1."""
        text = str(text)
        low = text.lower()
        kw = keyword.lower()
        n = len(kw)
        depth = 0
        i = start

        while i < len(text):
            c = text[i]

            if c in "([{":
                depth += 1
            elif c in ")]}":
                depth = max(0, depth - 1)
            elif depth == 0 and low.startswith(kw, i):
                before = text[i - 1] if i > 0 else " "
                after = text[i + n] if i + n < len(text) else " "

                if not (before.isalnum() or before == "_") and not (after.isalnum() or after == "_"):
                    return i

            i += 1

        return -1

    def split_trigger_body(self, raw):
        """Split verbatim rule text into (head, trigger, body) preserving spans."""
        raw = self.clean_condition(raw)
        match = re.match(r"^(\S+)\s+when\s+", raw, flags=re.IGNORECASE)

        if not match:
            return None

        head = match.group(1)
        trigger_start = match.end()
        then_index = self.top_level_index(raw, "then", trigger_start)

        if then_index < 0:
            return None

        trigger = raw[trigger_start:then_index].strip()
        body = raw[then_index + len("then"):].strip()

        return head, trigger, body

    def split_top_level_and(self, expr):
        """Top-level ' and '-separated conjuncts, each kept verbatim (parens intact)."""
        expr = str(expr)
        low = expr.lower()
        parts = []
        depth = 0
        last = 0
        i = 0

        while i < len(expr):
            c = expr[i]

            if c in "([{":
                depth += 1
            elif c in ")]}":
                depth = max(0, depth - 1)
            elif depth == 0 and low.startswith(" and ", i):
                parts.append(expr[last:i].strip())
                i += 5
                last = i
                continue

            i += 1

        tail = expr[last:].strip()

        if tail:
            parts.append(tail)

        return [p for p in parts if p]

    def is_fully_wrapped(self, expr):
        expr = expr.strip()

        if not (expr.startswith("(") and expr.endswith(")")):
            return False

        depth = 0

        for i, c in enumerate(expr):
            if c == "(":
                depth += 1
            elif c == ")":
                depth -= 1

                if depth == 0 and i != len(expr) - 1:
                    return False

        return depth == 0

    def wrap_group(self, expr):
        """Parenthesize any non-atomic boolean expression so it embeds safely.

        Single events/measures are left bare; anything with logical operators,
        comparisons, or negation is wrapped (extra parentheses are always valid
        SLEEC). Already-wrapped expressions are left unchanged.
        """
        expr = self.clean_condition(expr)

        if not expr:
            return expr

        if re.fullmatch(r"\{?[A-Za-z_][A-Za-z0-9_]*\}?", expr):
            return expr

        if self.is_fully_wrapped(expr):
            return expr

        return f"({expr})"

    def negate_group(self, expr):
        """Negated boolean group. SLEEC requires the negation itself to be
        parenthesized inside a conjunction, i.e. '(not (...))', never 'not (...)'."""
        inner = self.wrap_group(expr)

        if not inner:
            return ""

        return f"(not {inner})"
    
    def complement_context(self, expr):
        """
        Return the logical complement of a diagnosis-grounded contextual
        predicate for deterministic conflict refinement.

        Examples:
            not {humanAssents} -> {humanAssents}
            {humanAssents}     -> (not {humanAssents})
            {riskLevel} = high -> (not ({riskLevel} = high))
        """
        expr = self.clean_condition(expr)

        if not expr:
            return ""

        # Remove redundant outer parentheses first.
        while self.is_fully_wrapped(expr):
            expr = expr[1:-1].strip()

        # Eliminate a leading negation instead of creating double negation.
        match = re.fullmatch(
            r"not\s+(.+)",
            expr,
            flags=re.IGNORECASE
        )

        if match:
            positive = self.clean_condition(match.group(1))

            while self.is_fully_wrapped(positive):
                positive = positive[1:-1].strip()

            return positive

        return self.negate_group(expr)
    def right_nest_and(self, terms):
        """Right-fold terms into a binary 'a and (b and (c))' conjunction."""
        terms = [self.clean_condition(t) for t in terms if self.clean_condition(t)]

        if not terms:
            return ""

        acc = terms[-1]

        for term in reversed(terms[:-1]):
            acc = f"{term} and {self.wrap_group(acc)}"

        return acc

    def references_event(self, expr):
        """True if the expression mentions a declared event anywhere.

        Events are only valid as a rule's leading trigger; they cannot appear in
        an 'and'/defeater condition. Such contexts have no valid deterministic
        repair, so the operator is skipped and the issue falls through to the LLM.
        """
        events = getattr(self, "_events", set())

        if not events:
            return False

        tokens = set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", str(expr or "")))
        return bool(tokens & events)

    def usable_context(self, expr):
        """Drop top-level conjuncts that reference events; keep measure conditions."""
        conjuncts = self.split_top_level_and(self.clean_condition(expr))
        kept = [part for part in conjuncts if not self.references_event(part)]
        return " and ".join(kept)

    def combine_trigger(self, trigger, extra):
        """Add a condition to a trigger as valid SLEEC.

        SLEEC triggers are right-nested binary expressions whose first token is
        the bare trigger event: 'Event and (cond1 and (cond2))'. A flat
        'Event and cond1 and cond2' is rejected, and the leading event may not
        be parenthesized. The event is therefore kept bare while every added
        condition is folded into a right-nested, parenthesized group.
        """
        trigger = self.clean_condition(trigger)
        extra = self.usable_context(extra)

        if not extra:
            return trigger

        conjuncts = self.split_top_level_and(trigger)

        if len(conjuncts) <= 1:
            return f"{trigger} and {self.wrap_group(extra)}"

        event = conjuncts[0]
        inner = self.right_nest_and(conjuncts[1:] + [extra])
        return f"{event} and {self.wrap_group(inner)}"

    def norm_atom(self, atom):
        atom = str(atom).lower()
        atom = atom.replace("(", " ").replace(")", " ")
        atom = atom.replace("{", "").replace("}", "")
        atom = re.sub(r"\s+", " ", atom)
        return atom.strip()

    def specific_context(self, diagnosis_condition, rule_condition):
        diagnosis_conjuncts = self.split_top_level_and(
            self.clean_condition(diagnosis_condition)
        )
        rule_norms = {
            self.norm_atom(part)
            for part in self.split_top_level_and(self.clean_condition(rule_condition))
        }
        specific = [
            part
            for part in diagnosis_conjuncts
            if self.norm_atom(part) not in rule_norms
        ]

        if specific:
            return " and ".join(specific)

        return self.clean_condition(diagnosis_condition)
    def concern_specific_context(self, diagnosis_condition, rule_condition):
        """
        Extract repair context from an existential insufficiency.

        Example:
            diagnosis:
                UserDriving and (not {properlyPlaced})

            related rule:
                SensorsConnect and (not {properlyPlaced})
                -> not UserDriving

        UserDriving is the witnessed undesirable capability/state, not
        additional trigger context. It must therefore not be added to
        the trigger.

        Only diagnosis predicates other than the witnessed first
        capability/event are eligible as repair context.
        """
        diagnosis_parts = self.split_top_level_and(
            self.clean_condition(diagnosis_condition)
        )

        if not diagnosis_parts:
            return ""

        # For an existential concern, the first non-measure atom is the
        # witnessed capability/state, e.g. UserDriving.
        context_parts = []
        witnessed_removed = False

        for part in diagnosis_parts:
            cleaned = self.clean_condition(part)

            if (
                not witnessed_removed
                and cleaned
                and not self.is_measure_only_expression(cleaned)
            ):
                witnessed_removed = True
                continue

            if cleaned:
                context_parts.append(cleaned)

        if not context_parts:
            return ""

        rule_parts = [
            self.clean_condition(part)
            for part in self.split_top_level_and(
                self.clean_condition(rule_condition)
            )
            if self.clean_condition(part)
        ]

        rule_norms = {
            self.norm_atom(part)
            for part in rule_parts
        }

        def predicate_base(part):
            """
            Normalize a Boolean predicate while ignoring polarity.

            Examples:
                {substanceUse}       -> substanceuse
                not {substanceUse}   -> substanceuse
                (not {substanceUse}) -> substanceuse
            """
            value = self.clean_condition(part)

            # Remove surrounding Boolean negation.
            value = re.sub(
                r"^\s*\(?\s*not\s+",
                "",
                value,
                flags=re.IGNORECASE
            )

            value = value.strip("(){} ")
            return re.sub(r"\s+", "", value).lower()

        # Collect Boolean measure names appearing anywhere in the
        # existing trigger, including inside nested AND expressions.
        #
        # Example:
        #   (({health} and {hasLicense}) and (not {substanceUse}))
        #
        # must tell us that substanceUse is already represented.
        rule_measure_bases = {
            re.sub(r"\s+", "", name).lower()
            for name in re.findall(
                r"\{([^{}]+)\}",
                self.clean_condition(rule_condition)
            )
            if name.strip()
        }

        specific = []

        for part in context_parts:
            # Same predicate already present.
            if self.norm_atom(part) in rule_norms:
                continue

            # Same Boolean measure is already represented with the
            # opposite polarity. Adding it would create a contradictory
            # trigger such as:
            #
            #     not {substanceUse} and {substanceUse}
            #
            # so it is not valid strengthening context.
            context_measure_names = {
                re.sub(r"\s+", "", name).lower()
                for name in re.findall(r"\{([^{}]+)\}", part)
                if name.strip()
            }

            if (
                context_measure_names
                and context_measure_names.issubset(rule_measure_bases)
            ):
                continue

            specific.append(part)

        if not specific:
            return ""

        return " and ".join(specific)

    def condition_parts(self, condition):
        condition = self.clean_condition(condition)
        condition = condition.replace("(", " ").replace(")", " ")

        return [
            part.strip()
            for part in re.split(r"\s+and\s+", condition, flags=re.IGNORECASE)
            if part.strip()
        ]

    def strip_not(self, action):
        return re.sub(r"^not\s*", "", str(action or "").strip(), flags=re.IGNORECASE)

    def normalize_action(self, action):
        action = str(action or "").strip()
        action = re.split(
            r"\bwithin\b|\bunless\b|\beventually\b|\botherwise\b",
            action,
            maxsplit=1,
            flags=re.IGNORECASE
        )[0].strip()
        action = self.strip_not(action)
        action = action.strip("{}() ")
        action = re.sub(r"\s+", " ", action)
        return action

    def defeater_actions(self, defeater):
        actions = []

        for match in re.finditer(
            r"\bthen\s+(.+?)(?=\s+unless\s+|\s+otherwise\s+|$)",
            str(defeater or ""),
            flags=re.IGNORECASE
        ):
            actions.append(match.group(1).strip())

        return actions

    def defeater_clauses(self, rule):
        raw = self.rule_raw(rule)
        split = self.split_trigger_body(raw)

        if not split:
            return []

        body = split[2]
        clauses = []
        unless_index = self.top_level_index(body, "unless", 0)

        while unless_index >= 0:
            after = body[unless_index + len("unless"):].strip()
            next_unless = self.top_level_index(after, "unless", 0)
            clause = after[:next_unless].strip() if next_unless >= 0 else after
            then_index = self.top_level_index(clause, "then", 0)

            if then_index >= 0:
                condition = clause[:then_index].strip()
                action = clause[then_index + len("then"):].strip()
            else:
                condition = clause.strip()
                action = ""

            if condition:
                clauses.append((self.clean_condition(condition), action))

            if next_unless < 0:
                break

            body = after[next_unless:]
            unless_index = self.top_level_index(body, "unless", 0)

        return clauses

    def defeater_suffix(self, rule):
        defeater = self.clean_condition(rule.get("defeater", ""))

        if not defeater:
            return ""

        return " " + self.format_defeater(defeater)

    def format_defeater(self, defeater):
        defeater = self.clean_condition(defeater)

        if not defeater:
            return ""

        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", defeater):
            return f"unless {{{defeater}}}"

        # A defeater may carry its own 'then <response>'. Parenthesize only the
        # guard condition; keep the response outside so we never emit the
        # invalid 'unless ((cond) then action)'.
        then_index = self.top_level_index(defeater, "then", 0)

        if then_index >= 0:
            condition = defeater[:then_index].strip()
            response = defeater[then_index:].strip()
            return f"unless {self.wrap_group(condition)} {response}"

        return f"unless {self.wrap_group(defeater)}"

    def rule_to_text(self, rule):
        return self.rule_raw(rule)

    def find_redundant_rule_pair(self, selected_issue, rules):
        """
        Return (redundant_rule, survivor_rule) only when the redundancy
        diagnosis identifies two distinct rules that are exact
        semantic-structure duplicates.

        Conservative rule-removal policy:
        - same trigger
        - same response
        - same defeater
        - keep one rule
        - remove the other
        """

        issue_text = str(selected_issue or "")

        # Capture complete IDs such as:
        # r1, R2, Rule3, Rule5_1, C1
        candidate_ids = re.findall(
            r"\b(?:r\d+[A-Za-z]*(?:_\d+)*|rule\d+[A-Za-z]*(?:_\d+)*|c\d+[A-Za-z]*(?:_\d+)*)\b",
            issue_text,
            flags=re.IGNORECASE
        )

        matched_rules = []

        for candidate_id in candidate_ids:
            found = self.find_rule(candidate_id, rules)

            if not found:
                continue

            actual_id = str(found.get("id", ""))

            if not actual_id:
                continue

            # Avoid adding the same diagnosed rule more than once.
            if any(
                str(existing.get("id", "")).lower() == actual_id.lower()
                for existing in matched_rules
            ):
                continue

            matched_rules.append(found)

        # Rule removal requires at least two diagnosed rules.
        if len(matched_rules) < 2:
            return None, None

        r1 = matched_rules[0]
        r2 = matched_rules[1]

        # ---------------------------------------------------------
        # Same trigger
        # ---------------------------------------------------------

        same_condition = (
            self.normalized_condition(r1.get("condition", ""))
            ==
            self.normalized_condition(r2.get("condition", ""))
        )

        # ---------------------------------------------------------
        # Same response
        # ---------------------------------------------------------

        action_1 = re.sub(
            r"\s+",
            " ",
            str(r1.get("action", ""))
        ).strip().lower()

        action_2 = re.sub(
            r"\s+",
            " ",
            str(r2.get("action", ""))
        ).strip().lower()

        same_action = action_1 == action_2

        # ---------------------------------------------------------
        # Same defeater
        # ---------------------------------------------------------

        same_defeater = (
            self.normalized_condition(r1.get("defeater", ""))
            ==
            self.normalized_condition(r2.get("defeater", ""))
        )

                # ---------------------------------------------------------
        # Conservative removal
        # ---------------------------------------------------------

        # Removal is safe only when the diagnosed rules have the
        # same response and the same defeater structure.
        if not (same_action and same_defeater):
            return None, None

        # ---------------------------------------------------------
        # Case 1: exact duplicate
        #
        #   when A then X
        #   when A then X
        #
        # Preserve the first diagnosed rule and remove the second.
        # ---------------------------------------------------------
        if same_condition:
            survivor_rule = r1
            redundant_rule = r2
            return redundant_rule, survivor_rule

        # ---------------------------------------------------------
        # Case 2: trigger subsumption
        #
        #   when A then X
        #   when A and C then X
        #
        # The broader rule already covers the more specific rule.
        # Therefore preserve the broader rule and remove the
        # diagnosed specialized rule.
        # ---------------------------------------------------------

        parts1 = {
            self.norm_atom(part)
            for part in self.condition_parts(r1.get("condition", ""))
            if self.norm_atom(part)
        }

        parts2 = {
            self.norm_atom(part)
            for part in self.condition_parts(r2.get("condition", ""))
            if self.norm_atom(part)
        }

        if not parts1 or not parts2:
            return None, None

        # r1 is broader; r2 adds one or more trigger constraints.
        if parts1 < parts2:
            survivor_rule = r1
            redundant_rule = r2
            return redundant_rule, survivor_rule

        # r2 is broader; r1 adds one or more trigger constraints.
        if parts2 < parts1:
            survivor_rule = r2
            redundant_rule = r1
            return redundant_rule, survivor_rule

        # Neither trigger subsumes the other.
        return None, None

    def find_best_related_rule_context(self, selected_issue, rules):
        """
        Select both the related rule and the response branch responsible
        for the diagnosed WFI.

        Capability matching ignores response polarity so that, for example,
        a concern about 'not AdjustRoute' can be related to a rule branch
        whose response is 'AdjustRoute'. Opposite polarity receives an
        additional relevance bonus.
        """
        issue_text = str(selected_issue or "")
        parsed = self.parse_concern(issue_text)

        issue_condition = parsed.get("condition", "")
        issue_action = str(parsed.get("action", "") or "").strip()

        # Standard concern:
        #   when CONDITION then ACTION
        issue_capability = self.normalize_action(issue_action)

        # Existential insufficiency:
        #   c1 exists UserDriving and (not {properlyPlaced})
        #
        # There is no explicit "then ACTION". The first condition
        # component is the witnessed capability/event, while the
        # remaining components provide diagnostic context.
        if not issue_capability and issue_condition:
            parts = self.condition_parts(issue_condition)

            if parts:
                first_part = self.clean_condition(parts[0])

                # Only use the first component as a capability when it
                # is an event/capability atom, not a measure predicate.
                if (
                    first_part
                    and not self.is_measure_only_expression(first_part)
                ):
                    issue_action = first_part
                    issue_capability = self.normalize_action(first_part)

        if not issue_capability:
            return None
         # Existential concerns need stronger grounding than standard
        # when...then concerns. A candidate target must share at least
        # one diagnostic context predicate with the concern.
        #
        # Example:
        #   c1 exists UserDriving and (not {properlyPlaced})
        #
        # UserDriving is the witnessed capability/state. The remaining
        # predicate(s) are the diagnostic context used for grounding.
        is_existential_concern = bool(
            re.search(
                r"\bc\d+(?:_\d+)?\s+exists\b",
                issue_text,
                flags=re.IGNORECASE
            )
        )

        existential_context_terms = set()

        if is_existential_concern:
            parts = self.condition_parts(issue_condition)

            # Remove the witnessed capability/event (first component).
            if len(parts) > 1:
                context_text = " and ".join(parts[1:])
                existential_context_terms = self.condition_terms(context_text)

            if not existential_context_terms:
                return None

        issue_terms = self.condition_terms(issue_condition)
        explicitly_named = {
            str(rid).lower() for rid in self.extract_rule_ids(issue_text)
        }

        best_match = None
        best_score = -1

        for rule in rules:
            if not isinstance(rule, dict):
                continue

            rule_condition = self.clean_condition(rule.get("condition", ""))
            rule_terms = self.condition_terms(rule_condition)
            # Do not select an unrelated rule for an existential
            # insufficiency merely because its response has the same
            # capability (possibly with opposite polarity).
            #
            # The rule must also share diagnosis-specific context.
            if is_existential_concern:
                shared_existential_context = (
                    existential_context_terms.intersection(rule_terms)
                )

                if not shared_existential_context:
                    continue

            context_score = 0
            shared_terms = issue_terms.intersection(rule_terms)
            context_score += 4 * len(shared_terms)

            if (
                rule_condition
                and issue_condition
                and self.normalized_condition(rule_condition)
                in self.normalized_condition(issue_condition)
            ):
                context_score += 8

            if str(rule.get("id", "")).lower() in explicitly_named:
                context_score += 20

            # Main response.
            main_action = str(rule.get("action", "") or "").strip()
            if (
                main_action
                and self.normalize_action(main_action) == issue_capability
            ):
                score = context_score + 10
                if self.is_negative(main_action) != self.is_negative(issue_action):
                    score += 5

                if score > best_score:
                    best_score = score
                    best_match = {
                        "rule": rule,
                        "branch_type": "main",
                        "branch_condition": rule_condition,
                        "branch_action": main_action,
                        "score": score,
                    }

            # Alternative defeater responses.
            for branch in self.extract_defeater_branches(
                rule.get("defeater", "")
            ):
                branch_action = str(branch.get("action", "") or "").strip()

                if (
                    not branch_action
                    or self.normalize_action(branch_action) != issue_capability
                ):
                    continue

                score = context_score + 10
                if self.is_negative(branch_action) != self.is_negative(issue_action):
                    score += 5

                if score > best_score:
                    best_score = score
                    best_match = {
                        "rule": rule,
                        "branch_type": "defeater",
                        "branch_condition": branch.get("condition", ""),
                        "branch_action": branch_action,
                        "score": score,
                    }

        return best_match if best_score > 0 else None

    def extract_defeater_branches(self, defeater):
        """
        Extract alternative-response branches from a parsed defeater string.
        """
        text = self.clean_condition(defeater)
        if not text:
            return []

        parts = re.split(r"\s+unless\s+", text, flags=re.IGNORECASE)
        branches = []

        for part in parts:
            part = part.strip()
            if not part:
                continue

            match = re.match(
                r"^\(?(.+?)\)?\s+then\s+(.+)$",
                part,
                flags=re.IGNORECASE
            )
            if not match:
                continue

            condition = self.clean_condition(match.group(1))
            action = self.clean_condition(match.group(2))

            if condition and action:
                branches.append({
                    "condition": condition,
                    "action": action,
                })

        return branches

    def generate_temporal_refinement_patch(self, issue_type, selected_issue, rules):
        """Generate a diagnosis-driven temporal patch for supported WFI types."""
        context = self.find_temporal_refinement_context(
            selected_issue=selected_issue,
            rules=rules,
        )
        if not context:
            return None
        return self.make_temporal_refinement_patch(
            target_rule=context["target_rule"],
            diagnosed_temporal=context["diagnosed_temporal"]["text"],
            issue_type=issue_type,
        )

    def find_temporal_refinement_context(self, selected_issue, rules):
        """Find a timed target rule whose response matches a diagnosed bound."""
        diagnosis_text = str(selected_issue or "")
        requirements = self.extract_temporal_requirements(diagnosis_text)

        if not requirements:
            parsed = self.parse_when_then(selected_issue)
            temporal = self.temporal_bound(parsed.get("temporal", ""))
            action = parsed.get("action", "")
            if temporal and action:
                requirements = [{
                    "response": self.normalize_response_for_temporal_match(action),
                    "temporal": temporal,
                }]

        # Prefer rules explicitly named by the diagnosis, then any matching rule.
        named = self.extract_rule_ids(diagnosis_text)
        by_id = {
            str(r.get("id", "")).lower(): r
            for r in rules
            if isinstance(r, dict)
        }
        candidates = []
        for rid in named:
            rule = by_id.get(str(rid).lower())
            if rule and rule not in candidates:
                candidates.append(rule)
        for rule in rules:
            if isinstance(rule, dict) and rule not in candidates:
                candidates.append(rule)

        for rule in candidates:
            action = str(rule.get("action", ""))
            existing = self.temporal_bound(action)
            if not existing:
                continue
            target_response = self.normalize_response_for_temporal_match(action)

            for req in requirements:
                if req["response"] != target_response:
                    continue
                diagnosed = req["temporal"]
                if abs(existing["seconds"] - diagnosed["seconds"]) < 1e-9:
                    continue
                return {
                    "target_rule": rule,
                    "existing_temporal": existing,
                    "diagnosed_temporal": diagnosed,
                }
        return None

    def find_temporal_target_rule(self, rules, diagnosed_action, preferred_rule=None):
        """Find the timed rule for the diagnosed response, never just any timed rule."""
        wanted = self.normalize_response_for_temporal_match(diagnosed_action)
        candidates = []
        if preferred_rule:
            candidates.append(preferred_rule)
        candidates.extend(r for r in rules if r is not preferred_rule)
        seen = set()
        for rule in candidates:
            if not isinstance(rule, dict):
                continue
            rid = str(rule.get("id", ""))
            if rid in seen:
                continue
            seen.add(rid)
            action = str(rule.get("action", ""))
            if not self.temporal_bound(action):
                continue
            if self.normalize_response_for_temporal_match(action) == wanted:
                return rule
        return None

    def extract_temporal_requirements(self, text):
        """Extract every ``then RESPONSE within N UNIT`` from diagnosis text."""
        value = str(text or "")
        pattern = re.compile(
            r"\bthen\s+(.+?)\s+"
            r"(within\s+\d+(?:\.\d+)?\s+"
            r"(?:seconds?|minutes?|hours?|days?))\b",
            flags=re.IGNORECASE | re.DOTALL,
        )
        results = []
        for match in pattern.finditer(value):
            response = self.normalize_response_for_temporal_match(match.group(1))
            temporal = self.temporal_bound(match.group(2))
            if response and temporal:
                results.append({
                    "response": response,
                    "temporal": temporal,
                })
        return results

    def temporal_bound(self, text):
        """Extract a numeric ``within`` temporal bound and normalize it."""
        match = re.search(
            r"\bwithin\s+(\d+(?:\.\d+)?)\s+"
            r"(seconds?|minutes?|hours?|days?)\b",
            str(text or ""),
            flags=re.IGNORECASE,
        )
        if not match:
            return None
        value = float(match.group(1))
        unit = match.group(2).lower()
        return {
            "value": value,
            "unit": unit,
            "text": match.group(0),
            "seconds": self.temporal_to_seconds(value, unit),
        }

    def temporal_to_seconds(self, value, unit):
        unit = str(unit or "").lower()
        if unit.startswith("second"):
            return float(value)
        if unit.startswith("minute"):
            return float(value) * 60.0
        if unit.startswith("hour"):
            return float(value) * 3600.0
        if unit.startswith("day"):
            return float(value) * 86400.0
        raise ValueError(f"Unsupported temporal unit: {unit}")

    def normalize_response_for_temporal_match(self, text):
        response = str(text or "").strip()
        response = re.sub(r"^not\s+", "", response, flags=re.IGNORECASE)
        response = re.sub(
            r"\s+within\s+\d+(?:\.\d+)?\s+(?:seconds?|minutes?|hours?|days?)\b.*$",
            "", response, flags=re.IGNORECASE
        )
        return re.sub(r"\s+", " ", response).strip().lower()

    def make_temporal_refinement_patch(self, target_rule, diagnosed_temporal, issue_type=""):
        """Create restriction/relaxation by changing only the temporal bound.

        The diagnosed bound is authoritative. If the diagnosis does not contain
        a numeric ``within`` bound, or the target has no such bound, no patch is
        generated. This keeps the operator deterministic.
        """
        if not target_rule:
            return None

        old = self.temporal_bound(target_rule.get("action", ""))
        new = self.temporal_bound(diagnosed_temporal)
        if not old or not new:
            return None

        if abs(old["seconds"] - new["seconds"]) < 1e-9:
            return None

        subtype = (
            "temporal_restriction"
            if new["seconds"] < old["seconds"]
            else "temporal_relaxation"
        )

        original_rule = self.rule_to_text(target_rule)
        new_action = re.sub(
            r"\bwithin\s+\d+(?:\.\d+)?\s+"
            r"(?:seconds?|minutes?|hours?|days?)\b",
            new["text"],
            str(target_rule.get("action", "")),
            count=1,
            flags=re.IGNORECASE,
        )

        proposed_rule = (
            f'{target_rule["id"]} when {target_rule["condition"]} '
            f'then {new_action}{self.defeater_suffix(target_rule)}'
        )

        # Safety invariant: after replacing both temporal expressions by the
        # same marker, the original and proposed rules must be identical.
        if not self.temporal_only_change(original_rule, proposed_rule):
            return None

        return {
            "patch_id": f'd_temporal_{target_rule["id"]}',
            "id": f'd_temporal_{target_rule["id"]}',
            "source": "deterministic",
            "issue_type": issue_type,
            "operation": "temporal_refinement",
            "temporal_subtype": subtype,
            "target_rule_id": target_rule["id"],
            "original_rule": original_rule,
            "proposed_rule": proposed_rule,
            "old_temporal_bound": old["text"],
            "new_temporal_bound": new["text"],
            "natural_language_explanation": (
                f'{subtype.replace("_", " ").title()}: change only the temporal '
                f'bound from {old["text"]} to {new["text"]}, preserving the '
                'rule trigger, response, polarity, and defeater.'
            ),
        }

    def temporal_only_change(self, original_rule, proposed_rule):
        pattern = (
            r"\bwithin\s+\d+(?:\.\d+)?\s+"
            r"(?:seconds?|minutes?|hours?|days?)\b"
        )
        old_normalized = re.sub(
            pattern, "<TEMPORAL_BOUND>", str(original_rule),
            count=1, flags=re.IGNORECASE
        )
        new_normalized = re.sub(
            pattern, "<TEMPORAL_BOUND>", str(proposed_rule),
            count=1, flags=re.IGNORECASE
        )
        return old_normalized == new_normalized

    def normalize_boolean_expression(self, expression):
        """
        Normalize a Boolean condition while preserving SLEEC's binary Boolean
        grammar. In particular, never serialize a flat n-ary expression such
        as ``A or B or C``; emit ``A or (B or C)`` instead.

        This function intentionally performs conservative textual
        normalization. It does not change the logical operator ordering.
        """
        expr = self.clean_condition(expression)
        if not expr:
            return ""

        expr = re.sub(r"\s+", " ", expr).strip()

        # Remove only genuinely redundant outer parentheses.
        def strip_outer(s):
            s = s.strip()
            while s.startswith("(") and s.endswith(")"):
                depth = 0
                wraps_all = True
                for i, ch in enumerate(s):
                    if ch == "(":
                        depth += 1
                    elif ch == ")":
                        depth -= 1
                        if depth == 0 and i != len(s) - 1:
                            wraps_all = False
                            break
                if not wraps_all or depth != 0:
                    break
                s = s[1:-1].strip()
            return s

        def split_top_level(s, operator):
            """
            Split on a Boolean operator only when it occurs at parenthesis
            depth zero. Braced measure expressions are treated as atomic.
            """
            parts = []
            start = 0
            paren_depth = 0
            brace_depth = 0
            i = 0
            token = f" {operator} "

            while i < len(s):
                ch = s[i]

                if ch == "(":
                    paren_depth += 1
                    i += 1
                    continue
                if ch == ")":
                    paren_depth -= 1
                    i += 1
                    continue
                if ch == "{":
                    brace_depth += 1
                    i += 1
                    continue
                if ch == "}":
                    brace_depth -= 1
                    i += 1
                    continue

                if (
                    paren_depth == 0
                    and brace_depth == 0
                    and s[i:i + len(token)].lower() == token
                ):
                    parts.append(s[start:i].strip())
                    i += len(token)
                    start = i
                    continue

                i += 1

            if parts:
                parts.append(s[start:].strip())

            return parts

        def nest(parts, operator):
            """
            Right-associate Boolean expressions according to the SLEEC grammar:
            BoolBinaryOp := "(" BoolExp BoolOp BoolExp ")"

            [A, B, C] -> (A op (B op C))
            """
            parts = [p.strip() for p in parts if p and p.strip()]
            if not parts:
                return ""
            if len(parts) == 1:
                return parts[0]

            result = parts[-1]

            for part in reversed(parts[:-1]):
                result = f"({part} {operator} {result})"

            return result

        def serialize(s):
            s = strip_outer(s)
            if not s:
                return ""

            # OR has lower precedence than AND.
            # Every SLEEC BoolBinaryOp must be fully parenthesized:
            #     (lhs or rhs)
            or_parts = split_top_level(s, "or")
            if or_parts:
                rendered = [serialize(p) for p in or_parts]
                return nest(rendered, "or")

            # Every SLEEC BoolBinaryOp must be fully parenthesized:
            #     (lhs and rhs)
            and_parts = split_top_level(s, "and")
            if and_parts:
                rendered = [serialize(p) for p in and_parts]
                return nest(rendered, "and")

            # SLEEC Negation grammar:
            #     (not BoolExp)
            not_match = re.match(
                r"^not\s+(.+)$",
                s,
                flags=re.IGNORECASE,
            )
            if not_match:
                operand = strip_outer(not_match.group(1))
                rendered = serialize(operand)
                if not rendered:
                    return ""
                return f"(not {rendered})"

            # SLEEC scalar/numerical comparison grammar requires the
            # complete comparison to be parenthesized:
            #     ({riskLevel} = high)
            #     ({riskLevel} <> high)
            #     ({riskLevel} > high)
            comparison_match = re.fullmatch(
                r"(\{[A-Za-z_][A-Za-z0-9_]*\})\s*"
                r"(<=|>=|<>|=|<|>)\s*"
                r"(-?\d+(?:\.\d+)?|[A-Za-z_][A-Za-z0-9_]*)",
                s,
                flags=re.IGNORECASE,
            )
            if comparison_match:
                lhs, operator, rhs = comparison_match.groups()
                return f"({lhs} {operator} {rhs})"

            # Boolean terminals such as {userOccupied}, true, and false
            # remain atomic.
            return s.strip()

        return serialize(expr)

    def split_top_level_boolean(self, expr, operator):
        expr = str(expr or "").strip()
        depth = 0
        token = f" {operator} "
        lower = expr.lower()
        start = 0
        parts = []
        index = 0
        while index < len(expr):
            char = expr[index]
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
            if depth == 0 and lower.startswith(token, index):
                parts.append(expr[start:index].strip())
                index += len(token)
                start = index
                continue
            index += 1
        if parts:
            parts.append(expr[start:].strip())
        return parts

    def strip_outer_parentheses(self, text):
        text = str(text or "").strip()
        while self.outer_parentheses_wrap(text):
            text = text[1:-1].strip()
        return text

    def outer_parentheses_wrap(self, text):
        text = str(text or "").strip()
        if len(text) < 2 or text[0] != "(" or text[-1] != ")":
            return False
        depth = 0
        for index, char in enumerate(text):
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth == 0 and index != len(text) - 1:
                    return False
                if depth < 0:
                    return False
        return depth == 0

    def parenthesize(self, expr):
        expr = self.normalize_boolean_expression(expr)
        if not expr:
            return ""
        if expr.startswith("(") and expr.endswith(")") and self.outer_parentheses_wrap(expr):
            return expr
        return f"({expr})"

    def parenthesize_negated_atom(self, expr):
        expr = self.normalize_boolean_expression(expr)
        expr = self.strip_outer_parentheses(expr)
        if re.fullmatch(r"\{[A-Za-z_][A-Za-z0-9_]*\}", expr):
            return expr
        return self.parenthesize(expr)

    def negate_boolean_expression(self, expr):
        """Return a SLEEC-compatible Boolean complement.

        The grammar accepts negation as a parenthesized atom, but rejects
        `and not (...)`. Compound negation is therefore rendered using
        De Morgan's laws.
        """
        expr = self.normalize_boolean_expression(expr)
        expr = self.strip_outer_parentheses(expr)
        if not expr or self.is_bare_event_expression(expr):
            return ""

        or_parts = self.split_top_level_boolean(expr, "or")
        if or_parts:
            negated = [self.negate_boolean_expression(part) for part in or_parts]
            if any(not part for part in negated):
                return ""
            result = negated[0]
            for part in negated[1:]:
                result = self.and_expr(result, part)
            return result

        and_parts = self.split_top_level_boolean(expr, "and")
        if and_parts:
            negated = [self.negate_boolean_expression(part) for part in and_parts]
            if any(not part for part in negated):
                return ""
            result = negated[0]
            for part in negated[1:]:
                result = self.or_expr(result, part)
            return result

        not_match = re.fullmatch(r"\(?\s*not\s+(.+?)\s*\)?", expr, flags=re.IGNORECASE)
        if not_match:
            return self.normalize_boolean_expression(not_match.group(1))
                # Negate atomic measure comparisons explicitly.
        #
        # Do not generate forms such as:
        #     not {riskLevel} = high
        #
        # Instead complement the comparison operator itself.  This keeps
        # generated expressions compatible with the SLEEC measure grammar.
        comparison_match = re.fullmatch(
            r"\s*(\{[A-Za-z_][A-Za-z0-9_]*\})\s*"
            r"(<=|>=|<>|=|<|>)\s*"
            r"(-?\d+(?:\.\d+)?|[A-Za-z_][A-Za-z0-9_]*)\s*",
            expr,
            flags=re.IGNORECASE,
        )

        if comparison_match:
            measure, operator, value = comparison_match.groups()

            complement_operator = {
                "=": "<>",
                "<>": "=",
                "<": ">=",
                ">": "<=",
                "<=": ">",
                ">=": "<",
            }.get(operator)

            if not complement_operator:
                return ""

            return f"{measure} {complement_operator} {value}"
        return f"(not {self.parenthesize_negated_atom(expr)})"

    def and_expr(self, left, right):
        left = self.normalize_boolean_expression(left)
        right = self.normalize_boolean_expression(right)

        if not left:
            return right
        if not right:
            return left

        combined = f"{left} and ({right})"
        return self.normalize_boolean_expression(combined)


    def or_expr(self, left, right):
        left = self.normalize_boolean_expression(left)
        right = self.normalize_boolean_expression(right)

        if not left:
            return right
        if not right:
            return left

        combined = f"{left} or ({right})"
        return self.normalize_boolean_expression(combined)

    def is_bare_event_expression(self, expr):
        expr = str(expr or "").strip().strip("() ")
        return bool(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", expr))

    def is_measure_only_expression(self, expression):
        """
        Return True only when the expression is composed entirely of
        SLEEC measure predicates / Boolean operators.

        Event names must not be inserted into an `unless` condition.

        Examples:
            {humanConsents}                         -> True
            not {properlyPlaced}                   -> True
            {health} and {hasLicense}              -> True
            ({risk} = high) and {humanInRange}     -> True

            UserWantsControl                       -> False
            UserWantsControl and {health}          -> False
            SensorsConnect and not {properlyPlaced}-> False
        """

        expression = self.clean_condition(expression)

        if not expression:
            return False

        # Remove valid measure references first.
        remainder = re.sub(
            r"\{[A-Za-z_][A-Za-z0-9_]*\}",
            " ",
            expression,
        )

        # Remove comparison values/numbers.
        remainder = re.sub(
            r"(<=|>=|<>|=|<|>)\s*"
            r"(?:-?\d+(?:\.\d+)?|[A-Za-z_][A-Za-z0-9_]*)",
            " ",
            remainder,
            flags=re.IGNORECASE,
        )

        # Remove Boolean syntax.
        remainder = re.sub(
            r"\b(?:and|or|not|true|false)\b",
            " ",
            remainder,
            flags=re.IGNORECASE,
        )

        remainder = remainder.replace("(", " ").replace(")", " ")

        # Remove whitespace.
        remainder = re.sub(r"\s+", "", remainder)

        # Anything left is an unbraced symbol, normally an event.
        return remainder == ""

    def opposite_action(self, action):
        action = str(action or "").strip()
        if not action:
            return ""
        if re.match(r"^not\s+", action, flags=re.IGNORECASE):
            return re.sub(r"^not\s+", "", action, flags=re.IGNORECASE).strip()
        return f"not {action}"

    def apply_concern_deadline(self, action, temporal):
        """Use the concern deadline for the desired opposite response.

        For ``not A within 2 minutes``, preventing the concern requires ``A``
        within 2 minutes.  Existing temporal text on the action is replaced.
        """
        action = re.sub(
            r"\s+\b(within\s+\d+(?:\.\d+)?\s+"
            r"(?:seconds?|minutes?|hours?|days?)|eventually|immediately)\b.*$",
            "",
            str(action or "").strip(),
            flags=re.IGNORECASE
        ).strip()
        temporal = str(temporal or "").strip()
        return f"{action} {temporal}".strip()

    def split_defeater(self, defeater):
        """Return (condition, alternative action) for a SLEEC defeater."""
        text = self.clean_condition(defeater)
        match = re.match(
            r"^\(?(.+?)\)?\s+then\s+(.+)$",
            text,
            flags=re.IGNORECASE
        )
        if not match:
            return text, ""
        return self.clean_condition(match.group(1)), match.group(2).strip()

    def exclude_context_from_defeater(self, rule, context, concern_action=""):
        existing = self.clean_condition(rule.get("defeater", ""))
        if not existing:
            return ""

        defeater_condition, alternative = self.split_defeater(existing)
        if not defeater_condition or not alternative:
            return ""

        # Only refine a defeater whose alternative is the diagnosed concern
        # response (ignoring temporal text).  This prevents unrelated edits.
        if concern_action and (
            self.normalize_action(alternative) != self.normalize_action(concern_action)
            or self.is_negative(alternative) != self.is_negative(concern_action)
        ):
            return ""

        context = self.normalize_boolean_expression(context)
        defeater_condition = self.normalize_boolean_expression(defeater_condition)
        complement = self.negate_boolean_expression(context)
        if not complement:
            return ""
        narrowed = self.and_expr(defeater_condition, complement)
        return (
            f'{rule["id"]} when {rule["condition"]} then {rule["action"]} '
            f'unless {self.parenthesize(narrowed)} then {alternative}'
        )

    def is_negative(self, action):
        return bool(re.match(r"^not\s+", str(action or "").strip(), re.IGNORECASE))

    def next_available_rule_ids(self, base_rule_id, used_rule_ids, count=2):
        """Return collision-free child rule IDs derived from the target rule ID."""
        used = {str(x).lower() for x in (used_rule_ids or set())}
        result = []
        index = 1
        while len(result) < count:
            candidate = f"{base_rule_id}_{index}"
            if candidate.lower() not in used:
                result.append(candidate)
                used.add(candidate.lower())
            index += 1
        return result
    def sleec_trigger_expression(self, expression):
        """
        Serialize a Boolean expression for the SLEEC `when` position.

        SLEEC requires the trigger to begin with an event identifier, so
        remove only redundant parentheses that wrap the complete trigger.
        Preserve all internal Boolean grouping.
        """
        expression = str(expression or "").strip()

        while (
            expression.startswith("(")
            and expression.endswith(")")
            and self.outer_parentheses_wrap(expression)
        ):
            expression = expression[1:-1].strip()

        return expression
    def decompose_rule_for_concern(
        self, rule, context, desired_action, used_rule_ids=None
    ):
        """
        Deterministic rule decomposition.

        Split an existing obligation into multiple specialized rules
        only when the diagnosis provides a meaningful specialization
        context.

        IMPORTANT:
        - Never return the unchanged original rule as a decomposition.
        - Preserve the original temporal constraint.
        - Both branches must genuinely specialize the original rule.
        """

        if not rule:
            return None

        context = self.normalize_boolean_expression(context)

        # Diagnosis did not provide a usable specialization context.
        if not context:
            return None

        # The context must add information beyond the original trigger.
        specific = self.specific_context(
            context,
            rule.get("condition", "")
        )
        specific = self.normalize_boolean_expression(specific)

        if not specific:
            return None

        # Need a grammar-safe complementary context.
        complement = self.negate_boolean_expression(specific)

        if not complement:
            return None

        original_condition = self.normalize_boolean_expression(
            rule.get("condition", "")
        )

        # Build decomposition branches without wrapping the event-led
        # original trigger in parentheses. SLEEC requires the trigger
        # to start with the event identifier.
        
        original_trigger = self.sleec_trigger_expression(
            original_condition
        )

        specific = self.normalize_boolean_expression(specific)
        complement = self.normalize_boolean_expression(complement)

        # SLEEC Boolean conditions are binary.
        # Preserve the first event as the trigger and group all remaining
        # conditions into the right-hand Boolean branch.
        trigger_parts = self.split_top_level_and(original_trigger)

        if not trigger_parts:
            return None

        trigger_event = trigger_parts[0]
        if len(trigger_parts) == 1:
            specific = self.sleec_trigger_expression(specific)
            complement = self.sleec_trigger_expression(complement)

            branch_1_trigger = (
                f"{trigger_event} and ({specific})"
            )
            branch_2_trigger = (
                f"{trigger_event} and ({complement})"
            )

        else:
            existing_context = self.normalize_boolean_expression(
                " and ".join(trigger_parts[1:])
            )

            branch_1_context = self.and_expr(
                existing_context,
                specific
            )
            branch_2_context = self.and_expr(
                existing_context,
                complement
            )

            # Remove redundant parentheses around the complete
            # right-hand Boolean context before attaching it to
            # the event-led SLEEC trigger.
            branch_1_context = self.sleec_trigger_expression(
                branch_1_context
            )
            branch_2_context = self.sleec_trigger_expression(
                branch_2_context
            )

            branch_1_trigger = (
                f"{trigger_event} and ({branch_1_context})"
            )
            branch_2_trigger = (
                f"{trigger_event} and ({branch_2_context})"
            )
        
        if not branch_1_trigger or not branch_2_trigger:
            return None

        n_original = self.normalized_condition(original_condition)
        n_branch_1 = self.normalized_condition(branch_1_trigger)
        n_branch_2 = self.normalized_condition(branch_2_trigger)

        # Branches must be different.
        if n_branch_1 == n_branch_2:
            return None

        # Neither branch may reproduce the original trigger.
        if n_branch_1 == n_original:
            return None

        if n_branch_2 == n_original:
            return None

        first_id, second_id = self.next_available_rule_ids(
            rule["id"],
            used_rule_ids or set(),
            2
        )

        # desired_action already contains the diagnosed temporal
        # constraint when apply_concern_deadline() supplied one.
        #
        # The complementary branch keeps rule["action"] exactly,
        # including any original "within ..." constraint.
        branch_1 = (
            f'{first_id} when {branch_1_trigger} '
            f'then {desired_action}'
        )

        branch_2 = (
            f'{second_id} when {branch_2_trigger} '
            f'then {rule["action"]}{self.defeater_suffix(rule)}'
        )

        proposed = f"{branch_1}\n{branch_2}"

        if not self.validate_rule_decomposition(
            original_rule=rule,
            proposed_rule=proposed,
            context=specific
        ):
            return None

        return proposed

    def validate_rule_decomposition(
    self,
    original_rule,
    proposed_rule,
    context
):
        """
        Validate structural invariants specific to rule_decomposition.
        Formal LEGOS-SLEEC verification still happens later.
        """

        if not original_rule or not proposed_rule or not context:
            return False

        branches = [
            line.strip()
            for line in str(proposed_rule).splitlines()
            if line.strip()
        ]

        # Decomposition means MULTIPLE specialized rules.
        if len(branches) < 2:
            return False

        # No duplicate branches.
        normalized = [
            re.sub(r"\s+", " ", branch).strip().lower()
            for branch in branches
        ]

        if len(normalized) != len(set(normalized)):
            return False

        original_text = re.sub(
            r"\s+",
            " ",
            self.rule_to_text(original_rule)
        ).strip().lower()

        # The unchanged original rule cannot be one of the branches.
        if any(branch == original_text for branch in normalized):
            return False

        # Every branch must have when/then structure.
        if any(
            " when " not in branch.lower()
            or " then " not in branch.lower()
            for branch in branches
        ):
            return False

        # Preserve an existing temporal obligation.
        original_temporal = self.temporal_bound(
            original_rule.get("action", "")
        )

        if original_temporal:
            original_response = self.normalize_response_for_temporal_match(
                original_rule.get("action", "")
            )

            for branch in branches:
                parsed = self.parse_when_then(branch)

                branch_response = (
                    self.normalize_response_for_temporal_match(
                        parsed.get("action", "")
                    )
                )

                # Only compare temporal preservation when this branch
                # preserves the original response.
                if branch_response == original_response:
                    branch_temporal = self.temporal_bound(
                        parsed.get("temporal", "")
                    )

                    if not branch_temporal:
                        return False

                    if (
                        abs(
                            branch_temporal["seconds"]
                            - original_temporal["seconds"]
                        )
                        > 1e-9
                    ):
                        return False

        return True
