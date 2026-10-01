from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from openai import OpenAI


# ============================================================
# Paths
# ============================================================

APP_DIR = Path(__file__).resolve().parents[0]

if APP_DIR.name == "scripts":
    APP_DIR = APP_DIR.parent

SLEEC_DIR = APP_DIR / "sleec_usecases"
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
    "DressAssist": (
        "DRESSASSIST.sleec",
        "DRESSASSIST-corrected.sleec",
    ),
    "SafeSCAD": (
        "safescade.sleec",
        "safescade-corrected.sleec",
    ),
    "Tabiat": ("Tabiat.sleec", "Tabiat-corrected.sleec"),
}


MODEL = os.getenv(
    "CAPABILITY_CLASSIFIER_MODEL",
    "gpt-4o-mini",
)


# ============================================================
# Basic helpers
# ============================================================

def normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def extract_declared_symbols(
    text: str,
) -> tuple[list[str], list[str]]:

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

        if (
            not inside_defs
            or not line
            or line.startswith("//")
        ):
            continue

        m_event = re.match(
            r"^event\s+([A-Za-z_][A-Za-z0-9_]*)\b",
            line,
            re.IGNORECASE,
        )

        if m_event:
            events.append(m_event.group(1))
            continue

        m_measure = re.match(
            r"^measure\s+([A-Za-z_][A-Za-z0-9_]*)\b",
            line,
            re.IGNORECASE,
        )

        if m_measure:
            measures.append(m_measure.group(1))

    return (
        sorted(set(events)),
        sorted(set(measures)),
    )


def extract_rule_section(text: str) -> str:

    match = re.search(
        r"rule_start(.*?)rule_end",
        text,
        re.IGNORECASE | re.DOTALL,
    )

    return match.group(1).strip() if match else ""


def parse_json_object(raw: str) -> dict:

    raw = raw.strip()

    if raw.startswith("```"):
        raw = re.sub(
            r"^```(?:json)?\s*",
            "",
            raw,
            flags=re.IGNORECASE,
        )
        raw = re.sub(r"\s*```$", "", raw)

    start = raw.find("{")
    end = raw.rfind("}")

    if start == -1 or end == -1 or end < start:
        raise ValueError(
            f"Model did not return a JSON object:\n{raw}"
        )

    return json.loads(raw[start:end + 1])


# ============================================================
# Load one specification
# ============================================================

def load_spec(path: Path) -> dict:

    text = path.read_text(
        encoding="utf-8",
        errors="replace",
    )

    events, measures = extract_declared_symbols(text)

    return {
        "file": path.name,
        "events": events,
        "measures": measures,
        "declared_symbols": sorted(
            set(events) | set(measures)
        ),
        "rules": extract_rule_section(text),
    }


# ============================================================
# CANONICAL classification
# ============================================================

