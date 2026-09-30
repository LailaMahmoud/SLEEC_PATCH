from __future__ import annotations

import argparse
import json
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Sequence, Tuple
from services.manual_similarity_evaluator import ManualSimilarityEvaluator
APP_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = APP_DIR.parents[1]

# The application is under:
#   <repo>/SLEECpatch/app
# while the database and generated results are under:
#   <repo>/instance
#   <repo>/results
DB_PATH = REPO_ROOT / "instance" / "sleec_patch_results.db"
SLEEC_DIR = APP_DIR / "sleec_usecases"
RESULTS_DIR = REPO_ROOT / "results"
OUTPUT_DIR = APP_DIR / "overleaf_generated"

CASE_FILES = {
    "ALMI": ("ALMI.sleec", "ALMI-corrected.sleec"),
    "ASPEN": ("aspen.sleec", "aspen-corrected.sleec"),
    "AutoCAR": ("Autocar.sleec", "Autocar-corrected.sleec"),
    "BSN": ("BSN.sleec", "BSN-corrected.sleec"),
    "CSICobot": ("CSI.sleec", "CSI-corrected.sleec"),
    "DAISY": ("Daisy.sleec", "Daisy-corrected.sleec"),
    "DPA": ("DPA.sleec", "DPA-corrected.sleec"),
    "DressAssist": ("DRESSASSIST.sleec", "DRESSASSIST-corrected.sleec"),
    "SafeSCAD": ("safescade.sleec", "safescade-corrected.sleec"),
    "Tabiat": ("Tabiat.sleec", "Tabiat-corrected.sleec"),
    "Casper": ("Casper.sleec", "Casper-corrected.sleec"),
}


def discover_case_files() -> Dict[str, Tuple[str, str]]:
    """
    Discover all SLEEC use cases automatically.

    Corrected files are matched using -corrected.sleec or _corrected.sleec.
    CASE_FILES is retained only as a compatibility fallback for historical
    filenames/canonical labels.
    """
    discovered: Dict[str, Tuple[str, str]] = {}
    files = list(SLEEC_DIR.glob("*.sleec"))

    corrected_lookup = {
        p.name.lower(): p.name
        for p in files
        if "-corrected" in p.name.lower() or "_corrected" in p.name.lower()
    }

    for original in files:
        low = original.name.lower()
        if "-corrected" in low or "_corrected" in low:
            continue

        stem = original.stem
        corrected_name = ""
        for candidate in (
            f"{stem}-corrected.sleec",
            f"{stem}_corrected.sleec",
        ):
            found = corrected_lookup.get(candidate.lower())
            if found:
                corrected_name = found
                break

        discovered[stem] = (original.name, corrected_name)

    for case, (original_name, corrected_name) in CASE_FILES.items():
        original = SLEEC_DIR / original_name
        corrected = SLEEC_DIR / corrected_name
        if original.exists():
            discovered[case] = (
                original.name,
                corrected.name if corrected.exists() else ""
            )

    return discovered


LATEX_REPLACEMENTS = {
    "\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$",
    "#": r"\#", "_": r"\_", "{": r"\{", "}": r"\}",
    "~": r"\textasciitilde{}", "^": r"\textasciicircum{}",
}


def latex_escape(value: object) -> str:
    text = "" if value is None else str(value)
    return "".join(LATEX_REPLACEMENTS.get(ch, ch) for ch in text)


def yes_no(value: object) -> str:
    return "Yes" if bool(value) else "No"


def compact_wfi(issue_type: str) -> str:
    labels = {
        "concerns": "Concern", "concern": "Concern",
        "conflicts": "Conflict", "conflict": "Conflict",
        "situational_conflicts": "Sit. conflict",
        "situational_conflict": "Sit. conflict",
        "redundancies": "Redundancy", "redundancy": "Redundancy",
        "purpose_blocking": "Purpose", "purpose": "Purpose",
    }
    return labels.get(issue_type, issue_type)


def extract_rule_ids(*values: object) -> str:
    ids: List[str] = []
    pattern = re.compile(r"\b(?:Rule|R|r)\d+(?:_\d+)?\b")
    for value in values:
        for rule_id in pattern.findall(str(value or "")):
            if rule_id not in ids:
                ids.append(rule_id)
    return ", ".join(ids)


