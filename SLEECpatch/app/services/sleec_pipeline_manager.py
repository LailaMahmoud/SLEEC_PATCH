import json
import re
from openai import OpenAI

from services.sleec_detection_engine import SLEECDetectionEngine
from services.gpt_patch_engine import GPTPatchEngine


class SLEECPipelineManager:

    def __init__(self, model="gpt-4o-mini"):
        self.client = OpenAI()
        self.model = model
        self.detector = SLEECDetectionEngine()
        self.gpt_patch_engine = GPTPatchEngine()

    def clean_json(self, text):
        text = text.strip()
        text = re.sub(r"```json", "", text)
        text = re.sub(r"```", "", text)
        return text.strip()

    def clean_symbol(self, text):
        if not text:
            return ""

        text = str(text).strip()
        text = text.replace("{", "").replace("}", "")
        text = re.sub(r"\s+", "", text)
        return text

    def nl_to_sleec(self, nl_rules):
        rules = []

        for i, line in enumerate(nl_rules, start=1):
            line = line.strip()

            if not line:
                continue

            match = re.search(
                r"^(?:r\d+\s+)?when\s+(.+?)\s+then\s+(.+?)(?:\s+unless\s+\{?(.+?)\}?)?$",
                line,
                re.IGNORECASE
            )

            if not match:
                continue

            condition = self.clean_symbol(match.group(1))
            action = self.clean_symbol(match.group(2))
            defeater = self.clean_symbol(match.group(3)) if match.group(3) else ""

            rules.append({
                "id": f"r{len(rules) + 1}",
                "condition": condition,
                "action": action,
                "defeater": defeater
            })

        events = set()
        measures = set()

        for r in rules:
            condition = r["condition"]
            action = r["action"]

            if condition.lower().startswith("not"):
                condition = condition[3:]

            if action.lower().startswith("not"):
                action = action[3:]

            events.add(condition)
            events.add(action)

            if r["defeater"]:
                measures.add(r["defeater"])

        lines = ["def_start"]

        for e in sorted(events):
            if e:
                lines.append(f"event {e}")

        for m in sorted(measures):
            if m:
                lines.append(f"measure {m}:boolean")

        lines.append("def_end")
        lines.append("")
        lines.append("rule_start")

        for r in rules:
            rule = f'{r["id"]} when {r["condition"]} then {r["action"]}'

            if r["defeater"]:
                rule += f' unless {{{r["defeater"]}}}'

            lines.append(rule)

        lines.append("rule_end")

        return {
            "rules": rules,
            "sleec_text": "\n".join(lines)
        }


    def multi_nl_to_sleec(self, stakeholders_rules):
        all_rules = []

        for stakeholder_id, rules in stakeholders_rules.items():
            for r in rules:
                all_rules.append(r)

        result = self.nl_to_sleec(all_rules)
        result["stakeholders_rules"] = stakeholders_rules

        return result


    def extract_symbols(self, sleec_text):
        events = []
        measures = []

        for line in sleec_text.splitlines():
            line = line.strip()

            if line.startswith("event "):
                events.append(line.replace("event ", "").strip())

            elif line.startswith("measure "):
                measures.append(line.replace("measure ", "").strip())

        return {
            "events": events,
            "measures": measures
        }

    def extract_semantic_relations(self, sleec_text):
        symbols = self.extract_symbols(sleec_text)

        prompt = f"""
You are extracting semantic relations for SLEEC normative requirements.

Allowed event-event relations:
1. hypernym
2. equal
3. isContradictoryWith
4. happensBefore

Allowed measure-measure relations:
1. imply
2. mutuallyExclusive
3. opposite
4. equal

Allowed event-measure relations:
1. induces
2. forbids

Return ONLY a JSON array.
Each object must have:
id, source, relation, target, explanation, accepted

Use accepted=false by default.

SLEEC:
{sleec_text}

Symbols:
{json.dumps(symbols, indent=2)}
"""

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0
            )

            content = self.clean_json(response.choices[0].message.content)
            relations = json.loads(content)

            for i, r in enumerate(relations, start=1):
                r["id"] = r.get("id") or f"rel{i}"
                r["accepted"] = False

            return relations

        except Exception as e:
            return [{
                "id": "rel_error",
                "source": "",
                "relation": "error",
                "target": "",
                "explanation": str(e),
                "accepted": False
            }]

    def validate_relations(self, relations):
        return [
            r for r in relations
            if r.get("accepted") is True
        ]

    def add_relations_to_sleec(self, sleec_text, relations):
        if not relations:
            return sleec_text

        relation_lines = [
            "",
            "// validated semantic relations"
        ]

        for r in relations:
            relation_lines.append(
                f'// {r.get("source")} {r.get("relation")} {r.get("target")}'
            )

        return sleec_text + "\n" + "\n".join(relation_lines)

    def analyse_with_relations(self, sleec_text, relations):

        validated_relations = self.validate_relations(relations)

        enriched_sleec = self.add_relations_to_sleec(
            sleec_text,
            validated_relations
        )

        result = self.detector.run_text(enriched_sleec)

        return {
            "validated_relations": validated_relations,
            "enriched_sleec": enriched_sleec,
            "detections": result.get("detections", {}),
            "structured": result.get("structured", {})
        }

    def count_issues(self, structured):
        return sum(
            len(v)
            for v in structured.values()
            if isinstance(v, list)
        )

    def generate_patchess(self, sleec_text, issues, relations):
        validated_relations = self.validate_relations(relations)

        prompt = f"""
You are repairing SLEEC normative requirement rules.

Generate minimal resolution patches.

Allowed operations:
- edit_rule
- add_defeater
- refine_condition
- refine_action
- delete_redundant_rule
- add_rule

Return ONLY JSON array.
Each object must include:
id, issue_type, target_rule_id, operation, original_rule, proposed_rule, explanation, valid, selected

Use valid=false and selected=false by default.

SLEEC:
{sleec_text}

Validated relations:
{json.dumps(validated_relations, indent=2)}

Detected issues:
{json.dumps(issues, indent=2)}
"""

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0
            )

            content = self.clean_json(response.choices[0].message.content)
            patches = json.loads(content)

            for i, p in enumerate(patches, start=1):
                p["id"] = p.get("id") or f"p{i}"
                p["valid"] = False
                p["selected"] = False

            return patches

        except Exception as e:
            return [{
                "id": "p_error",
                "issue_type": "error",
                "target_rule_id": "",
                "operation": "none",
                "original_rule": "",
                "proposed_rule": "",
                "explanation": str(e),
                "valid": False,
                "selected": False
            }]

    
    def generate_patches(self, sleec_text, issues, relations):

        rules_json = self.sleec_text_to_rules_json(sleec_text)

        patches = self.gpt_patch_engine.generate_all_patches(
            rules=rules_json,
            structured_findings=issues
        )

        for i, p in enumerate(patches, start=1):
            p.setdefault("id", f"p{i}")
            p.setdefault("valid", False)
            p.setdefault("selected", False)

        return patches
    
    def sleec_text_to_rules_json(self, sleec_text):
        rules = []

        inside_rules = False

        for line in sleec_text.splitlines():
            line = line.strip()

            if line == "rule_start":
                inside_rules = True
                continue

            if line == "rule_end":
                inside_rules = False
                continue

            if not inside_rules or not line:
                continue

            match = re.search(
                r"^(r\d+)\s+when\s+(.+?)\s+then\s+(.+?)(?:\s+unless\s+\{?(.+?)\}?)?$",
                line,
                re.IGNORECASE
            )

            if match:
                rules.append({
                    "id": match.group(1),
                    "condition": match.group(2).strip(),
                    "action": match.group(3).strip(),
                    "defeater": match.group(4).strip() if match.group(4) else ""
                })

        return rules
    def apply_patch_to_text(self, sleec_text, patch):
        original_rule = patch.get("original_rule", "")
        proposed_rule = patch.get("proposed_rule", "")
        target_rule_id = patch.get("target_rule_id", "")
        operation = patch.get("operation", "")

        if operation == "delete_redundant_rule" and target_rule_id:
            lines = []
            for line in sleec_text.splitlines():
                if not line.strip().startswith(target_rule_id + " "):
                    lines.append(line)
            return "\n".join(lines)

        if original_rule and proposed_rule and original_rule in sleec_text:
            return sleec_text.replace(original_rule, proposed_rule)

        if target_rule_id and proposed_rule:
            lines = []
            replaced = False

            for line in sleec_text.splitlines():
                if line.strip().startswith(target_rule_id + " "):
                    lines.append(proposed_rule)
                    replaced = True
                else:
                    lines.append(line)

            if replaced:
                return "\n".join(lines)

        if operation == "add_rule" and proposed_rule:
            return sleec_text.replace(
                "rule_end",
                proposed_rule + "\nrule_end"
            )

        return sleec_text

    def validate_patches(self, sleec_text, patches, relations):
        original_analysis = self.analyse_with_relations(
            sleec_text,
            relations
        )

        original_count = self.count_issues(
            original_analysis.get("structured", {})
        )

        validated = []

        for patch in patches:
            patched_sleec = self.apply_patch_to_text(
                sleec_text,
                patch
            )

            patched_analysis = self.analyse_with_relations(
                patched_sleec,
                relations
            )

            patched_count = self.count_issues(
                patched_analysis.get("structured", {})
            )

            patch["patched_sleec"] = patched_sleec
            patch["validation"] = patched_analysis
            patch["valid"] = patched_count < original_count

            validated.append(patch)

        return validated

    def select_patch(self, sleec_text, patches, patch_id):
        selected = None
        patch_id = str(patch_id)

        clean_patches = []

        for p in patches:
            if p.get("deleted") is True:
                continue

            current_id = str(p.get("id"))

            p["selected"] = current_id == patch_id

            if p["selected"]:
                selected = p

            clean_patches.append(p)

        if selected is None:
            return {
                "selected_patch": None,
                "patches": clean_patches,
                "final_sleec": "",
                "error": f"No patch found with id {patch_id}"
            }

        final_sleec = self.apply_patch_to_text(
            sleec_text,
            selected
        )

        selected["patched_sleec"] = final_sleec

        return {
            "selected_patch": selected,
            "patches": clean_patches,
            "final_sleec": final_sleec
        }