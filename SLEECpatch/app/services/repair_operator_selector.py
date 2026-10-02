import re
from typing import Dict, List, Optional, Sequence, Set


class RepairOperatorSelector:
    """
    Paper-aligned repair-operator selector.

    The selector receives the diagnosed WFI together with the diagnosed rules
    and SLEEC vocabulary. It selects applicable operators before patch
    generation begins.
    """

    BASE_DETERMINISTIC_OPERATORS = {
        "conflicts": [
            "trigger_refinement",
            "defeater_introduction",
            "rule_merging",
        ],
        "situational_conflicts": [
            "trigger_refinement",
            "defeater_introduction",
            "rule_merging",
        ],
        "redundancies": [
            "rule_removal",
            "defeater_propagation",
        ],
        "concerns": [
            "trigger_strengthening",
            "defeater_refinement",
            "rule_decomposition",
            "deadline_refinement",
        ],
        "purpose_blocking": [
         "defeater_introduction",
        ],
    }

    BASE_LLM_OPERATORS = {
        "conflicts": ["event_specialization", "measure_specialization", "response_refinement"],
        "situational_conflicts": ["event_specialization", "measure_specialization", "response_refinement"],
        "redundancies": ["event_specialization", "measure_specialization", "response_refinement"],
        "concerns": ["new_rule_generation"],
        "purpose_blocking": ["response_refinement"],
    }
    ISSUE_ALIASES = {
        "conflict": "conflicts",
        "situational_conflict": "situational_conflicts",
        "redundancy": "redundancies",
        "concern": "concerns",
        "purpose": "purpose_blocking",
        "restrictiveness": "purpose_blocking",
        "insufficiency": "concerns",
    }

    # Temporal Refinement is not a WFI category. It is a deterministic
    # cross-cutting repair operator that may apply to existing WFIs when the
    # diagnosis provides a different explicit numeric temporal bound.
    TEMPORAL_REFINEMENT_WFIS = {
        "concerns",
        "conflicts",
        "situational_conflicts",
    }

    def select(
        self,
        issue_type: str,
        rules: Optional[Sequence[dict]] = None,
        selected_issue: object = "",
        existing_events: Optional[Sequence[str]] = None,
        existing_measures: Optional[Sequence[str]] = None,
        existing_responses: Optional[Sequence[str]] = None,
        system_description: str = "",
        sleec_text: str = "",
    ) -> Dict[str, object]:
        issue_type = self.ISSUE_ALIASES.get(issue_type, issue_type)
        if sleec_text:
            from services.paper_repairs import plan
            return plan(sleec_text, issue_type, selected_issue, system_description)
        rules = list(rules or [])
        existing_events = list(existing_events or [])
        existing_measures = list(existing_measures or [])
        existing_responses = list(existing_responses or [])
        system_description = str(system_description or "")

        deterministic: List[str] = []
        llm: List[str] = []
        applicability: Dict[str, dict] = {}

        issue_rules = self.find_issue_rules(selected_issue, rules)

        if issue_type in {"conflicts", "situational_conflicts"}:
            self._select_conflict_operators(
                deterministic,
                llm,
                applicability,
                issue_rules,
                selected_issue,
                existing_events,
                existing_measures,
                system_description,

            )
        elif issue_type == "redundancies":
            self._select_redundancy_operators(
                deterministic,
                llm,
                applicability,
                issue_rules,
                selected_issue,
                existing_events,
                existing_measures,
                system_description,
            )
        elif issue_type == "concerns":
            self._select_concern_operators(
                deterministic,
                llm,
                applicability,
                issue_rules,
                selected_issue,
            )
        elif issue_type == "purpose_blocking":
            self._select_purpose_operators(
                deterministic,
                llm,
                applicability,
                issue_rules,
                selected_issue,
                existing_responses,
            )
        else:
            deterministic.extend(
                self.BASE_DETERMINISTIC_OPERATORS.get(issue_type, [])
            )
            llm.extend(self.BASE_LLM_OPERATORS.get(issue_type, []))

        from services.operator_names import ALIASES
        llm = [ALIASES.get(op, op) for op in llm if op != "semantic_rule_merging"]
        applicability = {ALIASES.get(op, op): value for op, value in applicability.items() if op != "semantic_rule_merging"}
        for op in self.BASE_LLM_OPERATORS.get(issue_type, []):
            applicable = bool(issue_rules) and (
                (op == "event_specialization" and any(self.trigger_event(r, existing_events) for r in issue_rules))
                or (op == "response_refinement" and any(r.get("action") for r in issue_rules))
                or (op == "measure_specialization" and (system_description or any(r.get("guard") or r.get("defeater") for r in issue_rules))))
            if op != "new_rule_generation":
                self._add(llm, applicability, op, applicable, "Requires the corresponding implicated rule element and a grounded semantic distinction.")
        if issue_type == "concerns":
            deterministic = ["defeater_refinement" if op == "defeater_introduction" else op for op in deterministic]
            if not any(r.get("defeater") for r in issue_rules):
                deterministic = [op for op in deterministic if op != "defeater_refinement"]
            context = self.find_temporal_refinement_context(issue_rules, selected_issue)
            applicable = bool(context and self.temporal_to_seconds(context['diagnosed_temporal']['value'], context['diagnosed_temporal']['unit']) < self.temporal_to_seconds(context['existing_temporal']['value'], context['existing_temporal']['unit']) and not context['target_rule'].get('action','').strip().startswith('not '))
            self._add(deterministic, applicability, 'deadline_refinement', applicable, 'Requires a weaker numeric deadline for the same positive response.')
            applicability.pop('defeater_introduction', None)
            applicability['defeater_refinement'] = {'is_applicable': 'defeater_refinement' in deterministic, 'reason': 'Requires an implicated existing defeater.'}

        return {
            "deterministic": deterministic,
            "llm": llm,
            "applicability": applicability,
        }

    def _select_conflict_operators(
        self,
        deterministic,
        llm,
        applicability,
        issue_rules,
        selected_issue,
        existing_events,
        existing_measures,
        system_description="",

    ):
        if len(issue_rules) < 2:
            # Do not claim deterministic applicability when the diagnosis does
            # not identify both conflicting obligations. Candidate generation
            # must remain diagnosis-grounded rather than guessing a rule pair.
            self._add(
                deterministic, applicability, "trigger_refinement", False,
                "Two diagnosed conflicting rules are required to derive a diagnosis-grounded trigger refinement.",
            )
            self._add(
                deterministic, applicability, "defeater_introduction", False,
                "Two diagnosed conflicting rules are required to derive a diagnosis-grounded prioritisation exception.",
            )
            self._add(
                deterministic, applicability, "rule_merging", False,
                "Two diagnosed conflicting rules are required to establish merge compatibility.",
            )
            self._add(
                llm, applicability, "conflict_event_specialization", False,
                "A diagnosed conflicting rule pair is required before semantic event specialization is attempted.",
            )
            self._add(
                llm, applicability, "conflict_measure_specialization", False,
                "Two diagnosed conflicting rules are required to establish a shared environmental measure.",
            )
            self._add(
                llm, applicability, "semantic_rule_merging", False,
                "Two diagnosed conflicting rules are required before Semantic Rule Merging can be attempted.",
            )
            return

        r1, r2 = issue_rules[:2]

        has_context = (
            self.has_conflict_measure_context(
                r1,
                existing_events,
                existing_measures,
            )
            or
            self.has_conflict_measure_context(
                r2,
                existing_events,
                existing_measures,
            )
        )

        self._add(
            deterministic,
            applicability,
            "trigger_refinement",
            has_context,
            (
                "At least one diagnosed conflicting rule contains a declared "
                "contextual measure predicate whose complement can be "
                "propagated into the other rule's trigger."
                if has_context
                else
                "Trigger refinement requires a declared contextual measure "
                "predicate in one of the diagnosed conflicting rules; "
                "event co-occurrence alone is insufficient."
            ),
        )

        same_event = self.same_trigger_event(r1, r2, existing_events)

        defeater_applicable = (
            same_event
            and (
                self.has_contextual_predicate(r1, existing_events)
                or self.has_contextual_predicate(r2, existing_events)
            )
        )

        self._add(
            deterministic,
            applicability,
            "defeater_introduction",
            defeater_applicable,
            (
                "The conflicting rules share the same triggering event and "
                "provide a contextual predicate that can be expressed as a "
                "SLEEC defeater."
                if defeater_applicable
                else
                "Defeater introduction requires an expressible measure-based "
                "priority condition. Cross-event 'unless another rule triggered' "
                "is deferred until SLEEC provides suitable language support."
            ),
        )

        merge_compatible = same_event and self.contextually_specialized_pair(
            r1, r2, existing_events
        )
        self._add(
            deterministic,
            applicability,
            "rule_merging",
            merge_compatible,
            (
                "The rules share the same triggering event and one trigger is a contextual specialization of the other."
                if merge_compatible
                else "Rule merging requires the same triggering event and compatible default/specialized contexts."
            ),
        )

        event_context = self.find_event_specialization_context(
            issue_rules=[r1, r2],
            selected_issue=selected_issue,
            existing_events=existing_events,
            system_description=system_description,

        )

        event_applicable = event_context is not None

        self._add(
            llm,
            applicability,
            "conflict_event_specialization",
            event_applicable,
            (
                "The diagnosis provides independent semantic evidence for a "
                "finer-grained or intermediary event distinction."
                if event_applicable
                else
                "No independently grounded event-specialization relationship "
                "was identified. Distinct events that merely co-occur in the "
                "conflict are insufficient."
            ),
        )

        shared_measures = self.shared_declared_measures(
            r1, r2, existing_measures
        )
        self._add(
            llm,
            applicability,
            "conflict_measure_specialization",
            bool(shared_measures),
            (
                "The conflicting rules share declared measure(s): "
                + ", ".join(sorted(shared_measures))
                if shared_measures
                else "The conflicting rules do not share a declared environmental measure."
            ),
        )
        semantic_merge_applicable = (
            len(issue_rules) >= 2
            and not merge_compatible
        )

        self._add(
            llm,
            applicability,
            "semantic_rule_merging",
            semantic_merge_applicable,
            (
                "LEGOS-SLEEC identified the conflicting rules, but the pair "
                "does not satisfy the structural contract for deterministic "
                "rule_merging. Semantic Rule Merging may therefore propose "
                "alternative merged-rule candidates for formal verification."
                if semantic_merge_applicable
                else
                "Semantic Rule Merging is reserved for diagnosed conflict "
                "pairs for which deterministic rule_merging is not applicable."
            ),
        )

    def _select_redundancy_operators(
        self,
        deterministic,
        llm,
        applicability,
        issue_rules,
        selected_issue,
        existing_events,
        existing_measures,
        system_description,
    ):
        # LEGOS redundancy diagnosis should contain TWO rules.
        if len(issue_rules) >= 2:
            redundant_rule = issue_rules[0]
            because_rule = issue_rules[1]
        else:
            redundant_rule = issue_rules[0] if issue_rules else None
            because_rule = None

        # -----------------------------
        # Deterministic
        # -----------------------------

        self._add(
            deterministic,
            applicability,
            "rule_removal",
            redundant_rule is not None and because_rule is not None,
            (
                "The diagnosis identifies both the redundant rule and the rule that subsumes it."
                if redundant_rule and because_rule
                else "Rule removal requires two diagnosed redundant rules."
            ),
        )

        has_defeater = bool(
            redundant_rule and str(redundant_rule.get("defeater", "")).strip()
        )

        self._add(
            deterministic,
            applicability,
            "defeater_propagation",
            has_defeater,
            (
                "The redundant rule contains a defeater that can be propagated."
                if has_defeater
                else "Defeater propagation requires an existing defeater."
            ),
        )

        # -----------------------------
        # LLM
        # -----------------------------

        event_context = self.find_event_specialization_context(
            issue_rules=[redundant_rule] if redundant_rule else [],
            selected_issue=selected_issue,
            existing_events=existing_events,
            system_description=system_description,

        )

        event_applicable = event_context is not None

        self._add(
            llm,
            applicability,
            "redundancy_event_specialization",
            event_applicable,
            (
                "The diagnosed redundancy contains a trigger event and a distinct "
                "grounded event in the declared vocabulary that can represent the "
                "required semantic distinction."
                if event_applicable
                else
                "Event specialization requires a diagnosed trigger event and a "
                "distinct grounded event supported by the supplied vocabulary "
                "and diagnosis."
            ),
        )

        target_measures = (
            self.declared_measures_in_rule(redundant_rule, existing_measures)
            if redundant_rule
            else set()
        )

        self._add(
            llm,
            applicability,
            "redundancy_measure_specialization",
            bool(target_measures),
            (
                "The redundant rule uses declared measure(s): "
                + ", ".join(sorted(target_measures))
                if target_measures
                else "Measure specialization requires an environmental measure."
            ),
        )
    def _select_concern_operators(
        self,
        deterministic,
        llm,
        applicability,
        issue_rules,
        selected_issue,
    ):
        concern_condition = self.parse_when_condition(selected_issue)
        concern_action = self.parse_then_action(selected_issue)
        has_context = bool(concern_condition)

        # Whole-rule transformations are applicable only when the diagnosed
        # concern capability corresponds to a main rule response.  Ignore
        # polarity and temporal syntax for this capability-level comparison.
        wanted = self.normalize_response_for_temporal_match(concern_action)
        main_branch_target = bool(wanted) and any(
            self.normalize_response_for_temporal_match(rule.get("action", "")) == wanted
            for rule in issue_rules
            if isinstance(rule, dict)
        )

        self._add(
            deterministic,
            applicability,
            "trigger_strengthening",
            has_context and main_branch_target,
            (
                "The witness concern provides contextual conditions that can strengthen the diagnosed main obligation."
                if has_context and main_branch_target
                else "Trigger strengthening requires a diagnosed main-response rule and witness context."
            ),
        )
        self._add(
            deterministic,
            applicability,
            "defeater_introduction",
            has_context and bool(issue_rules),
            "The witness concern can be converted into an explicit exception on a related rule.",
        )
        self._add(
            deterministic,
            applicability,
            "rule_decomposition",
            has_context and main_branch_target,
            (
                "The diagnosed main obligation can be split into context-specific branches using the witness concern."
                if has_context and main_branch_target
                else "Rule decomposition requires a diagnosed main-response rule and witness context."
            ),
        )
        self._add(
            llm,
            applicability,
            "concern_new_rule_generation",
            bool(concern_condition and concern_action),
            "An insufficiency represents missing normative behaviour; a new rule is a candidate semantic repair.",
        )


    def _select_temporal_refinement(
        self,
        deterministic,
        applicability,
        issue_rules,
        selected_issue,
    ):
        """Select Temporal Refinement from diagnosis evidence, not WFI type.

        Applicability requires:
        1. an affected rule with an explicit numeric ``within`` bound;
        2. a diagnosis with a different explicit numeric ``within`` bound;
        3. the diagnosed response and target-rule response to match after
           ignoring polarity and temporal syntax.

        This method never invents a deadline.
        """
        context = self.find_temporal_refinement_context(
            issue_rules=issue_rules,
            selected_issue=selected_issue,
        )
        applicable = context is not None

        if applicable:
            old = context["existing_temporal"]
            new = context["diagnosed_temporal"]
            subtype = (
                "temporal_restriction"
                if self.temporal_to_seconds(new["value"], new["unit"])
                < self.temporal_to_seconds(old["value"], old["unit"])
                else "temporal_relaxation"
            )
            reason = (
                f"The diagnosis supplies {new['text']} for the same response "
                f"whose affected rule uses {old['text']}; {subtype.replace('_', ' ')} "
                "is applicable."
            )
        else:
            reason = (
                "Temporal refinement requires an affected rule and diagnosis "
                "with different explicit numeric temporal bounds for the same response."
            )

        self._add(
            deterministic,
            applicability,
            "temporal_refinement",
            applicable,
            reason,
        )

    def find_temporal_refinement_context(self, issue_rules, selected_issue):
        """Return target rule + diagnosed bound for a valid temporal mismatch."""
        diagnosis_text = str(selected_issue or "")
        requirements = self.extract_temporal_requirements(diagnosis_text)

        # Fallback for concern-like diagnostics where parse_then_action provides
        # a clean response but the generic multi-match pattern finds nothing.
        if not requirements:
            bound = self.extract_temporal_bound(diagnosis_text)
            action = self.parse_then_action(diagnosis_text)
            if bound and action:
                requirements = [{
                    "response": self.normalize_response_for_temporal_match(action),
                    "temporal": bound,
                }]

        for rule in issue_rules:
            if not isinstance(rule, dict):
                continue
            action = str(rule.get("action", ""))
            existing = self.extract_temporal_bound(action)
            if not existing:
                continue

            target_response = self.normalize_response_for_temporal_match(action)
            for req in requirements:
                if req["response"] != target_response:
                    continue
                diagnosed = req["temporal"]
                if self.same_temporal_bound(existing, diagnosed):
                    continue
                return {
                    "target_rule": rule,
                    "existing_temporal": existing,
                    "diagnosed_temporal": diagnosed,
                    "diagnosed_response": req["response"],
                }
        return None

    def extract_temporal_requirements(self, text: object) -> List[dict]:
        """Extract all diagnosed ``then RESPONSE within N UNIT`` requirements."""
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
            temporal = self.extract_temporal_bound(match.group(2))
            if response and temporal:
                results.append({
                    "response": response,
                    "temporal": temporal,
                })
        return results

    def _select_purpose_operators(
        self,
        deterministic,
        llm,
        applicability,
        issue_rules,
        selected_issue,
        existing_responses,
    ):
        purpose_condition = self.parse_when_condition(selected_issue)
        purpose_action = self.parse_then_action(selected_issue)

        # ---------------------------------------------------------
        # Deterministic: Defeater Introduction
        # ---------------------------------------------------------
        defeater_applicable = (
            bool(issue_rules)
            and bool(purpose_condition)
        )

        self._add(
            deterministic,
            applicability,
            "defeater_introduction",
            defeater_applicable,
            (
                "The intended purpose provides a diagnosed context "
                "that can be introduced as an exception to the "
                "blocking rule."
                if defeater_applicable
                else
                "Defeater introduction requires a blocking rule and "
                "a diagnosed purpose context."
            ),
        )

        # ---------------------------------------------------------
        # LLM: Response Refinement
        # ---------------------------------------------------------
        capability_applicable = bool(purpose_action)

        self._add(
            llm,
            applicability,
            "purpose_response_refinement",
            bool(purpose_action),
            (
                "The intended purpose contains a response that can be "
                "semantically refined into a more distinguishable capability."
                if purpose_action
                else
                "Response refinement requires a response in the "
                "diagnosed purpose."
            ),
        )

    def _add(self, destination, applicability, operator, applicable, reason):
        applicability[operator] = {
            "is_applicable": bool(applicable),
            "reason": reason,
        }
        if applicable and operator not in destination:
            destination.append(operator)

    def needs_llm(self, issue_type, **kwargs):
        return bool(self.select(issue_type, **kwargs).get("llm", []))

    def extract_rule_ids(self, text: object) -> List[str]:
        ids = []
        for match in re.finditer(
            r"\b(?:Rule|R|r|C|c)\d+[A-Za-z]*(?:_\d+)*\b",
            str(text or ""),
            flags=re.IGNORECASE,
        ):
            rid = match.group(0)
            if rid not in ids:
                ids.append(rid)
        return ids

    def find_issue_rules(self, selected_issue: object, rules: Sequence[dict]) -> List[dict]:
        rule_ids = [str(rule.get("id")) for rule in rules if rule.get("id") and re.search(r"(?<!\w)"+re.escape(str(rule["id"]))+r"(?!\w)", str(selected_issue))]
        rule_ids.sort(key=lambda rid: str(selected_issue).find(rid))
        by_id = {
            str(rule.get("id", "")).lower(): rule
            for rule in rules
            if isinstance(rule, dict)
        }

        found = []
        for rid in rule_ids:
            rule = by_id.get(rid.lower())
            if rule and rule not in found:
                found.append(rule)

        if found:
            return found

        issue_text = str(selected_issue or "").lower()

        for rule in rules:
            condition = str(rule.get("condition", "")).strip()
            action = str(rule.get("action", "")).strip()
            if (
                (condition and condition.lower() in issue_text)
                or (
                    action
                    and self.normalize_response(action)
                    in self.normalize_response(issue_text)
                )
            ):
                found.append(rule)

        return found[:2]
    def find_event_specialization_context(
        self,
        issue_rules,
        selected_issue,
        existing_events,
        system_description="",
    ):
        """
        Determine whether event_specialization has sufficient grounded
        event-level evidence to be attempted.

        Event specialization is selected only when the diagnosed rules expose
        at least two distinct declared trigger events.

        Events appearing only as responses/actions do not count as candidate
        trigger specializations.

        Measures, Boolean states, defeaters, and diagnosis phrases are not
        converted into events.

        This method selects an operator only.
        It does not generate or formally verify a patch.
        """

        if not issue_rules:
            return None

        existing_events = [
            str(event).strip()
            for event in (existing_events or [])
            if str(event).strip()
        ]

        # Collect only events that actually occur in the CONDITION/TRIGGER
        # of the diagnosed rules.
        diagnosed_trigger_events = []

        for rule in issue_rules:

            if not isinstance(rule, dict):
                continue

            condition = str(rule.get("condition", "") or "")

            for event in existing_events:

                if re.search(
                    rf"(?<![A-Za-z0-9_])"
                    rf"{re.escape(event)}"
                    rf"(?![A-Za-z0-9_])",
                    condition,
                    flags=re.IGNORECASE,
                ):
                    if event not in diagnosed_trigger_events:
                        diagnosed_trigger_events.append(event)

        # Event specialization needs an event-level distinction.
        # One trigger event alone is insufficient.
        # Multiple distinct trigger events in the same diagnosis establish
        # co-occurrence/conflict only. They do NOT establish that one event
        # specializes, refines, or is a subtype/component of another.
        #conflict_event_specialization
        # Therefore, do not select semantic event specialization solely from
        # distinct diagnosed trigger events.
        if len(diagnosed_trigger_events) < 2:
            return None

        return None




    def trigger_event(self, rule: Optional[dict], existing_events: Sequence[str]) -> str:
        if not rule:
            return ""

        condition = str(rule.get("condition", "") or "")
        candidates = []

        for event in existing_events:
            match = re.search(
                rf"(?<![A-Za-z0-9_]){re.escape(str(event))}(?![A-Za-z0-9_])",
                condition,
                flags=re.IGNORECASE,
            )
            if match:
                candidates.append((match.start(), str(event)))

        if candidates:
            return sorted(candidates, key=lambda item: item[0])[0][1]

        for token in re.findall(r"\b[A-Za-z_][A-Za-z0-9_]*\b", condition):
            if token[:1].isupper() and token.lower() not in {
                "and", "or", "not", "true", "false"
            }:
                return token

        return ""

    def same_trigger_event(self, r1, r2, existing_events) -> bool:
        e1 = self.trigger_event(r1, existing_events)
        e2 = self.trigger_event(r2, existing_events)
        return bool(e1 and e2 and e1.lower() == e2.lower())

    def contextually_specialized_pair(self, r1, r2, existing_events) -> bool:
        if not self.same_trigger_event(r1, r2, existing_events):
            return False

        e1 = self.trigger_event(r1, existing_events)
        e2 = self.trigger_event(r2, existing_events)

        c1 = self.condition_terms(r1.get("condition", ""))
        c2 = self.condition_terms(r2.get("condition", ""))

        c1.discard(e1.lower())
        c2.discard(e2.lower())

        return (
            c1.issubset(c2)
            or c2.issubset(c1)
            or bool(c1.intersection(c2))
        )
    def has_conflict_measure_context(
        self,
        rule,
        existing_events,
        existing_measures,
    ) -> bool:
        """
        Return True only when the rule trigger contains a declared
        contextual measure in addition to its leading trigger event.

        This mirrors the applicability requirement used by deterministic
        conflict trigger refinement: event co-occurrence alone is not
        sufficient.
        """
        if not rule:
            return False

        event = self.trigger_event(rule, existing_events)

        measures = self.declared_measures_in_rule(
            rule,
            existing_measures,
        )

        if not measures:
            return False

        # A measure is contextual only when it occurs in the trigger
        # condition in addition to the leading event.
        condition = str(rule.get("condition", "") or "").strip()

        if not condition:
            return False

        if event:
            event_pattern = (
                rf"^\s*{re.escape(str(event))}"
                rf"(?=\s+and\b|\s*$)"
            )

            remainder = re.sub(
                event_pattern,
                "",
                condition,
                count=1,
                flags=re.IGNORECASE,
            ).strip()

            remainder = re.sub(
                r"^and\b",
                "",
                remainder,
                count=1,
                flags=re.IGNORECASE,
            ).strip()
        else:
            remainder = condition

        if not remainder:
            return False

        return any(
            re.search(
                rf"(?<![A-Za-z0-9_])"
                rf"{re.escape(str(measure))}"
                rf"(?![A-Za-z0-9_])",
                remainder,
                flags=re.IGNORECASE,
            )
            for measure in measures
        )
    def has_contextual_predicate(self, rule, existing_events) -> bool:
        event = self.trigger_event(rule, existing_events)
        terms = self.condition_terms(rule.get("condition", ""))
        if event:
            terms.discard(event.lower())
        return bool(terms)

    def condition_terms(self, condition: object) -> Set[str]:
        ignored = {
            "and", "or", "not", "true", "false",
            "when", "then", "within", "unless",
            "seconds", "second", "minutes", "minute",
        }
        return {
            token.lower()
            for token in re.findall(
                r"\b[A-Za-z_][A-Za-z0-9_]*\b",
                str(condition or ""),
            )
            if token.lower() not in ignored
        }

    def declared_measures_in_rule(
        self,
        rule: Optional[dict],
        existing_measures: Sequence[str],
    ) -> Set[str]:
        if not rule:
            return set()

        condition = str(rule.get("condition", "") or "")
        found = set()

        for measure in existing_measures:
            if re.search(
                rf"(?<![A-Za-z0-9_]){re.escape(str(measure))}(?![A-Za-z0-9_])",
                condition,
                flags=re.IGNORECASE,
            ):
                found.add(str(measure))

        return found

    def shared_declared_measures(
        self,
        r1,
        r2,
        existing_measures: Sequence[str],
    ) -> Set[str]:
        m1 = {
            measure.lower(): measure
            for measure in self.declared_measures_in_rule(r1, existing_measures)
        }
        m2 = {
            measure.lower(): measure
            for measure in self.declared_measures_in_rule(r2, existing_measures)
        }
        return {m1[key] for key in set(m1).intersection(m2)}

    def issue_mentions_measure(self, issue, existing_measures) -> bool:
        text = str(issue or "")
        return any(
            re.search(
                rf"(?<![A-Za-z0-9_]){re.escape(str(measure))}(?![A-Za-z0-9_])",
                text,
                flags=re.IGNORECASE,
            )
            for measure in existing_measures
        )

    def extract_temporal_bound(self, text: object) -> Optional[dict]:
        """Return a numeric ``within`` bound from a rule/diagnosis, if present."""
        match = re.search(
            r"\bwithin\s+(\d+(?:\.\d+)?)\s+"
            r"(seconds?|minutes?|hours?|days?)\b",
            str(text or ""),
            flags=re.IGNORECASE,
        )
        if not match:
            return None
        return {
            "value": float(match.group(1)),
            "unit": match.group(2).lower(),
            "text": match.group(0),
        }


    def temporal_to_seconds(self, value: float, unit: str) -> float:
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

    def same_temporal_bound(self, left: dict, right: dict) -> bool:
        if not left or not right:
            return False
        return abs(
            self.temporal_to_seconds(left["value"], left["unit"])
            - self.temporal_to_seconds(right["value"], right["unit"])
        ) < 1e-9

    def normalize_response_for_temporal_match(self, text: object) -> str:
        response = str(text or "").strip()
        response = re.sub(r"^not\s+", "", response, flags=re.IGNORECASE)
        response = re.sub(
            r"\s+within\s+\d+(?:\.\d+)?\s+(?:seconds?|minutes?|hours?|days?)\b.*$",
            "", response, flags=re.IGNORECASE
        )
        return re.sub(r"\s+", " ", response).strip().lower()

    def find_temporal_target_rule(self, issue_rules, diagnosed_action):
        wanted = self.normalize_response_for_temporal_match(diagnosed_action)
        for rule in issue_rules:
            action = str(rule.get("action", ""))
            if not self.extract_temporal_bound(action):
                continue
            if self.normalize_response_for_temporal_match(action) == wanted:
                return rule
        return None

    def parse_when_condition(self, text: object) -> str:
        match = re.search(
            r"\bwhen\s+(.+?)\s+then\b",
            str(text or ""),
            flags=re.IGNORECASE | re.DOTALL,
        )
        return re.sub(r"\s+", " ", match.group(1)).strip() if match else ""

    def parse_then_action(self, text: object) -> str:
        match = re.search(
            r"\bthen\s+(.+?)(?:\s+within\b|\s+unless\b|$)",
            str(text or ""),
            flags=re.IGNORECASE | re.DOTALL,
        )
        return re.sub(r"\s+", " ", match.group(1)).strip() if match else ""

    def normalize_response(self, action: object) -> str:
        text = str(action or "").strip().lower()
        text = re.split(
            r"\bwithin\b|\bunless\b|\beventually\b|\botherwise\b",
            text,
            maxsplit=1,
            flags=re.IGNORECASE,
        )[0]
        return re.sub(r"\s+", " ", text).strip()