def database_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {
        row[1]
        for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
    }


def table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        """
        SELECT 1
        FROM sqlite_master
        WHERE type = 'table' AND name = ?
        """,
        (table,),
    ).fetchone()
    return row is not None


def safe_json(value: object) -> dict:
    if isinstance(value, dict):
        return value

    if not value:
        return {}

    try:
        parsed = json.loads(str(value))
        return parsed if isinstance(parsed, dict) else {}
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}


def load_verification_rankings(
    conn: sqlite3.Connection,
) -> Dict[Tuple[str, str, str], Dict[str, float]]:
    """
    Read rank/ranking_score from sleec_patch_verifications.

    The store may keep ranking information either in explicit columns,
    ranking_json, or patch_json. This function supports all three layouts.
    """
    if not table_exists(conn, "sleec_patch_verifications"):
        return {}

    columns = database_columns(conn, "sleec_patch_verifications")
    rows = conn.execute(
        "SELECT * FROM sleec_patch_verifications"
    ).fetchall()

    rankings: Dict[Tuple[str, str, str], Dict[str, float]] = {}

    for row in rows:
        data = dict(row)
        patch_json = safe_json(data.get("patch_json"))
        ranking_json = safe_json(data.get("ranking_json"))

        use_case = str(
            data.get("use_case")
            or patch_json.get("use_case")
            or ""
        )
        issue_id = str(
            data.get("issue_id")
            or patch_json.get("issue_id")
            or ""
        )
        patch_id = str(
            data.get("patch_id")
            or patch_json.get("patch_id")
            or patch_json.get("id")
            or ""
        )

        if not patch_id:
            continue

        rank = (
            data.get("rank")
            if "rank" in columns
            else None
        )
        if rank in (None, "", 0, "0"):
            rank = (
                ranking_json.get("rank")
                or patch_json.get("rank")
                or 0
            )

        ranking_score = (
            data.get("ranking_score")
            if "ranking_score" in columns
            else None
        )
        if ranking_score in (None, ""):
            ranking_score = (
                ranking_json.get("ranking_score")
                or ranking_json.get("score")
                or patch_json.get("ranking_score")
                or 0
            )

        key = (use_case, issue_id, patch_id)
        rankings[key] = {
            "rank": int(rank or 0),
            "ranking_score": float(ranking_score or 0),
        }

    return rankings


def load_verified_patch_rows(db_path: Path) -> List[dict]:
    if not db_path.exists():
        raise FileNotFoundError(
            "Results database not found: "
            f"{db_path}\n"
            "Expected repository layout:\n"
            "  <repo>/instance/sleec_patch_results.db"
        )

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    if not table_exists(conn, "sleec_patch_results"):
        conn.close()
        raise RuntimeError(
            "The database does not contain table "
            "'sleec_patch_results'."
        )

    result_columns = database_columns(conn, "sleec_patch_results")

    rank_expr = (
        "rank"
        if "rank" in result_columns
        else "0 AS rank"
    )
    score_expr = (
        "ranking_score"
        if "ranking_score" in result_columns
        else "0 AS ranking_score"
    )

    result_rows = conn.execute(f"""
        SELECT
            id,
            use_case,
            issue_id,
            issue_type,
            selected_issue,
            generation_time_seconds,
            validation_time_seconds,
            total_time_seconds,
            patch_id,
            operation,
            source,
            target_rule_id,
            proposed_rule,
            rules_modified,
            rules_added,
            rules_deleted,
            defeaters_added,
            conditions_refined,
            actions_refined,
            capabilities_refined,
            verified,
            expert_similarity,
            requires_social_scientist_review,
            timestamp,
            {rank_expr},
            {score_expr}
        FROM sleec_patch_results
        WHERE verified = 1
        ORDER BY use_case, issue_id, timestamp, id
    """).fetchall()

    verification_rankings = load_verification_rankings(conn)
    conn.close()

    rows: List[dict] = []

    for sqlite_row in result_rows:
        row = dict(sqlite_row)
        key = (
            str(row.get("use_case") or ""),
            str(row.get("issue_id") or ""),
            str(row.get("patch_id") or ""),
        )
        verification = verification_rankings.get(key, {})

        if not int(row.get("rank") or 0):
            row["rank"] = int(verification.get("rank", 0))

        if not float(row.get("ranking_score") or 0):
            row["ranking_score"] = float(
                verification.get("ranking_score", 0)
            )

        rows.append(row)

    return rows


