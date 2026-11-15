#!/usr/bin/env python3
"""Reviewed operational IDS runner. No writes without --execute + a pinned manifest.

Operational code only. All source values, control state and journals stay in work/.
"""
from __future__ import annotations
import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time
import urllib.parse
import urllib.request
import uuid
import load_ids as L
from ids_catalog import ACL_SQL, CATALOG_SQL, MIGRATIONS_SQL

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / 'work'
WRITE_COMMANDS = {'trial', 'full', 'resume', 'clear'}


def require(condition, code='SCOPE_MISMATCH'):
    if not condition:
        raise L.StopLoad(code)


def private_path(path):
    path = Path(path).absolute()
    require(not WORK.is_symlink() and path.resolve().is_relative_to(WORK.resolve()))
    require(not any(p.is_symlink() for p in (path, *path.parents) if p.is_relative_to(WORK)))
    return path


def save(path, value):
    path = private_path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            stream.write(L.canonical(value)); stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, path)
        fd = os.open(path.parent, os.O_RDONLY)
        try: os.fsync(fd)
        finally: os.close(fd)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)


def read_private(path):
    path = private_path(path)
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    with os.fdopen(fd) as stream:
        return json.load(stream)


@contextmanager
def operator_lock():
    WORK.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = private_path(WORK / 'ids-operator.lock')
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        try: fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError: raise L.StopLoad('RUN_LOCKED') from None
        yield
    finally: os.close(fd)


class Manifest:
    def __init__(self, filename):
        path = Path(filename).resolve()
        require(path.is_relative_to(ROOT))
        name = path.relative_to(ROOT).as_posix()
        registry = json.loads((ROOT / 'config/approved-load-manifests.json').read_text())['manifests']
        require(name in registry)
        data = path.read_bytes()
        self.digest = hashlib.sha256(data).hexdigest()
        require(self.digest == registry[name], 'SOURCE_CHANGED')
        self.value = json.loads(data)
        self.path = name
        m = self.value
        require(m['allowed_project_ref'] == L.SPEC['allowed_project_ref'])
        require(set(t['tab'] for t in m['tabs']) == set(L.TABLES))
        require(set(m['load_order']) == set(L.TABLES) and len(m['load_order']) == len(L.TABLES))
        require(set(m['trial_tabs']) <= set(m['load_order']))
        require(m['expected_quarantines'] == 0 and 1 <= m['resume_batch_rows'] <= m['batch_rows'] <= L.MAX_ROWS)
        require(m['pause_seconds'] >= 0 and m['health_every_batches'] > 0)
        L.AUDIT = m
        L.TABS = {t['tab']: t for t in m['tabs']}
        L.SOURCE = m['source_file_id']; L.SOURCE_VERSION = m['version']
        L.REQUIRED_MIGRATIONS = tuple(m['required_migrations'])
        self.tabs = L.TABS

    def environment(self):
        require(os.environ.get('SUPABASE_PROJECT_REF') == self.value['allowed_project_ref'])
        require(bool(os.environ.get('SUPABASE_ACCESS_TOKEN')), 'PREFLIGHT_FAILED')

    def summary(self):
        return {'manifest': self.path, 'version': self.value['version'],
                'tabs': len(self.tabs), 'source_rows': sum(t['records'] for t in self.tabs.values()),
                'source_file_id': self.value['source_file_id'], 'project_ref': self.value['allowed_project_ref']}


def decode_snapshot(path, manifest):
    """Capture JSON or the original operational metadata/batches JSON; never pickle."""
    raw = read_private(path)
    source = raw.get('source_file_id', raw.get('metadata', {}).get('spreadsheetId'))
    require(source == manifest.value['source_file_id'])
    props = {s['properties']['title']: s['properties'] for s in raw['metadata']['sheets']}
    require(set(props)==set(manifest.tabs)|set(manifest.value['documentation_tabs']), 'HEADER_CHANGED')
    grid = {}; formatted_grid = {}
    for batch in raw['batches']:
        tab = batch['tab']
        if tab not in manifest.tabs:
            require(tab in manifest.value['documentation_tabs']);continue
        if 'formatted_data' in batch:
            require(matching_dimensions(batch['data'], batch['formatted_data']), 'SOURCE_CHANGED')
            for row, displayed in enumerate(batch['formatted_data'], batch['first']):
                formatted_grid.setdefault(tab, {})[row] = displayed
        for row, cells in enumerate(batch['data'], batch['first']):
            require(row not in grid.setdefault(tab, {}), 'ROW_INVALID')
            grid[tab][row] = cells
    result = []
    for tab in manifest.tabs:
        spec = manifest.tabs[tab]; headers = spec['source_headers']; width = len(headers)
        require(props[tab]['sheetId'] == spec['sheet_id'])
        require(grid[tab].get(spec['header_row'], [])[:width] == headers, 'HEADER_CHANGED')
        require(not any(v not in (None,'')for v in grid[tab].get(spec['header_row'],[])[width:]),'HEADER_CHANGED')
        require(not any(any(v not in(None,'')for v in values)for n,values in grid[tab].items()if n>spec['last_data_row']),'SOURCE_CHANGED')
        canonical_rows = []
        for row in range(spec['first_data_row'], spec['last_data_row'] + 1):
            values = grid[tab].get(row, [])
            require(not any(v not in (None, '') for v in values[width:]), 'ROW_INVALID')
            values = (values + [None] * width)[:width]
            require(any(v not in (None, '') for v in values), 'ROW_INVALID')
            require(not any(isinstance(v, str) and v.startswith('=') for v in values), 'FORMULA_FOUND')
            canonical_rows.append([row] + values)
            cells = [{} if v in (None, '') else {'userEnteredValue':
                     {'boolValue': v} if type(v) is bool else {'numberValue': v}
                     if type(v) in (int, float) else {'stringValue': v}} for v in values]
            if row in formatted_grid.get(tab, {}):
                displayed = (formatted_grid[tab][row] + [None] * width)[:width]
                for cell, formatted in zip(cells, displayed):
                    cell['formattedValue'] = formatted
            result.append(L.transform(tab, row, cells, headers))
        digest = hashlib.sha256(L.canonical([tab, headers, canonical_rows]).encode()).hexdigest()
        require(digest == spec['raw_sha256'], 'SOURCE_CHANGED')
    require(len(result) == sum(t['records'] for t in manifest.tabs.values()))
    return L.private_snapshot(result)