def classify_use_case(
    client: OpenAI,
    use_case: str,
    specs: dict,
) -> dict:
    """
    Classify every unique symbol ONCE for a use case.

    The resulting canonical classification is reused for
    original, corrected, and SLEEC-PATCH.
    """

    all_symbols = set()

    for spec in specs.values():
        all_symbols.update(spec["declared_symbols"])

    all_symbols = sorted(all_symbols)

    # Give the model context from ALL available versions.
    context_sections = []

    for version, spec in specs.items():

        context_sections.append(
            f"""
==============================
VERSION: {version}
FILE: {spec["file"]}

DECLARED EVENTS:
{json.dumps(spec["events"], indent=2)}

DECLARED MEASURES:
{json.dumps(spec["measures"], indent=2)}

RULES:
{spec["rules"]}
==============================
""".strip()
        )

    all_context = "\n\n".join(context_sections)

    prompt = f"""
You are classifying system capabilities for a SLEEC
normative requirements evaluation.

USE CASE:
{use_case}

IMPORTANT METHODOLOGICAL REQUIREMENT:

You are given multiple versions of the SAME use case:
the original specification, the manually corrected
specification, and, when available, the SLEEC-PATCH
specification.

Classify each unique declared symbol ONCE.

The classification of a symbol MUST be identical across
all specification versions.

Do NOT classify the same symbol as a capability in one
version and as a non-capability in another version.


DEFINITION

A SYSTEM CAPABILITY is a behavior, service, operation,
or function that the system/agent itself can perform
or provide.

Examples of system capabilities:

- CallEmergencyServices
- InformCaregiver
- ShowConsentForm
- CreateConsentForm
- RemindUser
- TakeControlForSafety


NOT SYSTEM CAPABILITIES

Do NOT classify a symbol as a capability merely because
it is declared as an event or measure.

Exclude symbols representing:

- user actions
- user states
- user characteristics
- environmental occurrences
- observations
- sensor states
- system states that are not actions/functions
- contextual facts
- Boolean conditions
- risk/state variables
- consent states
- measurements
- trigger conditions

Examples:

- HumanOnFloor -> NOT capability
- UserDriving -> NOT capability
- UserEnters -> NOT capability
- UserSaysStop -> NOT capability
- UserHasDifferentCulture -> NOT capability
- riskLevel -> NOT capability
- userOccupied -> NOT capability
- rulesFollowed -> NOT capability
- SystemOn -> NOT capability


IMPORTANT

A capability may appear:

- before THEN,
- after THEN,
- or in both positions.

Its rule position alone does NOT determine whether it
is a capability.

Positive and negative normative uses refer to the same
underlying capability.

For example:

    CallEmergencyServices

and

    not CallEmergencyServices

refer to the same capability.


UNION OF ALL DECLARED SYMBOLS

{json.dumps(all_symbols, indent=2)}


SPECIFICATION CONTEXT

{all_context}


Return ONLY valid JSON in this form:

{{
  "capabilities": [
    "ExactDeclaredSymbol"
  ],

  "excluded": [
    {{
      "symbol": "ExactDeclaredSymbol",
      "reason": "short classification reason"
    }}
  ],

  "notes": "short explanation of ambiguous cases"
}}


STRICT REQUIREMENTS

1. Every symbol in "capabilities" must come from the
   UNION OF ALL DECLARED SYMBOLS.

2. Every unique declared symbol must receive ONE stable
   classification for this use case.

3. Do not invent symbols.

4. Classify according to semantic meaning, not merely
   whether the symbol is syntactically an event.

5. User/context/environment symbols are not system
   capabilities even if they are declared as events.
""".strip()

    response = client.responses.create(
        model=MODEL,
        input=prompt,
        temperature=0,
    )

    data = parse_json_object(response.output_text)

    capabilities = sorted({
        str(x).strip()
        for x in data.get("capabilities", [])
        if str(x).strip()
    })

    unknown = [
        symbol
        for symbol in capabilities
        if symbol not in all_symbols
    ]

    if unknown:
        raise ValueError(
            f"{use_case}: model returned undeclared "
            f"symbols: {unknown}"
        )

    capability_set = set(capabilities)

    # Build a reason lookup.
    reason_lookup = {}

    for item in data.get("excluded", []):

        if not isinstance(item, dict):
            continue

        symbol = str(
            item.get("symbol", "")
        ).strip()

        reason = normalize_space(
            str(item.get("reason", ""))
        )

        if (
            symbol in all_symbols
            and symbol not in capability_set
        ):
            reason_lookup[symbol] = reason

    # Ensure every non-capability is represented.
    excluded = []

    for symbol in all_symbols:

        if symbol in capability_set:
            continue

        excluded.append({
            "symbol": symbol,
            "reason": reason_lookup.get(
                symbol,
                "classified as non-capability",
            ),
        })

    return {
        "capabilities": capabilities,
        "count": len(capabilities),
        "excluded": excluded,
        "notes": normalize_space(
            str(data.get("notes", ""))
        ),
    }


# ============================================================
# Apply canonical classification to one specification
# ============================================================

def apply_canonical_classification(
    spec: dict,
    canonical: dict,
) -> dict:

    declared = set(spec["declared_symbols"])

    canonical_capabilities = set(
        canonical["capabilities"]
    )

    capabilities = sorted(
        declared & canonical_capabilities
    )

    excluded_lookup = {
        item["symbol"]: item.get(
            "reason",
            "classified as non-capability",
        )
        for item in canonical["excluded"]
    }

    excluded = []

    for symbol in sorted(
        declared - canonical_capabilities
    ):
        excluded.append({
            "symbol": symbol,
            "reason": excluded_lookup.get(
                symbol,
                "classified as non-capability",
            ),
        })

    return {
        "file": spec["file"],
        "capabilities": capabilities,
        "count": len(capabilities),
        "declared_events": len(spec["events"]),
        "declared_measures": len(spec["measures"]),
        "excluded": excluded,
    }