def latest_rows_per_patch(rows: Sequence[dict]) -> List[dict]:
    latest: Dict[Tuple[str, str, str], dict] = {}
    for row in rows:
        key = (row["use_case"], row["issue_id"], row["patch_id"])
        previous = latest.get(key)
        if previous is None or str(row["timestamp"]) >= str(previous["timestamp"]):
            latest[key] = row
    return sorted(latest.values(), key=lambda r: (str(r["use_case"]), str(r["issue_id"]), str(r["patch_id"])))
def compute_manual_similarity(rows: Sequence[dict]) -> List[dict]:
    """
    Compute patch-level M-Sim for verified patches using the same
    ManualSimilarityEvaluator used by evaluate_manual_similarity_legacy.py.

    This is read-only: it does not modify the evaluation database.
    """

    evaluator = ManualSimilarityEvaluator()
    case_files = discover_case_files()

    # Explicit aliases between DB use-case labels and SLEEC filenames.
    case_aliases = {
        "CSICobot": "CSI",
        "SafeSCAD": "safescade",
    }

    text_cache: Dict[str, Tuple[str, str]] = {}
    evaluated_rows: List[dict] = []

    for source_row in rows:
        row = dict(source_row)

        use_case = str(row.get("use_case") or "").strip()

        # ----------------------------------------------------
        # Find original/corrected SLEEC files
        # ----------------------------------------------------
        if use_case not in text_cache:

            file_pair = case_files.get(use_case)

            if file_pair is None:
                alias = case_aliases.get(use_case, use_case)

                # Case-insensitive fallback
                for discovered_case, pair in case_files.items():
                    if discovered_case.lower() == alias.lower():
                        file_pair = pair
                        break

            if not file_pair:
                print(
                    f"WARNING: no SLEEC files found for {use_case}; "
                    "M-Sim set to 0."
                )
                row["expert_similarity"] = 0.0
                evaluated_rows.append(row)
                continue

            original_name, corrected_name = file_pair

            original_path = SLEEC_DIR / original_name
            corrected_path = SLEEC_DIR / corrected_name

            if not original_path.exists() or not corrected_path.exists():
                print(
                    f"WARNING: original/corrected SLEEC missing for "
                    f"{use_case}; M-Sim set to 0."
                )
                row["expert_similarity"] = 0.0
                evaluated_rows.append(row)
                continue

            text_cache[use_case] = (
                original_path.read_text(encoding="utf-8"),
                corrected_path.read_text(encoding="utf-8"),
            )

        original_text, corrected_text = text_cache[use_case]

        # ----------------------------------------------------
        # Calculate M-Sim
        # ----------------------------------------------------
        result = evaluator.evaluate(
            operation=str(row.get("operation") or ""),
            target_rule_id=str(row.get("target_rule_id") or ""),
            proposed_rule=str(row.get("proposed_rule") or ""),
            original_text=original_text,
            corrected_text=corrected_text,
        )

        row["expert_similarity"] = float(
                result.get("m_sim", 0.0)
            )

        # ----------------------------------------------------
        # Store detailed M-Sim components for Overleaf export
        # ----------------------------------------------------
        components = result.get("components") or {}

        row["msim_target"] = components.get("target")
        row["msim_trigger"] = components.get("trigger")
        row["msim_response"] = components.get("response")
        row["msim_polarity"] = components.get("polarity")
        row["msim_defeater"] = components.get("defeater")
        row["msim_temporal"] = components.get("temporal")

        # Matched expert-authored rule
        expert = result.get("matched_expert_rule")

        if expert is not None:
            row["msim_expert_rule"] = (
                expert.raw
                if hasattr(expert, "raw")
                else str(expert)
            )
        else:
            row["msim_expert_rule"] = ""

        # IMPORTANT: append every verified patch
        evaluated_rows.append(row)

    return evaluated_rows

def filter_rows_by_use_case(
    rows: Sequence[dict],
    use_case: str = "",
) -> List[dict]:
    if not use_case:
        return list(rows)
    return [
        row for row in rows
        if str(row.get("use_case") or "") == use_case
    ]


