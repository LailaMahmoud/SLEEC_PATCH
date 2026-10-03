"""Run the LEGOS-SLEEC detectors and return per-finding diagnoses.

Every finding carries its formal evidence (source requirement or rule, witness
trace, implicated rules). A detector run that raises, returns an inconclusive or
malformed result, or whose findings cannot be attributed to the specification is
reported as a failure: an incomplete analysis is never a clean bill of health.
"""
import sys
import os
import re
import io
from contextlib import redirect_stdout

import pandas as pd

PROJECT_ROOT = os.path.abspath(
    os.path.join(
        os.path.dirname(__file__),
        "..",
        "..",
        ".."
    )
)

if PROJECT_ROOT not in sys.path:
    sys.path.append(PROJECT_ROOT)


from sleec.sleec_api import (
    check_conflict,
    check_redundancy,
    check_concern,
    check_purpose,
    check_situational
)
from sleec.analysis_runtime import ANALYSIS_LOCK, AnalysisError
from sleec.sleecParser import parse_sleec_ast
from services.diagnosis_evidence import extract_evidence
from services.rule_model import rules_from_text


DETECTOR_ISSUE_TYPES = {
    "concern": "concerns",
    "conflict": "conflicts",
    "purpose": "purpose_blocking",
    "redundancy": "redundancies",
    "situational_conflict": "situational_conflicts",
}


def analysis_failures(analysis):
    """Reject failed, missing or malformed detector results before verification."""
    if not isinstance(analysis, dict):
        return {"analysis": "No valid analysis result was returned."}
    failures = {}
    if analysis.get("status") != "OK":
        failures["analysis"] = analysis.get("error") or "Analysis did not complete successfully."
    detections = analysis.get("detections")
    structured = analysis.get("structured")
    if not isinstance(detections, dict) or not isinstance(structured, dict):
        failures["analysis"] = "Incomplete detector results."
        return failures
    for name, issue_type in DETECTOR_ISSUE_TYPES.items():
        result = detections.get(name)
        if not isinstance(result, dict) or result.get("success") is not True:
            failures[name] = (result.get("message") if isinstance(result, dict) else None) or "Detector did not complete."
        elif type(result.get("detected")) is not bool or not isinstance(structured.get(issue_type), list):
            failures[name] = "Malformed detector findings."
        elif result["detected"] != bool(structured[issue_type]):
            failures[name] = "Detector outcome and extracted findings disagree."
    return failures


