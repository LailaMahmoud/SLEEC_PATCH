import re
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional, Tuple


# ============================================================
# Normalization helpers
# ============================================================

def normalize(text: Optional[str]) -> str:
    """Normalize whitespace/case without destroying SLEEC structure."""
    if text is None:
        return ""
    text = str(text).strip().lower()
    text = re.sub(r"\s+", " ", text)
    return text


def tokens(text: Optional[str]) -> set:
    """
    Tokenize SLEEC expressions for lightweight structural similarity.
    """
    if not text:
        return set()

    return set(
        re.findall(
            r"[a-zA-Z_]\w*|[-+]?\d+(?:\.\d+)?|[<>=]+",
            normalize(text),
        )
    )


def jaccard(a: Optional[str], b: Optional[str]) -> float:
    """Jaccard similarity over normalized SLEEC tokens."""
    ta = tokens(a)
    tb = tokens(b)

    if not ta and not tb:
        return 1.0

    if not ta or not tb:
        return 0.0

    return len(ta & tb) / len(ta | tb)


# ============================================================
# Parsed rule representation
# ============================================================

@dataclass
class ParsedRule:
    rule_id: str
    trigger: str
    response: str
    polarity: str
    defeater: str = ""
    defeater_response: str = ""
    temporal: str = ""
    raw: str = ""

    def to_dict(self):
        return asdict(self)


# ============================================================
# Manual Similarity Evaluator
# ============================================================

