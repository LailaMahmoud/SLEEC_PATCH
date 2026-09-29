"""Parser-backed source edits. Unchanged spans are copied verbatim."""
import re

from sleec.sleecParser import parse_sleec_ast
from services.candidate_status import method_error


def source(text, node):
    return text[node._tx_position:node._tx_position_end] if node is not None else ""


def rules_from_text(text):
    model = parse_sleec_ast(text)
    ids = [node.name for node in model.ruleBlock.rules]
    if len(set(ids)) != len(ids):
        raise ValueError("Rule IDs must be unique.")
    return [rule_record(text, node) for node in model.ruleBlock.rules]


def rule_record(text, node):
    response = node.response
    defeaters = response.defeater
    body = source(text, response)
    main_end = defeaters[0]._tx_position if defeaters else response._tx_position_end
    guard = source(text, node.condition)
    trigger = node.trigger.event.name
    return {
        "id": node.name, "raw": source(text, node),
        "condition": trigger + (" and " + guard if guard else ""),
        "trigger": trigger, "guard": guard,
        "action": text[response._tx_position:main_end].rstrip(),
        "response": body,
        "defeater": text[defeaters[0]._tx_position:response._tx_position_end][len("unless"):].strip() if defeaters else "",
        "response_event": response.occ.event.event.name,
        "response_negative": response.occ.neg,
        "start": node._tx_position, "end": node._tx_position_end,
    }


def replace_span(text, node, replacement):
    return text[:node._tx_position] + replacement + text[node._tx_position_end:]


def edit_inside(text, rule, part, replacement):
    return (text[rule._tx_position:part._tx_position] + replacement
            + text[part._tx_position_end:rule._tx_position_end])


def with_guard(text, rule, guard, rule_id=None, response=None):
    # Guard syntax is taken from the AST or built from complete Boolean terms.
    trigger = rule.trigger.event.name
    return (f"{rule_id or rule.name} when {trigger}"
            + (f" and {guard}" if guard else "")
            + " then " + (source(text, rule.response) if response is None else response))


def conjunction(left, right):
    if not left:
        return right
    if not right or compact(left) == compact(right):
        return left
    return f"({left} and {right})"


def negation(term):
    return f"(not {term})" if term else "false"


def compact(text):
    return re.sub(r"\s+", " ", text).strip()


def expression_value(node, values):
    """Evaluate only grammar expressions at an observed measure snapshot.

    None means unknown. No missing measure is silently treated as false.
    Scale comparisons use their declared order, not alphabetical order.
    """
    if node is None:
        return True
    kind = type(node).__name__
    if kind == "Negation":
        value = expression_value(node.expr, values)
        return None if value is None else not value
    if hasattr(node, "op"):
        left, right = expression_value(node.lhs, values), expression_value(node.rhs, values)
        if node.op == "and":
            if left is False or right is False:
                return False
        if node.op == "or":
            if left is True or right is True:
                return True
        if left is None or right is None:
            return None
        if kind == "ScalarBinaryOp" or any(type(getattr(part, "ID", None)).__name__ == "ScalarMeasure" for part in (node.lhs, node.rhs)):
            measure = getattr(node.lhs, "ID", None) or getattr(node.rhs, "ID", None)
            if measure is None:
                # Both are literals; resolve the scale through their parent.
                literal = getattr(node.lhs, "value", None)
                scale = getattr(literal, "parent", None)
            else:
                scale = measure.type
            names = [p.name for p in getattr(scale, "scaleParams", [])]
            if left not in names or right not in names:
                return None
            left, right = names.index(left), names.index(right)
        operations = {"and": lambda: left and right, "or": lambda: left or right,
                      "=": lambda: left == right, "<>": lambda: left != right,
                      "<": lambda: left < right, ">": lambda: left > right,
                      "<=": lambda: left <= right, ">=": lambda: left >= right,
                      "+": lambda: left + right, "-": lambda: left - right, "*": lambda: left * right}
        try:
            return operations[node.op]()
        except (KeyError, TypeError):
            return None
    if kind == "BoolTerminal":
        if node.ID is not None:
            return values.get(node.ID.name)
        return node.value == "true"
    if kind == "ScalarTerminal":
        return values.get(node.ID.name) if node.ID is not None else node.value.name
    if kind == "NumTerminal":
        if node.ID is not None:
            if type(node.ID).__name__ == "ScaleParam":
                return node.ID.name
            return expression_value(node.ID.value, values) if type(node.ID).__name__ == "Constant" else values.get(node.ID.name)
        return expression_value(node.value, values)
    if kind == "Value":
        return expression_value(node.constant.value, values) if node.constant is not None else node.value
    return None


def apply_rule_patch(text, patch):
    """Replace only identified AST spans; never globally replace matching text."""
    error = method_error(patch)
    if error:
        raise ValueError(error)
    model = parse_sleec_ast(text)
    operation = patch.get("operation", "")
    target_id = patch.get("target_rule_id")
    nodes = {node.name: node for node in model.ruleBlock.rules}
    if len(nodes) != len(model.ruleBlock.rules):
        raise ValueError("Rule IDs must be unique before applying a repair.")
    if operation in {"add", "add_rule", "new_rule_generation"}:
        replacement = patch.get("new_rule") or patch.get("proposed_rule", "")
        position = model.ruleBlock.rules[-1]._tx_position_end
        return text[:position] + "\n" + replacement + text[position:]
    if target_id not in nodes:
        raise ValueError(f"Repair target {target_id!r} is not a rule in this specification.")
    if operation in {"delete", "delete_rule", "delete_redundant_rule", "rule_removal"}:
        # A redundancy proof may mention supporting rules. Only remove the
        # diagnosed redundant target, never all IDs appearing in its proof.
        replacement = ""
    else:
        replacement = patch.get("proposed_rule", "")
        if not replacement:
            raise ValueError("A replacement rule cannot be empty.")
    result = replace_span(text, nodes[target_id], replacement)
    declaration = patch.get("declaration_text", "")
    if declaration:
        position = model.definitions[-1]._tx_position_end
        result = result[:position] + "\n" + declaration + result[position:]
    return result


def preserved_requirements(original, updated):
    """A repair cannot pass by deleting the question posed to the checker."""
    before, after = parse_sleec_ast(original), parse_sleec_ast(updated)
    for block in ("concernBlock", "purposeBlock", "relBlock"):
        if source(original, getattr(before, block, None)) != source(updated, getattr(after, block, None)):
            raise ValueError("A repair cannot change concerns, purposes or relations used for verification.")
    definitions = {node.name: source(updated, node) for node in after.definitions}
    for node in before.definitions:
        if definitions.get(node.name) != source(original, node):
            raise ValueError("A repair cannot delete or redefine existing vocabulary.")
