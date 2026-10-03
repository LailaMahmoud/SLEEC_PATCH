"""Validate small LLM proposals and render their SLEEC in application code."""
import re

from services.rule_model import parse_sleec_ast, source, edit_inside, apply_rule_patch
from services.evidence_repair import concern_context, response_occurrences


IDENTIFIER = re.compile(r"[A-Za-z_]\w*\Z", re.ASCII)


def symbol(value):
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise ValueError("Every new name must be a single SLEEC identifier.")
    return value


def fields(value, required, optional=()):
    if not isinstance(value, dict) or not set(required).issubset(value) or set(value) - set(required) - set(optional):
        raise ValueError(f"Expected fields: {', '.join(required)}.")


def fresh_rule_id(declared_names):
    """Allocate a deterministic unused SLEEC rule identifier."""
    used = set(declared_names or [])
    index = 1
    while f"R{index}" in used:
        index += 1
    return f"R{index}"


def materialize_semantic_edit(text, proposal, allowed_rule_ids, addition_scope=None):
    fields(proposal, ("operation", "target_rule_id", "change", "natural_language_explanation"),
           ("patch_id", "id", "source", "issue_type", "diagnosis", "applicability", "source_requirement_id"))
    if not isinstance(proposal["natural_language_explanation"], str) or not proposal["natural_language_explanation"].strip():
        raise ValueError("Explain why the semantic change addresses the diagnosis.")
    model = parse_sleec_ast(text)
    rules = {node.name: node for node in model.ruleBlock.rules}
    target_id = proposal["target_rule_id"]
    change = proposal["change"]
    operation = proposal["operation"]
    source_id = proposal.get("source_requirement_id")
    scope = None
    if source_id:
        if (operation != "new_rule_generation" or target_id not in (None, "")
                or not addition_scope or source_id != addition_scope.get("source_id")):
            raise ValueError("A new rule must be anchored to the selected source concern, without an edited rule target.")
        scope = concern_context(text, model, "concerns", {"source_id": source_id})
        if scope is None:
            raise ValueError("This concern structure does not support a single additional obligation.")
        rule = None
    else:
        if target_id not in allowed_rule_ids or target_id not in rules:
            raise ValueError("The semantic proposal must target a rule identified for this finding.")
        rule = rules[target_id]
    definitions = {node.name: node for node in model.definitions}
    declared_names = set(definitions) | set(rules)
    declared_names.update(p.name for node in model.definitions if type(node).__name__ == "ScalarMeasure" for p in node.type.scaleParams)
    declaration = ""
    missing = ""
    if operation in {"event_specialization", "response_refinement", "measure_specialization"}:
        fields(change, ("from", "to", "meaning", "evidence"), ("scale_labels", "response_path", "element_path", "complementary_rule_id", "measure_type", "context"))
        old, new = (symbol(change["from"]) if change["from"] else ""), symbol(change["to"])
        for key in ("meaning", "evidence"):
            if not isinstance(change[key], str) or not change[key].strip():
                raise ValueError("Define the new concept and explain its connection to the evidence.")
        if new in declared_names:
            raise ValueError("A specialized concept must have a new, unused name.")
        missing = new
        if operation == "event_specialization":
            if old != rule.trigger.event.name:
                raise ValueError("Event specialization may change only the target rule's trigger event.")
            proposed = edit_inside(text, rule, rule.trigger, new)
            declaration = f"event {new}"
        elif operation == "response_refinement":
            paths = dict(response_occurrences(rule.response))
            occurrence = paths.get(change.get("response_path", "main"))
            if occurrence is None or old != occurrence.event.event.name:
                raise ValueError("Response refinement must identify the exact response path and existing event.")
            proposed = edit_inside(text, rule, occurrence.event, new)
            declaration = f"event {new}"
        else:
            from services.rule_model import with_guard, conjunction
            path = change.get("element_path", "trigger")
            if path == "trigger":
                element = rule.condition
            elif re.fullmatch(r"unless\[\d+\]", path):
                index = int(path[7:-1])
                if index >= len(rule.response.defeater):
                    raise ValueError("Unknown defeater path.")
                element = rule.response.defeater[index].expr
            else:
                raise ValueError("Measure specialization requires an exact condition path.")
            measure = definitions.get(old)
            if not old:
                if path != "trigger": raise ValueError("New contexts must target the trigger.")
                measure_type = change.get("measure_type", "boolean")
                if measure_type not in {"boolean", "numeric", "scale"}:
                    raise ValueError("Unsupported new measure type.")
                if measure_type == "scale":
                    labels = change.get("scale_labels")
                    if not isinstance(labels, list) or not labels:
                        raise ValueError("A new scale requires its ordered labels.")
                    labels = [symbol(label) for label in labels]
                    if len(set(labels)) != len(labels) or set(labels) & (declared_names | {new}):
                        raise ValueError("New scale labels must be unused and distinct.")
                    measure_type = "scale("+",".join(labels)+")"
                new_context = change.get("context", "{"+new+"}")
                if not isinstance(new_context, str) or not re.search(r"\{\s*"+re.escape(new)+r"\s*\}", new_context):
                    raise ValueError("The new context must reference the introduced measure.")
                proposed = with_guard(text, rule, conjunction(source(text, rule.condition), new_context))
                declaration = f"measure {new}:{measure_type}"
            else:
                if measure is None or type(measure).__name__ not in {"BoolMeasure", "NumMeasure", "ScalarMeasure"}:
                    raise ValueError("Measure specialization must name an existing measure.")
                pattern = r"\{\s*" + re.escape(old) + r"\s*\}"
                replacement, count = re.subn(pattern, "{" + new + "}", source(text, element))
                if not count:
                    raise ValueError("The measure is not used in the selected condition.")
                proposed = edit_inside(text, rule, element, replacement)
            if type(measure).__name__ == "ScalarMeasure":
                labels = change.get("scale_labels")
                old_labels = [item.name for item in measure.type.scaleParams]
                if not isinstance(labels, list) or len(labels) != len(old_labels):
                    raise ValueError("Provide one new scale label for each existing label, in the same order.")
                labels = [symbol(label) for label in labels]
                if len(set(labels)) != len(labels) or set(labels) & (declared_names | {new}):
                    raise ValueError("Specialized scale labels must be distinct, unused names.")
                mapping = dict(zip(old_labels, labels))
                replacement = re.sub(r"\b(?:" + "|".join(map(re.escape, old_labels)) + r")\b", lambda m: mapping[m.group(0)], replacement)
                proposed = edit_inside(text, rule, element, replacement)
                declaration = f"measure {new}:scale({','.join(labels)})"
            elif old:
                if "scale_labels" in change:
                    raise ValueError("Only scale measures can declare scale labels.")
                declaration = re.sub(r"^(measure\s+)" + re.escape(old) + r"\b", lambda m: m.group(1) + new, source(text, measure), count=1)
    elif operation == "new_rule_generation":
        fields(
            change,
            ("rule_id", "trigger_event", "condition",
             "response_event", "negated", "deadline"),
        )

        # GPT supplies semantic content. The application owns the final
        # identifier so a model-generated ID can never collide with the
        # current SLEEC namespace.
        requested_rule_id = symbol(change["rule_id"])
        new_id = fresh_rule_id(declared_names)

        trigger = symbol(change["trigger_event"])
        response = symbol(change["response_event"])

        for name in (trigger, response):
            if type(definitions.get(name)).__name__ != "Event":
                raise ValueError("A new rule must use declared events.")

        if (
            type(change["negated"]) is not bool
            or not isinstance(change["condition"], str)
        ):
            raise ValueError(
                "Expected a Boolean polarity and a condition expression."
            )

        condition = change["condition"].strip()

        # trigger_event is represented separately. The condition field is
        # only for SLEEC measure/context expressions.
        event_names = {
            name
            for name, node in definitions.items()
            if type(node).__name__ == "Event"
        }
        condition_identifiers = set(
            re.findall(r"(?<!\{)\b[A-Za-z_]\w*\b(?!\s*\})", condition)
        )
        condition_keywords = {"and", "or", "not", "true", "false"}
        event_leaks = (
            condition_identifiers - condition_keywords
        ) & event_names

        if event_leaks:
            raise ValueError(
                "A new-rule condition may contain only measure/context "
                "expressions; trigger/response events belong in their "
                "dedicated fields. Event(s) found in condition: "
                + ", ".join(sorted(event_leaks))
            )

        deadline = change["deadline"]
        suffix = ""

        if deadline == {"kind": "source"}:
            if scope is None:
                raise ValueError(
                    "Source timing requires the selected concern as an anchor."
                )
            suffix = " " + scope["timing"] if scope["timing"] else ""

        elif deadline == {"kind": "eventually"}:
            suffix = " eventually"

        elif deadline is not None:
            fields(deadline, ("value", "unit"))
            if (
                type(deadline["value"]) is not int
                or deadline["value"] < 0
                or deadline["unit"]
                not in {"seconds", "minutes", "hours", "days"}
            ):
                raise ValueError(
                    "The deadline must use a nonnegative integer "
                    "and a supported time unit."
                )
            suffix = (
                f" within {deadline['value']} {deadline['unit']}"
            )

        proposed = (
            f"{new_id} when {trigger}"
            + (f" and {condition}" if condition else "")
            + " then "
            + ("not " if change["negated"] else "")
            + response
            + suffix
        )

        # Keep the structured proposal unchanged. Semantic verification renders
        # it again against the original specification and must obtain the same
        # allocated ID without receiving extra fields in the change contract.
    else:
        raise ValueError("This is not a supported semantic edit operation.")

    additional_edits = {}
    counterpart = change.get("complementary_rule_id")
    if counterpart:
        if operation != "measure_specialization" or old or counterpart == target_id or counterpart not in allowed_rule_ids or counterpart not in rules:
            raise ValueError("A complementary partition requires a new context and another implicated rule.")
        other = rules[counterpart]
        additional_edits[counterpart] = with_guard(text, other, conjunction(source(text, other.condition), "(not "+new_context+")"))

    patch = {**proposal, "structured_edit_validated": True, "original_rule": "" if operation == "new_rule_generation" else source(text, rule), "proposed_rule": proposed,
             "missing_element": missing, "declaration_text": declaration,
             "source": "llm", "semantic_review_status": "pending", "additional_rule_edits": additional_edits, "original_sleec": text}
    patch["allowed_rule_ids"] = list(allowed_rule_ids)
    patch["addition_scope"] = addition_scope
    if operation == "new_rule_generation":
        patch["requested_rule_id"] = requested_rule_id
        patch["assigned_rule_id"] = new_id
    updated = apply_rule_patch(text, patch)
    try:
        parsed = parse_sleec_ast(updated)
    except Exception as exc:
        raise ValueError(f"The structured edit does not produce valid SLEEC: {exc}") from exc
    after = {node.name: source(updated, node) for node in parsed.ruleBlock.rules}
    expected_ids = set(rules)
    if operation == "new_rule_generation":
        expected_ids.add(new_id)
    if set(after) != expected_ids or len(after) != len(parsed.ruleBlock.rules):
        raise ValueError("The proposal changed the rule structure beyond its declared edit.")
    for name, node in rules.items():
        if (name != target_id and name not in additional_edits) or operation == "new_rule_generation":
            if after.get(name) != source(text, node):
                raise ValueError("The proposal changed an unrelated rule.")
    # Reject injected concern/purpose/relation edits in the condition field.
    for block in ("concernBlock", "purposeBlock", "relBlock"):
        if source(text, getattr(model, block, None)) != source(updated, getattr(parsed, block, None)):
            raise ValueError("A semantic rule proposal cannot change the verification requirements.")
    after_definitions = {node.name: source(updated, node) for node in parsed.definitions}
    expected_definitions = {node.name: source(text, node) for node in model.definitions}
    if declaration:
        expected_definitions[missing] = declaration
    if after_definitions != expected_definitions or len(after_definitions) != len(parsed.definitions):
        raise ValueError("The proposal changed declarations beyond its specified new concept.")
    return patch
