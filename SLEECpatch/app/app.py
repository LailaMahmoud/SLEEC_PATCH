
import numpy as np, re, os
import sys
import traceback
from dotenv import load_dotenv

from flask import Flask, render_template, request,redirect, jsonify, abort, url_for, session, render_template_string
from openai import OpenAI
import pandas as pd
from flask import send_file
#import pandas as pd

import json
import sys

APP_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(APP_DIR, ".env"))
ROOT_DIR = os.path.abspath(os.path.join(APP_DIR, "..", ".."))

if ROOT_DIR not in sys.path:
    sys.path.append(ROOT_DIR)
BASE_DIR = os.path.dirname(__file__)
from services.sleec_detection_engine import SLEECDetectionEngine
from services.sleec_resolution_manager import SLEECResolutionManager
sleec_detector = SLEECDetectionEngine()
sleec_manager = SLEECResolutionManager()

#from USCLLM import UseCaseRepository
from services.sleec_pipeline_manager import SLEECPipelineManager
sleec_pipeline_manager = SLEECPipelineManager()

from services.sleec_parser import SLEECParser
from services.evaluation_a_patch_match import EvaluationAPatchMatch
evaluation_a = EvaluationAPatchMatch(SLEECParser())
from services.evaluation_b_final_spec import EvaluationBFinalSpec
from services.repair_action_analyzer import RepairActionAnalyzer

evaluation_b = EvaluationBFinalSpec(
    parser=SLEECParser(),
    analyzer=RepairActionAnalyzer()
)
from services.philosopher_review_store import PhilosopherReviewStore

philosopher_review_store = PhilosopherReviewStore()
from services.evaluation_excel_exporter import EvaluationExcelExporter
evaluation_excel_exporter = EvaluationExcelExporter()
from services.patch_level_evaluator import PatchLevelEvaluator
patch_level_evaluator  = PatchLevelEvaluator()


SLEEC_EXCEL_FILES = {
    "ALMI": os.path.join(BASE_DIR, "sleec_usecases", "ALMI.xlsx"),
    "ASPEN": os.path.join(BASE_DIR, "sleec_usecases", "aspen.xlsx"),
    "AutoCAR": os.path.join(BASE_DIR, "sleec_usecases", "Autocar.xlsx"),
    "BSN": os.path.join(BASE_DIR, "sleec_usecases", "BSN.xlsx"),
    "CSICobot": os.path.join(BASE_DIR, "sleec_usecases", "CSI.xlsx"),
    "DAISY": os.path.join(BASE_DIR, "sleec_usecases", "Daisy.xlsx"),
    "DPA": os.path.join(BASE_DIR, "sleec_usecases", "DPA.xlsx"),
    "DressAssist": os.path.join(BASE_DIR, "sleec_usecases", "DRESSASSIST.xlsx"),
    "SafeSCAD": os.path.join(BASE_DIR, "sleec_usecases", "safescade.xlsx")
}


