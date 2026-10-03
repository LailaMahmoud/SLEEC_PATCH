"""Conservative repairs selected from source references and observed traces."""
import copy
import re

from services.rule_model import (parse_sleec_ast, source, expression_value,
                                 edit_inside, with_guard, conjunction, negation, compact)
from services.repair_operator_selector import RepairOperatorSelector
from services.boolean_simplifier import simplify_patch, simplify_rule


def selected_source(model, issue_type, diagnosis):
    block = getattr(model, "concernBlock" if issue_type == "concerns" else "purposeBlock", None)
    items = getattr(block, "concerns" if issue_type == "concerns" else "purposes", []) if block else []
    matches = [node for node in items if node.name == diagnosis.get("source_id")]
    return matches[0] if len(matches) == 1 else None


def concern_context(text, model, issue_type, diagnosis):
    """Identify the source concern for LLM generation without constructing a rule."""
    if issue_type != "concerns":
        return None
    node = selected_source(model, issue_type, diagnosis)
    if node is None or node.response is None or node.next or node.response.next:
        return None
    response = node.response.head
    if response.alternative or response.nd or response.defeater:
        return None
    occ = response.occ
    if occ.limit and occ.inf:
        return None
    timing = text[occ.event._tx_position_end:occ._tx_position_end].strip()
    return {"source_id": node.name, "source_text": source(text, node),
            "trigger_event": node.trigger.event.name, "condition": source(text, node.condition),
            "response_event": occ.event.event.name, "response_negated": occ.neg,
            "timing": timing}


def response_occurrences(response, path="main"):
    """Include nested exceptions and alternatives without flattening their scope."""
    yield path, response.occ
    for name in ("alternative", "nd"):
        branch = getattr(response, name, None)
        if branch is not None:
            yield from response_occurrences(branch.response, f"{path}.{name}")
    for index, defeater in enumerate(getattr(response, "defeater", [])):
        if defeater.response is not None:
            yield from response_occurrences(defeater.response, f"{path}.unless[{index}]")


def observed_contexts(diagnosis, trigger):
    trace = diagnosis.get("trace", [])
    snapshots = {entry.get("timestamp_raw", str(entry.get("timestamp"))): entry.get("values", {})
                 for entry in trace if entry.get("kind") == "measure"}
    return [{"timestamp": entry.get("timestamp"),
             "values": snapshots.get(entry.get("timestamp_raw", str(entry.get("timestamp"))), {})}
            for entry in trace if entry.get("kind") == "event" and entry.get("name") == trigger]


def target_resolution(text, issue_type, diagnosis):
    model = parse_sleec_ast(text)
    rules = model.ruleBlock.rules
    addition_scope = concern_context(text, model, issue_type, diagnosis)
    # An LLM may propose a new rule for a diagnosed concern even when there is
    # no existing rule to edit. This context is not a generated repair.
    common = {"addition_scope": addition_scope}
    explicit_redundant = diagnosis.get("redundant_rule_ids", []) if issue_type == "redundancies" else []
    reported = list(dict.fromkeys(diagnosis.get("affected_rule_ids", []) + explicit_redundant))
    if reported:
        ids = [node.name for node in rules if node.name in reported]
        if len(ids) != len(set(reported)):
            return {"rule_ids": [], "basis": "unresolved", "addition_scope": None, "reason": "A reported rule is absent from the current specification."}
        if issue_type == "redundancies":
            ids = list(explicit_redundant) if explicit_redundant else ([diagnosis["source_id"]] if diagnosis.get("source_id") in ids else [])
        return {**common, "rule_ids": ids, "basis": "detector_report",
                "reason": "These rules are identified in the detector report."}
    node = selected_source(model, issue_type, diagnosis)
    if node is None or node.response is None:
        return {**common, "rule_ids": [], "basis": "unresolved", "reason": "No rule references or supported source requirement identify a repair target."}
    trigger, response_event = node.trigger.event.name, node.response.head.occ.event.event.name
    contexts = observed_contexts(diagnosis, trigger)
    candidates = []
    related = []
    for rule in rules:
        branches = [path for path, occ in response_occurrences(rule.response)
                    if occ.event.event.name == response_event]
        if branches:
            related.append({"rule_id": rule.name, "trigger_event": rule.trigger.event.name,
                            "response_paths": branches})
        if rule.trigger.event.name != trigger:
            continue
        if not branches:
            continue
        candidates.append(rule.name)
    if not candidates:
        return {**common, "rule_ids": [], "candidate_rule_ids": candidates,
                "related_responses": related, "basis": "unresolved",
                "reason": "The source and witness do not identify a related repair target."}
    return {**common, "rule_ids": candidates, "related_responses": related,
            "basis": "source_and_trace" if contexts else "source_match",
            "observed_contexts": contexts,
            "reason": "These rules match the source trigger and response. Each is a separate repair hypothesis subject to verification; a false guard is retained as a possible broadening target."}


