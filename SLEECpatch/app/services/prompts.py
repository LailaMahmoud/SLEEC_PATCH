import json
import re


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


def build_sleec_syntax_bank(rules):
    rules = rules or []
    rule_texts = [
        str(rule.get("raw") or rule.get("text") or "").strip()
        if isinstance(rule, dict)
        else str(rule or "").strip()
        for rule in rules
    ]
    rule_texts = [text for text in rule_texts if text]

    observed = []
    if any(" unless " in text.lower() for text in rule_texts):
        observed.append("unless exceptions with optional alternative responses")
    if any(" within " in text.lower() for text in rule_texts):
        observed.append("within time bounds")
    if any(re.search(r"\{[A-Za-z_][A-Za-z0-9_]*\}", text) for text in rule_texts):
        observed.append("boolean measures wrapped in braces")
    if any(re.search(r"\{?[A-Za-z_][A-Za-z0-9_]*\}?\s*[<>=]\s*[A-Za-z0-9_]+", text) for text in rule_texts):
        observed.append("measure comparisons")
    if any(re.search(r"\b(?:and|or|not)\b", text, flags=re.IGNORECASE) for text in rule_texts):
        observed.append("and/or/not logical conditions")

    examples = rule_texts[:5]

    return {
        "allowed_rule_templates": [
            "RuleName when Trigger then Action",
            "RuleName when Trigger and Condition then Action",
            "RuleName when Trigger then Action within Number seconds",
            "RuleName when Trigger then Action unless Condition",
            "RuleName when Trigger then Action unless Condition then AlternativeAction",
        ],
        "observed_syntax_features": observed,
        "local_rule_examples": examples,
        "instruction": (
            "Use only these observed SLEEC syntax forms and the supplied "
            "vocabulary. Do not invent grammar constructs."
        )
    }


SLEEC_SYNTAX_CONTRACT = """
SLEEC SYNTAX CONTRACT:
Use only the SLEEC syntax already present in the input specification.

Allowed declaration lines:
- event EventName
- measure measureName:boolean
- measure measureName:numeric
- constant ConstantName = value

Allowed rule shapes:
- RuleName when Trigger then Action
- RuleName when Trigger and Condition then Action
- RuleName when Trigger then Action within Number seconds
- RuleName when Trigger then Action
       unless Condition then AlternativeAction
- RuleName when Trigger then Action
       unless Condition

Allowed condition syntax:
- and, or, not
- parentheses for grouping
- boolean measures as {measureName}
- numeric comparisons such as {measureName} > ConstantName

Forbidden syntax:
- Do not use IF, ELSE, REQUIRES, BECAUSE, SHOULD, MUST, UNTIL, EXCEPT, IMPLIES, or arrows.
- Do not invent new SLEEC keywords.
- Do not put prose, bullet points, or comments inside proposed_rule.
- Do not wrap the whole rule in parentheses.
- Do not output def_start, def_end, rule_start, or rule_end inside proposed_rule.
- Do not output declaration lines inside proposed_rule.

Vocabulary accounting:
- If missing_element is a new event, set new_events_added to 1.
- If missing_element is a new measure, set new_measures_added to 1.
- If missing_element is a new response/capability, set new_capabilities_added to 1.
- If the patch adds a new rule, set new_rules_added to 1.
- Otherwise the corresponding counter must be 0.

If you cannot express the repair using this syntax contract, return not_applicable.
"""


SLEEC_FEW_SHOT_SYNTAX_EXAMPLES = """
FEW-SHOT SLEEC SYNTAX EXAMPLES:
These examples teach syntax shape only. Do not copy their domain vocabulary.

Example 1: edit an existing event trigger
Original rule:
r1 when BroadEvent then SafeAction
Correct proposed_rule:
r1 when SpecificEvent then SafeAction

Example 2: preserve an unless branch
Original rule:
r2 when RequestAction then DoAction
   unless {unsafeState} then StopAction
Correct proposed_rule:
r2 when SpecificRequestAction then DoAction
   unless {unsafeState} then StopAction

Example 3: preserve temporal syntax
Original rule:
r3 when EmergencyEvent then NotifyHuman within 60 seconds
Correct proposed_rule:
r3 when SpecificEmergencyEvent then NotifyHuman within 60 seconds

Example 4: add one new rule
Correct proposed_rule:
r_new when MissingConditionEvent and {relevantState} then RequiredAction

Example 5: no safe semantic repair
Correct output:
[{"patch_id":"not_applicable","operation":"none","target_rule_id":"","original_rule":"","missing_element":"","proposed_rule":"","natural_language_explanation":"The selected semantic operator cannot be expressed safely with valid SLEEC syntax.","modification_cost":0,"new_events_added":0,"new_measures_added":0,"new_capabilities_added":0,"new_rules_added":0,"defeaters_added":0}]
"""


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
        "syntax_bank": build_sleec_syntax_bank(rules),
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
10. Ground every new semantic element in the diagnosed witness, current system description,
    or an explicit specialization/refinement relationship to existing vocabulary.
11. Do not invent a concept merely because it sounds plausible.
12. Preserve diagnosed temporal information. If the diagnosis contains WITHIN or another
    time bound, the generated patch must preserve or explicitly refine that temporal dimension.
13. For new_rule_generation, the new rule must explicitly address at least one diagnosed
    condition, response, measure, event, or temporal constraint.
14. Use existing declared vocabulary whenever it is sufficient.
15. Follow the SLEEC syntax contract exactly.
16. If the selected repair cannot be written in valid SLEEC syntax, return not_applicable.

{SLEEC_SYNTAX_CONTRACT}

{SLEEC_FEW_SHOT_SYNTAX_EXAMPLES}

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
