"""Operational-runner safety tests. All inputs invented; no hosted requests."""
import copy
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch,Mock
from test_load_ids import L,fixture,approval,FakeWorker,RUN
import ids_runner as R

class RunnerSafetyTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.work=Path(self.temp.name)/'work';self.work.mkdir()
        self.workpatch=patch.object(R,'WORK',self.work);self.workpatch.start();self.addCleanup(self.workpatch.stop)
        self.manifest=R.Manifest(R.ROOT/'docs/source-audit-v2.json')
    def test_write_flags_and_manifest_fail_before_worker_or_private_file_reads(self):
        with patch.object(R,'Worker')as worker,patch.object(R,'snapshots')as data,patch('sys.stdout',new=io.StringIO()):
            for command in R.WRITE_COMMANDS:
                self.assertEqual(R.main([command]),2)
                self.assertEqual(R.main([command,'--execute']),2)
                self.assertEqual(R.main([command,'--manifest',self.manifest.path]),2)
            worker.assert_not_called();data.assert_not_called()
    def test_model_source_metadata_matches_every_approved_manifest(self):
        registry=json.loads((R.ROOT/'config/approved-load-manifests.json').read_text())
        model=json.loads((R.ROOT/'docs/model-spec.json').read_text())
        tables={t['source_tab']:t for t in model['tables'] if t.get('source_tab')}
        for path in registry['manifests']:
            approved=R.Manifest(R.ROOT/path)
            with self.subTest(manifest=path):
                self.assertEqual(set(tables),set(approved.tabs))
            for tab,spec in approved.tabs.items():
                with self.subTest(manifest=path,tab=tab):
                    self.assertEqual(tables[tab]['source_count'],spec['records'])
                    self.assertEqual(tables[tab]['source_sheet_id'],spec['sheet_id'])

    def test_unknown_and_modified_manifest_refused(self):
        with self.assertRaises(L.StopLoad):R.Manifest(self.work/'unapproved.json')
        with patch.object(R.hashlib,'sha256',return_value=SimpleNamespace(hexdigest=lambda:'bad')):
            with self.assertRaisesRegex(L.StopLoad,'SOURCE_CHANGED'):R.Manifest(R.ROOT/self.manifest.path)
    def test_wrong_project_and_missing_secret_refused_before_transport(self):
        for env in ({'SUPABASE_PROJECT_REF':'invented_other','SUPABASE_ACCESS_TOKEN':'invented'}, {'SUPABASE_PROJECT_REF':L.PROJECT}):
            with patch.dict(os.environ,env,clear=True),patch.object(L.urllib.request,'build_opener')as opener:
                with self.assertRaises(L.StopLoad):R.Worker(self.manifest,self.work/'state')
                opener.assert_not_called()
    def test_manifest_only_dry_run_is_offline_and_explicitly_not_source_validated(self):
        with patch.object(R,'Worker')as worker,patch('sys.stdout',new=io.StringIO())as out:
            self.assertEqual(R.main(['dry-run','--manifest',self.manifest.path]),0)
        result=json.loads(out.getvalue());self.assertFalse(result['source_validated']);self.assertEqual(result['database_writes'],0);worker.assert_not_called()
    def test_private_paths_refuse_escape_and_symlink(self):
        with self.assertRaises(L.StopLoad):R.save(Path(self.temp.name)/'escape.json',{})
        target=Path(self.temp.name)/'outside';target.mkdir();(self.work/'link').symlink_to(target,target_is_directory=True)
        with self.assertRaises(L.StopLoad):R.save(self.work/'link'/'data.json',{})
        R.save(self.work/'private.json',{'invented':True})
        self.assertEqual((self.work/'private.json').stat().st_mode&0o777,0o600)
    def test_gitignore_covers_all_runner_state(self):
        for name in ('work/ids/invented/control.json','work/ids/invented/invented.started','work/ids/operator.lock','work/source.json','work/source.csv','work/source.xlsx','work/archive/old/state.json'):
            p=subprocess.run(['git','check-ignore','--quiet',name],cwd=R.ROOT)
            self.assertEqual(p.returncode,0)
    def test_operator_lock_excludes_second_attempt(self):
        with R.operator_lock():
            with self.assertRaisesRegex(L.StopLoad,'RUN_LOCKED'):
                with R.operator_lock():pass
    def test_workbook_capture_refuses_missing_google_secret_without_network(self):
        with patch.dict(os.environ,{},clear=True),patch.object(R.urllib.request,'build_opener')as opener:
            with self.assertRaises(L.StopLoad):R.capture(self.manifest,self.work/'capture.json')
            opener.assert_not_called()
    def capture_fixture(self, timezone='Asia/Kolkata', sentinel=None):
        tab='4.Partner Organisation';headers=L.TABS[tab]['source_headers']
        rows=[fixture(tab,3),fixture(tab,4)]
        values=[[next(iter(v.values()),None)for v in r['raw']]for r in rows]
        spec=dict(L.TABS[tab],records=2,last_data_row=4,raw_sha256=R.hashlib.sha256(L.canonical([tab,headers,[[i]+v for i,v in enumerate(values,3)]]).encode()).hexdigest())
        policy=SimpleNamespace(value={'source_file_id':L.SOURCE,'source_timezone':'Asia/Kolkata','documentation_tabs':[]},tabs={tab:spec})
        metadata={'spreadsheetId':L.SOURCE,'properties':{'timeZone':timezone},'sheets':[{'properties':{'title':tab,'sheetId':spec['sheet_id']}}]}
        requests=[]
        def open_response(request,timeout):
            requests.append(request.full_url)
            if '/values/' not in request.full_url:result=metadata
            else:
                a1=R.urllib.parse.unquote(request.full_url.split('/values/',1)[1].split('?',1)[0])
                if '!A5:' in a1:result={'values':sentinel or []}
                else:result={'values':[headers]+values}
            return io.BytesIO(json.dumps(result).encode())
        return policy,SimpleNamespace(open=Mock(side_effect=open_response)),requests

    def test_capture_refuses_wrong_or_missing_timezone_before_save_or_decode(self):
        for timezone in ('UTC','Asia/Calcutta',None):
            with self.subTest(timezone=timezone):
                policy,opener,requests=self.capture_fixture(timezone)
                with patch.dict(os.environ,{'GOOGLE_SHEETS_ACCESS_TOKEN':'invented_google_token'}),patch.object(R.urllib.request,'build_opener',return_value=opener),patch.object(R,'save')as save,patch.object(R,'decode_snapshot')as decode:
                    with self.assertRaisesRegex(R.CaptureRefusal,'timezone must equal manifest source_timezone'):
                        R.capture(policy,self.work/'capture.json')
                    save.assert_not_called();decode.assert_not_called()
                self.assertEqual(len(requests),1)

    def test_capture_refuses_populated_five_row_sentinel_and_names_tab(self):
        for value in ('invented_extra',0,False,' ','=1'):
            with self.subTest(value=value):
                policy,opener,requests=self.capture_fixture(sentinel=[[],[],[],[],[None]*(len(L.TABS['4.Partner Organisation']['source_headers'])-1)+[value]])
                with patch.dict(os.environ,{'GOOGLE_SHEETS_ACCESS_TOKEN':'invented_google_token'}),patch.object(R.urllib.request,'build_opener',return_value=opener),patch.object(R,'save')as save,patch.object(R,'decode_snapshot')as decode:
                    with self.assertRaisesRegex(R.CaptureRefusal,'Non-empty cell after last_data_row in tab 4.Partner Organisation'):
                        R.capture(policy,self.work/'capture.json')
                    save.assert_not_called();decode.assert_not_called()
                self.assertEqual(len(requests),2)
                self.assertIn('!A5:',R.urllib.parse.unquote(requests[-1]));self.assertIn('9?valueRenderOption=FORMULA',requests[-1])

    def test_capture_accepts_matching_timezone_and_blank_sentinel(self):
        policy,opener,requests=self.capture_fixture(sentinel=[[],[None,''],[],[],[]])
        with patch.dict(os.environ,{'GOOGLE_SHEETS_ACCESS_TOKEN':'invented_google_token'}),patch.object(R.urllib.request,'build_opener',return_value=opener):
            result=R.capture(policy,self.work/'capture.json')
        self.assertTrue(result['captured']);self.assertEqual(result['database_writes'],0)
        self.assertEqual(len(R.decode_snapshot(self.work/'capture.json',policy)),2)
        self.assertEqual(len(requests),3)
        self.assertEqual(len(R.read_private(self.work/'capture.json')['batches']),1)

    def test_capture_refusal_message_is_in_cli_output_without_source_values(self):
        with patch.object(R,'capture',side_effect=R.CaptureRefusal('Non-empty cell after last_data_row in tab invented_tab; capture refused.')),patch('sys.stdout',new=io.StringIO())as out:
            status=R.main(['capture','--manifest',self.manifest.path,'--output',str(self.work/'capture.json')])
        result=json.loads(out.getvalue());self.assertEqual(status,2)
        self.assertEqual(result['stopped'],'SOURCE_CHANGED');self.assertIn('invented_tab',result['message'])

    def run_fixture(self,worker=None):
        rows=[fixture('4.Partner Organisation',3),fixture('4.Partner Organisation',4)]
        return R.Run(self.manifest,RUN,L.private_snapshot(rows),worker or FakeWorker()),rows
    def test_runner_owns_immutable_snapshot(self):
        run,rows=self.run_fixture()
        before=L.sha(run.rows)
        rows[0]['record']['organisation_name']='invented_mutation'
        self.assertEqual(L.sha(run.rows),before)
        with self.assertRaises(TypeError):run.rows[0]['record']['organisation_name']='invented_change'

    def test_untrusted_or_missing_run_state_cannot_write(self):
        run,rows=self.run_fixture();run.worker.preflight=Mock()
        with run.journal.exclusive():
            with self.assertRaisesRegex(L.StopLoad,'RECONCILIATION_REQUIRED'):run.execute()
        self.assertFalse(run.worker.sql)
    def test_failure_queue_contains_only_coordinates_and_allowlisted_code(self):
        run,rows=self.run_fixture();run.failure(L.SOURCE,'invented-tab!3:4','WRITE_FAILED_OR_UNCERTAIN')
        queue=R.read_private(run.directory/'failure-log.json')
        self.assertEqual(set(queue[0]),{'source_file','row_reference','reason'})
        with self.assertRaises(L.StopLoad):run.failure(L.SOURCE,'invented','PRIVATE ERROR BODY')
    def test_clear_requires_extra_delete_approval_without_any_requests(self):
        worker=Mock()
        with self.assertRaisesRegex(L.StopLoad,'NOT_APPROVED'):R.clear_rows(self.manifest,worker,False)
        worker.assert_not_called();self.assertEqual(worker.method_calls,[])
    def test_uncertain_clear_cannot_be_retried(self):
        R.save(self.work/'clear-attempt.json',{'state':'in_flight'})
        worker=Mock()
        with self.assertRaisesRegex(L.StopLoad,'RECONCILIATION_REQUIRED'):R.clear_rows(self.manifest,worker,True)
        self.assertEqual(worker.method_calls,[])

    def test_changed_snapshot_and_formulas_stop_offline(self):
        # Minimal invented raw capture; no workbook values in test fixtures.
        t=self.manifest.value['tabs'][0];raw={'source_file_id':L.SOURCE,'metadata':{'sheets':[]},'batches':[]}
        R.save(self.work/'bad.json',raw)
        with self.assertRaises(L.StopLoad):R.decode_snapshot(self.work/'bad.json',self.manifest)
    def test_valid_snapshot_decodes_and_changed_values_or_formula_are_refused(self):
        tab='4.Partner Organisation';headers=L.TABS[tab]['source_headers'];rows=[fixture(tab,3),fixture(tab,4)]
        rawrows=[[next(iter(v.values()),None)for v in r['raw']]for r in rows]
        raw={'source_file_id':L.SOURCE,'metadata':{'sheets':[{'properties':{'title':tab,'sheetId':L.TABS[tab]['sheet_id']}}]},'batches':[{'tab':tab,'first':2,'data':[headers]+rawrows}]}
        spec=dict(L.TABS[tab],records=2,last_data_row=4,raw_sha256=R.hashlib.sha256(L.canonical([tab,headers,[[i]+v for i,v in enumerate(rawrows,3)]]).encode()).hexdigest())
        policy=SimpleNamespace(value={'source_file_id':L.SOURCE,'documentation_tabs':[]},tabs={tab:spec})
        path=self.work/'source.json';R.save(path,raw)
        self.assertEqual(len(R.decode_snapshot(path,policy)),2)
        raw['batches'][0]['data'][1][0]='invented_changed';R.save(path,raw)
        with self.assertRaisesRegex(L.StopLoad,'SOURCE_CHANGED'):R.decode_snapshot(path,policy)
        raw['batches'][0]['data'][1][0]='=1';R.save(path,raw)
        with self.assertRaisesRegex(L.StopLoad,'FORMULA_FOUND'):R.decode_snapshot(path,policy)
    def test_uncertain_batch_stops_without_retry_and_keeps_journal_inflight(self):
        worker=FakeWorker('timeout');run,rows=self.run_fixture(worker)
        run.manifest=SimpleNamespace(value={'load_order':['4.Partner Organisation'],'trial_tabs':['4.Partner Organisation'],'pause_seconds':0,'health_every_batches':1},tabs={'4.Partner Organisation':dict(L.TABS['4.Partner Organisation'],records=2,last_data_row=4)},digest=run.manifest.digest)
        run.bind(create=True)
        with run.journal.exclusive():
            run.journal.reconciled(run.approval,'first')
            with patch.object(run,'checkpoint_inventory',return_value=[]),patch.object(R,'ro',return_value={'rows':0,'other':0,'runs':0}),patch.object(R,'table_counts',return_value=[{'rows':0}]),patch.object(R.time,'sleep')as pause:
                with self.assertRaises(TimeoutError):run.execute(trial=True)
            self.assertEqual(run.journal.read()['state'],'in_flight')
            self.assertEqual(len(worker.sql),1);pause.assert_not_called()
            with self.assertRaisesRegex(L.StopLoad,'RECONCILIATION_REQUIRED'):run.execute(trial=True)
            self.assertEqual(len(worker.sql),1)

    def test_legacy_checkpoint_shape_and_tampered_hash_are_refused(self):
        run,rows=self.run_fixture();body,receipt=run.loader._chunk_sql(rows)
        meta={'id':receipt['chunk'],'sheet':rows[0]['sheet'],'first':3,'last':4,'sha256':receipt['sha256'],'status':'committed'}
        self.assertEqual(len(run.rows_for(meta)),2)
        meta['sha256']='0'*64
        with self.assertRaises(L.StopLoad):run.rows_for(meta)
    def test_resume_plan_uses_smaller_chunks_without_altering_approval(self):
        run,rows=self.run_fixture();before=L.canonical(run.approval.ranges);run.batch_rows=1
        chunks=run.chunks(set(),['4.Partner Organisation'])
        self.assertEqual([len(g[0])for g in chunks],[1,1]);self.assertEqual(L.canonical(run.approval.ranges),before)
