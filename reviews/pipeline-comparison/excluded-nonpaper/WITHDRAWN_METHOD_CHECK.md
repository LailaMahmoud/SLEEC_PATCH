# Step 1: deterministic concern completion

The comparison holds the improved parser, detector fixes, input files and
diagnoses fixed. The only generation change is whether `concern_completion`
appears in the allowed deterministic operators. LLM generation is excluded.

| Input | Concerns with a verified candidate, operator disabled | Operator enabled |
|---|---:|---:|
| BSN: C2, C8, C9 | 0 / 3 | 3 / 3 |
| BSN corrected: C9 | 0 / 1 | 1 / 1 |

Both candidate sets were regenerated from the same saved diagnoses. The disabled
variant produced no candidates. Every enabled output was byte-identical to its
previously verified repaired specification, and the recorded implementation and
input hashes matched. The earlier successful verification was reused; no solver
run or live LLM request was repeated. This is an operator comparison within the
current implementation, not a new baseline-branch benchmark or a dataset-wide
success estimate.

## Method implication

Section III.B of `LAILA_ICSE_2027-2.pdf` lists new-rule generation among the
LLM-assisted semantic operators. Deterministic concern completion therefore
extends that published method description. These BSN gains should be attributed
to the additional operator, separately from improvements to existing edits or
LLM performance.

The additional rule directly enforces the complement of a supported concern.
Target removal is expected by construction; successful regression verification
and stakeholder acceptability remain separate requirements. The evidence does
not establish that this operator works for every concern or that its proposals
are operationally appropriate.

Recommendation: evaluate the deterministic addition as an explicitly labelled
extension. Keep the main method consistent with the paper's existing operator
split unless the authors decide to revise that method description. This check
does not change the current application's configuration or operator defaults.

Evidence: [bsn-operator-ablation.json](bsn-operator-ablation.json).
