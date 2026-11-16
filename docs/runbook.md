# IDS operational runbook

## Scope, approval and prerequisites

Run from the repository root, in a **fresh task** configured with the required
network/secret bindings. Changing a managed environment's configuration does not
retroactively bind secrets to an existing task; start a new task after changes.
No command here authorizes a database load or deletion by itself. Obtain the
operator's approval for the project, manifest, source ranges and operation first.
Do not merge a PR or apply migrations as part of this runbook.

- Python 3.12, Git, and the pinned runtime dependency:

  ```sh
  python -m venv work/venv
  work/venv/bin/python -m pip install -r requirements-ids-runner.txt
  ```

- Allow outbound HTTPS to **api.supabase.com** for the worker route. There is no
  direct Postgres/TCP or Supabase connector fallback in these runners.
- Bind variable **SUPABASE_PROJECT_REF** to the `allowed_project_ref` in the
  approved manifest. Bind secret **SUPABASE_ACCESS_TOKEN** to api.supabase.com.
  Never place token values in shell history, arguments, Git, output or documents.
- Optional source capture additionally needs HTTPS to **sheets.googleapis.com**
  and a **GOOGLE_SHEETS_ACCESS_TOKEN** secret scoped to that domain with read
  permission on the source workbook. Supabase credentials are never sent there.
  A private export from an authorized Sheets connector is also supported below.
- Local validation requires Docker through the local Unix socket and the pinned
  PostgreSQL image used by `scripts/validate_local.py`. It uses invented fixtures
  only and strips inherited hosted credentials.

The active versioned scope is `docs/source-audit-v2.json`, SHA-pinned in
`config/approved-load-manifests.json`. It supplies workbook ID, allowed project,
tabs, sheet IDs, headers, exact row ranges/checksums, dependency order, trial
scope, batch defaults and retained-warning rows. Unknown or modified manifests
are refused. A new source version requires review and a new/updated registry
pin; do not edit a manifest merely to force a source mismatch through.
The fixed model allowlist is an independent second project check. Environment
and manifest refs must both match it. IDs are metadata, never credentials.

## Private data and state contract

