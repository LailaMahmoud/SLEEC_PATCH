# SLEEC-PATCH
**A repository for:** *SLEEC PATCH*

SLEEC PATCH is utomated Support for Resolving Normative Requirements Well-Formedness Issues

## Supplementary Material for:
# SLEEC-PATCH: Automated Diagnosis and Repair of Normative Requirements

SLEEC-PATCH is a framework for diagnosing and repairing Well-Formedness Issues (WFIs) in SLEEC normative requirements.

SLEEC-PATCH builds on LEGOS-SLEEC for formal WFI analysis and combines deterministic and LLM-assisted repair operators with formal verification and regression analysis.

## This Repository Contains

- The SLEEC-PATCH implementation
- Deterministic repair operators
- LLM-assisted repair operators
- Formal verification and regression analysis
- Evaluation scripts
- Nine SLEEC case studies
- Initial and expert-corrected SLEEC specifications
- Experimental results
- Scripts for generating evaluation tables

## SLEEC-PATCH Workflow

SLEEC Specification
        ↓
WFI Detection
        ↓
Diagnosis / Witness Extraction
        ↓
Repair Operator Selection
        ↓
Candidate Patch Generation
        ↓
Syntax and Semantic Validation
        ↓
Target-WFI Verification
        ↓
Regression Analysis
        ↓
Verified / Rejected Patch

Candidate generation does not by itself establish that a repair is valid. Generated patches are checked against the diagnosed WFI and the resulting specification is analyzed for newly introduced WFIs.

## WFI Categories

SLEEC-PATCH currently considers:

- Situational conflicts
- Concerns / insufficiencies
- Redundancies
- Purpose blocking / restrictiveness

## Repair Operators

Repair Operators
Situational Conflicts
Deterministic:

Trigger Refinement
Defeater Introduction
Rule Merging

LLM-assisted:
- Event Specialization
- Measure Specialization
- Response Refinement
### Concerns / Insufficiencies
Deterministic:
- Trigger Strengthening
- Defeater Refinement
- Rule Decomposition
- Deadline Refinement

LLM-assisted:

New Rule Generation

Redundancies
Deterministic:

Rule Removal
Defeater Propagation

LLM-assisted:
- Event Specialization
- Measure Specialization
- Response Refinement


Event Specialization
Measure Specialization
Response Refinement

Purpose Blocking / Restrictiveness
Deterministic:
- Defeater Introduction

Defeater Introduction
LLM-assisted:
- Response Refinement

## Prerequisites

- Python
- Flask
- OpenAI Python package
- z3-solver
- pysmt
- textX
- ordered-set

Install the project dependencies:

    pip install -r SLEECpatch/app/requirements.txt

## Launch SLEEC-PATCH

From the repository root:

    cd SLEECpatch/app

Run:

    python -m flask --app app run --port 5000 --no-debugger --no-reload

Then open `http://127.0.0.1:5000/`.

## Case Studies

1. ALMI
2. ASPEN
3. AutoCAR
4. BSN
5. CSICobot
6. DAISY
7. DPA
8. DressAssist
9. SafeSCAD

For each case study, the repository contains the SLEEC specification used for analysis and the corresponding expert-corrected specification used in the evaluation.

## Patch Verification

For each candidate patch, SLEEC-PATCH evaluates whether:

1. the candidate is syntactically valid;
2. the diagnosed target WFI is resolved;
3. no related/new WFI invalidates the repair; and
4. regression analysis passes.

A candidate that repairs the target issue but introduces a new WFI is reported as rejected rather than as a verified repair.

## Evaluation

- **WFI Resolution Coverage:** whether a diagnosed WFI has at least one verified repair.
- **Candidate Verification Rate:** the proportion of generated candidate patches that pass verification.

SLEEC-PATCH also reports manual similarity (M-Sim) against selected expert-authored repairs. M-Sim measures structural similarity and is not used to determine formal verification.

## Relationship to LEGOS-SLEEC

SLEEC-PATCH uses LEGOS-SLEEC for formal analysis of SLEEC specifications.

LEGOS-SLEEC detects and diagnoses well-formedness issues. SLEEC-PATCH extends this workflow with candidate repair generation, patch validation, formal re-analysis, regression analysis, and evaluation.

## Repository Structure

    SLEECpatch/
    └── app/
        ├── app.py
        ├── services/
        ├── sleec_usecases/
        ├── results/
        ├── templates/
        ├── static/
        └── requirements.txt

    scripts/
        └── evaluation and table-generation scripts
    Results:
    SLEECpatch/app/results/csv

    Case Studies
Please find here, both the initial and SLEECPATCH normative requirements collected for nine case studies.

ALMI (initial, SLEECPATCH)
ASPEN (initial, SLEECPATCH)
AutoCar (initial, SLEECPATCH)
BSN (initial, SLEECPATCH)
CSICobot (initial, SLEECPATCH)
DAISY (initial, SLEECPATCH)
DPA (initial, SLEECPATCH)
DressAssist (initial, SLEECPATCH)
SafeSCAD (initial, SLEECPATCH)


## Reproducibility

1. Select one of the nine case studies.
2. Run WFI diagnosis.
3. Select a diagnosed WFI.
4. Generate candidate repairs.
5. Verify the generated candidates.
6. Inspect target-WFI and regression results.
7. Export the evaluation results.


## Pipeline

## License

