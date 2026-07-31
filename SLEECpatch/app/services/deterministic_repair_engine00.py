import re


class DeterministicRepairEngine:

    def generate(self, issue_type, selected_issue, rules, operators):
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

        return patches

    def generate_redundancy_patches(self, selected_issue, rules, operators):
        patches = []
        issue_text = str(selected_issue)

        rule_id = self.extract_rule_id(issue_text)
        target_rule = self.find_rule(rule_id, rules)
        original_rule = self.rule_to_text(target_rule) if target_rule else issue_text

        if "rule_removal" in operators and rule_id:
            patches.append({
                "patch_id": f"d_remove_{rule_id}",
                "id": f"d_remove_{rule_id}",
                "source": "deterministic",
                "operation": "rule_removal",
                "target_rule_id": rule_id,
                "original_rule": original_rule,
                "proposed_rule": "",
                "natural_language_explanation": (
                    f"Remove {rule_id} because it is redundant."
                )
            })

        if "defeater_propagation" in operators and target_rule and target_rule.get("defeater"):
            patches.append({
                "patch_id": f"d_propagate_{rule_id}",
                "id": f"d_propagate_{rule_id}",
                "source": "deterministic",
                "operation": "defeater_propagation",
                "target_rule_id": rule_id,
                "original_rule": original_rule,
                "proposed_rule": self.propagate_defeater(target_rule),
                "natural_language_explanation": (
                    f"Propagate the defeater of {rule_id} into its trigger "
                    "so the rule is explicit about when it applies."
                )
            })

        if "rule_merging" in operators and rule_id:
            patches.append({
                "patch_id": f"d_merge_{rule_id}",
                "id": f"d_merge_{rule_id}",
                "source": "deterministic",
                "operation": "rule_merging",
                "target_rule_id": rule_id,
                "original_rule": original_rule,
                "proposed_rule": original_rule,
                "natural_language_explanation": (
                    f"Merge {rule_id} with the equivalent rule to avoid redundancy."
                )
            })

        return patches

    def generate_concern_patches(self, selected_issue, rules, operators):
        """Generate deterministic repairs for an insufficiency/concern.

        A concern ``when C then not A [within t]`` means that the undesirable
        response ``not A`` is still feasible in context ``C``.  Deterministic
        repairs therefore encode the negation of the concern: ensure ``A`` in
        ``C`` while preserving the original behaviour outside ``C``.
        """
        patches = []
        concern = self.parse_when_then(selected_issue)
        target_rule = self.find_best_related_rule(selected_issue, rules)

        if not target_rule:
            return patches

        original_rule = self.rule_to_text(target_rule)
        diagnosis_context = concern.get("condition") or target_rule.get("condition", "")
        context = (
            self.specific_context(diagnosis_context, target_rule.get("condition", ""))
            or diagnosis_context
        )
        context = self.clean_condition(context)

        if not context:
            return patches

        concern_action = concern.get("action", "").strip()
        desired_action = self.opposite_action(concern_action)
        desired_action = desired_action or target_rule.get("action", "")
        desired_action = self.apply_concern_deadline(
            desired_action,
            concern.get("temporal", "")
        )

        # 1. Trigger strengthening: specialize the positive obligation to the
        # diagnosed context.  Do not copy an existing defeater that permits the
        # concern response in exactly that context.
        if "trigger_strengthening" in operators:
            proposed_rule = (
                f'{target_rule["id"]} when {target_rule["condition"]} '
                f'and ({context}) then {desired_action}'
            )
            if proposed_rule != original_rule:
                patches.append({
                    "patch_id": f'd_strengthen_{target_rule["id"]}',
                    "id": f'd_strengthen_{target_rule["id"]}',
                    "source": "deterministic",
                    "operation": "trigger_strengthening",
                    "target_rule_id": target_rule["id"],
                    "original_rule": original_rule,
                    "proposed_rule": proposed_rule,
                    "natural_language_explanation": (
                        "Strengthen the positive obligation with the diagnosed "
                        "concern context and enforce the negation of the concern."
                    )
                })

        # 2. Defeater repair: when an existing defeater enables the concern,
        # narrow that defeater so it cannot fire inside the diagnosed context.
        if "defeater_introduction" in operators:
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
                    "operation": "defeater_introduction",
                    "target_rule_id": target_rule["id"],
                    "original_rule": original_rule,
                    "proposed_rule": proposed_rule,
                    "natural_language_explanation": (
                        "Refine the existing defeater so the undesirable concern "
                        "response is not enabled in the diagnosed context."
                    )
                })

        # 3. Rule decomposition: an explicit concern branch enforces the
        # desired response; the complementary branch retains the original rule.
        if "rule_decomposition" in operators:
            proposed_rule = self.decompose_rule_for_concern(
                target_rule,
                context,
                desired_action
            )
            if proposed_rule != original_rule:
                patches.append({
                    "id": f'd_decompose_{target_rule["id"]}',
                    "patch_id": f'd_decompose_{target_rule["id"]}',
                    "source": "deterministic",
                    "issue_type": "concerns",
                    "operation": "rule_decomposition",
                    "target_rule_id": target_rule["id"],
                    "original_rule": original_rule,
                    "proposed_rule": proposed_rule,
                    "natural_language_explanation": (
                        "Split the rule into a concern-context branch that "
                        "enforces the desired response and a complementary branch "
                        "that preserves the original behaviour."
                    )
                })

        return patches

    def generate_purpose_patches(self, selected_issue, rules, operators):
        patches = []
        purpose = self.parse_when_then(selected_issue)
        target_rule = self.find_related_rule(selected_issue, rules)

        if not target_rule:
            target_rule = self.find_opposing_rule(
                purpose.get("action", ""),
                rules
            )

        if not target_rule:
            return patches

        original_rule = self.rule_to_text(target_rule)
        purpose_context = self.specific_context(
            purpose.get("condition", ""),
            target_rule.get("condition", "")
        )

        if "purpose_defeater" in operators and purpose_context:
            proposed_rule = self.add_defeater(target_rule, purpose_context)

            if proposed_rule != original_rule:
                patches.append({
                    "patch_id": f'd_purpose_defeater_{target_rule["id"]}',
                    "id": f'd_purpose_defeater_{target_rule["id"]}',
                    "source": "deterministic",
                    "operation": "purpose_defeater",
                    "target_rule_id": target_rule["id"],
                    "original_rule": original_rule,
                    "proposed_rule": proposed_rule,
                    "natural_language_explanation": (
                        "Add the purpose-specific context as an exception so the "
                        "blocking rule no longer prevents the desired behaviour."
                    )
                })

        if "trigger_refinement" in operators and purpose.get("condition"):
            patches.append({
                "patch_id": f'd_purpose_refine_{target_rule["id"]}',
                "id": f'd_purpose_refine_{target_rule["id"]}',
                "source": "deterministic",
                "operation": "trigger_refinement",
                "target_rule_id": target_rule["id"],
                "original_rule": original_rule,
                "proposed_rule": self.refine_trigger_against_condition(
                    target_rule,
                    purpose_context or purpose.get("condition")
                ),
                "natural_language_explanation": (
                    "Refine the blocking rule so it does not apply in the "
                    "diagnosed purpose context."
                )
            })

        if "rule_decomposition" in operators and purpose_context:
            patches.append(
                self.make_rule_decomposition_patch(
                    target_rule,
                    purpose_context,
                    "Split the blocking rule into purpose-specific branches."
                )
            )

        return patches

    def generate_conflict_patches(self, issue_type, selected_issue, rules, operators):
        patches = []
        conflict_rules = self.find_conflicting_rules(selected_issue, rules)

        if len(conflict_rules) < 2:
            return patches

        r1 = conflict_rules[0]
        r2 = conflict_rules[1]

        if "defeater_introduction" in operators:
            patches.append({
                "id": "d1",
                "patch_id": "d1",
                "source": "deterministic",
                "issue_type": issue_type,
                "operation": "defeater_introduction",
                "target_rule_id": r1["id"],
                "original_rule": self.rule_to_text(r1),
                "proposed_rule": self.add_defeater(r1, self.specific_context(r2["condition"], r1["condition"])),
                "natural_language_explanation":
                    "The conflicting context is converted into an explicit defeater."
            })

            patches.append({
                "id": "d2",
                "patch_id": "d2",
                "source": "deterministic",
                "issue_type": issue_type,
                "operation": "defeater_introduction",
                "target_rule_id": r2["id"],
                "original_rule": self.rule_to_text(r2),
                "proposed_rule": self.add_defeater(r2, self.specific_context(r1["condition"], r2["condition"])),
                "natural_language_explanation":
                    "The opposite rule context is given an explicit defeater."
            })

        if "trigger_refinement" in operators:
            patches.append({
                "id": "d_trigger_refine_1",
                "patch_id": "d_trigger_refine_1",
                "source": "deterministic",
                "issue_type": issue_type,
                "operation": "trigger_refinement",
                "target_rule_id": r1["id"],
                "original_rule": self.rule_to_text(r1),
                "proposed_rule": self.refine_trigger_against_condition(
                    r1,
                    r2["condition"]
                ),
                "natural_language_explanation":
                    "The trigger is refined using the other conflicting rule's context."
            })

            patches.append({
                "id": "d_trigger_refine_2",
                "patch_id": "d_trigger_refine_2",
                "source": "deterministic",
                "issue_type": issue_type,
                "operation": "trigger_refinement",
                "target_rule_id": r2["id"],
                "original_rule": self.rule_to_text(r2),
                "proposed_rule": self.refine_trigger_against_condition(
                    r2,
                    r1["condition"]
                ),
                "natural_language_explanation":
                    "The opposite trigger is refined using the first rule's context."
            })

        if "trigger_strengthening" in operators:
            patches.append({
                "id": "d3",
                "patch_id": "d3",
                "source": "deterministic",
                "issue_type": issue_type,
                "operation": "trigger_strengthening",
                "target_rule_id": r1["id"],
                "original_rule": self.rule_to_text(r1),
                "proposed_rule": self.strengthen_trigger_with_condition(
                    r1,
                    self.complementary_context(
                        self.specific_context(r2["condition"], r1["condition"])
                    )
                ),
                "natural_language_explanation":
                    "The trigger is strengthened using contextual information."
            })

        if "rule_merging" in operators and self.compatible_for_merging(r1, r2):
            patches.append({
                "id": "d4",
                "patch_id": "d4",
                "source": "deterministic",
                "issue_type": issue_type,
                "operation": "rule_merging",
                "target_rule_id": r1["id"],
                "original_rule": self.rule_to_text(r1) + "\n" + self.rule_to_text(r2),
                "proposed_rule": self.merge_conflicting_rules(r1, r2),
                "natural_language_explanation":
                    "The two conflicting rules are merged into one rule."
            })

        if "rule_decomposition" in operators:
            patches.append({
                "id": f'd_decompose_{r1["id"]}',
                "patch_id": f'd_decompose_{r1["id"]}',
                "source": "deterministic",
                "issue_type": issue_type,
                "operation": "rule_decomposition",
                "target_rule_id": r1["id"],
                "rule_ids": [r1["id"], r2["id"]],
                "original_rule": self.rule_to_text(r1),
                "proposed_rule": self.decompose_conflicting_rule(r1, r2),
                "natural_language_explanation": (
                    "The broad rule is split into two contextual branches "
                    "with distinct responses."
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

        for match in re.finditer(r"\b(?:Rule|R|r)\d+(?:_\d+)?\b", str(text)):
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
            if isinstance(rule, dict) and rule.get("id", "") == rule_id:
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
            if rule["id"] == rule_id
        ]

        if len(found) >= 2:
            return found[:2]

        found = []

        for rule in rules:
            if self.rule_id_in_text(rule["id"], text) or rule["action"] in text:
                found.append(rule)

        if len(found) >= 2:
            return found[:2]

        for r1 in rules:
            for r2 in rules:
                if r1["id"] == r2["id"]:
                    continue

                if self.is_opposite_action(r1["action"], r2["action"]):
                    return [r1, r2]

        return []

    def find_related_rule(self, selected_issue, rules):
        """
        Backward-compatible wrapper around context-aware target selection.
        """
        return self.find_best_related_rule(selected_issue, rules)

    def find_best_related_rule(self, selected_issue, rules):
        """
        Select the rule most strongly related to the diagnosed WFI.

        This is use-case independent: it uses only the current diagnosis and
        the rules in the currently loaded SLEEC specification.
        """
        issue_text = str(selected_issue or "")
        parsed = self.parse_when_then(issue_text)
        issue_condition = parsed.get("condition", "")
        issue_action = self.normalize_action(parsed.get("action", ""))

        # Highest-confidence signal: an explicitly diagnosed rule ID.
        for rule_id in self.extract_rule_ids(issue_text):
            rule = self.find_rule(rule_id, rules)
            if rule:
                return rule

        issue_terms = self.condition_terms(issue_condition)
        best_rule = None
        best_score = -1

        for rule in rules:
            if not isinstance(rule, dict):
                continue

            score = 0
            rule_action = self.normalize_action(rule.get("action", ""))
            rule_condition = self.clean_condition(rule.get("condition", ""))
            rule_terms = self.condition_terms(rule_condition)

            # Same normative response is important, but is not sufficient alone.
            if issue_action and rule_action == issue_action:
                score += 10

            # Reward shared diagnosis/trigger vocabulary.
            shared_terms = issue_terms.intersection(rule_terms)
            score += 4 * len(shared_terms)

            # Strongly reward containment of the rule trigger in the WFI trigger.
            if (
                rule_condition
                and issue_condition
                and self.normalized_condition(rule_condition)
                in self.normalized_condition(issue_condition)
            ):
                score += 8

            # A response encoded in a defeater may also identify the related rule.
            defeater_matches = 0
            for defeater_action in self.defeater_actions(
                rule.get("defeater", "")
            ):
                if (
                    issue_action
                    and self.normalize_action(defeater_action) == issue_action
                ):
                    defeater_matches += 1

            score += 5 * defeater_matches

            # Do not select an unrelated rule just because every score is zero.
            if score > best_score:
                best_score = score
                best_rule = rule

        return best_rule if best_score > 0 else None

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

    def find_opposing_rule(self, action, rules):
        action = str(action or "").strip()

        if not action:
            return None

        for rule in rules:
            if self.is_opposite_action(action, rule.get("action", "")):
                return rule

        return self.find_rule_by_action(action, rules)

    def is_opposite_action(self, a, b):
        a = str(a).strip()
        b = str(b).strip()

        return (
            a == f"not {b}"
            or b == f"not {a}"
            or a == f"not{b}"
            or b == f"not{a}"
        )

    def add_defeater(self, rule, defeater):
        base = f'{rule["id"]} when {rule["condition"]} then {rule["action"]}'
        defeater = self.clean_condition(defeater)
        existing = self.clean_condition(rule.get("defeater", ""))

        if not defeater:
            return self.rule_to_text(rule)

        if existing:
            existing_parts = {
                part.strip().lower()
                for part in re.split(r"\s+OR\s+", existing, flags=re.IGNORECASE)
                if part.strip()
            }

            if defeater.lower() in existing_parts:
                return self.rule_to_text(rule)

            return base + " " + self.format_defeater(f"{existing} OR {defeater}")

        return base + " " + self.format_defeater(defeater)

    def strengthen_trigger(self, rule, context):
        return self.strengthen_trigger_with_condition(rule, context)

    def strengthen_trigger_with_condition(self, rule, context):
        context = self.clean_condition(context)

        if not context:
            return self.rule_to_text(rule)

        return (
            f'{rule["id"]} when {rule["condition"]} and ({context}) '
            f'then {rule["action"]}{self.defeater_suffix(rule)}'
        )

    def refine_trigger_against_condition(self, rule, context):
        context = self.specific_context(
            self.clean_condition(context),
            rule.get("condition", "")
        )

        if not context:
            return self.rule_to_text(rule)

        return (
            f'{rule["id"]} when {rule["condition"]} and not ({context}) '
            f'then {rule["action"]}{self.defeater_suffix(rule)}'
        )

    def complementary_context(self, context):
        context = self.clean_condition(context)
        match = re.fullmatch(
            r"not\s+\{?([A-Za-z_][A-Za-z0-9_]*)\}?",
            context,
            flags=re.IGNORECASE
        )
        return match.group(1) if match else context

    def compatible_for_merging(self, r1, r2):
        c1 = {
            part.lower()
            for part in self.condition_parts(r1.get("condition", ""))
        }
        c2 = {
            part.lower()
            for part in self.condition_parts(r2.get("condition", ""))
        }
        return bool(c1.intersection(c2))

    def propagate_defeater(self, rule):
        defeater = self.clean_condition(rule.get("defeater", ""))

        if not defeater:
            return self.rule_to_text(rule)

        return (
            f'{rule["id"]} when {rule["condition"]} and not ({defeater}) '
            f'then {rule["action"]}'
        )

    def merge_conflicting_rules(self, r1, r2):
        context = self.clean_condition(r2.get("condition", ""))
        alternative = str(r2.get("action", "")).strip()
        existing = self.clean_condition(r1.get("defeater", ""))

        if existing and context:
            context = f"({existing}) OR ({context})"
        elif existing:
            context = existing

        if not context:
            return self.rule_to_text(r1)

        if alternative:
            return (
                f'{r1["id"]} when {r1["condition"]} then {r1["action"]} '
                f'unless ({context}) then {alternative}'
            )

        return (
            f'{r1["id"]} when {r1["condition"]} then {r1["action"]} '
            f'unless ({context})'
        )

    def decompose_conflicting_rule(self, r1, r2):
        context = self.specific_context(
            r2.get("condition", ""),
            r1.get("condition", "")
        )
        context = self.clean_condition(context)

        if not context:
            return self.rule_to_text(r1)

        return (
            f'{r1["id"]}_1 when {r1["condition"]} and not ({context}) '
            f'then {r1["action"]}{self.defeater_suffix(r1)}\n'
            f'{r1["id"]}_2 when {r1["condition"]} and ({context}) '
            f'then {r2["action"]}{self.defeater_suffix(r2)}'
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
        context = self.clean_condition(context)

        if not context:
            return self.rule_to_text(rule)

        return (
            f'{rule["id"]}_1 when {rule["condition"]} and ({context}) '
            f'then {rule["action"]}{self.defeater_suffix(rule)}\n'
            f'{rule["id"]}_2 when {rule["condition"]} and not ({context}) '
            f'then {rule["action"]}{self.defeater_suffix(rule)}'
        )

    def parse_when_then(self, text):
        """Parse a diagnosis while retaining polarity and temporal bounds."""
        match = re.search(
            r"\bwhen\s+(.+?)\s+then\s+(.+?)(?:\n|$)",
            str(text),
            flags=re.IGNORECASE | re.DOTALL
        )

        if not match:
            return {"condition": "", "action": "", "temporal": ""}

        response = match.group(2).strip()
        response = re.split(
            r"\bunless\b|\botherwise\b",
            response,
            maxsplit=1,
            flags=re.IGNORECASE
        )[0].strip()

        temporal_match = re.search(
            r"\b(within\s+\d+(?:\.\d+)?\s+"
            r"(?:seconds?|minutes?|hours?|days?)|eventually|immediately)\b",
            response,
            flags=re.IGNORECASE
        )
        temporal = temporal_match.group(1).strip() if temporal_match else ""
        action = re.sub(
            r"\s+\b(within\s+\d+(?:\.\d+)?\s+"
            r"(?:seconds?|minutes?|hours?|days?)|eventually|immediately)\b.*$",
            "",
            response,
            flags=re.IGNORECASE
        ).strip()

        return {
            "condition": self.clean_condition(match.group(1)),
            "action": action,
            "temporal": temporal
        }

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

        narrowed = f"({defeater_condition}) and not ({context})"
        return (
            f'{rule["id"]} when {rule["condition"]} then {rule["action"]} '
            f'unless ({narrowed}) then {alternative}'
        )

    def is_negative(self, action):
        return bool(re.match(r"^not\s+", str(action or "").strip(), re.IGNORECASE))

    def decompose_rule_for_concern(self, rule, context, desired_action):
        return (
            f'{rule["id"]}_1 when {rule["condition"]} and ({context}) '
            f'then {desired_action}\n'
            f'{rule["id"]}_2 when {rule["condition"]} and not ({context}) '
            f'then {rule["action"]}{self.defeater_suffix(rule)}'
        )

    def clean_condition(self, condition):
        condition = str(condition or "").strip()
        condition = condition.replace("\n", " ")
        condition = re.sub(r"\s+", " ", condition)
        condition = condition.strip()
        return condition

    def specific_context(self, diagnosis_condition, rule_condition):
        diagnosis_parts = self.condition_parts(diagnosis_condition)
        rule_parts = self.condition_parts(rule_condition)
        specific = [
            part
            for part in diagnosis_parts
            if part.lower() not in {p.lower() for p in rule_parts}
        ]

        if specific:
            return " and ".join(specific)

        return self.clean_condition(diagnosis_condition)

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

    def defeater_suffix(self, rule):
        defeater = self.clean_condition(rule.get("defeater", ""))

        if not defeater:
            return ""

        return " " + self.format_defeater(defeater)

    def format_defeater(self, defeater):
        defeater = self.clean_condition(defeater)

        if not defeater:
            return ""

        simple_symbol = re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", defeater)

        if simple_symbol:
            return f"unless {{{defeater}}}"

        return f"unless ({defeater})"

    def rule_to_text(self, rule):
        text = f'{rule["id"]} when {rule["condition"]} then {rule["action"]}'

        if rule.get("defeater"):
            text += " " + self.format_defeater(rule["defeater"])

        return text
