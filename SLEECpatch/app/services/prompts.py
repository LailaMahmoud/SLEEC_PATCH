import json


PATCH_OUTPUT_FORMAT = """
Return a raw JSON array of small edit proposals. Return [] if the evidence does
not justify an edit. Each proposal has these required fields:
operation, target_rule_id, change, natural_language_explanation.
The only additional field allowed is source_requirement_id for a concern-anchored addition.
Do not supply proposed_rule, original_rule, declarations, verification results
or scores. Application code constructs the SLEEC and verifies it.

For event_specialization, capability_refinement and measure_specialization,
change has: from, to, meaning, evidence.
For scale-measure specialization also provide scale_labels: a list of new,
globally unused labels corresponding to the old labels in their original order.
For new_rule_generation, change has: rule_id, trigger_event, condition,
response_event, negated (Boolean), deadline (null or {value: integer, unit:
seconds/minutes/hours/days} or {kind: "eventually"}). Use existing vocabulary in new rules.
When addition_scope is provided, new_rule_generation must also include
source_requirement_id equal to its source_id and target_rule_id=null.
Synthesize the rule from the diagnosis and domain context and explain why it
addresses the concern. Application code renders the fields you supply; it does
not choose a rule for you. You may choose deadline={kind: "source"} to copy the
source timing exactly, including intervals, constants and eventually.
Preserve all existing rules and justify the timing of the additional rule.
"""

LLM_SEMANTIC_OPERATORS = [
    "event_specialization", "measure_specialization",
    "capability_refinement", "new_rule_generation"
]

# Examples are edit data, not handwritten SLEEC for the model to copy.
OPERATOR_EXAMPLES = {
    "event_specialization": json.dumps({
        "operation": "event_specialization", "target_rule_id": "r1",
        "change": {"from": "ParcelArrived", "to": "ParcelReadyForCollection",
                   "meaning": "The parcel is available at the collection point.",
                   "evidence": "The diagnosed arrival event conflates sorting and collection readiness; confirm this distinction with the requirements owner."},
        "natural_language_explanation": "Specialize the trigger while preserving its deadline, response and exceptions."}),
    "measure_specialization": json.dumps({
        "operation": "measure_specialization", "target_rule_id": "r1",
        "change": {"from": "ready", "to": "collectionReady",
                   "meaning": "The parcel can be collected by its recipient.",
                   "evidence": "The readiness predicate is ambiguous in the diagnosed context; this proposed interpretation needs stakeholder review."},
        "natural_language_explanation": "Specialize the measure and retain its declared type."}),
    "capability_refinement": json.dumps({
        "operation": "capability_refinement", "target_rule_id": "r1",
        "change": {"from": "Notify", "to": "SendCollectionNotice",
                   "meaning": "Send the recipient a notice that their parcel is ready.",
                   "evidence": "The diagnosed response does not distinguish this notice from other notifications; confirm that the system supports this response."},
        "natural_language_explanation": "Specialize only the main response event, preserving polarity, timing and exceptions."}),
    "new_rule_generation": json.dumps({
        "operation": "new_rule_generation", "target_rule_id": "r1",
        "change": {"rule_id": "priority_notice", "trigger_event": "ParcelArrived",
                   "condition": "{priority}", "response_event": "Notify", "negated": False,
                   "deadline": {"value": 2, "unit": "minutes"}},
        "natural_language_explanation": "Require the declared notification in the diagnosed priority context within its stated deadline."})
}


def semantic_refinement_prompt(
    issue_type, rules, findings, repair_operator, system_description="",
    existing_events=None, existing_measures=None, existing_responses=None
):
    items = findings if isinstance(findings, list) else [findings]
    addition_scopes = [item["addition_scope"] for item in items if isinstance(item, dict) and "addition_scope" in item]
    payload = {
        "issue_type": issue_type, "repair_operator": repair_operator,
        "sleec_findings": [item for item in items if not (isinstance(item, dict) and "diagnosis" in item)],
        "diagnosis_evidence": [item["diagnosis"] for item in items if isinstance(item, dict) and "diagnosis" in item],
        "addition_scopes": addition_scopes,
        "rules": rules, "system_description": system_description,
        "existing_events": existing_events or [], "existing_measures": existing_measures or [],
        "existing_responses": existing_responses or []
    }
    example = OPERATOR_EXAMPLES.get(repair_operator, "")
    if repair_operator == "new_rule_generation" and addition_scopes:
        # Keep an unrelated illustrative example. Do not precompute a solution
        # to the actual concern and attribute that choice to the LLM.
        illustrative = json.loads(example)
        illustrative.update(target_rule_id=None, source_requirement_id="parcel_notice_concern")
        example = json.dumps(illustrative)
    return f"""
Propose only the selected semantic edit operator: {repair_operator}.
Edits target only rules marked repair_target. A new rule may instead be anchored
to the provided addition_scope, including when no existing rule is a repair target.
Changes to meaning require stakeholder
review even if the resulting specification passes formal checks.
Use the reported source requirement, ordered trace, timestamps in seconds,
measure values and rule references. Trace observations are possible behaviours,
not new requirements. An empty affected_rule_ids list means causal rule IDs are
unavailable; any proposed target is a hypothesis to verify.
Do not invent observations or claim stakeholder approval.
Existing-rule edits keep deadlines, polarity, Boolean grouping and unrelated exceptions unchanged.
A new concept must be explained and grounded in the diagnosis or domain
description; do not assume a newly named event is already observable.
Event specialization changes only the trigger event. Capability refinement
changes only the main response event. Measure specialization substitutes a
measure with the same type, retaining comparisons and ordered scale meanings.
New-rule generation uses declared vocabulary and adds one rule. Do not change
the concern, purpose or relation that defines the verification problem.
A condition must be a SLEEC Boolean expression: {{priority}}, (not {{priority}}),
({{priority}} and {{ready}}), or ({{count}} > 0). Bare events are not Boolean
measures. Use parentheses around every binary Boolean expression.

{PATCH_OUTPUT_FORMAT}

Illustrative proposal for the selected operator (use the actual domain):
{example}

INPUT:
{json.dumps(payload, indent=2)}
"""