def export_suffix(use_case: str = "") -> str:
    if not use_case:
        return "all"
    suffix = re.sub(r"[^A-Za-z0-9._-]+", "-", use_case.strip()).strip("-")
    return suffix.lower() or "all"


def generate_patch_results_table(rows: Sequence[dict]) -> str:
    """
    TABLE ONE: verified patch-generation results.

    Uses database results only. It does NOT read corrected.sleec.
    """
    patch_counts: Dict[Tuple[str, str], int] = {}
    for row in rows:
        key = (str(row.get("use_case") or ""), str(row.get("issue_id") or ""))
        patch_counts[key] = patch_counts.get(key, 0) + 1

    lines = [
        r"\begin{table*}[t]",
        r"\caption{Verified SLEEC-PATCH generation results. RM, RA, RD, DA, TR, RR, and CR denote rules modified, rules added, rules deleted, defeaters added, trigger refinements, response refinements, and capability refinements, respectively. Gen. and Val. denote generation and validation time in seconds.}",
        r"\label{tab:patch-results}",
        r"\centering",
        r"\scriptsize",
        r"\setlength{\tabcolsep}{2.3pt}",
        r"\resizebox{\textwidth}{!}{%",
        r"\begin{tabular}{lllrrrrllrrrrrrrrlll}",
        r"\toprule",
        r"Case & IID & WFI & \#Patch & Total & Gen. & Val. & PID & Op. & RM & RA & RD & DA & TR & RR & CR & Rank & M-Sim. & Source & E-Review \\",
        r"\midrule",
    ]

    if not rows:
        lines.append(r"\multicolumn{20}{c}{No verified patch results were found.}\\")
    else:
        previous_case = None
        previous_issue = None

        for row in rows:
            case = str(row.get("use_case") or "")
            issue_id = str(row.get("issue_id") or "")
            issue_key = (case, issue_id)

            if previous_case is not None and case != previous_case:
                lines.append(r"\midrule")

            first_issue_row = issue_key != previous_issue

            rank = int(row.get("rank") or 0)
            values = [
                latex_escape(case) if case != previous_case else "",
                latex_escape(issue_id) if first_issue_row else "",
                latex_escape(compact_wfi(str(row.get("issue_type") or ""))) if first_issue_row else "",
                str(patch_counts[issue_key]) if first_issue_row else "",
                f'{float(row.get("total_time_seconds") or 0):.2f}' if first_issue_row else "",
                f'{float(row.get("generation_time_seconds") or 0):.2f}' if first_issue_row else "",
                f'{float(row.get("validation_time_seconds") or 0):.2f}' if first_issue_row else "",
                latex_escape(row.get("patch_id")),
                latex_escape(row.get("operation")),
                str(int(row.get("rules_modified") or 0)),
                str(int(row.get("rules_added") or 0)),
                str(int(row.get("rules_deleted") or 0)),
                str(int(row.get("defeaters_added") or 0)),
                str(int(row.get("conditions_refined") or 0)),
                str(int(row.get("actions_refined") or 0)),
                str(int(row.get("capabilities_refined") or 0)),
                str(rank) if rank > 0 else "--",
                f'{float(row.get("expert_similarity") or 0):.2f}',
                latex_escape(row.get("source")),
                yes_no(row.get("requires_social_scientist_review")),
            ]
            lines.append(" & ".join(values) + r" \\")

            previous_case = case
            previous_issue = issue_key

    lines += [r"\bottomrule", r"\end{tabular}%", r"}", r"\end{table*}", ""]
    return "\n".join(lines)


RULE_START_RE = re.compile(r"^(?P<id>(?:Rule|R|r)\d+(?:_\d+)?)\s+when\b", re.IGNORECASE)


@dataclass
class ParsedSpec:
    rules: Dict[str, str]
    capabilities: set[str]
    defeater_count: int
    constraint_count: int


def normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def parse_rule_blocks(text: str) -> Dict[str, str]:
    rules: Dict[str, str] = {}
    inside_rules = False
    current_id = ""
    current_lines: List[str] = []

    def flush() -> None:
        nonlocal current_id, current_lines
        if current_id:
            rules[current_id] = normalize_space(" ".join(current_lines))
        current_id = ""
        current_lines = []

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.lower() == "rule_start":
            inside_rules = True
            continue
        if line.lower() == "rule_end":
            flush()
            break
        if not inside_rules or not line or line.startswith("//"):
            continue
        match = RULE_START_RE.match(line)
        if match:
            flush()
            current_id = match.group("id")
            current_lines = [line]
        elif current_id:
            current_lines.append(line)
    flush()
    return rules


