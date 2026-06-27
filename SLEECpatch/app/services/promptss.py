import json


PATCH_OUTPUT_FORMAT = """
Return ONLY raw JSON array.

Each patch must use this format:
[
{
  "patch_id": "p3",
  "issue_type": "concern",
  "operation": "add_defeater",
  "target_rule_id": "Rule7",
  "original_rule": "Rule7 when PreparingExamination then ObtainConsent",
  "proposed_rule": "Rule7 when PreparingExamination then ObtainConsent unless {medicalEmergency}",
  "natural_language_explanation": "Emergency situations bypass normal consent procedure.",
  "modification_cost": 1,
  "new_events_added": 0,
  "defeaters_added": 1
}
]

Do NOT use markdown.
Do NOT use ```json.
Do NOT add text before or after JSON.
The response MUST start with [ and end with ].
"""


def redundancy_prompt(rules, findings):
    payload = {
        "issue_type": "redundancy",
        "sleec_findings": findings,
        "rules": rules
    }

    return f"""
You are an expert in automated reasoning, SLEEC, normative requirements, and rule engineering.

TASK:
Generate patch candidates to resolve SLEEC-detected redundant rules.

IMPORTANT:
- Prefer minimal edits.
- Do NOT remove rules unless absolutely necessary.
- Preserve stakeholder intent.
- Preserve domain meaning.
- Make redundant rules logically distinguishable.

ALLOWED TRANSFORMATIONS:
1. Add contextual constraints.
2. Specialize conditions.
3. Refine vague predicates or measures.
4. Replace actions with distinguishable alternatives only when necessary.
5. Add defeaters only when useful.

INPUT:
{json.dumps(payload, indent=2)}

{PATCH_OUTPUT_FORMAT}
"""


def concern_prompt(rules, findings):
    payload = {
        "issue_type": "concern_or_insufficiency",
        "sleec_findings": findings,
        "rules": rules
    }

    return f"""
You are an expert in automated reasoning, SLEEC, normative requirements, and requirement refinement.

TASK:
Generate patch candidates to resolve SLEEC-detected concerns or insufficiencies.

IMPORTANT:
- Address each concern directly.
- Prefer refining existing rules before adding new rules.
- Add new rules only when necessary.
- Prefer defeaters when they can resolve the concern.
- Preserve original intent and domain meaning.
- Modify only the minimum necessary part.

ALLOWED TRANSFORMATIONS:
1. Add defeaters.
2. Negate problematic conditions.
3. Add contextual constraints.
4. Split broad rules.
5. Add a new rule only if existing rules cannot address the concern.

INPUT:
{json.dumps(payload, indent=2)}

{PATCH_OUTPUT_FORMAT}
"""


def purpose_prompt(rules, findings):
    payload = {
        "issue_type": "purpose_blocking_or_restrictiveness",
        "sleec_findings": findings,
        "rules": rules
    }

    return f"""
You are an expert in automated reasoning, SLEEC, normative requirements, and capability refinement.

TASK:
Generate patch candidates to resolve SLEEC-detected purpose blocking or restrictiveness.

IMPORTANT:
- Enable intended system capability.
- Preserve operational safety.
- Preserve stakeholder intent.
- Modify only restrictive components.
- Prefer purpose-aware defeaters before new events.

ALLOWED TRANSFORMATIONS:
1. Add purpose-aware defeaters.
2. Refine restrictive conditions.
3. Decompose broad actions into more specific actions.
4. Replace restrictive events with more distinguishable events only when necessary.
5. Refine event granularity.

INPUT:
{json.dumps(payload, indent=2)}

{PATCH_OUTPUT_FORMAT}
"""


def conflict_prompt(rules, findings):
    payload = {
        "issue_type": "conflict",
        "sleec_findings": findings,
        "rules": rules
    }

    return f"""
You are an expert in automated reasoning, SLEEC, normative requirements, and conflict resolution.

TASK:
Generate patch candidates to resolve SLEEC-detected conflicts.

IMPORTANT:
- Preserve operational intent.
- Preserve stakeholder intent.
- Maintain logical consistency.
- Prefer condition refinement and defeaters.
- Do NOT introduce unrelated behavior.
- Modify only the minimum necessary part.

ALLOWED TRANSFORMATIONS:
1. Refine conflicting conditions.
2. Add defeaters.
3. Add negated conflict conditions.
4. Propagate contextual constraints.
5. Introduce intermediary events only if necessary.

INPUT:
{json.dumps(payload, indent=2)}

{PATCH_OUTPUT_FORMAT}
"""


def situational_conflict_prompt(rules, findings):
    payload = {
        "issue_type": "situational_conflict",
        "sleec_findings": findings,
        "rules": rules
    }

    return f"""
You are an expert in automated reasoning, SLEEC, normative requirements, and situational conflict resolution.

TASK:
Generate patch candidates to resolve SLEEC-detected situational conflicts.

IMPORTANT:
- Use the SLEEC-highlighted situation.
- Refine triggering conditions using the conflict context.
- Prefer adding defeaters or contextual constraints.
- Preserve domain meaning.
- Preserve stakeholder intent.
- Avoid unnecessary new events or measures.

ALLOWED TRANSFORMATIONS:
1. Add defeaters.
2. Refine conditions using negated conflict context.
3. Make events or measures more distinguishable only when necessary.
4. Propagate constraints to avoid the same conflict.
5. Split semi-conflicting contexts.

INPUT:
{json.dumps(payload, indent=2)}

{PATCH_OUTPUT_FORMAT}
"""

def build_prompt(issue_type, rules, findings):

    if issue_type in ["redundancy", "redundancies"]:
        return redundancy_prompt(rules, findings)

    if issue_type in ["concern", "concerns"]:
        return concern_prompt(rules, findings)

    if issue_type in ["purpose", "purpose_blocking"]:
        return purpose_prompt(rules, findings)

    if issue_type in ["conflict", "conflicts"]:
        return conflict_prompt(rules, findings)

    if issue_type in ["situational_conflict", "situational_conflicts"]:
        return situational_conflict_prompt(rules, findings)

    raise ValueError(
        f"Unknown issue type: {issue_type}"
    )
