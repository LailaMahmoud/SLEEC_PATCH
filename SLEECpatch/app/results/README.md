# SLEEC-PATCH Experimental Results

This directory contains the experimental results for SLEEC-PATCH i
## Files

- `SLEEC_PATCH_Experimental_Results.xlsx` — complete formatted Excel workbook.
- `csv/use_case_summary.csv` — per-use-case summary.
- `csv/verified_evaluation.csv` — verified evaluation records.
- `csv/all_candidates.csv` — all generated repair candidates.
- `csv/verification_records.csv` — verification outcomes.
- `csv/repair_runs.csv` — repair-run information.
- `csv/recorded_diagnoses.csv` — recorded WFI diagnoses.
- `csv/operation_summary.csv` — repair-operator summary.
- `csv/failure_analysis.csv` — failed/rejected candidate analysis.
- `csv/latex_report_results.csv` — results represented in the LaTeX report.

## Use Case Summary

| Use Case | Repair Runs | Distinct Issues | Candidates | Verified | Rejected | Unverified/No verification row | Deterministic Verified | LLM Verified | Avg Run Time (s) | Verification Rate |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| ALMI | 3 | 3 | 10 | 6 | 4 | 0 | 5 | 1 | 46.464 | 0.6 |
| ASPEN | 8 | 8 | 38 | 19 | 19 | 0 | 17 | 2 | 78.72 | 0.5 |
| AutoCAR | 8 | 8 | 19 | 4 | 13 | 2 | 3 | 1 | 41.622 | 0.21052631578947367 |
| BSN | 6 | 3 | 9 | 4 | 5 | 0 | 3 | 1 | 22.858 | 0.4444444444444444 |
| CSICobot | 12 | 10 | 30 | 21 | 9 | 0 | 10 | 11 | 30.486 | 0.7 |
| DAISY | 8 | 8 | 25 | 14 | 11 | 0 | 10 | 4 | 51.741 | 0.56 |
| DPA | 3 | 3 | 7 | 3 | 4 | 0 | 2 | 1 | 42.916 | 0.42857142857142855 |
| DressAssist | 1 | 1 | 1 | 1 | 0 | 0 | 0 | 1 | 15.049 | 1 |
| SafeSCAD | 20 | 19 | 81 | 29 | 52 | 0 | 25 | 4 | 64.866 | 0.35802469135802467 |

## Repair Operation Summary

| Source | Operation | Verified Rows | % of Verified Rows |
| --- | --- | --- | --- |
| deterministic | deadline_refinement | 1 | 0.009900990099009901 |
| deterministic | defeater_introduction | 21 | 0.2079207920792079 |
| deterministic | defeater_refinement | 9 | 0.0891089108910891 |
| deterministic | rule_decomposition | 10 | 0.09900990099009901 |
| deterministic | rule_removal | 12 | 0.1188118811881188 |
| deterministic | trigger_refinement | 19 | 0.18811881188118812 |
| deterministic | trigger_strengthening | 3 | 0.0297029702970297 |
| llm | event_specialization | 3 | 0.0297029702970297 |
| llm | new_rule_generation | 14 | 0.13861386138613863 |
| llm | response_refinement | 9 | 0.0891089108910891 |

## Failure Analysis

| Failure Reason | Count | % of Rejected Verifications |
| --- | --- | --- |
| A new rule must be anchored to the selected source concern, without an edited rule target. | 29 | 0.24786324786324787 |
| The selected issue remains in the patched specification. | 18 | 0.15384615384615385 |
| The semantic proposal must target a rule identified for this finding. | 17 | 0.1452991452991453 |
| Every new name must be a single SLEEC identifier. | 15 | 0.1282051282051282 |
| target issue not fixed | 14 | 0.11965811965811966 |
| target issue not fixed; introduced new WFI during regression | 7 | 0.05982905982905983 |
| A specialized concept must have a new, unused name. | 6 | 0.05128205128205128 |
| The selected issue remains in the patched specification. The patch introduces new well-formedness issues. | 4 | 0.03418803418803419 |
| The structured edit does not produce valid SLEEC: None:90:106: Expected ')' => 'lable}))) *then Adjus' | 2 | 0.017094017094017096 |
| The structured edit does not produce valid SLEEC: None:105:55: Expected ')' => '} = false *and {human' | 1 | 0.008547008547008548 |
| The structured edit does not produce valid SLEEC: None:90:70: Expected ')' => 'vailable} *= false) t' | 1 | 0.008547008547008548 |
| The structured edit does not produce valid SLEEC: None:90:107: Expected ')' => 'lable}))) *then Adjus' | 1 | 0.008547008547008548 |
| introduced new WFI during regression | 1 | 0.008547008547008548 |
| target issue not fixed; introduced related issue on edited rule; introduced new WFI during regression | 1 | 0.008547008547008548 |

## Reproducibility Note

The CSV files are provided so that the experimental data can be inspected directly in GitHub/Anonymous GitHub. The Excel workbook is retained as the complete formatted version for download and offline analysis.

The values in these tables are exported from the supplied SLEEC-PATCH experimental-results workbook and are not manually reconstructed.
