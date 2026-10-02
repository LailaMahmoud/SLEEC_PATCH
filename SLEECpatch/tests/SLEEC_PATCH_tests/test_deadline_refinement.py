"""
Unit tests for the Deadline Refinement deterministic repair operator.

Deadline Refinement applies to concerns when an existing SLEEC rule
contains a numeric temporal deadline and the diagnosed concern requires
the same response, with the same polarity, under a strictly tighter
deadline.

Applicability conditions:
1. The existing rule has an explicit numeric deadline.
2. The diagnosis has an explicit numeric deadline.
3. Both refer to the same response.
4. Response polarity is preserved.
5. The diagnosed deadline is strictly tighter than the existing deadline.

Formally:

    t_diagnosed < t_existing

Deadline Refinement must not:
- introduce a deadline when the original rule has none;
- relax an existing deadline;
- generate a no-op for equal deadlines;
- modify an unrelated response;
- change response polarity.

Example:

    Original:
        r10 when SmokeDetectorAlarm
            then CallEmergencyServices within 5 minutes

    Diagnosis:
        c1 when SmokeDetectorAlarm
            then CallEmergencyServices within 3 minutes

    Expected repair:
        r10 when SmokeDetectorAlarm
            then CallEmergencyServices within 3 minutes

Only the temporal bound changes:
    5 minutes -> 3 minutes
"""
from services.repair_operator_selector import RepairOperatorSelector
from services.deterministic_repair_engine import DeterministicRepairEngine


def make_rule(
    action,
    condition="SmokeDetectorAlarm",
    defeater="",
):
    return {
        "id": "r10",
        "condition": condition,
        "action": action,
        "defeater": defeater,
    }


# ============================================================
# Applicability tests
# ============================================================

def test_deadline_refinement_tighter_deadline_is_applicable():
    selector = RepairOperatorSelector()

    rule = make_rule("CallEmergencyServices within 5 minutes")
    diagnosis = (
        "c1 when SmokeDetectorAlarm "
        "then CallEmergencyServices within 3 minutes"
    )

    context = selector.find_deadline_refinement_context(
        issue_rules=[rule],
        selected_issue=diagnosis,
    )

    assert context is not None
    assert context["target_rule"]["id"] == "r10"


def test_deadline_refinement_weaker_deadline_is_not_applicable():
    selector = RepairOperatorSelector()

    rule = make_rule("CallEmergencyServices within 3 minutes")
    diagnosis = (
        "c1 when SmokeDetectorAlarm "
        "then CallEmergencyServices within 5 minutes"
    )

    context = selector.find_deadline_refinement_context(
        issue_rules=[rule],
        selected_issue=diagnosis,
    )

    assert context is None


def test_deadline_refinement_equal_deadline_is_not_applicable():
    selector = RepairOperatorSelector()

    rule = make_rule("CallEmergencyServices within 3 minutes")
    diagnosis = (
        "c1 when SmokeDetectorAlarm "
        "then CallEmergencyServices within 3 minutes"
    )

    context = selector.find_deadline_refinement_context(
        issue_rules=[rule],
        selected_issue=diagnosis,
    )

    assert context is None


def test_deadline_refinement_compares_different_time_units():
    selector = RepairOperatorSelector()

    rule = make_rule("CallEmergencyServices within 90 seconds")
    diagnosis = (
        "c1 when SmokeDetectorAlarm "
        "then CallEmergencyServices within 1 minute"
    )

    context = selector.find_deadline_refinement_context(
        issue_rules=[rule],
        selected_issue=diagnosis,
    )

    assert context is not None


def test_deadline_refinement_requires_existing_deadline():
    selector = RepairOperatorSelector()

    rule = make_rule("CallEmergencyServices")
    diagnosis = (
        "c1 when SmokeDetectorAlarm "
        "then CallEmergencyServices within 3 minutes"
    )

    context = selector.find_deadline_refinement_context(
        issue_rules=[rule],
        selected_issue=diagnosis,
    )

    assert context is None