SLEEC_FILES = {
    "ALMI": os.path.join(BASE_DIR, "sleec_usecases", "ALMI.sleec"),
    "ALMI-corrected": os.path.join(BASE_DIR, "sleec_usecases", "ALMI-corrected.sleec"),

    "ASPEN": os.path.join(BASE_DIR, "sleec_usecases", "aspen.sleec"),
    "ASPEN-corrected": os.path.join(BASE_DIR, "sleec_usecases", "aspen-corrected.sleec"),

    "AutoCAR": os.path.join(BASE_DIR, "sleec_usecases", "Autocar.sleec"),
    "AutoCAR-corrected": os.path.join(BASE_DIR, "sleec_usecases", "Autocar-corrected.sleec"),

    "BSN": os.path.join(BASE_DIR, "sleec_usecases", "BSN.sleec"),
    "BSN-corrected": os.path.join(BASE_DIR, "sleec_usecases", "BSN-corrected.sleec"),

    "CSICobot": os.path.join(BASE_DIR, "sleec_usecases", "CSI.sleec"),
    "CSICobot-corrected": os.path.join(BASE_DIR, "sleec_usecases", "CSI-corrected.sleec"),

    "DAISY": os.path.join(BASE_DIR, "sleec_usecases", "Daisy.sleec"),
    "DAISY-corrected": os.path.join(BASE_DIR, "sleec_usecases", "Daisy-corrected.sleec"),

    "DPA": os.path.join(BASE_DIR, "sleec_usecases", "DPA.sleec"),
    "DPA-corrected": os.path.join(BASE_DIR, "sleec_usecases", "DPA-corrected.sleec"),

    "DressAssist": os.path.join(BASE_DIR, "sleec_usecases", "DRESSASSIST.sleec"),
    "DressAssist-corrected": os.path.join(BASE_DIR, "sleec_usecases", "DRESSASSIST-corrected.sleec"),

    "SafeSCAD": os.path.join(BASE_DIR, "sleec_usecases", "safescade.sleec"),
    "SafeSCAD-corrected": os.path.join(BASE_DIR, "sleec_usecases", "safescade-corrected.sleec"),

    "Tabiat":os.path.join(BASE_DIR, "sleec_usecases", "Tabiat.sleec"),
    "Tabiat-corrected":os.path.join(BASE_DIR, "sleec_usecases", "Tabiat-corrected.sleec"),

    "Casper":os.path.join(BASE_DIR, "sleec_usecases", "Casper.sleec"),
    "Casper-corrected":os.path.join(BASE_DIR, "sleec_usecases", "Casper-corrected.sleec")

    }




BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.append(BASE_DIR)
##for step6 sleeec ##
from sleec.sleec_api import *
from sleec.sleec_api import *


from services.sleec_patch_workbench_engine import SLEECPatchWorkbenchEngine


app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", os.urandom(24).hex())

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

sleec_patch_engine = SLEECPatchWorkbenchEngine()





def load_sleec_text(use_case):

    file_path = SLEEC_FILES.get(use_case)

    if not file_path:
        print(f"[ERROR] Unknown use case: {use_case}")
        return ""

    if not os.path.isfile(file_path):
        print(f"[ERROR] File not found: {file_path}")
        return ""

    try:
        with open(file_path, "r", encoding="utf-8-sig", newline="") as f:
            text = f.read()

        print(f"[INFO] Loaded {use_case}")
        print(f"[INFO] Characters: {len(text)}")
        print(f"[INFO] Starts with: {repr(text[:30])}")

        return text

    except Exception as e:
        print(f"[ERROR] Failed to read {file_path}: {e}")
        return ""


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/about")
def about():
    return render_template("about.html")


@app.route("/contact")
def contact():
    return render_template("contact.html")


@app.route("/step6")
def step6():
    return render_template(
        "step6.html",
        use_cases=list(SLEEC_FILES.keys())
    )


@app.route("/sleec-patch-workbench")
def sleec_patch_workbench():

    selected = request.args.get("use_cases", "DAISY")

    selected_use_cases = [
        x.strip()
        for x in selected.split(",")
        if x.strip()
    ]

    return render_template(
        "SLEECPatchWorkbench.html",
        use_cases=list(SLEEC_FILES.keys()),
        selected_use_cases=selected_use_cases,
        sleec_text=""
    )


@app.route("/philosopher-review")
def philosopher_review():
    return render_template(
        "philosopher_review.html",
        use_cases=list(SLEEC_FILES.keys())
    )


@app.route("/sleec-patch-report")
def sleec_patch_report():
    return render_template(
        "SLEECPatchReport.html",
        use_cases=list(SLEEC_FILES.keys())
    )


@app.route("/api/sleec-patch/load-usecase", methods=["POST"])
def api_sleec_patch_load_usecase():

    data = request.get_json() or {}

    use_case = data.get("use_case", "DAISY")

    sleec_text = load_sleec_text(use_case)

    return jsonify({
        "status": "OK" if sleec_text else "ERROR",
        "use_case": use_case,
        "sleec_text": sleec_text,
        "length": len(sleec_text)
    })