def next_id(base, used):
    index = 1
    while f"{base}_{index}" in used:
        index += 1
    result = f"{base}_{index}"
    used.add(result)
    return result


def immediate_branches(text, response, context=""):
    """Effective guards for immediate obligations, including exception priority.

    Timed/reparation responses need temporal reasoning; a measure observed at
    one trigger cannot stand in for its value at a later trigger.
    """
    if response.alternative or response.nd:
        return
    remaining = context
    for defeater in reversed(response.defeater):
        guard = source(text, defeater.expr)
        if defeater.response is not None:
            yield from immediate_branches(text, defeater.response, conjunction(remaining, guard))
        remaining = conjunction(remaining, negation(guard))
    if not response.occ.limit and not response.occ.inf:
        yield response, remaining


def grouped_conflict_repairs(text, model, targets, operators, add):
    """Resolve all immediate competitors of a reported rule in one candidate.

    Extra peers are source-derived hypotheses, not added to the solver proof.
    They must share the trigger and impose the opposite immediate response.
    """
    grouped = set()
    if not {"trigger_refinement", "defeater_introduction"}.intersection(operators):
        return grouped
    for rule in targets:
        branches = list(immediate_branches(text, rule.response))
        for branch, _ in branches:
            contexts, peers = [], []
            for other in model.ruleBlock.rules:
                if other is rule or other.trigger.event.name != rule.trigger.event.name:
                    continue
                for opposite, guard in immediate_branches(text, other.response, source(text, other.condition)):
                    if (opposite.occ.event.event.name != branch.occ.event.event.name
                            or opposite.occ.neg == branch.occ.neg or not guard):
                        continue
                    if guard not in contexts:
                        contexts.append(guard)
                    if other.name not in peers:
                        peers.append(other.name)
            # Pairwise generation below already covers one competing rule.
            if len(peers) < 2:
                continue
            grouped.add(rule.name)
            context = contexts[0]
            for guard in contexts[1:]:
                context = f"({context} or {guard})"
            explanation = (f"Give {', '.join(peers)} priority in their effective measure contexts. "
                           "These same-trigger, opposite-response rules are source-derived repair hypotheses; review the priority choice.")
            if "trigger_refinement" in operators:
                add(rule, "trigger_refinement", with_guard(text, rule,
                    conjunction(source(text, rule.condition), negation(context))), explanation)
            if "defeater_introduction" in operators:
                # Braces are required for an exception inside an exception's
                # response; a bare trailing unless would affect the whole rule.
                body = source(text, branch).strip()
                if branch is rule.response:
                    replacement = body + f" unless {context}"
                else:
                    if body.startswith("{") and body.endswith("}"):
                        body = body[1:-1].strip()
                    replacement = "{" + body + f" unless {context}" + "}"
                add(rule, "defeater_introduction", edit_inside(text, rule, branch, replacement), explanation)
    return grouped


