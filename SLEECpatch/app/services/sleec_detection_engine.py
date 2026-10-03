import sys
import os
import json
import re
import subprocess
import tempfile
import pandas as pd
import io
from contextlib import redirect_stdout
from services.diagnosis_evidence import extract_evidence

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
        self.enrich_detections_with_ast_context(sleec_text, detections)
        self.enrich_detections_with_diagnosis_evidence(
            sleec_text,
            detections
        )

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

            success = True

            if isinstance(result, tuple) and len(result) == 3:
                success, message, data = result
            else:
                message = str(result)

            combined_message = str(message) + "\n" + str(printed_output)

            # TEMP DEBUG: compare raw LEGOS situational-conflict reports
            # with the findings produced by our parser.
            if detector_type == "situational_conflict":
                import re

                raw_sc_count = len(
                    re.findall(
                        r"Situational\s+conflict\s+under\s+situation\s*:?",
                        combined_message,
                        re.IGNORECASE,
                    )
                )

                print(f"[SC DEBUG] Raw LEGOS SC blocks: {raw_sc_count}")

            findings = self.extract_findings(
                detector_type,
                combined_message,
                data
            )

            if detector_type == "situational_conflict":
                print(f"[SC DEBUG] Parsed SC findings: {len(findings)}")

            return {
                "success": True,
                "detected": bool(success),
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
            from sleec.sleecParser import (
                parse_sleec,
                scalar_mask,
                scalar_type,
                registered_type,
            )
            from sleec.Analyzer.logic_operator import text_ref

            model, *_ = parse_sleec(sleec_text, read_file=False)

        except Exception:
            return inventory

        finally:
            try:
                scalar_mask.clear()
                scalar_type.clear()
                registered_type.clear()
                text_ref.clear()
            except (NameError, AttributeError):
                pass

        for rule in getattr(getattr(model, "ruleBlock", None), "rules", []) or []:
            rule_id = str(getattr(rule, "name", "") or "").strip()
            text = self.ast_fragment(sleec_text, rule)

            if rule_id and text:
                inventory["rules"][rule_id.lower()] = {
                    "id": rule_id,
                    "text": text,
                    "condition": self.parse_when_condition(text),
                    "action": self.parse_then_action(text),
                    "kind": "rule"
                }

        for concern in getattr(getattr(model, "concernBlock", None), "concerns", []) or []:
            concern_id = str(getattr(concern, "name", "") or "").strip()
            text = self.ast_fragment(sleec_text, concern)

            if concern_id and text:
                inventory["concerns"][concern_id.lower()] = {
                    "id": concern_id,
                    "text": text,
                    "condition": self.parse_when_condition(text),
                    "action": self.parse_then_action(text),
                    "kind": "concern"
                }

        for purpose in getattr(getattr(model, "purposeBlock", None), "purposes", []) or []:
            purpose_id = str(getattr(purpose, "name", "") or "").strip()
            text = self.ast_fragment(sleec_text, purpose)

            if purpose_id and text:
                inventory["purposes"][purpose_id.lower()] = {
                    "id": purpose_id,
                    "text": text,
                    "condition": self.parse_when_condition(text),
                    "action": self.parse_then_action(text),
                    "kind": "purpose"
                }

        return inventory

    def parse_when_condition(self, text):
        match = re.search(
            r"\bwhen\s+(.+?)\s+then\b",
            str(text or ""),
            flags=re.IGNORECASE | re.DOTALL
        )
        return re.sub(r"\s+", " ", match.group(1)).strip() if match else ""

    def parse_then_action(self, text):
        match = re.search(
            r"\bthen\s+(.+?)(?:\s+within\b|\s+unless\b|$)",
            str(text or ""),
            flags=re.IGNORECASE | re.DOTALL
        )
        return re.sub(r"\s+", " ", match.group(1)).strip() if match else ""

    def extract_ids(self, text, prefix):
        pattern = rf"\b{re.escape(prefix)}[A-Za-z0-9_]*\b"
        ids = []

        for match in re.finditer(pattern, str(text or ""), flags=re.IGNORECASE):
            value = match.group(0)

            if value.lower() not in {item.lower() for item in ids}:
                ids.append(value)

        return ids

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

    def resolve_rule_references(self, text, inventory):
        refs = []

        for rule_id in self.extract_ids(text, "R"):
            rule = inventory["rules"].get(rule_id.lower())

            if rule:
                refs.append({
                    "role": "referenced",
                    "kind": "rule",
                    "id": rule["id"],
                    "text": rule["text"]
                })

        return self.unique_refs(refs)

    def resolve_wfi_artifacts(self, text, inventory):
        artifacts = []

        for concern_id in self.extract_ids(text, "c"):
            concern = inventory["concerns"].get(concern_id.lower())

            if concern:
                artifacts.append({
                    "role": "violated_concern",
                    "kind": "concern",
                    "id": concern["id"],
                    "text": concern["text"]
                })

        for purpose_id in self.extract_ids(text, "p"):
            purpose = inventory["purposes"].get(purpose_id.lower())

            if purpose:
                artifacts.append({
                    "role": "blocked_purpose",
                    "kind": "purpose",
                    "id": purpose["id"],
                    "text": purpose["text"]
                })

        return self.unique_refs(artifacts)

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
        inventory = self.parse_ast_inventory(sleec_text)

        if not any(inventory.values()):
            return detections

        for detector_type, detection in detections.items():
            for finding in detection.get("findings", []) or []:
                value = finding.get("value", "")
                artifacts = self.resolve_wfi_artifacts(value, inventory)
                rule_refs = self.resolve_rule_references(value, inventory)
                existing_original = [
                    text
                    for text in finding.get("original_rules", [])
                    if str(text or "").strip()
                ]

                for original in existing_original:
                    for ref in self.resolve_rule_references(original, inventory):
                        rule_refs.append(ref)

                related_rules = self.infer_related_rules(
                    value,
                    artifacts,
                    rule_refs,
                    inventory
                )

                finding["wfi_artifacts"] = artifacts
                finding["rule_references"] = self.unique_refs(rule_refs)
                finding["related_rules"] = related_rules
                finding["original_rules"] = [
                    ref["text"]
                    for ref in finding["rule_references"]
                ]

                if detector_type == "concern" and not finding["original_rules"]:
                    finding["original_rules"] = [
                        ref["text"]
                        for ref in related_rules[:3]
                    ]

        return detections

    def extract_findings(self, detector_type, message, data):

        msg = str(message) if message else ""
        findings = []

        if detector_type == "concern":

            import re

            pattern = r"((?:c\d+)(?:_\d+)?\s+(?:when|exists)\b.*?Concern is raised)"
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

                # Preserve BOTH rules reported by LEGOS:
                #   1. the redundant rule
                #   2. the rule because of which it is redundant
                #
                # Both rules are formal diagnosis evidence. They must remain
                # distinct from heuristic related_rules used only for UI context.
                blocks = re.findall(
                    r"Redundant SLEEC rule:(.*?)"
                    r"Because of the following SLEEC rule:(.*?)"
                    r"(?=Redundant SLEEC rule:|\*{10,}|$)",
                    msg,
                    re.IGNORECASE | re.DOTALL
                )

                for redundant_text, because_text in blocks:
                    redundant_text = redundant_text.strip()
                    because_text = because_text.strip()

                    value = (
                        "Redundant SLEEC rule:\n"
                        + redundant_text
                        + "\nBecause of the following SLEEC rule:\n"
                        + because_text
                    )

                    original_rules = []
                    original_rules.extend(
                        self.extract_rules_from_finding(redundant_text)
                    )
                    original_rules.extend(
                        self.extract_rules_from_finding(because_text)
                    )

                    findings.append({
                        "source": "sleec",
                        "value": value,
                        "original_rules": original_rules
                    })

        elif detector_type == "situational_conflict":
            import re

            # Each LEGOS situational-conflict report is a separate diagnosis.
            # Stop at the next situational-conflict report, highlighted section,
            # detector section, or end of output.
            pattern = re.compile(
                r"Situational\s+conflict\s+under\s+situation\s*:?\s*"
                r"(.*?)"
                r"(?="
                r"Situational\s+conflict\s+under\s+situation\s*:?"
                r"|TO\s+BE\s+HIGHLIGHTED"
                r"|check\s+rule_\d+"
                r"|$"
                r")",
                re.IGNORECASE | re.DOTALL,
            )

            seen = set()

            for match in pattern.finditer(msg):

                value = match.group(1).strip()

                if not value:
                    continue

                original_rules = self.extract_rules_from_finding(value)

                # A situational conflict must be grounded in the diagnosed
                # rules belonging to this conflict block only.
                normalized_rules = []

                for rule in original_rules:
                    normalized = re.sub(
                        r"\s+",
                        " ",
                        str(rule)
                    ).strip()

                    if normalized and normalized not in normalized_rules:
                        normalized_rules.append(normalized)

                # Deduplicate repeated LEGOS reports while preserving
                # genuinely different situational conflicts.
                if normalized_rules:
                    key = tuple(
                        rule.lower()
                        for rule in normalized_rules
                    )
                else:
                    key = (
                        re.sub(r"\s+", " ", value).lower(),
                    )

                if key in seen:
                    continue

                seen.add(key)

                findings.append({
                    "source": "sleec",
                    "value": value,
                    "original_rules": normalized_rules,
                })

        elif detector_type == "purpose":

            import re

            # LEGOS may print "Not Blocking" for some purposes while also
            # reporting other purposes as blocked. Therefore, purpose findings
            # must be extracted from each explicit "Blocked SLEEC purpose:"
            # section rather than by testing the whole message for
            # "Not Blocking".
            pattern = re.compile(
                r"Blocked\s+SLEEC\s+purpose:\s*"
                r"(.*?)"
                r"-{5,}\s*"
                r"-{5,}\s*"
                r"Because\s+of\s+the\s+following\s+SLEEC\s+rule:\s*"
                r"-{5,}\s*"
                r"(.*?)"
                r"(?="
                r"\*{10,}"
                r"|Blocked\s+SLEEC\s+purpose:"
                r"|TO\s+BE\s+HIGHLIGHTED"
                r"|check\s+rule_\d+"
                r"|$"
                r")",
                re.IGNORECASE | re.DOTALL,
            )

            seen = set()

            for match in pattern.finditer(msg):

                purpose_text = match.group(1).strip()
                blocking_rules_text = match.group(2).strip()

                # Remove separator lines if any remain.
                purpose_text = re.sub(
                    r"\n\s*-{5,}\s*$",
                    "",
                    purpose_text,
                ).strip()

                blocking_rules_text = re.sub(
                    r"\n\s*-{5,}\s*$",
                    "",
                    blocking_rules_text,
                ).strip()

                # A blocked purpose may be printed more than once by LEGOS.
                # Deduplicate using the purpose + blocking-rule pair.
                key = (
                    re.sub(r"\s+", " ", purpose_text).lower(),
                    re.sub(r"\s+", " ", blocking_rules_text).lower(),
                )

                if key in seen:
                    continue

                seen.add(key)

                original_rules = self.extract_rules_from_finding(
                    blocking_rules_text
                )

                findings.append({
                    "source": "sleec",
                    "value": (
                        f"Blocked SLEEC purpose:\n"
                        f"{purpose_text}\n\n"
                        f"Because of the following SLEEC rule:\n"
                        f"{blocking_rules_text}"
                    ),
                    "purpose": purpose_text,
                    "blocking_rules": original_rules,
                    "original_rules": original_rules,
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
            },
            "wfi_artifacts_by_type": {
                "concerns": [
                    x.get("wfi_artifacts", [])
                    for x in detections["concern"]["findings"]
                ],
                "conflicts": [
                    x.get("wfi_artifacts", [])
                    for x in detections["conflict"]["findings"]
                ],
                "purpose_blocking": [
                    x.get("wfi_artifacts", [])
                    for x in detections["purpose"]["findings"]
                ],
                "redundancies": [
                    x.get("wfi_artifacts", [])
                    for x in detections["redundancy"]["findings"]
                ],
                "situational_conflicts": [
                    x.get("wfi_artifacts", [])
                    for x in detections["situational_conflict"]["findings"]
                ]
            },
            "rule_references_by_type": {
                "concerns": [
                    x.get("rule_references", [])
                    for x in detections["concern"]["findings"]
                ],
                "conflicts": [
                    x.get("rule_references", [])
                    for x in detections["conflict"]["findings"]
                ],
                "purpose_blocking": [
                    x.get("rule_references", [])
                    for x in detections["purpose"]["findings"]
                ],
                "redundancies": [
                    x.get("rule_references", [])
                    for x in detections["redundancy"]["findings"]
                ],
                "situational_conflicts": [
                    x.get("rule_references", [])
                    for x in detections["situational_conflict"]["findings"]
                ]
            },
            "related_rules_by_type": {
                "concerns": [
                    x.get("related_rules", [])
                    for x in detections["concern"]["findings"]
                ],
                "conflicts": [
                    x.get("related_rules", [])
                    for x in detections["conflict"]["findings"]
                ],
                "purpose_blocking": [
                    x.get("related_rules", [])
                    for x in detections["purpose"]["findings"]
                ],
                "redundancies": [
                    x.get("related_rules", [])
                    for x in detections["redundancy"]["findings"]
                ],
                "situational_conflicts": [
                    x.get("related_rules", [])
                    for x in detections["situational_conflict"]["findings"]
                ]
            },
            "diagnoses_by_type": {
                "concerns": [
                    x.get("diagnosis", {})
                    for x in detections["concern"]["findings"]
                ],
                "conflicts": [
                    x.get("diagnosis", {})
                    for x in detections["conflict"]["findings"]
                ],
                "purpose_blocking": [
                    x.get("diagnosis", {})
                    for x in detections["purpose"]["findings"]
                ],
                "redundancies": [
                    x.get("diagnosis", {})
                    for x in detections["redundancy"]["findings"]
                ],
                "situational_conflicts": [
                    x.get("diagnosis", {})
                    for x in detections["situational_conflict"]["findings"]
                ]
            },
        }
    def enrich_detections_with_diagnosis_evidence(self, sleec_text, detections):
        detector_to_issue_type = {
            "concern": "concerns",
            "conflict": "conflicts",
            "purpose": "purpose_blocking",
            "redundancy": "redundancies",
            "situational_conflict": "situational_conflicts",
        }

        for detector_type, issue_type in detector_to_issue_type.items():
            detection = detections.get(detector_type, {})
            message = detection.get("message", "")
            if detector_type == "concern":
                print("\n========== RAW CONCERN MESSAGE ==========")
                print(message)
                print("=========================================\n")

            try:
                evidence_findings = extract_evidence(
                    detector_type,
                    message,
                    sleec_text
                )
            except Exception as exc:
                print(
                    f"[DIAGNOSIS EVIDENCE] "
                    f"{detector_type} extraction failed: {exc}"
                )
                continue

            findings = detection.get("findings", [])

            for index, finding in enumerate(findings):
                if index >= len(evidence_findings):
                    break

                evidence_finding = evidence_findings[index]
                diagnosis = evidence_finding.get("diagnosis", {})

                finding["diagnosis"] = diagnosis

                if diagnosis.get("rule_references"):
                    finding["rule_references"] = diagnosis["rule_references"]

                if evidence_finding.get("original_rules"):
                    finding["original_rules"] = evidence_finding["original_rules"]
    def run_text(self, sleec_text):
        

        detections = {
            "concern": self.safe_call("concern", check_concern, sleec_text),
            "conflict": self.safe_call("conflict", check_conflict, sleec_text),
            "purpose": self.safe_call("purpose", check_purpose, sleec_text),
            "redundancy": self.safe_call("redundancy", check_redundancy, sleec_text),
            "situational_conflict": self.safe_call("situational_conflict", check_situational, sleec_text)
        }
        self.enrich_detections_with_ast_context(sleec_text, detections)
        self.enrich_detections_with_diagnosis_evidence(
            sleec_text,
            detections
        )

        structured = self.build_structured_results(detections)

        return {
            "status": "OK",
            "sleec_input": sleec_text,
            "detections": detections,
            "structured": structured
        }