@app.route("/api/sleec-patch/diagnose", methods=["POST"])
def api_sleec_patch_diagnose():

    data = request.get_json() or {}

    sleec_text = data.get("sleec_text", "")

    result = sleec_patch_engine.diagnose(sleec_text)

    return jsonify(result)


@app.route("/api/sleec-patch/generate-verified", methods=["POST"])
def api_sleec_patch_generate_verified():

    data = request.get_json() or {}

    try:
        result = sleec_patch_engine.generate_verified_patches(
            use_case=data.get("use_case", "Unknown"),
            sleec_text=data.get("sleec_text", ""),
            issue=data.get("issue", {}),
            max_attempts=data.get("max_attempts", 3)
        )
    except Exception as exc:
        # Return a JSON error instead of Flask's default HTML 500 page, so the
        # frontend can parse and display it (and we can see the real cause).
        traceback.print_exc()
        return jsonify({
            "status": "ERROR",
            "error": f"{type(exc).__name__}: {exc}"
        }), 500

    return jsonify(result)


@app.route("/api/sleec-patch/evaluation-summary", methods=["POST"])
def api_sleec_patch_evaluation_summary():

    return jsonify(
        sleec_patch_engine.store.summary()
    )


@app.route("/api/sleec-patch/evaluation-results", methods=["POST"])
def api_sleec_patch_evaluation_results():

    return jsonify(
        sleec_patch_engine.store.all_results(include_patched_sleec=False)
    )


@app.route("/api/sleec-patch/philosopher-review-queue", methods=["POST"])
def api_sleec_patch_philosopher_review_queue():
    data = request.get_json() or {}

    try:
        return jsonify({
            "status": "OK",
            "patches": sleec_patch_engine.store.philosopher_review_queue(
                use_case=data.get("use_case", ""),
                include_reviewed=bool(data.get("include_reviewed", False))
            ),
            "metrics": sleec_patch_engine.store.philosopher_review_metrics()
        })
    except Exception as exc:
        app.logger.exception("Failed to load philosopher review queue")
        return jsonify({
            "status": "ERROR",
            "error": "Failed to load persisted philosopher review queue.",
            "details": str(exc)
        }), 500


@app.route("/api/sleec-patch/philosopher-review-decision", methods=["POST"])
def api_sleec_patch_philosopher_review_decision():
    data = request.get_json() or {}
    result_id = data.get("id")
    decision = data.get("decision", "")

    if not result_id:
        return jsonify({
            "status": "ERROR",
            "error": "Missing patch result id."
        }), 400

    if decision not in {"Accepted", "Rejected"}:
        return jsonify({
            "status": "ERROR",
            "error": "Decision must be Accepted or Rejected."
        }), 400

    saved = sleec_patch_engine.store.save_philosopher_decision(
        result_id=result_id,
        decision=decision,
        comments=data.get("comments", "")
    )

    philosopher_review_store.save_review({
        "use_case": data.get("use_case", ""),
        "issue_id": data.get("issue_id", ""),
        "issue_type": data.get("issue_type", ""),
        "patch_id": data.get("patch_id", ""),
        "operation": data.get("operation", ""),
        "original_rule": data.get("original_rule", ""),
        "proposed_rule": data.get("proposed_rule", ""),
        "explanation": data.get("natural_language_explanation", ""),
        "reviewer": data.get("reviewer", "Philosopher"),
        "decision": decision,
        "comment": data.get("comments", "")
    })

    return jsonify({
        "status": "OK",
        "saved": saved,
        "metrics": sleec_patch_engine.store.philosopher_review_metrics()
    })


@app.route("/api/sleec-patch/philosopher-review-metrics", methods=["POST"])
def api_sleec_patch_philosopher_review_metrics():
    try:
        return jsonify({
            "status": "OK",
            "metrics": sleec_patch_engine.store.philosopher_review_metrics()
        })
    except Exception as exc:
        app.logger.exception("Failed to load philosopher review metrics")
        return jsonify({
            "status": "ERROR",
            "error": "Failed to load philosopher review metrics.",
            "details": str(exc)
        }), 500


