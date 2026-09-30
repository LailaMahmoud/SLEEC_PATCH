"""Translate the empowered backend's responses for the preserved live frontend.

The imported backend files remain byte-for-byte copies of their source commit.
This module does not generate, repair, rank or persist patches. It supplies UI
status aliases and report fields, and checks human edits against the selected
issue using the imported engine's own target/regression methods.
"""
import copy

from flask import request

from services.evaluation_reporting import (
    average, recorded_diagnoses, review_metrics,
)


def patch_key(patch):
    return tuple(str(patch.get(key) or "") for key in (
        "source", "patch_id", "operation", "target_rule_id", "proposed_rule"
    ))


def frontend_patch(patch):
    result = dict(patch)
    # Map the backend's verdict; never infer success from membership of a list.
    verified = patch.get("verified") is True
    if "formally_verified" in patch:
        verified = verified and patch["formally_verified"] is True
    result["formally_verified"] = verified
    syntax = patch.get("syntax_validation", {}).get("valid", patch.get("syntax_valid"))
    result["candidate_status"] = (
        "formally_verified" if verified else
        "rejected" if patch.get("failure_reason") else
        "syntax_valid" if syntax is True else "generated"
    )
    review = patch.get("requires_social_scientist_review")
    if review is None:
        review = patch.get("source") == "llm" or patch.get("operation") not in {
            "rule_removal", "delete_redundant_rule"
        }
    result["semantic_review_status"] = "pending" if review else "not_required"
    return result


def generation_payload(payload):
    result = copy.deepcopy(payload)
    checked = {}
    for field in ("verified_patches", "failed_patches"):
        result[field] = [frontend_patch(patch) for patch in result.get(field, [])]
        checked.update({patch_key(patch): patch for patch in result[field]})
    for field in ("deterministic_candidates", "llm_candidates"):
        result[field] = [
            frontend_patch({**patch, **checked.get(patch_key(patch), {})})
            for patch in result.get(field, [])
        ]
    return result


def report_payload(payload):
    result = copy.deepcopy(payload)
    runs = result.get("experiment_runs", [])
    rows = result.get("evaluation_details", [])
    # Keep the source backend's patch-level metrics and add the run-level fields
    # used by the live page. A repair run may produce several saved patches.
    result.setdefault("report_metrics", {}).update(
        repair_run_count=len(runs),
        avg_run_time_seconds=average(runs, "total_time_seconds"),
        avg_run_attempts=average(runs, "attempts"),
    )
    result["recorded_diagnoses"] = recorded_diagnoses(runs)
    result["philosopher_review_metrics"] = review_metrics(rows)
    summaries = result.setdefault("evaluation_summary", [])
    known = {row.get("use_case") for row in summaries}
    for name in sorted({run.get("use_case") for run in runs if run.get("use_case")} - known):
        summaries.append({"use_case": name, "total_records": 0, "verified_patches": 0})
    for row in summaries:
        selected_runs = [run for run in runs if run.get("use_case") == row.get("use_case")]
        row.update(
            repair_run_count=len(selected_runs),
            avg_run_time=average(selected_runs, "total_time_seconds"),
            avg_run_attempts=average(selected_runs, "attempts"),
        )
    return result


def edited_payload(engine, validation, submitted):
    # The live editor posts the baseline and selected issue. Its "Use" button
    # promises a resolved issue, whereas the source endpoint checks syntax and
    # detector execution only. Reuse the source engine's regression semantics.
    if validation.get("valid") is not True:
        return validation
    original = submitted.get("original_sleec")
    issue = submitted.get("issue")
    if not isinstance(original, str) or not isinstance(issue, dict):
        return {**validation, "valid": False, "failure_reason": "Original input and selected issue are required."}
    baseline = engine.validate_patched_sleec(original)
    if not baseline.get("valid"):
        return {**validation, "valid": False, "failure_reason": "Original input analysis failed: " + baseline.get("failure_reason", "")}
    before = baseline["analysis"].get("structured", {})
    kind, value = issue.get("issue_type"), issue.get("value")
    if not isinstance(kind, str) or value not in before.get(kind, []):
        return {**validation, "valid": False, "failure_reason": "The selected issue is not in the original diagnosis. Diagnose the input again."}
    report = engine.build_regression_report(
        kind, value, before, validation["analysis"].get("structured", {})
    )
    passed = report.get("regression_passed") is True
    return {
        **validation, "valid": passed, "regression_report": report,
        "failure_reason": "" if passed else "The selected issue still exists or the edit introduces a new issue.",
        "semantic_review_status": "pending",
    }


def install_frontend_compatibility(backend):
    app = backend.app
    if app.extensions.get("sleec_deployment_frontend"):
        return
    app.extensions["sleec_deployment_frontend"] = True

    @app.after_request
    def adapt_frontend_response(response):
        if not response.is_json or not 200 <= response.status_code < 300:
            return response
        endpoint = request.endpoint
        if endpoint not in {
            "api_sleec_patch_generate_verified", "api_sleec_patch_verify_edited_sleec",
            "api_sleec_patch_report_data", "api_sleec_patch_download_report_json",
        }:
            return response
        # send_file(BytesIO(...)) returns a streaming response for JSON exports.
        # Buffer it before adding the same report fields used by the live page.
        response.direct_passthrough = False
        payload = response.get_json()
        if not isinstance(payload, dict) or payload.get("status") == "ERROR":
            return response
        if endpoint == "api_sleec_patch_generate_verified":
            payload = generation_payload(payload)
        elif endpoint == "api_sleec_patch_verify_edited_sleec":
            payload = edited_payload(backend.sleec_patch_engine, payload, request.get_json(silent=True) or {})
        else:
            payload = report_payload(payload)
        response.set_data(app.json.dumps(payload))
        response.headers["Cache-Control"] = "no-store"
        return response
