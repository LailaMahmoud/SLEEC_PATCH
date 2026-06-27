import json


PATCH_OUTPUT_FORMAT = """
Return ONLY raw JSON array.

Each patch must use this format:
[
  {
    "patch_id": "p1",
    "issue_type": "conflict",
    "operation": "event_specialization",

    "applicability": {
      "is_applicable": true,
      "reason": "The conflict is caused by a broad trigger event that covers partially different behaviours."
    },

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

If the selected semantic operator is NOT applicable, return:
[
  {
    "patch_id": "not_applicable",
    "operation": "none",
    "applicability": {
      "is_applicable": false,
      "reason": "Explain why this semantic operator is not suitable."
    },
    "target_rule_id": "",
    "original_rule": "",
    "missing_element": "",
    "proposed_rule": "",
    "natural_language_explanation": "",
    "modification_cost": 0,
    "new_events_added": 0,
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

APPLICABILITY CHECK:
Before generating a patch, first decide whether the selected semantic repair operator is applicable.

The operator is applicable only if:
1. The diagnosis cannot be fully repaired by deterministic transformations.
2. The issue requires introducing a new semantic concept.
3. The new concept is justified by the witness trace, diagnosis, or domain context.
4. The patch preserves stakeholder intent.
5. The patch modifies only the relevant rule or adds only the needed rule.

If the selected semantic operator is not applicable, return the not_applicable JSON object from the required output format.

REPAIR OPERATOR MEANING:
- event_specialization: introduce a finer-grained event that distinguishes the conflicting situation.
- measure_specialization: introduce a more discriminative environmental measure or predicate.
- capability_refinement: refine a broad system response into a more specific capability.
- new_rule_generation: add a new normative rule when existing rules cannot prevent the issue.

EVENT SPECIALIZATION APPLICABILITY:
Use event_specialization only when:
- the same broad event triggers partially conflicting behaviours;
- the conflict cannot be resolved clearly by only adding a defeater;
- the diagnosis suggests that the event covers multiple contexts;
- a more specific event would make the behaviours distinguishable.

MEASURE SPECIALIZATION APPLICABILITY:
Use measure_specialization only when:
- the conflict depends on an environmental state;
- the current measure is too broad or vague;
- a more precise measure can distinguish the conflicting contexts.

CAPABILITY REFINEMENT APPLICABILITY:
Use capability_refinement only when:
- the response/action is too broad;
- the system capability needs to be decomposed into a more specific action;
- the existing action cannot explain the intended behaviour clearly.

NEW-RULE GENERATION APPLICABILITY:
Use new_rule_generation only when:
- the issue cannot be fixed by editing an existing rule;
- the diagnosis reveals a missing normative condition;
- a new rule is necessary to prevent the witness issue.

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