def snapshots(first, second, manifest):
    require(first is not None and second is not None, 'SNAPSHOT_INCOMPLETE')
    require(Path(first).resolve() != Path(second).resolve(), 'SNAPSHOT_INCOMPLETE')
    rows = decode_snapshot(first, manifest); repeated = decode_snapshot(second, manifest)
    require(L.sha(rows) == L.sha(repeated), 'SOURCE_CHANGED')
    return rows


def matching_dimensions(entered, displayed):
    return (isinstance(entered, list) and isinstance(displayed, list)
            and len(entered) == len(displayed)
            and all(isinstance(a, list) and isinstance(b, list) and len(a) == len(b)
                    for a, b in zip(entered, displayed)))


class CaptureRefusal(L.StopLoad):
    """Safe capture diagnostics: fixed messages and approved manifest tab names."""
    def __init__(self, message):
        super().__init__('SOURCE_CHANGED')
        self.public_message = message

    def __str__(self):
        return self.code + ': ' + self.public_message


def capture(manifest, output):
    """Read Google Sheets only; Google token never goes to the Supabase worker."""
    token = os.environ.get('GOOGLE_SHEETS_ACCESS_TOKEN')
    require(bool(token), 'PREFLIGHT_FAILED')
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args): return None
    opener = urllib.request.build_opener(NoRedirect())
    source = manifest.value['source_file_id']
    require(bool(__import__('re').fullmatch(r'[A-Za-z0-9_-]+', source)))
    base = 'https://sheets.googleapis.com/v4/spreadsheets/' + source
    def get(url):
        request = urllib.request.Request(url, headers={'Authorization': 'Bearer ' + token})
        try:
            with opener.open(request, timeout=60) as response: return json.load(response)
        except Exception: raise L.StopLoad('PREFLIGHT_FAILED') from None
    metadata = get(base + '?fields=spreadsheetId,properties(timeZone),sheets(properties)')
    require(metadata['spreadsheetId'] == source)
    if metadata.get('properties', {}).get('timeZone') != manifest.value['source_timezone']:
        raise CaptureRefusal('Workbook timezone must equal manifest source_timezone (' + manifest.value['source_timezone'] + ').')
    batches = []
    for tab, spec in manifest.tabs.items():
        width = len(spec['source_headers']); column = ''; n = width
        while n: n, remainder = divmod(n - 1, 26); column = chr(65 + remainder) + column
        sentinel_first = spec['last_data_row'] + 1
        sentinel_last = spec['last_data_row'] + 5
        sentinel = "'" + tab.replace("'", "''") + f"'!A{sentinel_first}:{column}{sentinel_last}"
        try:
            extra = get(base + '/values/' + urllib.parse.quote(sentinel, safe='') + '?valueRenderOption=FORMULA')
        except L.StopLoad:
            raise CaptureRefusal('Could not read the five-row sentinel for tab ' + tab + '; capture refused.') from None
        if any(value not in (None, '') for row in extra.get('values', []) for value in row):
            raise CaptureRefusal('Non-empty cell after last_data_row in tab ' + tab + '; capture refused.')
        for first in range(spec['header_row'], spec['last_data_row'] + 1, 2000):
            last = min(first + 1999, spec['last_data_row'])
            a1 = "'" + tab.replace("'", "''") + f"'!A{first}:{column}{last}"
            values = get(base + '/values/' + urllib.parse.quote(a1, safe='') + '?valueRenderOption=FORMULA')
            formatted = get(base + '/values/' + urllib.parse.quote(a1, safe='') + '?valueRenderOption=FORMATTED_VALUE')
            entered = values.get('values', []); displayed = formatted.get('values', [])
            if not matching_dimensions(entered, displayed):
                raise CaptureRefusal('Entered/displayed read dimensions differ in tab ' + tab + '; capture refused.')
            batches.append({'tab': tab, 'first': first, 'data': entered, 'formatted_data': displayed})
    save(output, {'source_file_id': source, 'metadata': metadata, 'batches': batches})
    decode_snapshot(output, manifest)  # Reject changed headers, rows and values now.
    return {'captured': True, 'tabs': len(manifest.tabs), 'database_writes': 0}


