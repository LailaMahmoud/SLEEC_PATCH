# Table 5: measured specification changes

Columns within each group: **RM, RA, RD, NE, BO, Neg, Def, Depth**.

RM/RA/RD = rules modified/added/deleted; NE = added events and measures plus introduced defeaters; BO = introduced condition Boolean operators; Neg = introduced condition negations; Def = introduced defeaters; Depth = maximum defeater nesting in resulting affected rules.

| Case | Manual | Selected-patch composition | Cumulative check |
| --- | --- | --- | --- |
| ALMI | 0, 4, 1, 1, 5, 2, 0, 1 | 2, 0, 0, 0, 3, 1, 0, 1 | passed |
| ASPEN | 1, 5, 3, 1, 4, 1, 0, 0 | --, --, --, --, --, --, --, -- | unavailable |
| AutoCar | 1, 20, 1, 1, 49, 22, 0, 0 | 0, 0, 2, 0, 0, 0, 0, 0 | passed |
| BSN | 1, 3, 0, 3, 2, 0, 0, 1 | 0, 1, 0, 0, 2, 0, 0, 0 | passed |
| CSI-Cobot | 0, 8, 2, 1, 11, 2, 0, 0 | 0, 4, 3, 0, 7, 1, 0, 0 | passed |
| DAISY | 0, 9, 3, 1, 13, 6, 1, 1 | --, --, --, --, --, --, --, -- | unavailable |

The source snapshot is the same 3 October 2026 export used by Table 4.
The table measures final specifications, not sums of per-issue counters. A failed cumulative check must be disclosed; the numerical edit size is not evidence of an effective combined repair.

Rule changes are matched by identifier: replacing an old rule with a differently named rule counts as deletion plus addition. Boolean conditions are simplified before counting; BO/Neg/Def are nonnegative net differences over all affected rules, while Depth is the resulting maximum. These paper metrics differ from raw per-rule addition counts in the manual-baseline report.

A passed cumulative check means all selected targets disappeared without introducing new issues. It does not mean every original issue was repaired. Smaller changes cannot establish superiority when repair coverage differs.

The six requested cases account for 42 saved issue groups and 26 rank-1 selections. The Table 4 export's 60 groups and 59 alternatives include SafeSCAD as a seventh case. These different scopes must be reconciled in the paper.

## Assembly and verification details

- **ALMI**: 2 selected patches from 3 saved issue groups.
  - Fresh diagnosis: 2 of 3 original issues removed; 0 new issues; 1 issues remain.
  - Manual file changes concerns/purposes/relations. Counts remain measurable; comparable effectiveness requires the original evaluation requirements.
- **ASPEN**: 8 selected patches from 8 saved issue groups.
  - situational_conflicts_2/d_trigger_refinement_R7_1_3: conflicting selected replacements for existing rule R7_1.
- **AutoCAR**: 2 selected patches from 9 saved issue groups.
  - Fresh diagnosis: 2 of 9 original issues removed; 0 new issues; 7 issues remain.
  - Manual file changes concerns/purposes/relations. Counts remain measurable; comparable effectiveness requires the original evaluation requirements.
- **BSN**: 1 selected patches from 3 saved issue groups.
  - Fresh diagnosis: 1 of 3 original issues removed; 0 new issues; 2 issues remain.
  - Manual file changes concerns/purposes/relations. Counts remain measurable; comparable effectiveness requires the original evaluation requirements.
- **CSICobot**: 7 selected patches from 10 saved issue groups.
  - concerns_4/g1: new rule R16 renamed to R16_1.
  - concerns_6/g1: new rule R16 renamed to R16_2.
  - concerns_7/g1: new rule R16 renamed to R16_3.
  - Fresh diagnosis: 7 of 10 original issues removed; 0 new issues; 3 issues remain.
  - Manual file changes concerns/purposes/relations. Counts remain measurable; comparable effectiveness requires the original evaluation requirements.
- **DAISY**: 6 selected patches from 9 saved issue groups.
  - concerns_2/g1: the saved patch lacks its original specification.
  - concerns_3/g1: the saved patch lacks its original specification.
  - concerns_4/g2: the saved patch lacks its original specification.
  - situational_conflicts_1/d_conflict_exception_1: the saved patch lacks its original specification.
  - situational_conflicts_2/d_conflict_exception_2: the saved patch lacks its original specification.
  - situational_conflicts_3/d_conflict_exception_2: the saved patch lacks its original specification.

Each case folder contains the exact original/manual inputs, selected patch evidence, and the composed specification where available. JSON records the measurement details, hashes, renaming and fresh verification results.
No model was called and no stored result was updated.

## Reproduce

Run from the repository root (the source export must be present):

```sh
venv/bin/python scripts/build_table5.py \
  --report instance/research_exports/20261003T112746Z/report_data.json \
  --table4-dir instance/research_exports/20261003T112746Z/latex \
  --output-dir reviews/table5-comparison \
  --verify --timeout 180
```
