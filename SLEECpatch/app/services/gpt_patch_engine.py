import json
import re

from openai import OpenAI

from services.prompts import build_prompt, LLM_SEMANTIC_OPERATORS

# Lazily created so the module imports without an API key (diagnosis works
# key-free; the client is built on the first LLM call).
_client = None


def _get_client():
    global _client
    if _client is None:
        _client = OpenAI()
    return _client


class GPTPatchEngine:

    def __init__(self, model="gpt-4o-mini"):
        self.model = model

    def clean_json(self, text):
        text = text.strip()
        text = re.sub(r"```json", "", text)
        text = re.sub(r"```", "", text)
        return text.strip()

    def call_gpt(
        self,
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
                f"{repair_operator} is deterministic and must not be sent to GPT."
            )

        prompt = build_prompt(
            issue_type=issue_type,
            rules=rules,
            findings=findings,
            repair_operator=repair_operator,
            system_description=system_description,
            existing_events=existing_events,
            existing_measures=existing_measures,
            existing_responses=existing_responses
        )

        response = _get_client().chat.completions.create(
            model=self.model,
            temperature=0,
            messages=[
                {
                    "role": "system",
                    "content": """
You are an expert in normative requirements, SLEEC reasoning,
semantic repair, and stakeholder-centered resolution.

Only instantiate the selected LLM-assisted semantic repair operator.
Always return valid raw JSON.
Never return markdown.
"""
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ]
        )

        content = response.choices[0].message.content

        try:
            parsed = json.loads(self.clean_json(content))

            if isinstance(parsed, dict):
                parsed = [parsed]

            for patch in parsed:
                patch["source"] = "llm"
                patch["operation"] = repair_operator

            return parsed

        except Exception:
            return [{
                "patch_id": "parse_error",
                "source": "llm",
                "issue_type": issue_type,
                "operation": repair_operator,
                "target_rule_id": "",
                "original_rule": "",
                "proposed_rule": content,
                "natural_language_explanation": "GPT output was not valid JSON.",
                "modification_cost": 0,
                "new_events_added": 0,
                "new_measures_added": 0,
                "new_capabilities_added": 0,
                "new_rules_added": 0,
                "defeaters_added": 0
            }]

    def generate_all_patches(
        self,
        rules,
        structured_findings,
        repair_operators=None,
        system_description="",
        existing_events=None,
        existing_measures=None,
        existing_responses=None
    ):

        patches = []

        repair_operators = repair_operators or []

        mapping = {
            "redundancies": "redundancy",
            "concerns": "concern",
            "purpose_blocking": "purpose",
            "conflicts": "conflict",
            "situational_conflicts": "situational_conflict"
        }

        for key, issue_type in mapping.items():

            findings = structured_findings.get(key, [])

            if not findings:
                continue

            for operator in repair_operators:

                if operator not in LLM_SEMANTIC_OPERATORS:
                    continue

                generated = self.call_gpt(
                    issue_type=issue_type,
                    rules=rules,
                    findings=findings,
                    repair_operator=operator,
                    system_description=system_description,
                    existing_events=existing_events,
                    existing_measures=existing_measures,
                    existing_responses=existing_responses
                )

                patches.extend(generated)

        return patches