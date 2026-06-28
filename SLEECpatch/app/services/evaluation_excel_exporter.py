import os
import pandas as pd


class EvaluationExcelExporter:

    def export_use_case(
        self,
        use_case,
        evaluation_a,
        evaluation_b,
        semantic_patches,
        philosopher_summary,
        selected_patches=None
    ):
        folder = os.path.join("results", use_case)
        os.makedirs(folder, exist_ok=True)

        path = os.path.join(folder, f"{use_case}_Evaluation.xlsx")

        with pd.ExcelWriter(path, engine="openpyxl") as writer:

            # Sheet 1: Summary
            summary_rows = [
                ["Use Case", use_case],
                ["Total WFIs", evaluation_a.get("total_wfis", 0)],
                ["WFIs With Matching Patch", evaluation_a.get("wfis_with_matching_patch", 0)],
                ["Total Patches", evaluation_a.get("total_patches", 0)],
                ["Matching Patches", evaluation_a.get("matching_patches", 0)],
                ["Patch Match Rate", evaluation_a.get("patch_match_rate", 0)],
                ["Overall Similarity", evaluation_b.get("overall_similarity", 0)],
                ["Philosopher Acceptance Rate", philosopher_summary.get("acceptance_rate", 0)]
            ]

            pd.DataFrame(summary_rows, columns=["Metric", "Value"]).to_excel(
                writer,
                sheet_name="1_Summary",
                index=False
            )

            # Sheet 2: Evaluation A by operation
            by_operation = []

            for operation, values in evaluation_a.get("by_operation", {}).items():
                by_operation.append({
                    "Operation": operation,
                    "Generated": values.get("generated", 0),
                    "Matched": values.get("matched", 0),
                    "Match Rate": values.get("match_rate", 0)
                })

            pd.DataFrame(by_operation).to_excel(
                writer,
                sheet_name="2_Eval_A_Operations",
                index=False
            )

            # Sheet 3: Evaluation A patch details
            pd.DataFrame(evaluation_a.get("patch_rows", [])).to_excel(
                writer,
                sheet_name="3_Eval_A_Patches",
                index=False
            )

            # Sheet 4: Evaluation B
            corrected = evaluation_b.get("corrected_vs_original", {})
            sleecpatch = evaluation_b.get("sleecpatch_vs_original", {})
            similarities = evaluation_b.get("similarities", {})

            metrics = sorted(set(corrected.keys()) | set(sleecpatch.keys()))

            b_rows = []

            for m in metrics:
                b_rows.append({
                    "Metric": m,
                    "Original_to_Corrected": corrected.get(m, 0),
                    "Original_to_SLEECPATCH": sleecpatch.get(m, 0),
                    "Similarity": similarities.get(m, 0)
                })

            pd.DataFrame(b_rows).to_excel(
                writer,
                sheet_name="4_Eval_B_FinalSpec",
                index=False
            )

            # Sheet 5: Evaluation C
            pd.DataFrame(semantic_patches).to_excel(
                writer,
                sheet_name="5_Eval_C_Review",
                index=False
            )

            # Sheet 6: Patch Traceability
            pd.DataFrame(selected_patches or []).to_excel(
                writer,
                sheet_name="6_Patch_Traceability",
                index=False
            )

            # Auto column width
            workbook = writer.book

            for sheet_name in writer.sheets:
                ws = writer.sheets[sheet_name]

                for col in ws.columns:
                    max_length = 0
                    col_letter = col[0].column_letter

                    for cell in col:
                        value = str(cell.value) if cell.value is not None else ""
                        max_length = max(max_length, len(value))

                    ws.column_dimensions[col_letter].width = min(max_length + 2, 45)

        return path