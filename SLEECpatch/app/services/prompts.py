import json


PATCH_OUTPUT_FORMAT = """
Return ONLY raw JSON array.

Each patch must use this format:
[
  {
    "patch_id": "p1",
    "issue_type": "conflict",
    "operation": "event_specialization",

    "target_rule_id": "r2",
    "original_rule": "r2 when UserRequestsDressing then StopDressing",
    "missing_element": "UserRequestsDressingWhileInPain",
    "proposed_rule": "r2 when UserRequestsDressingWhileInPain then StopDressing",

    "natural_language_explanation": "The broad event UserRequestsDressing is specialized into a pain-related event so the stop rule applies only in that context.",

    "modification_cost": 1,
    "new_events_added": 1,
    "new_measures_added": 0,
    "new_capabilities_added": 0,
    "new_rules_added": 0,
    "defeaters_added": 0
  }
]

Do NOT use markdown.
Do NOT use ```json.
Do NOT add text before or after JSON.
The response MUST start with [ and end with ].
"""


LLM_SEMANTIC_OPERATORS = [
    "event_specialization",
    "measure_specialization",
    "capability_refinement",
    "new_rule_generation"
]


OPERATOR_EXAMPLES = {'event_specialization': 'EXAMPLE: EVENT SPECIALIZATION FOR ALMI\n'
                         'Original rules:\n'
                         'r1 when FireSafetyMeasures then InformCaregiver\n'
                         'r2 when FireSafetyMeasures and not humanAssents then not InformCaregiver\n'
                         '\n'
                         'Correct patch:\n'
                         '[{"patch_id":"p1","issue_type":"situational_conflict","operation":"event_specialization","applicability":{"is_applicable":true,"reason":"The '
                         'event FireSafetyMeasures is too broad."},"target_rule_id":"r1","original_rule":"r1 when '
                         'FireSafetyMeasures then '
                         'InformCaregiver","missing_element":"ConfirmedFireHazard","proposed_rule":"r1 when '
                         'ConfirmedFireHazard then InformCaregiver","natural_language_explanation":"The broad event is '
                         'specialized into '
                         'ConfirmedFireHazard.","modification_cost":1,"new_events_added":1,"new_measures_added":0,"new_capabilities_added":0,"new_rules_added":0,"defeaters_added":0}]',
 'measure_specialization': 'EXAMPLE: MEASURE SPECIALIZATION FOR ALMI\n'
                           'Original rules:\n'
                           'r1 when UserWantsToCook and riskLevel=high then InterfereSafely\n'
                           'r2 when UserChangeMind and riskLevel=high then RecalculateApproach\n'
                           '\n'
                           'Correct patch:\n'
                           '[{"patch_id":"p1","issue_type":"situational_conflict","operation":"measure_specialization","applicability":{"is_applicable":true,"reason":"riskLevel '
                           'is too broad for different ALMI contexts."},"target_rule_id":"r1","original_rule":"r1 when '
                           'UserWantsToCook and riskLevel=high then '
                           'InterfereSafely","missing_element":"cookingRiskLevel","proposed_rule":"r1 when '
                           'UserWantsToCook and cookingRiskLevel=high then '
                           'InterfereSafely","natural_language_explanation":"The general risk measure is refined into '
                           'a cooking-specific risk '
                           'measure.","modification_cost":1,"new_events_added":0,"new_measures_added":1,"new_capabilities_added":0,"new_rules_added":0,"defeaters_added":0}]',
  'capability_refinement': 'EXAMPLE: CAPABILITY REFINEMENT FOR RESTRICTIVENESS\n'
                          'Blocking rule:\n'
                          'r1 when HumanOnFloor and not humanAssents then not CallEmergencyServices within 500 seconds\n'
                          'Intended purpose:\n'
                          'when HumanOnFloor and UserUnconscious and not humanAssents then CallEmergencyServices within 4 minutes\n'
                          '\n'
                          'Selected operator:\n'
                          'capability_refinement\n'
                          '\n'
                          'Correct patch:\n'
                          '[{"patch_id":"p1","issue_type":"purpose","operation":"capability_refinement","target_rule_id":"r1","original_rule":"r1 when HumanOnFloor and not humanAssents then not CallEmergencyServices within 500 seconds","missing_element":"RequestUrgentCareAssessment","proposed_rule":"r1 when HumanOnFloor and not humanAssents then not RequestUrgentCareAssessment within 500 seconds","natural_language_explanation":"The broad emergency-response capability is refined into a more specific urgent-care assessment capability.","modification_cost":1,"new_events_added":0,"new_measures_added":0,"new_capabilities_added":1,"new_rules_added":0,"defeaters_added":0}]',
'new_rule_generation': 'Use new_rule_generation only when no existing rule can be minimally edited. Add one '
                        'domain-specific rule and preserve all unrelated rules.'}

