import pytest

from services.prompts import build_prompt


COMMON = {
    "rules": [],
    "findings": [],
    "system_description": "Test autonomous system.",
    "existing_events": [
        "SmokeDetectorAlarm",
        "HumanOnFloor",
    ],
    "existing_measures": [
        "smokeSeverity",
        "humanAssents",
    ],
    "existing_responses": [
        "CallEmergencyServices",
        "CallFireDepartment",
        "NotifyUserRisk",
    ],
}


@pytest.mark.parametrize(
    "issue_type, expected_text",
    [
        ("situational_conflicts", "SITUATIONAL CONFLICT"),
        ("redundancy", "REDUNDANCY"),
    ],
)
def test_event_specialization_routes_by_wfi(issue_type, expected_text):
    prompt = build_prompt(
        issue_type=issue_type,
        repair_operator="event_specialization",
        **COMMON,
    )

    assert "event_specialization" in prompt
    assert expected_text in prompt


@pytest.mark.parametrize(
    "issue_type, expected_text",
    [
        ("situational_conflicts", "SITUATIONAL CONFLICT"),
        ("redundancy", "REDUNDANCY"),
    ],
)
def test_measure_specialization_routes_by_wfi(issue_type, expected_text):
    prompt = build_prompt(
        issue_type=issue_type,
        repair_operator="measure_specialization",
        **COMMON,
    )

    assert "measure_specialization" in prompt
    assert expected_text in prompt


@pytest.mark.parametrize(
    "issue_type, expected_text",
    [
        ("situational_conflicts", "WFI:\nSituational Conflict"),
        ("redundancy", "WFI:\nRedundancy"),
        ("purpose_blocking", "WFI:\nPurpose Blocking / Restrictiveness"),
    ],
)
def test_response_refinement_routes_by_wfi(issue_type, expected_text):
    prompt = build_prompt(
        issue_type=issue_type,
        repair_operator="response_refinement",
        **COMMON,
    )

    assert "response_refinement" in prompt
    assert expected_text in prompt


def test_new_rule_generation_routes_to_concern():
    prompt = build_prompt(
        issue_type="concerns",
        repair_operator="new_rule_generation",
        **COMMON,
    )

    assert "new_rule_generation" in prompt
    assert "APPLICABILITY" in prompt
    assert "normative behaviour not captured by the existing rules" in prompt


@pytest.mark.parametrize(
    "old_operator",
    [
        "semantic_rule_merging",
        "capability_refinement",
        "purpose_capability_refinement",
        "concern_new_rule_generation",
        "conflict_event_specialization",
        "conflict_measure_specialization",
        "redundancy_event_specialization",
        "redundancy_measure_specialization",
    ],
)
def test_obsolete_semantic_operator_names_are_rejected(old_operator):
    with pytest.raises(ValueError):
        build_prompt(
            issue_type="situational_conflicts",
            repair_operator=old_operator,
            **COMMON,
        )


@pytest.mark.parametrize(
    "issue_type",
    [
        "situational_conflicts",
        "redundancy",
        "purpose_blocking",
    ],
)
def test_new_rule_generation_rejects_non_concern_wfis(issue_type):
    with pytest.raises(ValueError):
        build_prompt(
            issue_type=issue_type,
            repair_operator="new_rule_generation",
            **COMMON,
        )


def test_new_rule_generation_preserves_response_polarity_instruction():
    from services.prompts import new_rule_generation_prompt

    prompt = new_rule_generation_prompt(
        issue_type="concerns",
        rules=[],
        findings=[],
        system_description="",
        existing_events=[],
        existing_measures=[],
        existing_responses=[],
    )

    assert "Preserve the response polarity" in prompt
    assert "not Response" in prompt
    assert "Do not reverse the required response" in prompt
