"""Structured semantic proposals; Python builds the SLEEC and LEGOS verifies it.

Examples illustrate the output contract, never provide domain evidence.
"""
import json

LLM_SEMANTIC_OPERATORS = frozenset({
    "event_specialization", "measure_specialization", "response_refinement", "new_rule_generation"
})

OPERATOR_EXAMPLES = {key: json.dumps(value) for key, value in {'event_specialization': {'operation': 'event_specialization',
                          'target_rule_id': 'r1',
                          'change': {'from': 'ParcelArrived',
                                     'to': 'TrackedParcelArrived',
                                     'meaning': 'Arrival of a tracked parcel.',
                                     'evidence': 'The description distinguishes tracked '
                                                 'deliveries.'},
                          'natural_language_explanation': 'Distinguish tracked arrivals '
                                                          'while retaining the existing '
                                                          'response.'},
 'measure_specialization': {'operation': 'measure_specialization',
                            'target_rule_id': 'r1',
                            'change': {'from': 'ready',
                                       'to': 'readyForDispatch',
                                       'meaning': 'Ready for dispatch.',
                                       'evidence': 'The description distinguishes dispatch '
                                                   'readiness.',
                                       'element_path': 'trigger'},
                            'natural_language_explanation': 'Specialize the readiness '
                                                            'condition only.'},
 'response_refinement': {'operation': 'response_refinement',
                         'target_rule_id': 'r1',
                         'change': {'from': 'Notify',
                                    'to': 'NotifyRecipient',
                                    'meaning': 'Notify the recipient.',
                                    'evidence': 'The description identifies the recipient of '
                                                'the notice.',
                                    'response_path': 'main'},
                         'natural_language_explanation': 'Clarify the recipient while '
                                                         'preserving timing and exceptions.'},
 'new_rule_generation': {'operation': 'new_rule_generation',
                         'target_rule_id': None,
                         'source_requirement_id': 'missed_notice',
                         'change': {'rule_id': 'r2',
                                    'trigger_event': 'ParcelArrived',
                                    'condition': '{priority}',
                                    'response_event': 'Notify',
                                    'negated': False,
                                    'deadline': {'kind': 'source'}},
                         'natural_language_explanation': 'Require a notice in the selected '
                                                         'concern context and time window.'}}.items()}

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
        raise ValueError("Only the four selected semantic operators may be sent to the LLM.")
    payload = {"diagnosis_evidence": findings, "selected_operator": repair_operator, "diagnosed_wfi": issue_type,
               "diagnosis_and_witness": findings, "implicated_rules": rules,
               "system_description": system_description, "existing_events": existing_events or [],
               "existing_measures": existing_measures or [], "existing_responses": existing_responses or []}
    return """Instantiate ONLY the selected operator, with one grounded candidate (or [] if evidence is insufficient).
Return a raw JSON array. Never rewrite the specification. Preserve all untargeted elements.
Do not assert applicability or formal correctness. A human must review the intended meaning.
Each object has operation, target_rule_id, change, natural_language_explanation.
Do not include proposed_rule, a complete specification, verified, ranking scores, or extra fields.
For a concern, the response describes an undesirable possibility: the added obligation must prevent it.
Do not invent a rule ID, source ID, event or measure that collides with a supplied identifier.
For event_specialization: change={"from":existing trigger event,"to":new identifier,"meaning":definition,"evidence":support in the supplied context}.
For response_refinement: use the same fields and optional response_path (default "main";
use "main.unless[0]", "main.alternative", etc. for the specifically implicated response).
Change only that event, preserving polarity, deadline, alternatives and defeaters.
For measure_specialization: the same fields specialize one existing measure, with optional scale_labels
(one new label per existing scale value, in order). Use element_path="trigger" or "unless[0]"
to identify the single condition to change. Do not replace unrelated occurrences.
For a new Boolean context where none exists, use from="", to=new measure identifier,
element_path="trigger", meaning and evidence; this adds only the contextual condition.
Optionally set complementary_rule_id to another implicated rule to conjoin the complement
of the new context to that rule, partitioning the two diagnosed paths in ONE candidate.
For a new numeric or scale measure, specify measure_type="numeric" or "scale", context
(e.g. "({smokeSeverity} = high)"), and scale_labels (ordered unused labels for scale only).
For new_rule_generation: change={"rule_id":"R_new","trigger_event":declared event,
"condition":SLEEC Boolean MEASURE/CONTEXT expression only,"response_event":declared event,
"negated":true or false,
"deadline":{"value":integer,"unit":"seconds" or "minutes" or "hours" or "days"}}.
The application assigns the final unique rule identifier; "R_new" is only a placeholder.
Do NOT put trigger_event or response_event inside condition.
The condition field contains only measure/context expressions such as
{measure}, (not {measure}), ({a} and {b}), or ({numericMeasure} > 3).
Use an empty string when no additional condition is required.
Use target_rule_id=null and source_requirement_id equal to the source concern ID.
A deadline can also be {"kind":"source"} to retain the concern's timing,
{"kind":"eventually"}, or null for an immediate response. Prefer source timing when appropriate.
Retain interval bounds and symbolic deadlines using source timing rather than guessing a scalar bound.
The rule must prevent the undesirable concern; never create a new concern.

For new_rule_generation when diagnosed_wfi is a concern/insufficiency:
- Treat the source concern as the undesirable behavior that the new rule must prevent.
- Preserve the diagnosed concern trigger and diagnosed measure/context condition unless the supplied diagnosis provides explicit evidence for a different context.
- Do NOT replace the diagnosed concern condition with its logical complement merely to avoid the witness.
- The generated response must address the concern, not reproduce it.
- If the source concern is "then not RESPONSE", generate the required positive RESPONSE when that repair is grounded by the diagnosis and existing vocabulary.
- Do NOT copy the same negative response polarity from such a concern into the repair.
- If the source concern has a deadline, use {"kind":"source"} unless the supplied diagnosis explicitly grounds a different deadline.
- If the source concern has no deadline, use deadline=null.
- Never invent a zero-second deadline.
- If the diagnosis does not provide enough evidence for a grounded repair, return [] rather than inventing behavior.

Example:
Source concern:
c1 when HumanOnFloor and ({userOccupied} and ({riskLevel} = high))
then not CallEmergencyServices

Correct repair direction:
{"operation":"new_rule_generation",
 "target_rule_id":null,
 "source_requirement_id":"c1",
 "change":{
   "rule_id":"R_new",
   "trigger_event":"HumanOnFloor",
   "condition":"({userOccupied} and ({riskLevel} = high))",
   "response_event":"CallEmergencyServices",
   "negated":false,
   "deadline":null
 },
 "natural_language_explanation":"Supply the missing emergency response in the diagnosed concern context."}

The rule must prevent the undesirable concern; never create or restate the diagnosed concern.
SLEEC conditions use {measure}, (not {measure}), ({a} and {b}), ({a} or {b}),
and ({numericMeasure} > 3). Braces around Boolean/numeric measure references are mandatory.
Evidence must explain the domain distinction using the supplied description/diagnosis/vocabulary.
Illustrative JSON example (syntax only; its identifiers are not evidence for the current case):
""" + OPERATOR_EXAMPLES[repair_operator] + "\nINPUT:\n" + json.dumps(payload, default=str)
