# BSN repair results

Implemented locally on `improvement/pipeline-robustness`. No deployment or
commit was made. The experimental inputs are unchanged; their SHA-256 hashes
match the earlier investigation.

## Verified results

| Input | Original concerns | Accepted additions | Remaining findings after repair |
|---|---|---:|---:|
| BSN | C2, C8, C9 | 3 | 0 |
| BSN corrected | C9 | 1 | 0 |

Each addition was checked independently against the original input. The three
original-BSN additions were also combined through the workbench's export path
and checked together. All five detectors completed successfully: concern,
conflict, purpose blocking, redundancy and situational conflict. Every original
rule remains verbatim, including consent protection, deletion requirements,
deadlines and exceptions. The repair does not change the concern, purpose,
relation or original vocabulary blocks.

Generated output copies, separate from the experiment inputs:

- [BSN repaired](generated/BSN-repaired.sleec)
- [BSN corrected, repaired](generated/BSN-corrected-repaired.sleec)

## Implementation

The generic `concern_completion` operator adds an obligation derived from a
single source concern: the same trigger and full condition, with the opposite
response occurrence and the original time window. It never turns a witness's
measure values into new requirements. Unsupported sequences, alternatives and
ambiguous source IDs remain unsupported. Existing protections are preserved
instead of reversing a prohibition's polarity.

C2 now supports adding the missing obligation even though the related response
occurs under a different trigger. C8's exception is recognised without replacing
the deletion response. C9's addition is identical whether the returned witness
has caregiver consent or lacks it. Related nested responses are recorded as
context, separately from authorised rule-edit targets and causal proof IDs.

Structured LLM additions may use a source concern as their anchor without
inventing an existing rule target. The materializer validates that anchor and
copies the source timing, including `eventually`, intervals and symbolic bounds.
It rejects changed source actions, polarity, timing and injected rules. The
prompt supplies a matching structured example. Status, review and export gates
apply to these additions as they do to other proposals.

## Situational-checker defect uncovered by C9

The initial additive C9 candidate cleared the concern but produced a
situational-conflict report involving the consent and notification rules. Its
trace omitted a required earlier notification. Inspection identified defects
in the normalised prefix encoding:

- Trigger conditions could use a measure snapshot from another timestamp.
- The absence/deadline condition was inside a universal event quantifier and
  used the wrong time direction. This mishandled empty response traces.
- A chained Python comparison could drop an interval's lower bound.
- `eventually` and a finite 99,999-second window were conflated; symbolic
  windows could also be treated as instantaneous through object truthiness.

These defects are fixed. A finite obligation becomes violated after its deadline
in the open-prefix convention used by `model_based_inst`; responses may still
occur at the current timestamp. Unbounded occurrences retain their meaning in
prefix violation/fulfilment checks. Genuine situational-conflict detection is
covered by the existing witness/proof regression test, which still passes.

## Validation and limits

- **67 automated tests pass**, including 16 new BSN/normalisation tests.
- Python parsing, JavaScript syntax and `git diff --check` pass.
- The six-case project regression completed without timeouts. DRESSASSIST's
  duplicate-ID inputs remain explicitly rejected and unchanged. ALMI corrected's
  redundancy repair still verifies. A follow-up checking every candidate for
  ALMI's sampled concern confirms its previously successful exception repair
  still verifies; the new addition is correctly rejected there. The standard
  two-candidate sample does not reach that third candidate.
- These are results under the existing solver limits, not a completeness proof
  for arbitrary specifications. The normaliser's blocking search still uses its
  existing finite representative horizon; it has not been fully redesigned.
- Formal acceptance does not establish stakeholder agreement or operational
  feasibility. In particular, an immediate prohibition and an eventual response
  have different time scopes; human review must confirm the intended meaning.

Full evidence, regression results and implementation hashes:
[bsn-repair-results.json](bsn-repair-results.json).
Test output: [bsn-tests.txt](bsn-tests.txt).
Re-run automated checks with `venv/bin/python -m unittest discover -s tests -v`.

## Live LLM test awaiting approval

The offline integration test exercises a structured LLM response through the
real parser, all detectors, ranking, persistence calls and export, with the
model response controlled by the test. It does not measure real model quality.

The live attempt had a connection error in the sandbox. Automatic approval
review then rejected network access because the request would send private BSN
rules and diagnosis to OpenAI without explicit permission for that transfer.
No model response was obtained, and no workaround was attempted.

The prepared request uses the application's `gpt-4o-mini`, temperature 0,
one API call, no API retries and a 1,200-token completion cap. At most two
returned proposals would be formally checked. The exact credential-free payload
is available in [bsn-live-request.json](bsn-live-request.json). The request uses
the existing [Chat Completions API](https://developers.openai.com/api/reference/python/resources/chat/subresources/completions/methods/create).
