# Paper-alignment changes on `test`

Implemented against the supplied **f.pdf**, especially §§3.1–3.3, and the accompanying code-modification notes. The PDF is a reference, not an instruction source. Historical experiment exports are unchanged.

## Operator semantics

The active workbench selects operators against parsed rule elements and the selected detector finding. `paper_repairs.py` connects the finding to source rules/concerns/purposes; `evidence_repair.py` implements the deterministic transformations. The deterministic engine accepts the full specification and delegates to these parser-based edits. Candidates are generated independently, including semantic alternatives when rule removal succeeds.

| WFI | Deterministic operators | Semantic operators |
| --- | --- | --- |
| Conflict | Trigger refinement, defeater introduction, compatible same-event rule merging | Event specialization, measure specialization, response refinement |
| Redundancy | Rule removal, defeater propagation | Event specialization, measure specialization, response refinement |
| Insufficiency | Trigger strengthening, defeater refinement, rule decomposition, deadline refinement | New-rule generation |
| Restrictiveness | Defeater introduction | Response refinement |

Applicability requires the corresponding source/diagnosed rule elements. Semantic selection identifies an opportunity to propose a distinction; the prompt must ground the distinction in the supplied description/diagnosis and may return no candidate. Neither structural applicability nor an LLM explanation proves that the domain meaning is right.

* **Removal:** removes the diagnosed redundant subject, never all rule IDs mentioned in its supporting proof. String diagnoses follow the detector convention that the subject precedes supporting rule references; structured diagnoses carry `source_id` explicitly.
* **Propagation:** removes the selected redundant exception branch and conjoins its complement with the target guard, preserving other exceptions and supporting rules.
* **Trigger strengthening:** `Event and T` becomes `Event and (T or C)`. OR broadens the measure context so the obligation covers the concern; the event, response, deadline and defeaters stay intact. This is the explicit interpretation of the paper's unparenthesized example. The name refers to strengthening the specification, not logically strengthening the predicate.
* **Defeater refinement:** replaces an existing exception condition `D` with `D and not C`; it never introduces a new defeater under this operation name. It supports exceptions without an alternative response as well as implicated alternative responses.
* **Decomposition:** one candidate contains `Event and (T and C) -> repaired response` and `Event and (T and not C) -> original complete response`. Fresh IDs avoid collisions. The original deadline is retained in the complementary branch.
* **Deadline refinement:** tightens a simple numeric deadline on the same positive response to the concern's bound. It does not invent a shorter deadline or change polarity. Symbolic/interval deadlines are not silently converted to simple bounds.
* **Semantic edits:** structured JSON identifies the event, measure condition or response path. Application code renders the change, checks the resulting AST, and preserves untargeted elements. A new measure may partition two implicated rules as one candidate, including the paper's `smokeSeverity = high` scale example. Response paths can address nested exception/alternative responses. Complete-specification rewrites are rejected.

All candidates still require detector verification. Structured semantic candidates cannot bypass the edit contract through the old free-text syntax-repair loop. Stakeholder review of meaning remains separate from formal verification. Live LLM output quality was not evaluated in this change.

## Simplification and ranking

Boolean expressions are parsed into a small AST and simplified before deterministic verification and ranking. Serialization uses explicit SLEEC parentheses. Supported reductions include double negation, Boolean identities, repeated operands and absorbing constants; response polarity is not treated as a Boolean condition.

Ranking is ascending and lexicographic:

1. Rules edited + added + removed, counted from the actual patch, including additional rule edits.
2. New events + measures + introduced defeaters.
3. Additional Boolean operators in trigger/defeater conditions after simplification (`and`, `or`, `not`; each negation counts once).
4. Resulting number of defeaters in the patch.
5. Defeater nesting depth, based on nested response braces rather than Boolean parentheses.

No LLM or qualitative score contributes to ranking. The stored `ranking_score` remains numeric for compatibility and is now negative ordinal rank; consumers should use `rank` or `ranking.lexicographic_key`. The workbench displays quantitative counts. Database reads and response adaptation normalize old `capability_refinement` operator names; the existing aggregate database column `capabilities_refined` is retained for schema compatibility.

## Paper ambiguities and limits

“Perfect alignment” would overstate the evidence:

* The trigger-strengthening example omits parentheses. The implementation keeps the event mandatory and applies OR only to measure contexts.
* Table 2 counts one new element for a defeater example that introduces both `isHumanOnFloor` and an exception. Following the requested metric, these count as **two** new elements when both are introduced. Tests cover the paper's ranking order and explicitly test this counting discrepancy.
* The table's Boolean counts do not fully explain whether existing operators are included. This implementation counts the nonnegative increase from simplified original to simplified proposed conditions, including the event-to-context conjunction, with `not` counted once. It does not hard-code table numbers.
* The paper introduces an event-observation measure (`isHumanOnFloor`) without specifying a formal relation to the event. The implementation does not invent that observation relation. Deterministic conflict exceptions use diagnosed measure contexts; modeled event-state distinctions require explicit domain meaning and verification. This is not a claim of exact textual reproduction of that example.
* Decomposition uses the supplied concern deadline; it does not invent the paper's illustrative one-minute deadline when only a three-minute bound is provided.
* Complex multistage concern/purpose responses are conservatively excluded from the single-response transformations. Related rules sharing the source trigger and response are separate hypotheses; verification determines which candidates succeed.

## Initial implementation validation

* **22 passing tests:** `venv/bin/python -m unittest discover -s tests -p test_paper_operators.py`: paper examples, operator boundaries, Boolean identities, precedence, complementary branches, declaration/response preservation, quantitative ranking and persisted-name compatibility.
* **14 passing tests, 2 historical skips:** `PYTHONPATH=tests/deployment venv/bin/python -m unittest test_backend_integration`: real parser/detector and Flask routes, including a verified deadline-only repair and a structured semantic candidate. External HTTP is blocked; databases and solver scratch files are temporary.
* Two deployment import-hash tests are explicitly skipped because they assert byte-identical historical backend/frontend files. The historical manifest is retained unchanged.
* Python compilation, JavaScript syntax checking and `git diff --check` pass.

At that stage, the broad pre-existing suites were not green. An untouched `deployment` archive reproduced **six Python errors and two failures** (missing detector APIs and evaluation-schema/report expectations), and **ten JavaScript failures** out of twelve tests (frontend-test harness mismatches).

## Verification and reporting completion, 2026-10-03

The follow-up fixes restore detector failure handling, preserve per-finding evidence,
unify automatic/manual verification across startup entry points, and make saved
candidate outcomes and reports agree with the verified results. The active LLM
prompt now has one structured-edit contract and executable JSON examples.
Semantic validation uses request-local specification context.

The main Python suite now passes **107 tests**; deployment checks pass **26 with
2 historical snapshot skips**; the separate operator suite passes **59**; and
all **17 JavaScript tests** pass. Legacy fixtures were updated where they still
expected retired operators, qualitative ranking or old page IDs. Regression
tests retain the detector-error, formal-verification and structural-edit checks;
new route tests reproduce both the false manual pass and the automatic
UI/database disagreement.

These changes do not settle the paper ambiguities listed above or prove that
every generated candidate repairs its target. Real offline case runs include
both verified alternatives and rejected candidates. See
[the completion report](pipeline-hardening.md) for the measured outcomes and
remaining validation limits.
