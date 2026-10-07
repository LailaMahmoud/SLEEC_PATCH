# Pipeline completion on `test`

Reviewed against working revision on 2026-10-03. This completes the
partly applied detector rewrite and the verification/reporting fixes. Tests use
temporary databases and solver working directories.
## Automated checks

| Suite | Result |
| --- | --- |
| Main Python tests under `tests/` | 107 passed |
| Deployment integration and verification contract | 26 passed, 2 skipped |
| Separate operator tests under `SLEECpatch/tests/SLEEC_PATCH_tests/` | 59 passed |
| JavaScript tests under `tests/` | 17 passed |

The two skips assert byte-identical historical deployment import snapshots.
Browser tests execute page logic with DOM stubs; they are not a full interactive
browser session. Backend tests use real parsing and detection with external HTTP
blocked. Controlled AI responses cover structured materialization, rejection,
verification and persistence; no live model quality was measured.

The separate operator tests require pytest, which is now declared in
`requirements-dev.txt`. From the repository root, using the project virtual
environment:

```sh
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests
python -m unittest discover -s tests/deployment
PYTHONPATH=SLEECpatch/app:. python -m pytest -q SLEECpatch/tests/SLEEC_PATCH_tests
node --test tests/*.js
```

Legacy tests were adjusted for the current structured proposal format, operator
names, quantitative ranking and page IDs. New tests check unresolved targets,
stale true flags, forged diagnosis metadata, missing detector results, rule
renaming, deleted requirements, conflicting edits, cache behaviour, separate
exports and candidate/result database agreement.

## Real case checks with AI generation disabled

Each selected issue is repaired against the original specification. Counts
below are alternative repairs, not patches composed into one final specification.
Successful-result counts were checked against verified candidate counts in
temporary SQLite databases.

| Case | Observed outcome |
| --- | --- |
| ALMI | 3 verified alternatives covering 2 of 3 diagnosed issues. `c1`: defeater refinement. `c4`: deadline refinement and decomposition. The `R3` situational conflict remained and its candidate was rejected. |
| Daisy | 9 verified alternatives covering 3 of 8 diagnosed issues: removal of redundant `Rule16`, and alternatives for conflicting `Rule18`/`Rule19`. Five concerns had no verified deterministic repair. |
| DressAssist | Diagnosis rejected before repair: two rules are named `Rule20_1`. No successful result saved. The dataset needs an unambiguous rule ID before it can be tested. |
| ASPEN | Full-case probe exceeded its 240-second limit and is inconclusive. A focused `R4` conflict run completed in 67 seconds: all 5 deterministic candidates failed, and 0 successful results were saved. Two independent, uncached diagnoses completed with the same 8 issue subjects but different raw evidence. |

The repeated ASPEN diagnoses found concerns `c4`, `c5`, `c7`, `c8`, redundant
rule `R14`, and situationally conflicting rules `R13`, `R4`, `R7_1`. The changed
witnesses demonstrate why proof text should not determine issue identity.
Two observations are a regression check, not a proof of solver determinism.
Measured summaries, run IDs and available input hashes are retained in
[`reviews/verification-hardening/case-results.json`](../reviews/verification-hardening/case-results.json).

Reproduce the bounded, offline probe with:

```sh
python scripts/check_repair_cases.py --output /tmp/repair-cases.json --timeout 240
python scripts/check_repair_cases.py --case aspen.sleec --issue-id situational_conflicts_1 --output /tmp/aspen-conflict.json --timeout 240
```

The probe disables model generation and external HTTP, stores results in a
temporary database, and writes JSON summaries plus diagnostic logs beside the
requested output file. A timed-out case is labelled inconclusive and retains
completed issue summaries. The timeout bounds the probe process; it is not a
new production request timeout.
An `OK` probe status means the selected checks finished; `verified` and
`successful` record whether any proposed repair actually passed.


