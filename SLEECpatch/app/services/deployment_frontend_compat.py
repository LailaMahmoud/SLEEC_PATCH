"""Translate the empowered backend's responses for the preserved live frontend.

This module does not generate, repair, rank or persist patches. It supplies UI
status aliases and report fields, and checks human edits against the selected
issue using the imported engine's own target/regression methods.
"""
import copy
from services.operator_names import normalize_operators

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
        "inconclusive" if patch.get("verification_inconclusive") else
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
    result = normalize_operators(copy.deepcopy(payload))
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
    result = normalize_operators(copy.deepcopy(payload))
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
    return engine.verify_edited_sleec(submitted.get("original_sleec"),
                                      submitted.get("sleec_text", ""), submitted.get("issue"))


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
            "api_sleec_patch_generate_verified",
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
        else:
            payload = report_payload(payload)
        response.set_data(app.json.dumps(payload))
        response.headers["Cache-Control"] = "no-store"
        return response
