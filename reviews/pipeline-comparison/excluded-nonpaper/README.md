# Excluded historical artifacts

Every file in this directory is **excluded from the paper-method results**.
These records used the subsequently removed deterministic `concern_completion`
operator, or were prepared for that withdrawn implementation. They are retained
only so the earlier claims and their correction can be audited.

- `bsn-repair-results.json` and `generated/`: old verification records and
  generated specifications. Their historical success flags are not current
  paper-method acceptance.
- `bsn-operator-ablation.json`: historical comparison with and without the
  extra operator, reusing earlier verification for identical outputs.
- `bsn-tests.txt`: superseded test output for the withdrawn implementation.
- `bsn-live-request.json`: obsolete prepared payload. Do not send it; its prompt
  includes a precomputed case-specific answer. No live model response was obtained.
- `WITHDRAWN_*.md`: superseded reports, including a recommendation to treat
  deterministic additions as an extension. The author rejected that extension.
- `manifest.json`: exclusion reason and hashes of the archived artifacts.

Raw historical records are preserved unchanged. Do not count, import or present
them as repairs produced by the current paper methodology. The current status
is in [BSN_REPAIR_RESULTS.md](../BSN_REPAIR_RESULTS.md) and
[METHOD_CHECK.md](../METHOD_CHECK.md).