def test_deadline_refinement_requires_same_response():
    selector = RepairOperatorSelector()

    rule = make_rule("NotifyCaregiver within 5 minutes")
    diagnosis = (
        "c1 when SmokeDetectorAlarm "
        "then CallEmergencyServices within 3 minutes"
    )

    context = selector.find_deadline_refinement_context(
        issue_rules=[rule],
        selected_issue=diagnosis,
    )

    assert context is None


def test_deadline_refinement_preserves_response_polarity():
    selector = RepairOperatorSelector()

    rule = make_rule("not CallEmergencyServices within 5 minutes")
    diagnosis = (
        "c1 when SmokeDetectorAlarm "
        "then CallEmergencyServices within 3 minutes"
    )

    context = selector.find_deadline_refinement_context(
        issue_rules=[rule],
        selected_issue=diagnosis,
    )

    assert context is None


# ============================================================
# Generated-patch tests
# ============================================================

def test_deadline_refinement_generates_expected_patch():
    engine = DeterministicRepairEngine()

    rule = make_rule(
        "CallEmergencyServices within 5 minutes",
        defeater="userOverrides",
    )

    diagnosis = (
        "c1 when SmokeDetectorAlarm "
        "then CallEmergencyServices within 3 minutes"
    )

    patch = engine.generate_deadline_refinement_patch(
        selected_issue=diagnosis,
        rules=[rule],
    )

    assert patch is not None
    assert patch["operation"] == "deadline_refinement"
    assert patch["issue_type"] == "concerns"
    assert patch["target_rule_id"] == "r10"

    assert patch["old_deadline"] == "within 5 minutes"
    assert patch["new_deadline"] == "within 3 minutes"

    proposed = patch["proposed_rule"]

    assert "when SmokeDetectorAlarm" in proposed
    assert "then CallEmergencyServices within 3 minutes" in proposed
    assert "unless {userOverrides}" in proposed

    assert "within 5 minutes" not in proposed


def test_deadline_refinement_does_not_generate_weaker_patch():
    engine = DeterministicRepairEngine()

    rule = make_rule("CallEmergencyServices within 3 minutes")
    diagnosis = (
        "c1 when SmokeDetectorAlarm "
        "then CallEmergencyServices within 5 minutes"
    )

    patch = engine.generate_deadline_refinement_patch(
        selected_issue=diagnosis,
        rules=[rule],
    )

    assert patch is None


def test_deadline_refinement_does_not_generate_for_opposite_polarity():
    engine = DeterministicRepairEngine()

    rule = make_rule(
        "not CallEmergencyServices within 5 minutes"
    )

    diagnosis = (
        "c1 when SmokeDetectorAlarm "
        "then CallEmergencyServices within 3 minutes"
    )

    patch = engine.generate_deadline_refinement_patch(
        selected_issue=diagnosis,
        rules=[rule],
    )

    assert patch is None


# ============================================================
# Paper example
# ============================================================

def test_deadline_refinement_paper_example():
    """Reproduce the Deadline Refinement example used in the paper."""
    engine = DeterministicRepairEngine()

    # Paper input:
    # r10: when SmokeDetectorAlarm
    #      then CallEmergencyServices within 5 minutes
    rule = {
        "id": "r10",
        "condition": "SmokeDetectorAlarm",
        "action": "CallEmergencyServices within 5 minutes",
        "defeater": "",
    }

    # Paper concern:
    # emergency services must not remain uncalled for 3 minutes
    # after the smoke alarm.
    diagnosis = (
        "c1 when SmokeDetectorAlarm "
        "then CallEmergencyServices within 3 minutes"
    )

    patch = engine.generate_deadline_refinement_patch(
        selected_issue=diagnosis,
        rules=[rule],
    )

    assert patch is not None
    assert patch["operation"] == "deadline_refinement"
    assert patch["target_rule_id"] == "r10"

    # The paper repair tightens 5 minutes -> 3 minutes.
    assert patch["old_deadline"] == "within 5 minutes"
    assert patch["new_deadline"] == "within 3 minutes"

    # Trigger and response are preserved; only deadline changes.
    assert patch["proposed_rule"] == (
        "r10 when SmokeDetectorAlarm "
        "then CallEmergencyServices within 3 minutes"
    )
