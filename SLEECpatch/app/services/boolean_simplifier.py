"""Common Boolean simplification for generated SLEEC patches.

The simplifier works from parsed SLEEC Boolean AST nodes and serializes the
simplified result back to grammar-valid SLEEC. It is intended to run after a
deterministic repair transformation and before verification and ranking.
"""


def _kind(node):
    """Return the textX grammar-class name for a parsed AST node."""
    return type(node).__name__ if node is not None else ""


def _serialize_terminal(node):
    """Serialize an atomic Boolean terminal."""
    value = getattr(node, "value", None)

    if value is not None and str(value) != "":
        return str(value).lower()

    measure = getattr(node, "ID", None)
    if measure is not None:
        name = getattr(measure, "name", None)
        if name:
            return f"{{{name}}}"

    return ""


def _serialize_non_boolean_binary(node):
    """Serialize scalar/numerical expressions without changing their meaning."""
    lhs = _serialize_expression(getattr(node, "lhs", None))
    rhs = _serialize_expression(getattr(node, "rhs", None))
    op = str(getattr(node, "op", "") or "").strip()

    if lhs and rhs and op:
        return f"({lhs} {op} {rhs})"

    return ""


def _serialize_expression(node):
    """Recursively simplify and serialize a parsed SLEEC expression."""
    if node is None:
        return ""

    kind = _kind(node)

    if kind == "BoolTerminal":
        return _serialize_terminal(node)

    if kind == "Negation":
        child = getattr(node, "expr", None)

        # not (not X) -> X
        if _kind(child) == "Negation":
            return _serialize_expression(getattr(child, "expr", None))

        rendered = _serialize_expression(child)
        return f"(not {rendered})" if rendered else ""

    if kind == "BoolBinaryOp":
        lhs = _serialize_expression(getattr(node, "lhs", None))
        rhs = _serialize_expression(getattr(node, "rhs", None))
        op = str(getattr(node, "op", "") or "").lower()

        # X and true -> X
        if op == "and":
            if lhs.lower() == "true":
                return rhs
            if rhs.lower() == "true":
                return lhs

            # X and X -> X
            if lhs == rhs:
                return lhs

        # X or false -> X
        if op == "or":
            if lhs.lower() == "false":
                return rhs
            if rhs.lower() == "false":
                return lhs

            # X or X -> X
            if lhs == rhs:
                return lhs

        if lhs and rhs and op:
            return f"({lhs} {op} {rhs})"

        return lhs or rhs

    # ScalarBinaryOp and NumericalOp are valid Boolean expressions but are
    # not simplified by the Boolean identities above.
    if kind in {"ScalarBinaryOp", "NumericalOp", "NumBinOp"}:
        return _serialize_non_boolean_binary(node)

    # Numerical/scalar terminals may occur inside comparisons.
    value = getattr(node, "value", None)
    if value is not None and str(value) != "":
        name = getattr(value, "name", None)
        return str(name if name is not None else value)

    ref = getattr(node, "ID", None)
    if ref is not None:
        name = getattr(ref, "name", None)
        if name:
            return f"{{{name}}}"

    return ""


def simplify_boolean_ast(node):
    """Return a simplified, grammar-valid SLEEC expression for an AST node.

    Supported Boolean identities:
        not (not X) -> X
        X and true  -> X
        X or false  -> X
        X and X     -> X
        X or X      -> X

    ``not not X`` is the same double-negation AST case once parsed as valid
    SLEEC syntax.
    """
    return _serialize_expression(node)


def simplify_sleec_booleans(sleec_text):
    """Simplify Boolean expressions in a complete SLEEC specification.

    This common post-transformation step simplifies:
      - rule guard conditions; and
      - top-level defeater conditions.

    Replacements use parsed AST source spans and are applied from right to
    left so textX positions remain valid. The resulting specification is
    reparsed before being returned.
    """
    from sleec.sleecParser import parse_sleec_ast

    model = parse_sleec_ast(sleec_text)
    replacements = []

    def collect(node):
        if node is None:
            return

        original = sleec_text[
            node._tx_position:node._tx_position_end
        ]
        simplified = simplify_boolean_ast(node)

        if simplified and simplified != original:
            replacements.append(
                (
                    node._tx_position,
                    node._tx_position_end,
                    simplified,
                )
            )

    for rule in model.ruleBlock.rules:
        # Main rule Boolean guard.
        collect(getattr(rule, "condition", None))

        # Top-level response defeaters:
        #     unless <MBoolExpr> [then <InnerResponse>]
        response = getattr(rule, "response", None)

        for defeater in getattr(response, "defeater", []) or []:
            collect(getattr(defeater, "expr", None))

    result = sleec_text

    for start, end, replacement in sorted(
        replacements,
        key=lambda item: item[0],
        reverse=True,
    ):
        result = result[:start] + replacement + result[end:]

    # The simplified candidate must remain grammar-valid SLEEC.
    parse_sleec_ast(result)

    return result

