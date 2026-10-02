"""Tests for common AST-based Boolean simplification.

The simplifier is intended to run after deterministic repair generation and
before formal verification and quantitative patch ranking.
"""

from sleec.sleecParser import parse_sleec_ast
from services.boolean_simplifier import simplify_boolean_ast


def parse_condition(expression):
    """Parse a Boolean expression in a minimal valid SLEEC specification."""
    sleec_text = f"""
def_start
event Start
event Act
measure humanAssents: boolean
def_end

rule_start
r1 when Start and {expression} then Act
rule_end
"""

    model = parse_sleec_ast(sleec_text)
    return model.ruleBlock.rules[0].condition


def test_conflict_trigger_refinement_simplifies_double_negation():
    """
    Conflict/SC trigger-refinement regression.

    Conceptual generated expression:
        not (not humanAssents)

    Grammar-valid generated SLEEC:
        (not (not {{humanAssents}}))

    Expected simplified expression:
        {{humanAssents}}
    """
    condition = parse_condition("(not (not {humanAssents}))")

    assert type(condition).__name__ == "Negation"
    assert type(condition.expr).__name__ == "Negation"

    simplified = simplify_boolean_ast(condition)

    assert simplified == "{humanAssents}"


def test_and_true_simplifies_to_operand():
    condition = parse_condition("({humanAssents} and true)")

    assert simplify_boolean_ast(condition) == "{humanAssents}"


def test_or_false_simplifies_to_operand():
    condition = parse_condition("({humanAssents} or false)")

    assert simplify_boolean_ast(condition) == "{humanAssents}"


def test_duplicate_and_operand_is_removed():
    condition = parse_condition(
        "({humanAssents} and {humanAssents})"
    )

    assert simplify_boolean_ast(condition) == "{humanAssents}"


def test_duplicate_or_operand_is_removed():
    condition = parse_condition(
        "({humanAssents} or {humanAssents})"
    )

    assert simplify_boolean_ast(condition) == "{humanAssents}"


def test_complete_candidate_simplifies_guard_and_defeater_and_reparses():
    from sleec.sleecParser import parse_sleec_ast
    from services.boolean_simplifier import simplify_sleec_booleans

    candidate = """
def_start
event Start
event Act
measure humanAssents: boolean
measure emergency: boolean
def_end

rule_start
r1 when Start and (not (not {humanAssents})) then Act unless ({emergency} and true)
rule_end
"""

    simplified = simplify_sleec_booleans(candidate)

    assert "r1 when Start and {humanAssents} then Act unless {emergency}" in simplified
    assert "(not (not {humanAssents}))" not in simplified
    assert "({emergency} and true)" not in simplified

    # The re-serialized result must still be valid SLEEC.
    parse_sleec_ast(simplified)