def generate_repairs(text, issue_type, diagnosis, operators):
    allowed = {op for ops in RepairOperatorSelector.BASE_DETERMINISTIC_OPERATORS.values() for op in ops}
    if set(operators) - allowed:
        raise ValueError("The deterministic generator accepts only the paper's deterministic operators.")
    model = parse_sleec_ast(text)
    resolution = target_resolution(text, issue_type, diagnosis)

    if issue_type in {"conflicts", "situational_conflicts"}:
        print("\n========== EVIDENCE REPAIR DEBUG ==========")
        print("ISSUE TYPE:", issue_type)
        print("DIAGNOSIS:", diagnosis)
        print("RESOLUTION:", resolution)
        print("OPERATORS:", operators)
        print("===========================================\n")

    targets = [node for node in model.ruleBlock.rules if node.name in resolution["rule_ids"]]
    used = {node.name for node in model.ruleBlock.rules} | {node.name for node in model.definitions}
    used.update(label.name for node in model.definitions if type(node).__name__ == "ScalarMeasure"
                for label in node.type.scaleParams)
    for block_name, items_name in (("concernBlock", "concerns"), ("purposeBlock", "purposes")):
        block = getattr(model, block_name, None)
        used.update(node.name for node in getattr(block, items_name, []))
    patches = []

    def add(rule, operation, proposed, explanation):
        proposed = simplify_rule(proposed)
        if compact(proposed) == compact(simplify_rule(source(text, rule))):
            return
        patch_id = f"d_{operation}_{rule.name}_{len(patches) + 1}"
        patches.append(simplify_patch({"patch_id": patch_id, "id": patch_id, "source": "deterministic",
                        "issue_type": issue_type, "operation": operation, "target_rule_id": rule.name,
                        "original_rule": source(text, rule), "proposed_rule": proposed,
                        "diagnosis": copy.deepcopy(diagnosis), "target_resolution": copy.deepcopy(resolution),
                        "natural_language_explanation": explanation}))

    if issue_type == "redundancies" and "rule_removal" in operators:
        if targets:
            add(targets[0], "rule_removal", "", "Remove only the explicitly diagnosed redundant targets; retain supporting rules.")
            if len(targets) > 1:
                patches[-1]['removed_rule_ids'] = [rule.name for rule in targets[1:]]
                patches[-1]['original_rule'] = "\n".join(source(text, rule) for rule in targets)
    if issue_type == "redundancies" and "defeater_propagation" in operators:
        for rule in targets:
            for defeater in rule.response.defeater:
                # Move the selected exception into the guard; retain every
                # other response/exception verbatim. Verification checks that
                # the supporting path supplies the eliminated behaviour.
                body = (text[rule.response._tx_position:defeater._tx_position]
                        + text[defeater._tx_position_end:rule.response._tx_position_end]).strip()
                add(rule, "defeater_propagation",
                    with_guard(text, rule, conjunction(source(text, rule.condition), negation(source(text, defeater.expr))), response=body),
                    "Exclude the redundant exception path from this rule; retain supporting rules.")

    if issue_type in {"concerns", "purpose_blocking"}:
        requirement = selected_source(model, issue_type, diagnosis)
        # Multi-stage requirements need an operator for their whole sequence.
        # Never silently repair only the first stage.
        if requirement is None or requirement.response is None or requirement.next or requirement.response.next:
            return patches
        response = requirement.response.head
        if response.alternative or response.nd or response.defeater:
            return patches
        guard = source(text, requirement.condition)
        occ = response.occ
        for rule in targets:
            if rule.trigger.event.name != requirement.trigger.event.name:
                continue
            if issue_type == "purpose_blocking":
                if "defeater_introduction" in operators and guard:
                    add(rule, "defeater_introduction", source(text, rule) + f" unless {guard}",
                        "Relax this blocking rule only in the purpose context; preserve its existing responses and exceptions.")
                continue
            main_matches = rule.response.occ.event.event.name == occ.event.event.name
            desired = source(text, occ)
            desired = re.sub(r"^not\s+", "", desired) if occ.neg else "not " + desired
            old_guard = source(text, rule.condition)
            opposite = rule.response.occ.neg != occ.neg
            if "trigger_strengthening" in operators and main_matches and guard and old_guard and opposite:
                add(rule, "trigger_strengthening",
                    with_guard(text, rule, f"({old_guard} or {guard})"),
                    "Broaden the measure context with OR, retaining the trigger event and complete response.")
            if "rule_decomposition" in operators and main_matches and guard:
                changed_body = desired + text[rule.response.occ._tx_position_end:rule.response._tx_position_end]
                # Splitting an unchanged response into C / not C is logically
                # identical to the input. It cannot repair the concern, and can
                # cause expensive redundant-rule proofs for the new fragments.
                if compact(changed_body) != compact(source(text, rule.response)):
                    proposed = (with_guard(text, rule, conjunction(old_guard, guard), response=changed_body)
                                + "\n" + with_guard(text, rule, conjunction(old_guard, negation(guard)), next_id(rule.name, used)))
                    add(rule, "rule_decomposition", proposed,
                        "Enforce the response preventing the concern in its context; preserve the complete original response in the complementary branch.")
            if "deadline_refinement" in operators and main_matches and opposite and not rule.response.occ.neg:
                selector = RepairOperatorSelector()
                old = selector.extract_temporal_bound(source(text, rule.response.occ))
                new = selector.extract_temporal_bound(source(text, occ))
                if old and new and selector.temporal_to_seconds(new['value'], new['unit']) < selector.temporal_to_seconds(old['value'], old['unit']):
                    # Only simple upper bounds; interval lower bounds are not discarded.
                    replacement = source(text, rule.response.occ).replace(old['text'], new['text'], 1)
                    add(rule, "deadline_refinement", edit_inside(text, rule, rule.response.occ, replacement),
                        "Tighten only the deadline to the bound supplied by the concern.")
            if "defeater_refinement" in operators and guard:
                for defeater in rule.response.defeater:
                    if defeater.response is None and not main_matches:
                        continue
                    if defeater.response is not None and (defeater.response.occ.event.event.name != occ.event.event.name
                            or defeater.response.occ.neg != occ.neg):
                        continue
                    replacement = conjunction(source(text, defeater.expr), negation(guard))
                    add(rule, "defeater_refinement", edit_inside(text, rule, defeater.expr, replacement),
                        "Exclude the concern context from this existing exception; preserve all responses and other exceptions.")
        return patches

    if issue_type in {"conflicts", "situational_conflicts"}:
        grouped = grouped_conflict_repairs(text, model, targets, operators, add)
        for rule in targets:
            for other in targets:
                if other is rule:
                    continue
                if rule.name in grouped and rule.trigger.event.name == other.trigger.event.name:
                    continue
                # These proposals explicitly choose which obligation takes
                # priority. Stakeholder review remains separate from proof.
                context = source(text, other.condition)
                if "trigger_refinement" in operators and context:
                    add(rule, "trigger_refinement",
                        with_guard(text, rule, conjunction(source(text, rule.condition), negation(context))),
                        f"Give {other.name} priority in its measure context. Retain this rule's complete response and exceptions; review the priority choice.")
                if "defeater_introduction" in operators and context:
                    add(rule, "defeater_introduction", source(text, rule) + f" unless {context}",
                        f"Give {other.name} priority in its contextual condition.")
                if "rule_merging" in operators and rule.trigger.event.name == other.trigger.event.name and context and not rule.condition:
                    if not rule.response.defeater and not other.response.defeater:
                        add(rule, "rule_merging", source(text, rule) + f" unless {context} then {{" + source(text, other.response) + "}",
                            "Merge the default and contextual responses into one rule.")
                        patches[-1]['removed_rule_ids'] = [other.name]
                        patches[-1]['original_rule'] += "\n" + source(text, other)
                if "defeater_introduction" in operators:
                    for defeater in rule.response.defeater:
                        if defeater.response is None:
                            continue
                        alt = defeater.response.occ
                        if alt.event.event.name != other.response.occ.event.event.name or alt.neg == other.response.occ.neg:
                            continue
                        if context:
                            replacement = conjunction(source(text, defeater.expr), negation(context))
                        elif (other.response.defeater
                              and rule.trigger.event.name == other.trigger.event.name
                              and not alt.limit and not alt.inf
                              and not other.response.occ.limit and not other.response.occ.inf):
                            # Only let this exception apply where the competing
                            # rule has an explicit exception of its own.
                            replacement = conjunction(source(text, defeater.expr), source(text, other.response.defeater[0].expr))
                        else:
                            continue
                        add(rule, "defeater_introduction", edit_inside(text, rule, defeater.expr, replacement),
                            f"Narrow this conflicting exception using {other.name}'s declared context; preserve all other clauses.")
    # Several proof paths can lead to the same proposed text.
    unique = {}
    for patch in patches:
        unique.setdefault((patch["operation"], patch["target_rule_id"], patch["proposed_rule"]), patch)
    return list(unique.values())