def semantic_refinement_prompt(
    issue_type,
    rules,
    findings,
    repair_operator,
    system_description="",
    existing_events=None,
    existing_measures=None,
    existing_responses=None
):
    existing_events = existing_events or []
    existing_measures = existing_measures or []
    existing_responses = existing_responses or []

    operator_example = OPERATOR_EXAMPLES.get(repair_operator, "")

    payload = {
        "issue_type": issue_type,
        "repair_operator": repair_operator,
        "sleec_findings": findings,
        "rules": rules,
        "system_description": system_description,
        "existing_events": existing_events,
        "existing_measures": existing_measures,
        "existing_responses": existing_responses
    }

    return f"""
You are an expert in SLEEC, normative requirements, semantic requirement refinement, and stakeholder-centered rule repair.

IMPORTANT ARCHITECTURE RULE:
SLEEC-PATCH uses deterministic Python scripts for syntactic repairs such as:
- trigger_refinement
- defeater_introduction
- rule_merging
- rule_removal
- trigger_strengthening
- rule_decomposition

You must NOT generate those deterministic repairs.

Your task is ONLY to instantiate the selected LLM-assisted semantic refinement operator:
- event_specialization
- measure_specialization
- capability_refinement
- new_rule_generation

TASK:
Generate candidate patches that introduce ONLY the missing semantic element required by the selected repair operator.

STRICT RULES:
1. Do not rewrite the full SLEEC specification.
2. Do not modify unrelated rules.
3. Preserve stakeholder intent.
4. Preserve the original domain meaning.
5. Generate only the missing event, measure, capability, or rule needed for the selected operator.
6. Avoid generic concepts such as RiskHigh, ConditionMet, SituationBad, or UserIsOk.
7. Prefer domain-specific concepts that are clear and interpretable.
8. Every proposed patch must be valid SLEEC syntax.
9. The patch will be formally verified by LEGOS-SLEEC after generation.

SELECTED REPAIR OPERATOR:
{repair_operator}

The repair operator has already been selected by SLEEC-PATCH from the
diagnosed well-formedness issue and its diagnosis context.

Your task is ONLY to instantiate this selected semantic repair operator.

Generate only the missing semantic element required by this operator:
- event_specialization: introduce one finer-grained domain event;
- measure_specialization: introduce one more discriminative environmental measure;
- capability_refinement: introduce one more specific system capability or response;
- new_rule_generation: introduce one additional normative SLEEC rule.

Do NOT select another repair operator.
Do NOT generate deterministic repairs.
Do NOT rewrite the complete specification.
Do NOT modify unrelated rules.
Preserve the original stakeholder intent.

REPAIR OPERATOR MEANING:
- event_specialization: introduce a finer-grained event that distinguishes the relevant situation.
- measure_specialization: introduce a more discriminative environmental measure or predicate.
- capability_refinement: refine a broad system response into a more specific capability.
- new_rule_generation: add a new normative rule when the diagnosed issue reveals missing normative behaviour.

OPERATOR-SPECIFIC INSTANTIATION GUIDANCE:

EVENT SPECIALIZATION:
Instantiate event_specialization by introducing a finer-grained event when:
- the diagnosis shows that a broad event covers multiple relevant contexts;
- the selected repair requires distinguishing those contexts semantically;
- the new event can make the affected behaviours distinguishable.
Do not introduce a defeater or other deterministic repair instead.

MEASURE SPECIALIZATION:
Instantiate measure_specialization by introducing a more discriminative measure when:
- the diagnosed issue depends on an environmental state;
- the current measure is too broad or vague for the selected repair;
- a more precise measure can distinguish the relevant contexts.
Do not replace this operator with a syntactic trigger refinement.

CAPABILITY REFINEMENT:
Instantiate capability_refinement by introducing a more specific system capability when:
- the response/action is too broad for the selected repair;
- the selected repair requires decomposing that response into a more specific action;
- the new capability better expresses the intended behaviour.
Do not change unrelated responses.

NEW-RULE GENERATION:
Instantiate new_rule_generation by adding one normative rule when:
- the diagnosis identifies missing normative behaviour;
- the selected repair requires an additional rule to prevent the witness issue;
- the new rule can be justified from the diagnosis and system context.
Do not rewrite existing unrelated rules.

OPERATOR-SPECIFIC WORKED EXAMPLE:
{operator_example}

Use this example only as a repair pattern. Do not copy concepts that are absent from the current use case.

INPUT:
{json.dumps(payload, indent=2)}

{PATCH_OUTPUT_FORMAT}
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
