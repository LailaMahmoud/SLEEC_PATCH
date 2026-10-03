"""Lossless, per-finding evidence from LEGOS' returned reports.

Printed solver progress is deliberately excluded: it contains repeated reports
and witnesses for checks which did not find a problem.
"""
import re

from sleec.sleecParser import parse_sleec_ast


TRACE_LINE = re.compile(r"^\s*\*?at time\s+([^:]+):\s*([A-Za-z_]\w*)\((.*)\)\s*$")
REPORT_MARKERS = {
    "concern": "Concern is raised",
    "conflict": "Conflicting SLEEC rule:",
    "purpose": "Blocked SLEEC purpose:",
    "redundancy": "Redundant SLEEC rule:",
    "situational_conflict": "Situational conflict under situation",
}


def source_catalog(sleec_text):
    model = parse_sleec_ast(sleec_text)
    catalog = {}
    for kind, block_name, items_name in (
        ("rule", "ruleBlock", "rules"),
        ("concern", "concernBlock", "concerns"),
        ("purpose", "purposeBlock", "purposes"),
    ):
        block = getattr(model, block_name, None)
        catalog[kind] = [
            {"id": node.name, "text": sleec_text[node._tx_position:node._tx_position_end]}
            for node in (getattr(block, items_name, []) if block else [])
        ]
    catalog["measure_types"] = {
        node.name: type(node).__name__ for node in model.definitions
        if type(node).__name__.endswith("Measure")
    }
    return catalog


def number_or_text(raw):
    # LEGOS uses integer seconds/numeric measures. Keep unexpected formats as
    # text rather than rounding rational values or inventing a conversion.
    return int(raw) if re.fullmatch(r"[+-]?\d+", raw) else raw


def parse_trace(report, measure_types=None):
    entries = []
    measure_types = measure_types or {}
    for line in report.splitlines():
        match = TRACE_LINE.match(line)
        if not match:
            if re.match(r"\s*\*?at time\b", line):
                entries.append({"kind": "unparsed", "raw": line})
            continue
        timestamp, name, arguments = match.groups()
        timestamp = timestamp.strip()
        values = {}
        for argument in arguments.split(","):
            key, sep, value = argument.strip().partition("=")
            if not sep:
                continue
            key, value = key.strip(), value.strip()
            value_type = measure_types.get(key)
            if value_type == "ScalarMeasure":
                parsed = value
            elif value_type in (None, "BoolMeasure") and value.lower() in ("true", "false"):
                parsed = value.lower() == "true"
            else:
                parsed = number_or_text(value)
            values[key] = parsed
        entries.append({
            "kind": "measure" if name == "Measure" else "event",
            "timestamp": number_or_text(timestamp),
            "timestamp_raw": timestamp,
            "time_unit": "seconds",
            "name": name,
            "values": values,
            "arguments_raw": arguments,
            "raw": line,
        })
    return entries


def referenced_sources(report, sources):
    """Match complete AST source spans, including custom IDs and multiline rules."""
    matches = []
    for source in sources:
        pattern = (r"(?m)^[ \t]*" + r"\s+".join(re.escape(t) for t in source["text"].split())
                   + r"(?=[ \t]*(?:\n|$))")
        match = re.search(pattern, report)
        if match:
            matches.append((match.start(), source))
    return [source for _, source in sorted(matches, key=lambda item: item[0])]



def referenced_sources_by_id(report, sources):
    """
    Match a LEGOS finding to an AST source by its exact declaration ID.

    Concern and purpose reports preserve identifiers such as c4, c7, c8,
    even when LEGOS normalizes the printed source text differently from
    the original AST source span.
    """
    matches = []

    for source in sources:
        source_id = str(source.get("id", "")).strip()

        if not source_id:
            continue

        pattern = (
            r"(?m)^[ \t]*"
            + re.escape(source_id)
            + r"(?=[ \t]+(?:when|exists)\b)"
        )

        match = re.search(pattern, report)

        if match:
            matches.append((match.start(), source))

    return [
        source
        for _, source in sorted(matches, key=lambda item: item[0])
    ]