class Worker(L.Worker):
    def __init__(self, manifest, directory, retries=0):
        manifest.environment()
        super().__init__(manifest.value['allowed_project_ref'])
        self.directory = private_path(directory); self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.diagnostics_path = self.directory / 'request-failures.jsonl'
        self.read_retries = retries; self.phase = 'preflight'; self.calls = {}; self.started = time.monotonic()
    def request(self, suffix, payload=None):
        key = self.phase + ('.query' if payload is not None else '.get')
        self.calls[key] = self.calls.get(key, 0) + 1
        try: return super().request(suffix, payload)
        finally: save(self.directory / 'metrics.json', {'requests': self.calls, 'seconds': round(time.monotonic()-self.started, 3), 'last_response': self.last_response})


def ro(worker, expression):
    return worker.read_query("BEGIN READ ONLY; SET LOCAL search_path=pg_catalog; SET LOCAL statement_timeout='30s'; SELECT " + expression + ' AS receipt; COMMIT;')[0]['receipt']


def table_counts(worker):
    expressions = []
    for schema, names in (('ids', L.INVENTORY_DATA_TABLES), ('ids_import', L.INVENTORY_IMPORT_TABLES)):
        for name in names:
            expressions.append(f"jsonb_build_object('schema',{L.literal(schema)},'table',{L.literal(name)},'rows',(SELECT count(*)FROM {L.ident(schema)}.{L.ident(name)}))")
    values = ro(worker, 'jsonb_build_array(' + ','.join(expressions) + ')')
    require(len(values) == 28 and {(v['schema'],v['table']) for v in values} ==
            {('ids',t) for t in L.INVENTORY_DATA_TABLES} | {('ids_import',t) for t in L.INVENTORY_IMPORT_TABLES})
    return values


def read_sql(worker, sql, alias):
    result = worker.read_query('BEGIN READ ONLY; ' + sql.rstrip(';') + '; COMMIT;')
    require(isinstance(result, list) and len(result) == 1, 'RECEIPT_INVALID')
    return result[0][alias]


def catalog(worker):
    return {'definitions': read_sql(worker, CATALOG_SQL, 'definitions'),
            'access': read_sql(worker, ACL_SQL, 'access'),
            'migrations': read_sql(worker, MIGRATIONS_SQL, 'migrations')}


def verify_security(worker):
    worker.preflight()
    snapshot = catalog(worker)
    access = snapshot['access']
    require(len(access['rls']) == 28 and all(t['enabled'] for t in access['rls']) and not access['policies'] and not access['grants'], 'PREFLIGHT_FAILED')
    advisor = worker.request('/advisors/security')
    require(not any(v['level'] in ('WARN', 'ERROR') for v in advisor['lints']), 'PREFLIGHT_FAILED')
    views = ro(worker, "(SELECT jsonb_build_object('count',count(*),'invoker',bool_and(coalesce(c.reloptions,'{}')@>ARRAY['security_invoker=true']))FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='ids'AND c.relkind='v')")
    require(views == {'count': 2, 'invoker': True}, 'PREFLIGHT_FAILED')
    revoked = ro(worker, "NOT EXISTS(SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace CROSS JOIN LATERAL aclexplode(coalesce(p.proacl,acldefault('f',p.proowner)))a WHERE n.nspname='public'AND p.proname='rls_auto_enable'AND(a.grantee=0 OR a.grantee IN(SELECT oid FROM pg_roles WHERE rolname IN('anon','authenticated'))))")
    require(revoked, 'PREFLIGHT_FAILED')
    return {'tables': table_counts(worker), 'rls': 28, 'policies': 0, 'forbidden_grants': 0,
            'advisor_levels': {k: sum(v['level']==k for v in advisor['lints']) for k in ('INFO','WARN','ERROR')},
            'catalog': snapshot}