def remove_rule_id(rule_text: str) -> str:
    return re.sub(r"^(?:Rule|R|r)\d+(?:_\d+)?\s+", "", normalize_space(rule_text), flags=re.IGNORECASE)


def action_from_rule(rule_text: str) -> str:
    match = re.search(r"\bthen\s+(.+?)(?:\s+unless\s+|$)", normalize_space(rule_text), flags=re.IGNORECASE)
    if not match:
        return ""
    action = re.sub(r"\s+within\s+.+$", "", match.group(1), flags=re.IGNORECASE)
    action = re.sub(r"^not\s+", "", action, flags=re.IGNORECASE)
    return normalize_space(action)


def condition_from_rule(rule_text: str) -> str:
    match = re.search(r"\bwhen\s+(.+?)\s+then\b", normalize_space(rule_text), flags=re.IGNORECASE)
    return normalize_space(match.group(1)) if match else ""


def defeater_from_rule(rule_text: str) -> str:
    match = re.search(r"\bunless\s+(.+?)(?:\s+then\s+|$)", normalize_space(rule_text), flags=re.IGNORECASE)
    return normalize_space(match.group(1)) if match else ""


def atomic_constraint_count(expression: str) -> int:
    expression = normalize_space(expression)
    if not expression:
        return 0
    parts = re.split(r"\s+(?:and|or)\s+", expression, flags=re.IGNORECASE)
    return sum(1 for part in parts if part.strip(" (){}"))


def extract_declared_capabilities(text: str) -> set[str]:
    """
    Return unique declared SLEEC events and measures.

    For the evaluation table:
    #C = number of unique declared events + measures.
    """
    events: set[str] = set()
    measures: set[str] = set()
    inside_defs = False

    for raw_line in text.splitlines():
        line = raw_line.strip()
        low = line.lower()

        if low == "def_start":
            inside_defs = True
            continue

        if low == "def_end":
            break

        if not inside_defs or not line or line.startswith("//"):
            continue

        event_match = re.match(
            r"^event\s+([A-Za-z_][A-Za-z0-9_]*)\b",
            line,
            re.IGNORECASE,
        )
        if event_match:
            events.add(event_match.group(1))
            continue

        measure_match = re.match(
            r"^measure\s+([A-Za-z_][A-Za-z0-9_]*)\b",
            line,
            re.IGNORECASE,
        )
        if measure_match:
            measures.add(measure_match.group(1))

    return events | measures
def parse_spec(path: Path) -> ParsedSpec:
    if not path.exists():
        return ParsedSpec({}, set(), 0, 0)
    text = path.read_text(encoding="utf-8", errors="replace")
    rules = parse_rule_blocks(text)
    #capabilities = {action_from_rule(rule) for rule in rules.values() if action_from_rule(rule)}
    capabilities = extract_declared_capabilities(text)
    defeater_count = sum(1 for rule in rules.values() if defeater_from_rule(rule))
    constraint_count = sum(
        atomic_constraint_count(condition_from_rule(rule)) + atomic_constraint_count(defeater_from_rule(rule))
        for rule in rules.values()
    )
    return ParsedSpec(rules, capabilities, defeater_count, constraint_count)


@dataclass
class SpecDiff:
    modified: List[str]
    deleted: List[str]
    added: List[str]


def compare_specs(original: ParsedSpec, target: ParsedSpec) -> SpecDiff:
    original_ids = set(original.rules)
    target_ids = set(target.rules)
    modified = sorted(
        rid for rid in original_ids & target_ids
        if remove_rule_id(original.rules[rid]).lower() != remove_rule_id(target.rules[rid]).lower()
    )
    return SpecDiff(modified, sorted(original_ids - target_ids), sorted(target_ids - original_ids))


def format_ids(ids: Iterable[str]) -> str:
    values = list(ids)
    return ", ".join(values) if values else "--"


def spec_summary(spec: ParsedSpec) -> str:
    return f"{len(spec.rules)} ({len(spec.capabilities)}, {spec.defeater_count}, {spec.constraint_count})"


