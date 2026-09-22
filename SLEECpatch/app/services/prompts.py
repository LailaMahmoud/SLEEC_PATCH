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

    "grounding_evidence": {
      "source": "system_description",
      "source_terms": [
        "pain"
      ],
      "existing_element": "UserRequestsDressing",
      "new_element": "UserRequestsDressingWhileInPain",
      "relationship": "The new event specializes the existing event using domain context explicitly supported by the supplied source."
    },

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


OPERATOR_EXAMPLES = {
'event_specialization': '''EXAMPLE: EVENT SPECIALIZATION

This example demonstrates the repair pattern and grounding format only.
Do not copy its domain vocabulary into another use case.

System description excerpt:
"The dressing assistant monitors the user for signs of pain during dressing."

Original rule:
r1 when UserRequestsDressing then ContinueDressing

Diagnosis:
The broad event UserRequestsDressing does not distinguish requests made while the user is experiencing pain.

Selected operator:
event_specialization

Correct patch:
[{
  "patch_id": "p1",
  "issue_type": "situational_conflict",
  "operation": "event_specialization",
  "applicability": {
    "is_applicable": true,
    "reason": "The supplied domain description explicitly supports pain as a relevant dressing context."
  },
  "target_rule_id": "r1",
  "original_rule": "r1 when UserRequestsDressing then ContinueDressing",
  "missing_element": "UserRequestsDressingWhileInPain",
  "proposed_rule": "r1 when UserRequestsDressingWhileInPain then ContinueDressing",
  "grounding_evidence": {
    "source": "system_description",
    "source_terms": ["pain", "during dressing"],
    "existing_element": "UserRequestsDressing",
    "new_element": "UserRequestsDressingWhileInPain",
    "relationship": "The new event specializes UserRequestsDressing using the explicitly described pain context."
  },
  "natural_language_explanation": "The broad request event is specialized using an explicitly supported domain context.",
  "modification_cost": 1,
  "new_events_added": 1,
  "new_measures_added": 0,
  "new_capabilities_added": 0,
  "new_rules_added": 0,
  "defeaters_added": 0
}]''',

'measure_specialization': '''EXAMPLE: MEASURE SPECIALIZATION

This example demonstrates the repair pattern and grounding format only.
Do not copy its domain vocabulary into another use case.

System description excerpt:
"The monitoring system measures room temperature to distinguish unsafe environmental conditions."

Original rule:
r1 when UserEntersRoom and {environmentRisk} then IssueWarning

Diagnosis:
The general environmentRisk measure does not distinguish the temperature-related situation identified in the diagnosis.

Selected operator:
measure_specialization

Correct patch:
[{
  "patch_id": "p1",
  "issue_type": "situational_conflict",
  "operation": "measure_specialization",
  "applicability": {
    "is_applicable": true,
    "reason": "The supplied domain description explicitly identifies room temperature as a monitored environmental condition."
  },
  "target_rule_id": "r1",
  "original_rule": "r1 when UserEntersRoom and {environmentRisk} then IssueWarning",
  "missing_element": "unsafeRoomTemperature",
  "proposed_rule": "r1 when UserEntersRoom and {unsafeRoomTemperature} then IssueWarning",
  "grounding_evidence": {
    "source": "system_description",
    "source_terms": ["room temperature", "unsafe environmental conditions"],
    "existing_element": "environmentRisk",
    "new_element": "unsafeRoomTemperature",
    "relationship": "The new measure specializes the broad environmentRisk measure using the explicitly described temperature condition."
  },
  "natural_language_explanation": "The broad environmental measure is specialized using an explicitly supported environmental property.",
  "modification_cost": 1,
  "new_events_added": 0,
  "new_measures_added": 1,
  "new_capabilities_added": 0,
  "new_rules_added": 0,
  "defeaters_added": 0
}]''',

'capability_refinement': '''EXAMPLE: CAPABILITY REFINEMENT

This example demonstrates the repair pattern and grounding format only.
Do not copy its domain vocabulary into another use case.

System description excerpt:
"The assistance system can contact a specialist support service when general user assistance is insufficient."

Original rule:
r1 when AssistanceNeeded then ContactSupport

Diagnosis:
The broad ContactSupport response does not distinguish the specialist-support capability required in the diagnosed situation.

Selected operator:
capability_refinement

Correct patch:
[{
  "patch_id": "p1",
  "issue_type": "purpose_blocking",
  "operation": "capability_refinement",
  "applicability": {
    "is_applicable": true,
    "reason": "The supplied domain description explicitly identifies specialist support as a system capability."
  },
  "target_rule_id": "r1",
  "original_rule": "r1 when AssistanceNeeded then ContactSupport",
  "missing_element": "ContactSpecialistSupport",
  "proposed_rule": "r1 when AssistanceNeeded then ContactSpecialistSupport",
  "grounding_evidence": {
    "source": "system_description",
    "source_terms": ["specialist support service", "general user assistance"],
    "existing_element": "ContactSupport",
    "new_element": "ContactSpecialistSupport",
    "relationship": "The new capability refines ContactSupport into the more specific specialist-support capability explicitly described by the domain source."
  },
  "natural_language_explanation": "The broad support capability is refined using a more specific capability explicitly supported by the domain description.",
  "modification_cost": 1,
  "new_events_added": 0,
  "new_measures_added": 0,
  "new_capabilities_added": 1,
  "new_rules_added": 0,
  "defeaters_added": 0
}]''',

    'new_rule_generation': '''EXAMPLE: NEW RULE GENERATION

This example demonstrates the repair pattern and grounding format only.
Do not copy its domain vocabulary into another use case.

System description excerpt:
"The monitoring system detects a user fall and can notify a caregiver."

Existing rule:
r1 when UserRequestsHelp then NotifyCaregiver

Diagnosis:
The diagnosed concern identifies missing normative behaviour after a detected user fall.

Selected operator:
new_rule_generation

Correct patch:
[{
  "patch_id": "p1",
  "issue_type": "concerns",
  "operation": "new_rule_generation",
  "applicability": {
    "is_applicable": true,
    "reason": "The diagnosis identifies missing behaviour, and the supplied domain description explicitly supports both fall detection and caregiver notification."
  },
  "target_rule_id": "",
  "original_rule": "",
  "missing_element": "UserFall -> NotifyCaregiver",
  "proposed_rule": "r_new when UserFall then NotifyCaregiver",
  "grounding_evidence": {
    "source": "system_description",
    "source_terms": ["detects a user fall", "notify a caregiver"],
    "existing_element": "NotifyCaregiver",
    "new_element": "UserFall -> NotifyCaregiver",
    "relationship": "The new rule connects the explicitly described fall event to the explicitly described caregiver-notification capability to address the diagnosed missing behaviour."
  },
  "natural_language_explanation": "A new normative rule is introduced for behaviour that is explicitly supported by both the diagnosis and the supplied domain description.",
  "modification_cost": 1,
  "new_events_added": 1,
  "new_measures_added": 0,
  "new_capabilities_added": 0,
  "new_rules_added": 1,
  "defeaters_added": 0
}]'''
}

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
10. Every newly introduced semantic element MUST be grounded in at least one permitted source:
    - system_description: the supplied original case-study Description;
    - diagnosis: the supplied LEGOS-SLEEC diagnosis;
    - witness: the supplied LEGOS-SLEEC witness/trace;
    - existing_vocabulary: an explicit event, measure, response, or rule supplied in the input.

