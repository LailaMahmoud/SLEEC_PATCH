from services.deterministic_repair_engine import DeterministicRepairEngine


def make_engine():
    return DeterministicRepairEngine()


# ---------------------------------------------------------------------------
# trigger_strengthening
# ---------------------------------------------------------------------------

def test_trigger_strengthening_paper_example():
    """
    Paper example:

    SmokeDetectorAlarm and not userPresent

    is broadened using the concern context:

    not userDisablesAlarm

    so that the repaired trigger has the semantics:

    (SmokeDetectorAlarm and not userPresent) or not userDisablesAlarm
    """
    engine = make_engine()

    rule = {
        "id": "r7",
        "condition": "SmokeDetectorAlarm and not userPresent",
        "action": "CallEmergencyServices within 1 minute",
        "defeater": "",
    }

    result = engine.strengthen_concern_trigger(
        rule,
        "not userDisablesAlarm",
    )

    assert result != engine.rule_raw(rule)

    # Existing trigger remains grouped before OR broadening.
    assert "SmokeDetectorAlarm" in result
    assert "not userPresent" in result
    assert " or " in result
    assert "not userDisablesAlarm" in result

    # Untargeted response and deadline are preserved.
    assert "then CallEmergencyServices within 1 minute" in result


def test_trigger_strengthening_rejects_duplicate_context():
    engine = make_engine()

    rule = {
        "id": "r7",
        "condition": "SmokeDetectorAlarm and not userPresent",
        "action": "CallEmergencyServices within 1 minute",
        "defeater": "",
    }

    result = engine.strengthen_concern_trigger(
        rule,
        "not userPresent",
    )

    assert result == engine.rule_raw(rule)


# ---------------------------------------------------------------------------
# rule_decomposition
# ---------------------------------------------------------------------------

def test_rule_decomposition_paper_example():
    """
    Paper decomposition:

        T and C     -> repaired response
        T and not C -> original response

    Both rules must be returned as one candidate patch.
    """
    engine = make_engine()

    rule = {
        "id": "r9",
        "condition": "SmokeDetectorAlarm and userPresent",
        "action": "not CallEmergencyServices within 3 minutes",
        "defeater": "",
    }

    result = engine.decompose_rule_for_concern(
        rule=rule,
        context="not userDisablesAlarm",
        desired_action="CallEmergencyServices within 1 minute",
        used_rule_ids=set(),
    )

    assert result is not None

    branches = result.splitlines()

    # One candidate contains exactly two generated rules.
    assert len(branches) == 2

    repaired_branch, complementary_branch = branches

    # T is preserved in both branches.
    assert "SmokeDetectorAlarm" in repaired_branch
    assert "userPresent" in repaired_branch
    assert "SmokeDetectorAlarm" in complementary_branch
    assert "userPresent" in complementary_branch

    # First branch uses C and the repaired response.
    assert "not userDisablesAlarm" in repaired_branch
    assert (
        "then CallEmergencyServices within 1 minute"
        in repaired_branch
    )

    # Second branch uses complement(C).
    assert "userDisablesAlarm" in complementary_branch
    assert "not userDisablesAlarm" not in complementary_branch

    # Complementary branch preserves the original response and deadline.
    assert (
        "then not CallEmergencyServices within 3 minutes"
        in complementary_branch
    )


def test_rule_decomposition_branches_use_complementary_contexts():
    engine = make_engine()

    rule = {
        "id": "r9",
        "condition": "SmokeDetectorAlarm and userPresent",
        "action": "not CallEmergencyServices within 3 minutes",
        "defeater": "",
    }

    context = "not userDisablesAlarm"

    result = engine.decompose_rule_for_concern(
        rule=rule,
        context=context,
        desired_action="CallEmergencyServices within 1 minute",
        used_rule_ids=set(),
    )

    assert result is not None

    branches = result.splitlines()
    assert len(branches) == 2

    first = engine.parse_when_then(branches[0])
    second = engine.parse_when_then(branches[1])

    # C appears only in the repaired branch.
    assert "not userDisablesAlarm" in first["condition"]

    # not(C) appears only in the complementary branch.
    complement = engine.negate_boolean_expression(context)
    assert complement
    assert complement in second["condition"]
    assert "not userDisablesAlarm" not in second["condition"]