All working files are under the ignored **work/** directory. Inputs are JSON,
not executable pickle files. Paths outside work/ and symlink escapes are refused.
Files are created mode 0600; state directories mode 0700. Keep filesystem access
private. Do not commit or upload extracts, snapshots, CSVs, journals, metrics,
failure queues, lock files, environment files or tokens.

For a run, files are under `work/ids/<run-id>/`:

- `control.json`: manifest and immutable snapshot binding, never source values.
- `<run-id>.json`: durable journal, including the pending attempt/receipt.
- `<run-id>.started`: separate generation marker; `<run-id>.lock`: run lock.
- `plan.json`, `progress.json`, `metrics.json`, `result.json`: private operational
  state/audit metadata. Request failures contain sanitized status/header/timing
  metadata only, not bodies or SQL. `failure-log.json` contains sanitized source
  file/tab/row coordinates and allowlisted reason codes only.
- `work/ids-operator.lock` serializes these commands across runs in this checkout.

All processes for a run must share the same work directory and filesystem locks.
State writes are atomic and fsync'd; durability across environment replacement
is **not established**. Preserve the whole private work directory securely. If
state disappears or is corrupt, never initialize a new first run against a
partially loaded database. Use explicit read-only rebuild/reconciliation below.
Do not clear an in_flight marker by editing files. The historical run used an
operator-provisioned state directory outside Git; this runner deliberately moves
new/rebuilt active state under ignored work/ as requested.

## Source capture and offline dry run

A manifest-only dry run needs no credentials, source files or network:

```sh
work/venv/bin/python scripts/ids_runner.py dry-run --manifest docs/source-audit-v2.json
```

It reports the approved plan and `source_validated:false`; it does **not** claim
that source rows were inspected. Capture the workbook independently twice:

```sh
work/venv/bin/python scripts/ids_runner.py capture --manifest docs/source-audit-v2.json --output work/source-pass1.json
work/venv/bin/python scripts/ids_runner.py capture --manifest docs/source-audit-v2.json --output work/source-pass2.json
work/venv/bin/python scripts/ids_runner.py dry-run --manifest docs/source-audit-v2.json --snapshot work/source-pass1.json --repeat-snapshot work/source-pass2.json
```

Capture performs read-only Google Sheets metadata reads. Each approved data
range is fetched twice with the identical A1 range: FORMULA for entered values
and FORMATTED_VALUE for displayed values. Row counts and each row width must
match exactly; a mismatch refuses capture before saving, naming the tab.
Both arrays are stored privately as data and formatted_data, then paired cell
by cell during decoding. Displayed values become formattedValue in transform()
and raw_formatted_values in database lineage; they never replace entered values
for type conversion or the approved raw-value checksum. Immediately after metadata is fetched, the
workbook timezone must exactly equal manifest source_timezone (currently
Asia/Kolkata); a missing timezone or alias such as Asia/Calcutta is refused.
This happens before fetching source rows, saving a capture or decoding it.

For every tab, capture also fetches rows last_data_row+1 through last_data_row+5,
across all approved columns, using FORMULA rendering. Any non-empty sentinel
cell, including zero, false, whitespace or a formula, refuses the entire capture
with a message naming the tab. A failed/unavailable sentinel read also refuses
capture; the runner never truncates that check or modifies the source grid.
No capture is saved or decoded until all tab sentinel checks have passed.
The five-row sentinel is a bounded check, not a scan of every later worksheet
row. The decoder additionally rejects out-of-range populated rows present in
an imported JSON export, but cannot detect rows omitted from that export.

The two decoded snapshots must match each other and every manifest checksum.
Captured source cells are checked for formulas, changed headers/IDs, missing
rows and changed values. Imported JSON that includes additional populated
columns or rows is refused. Capture does not scan outside the approved columns
or beyond the five-row sentinel. Boolean and numeric cell types are preserved;
dates remain raw serials or approved month text.
Monthly Target YYYY-MM becomes YYYY-MM-01 only in the transformed record; the
original text stays in raw lineage. Other date parsers are not broadened.

If using a connected Sheets service instead of an OAuth environment binding,
save its independently read responses privately as JSON with this contract:

```text
{
  "source_file_id": <from manifest>,
  "metadata": {"spreadsheetId": ..., "sheets": [{"properties": {
    "title": <exact tab>, "sheetId": <from live metadata>}} ...]},
  "batches": [{"tab": <exact tab>, "first": <worksheet row number>,
               "data": [[<entered scalar cell values or null>, ...], ...],
               "formatted_data": [[<displayed cell values or null>, ...], ...]} ...]
}
```

Include headers at the manifest header row and all approved data rows, without
overlapping batches. Metadata includes all data tabs and declared documentation
tabs. The original operational `metadata`/`batches` JSON shape is accepted too.
Legacy batches without formatted_data decode with null formatted lineage;
displayed values are never invented from entered values. When present,
formatted_data must have exactly the same dimensions as data. Independent
passes must match both entered and formatted lineage.
This is a format example, not source data. Never reconstruct the second pass by
copying the first. The CLI always validates private input contents before writes.

## First run, trial and full load

Choose and preserve one UUID for this import; do not generate a different UUID
when resuming an existing run. An example command to generate a new UUID is:

```sh
work/venv/bin/python -c 'import uuid; print(uuid.uuid4())'
```

Use that UUID in place of `RUN_UUID` in the following commands. The explicit
first-run operation performs only hosted read-only preflight/inventory and local
journal initialization; all 28 tables must be empty:

```sh
work/venv/bin/python scripts/ids_runner.py init --manifest docs/source-audit-v2.json --snapshot work/source-pass1.json --repeat-snapshot work/source-pass2.json --run-id RUN_UUID
```

Trial scope comes from the manifest: complete Reference List/Staff bootstrap,
Partner Organisation and Learner Profile. Reference List and Staff share one
deferred transaction; their individual checkpoints remain at most 100 rows.
Trial leaves the same import run open so full can continue it:

```sh
work/venv/bin/python scripts/ids_runner.py trial --execute --manifest docs/source-audit-v2.json --snapshot work/source-pass1.json --repeat-snapshot work/source-pass2.json --run-id RUN_UUID
work/venv/bin/python scripts/ids_runner.py full --execute --manifest docs/source-audit-v2.json --snapshot work/source-pass1.json --repeat-snapshot work/source-pass2.json --run-id RUN_UUID
```

Full can also follow init directly. Both write commands refuse to run without
**--execute AND an approved manifest**, before creating a Worker or reading
secrets/private snapshots. The batch and pause defaults come from the manifest.
They support `--batch-rows` (1–100), `--pause-seconds` (0–3600) and `--health-every`.
Parents precede children using the manifest dependency order. The runner retains
atomic business/lineage/checkpoint writes and exact source IDs. Existing chunks
are checked read-only before being skipped; a changed/conflicting record stops.
Each completed tab is reconciled before the next tab. There is no silent source
repair or automatic quarantine: this approved manifest expects zero quarantines.

## Uncertain writes and resumption

At the first failed/uncertain write, stop. **Do not rerun trial/full/resume yet.**
Keep the journal/marker, snapshots, run UUID, plan and sanitized failure log.
The default read retry budget is zero; optional `--read-retries 1` or `2` applies
only to bounded read-only transient HTTP failures and respects Retry-After.
There is never an automatic write retry. A declined write is not retried.

Run a read-only inspection first (no --execute):

```sh
work/venv/bin/python scripts/ids_runner.py reconcile --manifest docs/source-audit-v2.json --snapshot work/source-pass1.json --repeat-snapshot work/source-pass2.json --run-id RUN_UUID
```

This verifies run/snapshot scope, recorded checkpoint hashes, actual typed records
and raw lineage using indexed, payload-bounded read-only checks. For an uncertain
chunk, all committed rows/checkpoints must match exactly, or all domain/lineage
rows and checkpoints must be absent. Partial/conflicting/unknown results stop.
A checkpoint hash alone is not proof that records or lineage were not tampered.
After the read-only result is reviewed and resumption approved, accept it through
the normal reconciliation API and resume in smaller paced batches:

```sh
work/venv/bin/python scripts/ids_runner.py reconcile --accept-reconciliation --manifest docs/source-audit-v2.json --snapshot work/source-pass1.json --repeat-snapshot work/source-pass2.json --run-id RUN_UUID
work/venv/bin/python scripts/ids_runner.py resume --execute --manifest docs/source-audit-v2.json --snapshot work/source-pass1.json --repeat-snapshot work/source-pass2.json --run-id RUN_UUID --batch-rows 50 --pause-seconds 10 --health-every 20
```

The first command repeats the read-only proof rather than trusting an old report,
then records evidence and clears in_flight via the durable journal API. Resume
uses actual committed checkpoint ranges, preserving mixed historical 100-row and
new 50-row layouts. It starts at the first uncovered row, not a hard-coded source
coordinate. It does not replay confirmed writes. At each 20-batch boundary,
SELECT 1 runs with a requested 30-second statement timeout. No heavyweight
whole-workbook verification is run between batches; full reconciliation occurs
at tab/run completion. Safety checks remain inside each atomic chunk.

Missing/corrupt state requires an explicit full read-only rebuild; do not fake an
empty journal or pass an unrelated run UUID:

```sh
work/venv/bin/python scripts/ids_runner.py reconcile --rebuild-state --manifest docs/source-audit-v2.json --snapshot work/source-pass1.json --repeat-snapshot work/source-pass2.json --run-id RUN_UUID
work/venv/bin/python scripts/ids_runner.py reconcile --rebuild-state --accept-reconciliation --manifest docs/source-audit-v2.json --snapshot work/source-pass1.json --repeat-snapshot work/source-pass2.json --run-id RUN_UUID
```

Review the first result before accepting. Rebuild compares the existing database
run against the approved source/scope and verifies each record/lineage. It can be
expensive even though reads are packed into bounded requests. A running query or
uncertain prior request must be known settled before reconciliation is accepted.
A finalized-run lost response is also reconciled read-only, not blindly retried.

## Verification and failure reporting

```sh
work/venv/bin/python scripts/ids_runner.py verify --manifest docs/source-audit-v2.json --run-id RUN_UUID
```

Verification reports every table's count, RLS on all 28, zero policies/forbidden
ACLs, fee-view security-invoker flags, public.rls_auto_enable EXECUTE revocations,
required migration versions, Data API schema exclusions and security-advisor
levels. With a run UUID, it also requires a completed run and verifies all
manifest tab counts/lineage, total checkpoint coverage and retained-warning
counts. Use `verify --inventory-only --manifest docs/source-audit-v2.json` for
security/count review of an intentionally partial run before an approved clear.

As of 2026-11-16, the access query also rejects any schema-level privilege held
by PUBLIC, anon, authenticated or service_role on ids or ids_import. It expands
pg_namespace.nspacl, falling back to acldefault('n', nspowner) when NULL, so a
NULL ACL does not bypass verification. The same forbidden roles are checked in
pg_default_acl entries for both schemas and in global (namespace 0) defaults
for tables/views, sequences, functions and types, regardless of the default's
owner. Global defaults apply when objects are created in these schemas;
per-schema revokes do not subtract global grants. Reports distinguish existing
object grants, schema_grants and default_grants (scope '*' means global), with
owner, role, privilege and grant-option evidence for defaults. Verification
requires all three forbidden-grant lists to be empty. These checks run inside
the existing read-only catalog transaction; no grants are automatically revoked.
If a forbidden grant is found, stop, report the evidence and seek a separately
approved remediation. Existing relation/function ACL, RLS, policy, view,
Data API and advisor checks remain in force.

The full load's per-tab report verifies considered=loaded+quarantined,
lineage joins and exact manifest row counts; all checkpoints must be committed
before run finalization. Capture the private result/metrics files for the audit.

On failure, only coordinates and allowlisted codes go into the private durable
failure queue. Publish those fields to the project's approved failure-log Sheet
using its authenticated service, verify the readback, and stop; do not copy SQL,
provider error bodies, source values or tokens. Remote Sheet credentials/IDs and
connected-service sessions are intentionally not bundled. If that service is
unavailable, the local queue remains pending and no database operation resumes.
Resolved historical failures must be distinguished from active quarantines,
never silently presented as quarantined learners. Check all source-named failure
log tabs against the final quarantine results. The CLI does not automatically
publish to or clear a Google failure-log Sheet; this remains an explicit service
step, matching the historical operator acknowledgement boundary.

## Clear rows for an approved reload

Clearing is destructive and needs separate operator approval. Never use it as a
retry mechanism or run it on untrusted/in-flight progress. It does not load data.
First run verify above and review the before counts. Then:

```sh
work/venv/bin/python scripts/ids_runner.py clear --execute --approve-delete-rows --manifest docs/source-audit-v2.json
```

It locks all 28 target tables, checks preflight counts, deletes business rows in
reverse dependency order, then validation issues, source rows, chunks and runs,
inside one controlled transaction. It never drops/resets tables, schemas, views,
functions, sequences, RLS, grants, policies or migration history. Definitions,
access and history must match the baseline afterward, all counts must be zero,
and the advisor must remain clean. Only after successful verification are active
run directories archived under ignored work/archive/; they are not destroyed.
A subsequent new UUID + init can then establish a fresh first run.

An uncertain clear cannot be retried until read-only reconciliation succeeds:

```sh
work/venv/bin/python scripts/ids_runner.py clear-reconcile --manifest docs/source-audit-v2.json
work/venv/bin/python scripts/ids_runner.py clear-reconcile --accept-reconciliation --manifest docs/source-audit-v2.json
```

The result must be either exact pre-clear counts or all zero, with definitions,
ACLs and migration history unchanged. Anything partial or unexpected stops.
Reset the remote failure-log Sheet separately only with explicit authorization,
retaining tabs/headers and the appropriate historical audit evidence.

## Known issues and privacy limits

The historical load became unresponsive after an HTTP 544; even light worker
queries then timed out without an HTTP response. Dashboard checks and a
user-performed project restart restored responsiveness. The exact server cause
was not captured; do not call it a proven rate limit. A requested SQL statement
timeout is not an HTTP deadline: the worker HTTP timeout is 90 seconds. On either
kind of timeout, stop; do not switch routes or infer commit/rollback.

First-run reconciliation formerly issued hundreds of per-chunk requests. It now
uses one fixed inventory after preflight. Resumption/rebuild still requires exact
record and lineage verification, now indexed and packed into bounded reads; do
not replace it with checkpoint counts alone. The successful resume used 50-row
batches, 10-second pauses and a health check every 20 batches. These pauses alone
make large loads long-running; metrics count service requests, not credits.

This run used synthetic data. Source values are embedded in SQL statement text
and may reach database/request logs. **Before real client data, use a parameterised
route and verify database, parameter, error and request-log controls.** Sanitized
client diagnostics are not a server-log privacy guarantee. The real client goal
scale, IQ/height/weight necessity, units, interpretation and access remain open.


## Audit of the private operational scripts

| Private family audited | Public equivalent / exclusion |
|---|---|
| live_trial.py, live_full.py, v2-execute.py, full-approved-load.py | Run.init/trial/full, source decoder, atomic adapter and tab reports in ids_runner.py |
| resume-score-50.py | Run.reconcile_pending + resume, adaptive checkpoint ranges, pause/health controls |
| live_common.py | Worker metrics, read-only exact checks, private failure queue and accounting |
| clear_rows.py, clear_worker.py | clear/clear-reconcile and ids_catalog.py; no source rows or credential setup copied |
| live_verify.py, v2-final-verify.py, full-approved-final-verify.py | verify plus completed-run/accounting checks |
| light-score-key-check.py, light-uncertain-import-check.py, reconcile-uncertain-score.py | Explicit reconcile proof against pending deterministic chunk/row keys |
| worker_api.py | Existing allowlisted load_ids.Worker transport; duplicate credential plumbing excluded |
| source inspection/doc preparation/code patch helpers | Development-only one-offs excluded; approved checksums and capture/decoder remain versioned |
| v2-apply-migration.py | Excluded from load commands: migration application needs separate approval and standard migration workflow; applied SQL is already versioned |
| vendored work/test-deps | Excluded; runtime and test dependency is version-pinned in requirements-ids-runner.txt |

The new runner is a reviewed extraction/consolidation, not a byte-for-byte copy of
the one-off scripts. Per-run workbook values, counts, UUIDs, absolute state paths
and project credential assignments were removed. All remaining data-dependent
inputs come from the approved manifest and private snapshots. Retired v1 source
formats/scopes are not implicitly approved by this v2 registry; a different source
requires its own reviewed manifest entry. No private operational file is imported
at runtime. The source-value audit script compares every source cell value with
the whole PR file set. It reports common scalar/calendar/public-word and approved
schema/reference overlaps separately, and fails on private identifying values or
unreviewed phrases; it never prints source values or credential matches.


## 2026-11-15 — formatted-lineage compatibility

A single read-only worker query sampled worksheet rows 3–7 in Mobilisation Lead,
Lead Follow-up and Mobilisation Activity (15 lineage rows). None contained a
non-null raw_formatted_values element. No source values were returned. This
sample does not establish every row's state. Fresh paired captures preserve
formatted values and therefore will not reproduce those legacy null arrays.
Do not replay newly captured lineage against an existing import: changed-lineage
checks remain in force. A fresh import requires its own approved run and the
normal reconciliation gates; this change authorizes no reload or database edit.
Worker pacing/backoff, no automatic write retries, timezone validation and the
five-row FORMULA sentinel remain unchanged. Capture's Sheets reads fail closed;
they do not acquire automatic write retries or mutate the workbook.


## Reviewed sensitive-value overlaps — 16 November 2026

The audit treats the five income/IQ/height/weight fields and all fields in the
sensitive-details table as sensitive. It checks every matching line, including
later copies in a file. Sensitive values cannot escape via numeric, reference
or approved-metadata exceptions. Reports expose file/line/category and a digest,
never source values or surrounding text.

The one-time review is recorded in [audit-triage.md](audit-triage.md). Narrow
exceptions in config/audit-reviewed-contexts.json bind a file path, exact line
context digest and matched-value digest to either a coincidental number or a
schema/reference boundary. SHA-256 digests use a-p in place of hexadecimal digits
so the registry itself does not contain literal numeric source values in hashes.
There are no global value exemptions or production commands to approve matches
automatically. A changed context or a copy in another file requires new review;
new tests prove those cases fail. Review and update the registry deliberately
when a legitimate contextual exception changes. Never register copied source
records or source-derived statistical examples as exceptions. The registry is
not a substitute for a human privacy review of the synthetic sample.
