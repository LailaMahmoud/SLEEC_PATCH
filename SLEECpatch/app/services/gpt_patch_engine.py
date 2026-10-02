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

    def normalize_patch_schema(self, patch, issue_type, repair_operator):
        if isinstance(patch, dict) and "change" in patch:
            if patch.get("operation") != repair_operator:
                raise ValueError("The proposal changed the selected operator.")
            return {**patch, "source": "llm", "issue_type": issue_type}
        required_defaults = {
            "patch_id": "p_unknown",
            "issue_type": issue_type,
            "operation": repair_operator,
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
            "defeaters_added": 0,
        }

        normalized = dict(required_defaults)

        if isinstance(patch, dict):
            normalized.update(patch)

        normalized["source"] = "llm"
        normalized["issue_type"] = issue_type
        normalized["operation"] = repair_operator

        if not str(normalized.get("natural_language_explanation", "")).strip():
            normalized["natural_language_explanation"] = (
                "No explanation supplied by the LLM; review required."
            )

        for key in [
            "modification_cost",
            "new_events_added",
            "new_measures_added",
            "new_capabilities_added",
            "new_rules_added",
            "defeaters_added",
        ]:
            try:
                normalized[key] = int(normalized.get(key, 0) or 0)
            except (TypeError, ValueError):
                normalized[key] = 0



        return normalized

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

The repair operator has already been selected by SLEEC-PATCH.

Only instantiate the selected LLM-assisted semantic repair operator.
Generate only the missing semantic/syntactic element required by that operator.

Do not select another repair operator.
Do not decide whether the selected operator is applicable.
Do not claim that the generated candidate is formally correct or verified.
Do not claim that the targeted well-formedness issue has been eliminated.

Preserve the original stakeholder intent.
Do not modify unrelated parts of the specification.
Do not invent unsupported domain vocabulary.
Never invent SLEEC syntax or SLEEC keywords.

Always return valid raw JSON.
Never return markdown.

The generated output is a candidate repair.
Formal correctness is determined later by SLEEC-PATCH through
LEGOS-SLEEC re-analysis.
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

            return [
                self.normalize_patch_schema(
                    patch,
                    issue_type=issue_type,
                    repair_operator=repair_operator
                )
                for patch in parsed
            ]

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


    def assess_patch_quality(self, *args, **kwargs):
        """Compatibility only: ranking is quantitative and never calls an LLM."""
        return {"source": "removed", "reason": "Use PatchRanker lexicographic metrics."}


    def repair_patch_syntax(
        self,
        patch,
        syntax_error,
        original_sleec="",
        patched_sleec=""
    ):
        """
        Repair only malformed LLM patch JSON. This is never used for
        deterministic patches, preserving their script-only boundary.
        """
        prompt = f"""
The following LLM-generated SLEEC patch produced invalid SLEEC syntax.
Return one corrected raw JSON patch object only. Do not return markdown.

Rules:
- Preserve the same repair operation.
- Modify only the malformed fields needed to make the patch valid SLEEC.
- Do not rewrite the full specification.
- Keep the same target_rule_id unless it is clearly empty and inferable.

Syntax error:
{syntax_error}

Original patch JSON:
{json.dumps(patch, ensure_ascii=False, default=str)}

Patched SLEEC that failed:
{patched_sleec}

Original SLEEC:
{original_sleec}
"""

        response = _get_client().chat.completions.create(
            model=self.model,
            temperature=0,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You repair malformed SLEEC patch JSON. "
                        "Return valid raw JSON only."
                    )
                },
                {"role": "user", "content": prompt}
            ]
        )

        content = response.choices[0].message.content
        repaired = json.loads(self.clean_json(content))

        if isinstance(repaired, list):
            repaired = repaired[0] if repaired else {}

        merged = dict(patch)
        merged.update(repaired)
        merged["source"] = "llm"
        merged["operation"] = patch.get("operation", repaired.get("operation", ""))
        merged["syntax_repaired"] = True
        return merged

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