def generate_spec_comparison_table(
    use_cases: Sequence[str] | None = None,
) -> str:
    """
    TABLE TWO only.

    This is the only table that reads corrected.sleec because it explicitly
    compares Original vs Manually Corrected vs final SLEEC-PATCH.
    """
    lines = [
        r"\begin{table*}[t]",
        r"\caption{Comparison of original, manually corrected, and SLEEC-PATCH specifications. Each specification is reported as \#Rules (\#Capabilities, \#Defeaters, \#Constraints). ID-MR, ID-MD, and ID-RA denote modified, deleted, and added rule IDs.}",
        r"\label{tab:spec-comparison}", r"\centering", r"\scriptsize", r"\setlength{\tabcolsep}{3pt}",
        r"\resizebox{\textwidth}{!}{%",
        r"\begin{tabular}{llllllllll}", r"\toprule",
        r"\multirow{2}{*}{Case} & \multirow{2}{*}{Original} & \multicolumn{4}{c}{Manually corrected} & \multicolumn{4}{c}{SLEEC-PATCH} \\",
        r"\cmidrule(lr){3-6}\cmidrule(lr){7-10}",
        r"& & Spec. & ID-MR & ID-MD & ID-RA & Spec. & ID-MR & ID-MD & ID-RA \\", r"\midrule",
    ]
    selected_use_cases = set(use_cases or [])

    for use_case, (original_name, corrected_name) in discover_case_files().items():
        if selected_use_cases and use_case not in selected_use_cases:
            continue
        original_path = SLEEC_DIR / original_name
        if not original_path.exists():
            continue
        corrected_path = (SLEEC_DIR / corrected_name) if corrected_name else Path('__missing_corrected__.sleec')
        generated_path = RESULTS_DIR / use_case / f"{use_case}_SLEECPATCH.sleec"
        original = parse_spec(original_path)
        corrected = parse_spec(corrected_path)
        generated = parse_spec(generated_path)
        corrected_diff = compare_specs(original, corrected)
        generated_diff = compare_specs(original, generated)
        values = [
            latex_escape(use_case), latex_escape(spec_summary(original)),
            latex_escape(spec_summary(corrected)) if corrected.rules else "--",
            latex_escape(format_ids(corrected_diff.modified)) if corrected.rules else "--",
            latex_escape(format_ids(corrected_diff.deleted)) if corrected.rules else "--",
            latex_escape(format_ids(corrected_diff.added)) if corrected.rules else "--",
            latex_escape(spec_summary(generated)) if generated.rules else "--",
            latex_escape(format_ids(generated_diff.modified)) if generated.rules else "--",
            latex_escape(format_ids(generated_diff.deleted)) if generated.rules else "--",
            latex_escape(format_ids(generated_diff.added)) if generated.rules else "--",
        ]
        lines.append(" & ".join(values) + r" \\")
    lines += [r"\bottomrule", r"\end{tabular}%", r"}", r"\end{table*}", ""]
    return "\n".join(lines)