def verify_loaded(manifest, worker, run_id):
    rid=L.literal(run_id)+'::uuid'
    meta=ro(worker,f"(SELECT jsonb_build_object('project',project_ref,'source',source_file_id,'version',source_manifest->>'source_version','status',status)FROM ids_import.import_run WHERE import_run_id={rid})")
    require(meta=={'project':L.PROJECT,'source':L.SOURCE,'version':L.SOURCE_VERSION,'status':'completed'},'RECONCILIATION_REQUIRED')
    tabs=[]
    for tab,spec in manifest.tabs.items():
        table=L.ident(L.TABLES[tab]['name']);sheet=spec['sheet_id'];n=spec['records']
        value=ro(worker,f"jsonb_build_object('source',(SELECT count(*)FROM ids_import.source_row WHERE import_run_id={rid} AND source_sheet_id={sheet}),'loaded',(SELECT count(*)FROM ids_import.source_row WHERE import_run_id={rid} AND source_sheet_id={sheet} AND disposition='loaded'),'quarantined',(SELECT count(*)FROM ids_import.source_row WHERE import_run_id={rid} AND source_sheet_id={sheet} AND disposition='quarantined'),'domain',(SELECT count(*)FROM ids.{table}),'lineage',(SELECT count(*)FROM ids.{table} t JOIN ids_import.source_row s USING(source_row_id)WHERE s.import_run_id={rid} AND s.source_sheet_id={sheet}))")
        require(value=={'source':n,'loaded':n,'quarantined':0,'domain':n,'lineage':n},'RECONCILIATION_REQUIRED');tabs.append(dict(tab=tab,**value))
    counts=ro(worker,f"jsonb_build_object('source_rows',(SELECT count(*)FROM ids_import.source_row WHERE import_run_id={rid}),'checkpoint_rows',(SELECT coalesce(sum(last_row-first_row+1),0)FROM ids_import.import_chunk WHERE import_run_id={rid} AND status='committed'),'bad_chunks',(SELECT count(*)FROM ids_import.import_chunk WHERE import_run_id={rid} AND(status<>'committed' OR last_row-first_row+1>100)),'error_issues',(SELECT count(*)FROM ids_import.validation_issue WHERE severity<>'warning'OR reason<>reason_code),'warnings',(SELECT coalesce(jsonb_object_agg(reason_code,n),'{{}}'::jsonb)FROM(SELECT reason_code,count(*)n FROM ids_import.validation_issue WHERE severity='warning'GROUP BY reason_code)x))")
    total=sum(t['records']for t in manifest.tabs.values())
    require(counts['source_rows']==counts['checkpoint_rows']==total and counts['bad_chunks']==counts['error_issues']==0,'RECONCILIATION_REQUIRED')
    require(counts['warnings']=={k:len(v['rows'])for k,v in manifest.value['approved_warning_rows'].items()},'RECONCILIATION_REQUIRED')
    return {'tabs':tabs,'loaded':total,'quarantined':0,'checkpoint_accounting':counts}


