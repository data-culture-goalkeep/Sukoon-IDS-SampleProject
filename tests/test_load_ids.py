"""Offline tests only: fake worker, synthetic cells, PostgreSQL parser; no database."""
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import subprocess
from importlib.metadata import version
import unittest
from unittest.mock import patch
import uuid
from pglast import parse_sql, parse_plpgsql, ast, enums
from pglast.visitors import Visitor
if version('pglast') != '7.22':
    raise RuntimeError('Tests require pglast==7.22; install requirements-loader-test.txt')
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import load_ids as L

RUN = '11111111-1111-4111-8111-111111111111'

def fixture(tab='5.Monthly Target', row=3):
    values = {}
    for f in L.TABLES[tab]['fields']:
        if f['nullable']: continue
        if f['type'] in ('date','timestamptz'): value={'numberValue':44711}
        elif f['type'] in ('integer','numeric'): value={'numberValue':1}
        elif f['type']=='boolean': value={'boolValue':True}
        else: value={'stringValue':'fixture_'+f['name']+str(row)}
        values[f['name']]={'userEnteredValue':value}
    cells = [values.get(h.split(' (')[0], {}) for h in L.TABS[tab]['source_headers']]
    return L.transform(tab,row,cells,L.TABS[tab]['source_headers'])

def approval(rows, authorized=True):
    ranges = tuple((c[0]['tab'],c[0]['row'],c[-1]['row']) for c in L.chunks_for(rows))
    return L.Approval(L.PROJECT,L.SOURCE,RUN,L.sha(rows),ranges,authorized)

class FakeWorker:
    def __init__(self, mode='ok'): self.sql=[];self.mode=mode;self.preflights=0
    def preflight(self): self.preflights+=1
    def query(self, sql):
        self.sql.append(sql)
        if self.mode=='timeout': raise TimeoutError('PRIVATE DATABASE DETAIL')
        if self.mode=='bad_receipt': return []
        # Last SELECT contains the exact safely quoted JSON receipt.
        last=sql.rsplit('\nSELECT ',1)[1]
        receipt=json.loads(last.split("'::jsonb",1)[0][1:].replace("''", "'"))
        if 'inventory_check' in receipt:receipt['inventory']={'tables':28,'rows':0,'own_run':False}
        if 'reconciled' in receipt:receipt['mode']='first'
        return [{'receipt':receipt}]
    def read_query(self,sql):return self.query(sql)

class LoadTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.journal=L.Journal(Path(self.temp.name)/'state'/(RUN+'.json'))
        self.failures=[];self.worker=FakeWorker();self.rows=[fixture()]
        with self.journal.exclusive(): self.journal.reconciled(approval(self.rows),'first')
    def read_state(self):
        with self.journal.exclusive():return self.journal.read()
    def loader(self, a=None, worker=None):
        return L.Loader(a or approval(self.rows),worker or self.worker,lambda *x:(self.failures.append(x) or True),self.journal)
    def test_month_text_conversion_preserves_raw_lineage(self):
        original=fixture();headers=L.TABS['5.Monthly Target']['source_headers']
        cells=[{'userEnteredValue':v} for v in original['raw']]
        index=next(i for i,h in enumerate(headers) if h.split(' (')[0]=='month')
        for month in ('2024-02','2026-12','2000-01'):
            cells[index]={'userEnteredValue':{'stringValue':month}}
            row=L.transform('5.Monthly Target',3,cells,headers)
            self.assertEqual(row['record']['month'],month+'-01')
            self.assertEqual(row['raw'][index],{'stringValue':month})
        for month in ('2026-00','2026-13','2026-1','2026-01-01',' 2026-01','0000-01'):
            cells[index]={'userEnteredValue':{'stringValue':month}}
            with self.assertRaises(L.StopLoad):L.transform('5.Monthly Target',3,cells,headers)
        for value in ({'stringValue':'2026-11','formulaValue':'=TODAY()'},
                      {'stringValue':'2026-11','numberValue':1}, {}):
            cells[index]={'userEnteredValue':value}
            with self.assertRaises(L.StopLoad):L.transform('5.Monthly Target',3,cells,headers)

    def test_default_approval_denies(self):
        with self.assertRaisesRegex(L.StopLoad,'NOT_APPROVED'):self.loader(approval(self.rows,False)).load(self.rows,self.rows)
        self.assertFalse(self.worker.sql)
    def test_project_denies(self):
        a=approval(self.rows);a=L.Approval('other',a.source,a.run_id,a.snapshot_hash,a.ranges,True)
        with self.assertRaises(L.StopLoad):self.loader(a).load(self.rows,self.rows)
        self.assertFalse(self.worker.sql)
    def test_source_denies(self):
        a=approval(self.rows);a=L.Approval(a.project,'backup',a.run_id,a.snapshot_hash,a.ranges,True)
        with self.assertRaises(L.StopLoad):self.loader(a).load(self.rows,self.rows)
    def test_changed_snapshot_denies(self):
        changed=copy.deepcopy(self.rows);changed[0]['record']['target_id']='changed'
        with self.assertRaises(L.StopLoad):self.loader().load(self.rows,changed)
        self.assertFalse(self.worker.sql)
    def test_forged_transform_denies(self):
        rows=copy.deepcopy(self.rows);rows[0]['record']['target_id']='changed'
        with self.assertRaises(L.StopLoad):approval(rows).validate(rows)
    def test_duplicate_rows_denies(self):
        with self.assertRaises(L.StopLoad):approval(self.rows*2).validate(self.rows*2)
    def test_outside_range_denies(self):
        a=approval(self.rows);a=L.Approval(a.project,a.source,a.run_id,a.snapshot_hash,(('5.Monthly Target',4,4),),True)
        with self.assertRaises(L.StopLoad):a.validate(self.rows)
    def test_incomplete_bootstrap_denies(self):
        rows=[fixture('23.Staff')]
        with self.assertRaisesRegex(L.StopLoad,'SNAPSHOT_INCOMPLETE'):approval(rows).validate(rows)
    def test_atomic_and_verified(self):
        receipt=self.loader().load(self.rows,self.rows)
        self.assertTrue(receipt['complete']);self.assertEqual(len(self.worker.sql),2)
        sql=self.worker.sql[0]
        for fragment in ['BEGIN ISOLATION LEVEL READ COMMITTED','pg_advisory_xact_lock','SET CONSTRAINTS ALL DEFERRED','INSERT INTO ids_import.source_row','INSERT INTO ids."monthly_target"','UPDATE ids_import.import_chunk',"status='committed'",'RECORD_CONFLICT','LINEAGE_CONFLICT','WARNING_CONFLICT','SET CONSTRAINTS ALL IMMEDIATE','COMMIT;']:
            self.assertIn(fragment,sql)
        self.assertNotIn('UPDATE ids."monthly_target"',sql)
        self.assertNotIn('ON CONFLICT DO UPDATE',sql)
        self.assertEqual(self.read_state()['state'],'ready')
        self.assertEqual(os.stat(self.journal.path).st_mode&0o777,0o600)
    def test_replay_sql_same_ids_and_hash(self):
        a=self.loader()._chunk_sql(self.rows);b=self.loader()._chunk_sql(copy.deepcopy(self.rows))
        self.assertEqual(a,b)
        self.assertIn('CHUNK_CONFLICT',a[0]);self.assertIn('ROW_COUNT_CONFLICT',a[0])
    def test_failed_write_stops_and_survives_restart(self):
        worker=FakeWorker('timeout');loader=self.loader(worker=worker)
        with self.assertRaisesRegex(L.StopLoad,'WRITE_FAILED_OR_UNCERTAIN'):loader.load(self.rows,self.rows)
        self.assertEqual(len(worker.sql),1)
        self.assertEqual(self.read_state()['state'],'in_flight')
        with self.assertRaises(L.StopLoad):self.loader().load(self.rows,self.rows)
        self.assertFalse(self.worker.sql)
        self.assertNotIn('PRIVATE',json.dumps(self.failures))
    def test_bad_receipt_stops(self):
        worker=FakeWorker('bad_receipt')
        with self.assertRaisesRegex(L.StopLoad,'RECEIPT_INVALID'):self.loader(worker=worker).load(self.rows,self.rows)
        self.assertEqual(len(worker.sql),1)
    def test_failure_sink_failure_stops(self):
        def sink(*args):raise OSError('private')
        loader=L.Loader(approval(self.rows),FakeWorker('timeout'),sink,self.journal)
        with self.assertRaisesRegex(L.StopLoad,'FAILURE_LOG_FAILED'):loader.load(self.rows,self.rows)
    def test_chunk_limit_and_gaps(self):
        rows=[fixture(row=n) for n in range(3,105)]+[fixture(row=110)]
        self.assertEqual([len(c)for c in L.chunks_for(rows)],[100,2,1])
    def test_blanks_stay_null(self):self.assertIsNone(L.parse_cell({}, {'type':'numeric','nullable':True}))
    def test_required_blank_denies(self):
        with self.assertRaises(L.StopLoad):L.parse_cell({}, {'type':'text','nullable':False})
    def test_stale_format_boolean(self):
        cell={'userEnteredValue':{'boolValue':True},'userEnteredFormat':{'numberFormat':{'type':'DATE'}}}
        self.assertIs(L.parse_cell(cell,{'type':'boolean','nullable':True}),True)
    def test_numeric_text(self):
        self.assertEqual(L.parse_cell({'userEnteredValue':{'numberValue':10}}, {'type':'text','nullable':True}),'10')
    def test_source_whitespace_preserved(self):
        self.assertEqual(L.parse_cell({'userEnteredValue':{'stringValue':'  x  '}}, {'type':'text','nullable':True}),'  x  ')
    def test_formula_denies(self):
        with self.assertRaisesRegex(L.StopLoad,'FORMULA_FOUND'):L.parse_cell({'userEnteredValue':{'formulaValue':'=1'}},{'type':'integer','nullable':True})
    def test_strict_time_text(self):
        self.assertEqual(L.parse_cell({'userEnteredValue':{'stringValue':'09:30'}},{'type':'time','nullable':True}),'09:30:00')
        for text in ['25:00','tomorrow','9:30']:
            with self.assertRaises(L.StopLoad):L.parse_cell({'userEnteredValue':{'stringValue':text}},{'type':'time','nullable':True})
    def test_timezone(self):
        self.assertEqual(L.parse_cell({'userEnteredValue':{'numberValue':44711}},{'type':'timestamptz','nullable':True}),'2022-05-30T00:00:00+05:30')
    def test_nonfinite_denies(self):
        for v in ['NaN','Infinity',True]:
            with self.assertRaises(L.StopLoad):L.parse_cell({'userEnteredValue':{'stringValue':v}},{'type':'numeric','nullable':True})
    def test_header_change_denies(self):
        with self.assertRaisesRegex(L.StopLoad,'HEADER_CHANGED'):L.transform('5.Monthly Target',3,[],['changed'])
    def test_sql_literal_and_dollar_delimiter(self):
        self.assertEqual(L.literal("x'); SELECT 'y"),"'x''); SELECT ''y'")
        sql=L.block("PERFORM '$ids_loader$';")
        self.assertNotEqual(sql.splitlines()[0],'DO $ids_loader$')
        with self.assertRaises(L.StopLoad):L.literal('\x00')
    def test_worker_scope_guard_without_network(self):
        with patch.dict(os.environ,{'SUPABASE_PROJECT_REF':'other'}):
            with self.assertRaises(L.StopLoad):L.Worker(L.PROJECT)
    def test_worker_no_redirect(self):
        with patch.dict(os.environ,{'SUPABASE_PROJECT_REF':L.PROJECT,'SUPABASE_ACCESS_TOKEN':'synthetic'}):
            w=L.Worker(L.PROJECT)
            handlers=[h for h in w.opener.handlers if hasattr(h,'redirect_request')]
            self.assertEqual(len(handlers),1);self.assertIsNone(handlers[0].redirect_request(None,None,None,None,None,None))
    def test_payload_cap_before_write(self):
        with patch.object(L,'MAX_BYTES',100):
            with self.assertRaisesRegex(L.StopLoad,'PAYLOAD_TOO_LARGE'):self.loader().load(self.rows,self.rows)
        self.assertFalse(self.worker.sql)
    def test_oversized_chunks_split_before_any_write(self):
        rows=[fixture(row=n) for n in range(3,103)]
        worker=FakeWorker()
        with self.journal.exclusive():self.journal.reconciled(approval(rows),'first')
        with patch.object(L,'MAX_BYTES',25000):
            L.Loader(approval(rows),worker,lambda *x:True,self.journal).load(rows,rows)
        self.assertGreater(len(worker.sql),2)
        self.assertTrue(all(len(L.canonical({'query':sql}).encode())<=25000 for sql in worker.sql))
    def test_preflight_rejects_exposure_and_bad_catalog(self):
        for schemas,catalog in [('public,ids',[{'safe':True}]),('public',[{'safe':False}])]:
            with patch.dict(os.environ,{'SUPABASE_PROJECT_REF':L.PROJECT,'SUPABASE_ACCESS_TOKEN':'synthetic'}):
                worker=L.Worker(L.PROJECT)
            project={'id':L.PROJECT,'name':'Sukoon-IDS-SampleProject','status':'ACTIVE_HEALTHY'}
            with patch.object(worker,'request',side_effect=[project,{'db_schema':schemas},catalog]):
                with self.assertRaisesRegex(L.StopLoad,'PREFLIGHT_FAILED'):worker.preflight()
    def test_full_bootstrap_order(self):
        rows=[]
        for tab in ('24.Reference List','23.Staff'):
            rows.extend(fixture(tab,row=n) for n in range(3,L.TABS[tab]['last_data_row']+1))
        with self.journal.exclusive():self.journal.reconciled(approval(rows),'first')
        worker=FakeWorker();L.Loader(approval(rows),worker,lambda *x:None,self.journal).load(rows,rows)
        self.assertEqual(len(worker.sql),2)
        sql=worker.sql[0]
        self.assertLess(sql.rindex('INSERT INTO ids."reference_list"'),sql.index('INSERT INTO ids."staff"'))
        self.assertEqual(sql.count('COMMIT;'),1)
    def test_failure_sink_declined_stops(self):
        loader=L.Loader(approval(self.rows),FakeWorker('timeout'),lambda *x:False,self.journal)
        with self.assertRaisesRegex(L.StopLoad,'FAILURE_LOG_FAILED'):loader.load(self.rows,self.rows)
    def test_warning_manifest_counts(self):
        self.assertEqual(len(L.AUDIT['approved_warning_rows']['weekly_check_first_held_rule']['rows']),471)
        self.assertIn('non_delivered_with_actual_date',L.warnings_for('16.Batch Schedule',31))
    def test_missing_state_requires_explicit_readonly_reconciliation(self):
        self.journal.path.unlink()
        with self.assertRaisesRegex(L.StopLoad,'RECONCILIATION_REQUIRED'):self.loader().load(self.rows,self.rows)
        self.assertFalse(self.worker.sql)
        new=self.loader()
        with self.assertRaisesRegex(L.StopLoad,'NOT_APPROVED'):new.reconcile(self.rows,self.rows)
        new.reconcile(self.rows,self.rows,authorized=True)
        self.assertTrue(all('READ ONLY' in sql for sql in self.worker.sql))
        self.assertEqual(len(self.worker.sql),1)
        for sql in self.worker.sql:
            statements=parse_sql(sql)
            self.assertEqual(statements[0].stmt.kind,enums.TransactionStmtKind.TRANS_STMT_BEGIN)
            self.assertTrue(any(o.defname=='transaction_read_only' and isinstance(o.arg,ast.A_Const) and o.arg.val.ival==1 for o in statements[0].stmt.options))
            self.assertEqual(statements[-1].stmt.kind,enums.TransactionStmtKind.TRANS_STMT_COMMIT)
            self.assertTrue(all(isinstance(x.stmt,(ast.SelectStmt,ast.VariableSetStmt)) for x in statements[1:-1]))
            calls=[];relations=[]
            class Inspect(Visitor):
                def visit_FuncCall(self,ancestors,node):calls.append(tuple(x.sval for x in node.funcname))
                def visit_RangeVar(self,ancestors,node):relations.append((node.schemaname,node.relname))
                def visit_SelectStmt(self,ancestors,node):
                    if node.intoClause or node.lockingClause:raise AssertionError('Side-effecting SELECT')
            Inspect()(statements)
            self.assertTrue(calls)
            self.assertTrue(all(c in {('pg_catalog','count'),('pg_catalog','jsonb_build_object')} for c in calls))
            actual={name for schema,name in relations if schema=='ids'}
            expected={t['name'] for t in L.TABLES.values()}
            self.assertEqual(len(expected),24)
            self.assertEqual(set(L.TABLES),set(L.TABS))
            self.assertEqual(actual,expected)
            self.assertEqual(actual,set(L.INVENTORY_DATA_TABLES))
            self.assertEqual({name for schema,name in relations if schema=='ids_import'},set(L.INVENTORY_IMPORT_TABLES))
            self.assertNotIn('pg_advisory',sql)
            self.assertNotIn('query_to_xml',sql)
        self.assertEqual(self.read_state()['mode'],'first')
        self.worker.sql.clear()
        new.load(self.rows,self.rows)
        self.assertTrue(any('INSERT INTO ids.' in sql for sql in self.worker.sql))
    def test_failed_inventory_cannot_unlock_writes(self):
        self.journal.path.unlink()
        worker=FakeWorker('bad_receipt');loader=self.loader(worker=worker)
        with self.assertRaises(L.StopLoad):loader.reconcile(self.rows,self.rows,authorized=True)
        self.assertFalse(self.journal.path.exists())
        before=len(worker.sql)
        with self.assertRaisesRegex(L.StopLoad,'RECONCILIATION_REQUIRED'):self.loader(worker=worker).load(self.rows,self.rows)
        self.assertEqual(len(worker.sql),before)
        self.assertTrue(all('READ ONLY' in sql for sql in worker.sql))

    def test_reconcile_known_absence_preserves_evidence_and_refuses_partial(self):
        a=approval(self.rows);loader=self.loader();chunk=self.rows
        _,receipt=loader._chunk_sql(chunk)
        with self.journal.exclusive():
            self.journal.begin(a,'synthetic_attempt',{'run':a.run_id,'chunks':[receipt]})
        evidence={'project':L.PROJECT,'run':a.run_id,'sheet':chunk[0]['sheet'],'first_row':chunk[0]['row'],'last_row':chunk[-1]['row'],'chunk':receipt['chunk'],'counts':{'checkpoint_rows':0,'lineage_rows':0},'metadata':{'http_status':201,'error':None},'database_writes':0}
        partial=copy.deepcopy(evidence);partial['counts']['lineage_rows']=1
        with self.assertRaises(L.StopLoad):loader.reconcile(self.rows,self.rows,authorized=True,absence_evidence=partial)
        self.assertEqual(self.read_state()['state'],'in_flight')
        wrong=copy.deepcopy(evidence);wrong['run']='different'
        with self.assertRaises(L.StopLoad):loader.reconcile(self.rows,self.rows,authorized=True,absence_evidence=wrong)
        result=loader.reconcile(self.rows,self.rows,authorized=True,absence_evidence=evidence)
        self.assertEqual(result['outcome'],'not_committed')
        state=self.read_state();self.assertEqual(state['state'],'ready');self.assertEqual(state['mode'],'resume')
        self.assertEqual(state['reconciliation_evidence']['lineage_rows'],0)
        self.assertEqual(state['reconciliation_evidence']['outcome'],'not_committed')
        self.assertFalse(self.worker.sql)

    def test_total_state_loss_cannot_auto_initialize(self):
        self.journal.path.unlink();self.journal.marker.unlink()
        with self.assertRaisesRegex(L.StopLoad,'RECONCILIATION_REQUIRED'):self.loader().load(self.rows,self.rows)
        self.assertFalse(self.worker.sql)
    def test_corrupt_and_mismatched_generation_stop(self):
        self.journal.path.write_text('invalid JSON')
        with self.assertRaisesRegex(L.StopLoad,'RECONCILIATION_REQUIRED'):self.loader().load(self.rows,self.rows)
        self.assertFalse(self.worker.sql)
        with self.journal.exclusive():self.journal.reconciled(approval(self.rows),'first')
        self.journal.marker.write_text('{}')
        with self.assertRaisesRegex(L.StopLoad,'RECONCILIATION_REQUIRED'):self.loader().load(self.rows,self.rows)
    def test_wrong_attempt_cannot_clear_inflight(self):
        with self.journal.exclusive():
            self.journal.begin(approval(self.rows),'owner',{'synthetic':True})
            with self.assertRaisesRegex(L.StopLoad,'ATTEMPT_CONFLICT'):self.journal.complete('other')
            self.assertEqual(self.journal.read()['attempt'],'owner')
            self.assertEqual(self.journal.read()['state'],'in_flight')
    def test_mutation_during_preflight_cannot_change_compiled_snapshot(self):
        original_id=self.rows[0]['record']['target_id']
        def mutate():
            self.rows[0]['record']['target_id']='SYNTHETIC_UNAPPROVED_MUTATION'
            self.rows[0]['raw'][0]={'stringValue':'SYNTHETIC_UNAPPROVED_MUTATION'}
        self.worker.preflight=mutate
        self.loader().load(self.rows,copy.deepcopy(self.rows))
        self.assertNotIn('SYNTHETIC_UNAPPROVED_MUTATION',self.worker.sql[0])
        self.assertIn(original_id,self.worker.sql[0])
    def test_private_snapshot_is_recursively_immutable(self):
        frozen=L.private_snapshot(self.rows)
        with self.assertRaises(TypeError):frozen[0]['record']['target_id']='changed'
        with self.assertRaises(AttributeError):frozen.append({})
    def test_run_lock_precedes_journal_check_and_preflight(self):
        with self.journal.exclusive():
            other=L.Journal(self.journal.path)
            loader=L.Loader(approval(self.rows),self.worker,lambda *x:True,other)
            with self.assertRaisesRegex(L.StopLoad,'RUN_LOCKED'):loader.load(self.rows,self.rows)
        self.assertEqual(self.worker.preflights,0);self.assertFalse(self.worker.sql)
    def test_repository_state_path_is_rejected(self):
        with self.assertRaisesRegex(L.StopLoad,'SCOPE_MISMATCH'):L.Journal(L.ROOT/(RUN+'.json'))
    def test_missing_parser_fails_instead_of_skipping(self):
        result=subprocess.run([sys.executable,'-I','-S',str(Path(__file__).resolve())],capture_output=True,text=True)
        self.assertNotEqual(result.returncode,0)
        self.assertIn('pglast',result.stderr)
    def test_run_lock_excludes_another_process(self):
        code="""import sys
sys.path.insert(0,sys.argv[1])
from load_ids import Journal,StopLoad
try:
 with Journal(sys.argv[2]).exclusive():print('UNEXPECTED_LOCK')
except StopLoad as error:print(error.code)
"""
        with self.journal.exclusive():
            result=subprocess.run([sys.executable,'-c',code,str(L.ROOT/'scripts'),str(self.journal.path)],capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0);self.assertEqual(result.stdout.strip(),'RUN_LOCKED')
    def test_postgres_parses_all_table_statements(self):
        for tab in L.TABLES:
            with patch.dict(L.TABS[tab],{'last_data_row':max(3,L.TABS[tab]['last_data_row'])}):
                row=fixture(tab)
            loader=self.loader()
            body,_=loader._chunk_sql([row])
            sql=L.transaction(loader._run_guard(create=True)+body,{'test':True})
            parse_sql(sql)
            parse_plpgsql(sql[sql.index('DO '):sql.index('\nSET CONSTRAINTS ALL IMMEDIATE;')])
    def test_postgres_parses_generated_sql(self):
        self.loader().load(self.rows,self.rows)
        for sql in self.worker.sql:
            parse_sql(sql)
            # parse_plpgsql accepts DO statements and checks PL/pgSQL structure.
            parse_plpgsql(sql[sql.index('DO '):sql.index('\nSET CONSTRAINTS ALL IMMEDIATE;')])

if __name__=='__main__':unittest.main()
