# Deterministic repair investigation

Investigated on 2026-10-03. This follow-up covers deterministic generation,
formal verification and the bundled case inputs. All case probes below disable
model generation and external HTTP and use temporary SQLite and solver files.

## Causes and changes

**ASPEN: one proof did not describe every competing obligation.** A conflict
proof for `R4` may name only `R13`, although `R7_1` also prohibits deployment.
The old generator edited one pair at a time, leaving another conflict on `R4`.
The generator now constructs combined contexts from same-trigger rules with
opposite immediate responses. It accounts for exception conditions and their
priority. It offers a trigger refinement and a defeater on the conflicting
response branch; nested exceptions retain their scope through braces.

These additional rule matches are repair hypotheses derived from the source.
They do not replace or expand the recorded solver proof. Every candidate still
passes through the complete syntax, selected-issue and regression checks.
The priority choice remains visible in its explanation.

**The full ASPEN probe spent time on incomplete or unchanged alternatives.**
Pairwise variants are omitted when a combined repair is constructed for that
target. Decomposition also skips splitting an identical response into
complementary guards: that transformation preserves the original behaviour and
cannot resolve the concern. The original 240-second probe limit is unchanged.

**ALMI: the candidate copied a condition between different trigger times.**
The original witness has `SmokeDetectorAlarm` at time 0 and `HumanOnFloor` at
time 300. The candidate restricted `R3`'s exception using `R21`'s alarm-disabling
condition. That condition is read at the fall's time, and can differ from its
value when the smoke alarm triggered the outstanding obligation. The conflict
therefore remains. This fallback is now restricted to the same trigger with
immediate responses. A solver regression retains the counterexample to the old
edit.

The ALMI conflict remains unresolved under the currently supported deterministic
edits and supplied model. Its candidate list is empty rather than containing
the unsupported fallback. A verified repair would require a supported temporal
transformation or explicit model context defining how the obligations interact.

**DressAssist: two distinct declarations used `Rule20_1`.** The information
discarding rule now uses the unused identifier `Rule20_3`. The original and
corrected source copies and the input workbook agree. Duplicate-ID rejection
remains in place for ambiguous input.

## Validation

- Main Python suite: **114 passed**, including seven new regression tests.
- Deployment checks: **26 passed, two historical snapshot checks skipped**.
- Separate deterministic operator suite: **59 passed**.

The new tests cover combined repairs when the proof mentions only one opponent,
exception priority and nesting, temporal exclusions, rejection of ALMI's old
edit, unchanged decomposition, and matching unique DressAssist identifiers in
the source files and workbook. An existing decomposition fixture now changes
the response deadline so its identifier-collision check exercises an actual
edit.

Measured case summaries are in
[`deterministic-case-results.json`](../reviews/verification-hardening/deterministic-case-results.json).

| Case | Runtime | Deterministic outcome |
| --- | --- | --- |
| ASPEN | 167.839 s | Full probe completed within 240 s. Verified alternatives for all three conflict subjects (`R4`, `R7_1`, `R13`), concerns `c4`/`c5`, and redundant `R14`. Twelve verified candidate rows saved. Concerns `c7`/`c8` remain. |
| ALMI | 41.799 s | Three verified alternatives for `c1`/`c4`. No deterministic candidate for the unresolved `R3` conflict; no successful conflict result saved. |
| DressAssist | 10.519 s | Diagnosis now succeeds with unique IDs. Concern `c5` remains, with no deterministic repair or successful result. |

Each issue is repaired against the original specification. Verified counts are
alternative candidate rows, including repairs shared by different issue
subjects; they are not one composed, fully repaired specification. `OK` means
the probe completed, not that every diagnosed issue was repaired.

Reproduce from the repository root:

```sh
venv/bin/python -m unittest discover -s tests
venv/bin/python -m unittest discover -s tests/deployment
PYTHONPATH=SLEECpatch/app:. venv/bin/python -m pytest -q SLEECpatch/tests/SLEEC_PATCH_tests
venv/bin/python scripts/check_repair_cases.py --case aspen.sleec --case ALMI.sleec --case DRESSASSIST.sleec --output /tmp/deterministic-cases.json --timeout 240
```
