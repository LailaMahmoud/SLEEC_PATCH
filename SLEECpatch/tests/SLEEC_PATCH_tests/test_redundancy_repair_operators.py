from services.deterministic_repair_engine import DeterministicRepairEngine


def make_engine():
    return DeterministicRepairEngine()


# ------------------------------------------------------------------
# Rule Removal
# ------------------------------------------------------------------

def test_rule_removal_identifies_second_exact_duplicate_as_redundant():
    """
    For exact duplicates, preserve the first diagnosed rule and identify
    the second diagnosed rule as redundant.
    """
    engine = make_engine()

    r1 = {
        "id": "r1",
        "condition": "PatientFallen",
        "action": "CallSupport",
        "defeater": "",
    }

    r2 = {
        "id": "r2",
        "condition": "PatientFallen",
        "action": "CallSupport",
        "defeater": "",
    }

    redundant, survivor = engine.find_redundant_rule_pair(
        "Redundancy between r1 and r2",
        [r1, r2],
    )

    assert redundant is not None
    assert survivor is not None
    assert redundant["id"] == "r2"
    assert survivor["id"] == "r1"


def test_rule_removal_identifies_specialized_rule_as_redundant():
    """
    If a broader rule already provides the same response, the more
    specialized rule is redundant.
    """
    engine = make_engine()

    r1 = {
        "id": "r1",
        "condition": "PatientFallen",
        "action": "CallSupport",
        "defeater": "",
    }

    r2 = {
        "id": "r2",
        "condition": "PatientFallen and {riskLevel}=high",
        "action": "CallSupport",
        "defeater": "",
    }

    redundant, survivor = engine.find_redundant_rule_pair(
        "Redundancy between r1 and r2",
        [r1, r2],
    )

    assert redundant is not None
    assert survivor is not None
    assert redundant["id"] == "r2"
    assert survivor["id"] == "r1"


def test_rule_removal_rejects_different_responses():
    """Rules with different responses are not removable as duplicates."""
    engine = make_engine()

    r1 = {
        "id": "r1",
        "condition": "PatientFallen",
        "action": "CallSupport",
        "defeater": "",
    }

    r2 = {
        "id": "r2",
        "condition": "PatientFallen",
        "action": "ProvideCompanionship",
        "defeater": "",
    }

    redundant, survivor = engine.find_redundant_rule_pair(
        "Redundancy between r1 and r2",
        [r1, r2],
    )

    assert redundant is None
    assert survivor is None


def test_generate_rule_removal_removes_diagnosed_redundant_rule():
    """
    Production generation must remove the rule identified by the
    redundancy analysis, not simply the first rule mentioned.
    """
    engine = make_engine()

    r1 = {
        "id": "r1",
        "condition": "PatientFallen",
        "action": "CallSupport",
        "defeater": "",
    }

    r2 = {
        "id": "r2",
        "condition": "PatientFallen",
        "action": "CallSupport",
        "defeater": "",
    }

    patches = engine.generate_redundancy_patches(
        selected_issue="Redundancy between r1 and r2",
        rules=[r1, r2],
        operators=["rule_removal"],
    )

    assert len(patches) == 1

    patch = patches[0]

    assert patch["operation"] == "rule_removal"
    assert patch["target_rule_id"] == "r2"
    assert patch["original_rule"] == engine.rule_to_text(r2)
    assert patch["proposed_rule"] == ""


# ------------------------------------------------------------------
# Defeater Propagation
# ------------------------------------------------------------------

def defeater_propagation_rules():
    """
    R1: when A and C then E1

    R2: when A then E2
        unless C then E1
    """
    r1 = {
        "id": "r1",
        "condition": "PatientFallen and {patientNotDeaf}",
        "action": "ProvideCompanionship",
        "defeater": "",
    }

    r2 = {
        "id": "r2",
        "condition": "PatientFallen",
        "action": "CallSupport",
        "defeater": "{patientNotDeaf} then ProvideCompanionship",
    }

    return r1, r2


def test_defeater_propagation_finds_valid_pair():
    """The diagnosed supporting/defeater pair satisfies applicability."""
    engine = make_engine()
    r1, r2 = defeater_propagation_rules()

    supporting, defeater_rule = engine.find_defeater_propagation_pair(
        "Redundancy between r1 and r2",
        [r1, r2],
    )

    assert supporting is not None
    assert defeater_rule is not None
    assert supporting["id"] == "r1"
    assert defeater_rule["id"] == "r2"


def test_defeater_propagation_exact_transformation():
    """
    Propagation moves the complement of the defeater condition into
    the trigger and removes the redundant alternative response.
    """
    engine = make_engine()
    _, r2 = defeater_propagation_rules()

    proposed = engine.propagate_defeater(r2)

    assert "PatientFallen" in proposed
    assert "patientNotDeaf" in proposed
    assert "not" in proposed
    assert "CallSupport" in proposed
    assert "ProvideCompanionship" not in proposed
    assert "unless" not in proposed


def test_defeater_propagation_requires_alternative_response():
    """
    A bare defeater is insufficient: propagation requires
    'unless C then E1'.
    """
    engine = make_engine()

    r1 = {
        "id": "r1",
        "condition": "PatientFallen and {patientNotDeaf}",
        "action": "ProvideCompanionship",
        "defeater": "",
    }

    r2 = {
        "id": "r2",
        "condition": "PatientFallen",
        "action": "CallSupport",
        "defeater": "{patientNotDeaf}",
    }

    supporting, defeater_rule = engine.find_defeater_propagation_pair(
        "Redundancy between r1 and r2",
        [r1, r2],
    )

    assert supporting is None
    assert defeater_rule is None


def test_generate_defeater_propagation_patch():
    """Production generation emits the pair-aware propagation candidate."""
    engine = make_engine()
    r1, r2 = defeater_propagation_rules()

    patches = engine.generate_redundancy_patches(
        selected_issue="Redundancy between r1 and r2",
        rules=[r1, r2],
        operators=["defeater_propagation"],
    )

    assert len(patches) == 1

    patch = patches[0]

    assert patch["operation"] == "defeater_propagation"
    assert patch["source"] == "deterministic"
    assert patch["issue_type"] == "redundancies"
    assert patch["target_rule_id"] == "r2"
    assert patch["supporting_rule_id"] == "r1"

    assert "PatientFallen" in patch["proposed_rule"]
    assert "patientNotDeaf" in patch["proposed_rule"]
    assert "CallSupport" in patch["proposed_rule"]
    assert "ProvideCompanionship" not in patch["proposed_rule"]


def test_generate_defeater_propagation_rejects_ungrounded_diagnosis():
    """The generator must not guess a propagation pair."""
    engine = make_engine()
    r1, r2 = defeater_propagation_rules()

    patches = engine.generate_redundancy_patches(
        selected_issue="A redundancy was detected",
        rules=[r1, r2],
        operators=["defeater_propagation"],
    )

    assert patches == []