def extract_evidence(detector_type, message, sleec_text):
    marker = REPORT_MARKERS[detector_type]
    if marker not in message:
        return []
    catalog = source_catalog(sleec_text)
    # Situational reports have no star separator; their own header separates
    # findings. Other detectors emit one star-delimited block per check.
    if detector_type == "situational_conflict":
        blocks = re.split(r"(?=Situational conflict under situation)", message)
    else:
        blocks = re.split(r"(?m)^\*{10,}\s*$", message)
    findings = []
    for block in blocks:
        if marker not in block:
            continue
        raw_report = block.strip()
        trace = parse_trace(raw_report, catalog["measure_types"])
        source_kind = detector_type if detector_type in ("concern", "purpose") else "rule"

        # Concern and purpose findings carry their declaration ID in the
        # LEGOS report. Prefer exact ID matching because printed formatting
        # may differ from the AST source span.
        if detector_type in ("concern", "purpose"):
            sources = referenced_sources_by_id(
                raw_report,
                catalog[source_kind],
            )

            # Compatibility fallback for reports where the declaration ID
            # is not printed in the expected form.
            if not sources:
                sources = referenced_sources(
                    raw_report,
                    catalog[source_kind],
                )
        else:
            sources = referenced_sources(
                raw_report,
                catalog[source_kind],
            )

        if not sources:
            raise ValueError(f"Cannot identify the source of the {detector_type} finding.")

        source = sources[0]
        rule_report = raw_report
        if detector_type == "concern":
            rule_report = ""  # A witness supplies no rule-causality proof.
        elif detector_type == "purpose":
            rule_report = raw_report.partition("Because of the following SLEEC rule:")[2]
        rule_refs = referenced_sources(rule_report, catalog["rule"])
        # Values remain witness-independent for regression comparisons and
        # legacy rule parsers. Full reports and ordered witnesses live alongside.
        if detector_type == "concern":
            value = source["text"] + "\nConcern is raised"
        elif detector_type == "redundancy":
            value = source["text"]
        else:
            value = "\n".join(line for line in raw_report.splitlines()
                              if not re.match(r"\s*\*?at time\b", line))
        diagnosis = {
            "source_id": source["id"],
            "source_text": source["text"],
            "raw_report": raw_report,
            "trace": trace,
            "affected_rule_ids": [ref["id"] for ref in rule_refs],
            "rule_references": rule_refs,
            "rule_id_provenance": "detector_report" if rule_refs else "unavailable",
        }
        findings.append({
            "source": "sleec", "value": value,
            "original_rules": [ref["text"] for ref in rule_refs],
            "diagnosis": diagnosis,
        })
    return findings


def diagnosis_for_issue(structured, issue_type, value, issue_id=None):
    """Recover server-side evidence even from clients sending only a finding value."""
    values = structured.get(issue_type, [])
    diagnoses = structured.get("diagnoses_by_type", {}).get(issue_type, [])
    match = re.fullmatch(re.escape(issue_type) + r"_(\d+)", str(issue_id or ""))
    if match:
        index = int(match.group(1)) - 1
        if 0 <= index < min(len(values), len(diagnoses)) and values[index] == value:
            return diagnoses[index]
    matches = []
    for index, candidate in enumerate(values):
        if candidate == value and index < len(diagnoses):
            matches.append(diagnoses[index])
    if len(matches) > 1:
        raise ValueError("Multiple witnesses match this finding; its issue ID is required.")
    return matches[0] if matches else {}


def finding_identity(issue_type, value, diagnosis=None):
    """Identity is independent of the witness, the proof wording and the solver's
    choice of supporting rules.

    LEGOS checks well-formedness per rule, concern or purpose: a rule is
    (situationally) conflicting or redundant, a concern is raised, a purpose is
    blocked. The subject of the finding therefore identifies the issue; the
    "because of" rules are explanation, and may differ between solver runs.
    """
    diagnosis = diagnosis or {}
    source_id = diagnosis.get("source_id")
    if source_id:
        return (issue_type, str(source_id))
    # Compatibility with saved runs from before structured evidence existed:
    # LEGOS prints the diagnosed subject before any supporting rule.
    ids = re.findall(r"(?m)^\s*([A-Za-z_]\w*)\s+(?:when|exists)\b", str(value))
    if ids:
        return (issue_type, ids[0])
    stable = "\n".join(line for line in str(value).splitlines() if not re.match(r"\s*\*?at time\b", line))
    return (issue_type, re.sub(r"\s+", " ", stable).strip())