@app.route("/api/sleec-patch/persistence-status", methods=["POST"])
def api_sleec_patch_persistence_status():
    try:
        return jsonify({
            "status": "OK",
            "persistence": sleec_patch_engine.store.persistence_status()
        })
    except Exception as exc:
        app.logger.exception("Failed to load persistence status")
        return jsonify({
            "status": "ERROR",
            "error": "Failed to load persistence status.",
            "details": str(exc)
        }), 500


@app.route("/api/sleec-patch/experiment-runs", methods=["POST"])
def api_sleec_patch_experiment_runs():
    data = request.get_json() or {}

    return jsonify({
        "status": "OK",
        "runs": sleec_patch_engine.store.pipeline_runs(
            data.get("use_case", "")
        )
    })


@app.route("/api/sleec-patch/experiment-candidates", methods=["POST"])
def api_sleec_patch_experiment_candidates():
    data = request.get_json() or {}

    return jsonify({
        "status": "OK",
        "candidates": sleec_patch_engine.store.patch_candidates(
            data.get("run_id", "")
        )
    })


@app.route("/api/sleec-patch/experiment-verifications", methods=["POST"])
def api_sleec_patch_experiment_verifications():
    data = request.get_json() or {}

    return jsonify({
        "status": "OK",
        "verifications": sleec_patch_engine.store.patch_verifications(
            run_id=data.get("run_id", ""),
            include_patched_sleec=bool(data.get("include_patched_sleec", False))
        )
    })


def request_payload():
    data = request.get_json(silent=True) or {}
    return {
        **request.args.to_dict(),
        **data
    }


def truthy(value, default=False):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def count_by(rows, field):
    counts = {}

    for row in rows:
        key = row.get(field) or "Unknown"
        counts[key] = counts.get(key, 0) + 1

    return counts


def report_metrics(rows):
    total = len(rows)
    verified = sum(1 for row in rows if row.get("verified"))
    social_review = sum(
        1 for row in rows
        if row.get("requires_social_scientist_review")
    )
    philosopher_reviewed = sum(
        1 for row in rows
        if row.get("philosopher_decision")
    )

    return {
        "total_patch_rows": total,
        "verified_patch_rows": verified,
        "llm_patch_rows": sum(
            1 for row in rows
            if str(row.get("source", "")).lower() == "llm"
        ),
        "deterministic_patch_rows": sum(
            1 for row in rows
            if str(row.get("source", "")).lower() == "deterministic"
        ),
        "social_review_required_rows": social_review,
        "philosopher_reviewed_rows": philosopher_reviewed,
        "avg_attempts": round(
            sum(float(row.get("attempts") or 0) for row in rows) / total,
            3
        ) if total else 0,
        "avg_total_time_seconds": round(
            sum(float(row.get("total_time_seconds") or 0) for row in rows) / total,
            3
        ) if total else 0,
        "by_use_case": count_by(rows, "use_case"),
        "by_issue_type": count_by(rows, "issue_type"),
        "by_operation": count_by(rows, "operation"),
        "by_source": count_by(rows, "source")
    }


