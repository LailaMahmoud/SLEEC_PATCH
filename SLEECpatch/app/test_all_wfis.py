from pathlib import Path
from collections import Counter

from services.sleec_patch_workbench_engine import SLEECPatchWorkbenchEngine
from services.repair_operator_selector import RepairOperatorSelector


BASE = Path("sleec_usecases")

USE_CASES = {
    "ALMI": BASE / "ALMI.sleec",
    "ASPEN": BASE / "aspen.sleec",
    "AutoCAR": BASE / "Autocar.sleec",
    "BSN": BASE / "BSN.sleec",
    "CSICobot": BASE / "CSI.sleec",
    "DAISY": BASE / "Daisy.sleec",
    "DPA": BASE / "DPA.sleec",
    "DressAssist": BASE / "DRESSASSIST.sleec",
    "SafeSCAD": BASE / "safescade.sleec",
    "Tabiat": BASE / "Tabiat.sleec",
    "Casper": BASE / "Casper.sleec",
}


engine = SLEECPatchWorkbenchEngine()
selector = RepairOperatorSelector()


def as_list(value):
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def get_issues(result):
    """
    Flatten workbench diagnosis output into:
        [(issue_type, issue), ...]

    Preferred source:
        result["structured"]

    This is the normalized WFI output produced by
    SLEECPatchWorkbenchEngine.diagnose().
    """
    issues = []

    if not isinstance(result, dict):
        return issues

    keys = [
        "concerns",
        "situational_conflicts",
        "conflicts",
        "redundancies",
        "purpose_blocking",
    ]

    # ---------------------------------------------------------
    # Preferred source: normalized workbench diagnosis
    # ---------------------------------------------------------
    structured = result.get("structured", {})

    if isinstance(structured, dict):
        for issue_type in keys:
            for item in as_list(structured.get(issue_type)):
                if item:
                    issues.append((issue_type, item))

    # If structured output exists, do not also read raw detector
    # output because that could duplicate the same WFI.
    if issues:
        return issues

    # ---------------------------------------------------------
    # Fallback for older diagnosis-result formats
    # ---------------------------------------------------------
    for issue_type in keys:
        for item in as_list(result.get(issue_type)):
            if item:
                issues.append((issue_type, item))

    detections = result.get("detections")

    if isinstance(detections, dict):
        for issue_type in keys:
            for item in as_list(detections.get(issue_type)):
                if item:
                    issues.append((issue_type, item))

    return issues


def issue_text(issue):
    if isinstance(issue, str):
        return issue

    if isinstance(issue, dict):
        for key in [
            "diagnosis",
            "summary",
            "text",
            "message",
            "description",
            "witness",
        ]:
            value = issue.get(key)
            if value:
                return str(value)

        return str(issue)

    return str(issue)


for use_case, path in USE_CASES.items():

    print("\n" + "=" * 78)
    print("USE CASE:", use_case)
    print("FILE:", path)
    print("=" * 78)

    if not path.exists():
        print("SKIP: file not found")
        continue

    sleec_text = path.read_text(encoding="utf-8")

    try:
        result = engine.diagnose(sleec_text)
    except Exception as exc:
        print("DIAGNOSIS ERROR:", repr(exc))
        continue

    issues = get_issues(result)
    counts = Counter(t for t, _ in issues)

    print("\nWFI COUNTS")
    print("concerns             :", counts["concerns"])
    print("situational_conflicts:", counts["situational_conflicts"])
    print("conflicts            :", counts["conflicts"])
    print("redundancies         :", counts["redundancies"])
    print("purpose_blocking     :", counts["purpose_blocking"])
    print("TOTAL                :", len(issues))

    # We are especially interested in SC.
    scs = [
        issue
        for issue_type, issue in issues
        if issue_type == "situational_conflicts"
    ]

    if not scs:
        print("\nSC: none detected")
        continue

    print("\n*** SITUATIONAL CONFLICTS ***")

    # Try to obtain parsed rules/vocabulary using the engine helpers.
    try:
        rules = engine.sleec_text_to_rules_json(sleec_text)
    except Exception:
        rules = []

    existing_events = []
    existing_measures = []
    existing_responses = []

    # Diagnose output may already expose vocabulary.
    if isinstance(result, dict):
        existing_events = (
            result.get("events")
            or result.get("existing_events")
            or []
        )
        existing_measures = (
            result.get("measures")
            or result.get("existing_measures")
            or []
        )
        existing_responses = (
            result.get("responses")
            or result.get("existing_responses")
            or []
        )

    for number, sc in enumerate(scs, start=1):

        text = issue_text(sc)

        print("\n" + "-" * 70)
        print(f"SC #{number}")
        print("-" * 70)
        print(text[:2500])

        try:
            selected = selector.select(
                issue_type="situational_conflicts",
                rules=rules,
                selected_issue=text,
                existing_events=existing_events,
                existing_measures=existing_measures,
                existing_responses=existing_responses,
            )

            print("\nDETERMINISTIC:")
            print(selected.get("deterministic", []))

            print("LLM:")
            print(selected.get("llm", []))

            print("\nAPPLICABILITY:")
            for op, info in selected.get("applicability", {}).items():
                applicable = info.get("is_applicable")
                reason = info.get("reason", "")
                print(f"  {op:38} {applicable}")
                print(f"      {reason}")

        except Exception as exc:
            print("SELECTOR ERROR:", repr(exc))


print("\n" + "=" * 78)
print("FINISHED")
print("=" * 78)
