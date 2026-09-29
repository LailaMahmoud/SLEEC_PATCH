"""Conservative repairs selected from source references and observed traces."""
import copy
import re

from services.rule_model import (parse_sleec_ast, source, expression_value,
                                 edit_inside, with_guard, conjunction, negation, compact)
from services.repair_operator_selector import RepairOperatorSelector


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
    reported = diagnosis.get("affected_rule_ids", [])
    if reported:
        ids = [node.name for node in rules if node.name in reported]
        if len(ids) != len(set(reported)):
            return {"rule_ids": [], "basis": "unresolved", "addition_scope": None, "reason": "A reported rule is absent from the current specification."}
        if issue_type == "redundancies":
            ids = [diagnosis["source_id"]] if diagnosis.get("source_id") in ids else []
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
        if contexts and all(expression_value(rule.condition, item["values"]) is False for item in contexts):
            continue
        candidates.append(rule.name)
    if len(candidates) != 1:
        return {**common, "rule_ids": [], "candidate_rule_ids": candidates,
                "related_responses": related, "basis": "unresolved",
                "reason": "The source and witness do not identify a unique repair target."}
    return {**common, "rule_ids": candidates, "related_responses": related,
            "basis": "source_and_trace" if contexts else "source_match",
            "observed_contexts": contexts,
            "reason": "One rule matches the source trigger and response and is not excluded by the observed measure values. This is a repair hypothesis, not a causal proof."}


def next_id(base, used):
    index = 1
    while f"{base}_{index}" in used:
        index += 1
    result = f"{base}_{index}"
    used.add(result)
    return result


def generate_repairs(text, issue_type, diagnosis, operators):
    allowed = {op for ops in RepairOperatorSelector.BASE_DETERMINISTIC_OPERATORS.values() for op in ops}
    if set(operators) - allowed:
        raise ValueError("The deterministic generator accepts only the paper's deterministic operators.")
    model = parse_sleec_ast(text)
    resolution = target_resolution(text, issue_type, diagnosis)
    targets = [node for node in model.ruleBlock.rules if node.name in resolution["rule_ids"]]
    used = {node.name for node in model.ruleBlock.rules} | {node.name for node in model.definitions}
    used.update(label.name for node in model.definitions if type(node).__name__ == "ScalarMeasure"
                for label in node.type.scaleParams)
    for block_name, items_name in (("concernBlock", "concerns"), ("purposeBlock", "purposes")):
        block = getattr(model, block_name, None)
        used.update(node.name for node in getattr(block, items_name, []))
    patches = []

    def add(rule, operation, proposed, explanation):
        if compact(proposed) == compact(source(text, rule)):
            return
        patch_id = f"d_{operation}_{rule.name}_{len(patches) + 1}"
        patches.append({"patch_id": patch_id, "id": patch_id, "source": "deterministic",
                        "issue_type": issue_type, "operation": operation, "target_rule_id": rule.name,
                        "original_rule": source(text, rule), "proposed_rule": proposed,
                        "diagnosis": copy.deepcopy(diagnosis), "target_resolution": copy.deepcopy(resolution),
                        "natural_language_explanation": explanation})

    if issue_type == "redundancies" and "rule_removal" in operators:
        for rule in targets:
            add(rule, "rule_removal", "", "Remove only the redundant target; retain its supporting rules.")
        return patches

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
                if "purpose_defeater" in operators and guard:
                    add(rule, "purpose_defeater", source(text, rule) + f" unless {guard}",
                        "Relax this blocking rule only in the purpose context; preserve its existing responses and exceptions.")
                continue
            if rule.response.occ.event.event.name != occ.event.event.name:
                continue
            desired = source(text, occ)
            desired = re.sub(r"^not\s+", "", desired) if occ.neg else "not " + desired
            # Retiming an existing obligation keeps its polarity. Reversing a
            # prohibition can remove a protection (e.g. consent). New-rule
            # proposals belong to the LLM stage, not this generator.
            if (rule.response.occ.neg != occ.neg
                    and set(operators) & {"trigger_strengthening", "rule_decomposition"}):
                # Retain all response alternatives and defeaters, changing only
                # the implicated main occurrence. Unaffected contexts keep the
                # entire original response, including its original deadline.
                changed_body = (desired + text[rule.response.occ._tx_position_end:rule.response._tx_position_end])
                old_guard = source(text, rule.condition)
                if not guard or compact(guard) == compact(old_guard):
                    proposed = edit_inside(text, rule, rule.response.occ, desired)
                    operation = "trigger_strengthening"
                else:
                    proposed = (with_guard(text, rule, conjunction(old_guard, guard), response=changed_body)
                                + "\n" + with_guard(text, rule, conjunction(old_guard, negation(guard)), next_id(rule.name, used)))
                    operation = "rule_decomposition"
                add(rule, operation, proposed, "Enforce the opposite of the concern within its declared deadline. Preserve the original response outside its context and retain all exceptions.")
            if "defeater_introduction" in operators:
                for defeater in rule.response.defeater:
                    if (defeater.response is None or defeater.response.occ.event.event.name != occ.event.event.name
                            or defeater.response.occ.neg != occ.neg):
                        continue
                    replacement = conjunction(source(text, defeater.expr), negation(guard))
                    add(rule, "defeater_introduction", edit_inside(text, rule, defeater.expr, replacement),
                        "Exclude the concern context from this implicated exception; preserve the other exceptions and their order.")
        return patches

    if issue_type in {"conflicts", "situational_conflicts"}:
        for rule in targets:
            for other in targets:
                if other is rule:
                    continue
                # These proposals explicitly choose which obligation takes
                # priority. Stakeholder review remains separate from proof.
                context = source(text, other.condition)
                if "trigger_refinement" in operators and context:
                    add(rule, "trigger_refinement",
                        with_guard(text, rule, conjunction(source(text, rule.condition), negation(context))),
                        f"Give {other.name} priority in its measure context. Retain this rule's complete response and exceptions; review the priority choice.")
                if "defeater_introduction" in operators:
                    for defeater in rule.response.defeater:
                        if defeater.response is None:
                            continue
                        alt = defeater.response.occ
                        if alt.event.event.name != other.response.occ.event.event.name or alt.neg == other.response.occ.neg:
                            continue
                        if context:
                            replacement = conjunction(source(text, defeater.expr), negation(context))
                        elif other.response.defeater:
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
        unique.setdefault((patch["target_rule_id"], patch["proposed_rule"]), patch)
    return list(unique.values())