@app.route("/api/sleec-patch/report-data", methods=["GET", "POST"])
def api_sleec_patch_report_data():
    data = request_payload()
    use_case = data.get("use_case", "").strip()
    include_patched_sleec = truthy(
        data.get("include_patched_sleec"),
        default=True
    )
    evaluation_summary = sleec_patch_engine.store.summary()

    if use_case:
        patch_rows = sleec_patch_engine.store.results_for_use_case(
            use_case,
            include_patched_sleec=include_patched_sleec
        )
        evaluation_summary = [
            row for row in evaluation_summary
            if row.get("use_case") == use_case
        ]
    else:
        patch_rows = sleec_patch_engine.store.all_results(
            include_patched_sleec=include_patched_sleec
        )

    experiment_runs = sleec_patch_engine.store.pipeline_runs(use_case)
    experiment_candidates = sleec_patch_engine.store.patch_candidates()
    experiment_verifications = sleec_patch_engine.store.patch_verifications(
        include_patched_sleec=include_patched_sleec
    )
    philosopher_reviews = philosopher_review_store.all_reviews()

    if use_case:
        experiment_candidates = [
            row for row in experiment_candidates
            if row.get("use_case") == use_case
        ]
        experiment_verifications = [
            row for row in experiment_verifications
            if row.get("use_case") == use_case
        ]
        philosopher_reviews = [
            row for row in philosopher_reviews
            if row.get("use_case") == use_case
        ]

    return jsonify({
        "status": "OK",
        "use_case": use_case or "ALL",
        "include_patched_sleec": include_patched_sleec,
        "persistence": sleec_patch_engine.store.persistence_status(),
        "report_metrics": report_metrics(patch_rows),
        "evaluation_summary": evaluation_summary,
        "evaluation_details": patch_rows,
        "philosopher_review_metrics": (
            sleec_patch_engine.store.philosopher_review_metrics()
        ),
        "philosopher_review_summary": philosopher_review_store.summary(),
        "philosopher_reviews": philosopher_reviews,
        "experiment_runs": experiment_runs,
        "experiment_candidates": experiment_candidates,
        "experiment_verifications": experiment_verifications
    })


@app.route("/api/sleec-patch/evaluation-a", methods=["POST"])
def api_evaluation_a():
    data = request.get_json() or {}
    use_case = data.get("use_case", "ALMI")

    corrected_path = SLEEC_FILES.get(f"{use_case}-corrected")

    if not corrected_path:
        return jsonify({
            "status": "ERROR",
            "error": f"No corrected SLEEC file found for {use_case}"
        }), 404

    generated_patches = sleec_patch_engine.store.results_for_use_case(
        use_case,
        include_patched_sleec=False
    )

    result = evaluation_a.evaluate_use_case(
        use_case=use_case,
        corrected_path=corrected_path,
        generated_patches=generated_patches
    )

    return jsonify({
        "status": "OK",
        "evaluation": "A",
        "result": result
    })



@app.route("/api/sleec-patch/evaluation-b", methods=["POST"])
def api_evaluation_b():
    data = request.get_json() or {}
    use_case = data.get("use_case", "ALMI")

    original_path = SLEEC_FILES.get(use_case)
    corrected_path = SLEEC_FILES.get(f"{use_case}-corrected")

    original_sleec = load_sleec_text(use_case)

    use_case_patches = sleec_patch_engine.store.results_for_use_case(
        use_case,
        include_patched_sleec=False
    )

    built = evaluation_b.build_sleecpatch_file(
        use_case=use_case,
        original_sleec=original_sleec,
        all_patch_results=use_case_patches,
        apply_patch_to_text=sleec_patch_engine.apply_patch_to_text,
        validate_patched_sleec=lambda final_sleec: (
            sleec_patch_engine.validate_cumulative_sleec(
                original_sleec,
                final_sleec
            )
        )
    )

    if not built.get("output_path"):
        return jsonify({
            "status": "ERROR",
            "error": "Cumulative SLEEC-PATCH verification failed.",
            "cumulative_verification": built.get("cumulative_verification", {})
        }), 422

    result = evaluation_b.evaluate(
        use_case=use_case,
        original_path=original_path,
        corrected_path=corrected_path,
        sleecpatch_path=built["output_path"]
    )

    return jsonify({
        "status": "OK",
        "evaluation": "B",
        "generated_file": built["output_path"],
        "selected_patches": built["selected_patches"],
        "result": result
    })



