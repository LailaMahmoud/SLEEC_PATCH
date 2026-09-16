import json
import re

from openai import OpenAI

from services.prompts import build_prompt, LLM_SEMANTIC_OPERATORS, patch_quality_ranking_prompt

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

        if normalized.get("patch_id") == "not_applicable":
            normalized["operation"] = "none"

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

Only instantiate the selected LLM-assisted semantic repair operator.
Always return valid raw JSON.
Never return markdown.
Never invent SLEEC syntax or SLEEC keywords.
If a repair cannot be expressed with valid SLEEC rule syntax, return not_applicable.
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


    def assess_patch_quality(
        self,
        patch,
        system_description="",
        existing_events=None,
        existing_measures=None,
        existing_responses=None
    ):
        """
        Section C ranking assessment.

        This method is called only after formal verification. GPT does not
        decide correctness here; it scores semantic clarity and interpretability.
        """
        prompt = patch_quality_ranking_prompt(
            patch=patch,
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
                    "content": (
                        "You are a requirements-quality assessor. "
                        "The candidate repair has already passed formal verification. "
                        "Assess only semantic clarity and interpretability. "
                        "Return valid raw JSON only."
                    )
                },
                {"role": "user", "content": prompt}
            ]
        )

        content = response.choices[0].message.content

        try:
            result = json.loads(self.clean_json(content))
            semantic = float(result.get("semantic_clarity", 0))
            interpretability = float(result.get("interpretability", 0))

            return {
                "semantic_clarity": max(0, min(100, semantic)),
                "semantic_clarity_reason": str(
                    result.get("semantic_clarity_reason", "")
                ).strip(),
                "interpretability": max(0, min(100, interpretability)),
                "interpretability_reason": str(
                    result.get("interpretability_reason", "")
                ).strip(),
                "source": "llm"
            }
        except Exception as exc:
            return {
                "semantic_clarity": None,
                "semantic_clarity_reason": (
                    "LLM quality assessment could not be parsed."
                ),
                "interpretability": None,
                "interpretability_reason": str(exc),
                "source": "llm_error"
            }

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
