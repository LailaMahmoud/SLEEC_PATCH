from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from openai import OpenAI

APP_DIR = Path(__file__).resolve().parents[0]
# When copied into SLEECpatch/app/scripts, use parent app directory instead.
if APP_DIR.name == "scripts":
    APP_DIR = APP_DIR.parent

SLEEC_DIR = APP_DIR / "sleec_usecases"
REPO_ROOT = APP_DIR.parents[1] if APP_DIR.name == "app" else APP_DIR.parent
RESULTS_DIR = APP_DIR / "results"
OUTPUT_PATH = APP_DIR / "capability_map.json"

CASE_FILES = {
    "ALMI": ("ALMI.sleec", "ALMI-corrected.sleec"),
    "ASPEN": ("aspen.sleec", "aspen-corrected.sleec"),
    "AutoCAR": ("Autocar.sleec", "Autocar-corrected.sleec"),
    "BSN": ("BSN.sleec", "BSN-corrected.sleec"),
    "Casper": ("Casper.sleec", "Casper-corrected.sleec"),
    "CSICobot": ("CSI.sleec", "CSI-corrected.sleec"),
    "DAISY": ("Daisy.sleec", "Daisy-corrected.sleec"),
    "DPA": ("DPA.sleec", "DPA-corrected.sleec"),
    "DressAssist": ("DRESSASSIST.sleec", "DRESSASSIST-corrected.sleec"),
    "SafeSCAD": ("safescade.sleec", "safescade-corrected.sleec"),
    "Tabiat": ("Tabiat.sleec", "Tabiat-corrected.sleec"),
}

MODEL = os.getenv("CAPABILITY_CLASSIFIER_MODEL", "gpt-4o-mini")


def normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def extract_declared_symbols(text: str) -> tuple[list[str], list[str]]:
    events: list[str] = []
    measures: list[str] = []
    inside_defs = False

    for raw in text.splitlines():
        line = raw.strip()
        low = line.lower()
        if low == "def_start":
            inside_defs = True
            continue
        if low == "def_end":
            break
        if not inside_defs or not line or line.startswith("//"):
            continue

        m_event = re.match(r"^event\s+([A-Za-z_][A-Za-z0-9_]*)\b", line, re.IGNORECASE)
        if m_event:
            events.append(m_event.group(1))
            continue

        m_measure = re.match(r"^measure\s+([A-Za-z_][A-Za-z0-9_]*)\b", line, re.IGNORECASE)
        if m_measure:
            measures.append(m_measure.group(1))

    return sorted(set(events)), sorted(set(measures))


def extract_rule_section(text: str) -> str:
    match = re.search(r"rule_start(.*?)rule_end", text, re.IGNORECASE | re.DOTALL)
    return match.group(1).strip() if match else ""


def parse_json_object(raw: str) -> dict:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
        raw = re.sub(r"\s*```$", "", raw)
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError(f"Model did not return a JSON object:\n{raw}")
    return json.loads(raw[start:end + 1])


