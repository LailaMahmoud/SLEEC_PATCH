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

        detections = {
            "concern": self.safe_call("concern", check_concern, sleec_text),
            "conflict": self.safe_call("conflict", check_conflict, sleec_text),
            "purpose": self.safe_call("purpose", check_purpose, sleec_text),
            "redundancy": self.safe_call("redundancy", check_redundancy, sleec_text),
            "situational_conflict": self.safe_call("situational_conflict", check_situational, sleec_text)
        }
        structured = self.build_structured_results(detections)

        return {
            "status": "OK",
            "excel_file": excel_file,
            "sleec_input": sleec_text,
            "detections": detections,
            "structured": structured

        }


    def safe_call(self, detector_type, detector, text):

        import io
        from contextlib import redirect_stdout

        try:
            buffer = io.StringIO()

            with redirect_stdout(buffer):
                result = detector(text)

            printed_output = buffer.getvalue()

            message = ""
            data = []

            if isinstance(result, tuple) and len(result) == 3:
                _, message, data = result
            else:
                message = str(result)

            combined_message = str(message) + "\n" + str(printed_output)

            findings = self.extract_findings(
                detector_type,
                combined_message,
                data
            )

            return {
                "success": True,
                "message": combined_message,
                "data": data if data else [],
                "findings": findings,
                "count": len(findings)
            }

        except Exception as e:
            return {
                "success": False,
                "message": str(e),
                "data": [],
                "findings": [],
                "count": 0
            }

    def extract_rules_from_finding(self, text):
        import re

        rules = re.findall(
            r"(r\d+\s+when\s+.*?then\s+.*?)(?=\n|-{5,}|$)",
            str(text),
            re.IGNORECASE
        )

        clean_rules = []

        for r in rules:
            rule = r.strip()

            if rule and rule not in clean_rules:
                clean_rules.append(rule)

        return clean_rules

    def extract_findings(self, detector_type, message, data):

        msg = str(message) if message else ""
        findings = []

        if detector_type == "concern":

            import re

            pattern = r"((?:c\d+)(?:_\d+)?\s+when.*?Concern is raised)"
            matches = re.findall(
                pattern,
                msg,
                re.IGNORECASE | re.DOTALL
            )

            for m in matches:
                findings.append({
                    "source": "sleec",
                    "value": m.strip()
                })


        elif detector_type == "conflict":

            import re

            conflicts = re.findall(
                r"Conflict detected.*?TO BE HIGHLIGHTED(.*?)(?=\*{10,}|$)",
                msg,
                re.DOTALL
            )

            for c in conflicts:
                findings.append({
                    "source": "sleec",
                    "value": c.strip()
                })

        elif detector_type == "redundancy":
            if "Redundant SLEEC rule" in msg:
                import re

                matches = re.findall(
                    r"Redundant SLEEC rule:(.*?)Because of the following SLEEC rule:",
                    msg,
                    re.DOTALL
                )

                for m in matches:
                    findings.append({
                        "source": "sleec",
                        "value": m.strip()
                    })

        elif detector_type == "situational_conflict":

            import re

            matches = re.findall(
                r"Situational conflict under situation(.*?)(?=\*{10,}|$)",
                msg,
                re.DOTALL
            )

            for m in matches:
                value = m.strip()
                findings.append({
                    "source": "sleec",
                    "value": value,
                    "original_rules": self.extract_rules_from_finding(value)
                })

                
        elif detector_type == "purpose":
            if "Blocking" in msg and "Not Blocking" not in msg:
                findings.append({
                    "source": "sleec",
                    "value": "Purpose blocking detected."
                })

        return findings
    
    def build_structured_results(self, detections):

        return {
            "concerns": [
                x["value"]
                for x in detections["concern"]["findings"]
            ],
            "conflicts": [
                x["value"]
                for x in detections["conflict"]["findings"]
            ],
            "purpose_blocking": [
                x["value"]
                for x in detections["purpose"]["findings"]
            ],
            "redundancies": [
                x["value"]
                for x in detections["redundancy"]["findings"]
            ],
            "situational_conflicts": [
                x["value"]
                for x in detections["situational_conflict"]["findings"]
            ],
            "original_rules_by_type": {
                "concerns": [
                    x.get("original_rules", [])
                    for x in detections["concern"]["findings"]
                ],
                "conflicts": [
                    x.get("original_rules", [])
                    for x in detections["conflict"]["findings"]
                ],
                "purpose_blocking": [
                    x.get("original_rules", [])
                    for x in detections["purpose"]["findings"]
                ],
                "redundancies": [
                    x.get("original_rules", [])
                    for x in detections["redundancy"]["findings"]
                ],
                "situational_conflicts": [
                    x.get("original_rules", [])
                    for x in detections["situational_conflict"]["findings"]
                ]
            }
        }
    
    def run_text(self, sleec_text):
        

        detections = {
            "concern": self.safe_call("concern", check_concern, sleec_text),
            "conflict": self.safe_call("conflict", check_conflict, sleec_text),
            "purpose": self.safe_call("purpose", check_purpose, sleec_text),
            "redundancy": self.safe_call("redundancy", check_redundancy, sleec_text),
            "situational_conflict": self.safe_call("situational_conflict", check_situational, sleec_text)
        }

        structured = self.build_structured_results(detections)

        return {
            "status": "OK",
            "sleec_input": sleec_text,
            "detections": detections,
            "structured": structured
        }