def test_rule_decomposition_preserves_original_deadline_in_complementary_branch():
    engine = make_engine()

    rule = {
        "id": "r9",
        "condition": "SmokeDetectorAlarm and userPresent",
        "action": "not CallEmergencyServices within 3 minutes",
        "defeater": "",
    }

    result = engine.decompose_rule_for_concern(
        rule=rule,
        context="not userDisablesAlarm",
        desired_action="CallEmergencyServices within 1 minute",
        used_rule_ids=set(),
    )

    assert result is not None

    branches = result.splitlines()
    assert len(branches) == 2

    complementary_branch = branches[1]

    original_temporal = engine.temporal_bound(rule["action"])
    branch_temporal = engine.temporal_bound(complementary_branch)

    assert original_temporal is not None
    assert branch_temporal is not None

    assert (
        branch_temporal["seconds"]
        == original_temporal["seconds"]
    )


def test_rule_decomposition_rejects_context_already_in_trigger():
    engine = make_engine()

    rule = {
        "id": "r9",
        "condition": "SmokeDetectorAlarm and userPresent",
        "action": "not CallEmergencyServices within 3 minutes",
        "defeater": "",
    }

    result = engine.decompose_rule_for_concern(
        rule=rule,
        context="userPresent",
        desired_action="CallEmergencyServices within 1 minute",
        used_rule_ids=set(),
    )

    assert result is None


# ---------------------------------------------------------------------------
# defeater_refinement
# ---------------------------------------------------------------------------

def test_defeater_refinement_paper_example():
    """
    Paper example:

    Original:
        when SmokeDetectorAlarm
        then CallEmergencyServices within 1 minute
        unless userPresent

    Concern context:
        not userDisablesAlarm

    Refined:
        unless userPresent and userDisablesAlarm
    """
    engine = make_engine()

    rule = {
        "id": "r8",
        "condition": "SmokeDetectorAlarm",
        "action": "CallEmergencyServices within 1 minute",
        "defeater": "userPresent",
    }

    result = engine.exclude_context_from_defeater(
        rule=rule,
        context="not userDisablesAlarm",
        concern_action="",
    )

    assert result

    # Trigger is untouched.
    assert "when SmokeDetectorAlarm" in result

    # Response and deadline are untouched.
    assert (
        "then CallEmergencyServices within 1 minute"
        in result
    )

    # Existing defeater is preserved and refined with complement(C).
    assert "userPresent" in result
    assert "userDisablesAlarm" in result

    # C itself must not be copied into the refined defeater.
    assert "not userDisablesAlarm" not in result


def test_defeater_refinement_requires_existing_defeater():
    engine = make_engine()

    rule = {
        "id": "r8",
        "condition": "SmokeDetectorAlarm",
        "action": "CallEmergencyServices within 1 minute",
        "defeater": "",
    }

    result = engine.exclude_context_from_defeater(
        rule=rule,
        context="not userDisablesAlarm",
        concern_action="",
    )

    assert result == ""


def test_defeater_refinement_preserves_alternative_response():
    engine = make_engine()

    rule = {
        "id": "r8",
        "condition": "SmokeDetectorAlarm",
        "action": "CallEmergencyServices within 1 minute",
        "defeater": (
            "userPresent then "
            "not CallEmergencyServices within 3 minutes"
        ),
    }

    result = engine.exclude_context_from_defeater(
        rule=rule,
        context="not userDisablesAlarm",
        concern_action=(
            "not CallEmergencyServices within 3 minutes"
        ),
    )

    assert result

    assert "userPresent" in result
    assert "userDisablesAlarm" in result

    # The existing alternative response is preserved exactly.
    assert (
        "then not CallEmergencyServices within 3 minutes"
        in result
    )


def test_defeater_refinement_rejects_unrelated_alternative_response():
    engine = make_engine()

    rule = {
        "id": "r8",
        "condition": "SmokeDetectorAlarm",
        "action": "CallEmergencyServices within 1 minute",
        "defeater": (
            "userPresent then "
            "NotifyUserRisk within 2 minutes"
        ),
    }

    result = engine.exclude_context_from_defeater(
        rule=rule,
        context="not userDisablesAlarm",
        concern_action=(
            "not CallEmergencyServices within 3 minutes"
        ),
    )

    assert result == ""