def classify_spec(client: OpenAI, use_case: str, version: str, path: Path) -> dict:
    text = path.read_text(encoding="utf-8", errors="replace")
    events, measures = extract_declared_symbols(text)
    declared = set(events) | set(measures)
    rules = extract_rule_section(text)

    prompt = f"""
You are classifying system capabilities in a SLEEC normative requirements specification.

Use case: {use_case}
Specification version: {version}

Definition used for this evaluation:
A SYSTEM CAPABILITY is a behavior, service, operation, or function that the system/agent itself can perform or provide.

Do NOT classify as a capability merely because a symbol is declared as an event or measure.
Exclude environmental occurrences, user actions, observations, sensor states, contextual facts, Boolean conditions, risk/state variables, consent states, and other conditions that describe the world rather than something the system can perform.

Examples:
- CallEmergencyServices -> capability when the system can perform it.
- InformCaregiver -> capability.
- HumanOnFloor -> not a capability; it is an environmental condition/event.
- userDisablesAlarm -> not a capability; it is a user/context condition.
- riskLevel -> not a capability; it is a contextual measure.

A capability may occur after THEN, before THEN, or in both positions. Position in a rule alone does not determine whether it is a capability.
Treat positive and negative normative uses as the same underlying capability (e.g., CallEmergencyServices and not CallEmergencyServices refer to one capability).

Declared events:
{json.dumps(events, indent=2)}

Declared measures:
{json.dumps(measures, indent=2)}

SLEEC rules:
{rules}

Return ONLY valid JSON with this shape:
{{
  "capabilities": ["ExactDeclaredSymbol", "..."],
  "excluded": [
    {{"symbol": "ExactDeclaredSymbol", "reason": "short reason"}}
  ],
  "notes": "short explanation of ambiguous cases"
}}

Every capability must be one of the declared event/measure symbols above. Do not invent names.
""".strip()

    response = client.responses.create(
        model=MODEL,
        input=prompt,
        temperature=0,
    )
    data = parse_json_object(response.output_text)

    capabilities = sorted({str(x).strip() for x in data.get("capabilities", []) if str(x).strip()})
    unknown = [x for x in capabilities if x not in declared]
    if unknown:
        raise ValueError(f"{use_case}/{version}: model returned undeclared symbols: {unknown}")

    excluded = []
    for item in data.get("excluded", []):
        if not isinstance(item, dict):
            continue
        symbol = str(item.get("symbol", "")).strip()
        if symbol in declared and symbol not in capabilities:
            excluded.append({
                "symbol": symbol,
                "reason": normalize_space(str(item.get("reason", ""))),
            })

    return {
        "file": path.name,
        "capabilities": capabilities,
        "count": len(capabilities),
        "declared_events": len(events),
        "declared_measures": len(measures),
        "excluded": excluded,
        "notes": normalize_space(str(data.get("notes", ""))),
    }



def main() -> None:
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY is not set.")

    client = OpenAI(
        timeout=60.0,
        max_retries=2,
    )

    # Resume existing results if capability_map.json already exists
    if OUTPUT_PATH.exists():
        try:
            output = json.loads(
                OUTPUT_PATH.read_text(encoding="utf-8")
            )
            print(f"Resuming from: {OUTPUT_PATH}")
        except Exception:
            output = {}
    else:
        output = {}

    if "_metadata" not in output:
        output["_metadata"] = {
            "model": MODEL,
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "definition": (
                "A system capability is a behavior, service, "
                "operation, or function that the system/agent "
                "itself can perform or provide."
            ),
            "review_required": True,
        }

    for use_case, (original_name, corrected_name) in CASE_FILES.items():

        versions = {
            "original": SLEEC_DIR / original_name,
            "corrected": SLEEC_DIR / corrected_name,
            "sleecpatch": (
                RESULTS_DIR
                / use_case
                / f"{use_case}_SLEECPATCH.sleec"
            ),
        }

        if use_case not in output:
            output[use_case] = {}

        for version, path in versions.items():

            if not path.exists():
                print(
                    f"SKIP {use_case}/{version}: "
                    f"{path} not found"
                )
                continue

            # Already successfully classified → don't call GPT again
            existing = output[use_case].get(version)

            if (
                isinstance(existing, dict)
                and "capabilities" in existing
                and "count" in existing
            ):
                print(
                    f"DONE {use_case}/{version}: "
                    f"{existing['count']} capabilities"
                )
                continue

            print(
                f"Classifying {use_case}/{version}: "
                f"{path.name}"
            )

            try:
                result = classify_spec(
                    client,
                    use_case,
                    version,
                    path,
                )

                output[use_case][version] = result

                # Save immediately
                OUTPUT_PATH.write_text(
                    json.dumps(output, indent=2),
                    encoding="utf-8",
                )

                print(
                    f"  -> {result['count']} capabilities"
                )

            except KeyboardInterrupt:
                print(
                    "\nInterrupted. Existing results have been saved."
                )
                OUTPUT_PATH.write_text(
                    json.dumps(output, indent=2),
                    encoding="utf-8",
                )
                return

            except Exception as exc:
                print(
                    f"ERROR {use_case}/{version}: {exc}"
                )
                print("Continuing to next specification...")
                continue

    OUTPUT_PATH.write_text(
        json.dumps(output, indent=2),
        encoding="utf-8",
    )

    print(f"\nWrote: {OUTPUT_PATH}")
    print(
        "IMPORTANT: review capability_map.json "
        "before using it for paper tables."
    )

if __name__ == "__main__":
    main()
