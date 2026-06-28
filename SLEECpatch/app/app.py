
import  spacy, numpy as np, re, os
import sys

from flask import Flask, render_template, request,redirect, jsonify, abort, url_for, session, render_template_string
from openai import OpenAI
import pandas as pd
from flask import send_file
#import pandas as pd

import json
import sys

APP_DIR = os.path.dirname(os.path.abspath(__file__))
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
from services.sleec_patch_workbench_engine import SLEECPatchWorkbenchEngine
sleec_patch_engine = SLEECPatchWorkbenchEngine()
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

    "SafeSCAD": os.path.join(BASE_DIR, "sleec_usecases", "Safescade.sleec"),
    "SafeSCAD-corrected": os.path.join(BASE_DIR, "sleec_usecases", "Safescade-corrected.sleec")
}




BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.append(BASE_DIR)
##for step6 sleeec ##
from sleec.sleec_api import *
from sleec.sleec_api import *


import os

from dotenv import load_dotenv

from services.sleec_patch_workbench_engine import SLEECPatchWorkbenchEngine


load_dotenv()

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

    result = sleec_patch_engine.generate_verified_patches(
        use_case=data.get("use_case", "Unknown"),
        sleec_text=data.get("sleec_text", ""),
        issue=data.get("issue", {}),
        max_attempts=data.get("max_attempts", 3)
    )

    return jsonify(result)


@app.route("/api/sleec-patch/evaluation-summary", methods=["POST"])
def api_sleec_patch_evaluation_summary():

    return jsonify(
        sleec_patch_engine.store.summary()
    )


@app.route("/api/sleec-patch/evaluation-results", methods=["POST"])
def api_sleec_patch_evaluation_results():

    return jsonify(
        sleec_patch_engine.store.all_results()
    )


@app.route("/api/sleec-patch/evaluation-a", methods=["POST"])
def api_evaluation_a():
    data = request.get_json() or {}
    use_case = data.get("use_case", "ALMI")

    corrected_path = SLEEC_FILES.get(f"{use_case}-corrected")

    generated_patches = sleec_patch_engine.store.all_results()

    generated_patches = [
        p for p in generated_patches
        if p.get("use_case") == use_case
    ]

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

    all_results = sleec_patch_engine.store.all_results()

    use_case_patches = [
        p for p in all_results
        if p.get("use_case") == use_case
    ]

    built = evaluation_b.build_sleecpatch_file(
        use_case=use_case,
        original_sleec=original_sleec,
        all_patch_results=use_case_patches,
        apply_patch_to_text=sleec_patch_engine.apply_patch_to_text
    )

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

    rows = sleec_patch_engine.store.all_results()

    patches = []

    for r in rows:
        if use_case and r.get("use_case") != use_case:
            continue

        if r.get("source") == "llm" or r.get("operation") in semantic_ops:
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

if __name__ == "__main__":
    app.run(debug=True)
