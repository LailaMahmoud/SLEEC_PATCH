import re
import time
import os
from services.sleec_detection_engine import SLEECDetectionEngine
from services.gpt_patch_engine import GPTPatchEngine
from services.sleec_patch_evaluation_store import SLEECPatchEvaluationStore
from services.repair_operator_selector import RepairOperatorSelector
from services.deterministic_repair_engine import DeterministicRepairEngine
from services.patch_ranker import PatchRanker


class SLEECPatchWorkbenchEngine:

    def __init__(self):
        self.detector = SLEECDetectionEngine()
        self.gpt_patch_engine = GPTPatchEngine()
        self.store = SLEECPatchEvaluationStore()

        self.operator_selector = RepairOperatorSelector()
        self.deterministic_engine = DeterministicRepairEngine()
        self.patch_ranker = PatchRanker()

    def diagnose(self, sleec_text):
        result = self.detector.run_text(sleec_text)
        result = self.detector.run_text(sleec_text)

        print("\n========== DETECTOR OUTPUT ==========")
        print(result)
        print("====================================\n")
        structured = result.get("structured", {})
        detections = result.get("detections", {})

        issues = []

        original_rules_by_type = structured.get("original_rules_by_type", {})

        for issue_type, items in structured.items():

            if issue_type == "original_rules_by_type":
                continue

            for index, item in enumerate(items, start=1):

                original_rules = []

                if issue_type in original_rules_by_type:
                    rules_list = original_rules_by_type.get(issue_type, [])

                    if index - 1 < len(rules_list):
                        original_rules = rules_list[index - 1]

                issues.append({
                    "id": f"{issue_type}_{index}",
                    "issue_type": issue_type,
                    "value": item,
                    "original_rules": original_rules,
                    "source": "sleec"
                })



        if not issues:
            fallback = self.fallback_wfi_detection(sleec_text)

            for issue_type, items in fallback.items():
                for index, item in enumerate(items, start=1):
                    issues.append({
                        "id": f"{issue_type}_{index}",
                        "issue_type": issue_type,
                        "value": item,
                        "source": "fallback"
                    })

            structured.update(fallback)

        return {
            "status": "OK",
            "sleec_text": sleec_text,
            "structured": structured,
            "detections": detections,
            "issues": issues,
            "issue_count": len(issues)
        }

    def fallback_wfi_detection(self, sleec_text):
        rules = self.sleec_text_to_rules_json(sleec_text)

        result = {
            "conflicts": [],
            "redundancies": [],
            "concerns": [],
            "purpose_blocking": [],
            "situational_conflicts": []
        }

        seen = {}

        for r in rules:
            key = (
                r.get("condition", "").strip(),
                r.get("action", "").strip(),
                r.get("defeater", "").strip()
            )

            if key in seen:
                result["redundancies"].append(
                    self.rule_to_text(seen[key]) + "\n" + self.rule_to_text(r)
                )
            else:
                seen[key] = r

        for i, r1 in enumerate(rules):
            for r2 in rules[i + 1:]:
                same_condition = (
                    r1.get("condition", "").strip()
                    ==
                    r2.get("condition", "").strip()
                )

                opposite_actions = self.opposite_actions(
                    r1.get("action", ""),
                    r2.get("action", "")
                )

                if same_condition and opposite_actions:
                    result["conflicts"].append(
                        self.rule_to_text(r1) + "\n" + self.rule_to_text(r2)
                    )

        return result

    def opposite_actions(self, a, b):
        a = str(a).strip()
        b = str(b).strip()

        return (
            a == f"not {b}"
            or b == f"not {a}"
            or a == f"not{b}"
            or b == f"not{a}"
        )

    def rule_to_text(self, rule):
        text = f'{rule["id"]} when {rule["condition"]} then {rule["action"]}'

        if rule.get("defeater"):
            text += f' unless {{{rule["defeater"]}}}'

        
        return text
    
    def generate_verified_patches(
    self,
    use_case,
    sleec_text,
    issue,
    max_attempts=1
):
        start_total = time.time()

        original_analysis = self.detector.run_text(sleec_text)
        original_structured = original_analysis.get("structured", {})

        issue_type = issue.get("issue_type", "")
        issue_key = issue_type

        if issue_type == "redundancy":
            issue_key = "redundancies"
        elif issue_type == "conflict":
            issue_key = "conflicts"
        elif issue_type == "concern":
            issue_key = "concerns"
        elif issue_type == "purpose":
            issue_key = "purpose_blocking"
        elif issue_type == "situational_conflict":
            issue_key = "situational_conflicts"

        selected_issue_value = issue.get("value", "")

        verified_patches = []
        failed_patch_count = 0

        deterministic_candidates = []
        llm_candidates = []

        generation_time = 0
        validation_time = 0
        attempts = 0

        rules_json = self.sleec_text_to_rules_json(sleec_text)
        operator_plan = self.operator_selector.select(issue_key)

        print("\n========== REPAIR OPERATOR SELECTION ==========")
        print("Issue Type:", issue_key)
        print("Deterministic operators:", operator_plan.get("deterministic", []))
        print("LLM operators:", operator_plan.get("llm", []))
        print("==============================================\n")

        selected_findings = {
            issue_key: [selected_issue_value]
        }

        # -------------------------------
        # GPT is called ONCE per issue
        # -------------------------------

        semantic_ops = operator_plan.get("llm", [])
        llm_patches = []

        if semantic_ops:
            start_generation = time.time()

            print(">>> Calling GPT with operators:", semantic_ops)

            llm_patches = self.gpt_patch_engine.generate_all_patches(
                rules=rules_json,
                structured_findings=selected_findings,
                repair_operators=semantic_ops
            )

            for i, p in enumerate(llm_patches, start=1):
                p["patch_id"] = f"g{i}"
                p["id"] = f"g{i}"

            llm_candidates.extend(llm_patches)

            generation_time += time.time() - start_generation

        seen_candidate_signatures = set()
        seen_verified_signatures = set()

        # -------------------------------
        # Multiple attempts
        # -------------------------------

        while attempts <= max_attempts:

            attempts += 1

            start_generation = time.time()

            deterministic_patches = self.deterministic_engine.generate(
                issue_type=issue_key,
                selected_issue=selected_issue_value,
                rules=rules_json,
                operators=operator_plan.get("deterministic", [])
            )

            generation_time += time.time() - start_generation

            for p in deterministic_patches:
                sig = (
                    p.get("operation"),
                    p.get("target_rule_id"),
                    p.get("proposed_rule"),
                    p.get("missing_element")
                )

                if sig not in seen_candidate_signatures:
                    deterministic_candidates.append(p)
                    seen_candidate_signatures.add(sig)

            patches = deterministic_patches + llm_patches

            for patch in patches:
                
                normalized_patch = self.normalize_patch(patch, sleec_text)

                if normalized_patch.get("patch_id") == "not_applicable":
                    failed_patch_count += 1
                    continue

                patch_signature = (
                    normalized_patch.get("operation"),
                    normalized_patch.get("target_rule_id"),
                    normalized_patch.get("proposed_rule"),
                    normalized_patch.get("missing_element")
                )

                if patch_signature in seen_verified_signatures:
                    continue

                patched_sleec = self.apply_patch_to_text(
                    sleec_text,
                    normalized_patch
                )

                start_validation = time.time()

                new_analysis = self.detector.run_text(patched_sleec)
                new_structured = new_analysis.get("structured", {})

                validation_time += time.time() - start_validation

                target_fixed = self.target_issue_fixed(
                    issue_key,
                    selected_issue_value,
                    original_structured,
                    new_structured
                )

                no_new_violations = (
                    self.count_issues(new_structured)
                    <=
                    self.count_issues(original_structured)
                )

                print("--------------------------------")
                print("ATTEMPT:", attempts)
                print("SOURCE:", normalized_patch.get("source"))
                print("OPERATION:", normalized_patch.get("operation"))
                print("TARGET FIXED:", target_fixed)
                print("NO NEW VIOLATIONS:", no_new_violations)
                print("--------------------------------")

                if target_fixed and no_new_violations:
                    normalized_patch["verified"] = True
                    normalized_patch["patched_sleec"] = patched_sleec
                    normalized_patch["validation_result"] = new_structured
                    normalized_patch["attempt"] = attempts

                    verified_patches.append(normalized_patch)
                    seen_verified_signatures.add(patch_signature)

                else:
                    failed_patch_count += 1

        total_time = time.time() - start_total

        verified_patches = self.patch_ranker.rank(verified_patches)
        output_file = self.build_final_sleecpatch_file(
        use_case,
        sleec_text,
        verified_patches
        )

        log = {
            "use_case": use_case,
            "issue_id": issue.get("id", ""),
            "issue_type": issue_key,
            "attempts": attempts,
            "max_attempts": max_attempts,
            "failed_patch_count": failed_patch_count,
            "verified_patch_count": len(verified_patches),
            "generation_time_seconds": round(generation_time, 3),
            "validation_time_seconds": round(validation_time, 3),
            "total_time_seconds": round(total_time, 3),
            "successful": len(verified_patches) > 0
        }

        for patch in verified_patches:

            metrics = self.patch_metrics(patch)

            self.store.save_result({
                "use_case": use_case,
                "issue_id": issue.get("id", ""),
                "issue_type": issue_key,
                "selected_issue": selected_issue_value,

                "attempts": attempts,
                "failed_patch_count": failed_patch_count,
                "verified_patch_count": len(verified_patches),

                "generation_time_seconds": round(generation_time, 3),
                "validation_time_seconds": round(validation_time, 3),
                "total_time_seconds": round(total_time, 3),

                "patch_id": patch.get("patch_id", patch.get("id", "")),
                "operation": patch.get("operation", ""),
                "source": patch.get("source", "unknown"),
                "rank": patch.get("rank", 0),
                "ranking_score": patch.get("ranking_score", 0),

                "target_rule_id": patch.get("target_rule_id", ""),
                "original_rule": patch.get("original_rule", ""),
                "proposed_rule": patch.get("proposed_rule", ""),
                "natural_language_explanation": patch.get(
                    "natural_language_explanation",
                    ""
                ),
                "patched_sleec": patch.get("patched_sleec", ""),

                "rules_modified": metrics["rules_modified"],
                "rules_added": metrics["rules_added"],
                "rules_deleted": metrics["rules_deleted"],
                "defeaters_added": metrics["defeaters_added"],
                "conditions_refined": metrics["conditions_refined"],
                "actions_refined": metrics["actions_refined"],
                "capabilities_refined": metrics["capabilities_refined"],

                "verified": True,

                "expert_similarity": 0,
                "expert_match": False,
                "requires_social_scientist_review": False
            })

        return {
            "status": "OK",
            "selected_issue": issue,
            "repair_operators": operator_plan,
            "deterministic_candidates": deterministic_candidates,
            "llm_candidates": llm_candidates,
            "verified_patches": verified_patches,
            "generated_file": output_file,

            "log": log
        }


    def generate_verified_patchese(
    self,
    use_case,
    sleec_text,
    issue,
    max_attempts=1
):
        start_total = time.time()

        original_analysis = self.detector.run_text(sleec_text)
        original_structured = original_analysis.get("structured", {})

        issue_type = issue.get("issue_type", "")
        issue_key = issue_type

        if issue_type == "redundancy":
            issue_key = "redundancies"
        elif issue_type == "conflict":
            issue_key = "conflicts"
        elif issue_type == "concern":
            issue_key = "concerns"
        elif issue_type == "purpose":
            issue_key = "purpose_blocking"
        elif issue_type == "situational_conflict":
            issue_key = "situational_conflicts"

        selected_issue_value = issue.get("value", "")

        verified_patches = []
        failed_patch_count = 0

        deterministic_candidates = []
        llm_candidates = []

        generation_time = 0
        validation_time = 0
        attempts = 1

        rules_json = self.sleec_text_to_rules_json(sleec_text)
        operator_plan = self.operator_selector.select(issue_key)

        print("\n========== REPAIR OPERATOR SELECTION ==========")
        print("Issue Type:", issue_key)
        print("Deterministic operators:", operator_plan.get("deterministic", []))
        print("LLM operators:", operator_plan.get("llm", []))
        print("==============================================\n")

        selected_findings = {
            issue_key: [selected_issue_value]
        }

        start_generation = time.time()

        deterministic_patches = self.deterministic_engine.generate(
            issue_type=issue_key,
            selected_issue=selected_issue_value,
            rules=rules_json,
            operators=operator_plan.get("deterministic", [])
        )

        deterministic_candidates.extend(deterministic_patches)

        semantic_ops = operator_plan.get("llm", [])
        llm_patches = []

        if semantic_ops:
            print(">>> Calling GPT with operators:", semantic_ops)

            llm_patches = self.gpt_patch_engine.generate_all_patches(
                rules=rules_json,
                structured_findings=selected_findings,
                repair_operators=semantic_ops
            )

            for i, p in enumerate(llm_patches, start=1):
                p["patch_id"] = f"g{i}"
                p["id"] = f"g{i}"

            llm_candidates.extend(llm_patches)

        generation_time += time.time() - start_generation

        # deterministic first, then GPT
        patches = deterministic_patches + llm_patches

        for patch in patches:
            normalized_patch = self.normalize_patch(patch, sleec_text)

            if normalized_patch.get("patch_id") == "not_applicable":
                failed_patch_count += 1
                continue

            patch_signature = (
                normalized_patch.get("operation"),
                normalized_patch.get("target_rule_id"),
                normalized_patch.get("proposed_rule"),
                normalized_patch.get("missing_element")
            )

            duplicate = any(
                (
                    vp.get("operation"),
                    vp.get("target_rule_id"),
                    vp.get("proposed_rule"),
                    vp.get("missing_element")
                ) == patch_signature
                for vp in verified_patches
            )

            if duplicate:
                continue

            patched_sleec = self.apply_patch_to_text(
                sleec_text,
                normalized_patch
            )

            start_validation = time.time()

            new_analysis = self.detector.run_text(patched_sleec)
            new_structured = new_analysis.get("structured", {})

            validation_time += time.time() - start_validation

            target_fixed = self.target_issue_fixed(
                issue_key,
                selected_issue_value,
                original_structured,
                new_structured
            )

            no_new_violations = (
                self.count_issues(new_structured)
                <=
                self.count_issues(original_structured)
            )

            print("--------------------------------")
            print("SOURCE:", normalized_patch.get("source"))
            print("OPERATION:", normalized_patch.get("operation"))
            print("TARGET FIXED:", target_fixed)
            print("NO NEW VIOLATIONS:", no_new_violations)
            print("--------------------------------")

            if target_fixed and no_new_violations:
                normalized_patch["verified"] = True
                normalized_patch["patched_sleec"] = patched_sleec
                normalized_patch["validation_result"] = new_structured
                normalized_patch["attempt"] = attempts

                verified_patches.append(normalized_patch)
            else:
                failed_patch_count += 1

        total_time = time.time() - start_total

        verified_patches = self.patch_ranker.rank(verified_patches)

        log = {
            "use_case": use_case,
            "issue_id": issue.get("id", ""),
            "issue_type": issue_key,
            "attempts": attempts,
            "max_attempts": max_attempts,
            "failed_patch_count": failed_patch_count,
            "verified_patch_count": len(verified_patches),
            "generation_time_seconds": round(generation_time, 3),
            "validation_time_seconds": round(validation_time, 3),
            "total_time_seconds": round(total_time, 3),
            "successful": len(verified_patches) > 0
        }

        for patch in verified_patches:
            metrics = self.patch_metrics(patch)

            self.store.save_result({
                "use_case": use_case,
                "issue_id": issue.get("id", ""),
                "issue_type": issue_key,
                "selected_issue": selected_issue_value,

                "attempts": attempts,
                "failed_patch_count": failed_patch_count,
                "verified_patch_count": len(verified_patches),

                "generation_time_seconds": round(generation_time, 3),
                "validation_time_seconds": round(validation_time, 3),
                "total_time_seconds": round(total_time, 3),

                "patch_id": patch.get("patch_id", patch.get("id", "")),
                "operation": patch.get("operation", ""),
                "source": patch.get("source", "unknown"),
                "target_rule_id": patch.get("target_rule_id", ""),
                "original_rule": patch.get("original_rule", ""),
                "proposed_rule": patch.get("proposed_rule", ""),
                "natural_language_explanation": patch.get("natural_language_explanation", ""),
                "patched_sleec": patch.get("patched_sleec", ""),
                "rank": patch.get("rank", 0),
                "ranking_score": patch.get("ranking_score", 0),

                "target_rule_id": patch.get("target_rule_id", ""),
                "original_rule": patch.get("original_rule", ""),
                "proposed_rule": patch.get("proposed_rule", ""),
                "natural_language_explanation": patch.get(
                    "natural_language_explanation",
                    ""
                ),

                "rules_modified": metrics["rules_modified"],
                "rules_added": metrics["rules_added"],
                "rules_deleted": metrics["rules_deleted"],
                "defeaters_added": metrics["defeaters_added"],
                "conditions_refined": metrics["conditions_refined"],
                "actions_refined": metrics["actions_refined"],
                "capabilities_refined": metrics["capabilities_refined"],

                "verified": True,

                "expert_similarity": 0,
                "expert_match": False,
                "requires_social_scientist_review": False
            })

        return {
            "status": "OK",
            "selected_issue": issue,
            "repair_operators": operator_plan,
            "deterministic_candidates": deterministic_candidates,
            "llm_candidates": llm_candidates,
            "verified_patches": verified_patches,
            "log": log
        }

    def generate_verified_patchess(
        self,
        use_case,
        sleec_text,
        issue,
        max_attempts=7
    ):
        start_total = time.time()

        original_analysis = self.detector.run_text(sleec_text)
        original_structured = original_analysis.get("structured", {})

        issue_type = issue.get("issue_type", "")
        issue_key = issue_type

        if issue_type == "redundancy":
            issue_key = "redundancies"
        elif issue_type == "conflict":
            issue_key = "conflicts"
        elif issue_type == "concern":
            issue_key = "concerns"
        elif issue_type == "purpose":
            issue_key = "purpose_blocking"
        elif issue_type == "situational_conflict":
            issue_key = "situational_conflicts"

        selected_issue_value = issue.get("value", "")

        verified_patches = []
        failed_patch_count = 0
        deterministic_candidates = []
        llm_candidates = []

        generation_time = 0
        validation_time = 0
        attempts = 0

        rules_json = self.sleec_text_to_rules_json(sleec_text)
        operator_plan = self.operator_selector.select(issue_key)

        print("\n========== REPAIR OPERATOR SELECTION ==========")
        print("Issue Type:", issue_key)
        print("Deterministic operators:", operator_plan.get("deterministic", []))
        print("LLM operators:", operator_plan.get("llm", []))
        print("==============================================\n")

        selected_findings = {
            issue_key: [selected_issue_value]
        }
        semantic_ops = operator_plan.get("llm", [])
        llm_patches = []

        if semantic_ops:
            print(">>> Calling GPT with operators:", semantic_ops)

            llm_patches = self.gpt_patch_engine.generate_all_patches(
                rules=rules_json,
                structured_findings=selected_findings,
                repair_operators=semantic_ops
            )
            llm_candidates.extend(llm_patches)

            for i, p in enumerate(llm_patches, start=1):
                p["patch_id"] = f"g{i}"
                p["id"] = f"g{i}"

        while attempts < max_attempts :
            attempts += 1

            start_generation = time.time()

            deterministic_patches = self.deterministic_engine.generate(
                issue_type=issue_key,
                selected_issue=selected_issue_value,
                rules=rules_json,
                operators=operator_plan.get("deterministic", [])
            )
            deterministic_candidates.extend(deterministic_patches)
                     
            patches =  deterministic_patches+llm_patches
            generation_time += time.time() - start_generation

            for patch in patches:
                normalized_patch = self.normalize_patch(patch, sleec_text)

                if normalized_patch.get("patch_id") == "not_applicable":
                    failed_patch_count += 1
                    continue

                patch_signature = (
                    normalized_patch.get("operation"),
                    normalized_patch.get("target_rule_id"),
                    normalized_patch.get("proposed_rule"),
                    normalized_patch.get("missing_element")
                )

                duplicate = any(
                    (
                        vp.get("operation"),
                        vp.get("target_rule_id"),
                        vp.get("proposed_rule"),
                        vp.get("missing_element")
                    ) == patch_signature
                    for vp in verified_patches
                )

                if duplicate:
                    continue

                patched_sleec = self.apply_patch_to_text(
                    sleec_text,
                    normalized_patch
                )

                start_validation = time.time()

                new_analysis = self.detector.run_text(patched_sleec)
                new_structured = new_analysis.get("structured", {})

                validation_time += time.time() - start_validation

                target_fixed = self.target_issue_fixed(
                    issue_key,
                    selected_issue_value,
                    original_structured,
                    new_structured
                )

                no_new_violations = (
                    self.count_issues(new_structured)
                    <=
                    self.count_issues(original_structured)
                )
                print("--------------------------------")
                print("SOURCE:", normalized_patch.get("source"))
                print("OPERATION:", normalized_patch.get("operation"))
                print("TARGET FIXED:", target_fixed)
                print("NO NEW VIOLATIONS:", no_new_violations)
                print("--------------------------------")

                if target_fixed and no_new_violations:
                    normalized_patch["verified"] = True
                    normalized_patch["patched_sleec"] = patched_sleec
                    normalized_patch["validation_result"] = new_structured
                    normalized_patch["attempt"] = attempts

                    verified_patches.append(normalized_patch)

                    if len(verified_patches) >= 3:
                        break
                else:
                    failed_patch_count += 1

        total_time = time.time() - start_total

        verified_patches = self.patch_ranker.rank(verified_patches)

        log = {
            "use_case": use_case,
            "issue_id": issue.get("id", ""),
            "issue_type": issue_key,
            "attempts": attempts,
            "max_attempts": max_attempts,
            "failed_patch_count": failed_patch_count,
            "verified_patch_count": len(verified_patches),
            "generation_time_seconds": round(generation_time, 3),
            "validation_time_seconds": round(validation_time, 3),
            "total_time_seconds": round(total_time, 3),
            "successful": len(verified_patches) > 0
        }

        for patch in verified_patches:
            metrics = self.patch_metrics(patch)

            self.store.save_result({
                "use_case": use_case,
                "issue_id": issue.get("id", ""),
                "issue_type": issue_key,
                "selected_issue": selected_issue_value,

                "attempts": attempts,
                "failed_patch_count": failed_patch_count,
                "verified_patch_count": len(verified_patches),

                "generation_time_seconds": round(generation_time, 3),
                "validation_time_seconds": round(validation_time, 3),
                "total_time_seconds": round(total_time, 3),

                "patch_id": patch.get("patch_id", patch.get("id", "")),
                "operation": patch.get("operation", ""),
                "source": patch.get("source", "unknown"),
                "rank": patch.get("rank", 0),
                "ranking_score": patch.get("ranking_score", 0),

                "rules_modified": metrics["rules_modified"],
                "rules_added": metrics["rules_added"],
                "rules_deleted": metrics["rules_deleted"],
                "defeaters_added": metrics["defeaters_added"],
                "conditions_refined": metrics["conditions_refined"],
                "actions_refined": metrics["actions_refined"],
                "capabilities_refined": metrics["capabilities_refined"],

                "verified": True,

                "expert_similarity": 0,
                "expert_match": False,
                "requires_social_scientist_review": False
            })

        return {
            "status": "OK",
            "selected_issue": issue,
            "repair_operators": operator_plan,
            "deterministic_candidates": deterministic_candidates,
            "llm_candidates": llm_candidates,
            "verified_patches": verified_patches,
            "log": log
        }

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



    def extract_rule_by_id(self, sleec_text, rule_id):
        if not rule_id:
            return ""

        pattern = rf"^\s*({re.escape(rule_id)}\s+when\s+.*?)(?=^\s*Rule|\n\s*rule_end|\n\s*concern_start|\Z)"
        match = re.search(pattern, sleec_text, re.MULTILINE | re.DOTALL)

        if not match:
            return ""

        return match.group(1).strip()


    def clean_original_rule(self, original_rule, sleec_text, target_rule_id):
        original_rule = str(original_rule or "").strip()

        if target_rule_id:
            extracted = self.extract_rule_by_id(sleec_text, target_rule_id)
            if extracted:
                return extracted

        if len(original_rule) > 600 or "rule_start" in original_rule or "purpose_start" in original_rule:
            return ""

        return original_rule
    def normalize_patch(self, patch, sleec_text=""):
        patch_id = patch.get("patch_id") or patch.get("id") or "p_unknown"
        target_rule_id = patch.get("target_rule_id", "")

        original_rule = self.clean_original_rule(
            patch.get("original_rule", ""),
            sleec_text,
            target_rule_id
        )

        return {
            "id": patch_id,
            "patch_id": patch_id,
            "source": patch.get("source", "llm"),
            "issue_type": patch.get("issue_type", ""),
            "rule_ids": patch.get("rule_ids", []),
            "target_rule_id": target_rule_id,
            "operation": patch.get("operation", "N/A"),

            # now this is only Rule18, not full DAISY.sleec
            "original_rule": original_rule,

            "proposed_rule": patch.get("proposed_rule", ""),
            "missing_element": patch.get("missing_element", ""),
            "new_event": patch.get("new_event", patch.get("missing_element", "")),
            "new_measure": patch.get("new_measure", patch.get("missing_element", "")),
            "new_capability": patch.get("new_capability", patch.get("missing_element", "")),
            "new_rule": patch.get("new_rule", patch.get("proposed_rule", "")),
            "applicability": patch.get("applicability", {}),
            "natural_language_explanation": patch.get(
                "natural_language_explanation",
                patch.get("explanation", "")
            ),
            "modification_cost": patch.get("modification_cost", 1),
            "new_events_added": patch.get("new_events_added", 0),
            "new_measures_added": patch.get("new_measures_added", 0),
            "new_capabilities_added": patch.get("new_capabilities_added", 0),
            "new_rules_added": patch.get("new_rules_added", 0),
            "defeaters_added": patch.get("defeaters_added", 0),
            "verified": False
        }

    def apply_patch_to_text(self, sleec_text, patch):
        operation = patch.get("operation", "")
        original_rule = patch.get("original_rule", "")
        proposed_rule = patch.get("proposed_rule", "")
        target_rule_id = patch.get("target_rule_id", "")
        rule_ids = patch.get("rule_ids", [])

        if not target_rule_id and rule_ids:
            target_rule_id = rule_ids[0]

        delete_operations = [
            "delete",
            "delete_rule",
            "delete_redundant_rule",
            "rule_removal"
        ]

        replace_operations = [
            "edit",
            "edit_rule",
            "add_defeater",
            "defeater_introduction",
            "trigger_refinement",
            "trigger_strengthening",
            "rule_merging",
            "rule_decomposition",
            "refine_condition",
            "specialize_condition",
            "add_contextual_constraint",
            "replace_action",
            "refine_vague_predicate",
            "refine_action",
            "capability_refinement",
            "event_specialization",
            "measure_specialization"
        ]

        add_operations = [
            "add",
            "add_rule",
            "new_rule_generation"
        ]

        if operation == "event_specialization":
            new_event = patch.get("new_event") or patch.get("missing_element", "")

            if new_event and f"event {new_event}" not in sleec_text:
                sleec_text = sleec_text.replace(
                    "def_end",
                    f"event {new_event}\ndef_end"
                )

        if operation == "measure_specialization":
            new_measure = patch.get("new_measure") or patch.get("missing_element", "")

            if new_measure and f"measure {new_measure}" not in sleec_text:
                sleec_text = sleec_text.replace(
                    "def_end",
                    f"measure {new_measure}:boolean\ndef_end"
                )

        if operation == "capability_refinement":
            new_capability = (
                patch.get("new_capability")
                or patch.get("missing_element")
                or ""
            )

            if new_capability and f"event {new_capability}" not in sleec_text:
                sleec_text = sleec_text.replace(
                    "def_end",
                    f"event {new_capability}\ndef_end"
                )

        if operation in delete_operations:
            ids_to_delete = set(rule_ids)

            if target_rule_id:
                ids_to_delete.add(target_rule_id)

            if not ids_to_delete and original_rule:
                return sleec_text.replace(original_rule, "")

            lines = []

            for line in sleec_text.splitlines():
                stripped = line.strip()
                delete_line = False

                for rid in ids_to_delete:
                    if stripped.startswith(str(rid) + " "):
                        delete_line = True
                        break

                if not delete_line:
                    lines.append(line)

            return "\n".join(lines)

        if operation in replace_operations:
            if original_rule and proposed_rule and original_rule in sleec_text:
                return sleec_text.replace(
                    original_rule,
                    self.ensure_rule_id(original_rule, proposed_rule)
                )

        if operation in replace_operations:
            if target_rule_id and proposed_rule:
                lines = []
                replaced = False

                for line in sleec_text.splitlines():
                    stripped = line.strip()

                    if stripped.startswith(str(target_rule_id) + " "):
                        lines.append(
                            self.ensure_rule_id(line, proposed_rule)
                        )
                        replaced = True
                    else:
                        lines.append(line)

                if replaced:
                    return "\n".join(lines)

        if operation in add_operations:
            new_rule = patch.get("new_rule") or proposed_rule

            if new_rule:
                return sleec_text.replace(
                    "rule_end",
                    f"{new_rule}\nrule_end"
                )

        return sleec_text

    def ensure_rule_id(self, original_rule, proposed_rule):
        proposed_rule = proposed_rule.strip()

        if re.match(r"^r\d+\s+when\s+", proposed_rule, re.IGNORECASE):
            return proposed_rule

        match = re.match(r"^(r\d+)\s+", original_rule.strip())

        if match:
            return f"{match.group(1)} {proposed_rule}"

        return proposed_rule

    def target_issue_fixed(
        self,
        issue_type,
        selected_issue_value,
        original_structured,
        new_structured
    ):
        before = original_structured.get(issue_type, [])
        after = new_structured.get(issue_type, [])

        if len(after) < len(before):
            return True

        selected_text = str(selected_issue_value).strip()
        after_text = "\n".join(str(x) for x in after)

        return selected_text not in after_text

    def count_issues(self, structured):
        total = 0

        for value in structured.values():
            if isinstance(value, list):
                total += len(value)

        return total

    def patch_metrics(self, patch):
        operation = str(patch.get("operation", "")).strip()

        rules_modified = 1 if operation in [
            "edit",
            "edit_rule",
            "add_defeater",
            "defeater_introduction",
            "refine_condition",
            "trigger_refinement",
            "trigger_strengthening",
            "rule_merging",
            "rule_decomposition",
            "specialize_condition",
            "add_contextual_constraint",
            "replace_action",
            "refine_vague_predicate",
            "event_specialization",
            "measure_specialization",
            "capability_refinement"
        ] else 0

        rules_added = 1 if operation in [
            "add",
            "add_rule",
            "new_rule_generation"
        ] else 0

        rules_deleted = 1 if operation in [
            "delete",
            "delete_rule",
            "delete_redundant_rule",
            "rule_removal"
        ] else 0

        defeaters_added = 1 if operation in [
            "add_defeater",
            "defeater_introduction"
        ] else 0

        conditions_refined = 1 if operation in [
            "refine_condition",
            "trigger_refinement",
            "trigger_strengthening",
            "specialize_condition",
            "add_contextual_constraint",
            "event_specialization",
            "measure_specialization"
        ] else 0

        actions_refined = 1 if operation in [
            "refine_action",
            "replace_action",
            "capability_refinement"
        ] else 0

        capabilities_refined = 1 if operation in [
            "refine_action",
            "replace_action",
            "capability_refinement"
        ] else 0

        return {
            "rules_modified": rules_modified,
            "rules_added": rules_added,
            "rules_deleted": rules_deleted,
            "defeaters_added": defeaters_added,
            "conditions_refined": conditions_refined,
            "actions_refined": actions_refined,
            "capabilities_refined": capabilities_refined
        }
    

    def build_final_sleecpatch_file(self, use_case, original_sleec, verified_patches):
        final_sleec = original_sleec

        for patch in verified_patches:
            final_sleec = self.apply_patch_to_text(final_sleec, patch)

        folder = os.path.join("results", use_case)
        os.makedirs(folder, exist_ok=True)

        path = os.path.join(folder, f"{use_case}_SLEECPATCH.sleec")

        with open(path, "w", encoding="utf-8") as f:
            f.write(final_sleec)

        return {
            "use_case": use_case,
            "path": path,
            "sleec_text": final_sleec
        }