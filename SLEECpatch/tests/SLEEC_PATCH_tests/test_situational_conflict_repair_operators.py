from services.deterministic_repair_engine import DeterministicRepairEngine


def make_engine():
    return DeterministicRepairEngine()


def conflict_rules():
    """
    Paper-style situational conflict.

    r1:
        SmokeDetectorAlarm -> CallEmergencyServices

    r2:
        HumanOnFloor and not {humanAssents}
            -> not CallEmergencyServices

    The contextual measure predicate is not {humanAssents}.
    """
    r1 = {
        "id": "r1",
        "condition": "SmokeDetectorAlarm",
        "action": "CallEmergencyServices within 5 minutes",
        "defeater": "",
    }

    r2 = {
        "id": "r2",
        "condition": "HumanOnFloor and not {humanAssents}",
        "action": "not CallEmergencyServices within 500 seconds",
        "defeater": "",
    }

    return r1, r2


# ------------------------------------------------------------------
# Trigger Refinement
# ------------------------------------------------------------------

def test_trigger_refinement_extracts_measure_context():
    """Only contextual measures, never the triggering event, are propagated."""
    engine = make_engine()
    _, r2 = conflict_rules()

    context = engine.conflict_measure_context(r2)

    assert context
    assert "humanAssents" in context
    assert "HumanOnFloor" not in context


def test_trigger_refinement_uses_complementary_context():
    """A negative conflicting context is complemented before refinement."""
    engine = make_engine()
    _, r2 = conflict_rules()

    context = engine.conflict_measure_context(r2)
    complement = engine.complement_context(context)

    assert complement
    assert "humanAssents" in complement
    assert "not {humanAssents}" not in complement


def test_trigger_refinement_rejects_event_only_rule():
    """An event-only trigger supplies no contextual measure predicate."""
    engine = make_engine()

    rule = {
        "id": "r2",
        "condition": "HumanOnFloor",
        "action": "not CallEmergencyServices",
        "defeater": "",
    }

    assert engine.conflict_measure_context(rule) == ""


# ------------------------------------------------------------------
# Defeater Introduction
# ------------------------------------------------------------------

def test_defeater_introduction_adds_measure_exception():
    """A diagnosis-grounded measure context can be introduced as a defeater."""
    engine = make_engine()

    rule = {
        "id": "r1",
        "condition": "SmokeDetectorAlarm",
        "action": "CallEmergencyServices within 5 minutes",
        "defeater": "",
    }

    proposed = engine.add_defeater(
        rule,
        "not {humanAssents}",
    )

    assert proposed
    assert "unless" in proposed
    assert "humanAssents" in proposed


def test_defeater_introduction_preserves_original_rule_body():
    """Introducing an exception must preserve trigger and primary response."""
    engine = make_engine()

    rule = {
        "id": "r1",
        "condition": "SmokeDetectorAlarm",
        "action": "CallEmergencyServices within 5 minutes",
        "defeater": "",
    }

    proposed = engine.add_defeater(
        rule,
        "not {humanAssents}",
    )

    assert "SmokeDetectorAlarm" in proposed
    assert "CallEmergencyServices within 5 minutes" in proposed


# ------------------------------------------------------------------
# Rule Merging
# ------------------------------------------------------------------

def test_rule_merging_is_applicable_for_confirmed_conflict_shape():
    """
    Rule merging applies when actions have opposite polarity and exactly
    one rule contains additional contextual conditions.
    """
    engine = make_engine()
    r1, r2 = conflict_rules()

    assert engine.compatible_for_merging(r1, r2) is True


def test_rule_merging_generates_conditional_alternative():
    """A compatible pair produces one rule with an explicit alternative."""
    engine = make_engine()
    r1, r2 = conflict_rules()

    proposed = engine.merge_conflicting_rules(r1, r2)

    assert proposed is not None
    assert "SmokeDetectorAlarm" in proposed
    assert "CallEmergencyServices" in proposed
    assert "unless" in proposed
    assert "HumanOnFloor" in proposed
    assert "humanAssents" in proposed
    assert "not CallEmergencyServices" in proposed