class ManualSimilarityEvaluator:

    TEMP_RE = re.compile(
        r"\b("
        r"within\s+(?:[-+]?\d+(?:\.\d+)?|[A-Za-z_]\w*)\s+"
        r"(?:seconds?|minutes?|hours?|days?)"
        r"|eventually"
        r")\b",
        re.IGNORECASE,
    )

    NUMERIC_TEMP_RE = re.compile(
        r"\bwithin\s+([-+]?\d+(?:\.\d+)?)\s+"
        r"(seconds?|minutes?|hours?|days?)\b",
        re.IGNORECASE,
    )

    UNIT_SECONDS = {
        "second": 1.0,
        "seconds": 1.0,
        "minute": 60.0,
        "minutes": 60.0,
        "hour": 3600.0,
        "hours": 3600.0,
        "day": 86400.0,
        "days": 86400.0,
    }

    # --------------------------------------------------------
    # Parsing
    # --------------------------------------------------------

    def parse_rule(self, raw: str) -> Optional[ParsedRule]:
        """
        Parse one SLEEC rule.

        Supports:
            R3 when A then B
            R3 when A then not B
            R3 when A then B within 5 minutes
            R3 when A then B eventually
            R3 when A then B unless C
            R3 when A then B unless C then D
            R3 when A then B unless C then not D
        """

        if raw is None:
            return None

        raw = str(raw).strip()

        if not raw:
            return None

        # A multi-rule patch must be handled by parse_patch_rules().
        if "\n" in raw:
            nonempty = [
                line.strip()
                for line in raw.splitlines()
                if line.strip()
            ]

            if len(nonempty) > 1:
                return None

            if nonempty:
                raw = nonempty[0]

        m = re.match(
            r"(?is)^\s*(\S+)\s+when\s+(.+?)\s+then\s+(.+)$",
            raw,
        )

        if not m:
            return None

        rule_id = m.group(1).strip()
        trigger = m.group(2).strip()
        remainder = m.group(3).strip()

        # ----------------------------------------------------
        # Separate main response from defeater
        # ----------------------------------------------------

        defeater = ""
        defeater_response = ""

        unless_parts = re.split(
            r"\s+unless\s+",
            remainder,
            maxsplit=1,
            flags=re.IGNORECASE,
        )

        main_response = unless_parts[0].strip()

        if len(unless_parts) == 2:
            defeater_part = unless_parts[1].strip()

            # A defeater may itself have:
            # CONDITION then ALTERNATIVE_RESPONSE
            defeater_then = re.split(
                r"\s+then\s+",
                defeater_part,
                maxsplit=1,
                flags=re.IGNORECASE,
            )

            defeater = defeater_then[0].strip()

            if len(defeater_then) == 2:
                defeater_response = defeater_then[1].strip()

        # ----------------------------------------------------
        # Extract temporal constraint from main response
        # ----------------------------------------------------

        temporal = ""

        tm = self.TEMP_RE.search(main_response)

        if tm:
            temporal = tm.group(1).strip()

            main_response = (
                main_response[:tm.start()]
                + main_response[tm.end():]
            ).strip()

        # ----------------------------------------------------
        # Main response polarity
        # ----------------------------------------------------

        if re.match(r"(?i)^not\s+", main_response):
            polarity = "negative"
            response = re.sub(
                r"(?i)^not\s+",
                "",
                main_response,
                count=1,
            ).strip()
        else:
            polarity = "positive"
            response = main_response.strip()

        return ParsedRule(
            rule_id=rule_id,
            trigger=trigger,
            response=response,
            polarity=polarity,
            defeater=defeater,
            defeater_response=defeater_response,
            temporal=temporal,
            raw=raw,
        )

    def parse_patch_rules(self, raw: str) -> List[ParsedRule]:
        """
        Parse a patch containing one or multiple SLEEC rules.

        Rule decomposition is commonly stored as:
            R3_1 when ...
            R3_2 when ...
        """

        if raw is None:
            return []

        text = str(raw).strip()

        if not text:
            return []

        lines = [
            line.strip()
            for line in text.splitlines()
            if line.strip()
        ]

        parsed = []

        for line in lines:
            rule = self.parse_rule(line)

            if rule is not None:
                parsed.append(rule)

        return parsed

    def parse_sleec_rules(self, sleec_text: str) -> Dict[str, ParsedRule]:
        """
        Parse all rule-like lines in a SLEEC specification.
        """

        rules = {}

        for raw_line in str(sleec_text).splitlines():
            line = raw_line.strip()

            if not line:
                continue

            if line.startswith("//"):
                continue

            if not re.match(
                r"(?i)^\S+\s+when\s+",
                line,
            ):
                continue

            parsed = self.parse_rule(line)

            if parsed:
                rules[parsed.rule_id] = parsed

        return rules

    # --------------------------------------------------------
    # Expert changes
    # --------------------------------------------------------

    def expert_changes(
        self,
        original_text: str,
        corrected_text: str,
    ) -> Dict:
        """
        Derive expert changes by comparing original and corrected specs.
        """

        original = self.parse_sleec_rules(original_text)
        corrected = self.parse_sleec_rules(corrected_text)

        removed = {}
        added = {}
        modified = {}

        for rid, old_rule in original.items():
            if rid not in corrected:
                removed[rid] = old_rule
                continue

            new_rule = corrected[rid]

            if self.rule_signature(old_rule) != self.rule_signature(new_rule):
                modified[rid] = {
                    "old": old_rule,
                    "new": new_rule,
                }

        for rid, new_rule in corrected.items():
            if rid not in original:
                added[rid] = new_rule

        return {
            "original": original,
            "corrected": corrected,
            "removed": removed,
            "added": added,
            "modified": modified,
        }

    @staticmethod
    def rule_signature(rule: ParsedRule) -> Tuple:
        return (
            normalize(rule.trigger),
            normalize(rule.response),
            normalize(rule.polarity),
            normalize(rule.defeater),
            normalize(rule.defeater_response),
            normalize(rule.temporal),
        )

    # --------------------------------------------------------
    # Component similarities
    # --------------------------------------------------------

    def temporal_similarity(
        self,
        generated: Optional[str],
        expert: Optional[str],
    ) -> Optional[float]:
        """
        Compare temporal constraints.

        None means the temporal component is not applicable because
        neither repair contains temporal information.  A value of 0.0
        means temporal information is present on only one side, or the
        two temporal expressions are incompatible.
        """
        g = normalize(generated)
        e = normalize(expert)

        if not g and not e:
            return None

        if not g or not e:
            return 0.0

        if g == e:
            return 1.0

        # "eventually" is qualitative; never invent a numeric deadline.
        if g == "eventually" or e == "eventually":
            return 1.0 if g == e else 0.0

        g_num = self.numeric_temporal_seconds(g)
        e_num = self.numeric_temporal_seconds(e)

        if g_num is not None and e_num is not None:
            if g_num == e_num:
                return 1.0
            high = max(g_num, e_num)
            low = min(g_num, e_num)
            return 0.0 if high == 0 else low / high

        # Symbolic / non-numeric temporal expressions remain comparable
        # structurally, but are not coerced to numeric values.
        return jaccard(g, e)

    def numeric_temporal_seconds(
        self,
        temporal: Optional[str],
    ) -> Optional[float]:

        if not temporal:
            return None

        m = self.NUMERIC_TEMP_RE.search(str(temporal))

        if not m:
            return None

        value = float(m.group(1))
        unit = m.group(2).lower()

        multiplier = self.UNIT_SECONDS.get(unit)

        if multiplier is None:
            return None

        return value * multiplier

    @staticmethod
    def average_applicable(components: Dict[str, Optional[float]]) -> float:
        """Average only components that are applicable to this comparison."""
        values = [
            float(score)
            for score in components.values()
            if score is not None
        ]
        return sum(values) / len(values) if values else 0.0

    @staticmethod
    def _combined_defeater(rule: ParsedRule) -> str:
        return " ".join(
            x for x in [rule.defeater, rule.defeater_response] if x
        ).strip()

    def compare_rules(
        self,
        generated: ParsedRule,
        expert: ParsedRule,
        compare_target: bool = True,
        operation: Optional[str] = None,
    ) -> Dict[str, Optional[float]]:
        """
        Applicability-aware component comparison.

        * A component absent on both sides is N/A (None), not a free 1.0.
        * A component present on only one side is a mismatch (0.0).
        * When target IDs are intentionally irrelevant, target is N/A.
        * Operation type controls which changed component is emphasized,
          while preserved rule content remains visible for interpretation.
        """
        op = normalize(operation)

        target_score = None
        if compare_target:
            target_score = (
                1.0
                if normalize(generated.rule_id) == normalize(expert.rule_id)
                else 0.0
            )

        trigger_score = jaccard(generated.trigger, expert.trigger)
        response_score = jaccard(generated.response, expert.response)
        polarity_score = (
            1.0
            if normalize(generated.polarity) == normalize(expert.polarity)
            else 0.0
        )

        generated_defeater = self._combined_defeater(generated)
        expert_defeater = self._combined_defeater(expert)
        if not generated_defeater and not expert_defeater:
            defeater_score = None
        elif not generated_defeater or not expert_defeater:
            defeater_score = 0.0
        else:
            defeater_score = jaccard(generated_defeater, expert_defeater)

        temporal_score = self.temporal_similarity(
            generated.temporal,
            expert.temporal,
        )

        components = {
            "target": target_score,
            "trigger": trigger_score,
            "response": response_score,
            "polarity": polarity_score,
            "defeater": defeater_score,
            "temporal": temporal_score,
        }

        # Operation-aware relevance.  We retain preservation components
        # (response/polarity and, where applicable, context) but never
        # reward a component that is absent on both sides.
        relevant = {
        # ---------------------------------------------------------
        # New-rule generation
        # ---------------------------------------------------------
        "new_rule_generation": {
            "trigger", "response", "polarity", "defeater", "temporal"
        },
        "concern_new_rule_generation": {
            "trigger", "response", "polarity", "defeater", "temporal"
        },

        # ---------------------------------------------------------
        # Event specialization
        # ---------------------------------------------------------
        "event_specialization": {
            "target", "trigger", "response", "polarity",
            "defeater", "temporal"
        },
        "conflict_event_specialization": {
            "target", "trigger", "response", "polarity",
            "defeater", "temporal"
        },
        "redundancy_event_specialization": {
            "target", "trigger", "response", "polarity",
            "defeater", "temporal"
        },

        # ---------------------------------------------------------
        # Measure specialization
        # ---------------------------------------------------------
        "measure_specialization": {
            "target", "trigger", "response", "polarity",
            "defeater", "temporal"
        },
        "conflict_measure_specialization": {
            "target", "trigger", "response", "polarity",
            "defeater", "temporal"
        },
        "redundancy_measure_specialization": {
            "target", "trigger", "response", "polarity",
            "defeater", "temporal"
        },

        # ---------------------------------------------------------
        # Capability refinement
        # ---------------------------------------------------------
        "capability_refinement": {
            "target", "trigger", "response", "polarity",
            "defeater", "temporal"
        },
        "purpose_capability_refinement": {
            "target", "trigger", "response", "polarity",
            "defeater", "temporal"
        },

        # ---------------------------------------------------------
        # Deterministic operators
        # ---------------------------------------------------------
        "trigger_strengthening": {
            "target", "trigger", "response", "polarity",
            "defeater", "temporal"
        },
        "trigger_refinement": {
            "target", "trigger", "response", "polarity",
            "defeater", "temporal"
        },
        "defeater_introduction": {
            "target", "trigger", "response", "polarity",
            "defeater", "temporal"
        },
        "defeater_propagation": {
            "target", "trigger", "response", "polarity",
            "defeater", "temporal"
        },
        "purpose_defeater": {
            "target", "trigger", "response", "polarity",
            "defeater", "temporal"
        },

        # ---------------------------------------------------------
        # Rule merging
        # ---------------------------------------------------------
        "rule_merging": {
            "trigger", "response", "polarity", "defeater", "temporal"
        },
        "semantic_rule_merging": {
            "trigger", "response", "polarity", "defeater", "temporal"
        },
    }
        selected_names = relevant.get(op, set(components))
        selected = {
            name: score
            for name, score in components.items()
            if name in selected_names
        }

        m_sim = self.average_applicable(selected)
        applicable_count = sum(v is not None for v in selected.values())

        result = dict(components)
        result["applicable_count"] = applicable_count
        result["m_sim"] = m_sim
        return result

    # --------------------------------------------------------
    # Temporal refinement comparison
    # --------------------------------------------------------

    def evaluate_temporal_refinement(
        self,
        generated: ParsedRule,
        original_rule: Optional[ParsedRule],
        expert_rules: List[ParsedRule],
    ) -> Dict:
        """
        Compare a generated temporal transition against the best expert
        temporal transition for the same response/context.

        This allows an expert correction to express the new bound in an
        added rule (e.g., R21b) rather than forcing a same-ID match.
        """
        if original_rule is None:
            return {
                "m_sim": 0.0,
                "components": {},
                "matched_expert_rule": None,
                "warning": "Temporal refinement requires the original target rule.",
            }

        generated_new = self.numeric_temporal_seconds(generated.temporal)
        original_old = self.numeric_temporal_seconds(original_rule.temporal)

        if original_old is None or generated_new is None:
            return {
                "m_sim": 0.0,
                "components": {},
                "matched_expert_rule": None,
                "warning": (
                    "Temporal refinement requires explicit numeric old and "
                    "generated temporal bounds."
                ),
            }

        best = None
        best_score = -1.0

        for expert_rule in expert_rules:
            expert_new = self.numeric_temporal_seconds(expert_rule.temporal)
            if expert_new is None:
                continue

            trigger = jaccard(generated.trigger, expert_rule.trigger)
            response = jaccard(generated.response, expert_rule.response)
            polarity = (
                1.0 if normalize(generated.polarity)
                == normalize(expert_rule.polarity) else 0.0
            )

            # The old bound is anchored in the original target rule.
            old_bound = 1.0

            if generated_new == expert_new:
                new_bound = 1.0
            else:
                high = max(generated_new, expert_new)
                low = min(generated_new, expert_new)
                new_bound = 0.0 if high == 0 else low / high

            generated_subtype = self.temporal_subtype(
                original_old, generated_new
            )
            expert_subtype = self.temporal_subtype(
                original_old, expert_new
            )
            subtype = (
                1.0
                if generated_subtype is not None
                and generated_subtype == expert_subtype
                else 0.0
            )

            components = {
                "trigger": trigger,
                "response": response,
                "polarity": polarity,
                "old_bound": old_bound,
                "new_bound": new_bound,
                "temporal_subtype": subtype,
            }
            score = self.average_applicable(components)

            if score > best_score:
                best_score = score
                best = (
                    expert_rule,
                    components,
                    generated_subtype,
                    expert_subtype,
                )

        if best is None:
            return {
                "m_sim": 0.0,
                "components": {},
                "matched_expert_rule": None,
                "warning": "No expert rule with a comparable numeric temporal bound found.",
            }

        expert_rule, components, generated_subtype, expert_subtype = best
        components["applicable_count"] = 6

        return {
            "m_sim": best_score,
            "components": components,
            "matched_expert_rule": expert_rule.rule_id,
            "generated_temporal_subtype": generated_subtype,
            "expert_temporal_subtype": expert_subtype,
            "warning": None,
        }

    @staticmethod
    def temporal_subtype(
        old_seconds: Optional[float],
        new_seconds: Optional[float],
    ) -> Optional[str]:

        if old_seconds is None or new_seconds is None:
            return None

        if new_seconds < old_seconds:
            return "temporal_restriction"

        if new_seconds > old_seconds:
            return "temporal_relaxation"

        return "unchanged"

    # --------------------------------------------------------
    # Best expert match
    # --------------------------------------------------------

    def best_match(
        self,
        generated: ParsedRule,
        expert_rules: List[ParsedRule],
        compare_target: bool = True,
        operation: Optional[str] = None,
    ) -> Tuple[Optional[ParsedRule], Optional[Dict]]:

        best_rule = None
        best_components = None
        best_score = -1.0

        for expert in expert_rules:
            components = self.compare_rules(
                generated,
                expert,
                compare_target=compare_target,
                operation=operation,
            )

            score = components["m_sim"]

            if score > best_score:
                best_score = score
                best_rule = expert
                best_components = components

        return best_rule, best_components

    # --------------------------------------------------------
    # Rule decomposition
    # --------------------------------------------------------

    def evaluate_decomposition(
        self,
        generated_rules: List[ParsedRule],
        target_rule_id: str,
        changes: Dict,
    ) -> Dict:

        expert_candidates = []

        # Expert-added subrules such as R3_1, R3_2.
        target_norm = normalize(target_rule_id)

        for rid, rule in changes["added"].items():
            rid_norm = normalize(rid)

            if (
                rid_norm.startswith(target_norm + "_")
                or rid_norm.startswith(target_norm)
            ):
                expert_candidates.append(rule)

        # Also consider corrected target itself.
        corrected_target = self.get_rule_case_insensitive(
            changes["corrected"],
            target_rule_id,
        )

        if corrected_target is not None:
            expert_candidates.append(corrected_target)

        # If no target-related expert candidates were found,
        # use all expert-added rules.
        if not expert_candidates:
            expert_candidates = list(
                changes["added"].values()
            )

        if not generated_rules:
            return {
                "m_sim": 0.0,
                "components": {},
                "matched_expert_rule": None,
                "warning": "Could not parse decomposition rules.",
            }

        if not expert_candidates:
            return {
                "m_sim": 0.0,
                "components": {},
                "matched_expert_rule": None,
                "warning": (
                    "No corresponding expert decomposition/change found."
                ),
            }

        per_rule = []
        matched_ids = []
        remaining = list(expert_candidates)

        # One-to-one matching: an expert rule cannot be reused for two
        # generated decomposition subrules.
        for generated in generated_rules:
            best_rule, best_components = self.best_match(
                generated,
                remaining,
                compare_target=False,
                operation="rule_decomposition",
            )

            if best_rule is not None and best_components is not None:
                per_rule.append(best_components["m_sim"])
                matched_ids.append(best_rule.rule_id)
                remaining = [
                    r for r in remaining
                    if normalize(r.rule_id) != normalize(best_rule.rule_id)
                ]

        if not per_rule:
            score = 0.0
        else:
            score = sum(per_rule) / len(per_rule)

        return {
            "m_sim": score,
            "components": {
                "decomposed_rule_scores": per_rule,
            },
            "matched_expert_rule": ",".join(matched_ids),
            "warning": None,
        }

    # --------------------------------------------------------
    # Main evaluation
    # --------------------------------------------------------

    def evaluate(
        self,
        operation: str,
        target_rule_id: str,
        proposed_rule: str,
        original_text: str,
        corrected_text: str,
    ) -> Dict:

        operation = normalize(operation)
        target_rule_id = str(target_rule_id or "").strip()

        changes = self.expert_changes(
            original_text,
            corrected_text,
        )

        original_target = self.get_rule_case_insensitive(
            changes["original"],
            target_rule_id,
        )

        corrected_target = self.get_rule_case_insensitive(
            changes["corrected"],
            target_rule_id,
        )

        # ====================================================
        # Rule removal
        # ====================================================

        if operation == "rule_removal":
            removed_target = self.get_rule_case_insensitive(
                changes["removed"],
                target_rule_id,
            )

            score = 1.0 if removed_target is not None else 0.0

            return {
                "m_sim": score,
                "components": {
                    "expert_removed_same_target": score,
                },
                "matched_expert_rule": (
                    removed_target.rule_id
                    if removed_target
                    else None
                ),
                "warning": None,
                "expert_match": False,
                "operation_type": operation,
            }

        # ====================================================
        # Parse generated patch
        # ====================================================

        generated_rules = self.parse_patch_rules(
            proposed_rule
        )

        if not generated_rules:
            return {
                "m_sim": 0.0,
                "components": {},
                "matched_expert_rule": None,
                "warning": "Could not parse proposed rule",
                "expert_match": False,
                "operation_type": operation,
            }

        # ====================================================
        # Rule decomposition
        # ====================================================

        if operation == "rule_decomposition":
            result = self.evaluate_decomposition(
                generated_rules,
                target_rule_id,
                changes,
            )

            result["expert_match"] = False
            return result

        generated = generated_rules[0]

        # ====================================================
        # Temporal refinement
        # ====================================================

        if operation == "temporal_refinement":
            temporal_candidates = []

            if corrected_target is not None:
                temporal_candidates.append(corrected_target)

            # Include expert-added rules and modified-rule new versions.
            # The evaluator chooses the best temporal transition rather
            # than requiring the same rule ID.
            temporal_candidates.extend(changes["added"].values())
            temporal_candidates.extend(
                item["new"] for item in changes["modified"].values()
            )

            result = self.evaluate_temporal_refinement(
                generated,
                original_target,
                temporal_candidates,
            )

            result["expert_match"] = False
            result["operation_type"] = "temporal_refinement"
            return result

        # ====================================================
        # New rule generation
        # ====================================================

        if operation == "new_rule_generation":
            expert_added = list(
                changes["added"].values()
            )

            if not expert_added:
                return {
                    "m_sim": 0.0,
                    "components": {},
                    "matched_expert_rule": None,
                    "warning": "No expert-added rule found",
                    "expert_match": False,
                }

            best_rule, components = self.best_match(
                generated,
                expert_added,
                compare_target=False,
                operation=operation,
            )

            if best_rule is None or components is None:
                return {
                    "m_sim": 0.0,
                    "components": {},
                    "matched_expert_rule": None,
                    "warning": "No expert match found",
                    "expert_match": False,
                }

            return {
                "m_sim": components["m_sim"],
                "components": components,
                "matched_expert_rule": best_rule.rule_id,
                "warning": None,
                "expert_match": False,
                "operation_type": operation,
            }

        # ====================================================
        # Existing-rule repair
        # ====================================================

        if corrected_target is not None:
            components = self.compare_rules(
                generated,
                corrected_target,
                compare_target=True,
                operation=operation,
            )

            return {
                "m_sim": components["m_sim"],
                "components": components,
                "matched_expert_rule": corrected_target.rule_id,
                "warning": None,
                "expert_match": False,
                "operation_type": operation,
            }

        # ====================================================
        # Fallback:
        # compare with expert modified/added rules
        # ====================================================

        expert_candidates = []

        for item in changes["modified"].values():
            expert_candidates.append(item["new"])

        expert_candidates.extend(
            changes["added"].values()
        )

        best_rule, components = self.best_match(
            generated,
            expert_candidates,
            compare_target=False,
            operation=operation,
        )

        if best_rule is None or components is None:
            return {
                "m_sim": 0.0,
                "components": {},
                "matched_expert_rule": None,
                "warning": "No corresponding expert rule found",
                "expert_match": False,
                "operation_type": operation,
            }

        return {
            "m_sim": components["m_sim"],
            "components": components,
            "matched_expert_rule": best_rule.rule_id,
            "warning": None,
            "expert_match": False,
        }

    # --------------------------------------------------------
    # Utility
    # --------------------------------------------------------

    @staticmethod
    def get_rule_case_insensitive(
        rules: Dict[str, ParsedRule],
        rule_id: str,
    ) -> Optional[ParsedRule]:

        wanted = normalize(rule_id)

        for rid, rule in rules.items():
            if normalize(rid) == wanted:
                return rule

        return None