class SLEECDetectionEngine:

    def excel_to_full_sleec(self, excel_file):

        xls = pd.ExcelFile(excel_file)

        sections = {
            "Definitions": [],
            "Rules": [],
            "Other": []
        }

        for sheet in xls.sheet_names:
            df = pd.read_excel(excel_file, sheet_name=sheet)

            for col in df.columns:
                for value in df[col].dropna():
                    line = str(value).strip()
                    if line:
                        sections.setdefault(sheet, []).append(line)

        lines = []

        lines.append("def_start")
        lines.extend(sections.get("Definitions", []))
        lines.append("def_end")
        lines.append("")

        lines.append("rule_start")
        lines.extend(sections.get("Rules", []))
        lines.append("rule_end")
        lines.append("")

        lines.extend(sections.get("Other", []))

        return "\n".join(lines)

    def run(self, excel_file):
        sleec_text = self.excel_to_full_sleec(excel_file)
        result = self.run_text(sleec_text)
        result["excel_file"] = excel_file
        return result

    def safe_call(self, detector_type, detector, text):
        try:
            # Repairs address rules by ID, so the input must identify every
            # rule unambiguously before any proof is attributed to it.
            rules_from_text(text)
            buffer = io.StringIO()

            # stdout capture is process-wide, as is LEGOS state. Hold the same
            # lock as the underlying detector for the entire capture window.
            with ANALYSIS_LOCK, redirect_stdout(buffer):
                result = detector(text)

            printed_output = buffer.getvalue()

            if not isinstance(result, tuple) or len(result) != 3:
                raise AnalysisError("Detector returned an invalid result format.")
            detected, message, data = result
            if type(detected) is not bool or not isinstance(message, str) or not isinstance(data, list):
                raise AnalysisError("Detector returned an incomplete or invalid outcome.")

            combined_message = str(message) + "\n" + str(printed_output)

            findings = self.extract_findings(detector_type, message, data, text)
            if detected != bool(findings):
                raise AnalysisError(
                    "Detector outcome and extracted findings disagree; diagnosis is incomplete."
                )

            return {
                "success": True,
                "detected": detected,
                "message": combined_message,
                "report": message,
                "debug_output": printed_output,
                "data": data if data else [],
                "findings": findings,
                "count": len(findings)
            }

        except Exception as e:
            return {
                "success": False,
                "detected": None,
                "message": str(e),
                "data": [],
                "findings": [],
                "count": 0
            }

    def extract_findings(self, detector_type, message, data, sleec_text):
        """One parser for findings and their evidence, so they can never disagree."""
        return extract_evidence(detector_type, message, sleec_text)

    # ------------------------------------------------------------------
    # AST context shown next to each finding in the workbench.
    # ------------------------------------------------------------------

    def clean_source_fragment(self, text):
        lines = [
            line.strip()
            for line in str(text or "").strip().splitlines()
            if line.strip() and not line.strip().startswith("//")
        ]
        return "\n".join(lines)

    def ast_fragment(self, sleec_text, node):
        start = getattr(node, "_tx_position", None)
        end = getattr(node, "_tx_position_end", None)

        if isinstance(start, int) and isinstance(end, int) and end > start:
            return self.clean_source_fragment(sleec_text[start:end])

        return ""

    def parse_ast_inventory(self, sleec_text):
        inventory = {
            "rules": {},
            "concerns": {},
            "purposes": {}
        }

        try:
            model = parse_sleec_ast(sleec_text)
        except Exception:
            return inventory

        for kind, block_name, items_name in (
            ("rule", "ruleBlock", "rules"),
            ("concern", "concernBlock", "concerns"),
            ("purpose", "purposeBlock", "purposes"),
        ):
            block = getattr(model, block_name, None)
            for node in (getattr(block, items_name, []) if block else []) or []:
                node_id = str(getattr(node, "name", "") or "").strip()
                text = self.ast_fragment(sleec_text, node)
                if node_id and text:
                    inventory[items_name][node_id.lower()] = {
                        "id": node_id,
                        "text": text,
                        "condition": self.parse_when_condition(text),
                        "action": self.parse_then_action(text),
                        "kind": kind
                    }

        return inventory

    def parse_when_condition(self, text):
        match = re.search(
            r"\b(?:when|exists)\s+(.+?)\s+(?:then|while)\b",
            str(text or ""),
            flags=re.IGNORECASE | re.DOTALL
        )
        return re.sub(r"\s+", " ", match.group(1)).strip() if match else ""

    def parse_then_action(self, text):
        match = re.search(
            r"\b(?:then|while)\s+(.+?)(?:\s+within\b|\s+unless\b|$)",
            str(text or ""),
            flags=re.IGNORECASE | re.DOTALL
        )
        return re.sub(r"\s+", " ", match.group(1)).strip() if match else ""

    def condition_terms(self, text):
        ignored = {
            "and", "or", "not", "when", "then", "unless", "within",
            "eventually", "while", "exists", "true", "false",
            "seconds", "second", "minutes", "minute"
        }
        return {
            token.lower()
            for token in re.findall(
                r"[A-Za-z_][A-Za-z0-9_]*",
                str(text or "")
            )
            if token.lower() not in ignored
        }

    def normalize_action(self, text):
        text = str(text or "").strip()
        text = re.split(
            r"\bwithin\b|\bunless\b|\beventually\b|\botherwise\b",
            text,
            maxsplit=1,
            flags=re.IGNORECASE
        )[0]
        return re.sub(r"\s+", " ", text).strip().lower()

    def unique_refs(self, refs):
        seen = set()
        unique = []

        for ref in refs:
            key = (ref.get("kind"), ref.get("id", "").lower(), ref.get("role"))

            if key in seen:
                continue

            seen.add(key)
            unique.append(ref)

        return unique

    def infer_related_rules(self, finding_text, artifact_refs, rule_refs, inventory):
        related = []
        referenced = {ref.get("id", "").lower() for ref in rule_refs}
        basis_text = str(finding_text or "")

        for artifact in artifact_refs:
            basis_text += "\n" + artifact.get("text", "")

        basis_terms = self.condition_terms(basis_text)
        basis_action = self.normalize_action(self.parse_then_action(basis_text))

        for rule in inventory["rules"].values():
            if rule["id"].lower() in referenced:
                continue

            rule_text = rule["text"]
            rule_terms = self.condition_terms(rule_text)
            rule_action = self.normalize_action(rule.get("action", ""))
            shared = basis_terms.intersection(rule_terms)
            score = len(shared)

            if basis_action and rule_action == basis_action:
                score += 4

            if basis_action and basis_action in self.normalize_action(rule_text):
                score += 2

            if score >= 2 or (artifact_refs and score >= 1):
                related.append({
                    "role": "inferred",
                    "kind": "rule",
                    "id": rule["id"],
                    "text": rule_text,
                    "score": score
                })

        related.sort(key=lambda item: (-item.get("score", 0), item.get("id", "")))
        return self.unique_refs(related[:5])

    def enrich_detections_with_ast_context(self, sleec_text, detections):
        """Attach the diagnosed artifact, proof rules and heuristic related rules.

        The formal diagnosis is never changed here; related rules are UI context.
        """
        inventory = self.parse_ast_inventory(sleec_text)

        if not any(inventory.values()):
            return detections

        for detector_type, detection in detections.items():
            for finding in detection.get("findings", []) or []:
                diagnosis = finding.get("diagnosis", {}) or {}
                source_id = str(diagnosis.get("source_id", "") or "")
                artifacts = []
                if detector_type in ("concern", "purpose") and source_id:
                    items = inventory["concerns" if detector_type == "concern" else "purposes"]
                    item = items.get(source_id.lower())
                    if item:
                        artifacts.append({
                            "role": "violated_concern" if detector_type == "concern" else "blocked_purpose",
                            "kind": item["kind"],
                            "id": item["id"],
                            "text": item["text"]
                        })

                rule_refs = []
                for ref in diagnosis.get("rule_references", []) or []:
                    rule_refs.append({
                        "role": "diagnosed" if ref.get("id") == source_id else "referenced",
                        "kind": "rule",
                        "id": ref.get("id", ""),
                        "text": ref.get("text", "")
                    })

                related_rules = self.infer_related_rules(
                    finding.get("value", ""),
                    artifacts,
                    rule_refs,
                    inventory
                )

                finding["wfi_artifacts"] = artifacts
                finding["rule_references"] = self.unique_refs(rule_refs)
                finding["related_rules"] = related_rules
                if not finding.get("original_rules"):
                    finding["original_rules"] = [ref["text"] for ref in finding["rule_references"]]

                if detector_type == "concern" and not finding["original_rules"]:
                    finding["original_rules"] = [
                        ref["text"]
                        for ref in related_rules[:3]
                    ]

        return detections

    def build_structured_results(self, detections):
        structured = {}
        by_type = {
            "original_rules_by_type": "original_rules",
            "wfi_artifacts_by_type": "wfi_artifacts",
            "rule_references_by_type": "rule_references",
            "related_rules_by_type": "related_rules",
            "diagnoses_by_type": "diagnosis",
        }
        collections = {key: {} for key in by_type}
        for detector_type, issue_type in DETECTOR_ISSUE_TYPES.items():
            findings = detections.get(detector_type, {}).get("findings", []) or []
            structured[issue_type] = [finding["value"] for finding in findings]
            for key, field in by_type.items():
                default = {} if field == "diagnosis" else []
                collections[key][issue_type] = [finding.get(field, default) for finding in findings]
        structured.update(collections)
        return structured

    def run_text(self, sleec_text):
        detections = {
            "concern": self.safe_call("concern", check_concern, sleec_text),
            "conflict": self.safe_call("conflict", check_conflict, sleec_text),
            "purpose": self.safe_call("purpose", check_purpose, sleec_text),
            "redundancy": self.safe_call("redundancy", check_redundancy, sleec_text),
            "situational_conflict": self.safe_call("situational_conflict", check_situational, sleec_text)
        }
        self.enrich_detections_with_ast_context(sleec_text, detections)

        structured = self.build_structured_results(detections)

        failures = {name: result["message"] for name, result in detections.items() if not result["success"]}
        return {
            "status": "ERROR" if failures else "OK",
            "error": f"SLEEC analysis failed: {failures}" if failures else "",
            "sleec_input": sleec_text,
            "detections": detections,
            "structured": structured
        }
