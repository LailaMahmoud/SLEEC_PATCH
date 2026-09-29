# Pipeline robustness implementation

The current paper-method correction and validation results are recorded in
[BSN_REPAIR_RESULTS.md](BSN_REPAIR_RESULTS.md) and [METHOD_CHECK.md](METHOD_CHECK.md).
The added deterministic concern-completion operator has been removed. Its BSN
successes are excluded from paper-method results; live LLM repair success is
still unmeasured. All 70 current tests pass. The stage-specific results below
describe the earlier robustness work and are not a fresh current benchmark.

Implemented on `improvement/pipeline-robustness`, based on `origin/main` at
`c75d47e19609a8cfd4b8d99ed5eb311e75750a69`. Changes are local; no deployment or
live LLM request was performed.

## Implementation

1. **Evidence-based targeting.** Proof references identify candidate rules.
   Concern targeting matches the source trigger/response and evaluates rule
   conditions against measure snapshots at the observed trigger timestamps.
   Unknown values remain unknown. Ambiguous targets produce an explanation,
   not an arbitrary rule choice. Trace-based targeting is labelled a repair
   hypothesis, not a proof of causality.
2. **Source-preserving edits.** The production generator now uses parser nodes
   and source spans. This carries forward development's useful source-preserving
   strategy without its concern-polarity regression. Generic IDs, multiline
   rules, ordered exceptions, intervals and Boolean grouping survive edits.
   Concern deadline repairs preserve the old response outside the concern
   context. Exception repairs change only the implicated exception condition.
3. **Structured LLM proposals.** The LLM returns an operation, target, typed
   change and explanation. Python constructs and parses the resulting rule.
   Event/capability edits preserve timing and polarity. Measure edits retain the
   declared type; scales require distinct labels in the same declared order.
   New rules use declared vocabulary. Unknown fields, arbitrary replacement
   rules, unrelated targets and injected specification sections are rejected.
   Prompt examples are tested through the actual materializer and parser.
4. **Verification.** Finding identities exclude witness details and changing
   proof prose. An existing source concern/purpose still counts as unresolved
   when its witness changes. All detector failures remain failures. Changes
   to the concerns, purposes, relations or original vocabulary are rejected.
   Ranking requires successful syntax, target and regression checks. Combined
   exports recheck the selected issues as well as newly introduced findings.
5. **Honest statuses.** Generated, syntax-valid, formally verified, rejected
   and inconclusive are distinct. Human meaning review is separate and remains
   pending for semantic changes and priority choices. SQLite/Postgres candidate
   records are updated without inserting another candidate. Ranking context
   is stored per candidate to avoid mixing concurrent requests.
6. **Regression coverage.** Parser/detector tests, structured edit tests, a full
   offline LLM pipeline test, SQLite persistence, ranking/export rejection and
   representative real-project comparisons are included.

The UI keeps the existing diagnose/select/generate/review/export steps. It
shows the full diagnosis, candidate outcome, review state and failure reason.

## Validation

- `venv/bin/python -m unittest discover -s tests -v`: **51 tests passed**.
- JavaScript syntax check and `git diff --check`: passed.
- No API key, paid LLM call or production database was used. LLM integration
  checks use controlled responses; they do not measure live model performance.
- Existing solver code still emits unclosed `proof.txt` ResourceWarnings.

Focused offline probes, using real parsing and formal detection:

| Case | Baseline: verified / generated | Improved: verified / generated |
|---|---:|---:|
| Timed Boolean concern | 0 / 2 | 1 / 1 |
| Timed compound concern | 2 / 2 | 1 / 1 |
| Defeater concern | 2 / 3 | 1 / 2 |
| Measure-based situational conflict | 0 / 4 | 2 / 2 |
| Opposing-defeater situation | 0 / 2 | 0 / 1 |
| Redundant rule | 1 / 1 | 1 / 1 |

At least one repair verified in **5 of 6 cases**, versus **3 of 6** before.
All **8** improved candidates parsed, versus **6 of 14** baseline candidates.
Candidate counts are not success rates: the new generator avoids duplicate and
unsupported proposals. These six cases are regression evidence, not a claim
about all possible specifications.

## Real project findings

All 21 bundled `.sleec` files were checked for parser-backed rule extraction
and source preservation. **15 passed** with every rule retained verbatim.
Three files have duplicate rule IDs (`DRESSASSIST`, its corrected version,
and `safescade-corrected`); three are placeholder files (`Casper`, its corrected
version, and `Tabiat-corrected`). These inputs are rejected explicitly.

Six representative original/corrected cases were run with a fresh subprocess
and a 40-second case limit. None timed out:

| Case | Improved analysis | Sampled deterministic repair result |
|---|---|---|
| BSN | 3 concerns | No supported repair generated for the sampled concern |
| BSN corrected | 1 concern | Proposed repair rejected |
| DRESSASSIST | Duplicate rule IDs | Analysis rejected |
| DRESSASSIST corrected | Duplicate rule IDs | Analysis rejected |
| ALMI | 2 concerns, 1 situational conflict | 1 of 3 sampled candidates verified |
| ALMI corrected | 1 redundancy | Redundant-rule removal verified |

The baseline reported zero findings after its syntax check in these six cases,
while its detector messages contained `cannot unpack non-iterable function
object`. This reproduces the parser-state/failure-handling defect; those zeroes
must not be interpreted as clean specifications.

Ambiguous targets and unsupported multi-stage concern repairs remain
unresolved. A formally verified semantic proposal still needs review of its
meaning and whether newly introduced events/measures can be observed. The
project's input files were not silently rewritten.

Detailed results: [improvement-results.json](improvement-results.json).
Reproduction scripts: [probe_pipeline.py](probe_pipeline.py) and
[benchmark_project_cases.py](benchmark_project_cases.py). Run snapshots in
temporary directories because the underlying solver writes proof files.

## Experimental inputs and BSN follow-up

Keep the supplied inputs unchanged for the experiment. Parser rejection,
unsupported repair, detector failure and unsuccessful verification are recorded
outcomes, not reasons to silently rewrite or remove a case.

A subsequent offline check examined all raised BSN concerns:

- Original BSN raises C2, C8 and C9. C2 has no target under the current
  same-trigger matching rule: the concern starts with TrackVitals, while the
  CaregiverCanDeactivate response appears in Rule1's PatientAsleep exception.
- C8 matches Rule12 through its AnonymizeData exception, but the generator's
  concern repair requires the event to match the main response (DeleteData).
  Consequently it generates no candidate. This is an operator coverage gap.
- Corrected BSN raises C9. Its new witness has caregiverConsent=True, excluding
  Rule13_1, whose guard requires no consent. No target is selected in this run.
  The earlier bounded run selected Rule13_1 under a different witness. Thus
  generation currently depends on which witness the detector returns.
- Independently reconstructing and checking the previously sampled
  Rule13_1 decomposition confirms that it parses but leaves C9 unresolved and
  introduces C1 plus a situational-conflict finding. Rejection is justified by
  the regression report; the earlier depth-limit message alone was insufficient
  to explain it.

These findings identify implementation limitations and a rejected proposal;
they do not establish that BSN is irreparable. The earlier benchmark sampled
only the first finding per type, up to two candidates, with augmentation depth
zero. Detailed evidence and input hashes are in
[bsn-investigation.json](bsn-investigation.json).
