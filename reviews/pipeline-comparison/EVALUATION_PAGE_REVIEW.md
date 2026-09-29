# Evaluation/report page review

Implemented locally on `improvement/pipeline-robustness`. No deployment, model
call, production database access or experimental input change was performed.
The paper's repair methodology is unchanged.

## Confirmed problems

1. The report's Total counted saved patch rows, which can grow when an issue
   produces several patches or is run again. It did not count diagnosed issues.
2. Filtering by use case left philosopher-review statistics global. A zero
   accepted count could also fall back to a different review-history total.
3. Average time was weighted by the number of saved patches from each run.
   Runs producing no saved patches were absent from that average and summary.
4. Changing the filter left the previous report displayed until Load Report
   Data was clicked. A late response could replace a more recent selection.

These are report defects, not proof of the cause of the co-author's exact
reported fresh-9-then-reduced diagnosis count. That sequence remains unconfirmed
on her actual running version; see `run-order-check/README.md`.

## Resulting behavior

- The page labels saved patches, verified patches, repair runs and use cases
  explicitly. Patch breakdowns count patch records, including repeated runs.
- A separate diagnosis table shows the issue count captured before each saved
  repair run. It reads the saved original detector results and never derives
  issue counts from the number of patches, runs or selected issue IDs.
- New repair runs store a SHA-256 fingerprint of the exact analyzed input.
  Matching fingerprints identify the same input. Historical runs without this
  value remain unknown; no fingerprint is fabricated or backfilled.
- Missing/inconsistent historical diagnosis details show Not recorded or
  Inconsistent record. Complete recorded zero-issue diagnoses remain zero.
- All visible review, patch and experiment sections respect the use-case
  selection. The JSON persistence metadata retains its explicitly global scope.
- The page's timing/attempt averages count each saved pipeline run once,
  including unsuccessful runs. Legacy patch-weighted API fields remain available.
- Filter changes reload automatically, clear the previous display and ignore
  outdated responses. Failed loads show an explicit error and no previous-case
  results. Report requests/responses disable HTTP caching.
- Reports preserve historical records. No data-clearing or deduplication
  migration was introduced.

The diagnosis table contains records saved with repair runs. A Diagnose action
that does not reach a saved repair run is not included. This is stated on the
page. Existing evaluation-workbench summary APIs retain their legacy metrics;
these changes target the standalone report page shown in the user's screenshot.

## Validation

- Full Python suite: 77 tests passed.
- Four offline JavaScript UI-state checks passed with Node's test runner.
- The seven new report tests cover repeat repairs across cases, scoped review
  statistics and logs, averages including unsuccessful runs, legacy records,
  SQLite schema migration and the actual report route's filtering/cache headers.
- The existing pipeline integration test now checks that the recorded input
  fingerprint is calculated from the analyzed specification.
- Python and Jinja syntax, JavaScript syntax and git diff --check passed.
- After adding the legacy generation/validation timing columns to result
  queries, the seven report tests were rerun and passed.

All database tests use temporary SQLite files. The live Postgres deployment and
an interactive browser session were not exercised. Schema creation/migration
adds only the nullable input_sha256 field to pipeline-run records.

Evidence: `evaluation-full-tests.txt`, `evaluation-report-tests.txt` and
`evaluation-report-ui-tests.txt`. Commands:

- `venv/bin/python -m unittest discover -s tests -v`
- `node --test tests/test_report_page.js`