@app.route("/api/sleec-patch/non-deterministic-patches", methods=["POST"])
def api_non_deterministic_patches():
    data = request.get_json() or {}
    use_case = data.get("use_case", "")

    semantic_ops = {
        "event_specialization",
        "measure_specialization",
        "capability_refinement",
        "new_rule_generation"
    }

    if use_case:
        rows = sleec_patch_engine.store.results_for_use_case(
            use_case,
            include_patched_sleec=False
        )
    else:
        rows = sleec_patch_engine.store.all_results(
            include_patched_sleec=False
        )

    patches = []

    for r in rows:
        if use_case and r.get("use_case") != use_case:
            continue

        is_verified = r.get("verified") in [True, 1, "1", "true", "True"]

        if is_verified and (
            r.get("source") == "llm" or r.get("operation") in semantic_ops
        ):
            patches.append({
                "use_case": r.get("use_case", ""),
                "issue_id": r.get("issue_id", ""),
                "issue_type": r.get("issue_type", ""),
                "patch_id": r.get("patch_id", ""),
                "operation": r.get("operation", ""),
                "original_rule": r.get("original_rule", ""),
                "proposed_rule": r.get("proposed_rule", ""),
                "explanation": r.get("natural_language_explanation", "")
            })

    return jsonify({
        "status": "OK",
        "patches": patches,
        "count": len(patches)
    })


@app.route("/api/sleec-patch/philosopher-review", methods=["POST"])
def api_philosopher_review():
    data = request.get_json() or {}

    philosopher_review_store.save_review(data)

    return jsonify({
        "status": "OK",
        "message": "Review saved"
    })


@app.route("/api/sleec-patch/philosopher-review-summary", methods=["POST"])
def api_philosopher_review_summary():
    return jsonify({
        "status": "OK",
        "summary": philosopher_review_store.summary(),
        "reviews": philosopher_review_store.all_reviews()
    })


@app.route("/api/sleec-patch/export-evaluation", methods=["POST"])
def api_export_evaluation():
    data = request.get_json() or {}
    use_case = data.get("use_case", "ALMI")

    corrected_path = SLEEC_FILES.get(f"{use_case}-corrected")
    original_path = SLEEC_FILES.get(use_case)

    use_case_patches = sleec_patch_engine.store.results_for_use_case(
        use_case,
        include_patched_sleec=False
    )

    evaluation_a_result = evaluation_a.evaluate_use_case(
        use_case=use_case,
        corrected_path=corrected_path,
        generated_patches=use_case_patches
    )

    original_sleec = load_sleec_text(use_case)

    built = evaluation_b.build_sleecpatch_file(
        use_case=use_case,
        original_sleec=original_sleec,
        all_patch_results=use_case_patches,
        apply_patch_to_text=sleec_patch_engine.apply_patch_to_text,
        validate_patched_sleec=lambda final_sleec: (
            sleec_patch_engine.validate_cumulative_sleec(
                original_sleec,
                final_sleec
            )
        )
    )

    if not built.get("output_path"):
        return jsonify({
            "status": "ERROR",
            "error": "Cumulative SLEEC-PATCH verification failed.",
            "cumulative_verification": built.get("cumulative_verification", {})
        }), 422

    evaluation_b_result = evaluation_b.evaluate(
        use_case=use_case,
        original_path=original_path,
        corrected_path=corrected_path,
        sleecpatch_path=built["output_path"]
    )

    semantic_ops = {
        "event_specialization",
        "measure_specialization",
        "capability_refinement",
        "new_rule_generation"
    }

    semantic_patches = [
        p for p in use_case_patches
        if (
            p.get("verified") in [True, 1, "1", "true", "True"]
            and (p.get("source") == "llm" or p.get("operation") in semantic_ops)
        )
    ]

    philosopher_summary = philosopher_review_store.summary()

    excel_path = evaluation_excel_exporter.export_use_case(
        use_case=use_case,
        evaluation_a=evaluation_a_result,
        evaluation_b=evaluation_b_result,
        semantic_patches=semantic_patches,
        philosopher_summary=philosopher_summary,
        selected_patches=built.get("selected_patches", [])
    )

    return jsonify({
        "status": "OK",
        "use_case": use_case,
        "excel_path": excel_path
    })

if __name__ == "__main__":
    app.run(debug=True)