11. For every new semantic element, populate grounding_evidence.
    - source must identify the permitted source used.
    - source_terms must contain exact words, phrases, or formal identifiers present in that source.
    - existing_element must identify the existing SLEEC element being specialized or refined,
      when the selected operator modifies an existing semantic element.
    - new_element must exactly identify the semantic element introduced by the patch.
    - relationship must explain how the cited source evidence supports the specialization,
      refinement, or missing behaviour.

12. Do NOT claim grounding from general knowledge, common sense, an unstated domain assumption,
    the worked example, or a concept that merely sounds plausible.

13. Do NOT copy semantic concepts from the worked example unless those concepts are independently
    supported by the current use case's permitted sources.

14. If no permitted source supports the semantic element required by the selected operator,
    return not_applicable rather than inventing a concept.

15. Preserve diagnosed temporal information. If the diagnosis contains WITHIN or another
    time bound, the generated patch must preserve or explicitly refine that temporal dimension.

16. For new_rule_generation, the new rule must explicitly address at least one diagnosed
    condition, response, measure, event, or temporal constraint.

17. Use existing declared vocabulary whenever it is sufficient.

18. Follow the SLEEC syntax contract exactly.

19. If the selected repair cannot be written in valid SLEEC syntax, return not_applicable.
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
{json.dumps(payload, indent=2, ensure_ascii=False)}
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
{json.dumps(payload, indent=2, ensure_ascii=False)}

Return ONLY this raw JSON object:
{{
  "semantic_clarity": 0,
  "semantic_clarity_reason": "one concise reason",
  "interpretability": 0,
  "interpretability_reason": "one concise reason"
}}
"""