# ============================================================
# Added / removed capability comparison
# ============================================================

def add_comparison_fields(
    case_result: dict,
) -> None:

    original = case_result.get("original")

    if not original:
        return

    original_caps = set(
        original.get("capabilities", [])
    )

    for version in (
        "corrected",
        "sleecpatch",
    ):

        spec = case_result.get(version)

        if not spec:
            continue

        current_caps = set(
            spec.get("capabilities", [])
        )

        spec["added_vs_original"] = sorted(
            current_caps - original_caps
        )

        spec["removed_vs_original"] = sorted(
            original_caps - current_caps
        )


# ============================================================
# Main
# ============================================================

def main() -> None:

    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError(
            "OPENAI_API_KEY is not set."
        )

    client = OpenAI(
        timeout=60.0,
        max_retries=2,
    )

    # IMPORTANT:
    # Generate a fresh canonical map.
    # Do not resume the old independently classified map.
    output = {
        "_metadata": {
            "model": MODEL,
            "generated_at_utc": (
                datetime.now(timezone.utc).isoformat()
            ),
            "method": (
                "canonical_use_case_level_classification"
            ),
            "definition": (
                "A system capability is a behavior, "
                "service, operation, or function that "
                "the system/agent itself can perform "
                "or provide."
            ),
            "classification_scope": (
                "Each unique declared symbol is "
                "classified once per use case using "
                "all available specification versions."
            ),
            "review_required": True,
        }
    }

    for (
        use_case,
        (original_name, corrected_name),
    ) in CASE_FILES.items():

        print(f"\n=== {use_case} ===")

        paths = {
            "original": (
                SLEEC_DIR / original_name
            ),
            "corrected": (
                SLEEC_DIR / corrected_name
            ),
            "sleecpatch": (
                RESULTS_DIR
                / use_case
                / f"{use_case}_SLEECPATCH.sleec"
            ),
        }

        specs = {}

        for version, path in paths.items():

            if not path.exists():
                print(
                    f"SKIP {version}: "
                    f"{path} not found"
                )
                continue

            # Ignore effectively empty files.
            if path.stat().st_size <= 1:
                print(
                    f"SKIP {version}: "
                    f"{path.name} is empty"
                )
                continue

            specs[version] = load_spec(path)

            print(
                f"Loaded {version}: "
                f"{path.name} "
                f"({len(specs[version]['declared_symbols'])} "
                f"declared symbols)"
            )

        if not specs:
            print(
                f"SKIP {use_case}: "
                "no usable specifications"
            )
            continue

        print(
            "Classifying canonical capability "
            "vocabulary..."
        )

        try:

            canonical = classify_use_case(
                client,
                use_case,
                specs,
            )

            case_result = {
                "canonical": canonical,
            }

            for version, spec in specs.items():

                case_result[version] = (
                    apply_canonical_classification(
                        spec,
                        canonical,
                    )
                )

            add_comparison_fields(case_result)

            output[use_case] = case_result

            # Save after each use case.
            OUTPUT_PATH.write_text(
                json.dumps(
                    output,
                    indent=2,
                ),
                encoding="utf-8",
            )

            print(
                "Canonical capabilities:",
                canonical["count"],
            )

            for version in (
                "original",
                "corrected",
                "sleecpatch",
            ):

                if version not in case_result:
                    continue

                result = case_result[version]

                print(
                    f"  {version}: "
                    f"{result['count']}"
                )

                if version != "original":

                    print(
                        "    added:",
                        result.get(
                            "added_vs_original",
                            [],
                        ),
                    )

                    print(
                        "    removed:",
                        result.get(
                            "removed_vs_original",
                            [],
                        ),
                    )

        except KeyboardInterrupt:

            print(
                "\nInterrupted. Results already "
                "completed have been saved."
            )
            return

        except Exception as exc:

            print(
                f"ERROR {use_case}: {exc}"
            )
            print(
                "Continuing to next use case..."
            )
            continue

    OUTPUT_PATH.write_text(
        json.dumps(
            output,
            indent=2,
        ),
        encoding="utf-8",
    )

    print(
        f"\nWrote: {OUTPUT_PATH}"
    )

    print(
        "IMPORTANT: review the canonical "
        "classification before using capability "
        "counts in the paper."
    )


if __name__ == "__main__":
    main()