class Run:
    def __init__(self, manifest, run_id, rows, worker, batch_rows=None):
        self.manifest = manifest; self.run_id = str(uuid.UUID(run_id)); self.rows = L.private_snapshot(rows)
        self.directory = private_path(WORK / 'ids' / self.run_id)
        self.control = self.directory / 'control.json'
        self.journal = L.Journal(self.directory / (self.run_id + '.json'))
        scope = tuple((c[0]['tab'],c[0]['row'],c[-1]['row']) for c in L.chunks_for(self.rows))
        self.approval = L.Approval(L.PROJECT, L.SOURCE, self.run_id, L.sha(self.rows), scope, True)
        self.approval.validate(self.rows)
        self.worker = worker; self.loader = L.Loader(self.approval, worker, self.failure, self.journal)
        self.batch_rows = batch_rows or manifest.value['batch_rows']
        require(type(self.batch_rows) is int and 1 <= self.batch_rows <= L.MAX_ROWS)

    def failure(self, source, reference, reason):
        require(source == L.SOURCE and reason in L.CODES)
        path = self.directory / 'failure-log.json'
        queue = read_private(path) if path.exists() else []
        queue.append({'source_file': source, 'row_reference': reference, 'reason': reason})
        save(path, queue)
        # Durable local failure queue only. Publishing to Sheets is an explicit
        # operator step; it never acknowledges/resumes an uncertain DB write.
        return True

    def binding(self):
        return {'run': self.run_id, 'project': L.PROJECT, 'source': L.SOURCE,
                'version': L.SOURCE_VERSION, 'snapshot_hash': self.approval.snapshot_hash,
                'manifest_sha256': self.manifest.digest}

    def bind(self, create=False):
        if self.control.exists(): require(read_private(self.control) == self.binding(), 'RECONCILIATION_REQUIRED')
        elif create: save(self.control, self.binding())
        else: raise L.StopLoad('RECONCILIATION_REQUIRED')

    def initial_reconcile(self):
        receipt = self.loader.reconcile(self.rows, self.rows, authorized=True)
        require(receipt['mode'] == 'first', 'RECONCILIATION_REQUIRED')
        self.bind(create=True)
        return receipt

    def checkpoint_inventory(self):
        rid = L.literal(self.run_id) + '::uuid'
        return ro(self.worker, f"(SELECT coalesce(jsonb_agg(jsonb_build_object('id',import_chunk_id,'sheet',source_sheet_id,'first',first_row,'last',last_row,'sha256',payload_sha256,'status',status) ORDER BY source_sheet_id,first_row),'[]'::jsonb)FROM ids_import.import_chunk WHERE import_run_id={rid})")

    def rows_for(self, meta):
        rows = [r for r in self.rows if r['sheet']==meta['sheet'] and meta['first']<=r['row']<=meta['last']]
        require(rows and len(rows)==meta['last']-meta['first']+1 and len(rows)<=L.MAX_ROWS, 'RECONCILIATION_REQUIRED')
        _, expected = self.loader._chunk_sql(rows)
        require(meta['id']==expected['chunk'] and meta['sha256']==expected['sha256'] and meta['status']=='committed', 'RECONCILIATION_REQUIRED')
        return rows

    def verify_existing(self, metas):
        # Pack indexed exact checks into bounded read-only requests, rather than
        # one request per checkpoint. Every legacy row and raw lineage is checked.
        covered=set();body=self.loader._run_guard();receipts=[]
        def size(text, expected):
            sql="BEGIN READ ONLY; SET LOCAL search_path=pg_catalog; SET LOCAL statement_timeout='30s'; "+L.block(text)+' SELECT '+L.json_sql(expected)+' AS receipt; COMMIT;'
            return len(L.canonical({'query':sql}).encode())
        for meta in metas:
            rows=self.rows_for(meta)
            for r in rows:
                key=(r['tab'],r['row']);require(key not in covered,'RECONCILIATION_REQUIRED');covered.add(key)
            text,expected=self.loader._chunk_sql(rows,read_only=True)
            text=f"IF NOT EXISTS(SELECT 1 FROM ids_import.import_chunk WHERE import_chunk_id={L.literal(meta['id'])}::uuid) THEN RAISE EXCEPTION 'CHECKPOINT_MISSING'; END IF;"+text
            if receipts and size(body+text,{'checked':receipts+[expected]})>L.MAX_BYTES:
                self.read_checks(body,{'checked':receipts});body=self.loader._run_guard();receipts=[]
            require(size(body+text,{'checked':receipts+[expected]})<=L.MAX_BYTES,'PAYLOAD_TOO_LARGE')
            body+=text;receipts.append(expected)
        if receipts:self.read_checks(body,{'checked':receipts})
        return covered

    def read_checks(self, body, expected):
        sql = "BEGIN READ ONLY; SET LOCAL standard_conforming_strings=on; SET LOCAL search_path=pg_catalog; SET LOCAL statement_timeout='30s'; " + L.block(body) + '\nSELECT ' + L.json_sql(expected) + ' AS receipt; COMMIT;'
        old = self.worker.read_retries; self.worker.read_retries = 0
        try: response = self.worker.read_query(sql)
        finally: self.worker.read_retries = old
        require(response == [{'receipt': expected}], 'RECEIPT_INVALID')

    def reconcile_pending(self, accept=False, rebuild=False):
        self.worker.preflight()
        metas = self.checkpoint_inventory()
        covered = self.verify_existing(metas)
        rid = L.literal(self.run_id) + '::uuid'
        lineage = ro(self.worker, f"jsonb_build_object('rows',(SELECT count(*)FROM ids_import.source_row WHERE import_run_id={rid}),'loaded',(SELECT count(*)FROM ids_import.source_row WHERE import_run_id={rid}AND disposition='loaded'))".replace('::uuidAND','::uuid AND'))
        require(lineage == {'rows':len(covered),'loaded':len(covered)}, 'RECONCILIATION_REQUIRED')
        if rebuild:
            # DB guard checked against full approved snapshot by verify_existing.
            require(metas, 'RECONCILIATION_REQUIRED')
            self.read_checks(self.loader._run_guard(), {'run':self.run_id,'scope_checked':True})
            if accept:
                self.journal.reconciled(self.approval,'resume',evidence={'outcome':'full_readonly_rebuild','verified_chunks':len(metas),'verified_rows':len(covered)})
                self.bind(create=True)
            return {'outcome':'verified_existing_run','rows':len(covered),'accepted':accept}
        self.bind(); state = self.journal.read()
        if state['state']=='ready': return {'outcome':'ready','verified_rows':len(covered)}
        if state.get('receipt')=={'run':self.run_id,'complete':True,'rows':len(self.rows)}:
            require(len(covered)==len(self.rows),'RECONCILIATION_REQUIRED')
            status=ro(self.worker,f"(SELECT to_jsonb(status) FROM ids_import.import_run WHERE import_run_id={rid})")
            require(status in ('running','completed'),'RECONCILIATION_REQUIRED')
            if accept:self.journal.reconciled(self.approval,'resume',evidence={'outcome':'finalized'if status=='completed'else 'finalize_not_committed','verified_rows':len(covered)})
            return {'outcome':'finalized'if status=='completed'else 'finalize_not_committed','accepted':accept}
        pending = state.get('receipt',{}).get('chunks')
        require(pending and state['receipt'].get('run')==self.run_id, 'RECONCILIATION_REQUIRED')
        lookup = {m['id']:m for m in metas}
        present = [p['chunk'] in lookup for p in pending]
        if all(present):
            # verify_existing checked every row, raw lineage and checkpoint.
            for p in pending:
                m=lookup[p['chunk']]; require(m['sha256']==p['sha256'] and m['last']-m['first']+1==p['rows'])
            if accept: self.journal.reconciled(self.approval,'resume',evidence={'outcome':'committed','chunks':[p['chunk']for p in pending]})
            return {'outcome':'committed','accepted':accept}
        require(not any(present), 'RECONCILIATION_REQUIRED')
        candidates=[]
        for pending_receipt in pending:
            matches=[]
            for tab in self.manifest.value['load_order']:
                available=[r for r in self.rows if r['tab']==tab and (tab,r['row'])not in covered]
                chunk=available[:pending_receipt['rows']]
                if not chunk: continue
                _,candidate=self.loader._chunk_sql(chunk)
                if candidate==pending_receipt:matches.append(chunk)
            require(len(matches)==1,'RECONCILIATION_REQUIRED');candidates.extend(matches)
        # General read-only absence proof by deterministic source UUID and PK.
        for chunk in candidates:
            pk=next(f['name']for f in L.TABLES[chunk[0]['tab']]['fields']if f['primary_key'])
            target=L.ident(L.TABLES[chunk[0]['tab']]['name'])
            ids=[str(uuid.uuid5(uuid.UUID(self.run_id),f"{r['sheet']}:{r['row']}"))for r in chunk]
            expr=f"jsonb_build_object('lineage',(SELECT count(*)FROM ids_import.source_row WHERE source_row_id IN({','.join(L.literal(s)+'::uuid'for s in ids)})),'domain',(SELECT count(*)FROM ids.{target}WHERE {L.ident(pk)} IN({','.join(L.literal(r['record'][pk])for r in chunk)})))"
            require(ro(self.worker,expr)=={'lineage':0,'domain':0}, 'RECONCILIATION_REQUIRED')
        if accept: self.journal.reconciled(self.approval,'resume',evidence={'outcome':'not_committed','chunks':[p['chunk']for p in pending],'lineage_rows':0,'domain_rows':0,'checkpoint_rows':0})
        return {'outcome':'not_committed','accepted':accept}

    def chunks(self, covered, tabs):
        chunks=[]
        bootstrap=[]
        for tab in self.manifest.value['load_order']:
            if tab not in tabs: continue
            rows=[r for r in self.rows if r['tab']==tab and (tab,r['row'])not in covered]
            if tab in self.manifest.value['load_order'][:2]:
                require(not rows or len(rows)==self.manifest.tabs[tab]['records'], 'RECONCILIATION_REQUIRED')
            for i in range(0,len(rows),self.batch_rows):
                chunk=rows[i:i+self.batch_rows]
                require(chunk[-1]['row']-chunk[0]['row']+1==len(chunk), 'RECONCILIATION_REQUIRED')
                if tab in self.manifest.value['load_order'][:2]: bootstrap.append(chunk)
                else: chunks.append([chunk])
        if bootstrap: chunks.insert(0,bootstrap)
        return chunks

    def tab_accounting(self, tab, expected):
        rid=L.literal(self.run_id)+'::uuid';sid=self.manifest.tabs[tab]['sheet_id'];table=L.ident(L.TABLES[tab]['name'])
        value=ro(self.worker,f"jsonb_build_object('considered',(SELECT count(*)FROM ids_import.source_row WHERE import_run_id={rid} AND source_sheet_id={sid}),'loaded',(SELECT count(*)FROM ids_import.source_row WHERE import_run_id={rid} AND source_sheet_id={sid} AND disposition='loaded'),'quarantined',(SELECT count(*)FROM ids_import.source_row WHERE import_run_id={rid} AND source_sheet_id={sid} AND disposition='quarantined'),'domain',(SELECT count(*)FROM ids.{table}),'lineage',(SELECT count(*)FROM ids.{table} t JOIN ids_import.source_row s USING(source_row_id)WHERE s.import_run_id={rid} AND s.source_sheet_id={sid}))")
        require(value=={'considered':expected,'loaded':expected,'quarantined':0,'domain':expected,'lineage':expected},'RECONCILIATION_REQUIRED')
        return dict(tab=tab,**value)

    def execute(self, trial=False, pause=None, health_every=None):
        self.worker.preflight(); self.bind()
        state=self.journal.read(); require(state['state']=='ready','RECONCILIATION_REQUIRED')
        metas=self.checkpoint_inventory();covered=self.verify_existing(metas)
        rid=L.literal(self.run_id)+'::uuid'
        accounting=ro(self.worker,f"jsonb_build_object('rows',(SELECT count(*)FROM ids_import.source_row WHERE import_run_id={rid}),'other',(SELECT count(*)FROM ids_import.source_row WHERE import_run_id={rid} AND disposition IS DISTINCT FROM 'loaded'),'runs',(SELECT count(*)FROM ids_import.import_run))")
        require(accounting['rows']==len(covered) and accounting['other']==0,'RECONCILIATION_REQUIRED')
        if not metas:
            require(accounting['runs']==0 and all(t['rows']==0 for t in table_counts(self.worker)),'RECONCILIATION_REQUIRED')
        tabs=self.manifest.value['trial_tabs']if trial else self.manifest.value['load_order']
        groups=self.chunks(covered,tabs);compiled=[]
        for group in groups:
            exists=' OR '.join(f'EXISTS(SELECT 1 FROM {L.ident(schema)}.{L.ident(t)})'for schema,names in (('ids',L.INVENTORY_DATA_TABLES),('ids_import',L.INVENTORY_IMPORT_TABLES))for t in names)
            body=f"IF NOT EXISTS(SELECT 1 FROM ids_import.import_run WHERE import_run_id={rid}) THEN IF {exists} THEN RAISE EXCEPTION 'FIRST_RUN_NOT_EMPTY'; END IF; END IF;"+self.loader._run_guard(create=True);receipts=[]
            for chunk in group:
                text,receipt=self.loader._chunk_sql(chunk);body+=text;receipts.append(receipt)
            expected={'run':self.run_id,'chunks':receipts};sql=L.transaction(body,expected)
            require(len(L.canonical({'query':sql}).encode())<=L.MAX_BYTES,'PAYLOAD_TOO_LARGE')
            from pglast import parse_sql
            parse_sql(sql);compiled.append((sql,expected,group))
        pause=self.manifest.value['pause_seconds']if pause is None else pause
        health_every=health_every or self.manifest.value['health_every_batches']; require(pause>=0 and health_every>0)
        require(__import__('math').isfinite(pause) and pause<=3600)
        reports=[];began=time.monotonic();finished=set()
        save(self.directory/'plan.json',{'groups':[[{'tab':c[0]['tab'],'sheet':c[0]['sheet'],'first':c[0]['row'],'last':c[-1]['row']}for c in g]for _,_,g in compiled]})
        for index,(sql,expected,group)in enumerate(compiled,1):
            context=group
            try: self.loader._send(sql,expected)
            except Exception as exc:
                self.loader.stopped=True
                for chunk in context:self.failure(L.SOURCE,f"{chunk[0]['tab']}!{chunk[0]['row']}:{chunk[-1]['row']}",exc.code if isinstance(exc,L.StopLoad)else 'WRITE_FAILED_OR_UNCERTAIN')
                raise
            for chunk in group:
                covered.update((r['tab'],r['row'])for r in chunk)
            for tab in tabs:
                if tab not in finished and all((tab,n)in covered for n in range(self.manifest.tabs[tab]['first_data_row'],self.manifest.tabs[tab]['last_data_row']+1)):
                    report=self.tab_accounting(tab,self.manifest.tabs[tab]['records']);reports.append(report);finished.add(tab)
                    print(L.canonical({'tab_reconciled':report}),flush=True)
            save(self.directory/'progress.json',{'batches':index,'covered_rows':len(covered),'seconds':round(time.monotonic()-began,3)})
            if index%health_every==0:
                require(ro(self.worker,'1')==1,'RECEIPT_INVALID');print(L.canonical({'health_after_batch':index,'healthy':True}),flush=True)
            if index<len(compiled):time.sleep(pause)
        if not trial:
            reports=[self.tab_accounting(t,self.manifest.tabs[t]['records'])for t in self.manifest.value['load_order']]
            require(sum(v['loaded']for v in reports)==len(self.rows))
            count=len(metas)+sum(len(g)for _,_,g in compiled);rid=L.literal(self.run_id)+'::uuid'
            body=self.loader._run_guard()+f"IF (SELECT count(*)FROM ids_import.source_row WHERE import_run_id={rid})<>{len(self.rows)} OR EXISTS(SELECT 1 FROM ids_import.source_row WHERE import_run_id={rid}AND disposition IS DISTINCT FROM 'loaded') OR (SELECT count(*)FROM ids_import.import_chunk WHERE import_run_id={rid}AND status='committed')<>{count} OR EXISTS(SELECT 1 FROM ids_import.import_chunk WHERE import_run_id={rid}AND status<>'committed') THEN RAISE EXCEPTION 'RECONCILIATION_FAILED'; END IF; UPDATE ids_import.import_run SET status='completed',finished_at=coalesce(finished_at,now())WHERE import_run_id={rid};"
            body=body.replace('::uuidAND','::uuid AND')
            receipt={'run':self.run_id,'complete':True,'rows':len(self.rows)};self.loader._send(L.transaction(body,receipt),receipt)
        result={'run':self.run_id,'trial':trial,'loaded':sum(v['loaded']for v in reports),'quarantined':0,'tabs':reports,'seconds':round(time.monotonic()-began,3)}
        save(self.directory/'result.json',result);return result