def generate_manual_similarity_details_table(
    rows: Sequence[dict],
) -> str:
    """
    Detailed component-level Manual Similarity (M-Sim) table.

    Uses the M-Sim values already computed by
    compute_manual_similarity(). No similarity is recomputed here.
    """

    def score(value):
        if value is None:
            return "--"
        try:
            return f"{float(value):.2f}"
        except (TypeError, ValueError):
            return "--"

    def expert_rule_id(value):
        """
        Keep only the expert rule identifier in the table.
        Example:
            'R3b when HumanOnFloor then AskCallHelp'
        becomes:
            'R3b'
        """
        text = str(value or "").strip()

        if not text:
            return "--"

        return text.split()[0]

    lines = [
        r"\begin{table*}[t]",
        (
            r"\caption{Component-level manual similarity (M-Sim) "
            r"for formally verified SLEEC-PATCH repairs. "
            r"Trig., Resp., Pol., Def., and Temp. denote trigger, "
            r"response, polarity, defeater, and temporal similarity, "
            r"respectively. A dash indicates that a component is not "
            r"applicable to the repair comparison.}"
        ),
        r"\label{tab:manual-similarity-details}",
        r"\centering",
        r"\scriptsize",
        r"\setlength{\tabcolsep}{2.5pt}",
        r"\resizebox{\textwidth}{!}{%",
        r"\begin{tabular}{lllllllrrrrrr}",
        r"\toprule",
        (
            r"Case & IID & PID & Op. & Source & Target & Expert "
            r"& Trig. & Resp. & Pol. & Def. & Temp. & M-Sim \\"
        ),
        r"\midrule",
    ]

    if not rows:
        lines.append(
            r"\multicolumn{13}{c}{No verified patches were found.}\\"
        )
    else:
        previous_case = None

        for row in rows:
            case = str(row.get("use_case") or "")

            if previous_case is not None and case != previous_case:
                lines.append(r"\midrule")

            values = [
                latex_escape(case),
                latex_escape(row.get("issue_id")),
                latex_escape(row.get("patch_id")),
                latex_escape(row.get("operation")),
                latex_escape(row.get("source") or "--"),
                latex_escape(row.get("target_rule_id") or "--"),
                latex_escape(
                    expert_rule_id(
                        row.get("msim_expert_rule")
                    )
                ),
                score(row.get("msim_trigger")),
                score(row.get("msim_response")),
                score(row.get("msim_polarity")),
                score(row.get("msim_defeater")),
                score(row.get("msim_temporal")),
                score(row.get("expert_similarity")),
            ]

            lines.append(
                " & ".join(values) + r" \\"
            )

            previous_case = case

    lines += [
        r"\bottomrule",
        r"\end{tabular}%",
        r"}",
        r"\end{table*}",
        "",
    ]

    return "\n".join(lines)
def build_overleaf_exports(
    db_path: Path = DB_PATH,
    use_case: str = "",
) -> Dict[str, str]:
    rows = latest_rows_per_patch(
    filter_rows_by_use_case(
        load_verified_patch_rows(db_path),
        use_case=use_case,
    )
)

    # Compute fresh patch-level M-Sim using the expert-corrected SLEEC.
    # This updates only the in-memory rows; the database remains unchanged.
    rows = compute_manual_similarity(rows)

    selected_cases = [use_case] if use_case else None
    patch_results = generate_patch_results_table(rows)

    manual_similarity_details = (
        generate_manual_similarity_details_table(rows)
    )

    spec_comparison = generate_spec_comparison_table(
        selected_cases
    )

    bundle_lines = [
    "% Auto-generated by SLEEC-PATCH.",
    "% Import this file or copy the tables below into Overleaf.",
    "",
    patch_results.strip(),
    "",
    manual_similarity_details.strip(),
    "",
    spec_comparison.strip(),
    "",
]
    suffix = export_suffix(use_case)

    return {
    f"sleec_patch_report_{suffix}.tex": "\n".join(bundle_lines),

    f"table_patch_results_{suffix}.tex":
        patch_results,

    f"table_manual_similarity_details_{suffix}.tex":
        manual_similarity_details,

    f"table_spec_comparison_{suffix}.tex":
        spec_comparison,
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate Overleaf LaTeX tables from SLEEC-PATCH runs.")
    parser.add_argument("--db", type=Path, default=DB_PATH)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Database: {args.db}")
    print(f"SLEEC files: {SLEEC_DIR}")
    print(f"Generated results: {RESULTS_DIR}")

    exports = build_overleaf_exports(args.db)
    patch_results = exports["table_patch_results_all.tex"]
    manual_similarity_details = exports[
        "table_manual_similarity_details_all.tex"
    ]
    spec_comparison = exports["table_spec_comparison_all.tex"]

    (args.output_dir / "table_patch_results.tex").write_text(
        patch_results,
        encoding="utf-8"
    )
    (args.output_dir / "table_spec_comparison.tex").write_text(
        spec_comparison,
        encoding="utf-8"
    )
    (args.output_dir / "table_manual_similarity_details.tex").write_text(
        manual_similarity_details,
        encoding="utf-8"
    )
    print(
        "Verified patch rows: "
        f"{len(latest_rows_per_patch(load_verified_patch_rows(args.db)))}"
    )
    print(f"Wrote: {args.output_dir / 'table_patch_results.tex'}")
    print(f"Wrote: {args.output_dir / 'table_spec_comparison.tex'}")
    print(
    f"Wrote: {args.output_dir / 'table_manual_similarity_details.tex'}"
    )


if __name__ == "__main__":
    main()
