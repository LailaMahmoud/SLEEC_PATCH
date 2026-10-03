# Combined Overleaf download

After deploying this change, open **Evaluation Results**, choose a use case
or **All use cases**, then select **Download LaTeX**. The downloaded `.tex`
file contains the co-author's three tables:

1. Verified patch results, including rank and overall M-Sim.
2. Component-level manual similarity (M-Sim).
3. Original, expert-corrected and generated specification comparison.

Upload the file to Overleaf. Add these packages to the main document preamble:

```latex
\usepackage{booktabs,multirow,graphicx}
```

Include the downloaded file inside the document, for example:

```latex
\input{sleec-patch-report-almi.tex}
```

The download uses `/api/sleec-patch/download-report-latex?use_case=ALMI`.
Omit `use_case` to export all cases. Both this endpoint and the existing ZIP
endpoint now use the application's configured database store, including
PostgreSQL. The standalone script still accepts a local SQLite `--db` path.
Exporting computes similarity locally and does not call an AI service or
update saved patch results. Repeated patch IDs retain the script's existing
latest-result selection; rankings are matched to the corresponding repair run.

Similarity requires the matching original and expert-corrected `.sleec`
files. Missing references are shown as `--`. Generated specification columns
require the separately verified cumulative `results/<case>/<case>_SLEECPATCH.sleec`
file. Missing cumulative files are also shown as `--`; the download does not
combine alternative repair candidates into an unverified final specification.

Validation: 125 main Python tests, 28 deployment tests, and 18 JavaScript tests
passed; two historical deployment checks were skipped. New coverage includes
the combined attachment, similarity values, case filtering, read-only result
handling, missing references and both download routes. PostgreSQL routing was
checked with a mocked driver. A live PostgreSQL connection, the deployed
download and LaTeX compilation were not tested.
