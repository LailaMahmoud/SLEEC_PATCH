# Deployment backend import

The `deployment` branch uses the 11 requested backend files from
`sleec-patch-empowered` at commit `7780b5e`, with the live frontend preserved.
The complete source commit and per-file SHA-256 checksums are recorded in
`deployment-backend-import.json`.

## What was imported

All 11 requested files are byte-for-byte source copies, including `app.py`,
`prompts.py`, and `manual_similarity_evaluator.py`. Two direct dependencies
were also copied from that commit:

- `services/patch_ranker.py`: the previous branch's ranker imposed an additional
  verification filter that is not part of the imported engine's ranker contract.
- `scripts/export_overleaf_tables.py`: imported `app.py` requires its export
  helpers and it uses the new manual similarity evaluator.

Unlisted modules, the shared LEGOS/parser code, and experimental input files
remain from the deployment baseline. This is an import of the specified active
backend and the two dependencies above, not a wholesale checkout of the source
branch. The previous backend-specific regression suite is not an acceptance
suite for this different implementation; deployment integration checks are
under `tests/deployment/`.

## Frontend preservation

Every file under `SLEECpatch/app/templates/` and `SLEECpatch/app/static/` was
snapshotted before the import. All 35 files retain their original bytes.
The 12 public CSS/JavaScript assets used by the live workbench, report and expert
review pages were downloaded and matched against the local copies on
2026-09-30. The previously uncommitted frontend changes are therefore preserved
on this branch rather than replaced with the older frontend from `main`.

## Deployment compatibility

The container starts `deployment_app:app`. It imports the unchanged source
`app.py` and installs `services/deployment_frontend_compat.py` for the existing
frontend's response contract:

- Map the imported backend's verification verdict to the frontend's status
  fields. The adapter does not generate, repair, rank or persist patches.
- Supply recorded-diagnosis and repair-run fields used by the live report page,
  keeping patch counts separate from issue/run counts and scoping review totals
  to the selected use case. JSON downloads receive the same additional fields.
- The source manual-edit endpoint checks syntax and detector completion. The
  live editor's acceptance button also promises that its selected issue has been
  resolved. For that response, reuse the imported engine's target/regression
  methods against the posted original input before setting `valid`.

These adaptations are outside the copied backend files and do not reinstate
our earlier automatic repair operators or LLM prompts. Manual edit verification
is an additional integration check; the source backend's verification semantics
otherwise govern automatic repair results.

The source branch's additional endpoints are retained. Its standalone LaTeX/ZIP
export helper uses a local SQLite database; this import does not convert that
helper to PostgreSQL. The currently deployed frontend uses the report API and
JSON export. The LaTeX/ZIP dataset path has not been validated against the live
production database.

## Excluded files

24 inactive numbered, suffixed and backup Python variants were removed from this
branch. `.gitignore` and `.dockerignore` exclude those file families while
explicitly retaining their canonical active modules. They remain in prior Git
history; this does not rewrite repository history. Local credentials, logs and
pre-generated Overleaf artifacts are excluded from the container build.

## Validation

- 15 offline integration checks passed:
  `venv/bin/python -m unittest discover -s tests/deployment -v`.
- The checks compile all imported files, compare backend/frontend checksums,
  test real diagnosis and deterministic repair, exercise an LLM-response fixture,
  and test manual verification, reports, JSON export and expert review with a
  temporary SQLite database. External HTTP is blocked in these tests.
- Local browser checks passed for profession/instructions, real diagnosis,
  generation of a deterministic repair, patch selection, verification handoff,
  populated report counts and the expert-review page. No JavaScript exceptions
  or mobile horizontal overflow were observed. Original input was preserved.
- A Linux AMD64 Docker image built successfully. With networking disabled and a
  dummy API key, the deployment entry point served the three main pages and the
  report API with HTTP 200. Backup engine files and `.env` were absent.
- No live LLM request, production-database test, push, or deployment was performed.

Imported source and preserved frontend whitespace were retained intentionally;
whitespace-only warnings in those files must not be resolved by changing their
bytes during this import.
