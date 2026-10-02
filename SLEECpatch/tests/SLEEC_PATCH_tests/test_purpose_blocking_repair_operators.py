import pytest

from services.deterministic_repair_engine import DeterministicRepairEngine
from services.repair_operator_selector import RepairOperatorSelector


@pytest.fixture
def engine():
    return DeterministicRepairEngine()


@pytest.fixture
def selector():
    return RepairOperatorSelector()


@pytest.fixture
def blocking_rule():
    return {
        "id": "R9_1",
        "condition": "InformUser",
        "action": "RemindUser within 10 minutes",
        "defeater": "",
    }


def test_purpose_defeater_introduction_generates_patch(
    engine,
    blocking_rule,
):
    diagnosis = (
        "p7 when InformUser and {rulesFollowed} "
        "then not RemindUser within 10 minutes "
        "Because of the following SLEEC rule: R9_1"
    )

    patches = engine.generate_purpose_patches(
        diagnosis,
        [blocking_rule],
        ["defeater_introduction"],
    )

    assert len(patches) == 1

    patch = patches[0]

    assert patch["operation"] == "defeater_introduction"
    assert patch["issue_type"] == "purpose_blocking"
    assert patch["target_rule_id"] == "R9_1"

    assert "{rulesFollowed}" in patch["proposed_rule"]
    assert "unless" in patch["proposed_rule"]


def test_purpose_defeater_introduction_preserves_rule_body(
    engine,
    blocking_rule,
):
    diagnosis = (
        "p7 when InformUser and {rulesFollowed} "
        "then not RemindUser within 10 minutes "
        "Because of R9_1"
    )

    patches = engine.generate_purpose_patches(
        diagnosis,
        [blocking_rule],
        ["defeater_introduction"],
    )

    assert len(patches) == 1

    proposed = patches[0]["proposed_rule"]

    assert "when InformUser" in proposed
    assert "RemindUser within 10 minutes" in proposed
    assert "{rulesFollowed}" in proposed


def test_purpose_rejects_ungrounded_blocking_rule(
    engine,
    blocking_rule,
):
    diagnosis = (
        "p7 when InformUser and {rulesFollowed} "
        "then not RemindUser within 10 minutes"
    )

    patches = engine.generate_purpose_patches(
        diagnosis,
        [blocking_rule],
        ["defeater_introduction"],
    )

    assert patches == []


def test_purpose_rejects_no_new_context(
    engine,
    blocking_rule,
):
    diagnosis = (
        "p7 when InformUser "
        "then not RemindUser within 10 minutes "
        "Because of R9_1"
    )

    patches = engine.generate_purpose_patches(
        diagnosis,
        [blocking_rule],
        ["defeater_introduction"],
    )

    assert patches == []


def test_purpose_respects_operator_selection(
    engine,
    blocking_rule,
):
    diagnosis = (
        "p7 when InformUser and {rulesFollowed} "
        "then not RemindUser within 10 minutes "
        "Because of R9_1"
    )

    patches = engine.generate_purpose_patches(
        diagnosis,
        [blocking_rule],
        [],
    )

    assert patches == []


def test_selector_selects_purpose_defeater_when_context_exists(
    selector,
    blocking_rule,
):
    diagnosis = (
        "p7 when InformUser and {rulesFollowed} "
        "then not RemindUser within 10 minutes "
        "Because of R9_1"
    )

    result = selector.select(
        "purpose_blocking",
        rules=[blocking_rule],
        selected_issue=diagnosis,
    )

    assert "defeater_introduction" in result["deterministic"]


def test_restrictiveness_alias_routes_to_purpose_blocking(
    selector,
    blocking_rule,
):
    diagnosis = (
        "p7 when InformUser and {rulesFollowed} "
        "then not RemindUser within 10 minutes "
        "Because of R9_1"
    )

    result = selector.select(
        "restrictiveness",
        rules=[blocking_rule],
        selected_issue=diagnosis,
    )

    assert "defeater_introduction" in result["deterministic"]


def test_selector_rejects_purpose_without_new_context(
    selector,
    blocking_rule,
):
    diagnosis = (
        "p7 when InformUser "
        "then not RemindUser within 10 minutes "
        "Because of R9_1"
    )

    result = selector.select(
        "purpose_blocking",
        rules=[blocking_rule],
        selected_issue=diagnosis,
    )

    assert "defeater_introduction" not in result["deterministic"]