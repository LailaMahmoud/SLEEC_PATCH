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
            "defeater_introduction",
            "rule_decomposition",
        ],
        "purpose_blocking": [
            "purpose_defeater",
        ],
    }

    BASE_LLM_OPERATORS = {
        "conflicts": [
            "event_specialization",
            "measure_specialization",
        ],
        "situational_conflicts": [
            "event_specialization",
            "measure_specialization",
        ],
        "redundancies": [
            "event_specialization",
            "measure_specialization",
            "capability_refinement",
        ],
        "concerns": [
            "new_rule_generation",
        ],
        "purpose_blocking": [
            "capability_refinement",
        ],
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

    def select(
        self,
        issue_type: str,
        rules: Optional[Sequence[dict]] = None,
        selected_issue: object = "",
        existing_events: Optional[Sequence[str]] = None,
        existing_measures: Optional[Sequence[str]] = None,
        existing_responses: Optional[Sequence[str]] = None,
    ) -> Dict[str, object]:
        issue_type = self.ISSUE_ALIASES.get(issue_type, issue_type)
        rules = list(rules or [])
        existing_events = list(existing_events or [])
        existing_measures = list(existing_measures or [])
        existing_responses = list(existing_responses or [])

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
    ):
        if len(issue_rules) < 2:
            self._add(
                deterministic,
                applicability,
                "trigger_refinement",
                True,
                "Conflict diagnosis is available; witness/context predicates can refine a trigger.",
            )
            self._add(
                deterministic,
                applicability,
                "defeater_introduction",
                True,
                "The diagnosed conflict can be resolved by explicitly prioritising one obligation.",
            )
            self._add(
                deterministic,
                applicability,
                "rule_merging",
                False,
                "Two diagnosed rules are required to establish merge compatibility.",
            )
            self._add(
                llm,
                applicability,
                "event_specialization",
                True,
                "A finer-grained event may distinguish partially conflicting behaviours.",
            )
            self._add(
                llm,
                applicability,
                "measure_specialization",
                False,
                "A shared declared measure could not be established.",
            )
            return

        r1, r2 = issue_rules[:2]

        has_context = (
            self.has_contextual_predicate(r1, existing_events)
            or self.has_contextual_predicate(r2, existing_events)
            or self.issue_mentions_measure(selected_issue, existing_measures)
        )
        self._add(
            deterministic,
            applicability,
            "trigger_refinement",
            has_context,
            (
                "The diagnosed conflict contains contextual predicates that can be propagated into a trigger."
                if has_context
                else "No contextual predicate was identified for trigger refinement."
            ),
        )

        self._add(
            deterministic,
            applicability,
            "defeater_introduction",
            True,
            "Two diagnosed conflicting obligations are available for explicit prioritisation.",
        )

        same_event = self.same_trigger_event(r1, r2, existing_events)
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

        event_applicable = bool(
            self.trigger_event(r1, existing_events)
            or self.trigger_event(r2, existing_events)
        )
        self._add(
            llm,
            applicability,
            "event_specialization",
            event_applicable,
            (
                "At least one diagnosed rule has a triggering event that can be semantically specialized."
                if event_applicable
                else "No triggering event was identified for event specialization."
            ),
        )

        shared_measures = self.shared_declared_measures(
            r1, r2, existing_measures
        )
        self._add(
            llm,
            applicability,
            "measure_specialization",
            bool(shared_measures),
            (
                "The conflicting rules share declared measure(s): "
                + ", ".join(sorted(shared_measures))
                if shared_measures
                else "The conflicting rules do not share a declared environmental measure."
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
    ):
        target = issue_rules[0] if issue_rules else None

        self._add(
            deterministic,
            applicability,
            "rule_removal",
            target is not None or bool(self.extract_rule_ids(selected_issue)),
            "The diagnosed redundant rule can be removed.",
        )

        has_defeater = bool(target and str(target.get("defeater", "")).strip())
        self._add(
            deterministic,
            applicability,
            "defeater_propagation",
            has_defeater,
            (
                "The redundant rule contains a defeater that can be propagated into its trigger."
                if has_defeater
                else "Defeater propagation requires an existing defeater."
            ),
        )

        event_applicable = bool(
            target and self.trigger_event(target, existing_events)
        )
        self._add(
            llm,
            applicability,
            "event_specialization",
            event_applicable,
            "The redundant rule has a trigger event that can be semantically specialized.",
        )

        target_measures = (
            self.declared_measures_in_rule(target, existing_measures)
            if target
            else set()
        )
        self._add(
            llm,
            applicability,
            "measure_specialization",
            bool(target_measures),
            (
                "The redundant rule uses declared measure(s): "
                + ", ".join(sorted(target_measures))
                if target_measures
                else "Measure specialization requires an environmental measure in the redundant rule."
            ),
        )

        has_action = bool(target and str(target.get("action", "")).strip())
        self._add(
            llm,
            applicability,
            "capability_refinement",
            has_action,
            "The redundant rule has a response that can be replaced by a more distinguishable capability.",
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
        has_context = bool(concern_condition)

        self._add(
            deterministic,
            applicability,
            "trigger_strengthening",
            has_context and bool(issue_rules),
            "The witness concern provides contextual conditions that can strengthen a related rule.",
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
            has_context and bool(issue_rules),
            "A related rule can be split into context-specific branches using the witness concern.",
        )
        self._add(
            llm,
            applicability,
            "new_rule_generation",
            True,
            "An insufficiency represents missing normative behaviour; a new rule is a candidate semantic repair.",
        )

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

        self._add(
            deterministic,
            applicability,
            "purpose_defeater",
            bool(issue_rules) and bool(purpose_condition),
            "The intended purpose supplies a context that can be introduced as an exception to the blocking rule.",
        )
        self._add(
            llm,
            applicability,
            "capability_refinement",
            bool(purpose_action or existing_responses),
            "The intended behaviour contains a response that can be refined into a more distinguishable capability.",
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
            r"\b(?:Rule|R|r)\d+(?:_\d+)?\b",
            str(text or ""),
            flags=re.IGNORECASE,
        ):
            rid = match.group(0)
            if rid not in ids:
                ids.append(rid)
        return ids

    def find_issue_rules(self, selected_issue: object, rules: Sequence[dict]) -> List[dict]:
        rule_ids = self.extract_rule_ids(selected_issue)
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

    def parse_when_condition(self, text: object) -> str:
        match = re.search(
            r"\b(?:when|exists)\s+(.+?)\s+(?:then|while)\b",
            str(text or ""),
            flags=re.IGNORECASE | re.DOTALL,
        )
        return re.sub(r"\s+", " ", match.group(1)).strip() if match else ""

    def parse_then_action(self, text: object) -> str:
        match = re.search(
            r"\b(?:then|while)\s+(.+?)(?:\s+within\b|\s+unless\b|$)",
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
