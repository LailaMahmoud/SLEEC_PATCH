# Paper methodology correction

The author requires the methodology in Section III.B
`. Deterministic new-rule generation is not part of that
method. The added `concern_completion` operator has been removed, and its BSN
repair successes are excluded from paper-method results.

## Generation boundary

| Stage | Responsibility |
|---|---|
| Deterministic generation | Transform existing rules using the diagnosed evidence and supported syntactic repair operators. |
| LLM generation | Propose semantic refinements, including the contents of any new normative rule. |
| Application code | Validate structured fields and render the LLM's proposed edit in valid SLEEC. |
| Formal verification | Require the selected issue to disappear and no new issues to appear, with every detector completing successfully. |
| Ranking and human review | Rank only formally verified candidates; stakeholder meaning remains subject to review. |

The paper lists trigger refinement, defeater introduction, rule merging, rule
removal, trigger strengthening and rule decomposition as deterministic
transformations. It assigns event specialization, measure specialization,
capability refinement and new-rule generation to the LLM. This correction
restores that generation boundary; it does not establish complete implementation
or experimental coverage of every operator listed in the paper.

## Changes enforcing the boundary

- The deterministic selector and generator no longer offer concern completion.
  Requests for that operator or an LLM semantic operator are rejected by the
  deterministic generator.
- A source concern can supply diagnosis context and an anchor for an LLM
  proposal, without choosing its new rule. The prompt uses an unrelated
  illustrative example rather than a precomputed answer to the actual case.
- The LLM supplies the new rule's trigger, condition, response, polarity and
  timing. It may explicitly request exact source timing. Application code
  validates and renders those choices, preserving every existing rule.
- No model output, or a model failure, produces no semantic candidate. There is
  no deterministic new-rule fallback.
- Previously saved concern-completion candidates are rejected by application,
  ranking and export even if their old records say they were formally verified.

## Evidence and remaining work

All **70 offline tests pass**. These include real parsing and formal checks,
controlled LLM integration, failed/empty model responses, source preservation,
and rejection of retired saved candidates. Controlled responses are handwritten
test fixtures and do not measure live LLM quality.

The current deterministic generator produces no candidate for the sampled BSN
concerns C2, C8 and C9, or corrected BSN's C9. The appropriate next experimental
step is real LLM generation followed by the existing formal verification gates.
No live model response has been obtained, so paper-method BSN repair success
remains unmeasured.

See [current BSN status](BSN_REPAIR_RESULTS.md), [test output](paper-method-tests.txt)
and the [excluded historical evidence](excluded-nonpaper/README.md).
