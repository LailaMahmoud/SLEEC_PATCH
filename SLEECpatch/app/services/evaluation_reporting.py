"""Report saved evidence without confusing diagnoses, repair runs and patches."""
from collections import defaultdict
import json
import math


ISSUE_TYPES = ("concerns", "conflicts", "purpose_blocking", "redundancies", "situational_conflicts")


def enabled(value):
    return value is True or value == 1 or value == "1"


def count_by(rows, field):
    counts = defaultdict(int)
    for row in rows:
        counts[row.get(field) or "Unknown"] += 1
    return dict(counts)


def average(rows, field):
    values = []
    for row in rows:
        try:
            value = float(row[field])
        except (KeyError, TypeError, ValueError):
            continue
        if math.isfinite(value) and value >= 0:
            values.append(value)
    return round(sum(values) / len(values), 3) if values else None


def report_metrics(rows, runs=()):
    return {
        "total_patch_rows": len(rows),
        "verified_patch_rows": sum(enabled(row.get("verified")) for row in rows),
        "llm_patch_rows": sum(str(row.get("source", "")).lower() == "llm" for row in rows),
        "deterministic_patch_rows": sum(str(row.get("source", "")).lower() == "deterministic" for row in rows),
        "social_review_required_rows": sum(enabled(row.get("requires_social_scientist_review")) for row in rows),
        "philosopher_reviewed_rows": sum(bool(row.get("philosopher_decision")) for row in rows),
        # Preserve these legacy patch-weighted fields for existing API consumers.
        "avg_attempts": average(rows, "attempts"),
        "avg_total_time_seconds": average(rows, "total_time_seconds"),
        "repair_run_count": len(runs),
        "avg_run_time_seconds": average(runs, "total_time_seconds"),
        "avg_run_attempts": average(runs, "attempts"),
        **{f"by_{field}": count_by(rows, field) for field in ("use_case", "issue_type", "operation", "source")},
    }


def evaluation_summary(rows, runs):
    groups, run_groups = defaultdict(list), defaultdict(list)
    for row in rows:
        groups[row.get("use_case") or "Unknown"].append(row)
    for run in runs:
        run_groups[run.get("use_case") or "Unknown"].append(run)
    result = []
    for use_case in sorted(groups.keys() | run_groups.keys()):
        patches, case_runs = groups[use_case], run_groups[use_case]
        metrics = report_metrics(patches, case_runs)
        result.append({
            "use_case": use_case, "total_records": len(patches),
            "verified_patches": metrics["verified_patch_rows"],
            "avg_attempts": metrics["avg_attempts"],
            "avg_total_time": metrics["avg_total_time_seconds"],
            "avg_generation_time": average(patches, "generation_time_seconds"),
            "avg_validation_time": average(patches, "validation_time_seconds"),
            "avg_expert_similarity": average(patches, "expert_similarity"),
            "repair_run_count": len(case_runs),
            "avg_run_attempts": metrics["avg_run_attempts"],
            "avg_run_time": metrics["avg_run_time_seconds"],
            "social_review_needed": metrics["social_review_required_rows"],
            **{field: sum(row.get(field) or 0 for row in patches)
               for field in ("rules_modified", "rules_added", "rules_deleted", "defeaters_added",
                             "conditions_refined", "actions_refined", "capabilities_refined")},
        })
    return result


def recorded_diagnoses(runs):
    records = []
    for run in runs:
        try:
            structured = json.loads(run.get("original_structured_json") or "null")
        except (TypeError, ValueError):
            structured = None
        complete = isinstance(structured, dict) and all(isinstance(structured.get(key), list) for key in ISSUE_TYPES)
        counts = {key: len(structured[key]) for key in ISSUE_TYPES} if complete else None
        total = sum(counts.values()) if counts is not None else None
        recorded_total = run.get("original_issue_count")
        mismatch = total is not None and recorded_total is not None and recorded_total != total
        records.append({
            "run_id": run.get("run_id", ""), "use_case": run.get("use_case", ""),
            "selected_issue_id": run.get("issue_id", ""), "timestamp": run.get("timestamp", ""),
            "input_sha256": run.get("input_sha256") or "",
            "issue_count": None if mismatch else total,
            "counts_by_type": counts,
            "status": "inconsistent_record" if mismatch else "recorded" if complete else "unavailable",
        })
    return records


def review_metrics(rows):
    def empty():
        return dict(total=0, accepted=0, rejected=0, pending=0, acceptance_rate=0)
    overall, by_case, by_operation = empty(), {}, {}
    for row in rows:
        if str(row.get("source", "")).lower() != "llm" or not enabled(row.get("verified")):
            continue
        decision = str(row.get("philosopher_decision") or "").lower()
        status = decision if decision in {"accepted", "rejected"} else "pending"
        for bucket in (overall, by_case.setdefault(row.get("use_case") or "Unknown", empty()),
                       by_operation.setdefault(row.get("operation") or "unknown", empty())):
            bucket["total"] += 1
            bucket[status] += 1
    for bucket in [overall, *by_case.values(), *by_operation.values()]:
        reviewed = bucket["accepted"] + bucket["rejected"]
        bucket["acceptance_rate"] = round(bucket["accepted"] / reviewed, 3) if reviewed else 0
    return {"overall": overall, "by_use_case": by_case, "by_operation": by_operation}


def review_history_summary(reviews):
    def bucket(rows):
        accepted = sum(str(row.get("decision", "")).lower() in {"accept", "accepted"} for row in rows)
        rejected = sum(str(row.get("decision", "")).lower() in {"reject", "rejected"} for row in rows)
        return {"total": len(rows), "accepted": accepted, "rejected": rejected,
                "acceptance_rate": round(accepted / len(rows), 3) if rows else 0}
    groups = defaultdict(list)
    for row in reviews:
        groups[row.get("operation") or "unknown"].append(row)
    overall = bucket(reviews)
    overall["total_reviews"] = overall.pop("total")
    return {**overall, "by_operation": {name: bucket(rows) for name, rows in groups.items()}}


def build_report_payload(store, review_store, use_case="", include_patched_sleec=True):
    # All visible summaries derive from the same selected patch rows.
    rows = (store.results_for_use_case(use_case, include_patched_sleec=include_patched_sleec) if use_case
            else store.all_results(include_patched_sleec=include_patched_sleec))
    runs = store.pipeline_runs(use_case)
    def selected(items):
        return [row for row in items if not use_case or row.get("use_case") == use_case]
    reviews = selected(review_store.all_reviews())
    persistence = store.persistence_status()
    return {
        "status": "OK", "use_case": use_case or "ALL", "include_patched_sleec": include_patched_sleec,
        "persistence": {**persistence, "scope": "all_use_cases"},
        "report_metrics": report_metrics(rows, runs),
        "evaluation_summary": evaluation_summary(rows, runs), "evaluation_details": rows,
        "recorded_diagnoses": recorded_diagnoses(runs),
        "philosopher_review_metrics": review_metrics(rows),
        "philosopher_review_summary": review_history_summary(reviews),
        "philosopher_reviews": reviews, "experiment_runs": runs,
        "experiment_candidates": selected(store.patch_candidates()),
        "experiment_verifications": selected(store.patch_verifications(include_patched_sleec=include_patched_sleec)),
    }
