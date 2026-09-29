# Run-order investigation

Sequence: DAISY → ALMI → ASPEN → original DAISY, within one process per implementation.
The detector cache was bypassed. Inputs were unchanged. No LLM or database was used.

| Implementation | First DAISY diagnosis | Returning to DAISY |
|---|---:|---:|
| Local improvement branch | 8 | 8 |
| Local development snapshot | 7 | 7 |

The reported fresh count of 9 followed by a reduced count was not reproduced.
This check excludes the repair-generation stage and report queries. It therefore
cannot establish the cause of the co-author's reported problem or claim it fixed.
The different initial counts also mean neither local setup matches her stated
fresh result. Her precise code version, input and action sequence are needed.

Counts are compared directly. The saved first lines identify the concerns and
redundancy, but not the situational-conflict identities. Equal counts alone do
not establish equality of every finding.

`current.json` and `development.json` contain measured results. `metadata.json`
records provenance and limitations. `probe.py` reruns the same check with:

`venv/bin/python probe.py IMPLEMENTATION_ROOT INPUT_DIRECTORY OUTPUT_JSON`
