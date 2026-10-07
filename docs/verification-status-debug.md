# Verification status mismatch

Investigated on the `test` branch, starting from `5452ca7`, on 2026-10-03.

## Reproduced causes

Directly starting `app.py` did not install the response adapter used by
`deployment_app.py`. Deterministic repairs could pass the detector, selected-issue
check and regression check, then be returned with `verified: true` but without
`formally_verified`. The workbench requires both fields. The results store used
`verified`, so the same run could display “No verified patch found” while saving
a genuinely verified repair. This was reproduced with the real detector and a
temporary SQLite database: two saved repairs, zero selectable repairs.

The direct-start manual verification route only checked syntax and successful
detector execution. It therefore returned `valid: true` for an unchanged input
whose concern remained. The deployment adapter previously supplied the missing
selected-issue/regression checks only for the deployment entry point.


## Validation

Run from the repository root:

```sh
PYTHONPATH=tests/deployment venv/bin/python -m unittest test_backend_integration test_verification_contract
venv/bin/python -m unittest discover -s tests -p test_paper_operators.py
node --test tests/test_verification_status.js
```

After the completion pass: 107 main Python tests passed; 26 backend tests
passed, with 2 historical import-snapshot checks skipped; 59 separate operator
tests passed; all 17 JavaScript tests passed (including these 4 status checks).
Backend checks use the real detector and temporary databases, with external HTTP
blocked. The JavaScript tests run the workbench logic with a small DOM stub,
not a browser. See [the completion report](pipeline-hardening.md) for commands,
case-study results and limits.

The bundled ALMI case was also run against the raw `app.py` routes with the real
detector, a temporary database, one automatic attempt and LLM generation disabled.
For `situational_conflicts_1`, the generated `defeater_introduction` candidate was
rejected because the selected conflict remained. The response contained zero
verified repairs, and no successful result was saved. Verifying the unchanged
ALMI input manually also failed.

The starting revision lacked the detector APIs referenced by
`tests/test_sleec_verification.py`. The completion pass restored those APIs and
their failure checks while preserving structured diagnosis evidence and AST
context. That suite now passes. Existing parser resource warnings about
`proof.txt` remain.
earlier rows belong to the failing situational-conflict run.