def event_specialization_prompt(
    issue_type,
    rules,
    findings,
    system_description="",
    existing_events=None,
    existing_measures=None,
    existing_responses=None
):
    return semantic_refinement_prompt(
        issue_type=issue_type,
        rules=rules,
        findings=findings,
        repair_operator="event_specialization",
        system_description=system_description,
        existing_events=existing_events,
        existing_measures=existing_measures,
        existing_responses=existing_responses
    )


def measure_specialization_prompt(
    issue_type,
    rules,
    findings,
    system_description="",
    existing_events=None,
    existing_measures=None,
    existing_responses=None
):
    return semantic_refinement_prompt(
        issue_type=issue_type,
        rules=rules,
        findings=findings,
        repair_operator="measure_specialization",
        system_description=system_description,
        existing_events=existing_events,
        existing_measures=existing_measures,
        existing_responses=existing_responses
    )


def capability_refinement_prompt(
    issue_type,
    rules,
    findings,
    system_description="",
    existing_events=None,
    existing_measures=None,
    existing_responses=None
):
    return semantic_refinement_prompt(
        issue_type=issue_type,
        rules=rules,
        findings=findings,
        repair_operator="capability_refinement",
        system_description=system_description,
        existing_events=existing_events,
        existing_measures=existing_measures,
        existing_responses=existing_responses
    )


def new_rule_generation_prompt(
    issue_type,
    rules,
    findings,
    system_description="",
    existing_events=None,
    existing_measures=None,
    existing_responses=None
):
    return semantic_refinement_prompt(
        issue_type=issue_type,
        rules=rules,
        findings=findings,
        repair_operator="new_rule_generation",
        system_description=system_description,
        existing_events=existing_events,
        existing_measures=existing_measures,
        existing_responses=existing_responses
    )


def build_prompt(
    issue_type,
    rules,
    findings,
    repair_operator,
    system_description="",
    existing_events=None,
    existing_measures=None,
    existing_responses=None
):
    if repair_operator not in LLM_SEMANTIC_OPERATORS:
        raise ValueError(
            f"{repair_operator} is deterministic and must be generated by Python script, not GPT."
        )

    return semantic_refinement_prompt(
        issue_type=issue_type,
        rules=rules,
        findings=findings,
        repair_operator=repair_operator,
        system_description=system_description,
        existing_events=existing_events,
        existing_measures=existing_measures,
        existing_responses=existing_responses
    )


# PATCH RANKING — Section C
def patch_quality_ranking_prompt(
    patch,
    system_description="",
    existing_events=None,
    existing_measures=None,
    existing_responses=None
):
    payload = {
        "system_description": system_description,
        "original_rule": patch.get("original_rule", ""),
        "proposed_rule": patch.get("proposed_rule", ""),
        "operation": patch.get("operation", ""),
        "natural_language_explanation": patch.get(
            "natural_language_explanation", patch.get("explanation", "")
        ),
        "missing_element": patch.get("missing_element", ""),
        "issue_type": patch.get("issue_type", ""),
        "selected_issue": patch.get("selected_issue", ""),
        "affected_rules": patch.get("affected_rules", []),
        "diagnosis_context": patch.get("diagnosis_context", ""),
        "existing_events": existing_events or [],
        "existing_measures": existing_measures or [],
        "existing_responses": existing_responses or []
    }

    return f"""
The SLEEC repair below has ALREADY passed formal verification.
Do NOT assess formal correctness and do NOT propose a different repair.

Assess only:

SEMANTIC CLARITY (0-100)
Prefer specific, unambiguous, domain-grounded events, measures, and responses.

VOCABULARY INTERPRETATION RULES:
- existing_events, existing_measures, and existing_responses contain concepts
  already declared or already used in the current SLEEC specification.
- Do NOT classify or penalize a concept as newly introduced merely because it
  is absent from the individual original_rule.
- A concept is genuinely new only if it appears in proposed_rule but is absent
  from existing_events, existing_measures, existing_responses, and original_rule.
- Reuse of a declared concept should normally support semantic clarity when the
  concept is used consistently with its domain meaning.
- For a genuinely new concept, assess whether it is specific, unambiguous,
  domain-grounded, explained by the repair rationale/system description, and
  meaningfully distinct from existing vocabulary.
- Penalize genuinely new generic placeholders such as RiskHigh, ConditionMet,
  SituationBad, UserIsOk, NormalState, and SpecialCase.
- Do NOT penalize declared concepts such as riskLevel, userOccupied,
  humanAssents, SmokeDetectorAlarm, or userDisablesAlarm when they appear in
  the supplied existing vocabulary.

INTERPRETABILITY (0-100)
Prefer preservation of apparent stakeholder intent, an understandable rationale,
minimal dependence on unstated context, and descriptive predicates.
Penalize unexplained action changes or contextual distinctions.

AND, OR, NOT, WHEN, THEN, UNLESS, and WITHIN are SLEEC syntax, not predicates.
If proposed_rule contains multiple rules, assess the complete repair.

INPUT:
{json.dumps(payload, indent=2)}

Return ONLY this raw JSON object:
{{
  "semantic_clarity": 0,
  "semantic_clarity_reason": "one concise reason",
  "interpretability": 0,
  "interpretability_reason": "one concise reason"
}}
"""