def test_rule_merging_rejects_same_polarity_actions():
    """Rules that do not prescribe opposite responses cannot be merged."""
    engine = make_engine()

    r1 = {
        "id": "r1",
        "condition": "SmokeDetectorAlarm",
        "action": "CallEmergencyServices",
        "defeater": "",
    }

    r2 = {
        "id": "r2",
        "condition": "HumanOnFloor and not {humanAssents}",
        "action": "CallEmergencyServices",
        "defeater": "",
    }

    assert engine.compatible_for_merging(r1, r2) is False
    assert engine.merge_conflicting_rules(r1, r2) is None


def test_rule_merging_rejects_when_both_rules_have_context():
    """Exactly one rule may contain additional context for this operator."""
    engine = make_engine()

    r1 = {
        "id": "r1",
        "condition": "SmokeDetectorAlarm and {riskLevel}=high",
        "action": "CallEmergencyServices",
        "defeater": "",
    }

    r2 = {
        "id": "r2",
        "condition": "HumanOnFloor and not {humanAssents}",
        "action": "not CallEmergencyServices",
        "defeater": "",
    }

    assert engine.compatible_for_merging(r1, r2) is False
    assert engine.merge_conflicting_rules(r1, r2) is None

# ------------------------------------------------------------------
# Conflict Patch Generation Integration
# ------------------------------------------------------------------

def test_generate_conflict_patches_routes_applicable_requested_operator():
    """
    The production conflict generator should emit an applicable requested
    deterministic repair operator for a diagnosis-grounded conflict.

    Requesting several operators does not imply that every operator must
    produce a candidate: operator-specific applicability conditions still
    apply.
    """
    engine = make_engine()
    r1, r2 = conflict_rules()

    patches = engine.generate_conflict_patches(
        issue_type="situational_conflicts",
        selected_issue="Situational conflict between r1 and r2",
        rules=[r1, r2],
        operators=[
            "trigger_refinement",
            "defeater_introduction",
            "rule_merging",
        ],
    )

    assert patches

    operations = {
        patch.get("operation")
        for patch in patches
    }

    # This rule pair satisfies the confirmed rule-merging contract.
    assert "rule_merging" in operations

    # Every generated candidate must belong to the requested operator set.
    assert operations <= {
        "trigger_refinement",
        "defeater_introduction",
        "rule_merging",
    }


def test_generate_conflict_patches_preserves_patch_metadata():
    """
    Generated candidates must retain deterministic source, WFI type,
    target information, original rule text, and proposed rule text.
    """
    engine = make_engine()
    r1, r2 = conflict_rules()

    patches = engine.generate_conflict_patches(
        issue_type="situational_conflicts",
        selected_issue="Situational conflict between r1 and r2",
        rules=[r1, r2],
        operators=[
            "trigger_refinement",
            "defeater_introduction",
            "rule_merging",
        ],
    )

    assert patches

    for patch in patches:
        assert patch["source"] == "deterministic"
        assert patch["issue_type"] == "situational_conflicts"
        assert patch["operation"] in {
            "trigger_refinement",
            "defeater_introduction",
            "rule_merging",
        }
        assert patch.get("target_rule_id")
        assert patch.get("original_rule")
        assert patch.get("proposed_rule")

        # Candidate generation must never emit a no-op patch.
        assert (
            patch["proposed_rule"].strip().lower()
            != patch["original_rule"].strip().lower()
        )


def test_generate_conflict_patches_respects_operator_selection():
    """
    Requesting only rule_merging must not generate candidates belonging
    to the other conflict repair operators.
    """
    engine = make_engine()
    r1, r2 = conflict_rules()

    patches = engine.generate_conflict_patches(
        issue_type="situational_conflicts",
        selected_issue="Situational conflict between r1 and r2",
        rules=[r1, r2],
        operators=["rule_merging"],
    )

    assert patches
    assert all(
        patch["operation"] == "rule_merging"
        for patch in patches
    )


def test_generate_conflict_patches_rejects_ungrounded_diagnosis():
    """
    Deterministic conflict repair must not guess a conflicting rule pair
    when the diagnosis does not identify two rules.
    """
    engine = make_engine()
    r1, r2 = conflict_rules()

    patches = engine.generate_conflict_patches(
        issue_type="situational_conflicts",
        selected_issue="A situational conflict was detected",
        rules=[r1, r2],
        operators=[
            "trigger_refinement",
            "defeater_introduction",
            "rule_merging",
        ],
    )

    assert patches == []
