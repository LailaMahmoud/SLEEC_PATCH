import pandas as pd
import os
from datetime import datetime
from services.patch_operation_engine import PatchOperationEngine
from services.nl_sleec_mapper import NLSLEECMapper
from services.sleec_detection_engine import SLEECDetectionEngine
from services.gpt_resolution_engine import GPTResolutionEngine
from services.patch_comparator import PatchComparator
from services.gpt_patch_engine import GPTPatchEngine



class SLEECResolutionManager:
    def __init__(self):
        self.mapper = NLSLEECMapper()
        self.detector = SLEECDetectionEngine()
        self.resolver = GPTResolutionEngine()
        self.comparator = PatchComparator()
        self.patch_operation_engine = PatchOperationEngine()
        self.gpt_patch_engine = GPTPatchEngine()







    def save_selected_patches(self, stakeholder, use_case, patches):
        folder = os.path.join("results", use_case, stakeholder)

        os.makedirs(folder, exist_ok=True)

        path = os.path.join(folder, "selected_patches.xlsx")

        df = pd.DataFrame(patches)

        df.to_excel(path, index=False)

        return path

    def approve(self, stakeholder, use_case):
        os.makedirs("results", exist_ok=True)

        path = os.path.join("results", "approvals.xlsx")

        row = {
            "timestamp": datetime.now(),
            "stakeholder": stakeholder,
            "use_case": use_case,
            "approved": True
        }

        if os.path.exists(path):
            df = pd.read_excel(path)
        else:
            df = pd.DataFrame()

        df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)

        df.to_excel(path, index=False)

        return path

    def compare_with_expert(self, expert_file, usc_rules):
        expert_rules = self.comparator.load_excel_rules(expert_file)

        return self.comparator.compare(
            expert_rules=expert_rules,
            usc_rules=usc_rules
        )
    

    def analyze_single(self, stakeholder, use_case, nl_rules):

        rules, mapping = self.mapper.parse_nl_rules(nl_rules)
        sleec_text = self.mapper.build_sleec(rules)

        detection_result = self.detector.run_text(sleec_text)

        structured = detection_result.get("structured", {})

        rules_json = []

        for r in rules:
            if isinstance(r, dict):
                rules_json.append({
                    "id": r.get("id"),
                    "condition": r.get("condition"),
                    "action": r.get("action"),
                    "defeater": r.get("defeater")
                })
            else:
                rules_json.append({
                    "id": r.id,
                    "condition": r.condition,
                    "action": r.action,
                    "defeater": r.defeater
                })

        patches = self.gpt_patch_engine.generate_all_patches(
            rules=rules_json,
            structured_findings=structured
        )

        return {
            "mode": "single",
            "stakeholder": stakeholder,
            "use_case": use_case,
            "rules": rules_json,
            "mapping": mapping,
            "sleec_text": sleec_text,
            "detections": structured,
            "patches": patches
        }

    def analyze_multiple(self, use_case, stakeholders_rules):

        all_rules = []
        stakeholder_rule_map = {}

        counter = 1

        for stakeholder_id, nl_rules in stakeholders_rules.items():

            stakeholder_rule_map[stakeholder_id] = []

            for rule in nl_rules:
                all_rules.append(rule)
                stakeholder_rule_map[stakeholder_id].append(
                    f"r{counter}"
                )
                counter += 1

        result = self.analyze_single(
            stakeholder="MULTI",
            use_case=use_case,
            nl_rules=all_rules
        )

        result["mode"] = "multiple"
        result["stakeholder_rule_map"] = stakeholder_rule_map
        result["stakeholders_rules"] = stakeholders_rules

        return result


    def apply_selected_patches(self, rules, patches):

        selected = [
            p for p in patches
            if p.get("selected")
        ]

        return self.patch_operation_engine.apply_patches(
            rules,
            selected
        )
    