def clear_rows(manifest, worker, approve_delete=False):
    require(approve_delete,'NOT_APPROVED')
    attempt=WORK/'clear-attempt.json'
    require(not attempt.exists()or read_private(attempt).get('state')!='in_flight','RECONCILIATION_REQUIRED')
    before=verify_security(worker);counts=before['tables']
    require(ro(worker,"NOT EXISTS(SELECT 1 FROM pg_constraint f JOIN pg_class child ON child.oid=f.conrelid JOIN pg_namespace cn ON cn.oid=child.relnamespace JOIN pg_class parent ON parent.oid=f.confrelid JOIN pg_namespace pn ON pn.oid=parent.relnamespace WHERE f.contype='f'AND pn.nspname IN('ids','ids_import')AND cn.nspname NOT IN('ids','ids_import'))"),'PREFLIGHT_FAILED')
    # Reject untrusted/in-flight local attempts; all known journals share work/.
    for path in (WORK/'ids').glob('*/*.started'):
        journal=L.Journal(path.with_suffix('.json'))
        with journal.exclusive():require(journal.read()['state']=='ready','RECONCILIATION_REQUIRED')
    order=[('ids',L.TABLES[t]['name'])for t in reversed(manifest.value['load_order'])]
    order += [('ids_import',t)for t in ('validation_issue','source_row','import_chunk','import_run')]
    require(len(order)==28)
    body=''
    for item in counts:
        table=L.ident(item['schema'])+'.'+L.ident(item['table'])
        body+=f"IF (SELECT count(*)FROM {table})<>{item['rows']} THEN RAISE EXCEPTION 'COUNTS_CHANGED'; END IF;\n"
    body+='\n'.join(f'DELETE FROM {L.ident(s)}.{L.ident(t)};'for s,t in order)
    for schema,table in order:body+=f"IF EXISTS(SELECT 1 FROM {L.ident(schema)}.{L.ident(table)}) THEN RAISE EXCEPTION 'ROWS_REMAIN'; END IF;\n"
    lock='LOCK TABLE '+','.join(L.ident(s)+'.'+L.ident(t)for s,t in order)+' IN ACCESS EXCLUSIVE MODE;'
    receipt={'rows_cleared':sum(v['rows']for v in counts),'tables':28}
    sql=L.transaction(lock+body,receipt)
    save(WORK/'clear-attempt.json',{'state':'in_flight','before':before})
    require(worker.query(sql)==[{'receipt':receipt}],'RECEIPT_INVALID')
    after=verify_security(worker)
    require(all(v['rows']==0 for v in after['tables']) and after['catalog']==before['catalog'],'RECONCILIATION_REQUIRED')
    archive=private_path(WORK/'archive'/str(uuid.uuid4()));archive.mkdir(parents=True,mode=0o700)
    if (WORK/'ids').exists():os.replace(WORK/'ids',archive/'ids')
    save(WORK/'clear-attempt.json',{'state':'verified_empty','archived_state':str(Path('work')/archive.relative_to(WORK))})
    return {'cleared':True,'tables':28,'rows':0,'archived_state':str(Path('work')/archive.relative_to(WORK))}


