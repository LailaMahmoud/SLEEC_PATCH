"""Tests for the shared Boolean simplification step.

The simplifier runs after deterministic repair generation and before
verification/ranking.
"""

from services.boolean_simplifier import (
    simplify_expression,
    simplify_patch,
    simplify_rule,
)


def test_double_negation_is_removed():
    assert simplify_expression("not (not {humanAssents})") == "{humanAssents}"


def test_and_true_simplifies_to_operand():
    assert simplify_expression("({humanAssents} and true)") == "{humanAssents}"


def test_or_false_simplifies_to_operand():
    assert simplify_expression("({humanAssents} or false)") == "{humanAssents}"


def test_duplicate_and_operand_is_removed():
    assert (
        simplify_expression("({humanAssents} and {humanAssents})")
        == "{humanAssents}"
    )


def test_duplicate_or_operand_is_removed():
    assert (
        simplify_expression("({humanAssents} or {humanAssents})")
        == "{humanAssents}"
    )


def test_simplification_is_recursive():
    assert (
        simplify_expression("(({humanAssents} and {humanAssents}) or false)")
        == "{humanAssents}"
    )


def test_rule_simplifies_trigger_and_defeater():
    rule = (
        "r1 when Start and (not (not {humanAssents})) "
        "then Act unless ({emergency} and true)"
    )

    simplified = simplify_rule(rule)

    assert "when Start and {humanAssents} then Act" in simplified
    assert "unless {emergency}" in simplified
    assert "not (not {humanAssents})" not in simplified
    assert "({emergency} and true)" not in simplified


def test_complete_patch_uses_shared_simplifier():
    patch = {
        "patch_id": "d1",
        "operation": "trigger_refinement",
        "proposed_rule": (
            "r1 when Start and (not (not {humanAssents})) "
            "then Act unless ({emergency} and true)"
        ),
    }

    simplified = simplify_patch(patch)

    assert (
        "when Start and {humanAssents} then Act unless {emergency}"
        in simplified["proposed_rule"]
    )

    # simplify_patch must not mutate the original candidate.
    assert "not (not {humanAssents})" in patch["proposed_rule"]
