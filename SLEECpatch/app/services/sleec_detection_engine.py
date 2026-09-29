import sys
import os
import json
import re
import subprocess
import tempfile
import pandas as pd
import io
from contextlib import redirect_stdout


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

        import io
        from contextlib import redirect_stdout

        try:
            # Validate source identity before running or attributing any proof.
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

            findings = self.extract_findings(
                detector_type,
                message,
                data,
                text
            )
            if detected != bool(findings):
                raise AnalysisError("Detector outcome and extracted findings disagree; diagnosis is incomplete.")

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
        return extract_evidence(detector_type, message, sleec_text)

    def build_structured_results(self, detections):
        structured = {}
        original_rules = {}
        diagnoses = {}
        for detector_type, issue_type in DETECTOR_ISSUE_TYPES.items():
            findings = detections[detector_type]["findings"]
            structured[issue_type] = [finding["value"] for finding in findings]
            original_rules[issue_type] = [finding["original_rules"] for finding in findings]
            diagnoses[issue_type] = [finding["diagnosis"] for finding in findings]
        structured["original_rules_by_type"] = original_rules
        structured["diagnoses_by_type"] = diagnoses
        return structured

    def run_text(self, sleec_text):
        

        detections = {
            "concern": self.safe_call("concern", check_concern, sleec_text),
            "conflict": self.safe_call("conflict", check_conflict, sleec_text),
            "purpose": self.safe_call("purpose", check_purpose, sleec_text),
            "redundancy": self.safe_call("redundancy", check_redundancy, sleec_text),
            "situational_conflict": self.safe_call("situational_conflict", check_situational, sleec_text)
        }

        structured = self.build_structured_results(detections)

        failures = {name: result["message"] for name, result in detections.items() if not result["success"]}
        return {
            "status": "ERROR" if failures else "OK",
            "error": f"SLEEC analysis failed: {failures}" if failures else "",
            "sleec_input": sleec_text,
            "detections": detections,
            "structured": structured
        }