def parser():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('command',choices=('capture','dry-run','init','trial','full','reconcile','resume','verify','clear','clear-reconcile'))
    p.add_argument('--manifest',type=Path)
    p.add_argument('--snapshot',type=Path);p.add_argument('--repeat-snapshot',type=Path)
    p.add_argument('--output',type=Path);p.add_argument('--run-id')
    p.add_argument('--execute',action='store_true')
    p.add_argument('--inventory-only',action='store_true')
    p.add_argument('--accept-reconciliation',action='store_true');p.add_argument('--rebuild-state',action='store_true')
    p.add_argument('--approve-delete-rows',action='store_true')
    p.add_argument('--batch-rows',type=int);p.add_argument('--pause-seconds',type=float)
    p.add_argument('--health-every',type=int);p.add_argument('--read-retries',type=int,choices=(0,1,2),default=0)
    return p


def main(argv=None):
    args=parser().parse_args(argv)
    worker=None
    try:
        # Gates precede reading private files, credentials, Worker creation/network.
        if args.command in WRITE_COMMANDS:require(args.execute and args.manifest is not None,'NOT_APPROVED')
        require(args.manifest is not None,'NOT_APPROVED');m=Manifest(args.manifest)
        if args.command=='capture':require(args.output is not None);result=capture(m,args.output)
        elif args.command=='dry-run':
            result=dict(m.summary(),database_writes=0,network_requests=0,source_validated=False)
            if args.snapshot or args.repeat_snapshot:
                rows=snapshots(args.snapshot,args.repeat_snapshot,m);result.update(source_validated=True,transformed=len(rows),warnings=sum(len(r['warnings'])for r in rows))
        else:
            require(args.run_id is not None or args.command in ('verify','clear','clear-reconcile'))
            run_id=str(uuid.UUID(args.run_id))if args.run_id else str(uuid.uuid4())
            directory=private_path(WORK/'ids'/run_id)
            with operator_lock():
                worker=Worker(m,directory,args.read_retries)
                if args.command=='verify':
                    result=verify_security(worker)
                    if not args.inventory_only:
                        require(args.run_id is not None,'NOT_APPROVED');result['workbook']=verify_loaded(m,worker,run_id)
                    save(directory/'verification.json',result);result={k:v for k,v in result.items()if k!='catalog'}
                elif args.command=='clear':result=clear_rows(m,worker,args.approve_delete_rows)
                elif args.command=='clear-reconcile':
                    pending=read_private(WORK/'clear-attempt.json');require(pending['state']=='in_flight','RECONCILIATION_REQUIRED')
                    current=verify_security(worker);require(current['catalog']==pending['before']['catalog'],'RECONCILIATION_REQUIRED')
                    empty=all(t['rows']==0 for t in current['tables'])
                    unchanged=current['tables']==pending['before']['tables']
                    require(empty or unchanged,'RECONCILIATION_REQUIRED')
                    outcome='committed'if empty else 'not_committed'
                    if args.accept_reconciliation:
                        if empty and (WORK/'ids').exists():
                            archive=WORK/'archive'/str(uuid.uuid4());archive.mkdir(mode=0o700,parents=True);os.replace(WORK/'ids',archive/'ids')
                        save(WORK/'clear-attempt.json',{'state':'reconciled','outcome':outcome})
                    result={'clear_outcome':outcome,'accepted':args.accept_reconciliation}

                else:
                    rows=snapshots(args.snapshot,args.repeat_snapshot,m)
                    run=Run(m,run_id,rows,worker,args.batch_rows or (m.value['resume_batch_rows']if args.command=='resume'else m.value['batch_rows']))
                    if args.command=='init':
                        require(not run.control.exists(),'RECONCILIATION_REQUIRED');result=run.initial_reconcile()
                    else:
                        with run.journal.exclusive():
                            if args.command=='reconcile':result=run.reconcile_pending(args.accept_reconciliation,args.rebuild_state)
                            else:result=run.execute(args.command=='trial',args.pause_seconds,args.health_every)
        print(L.canonical(result));return 0
    except Exception as exc:
        code=exc.code if isinstance(exc,L.StopLoad)else 'SCOPE_MISMATCH'
        result={'stopped':code,'no_automatic_write_retry':True}
        if isinstance(exc,CaptureRefusal):result['message']=exc.public_message
        if worker is not None:result.update(phase=worker.phase,last_response=worker.last_response)
        print(L.canonical(result));return 2

if __name__=='__main__':raise SystemExit(main())
