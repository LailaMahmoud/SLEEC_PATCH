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
        patches = []
        concern = self.parse_when_then(selected_issue)
        # Generic target selection across the currently loaded specification.
        # Do not choose the first rule that merely shares the same response.
        target_rule = self.find_best_related_rule(selected_issue, rules)

        if not target_rule:
            return patches

        original_rule = self.rule_to_text(target_rule)
        diagnosis_context = concern.get("condition") or target_rule.get("condition", "")
        context = (
            self.specific_context(
                diagnosis_context,
                target_rule.get("condition", "")
            )
            or diagnosis_context
        )

        if "trigger_strengthening" in operators and context:
            patches.append({
                "patch_id": f'd_strengthen_{target_rule["id"]}',
                "id": f'd_strengthen_{target_rule["id"]}',
                "source": "deterministic",
                "operation": "trigger_strengthening",
                "target_rule_id": target_rule["id"],
                "original_rule": original_rule,
                "proposed_rule": self.strengthen_trigger_with_condition(
                    target_rule,
                    context
                ),
                "natural_language_explanation": (
                    "Strengthen the rule trigger using the concern context "
                    "identified by the diagnosis."
                )
            })

        if "defeater_introduction" in operators and context:
            proposed_rule = self.add_defeater(target_rule, context)

            if proposed_rule != original_rule:
                patches.append({
                    "patch_id": f'd_concern_defeater_{target_rule["id"]}',
                    "id": f'd_concern_defeater_{target_rule["id"]}',
                    "source": "deterministic",
                    "operation": "defeater_introduction",
                    "target_rule_id": target_rule["id"],
                    "original_rule": original_rule,
                    "proposed_rule": proposed_rule,
                    "natural_language_explanation": (
                        "Add the concern context as an explicit exception to the "
                        "related rule."
                    )
                })

        if "rule_decomposition" in operators and context:
            patches.append(
                self.make_rule_decomposition_patch(
                    target_rule,
                    context,
                    "Split the related rule into context-specific branches for the concern."
                )
            )

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
        raw1 = self.rule_raw(r1)
        context = self.wrap_group(self.usable_context(r2.get("condition", "")))

        if not context:
            return raw1

        split2 = self.split_trigger_body(self.rule_raw(r2))
        alternative = split2[2].strip() if split2 else str(r2.get("action", "")).strip()

        if alternative:
            return f"{raw1} unless {context} then {alternative}"

        return f"{raw1} unless {context}"

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
