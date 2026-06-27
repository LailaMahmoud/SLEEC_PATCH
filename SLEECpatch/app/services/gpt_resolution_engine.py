import json
from openai import OpenAI

client = OpenAI()


class GPTResolutionEngine:
    def __init__(self, model="gpt-4o-mini"):
        self.model = model

    def generate_patches(self, issue_type, issues, rules, relationships=None):

        payload = {
            "issue_type": issue_type,
            "detected_issues": issues,
            "detected_sleec_relationships": relationships or [],
            "current_rules": rules
        }

        prompt = """
You are an expert in SLEEC, normative requirements, and prompt-based rule resolution.

IMPORTANT:
- SLEEC detected the issue.
- Your task is only to propose resolution patches.
- Preserve stakeholder intent.
- Prefer minimal modification.
- Prefer fewer edited rules.
- Prefer fewer new rules.
- Prefer fewer defeaters.
- Do not introduce new events unless necessary.
- Translate every patch into natural language for stakeholders.
- The proposed_rule MUST be different from the original_rule.
- The proposed_rule MUST NOT be empty.
- Do NOT only explain the change; actually rewrite the rule.

Allowed operations:
- edit
- add
- delete
- add_defeater
- refine_condition
- refine_action

Return ONLY a raw JSON array.
Each patch MUST have exactly this structure:

[
  {
    "patch_id": "p1",
    "issue_type": "conflicts",
    "rule_ids": ["r1"],
    "operation": "edit",
    "original_rule": "when PatientFallen then CallSupport",
    "proposed_rule": "when PatientFallen and EmergencyDetected then CallSupport",
    "natural_language_explanation": "This patch makes the triggering condition more specific.",
    "modification_cost": 1,
    "new_events_added": 0,
    "defeaters_added": 0
  }
]

INPUT:
""" + json.dumps(payload, indent=2)

        response = client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": prompt
                }
            ],
            temperature=0
        )

        text = response.choices[0].message.content

        try:
            patches = json.loads(text)
        except Exception:
            print("GPT returned invalid JSON:")
            print(text)
            return []

        clean_patches = []

        for i, p in enumerate(patches, start=1):
            proposed_rule = (
                p.get("proposed_rule")
                or p.get("patch")
                or p.get("resolution")
                or p.get("suggested_rule")
                or ""
            )

            if not proposed_rule.strip():
                continue

            clean_patches.append({
                "patch_id": p.get("patch_id", f"p{i}"),
                "issue_type": p.get("issue_type", issue_type),
                "rule_ids": p.get("rule_ids", []),
                "operation": p.get("operation", "edit"),
                "original_rule": p.get("original_rule", ""),
                "proposed_rule": proposed_rule,
                "natural_language_explanation": p.get("natural_language_explanation", ""),
                "modification_cost": p.get("modification_cost", 1),
                "new_events_added": p.get("new_events_added", 0),
                "defeaters_added": p.get("defeaters_added", 0),
                "selected": False
            })

        return clean_patches