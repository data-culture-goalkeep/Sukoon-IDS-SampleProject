"""Synthetic transport tests: no network, source data or real credentials."""
import io
import json
import tempfile
import urllib.error
from email.message import Message
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch
from test_load_ids import L

READ='BEGIN READ ONLY; SELECT 1 AS probe; COMMIT;'
class Response(io.BytesIO):
    def __init__(self,value=b'[{"probe":1}]',status=201,headers=None):
        super().__init__(value);self.status=status;self.headers=headers or Message()

def failure(status=429):
    headers=Message()
    headers['Retry-After']='2';headers['X-RateLimit-Remaining']='0'
    headers['Authorization']='PRIVATE TOKEN';headers['Set-Cookie']='PRIVATE SOURCE'
    return urllib.error.HTTPError('https://private.invalid/PRIVATE',status,'PRIVATE SOURCE',headers,io.BytesIO(b'PRIVATE BODY'))

class WorkerRequestTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.env=patch.dict(L.os.environ,{'SUPABASE_PROJECT_REF':L.PROJECT,'SUPABASE_ACCESS_TOKEN':'SYNTHETIC_TOKEN'});self.env.start();self.addCleanup(self.env.stop)
        self.worker=L.Worker(L.PROJECT);self.worker.diagnostics_path=Path(self.temp.name)/'requests.jsonl'
        self.now=100.0
        def sleep(seconds):self.now+=seconds
        self.clock=patch.object(L.clock,'monotonic',side_effect=lambda:self.now);self.clock.start();self.addCleanup(self.clock.stop)
        self.sleep=patch.object(L.clock,'sleep',side_effect=sleep);self.sleeper=self.sleep.start();self.addCleanup(self.sleep.stop)
    def test_pinned_parser_represents_readonly_and_readwrite_as_constants(self):
        from pglast import parse_sql,ast
        for mode,expected in (('READ ONLY',1),('READ WRITE',0)):
            with self.subTest(mode=mode):
                first=parse_sql(f'BEGIN {mode}; SELECT 1; COMMIT;')[0].stmt
                options=[o.arg for o in first.options if o.defname=='transaction_read_only']
                self.assertEqual(len(options),1)
                self.assertIsInstance(options[0],ast.A_Const)
                self.assertIsInstance(options[0].val,ast.Integer)
                self.assertEqual(options[0].val.ival,expected)
        self.worker.opener=SimpleNamespace(open=Mock(return_value=Response()))
        self.assertEqual(self.worker.read_query(READ),[{'probe':1}])
        self.assertEqual(self.worker.opener.open.call_count,1)
    def test_readwrite_and_conflicting_modes_are_refused_before_transport(self):
        self.worker.opener=SimpleNamespace(open=Mock())
        for mode in ('READ WRITE','READ ONLY, READ WRITE','READ WRITE, READ ONLY',
                     'READ ONLY, READ ONLY'):
            with self.subTest(mode=mode):
                with self.assertRaisesRegex(L.StopLoad,'SCOPE_MISMATCH'):
                    self.worker.read_query(f'BEGIN {mode}; SELECT 1; COMMIT;')
        self.worker.opener.open.assert_not_called()
    def test_http_failure_preserves_only_sanitized_metadata(self):
        self.worker.opener=SimpleNamespace(open=Mock(side_effect=failure()))
        with self.assertRaises(L.StopLoad):self.worker.read_query(READ)
        d=json.loads(self.worker.diagnostics_path.read_text())
        self.assertEqual(d['http_status'],429);self.assertEqual(d['status_text'],'Too Many Requests')
        self.assertEqual(d['headers'],{'retry-after':'2','x-ratelimit-remaining':'0'})
        self.assertIn('elapsed_seconds',d)
        self.assertNotIn('PRIVATE',json.dumps(d));self.assertNotIn('TOKEN',json.dumps(d))
        self.assertEqual(self.worker.diagnostics_path.stat().st_mode&0o777,0o600)
        self.assertEqual(self.worker.opener.open.call_count,1)
    def test_optin_read_retry_respects_retry_after(self):
        self.worker.read_retries=2
        self.worker.opener=SimpleNamespace(open=Mock(side_effect=[failure(),Response()]))
        self.assertEqual(self.worker.read_query(READ),[{'probe':1}])
        self.assertEqual(self.worker.opener.open.call_count,2)
        self.assertGreaterEqual(sum(c.args[0]for c in self.sleeper.call_args_list),2)
        self.assertEqual(len(self.worker.failed_requests),1)
    def test_write_never_retries_even_with_read_retries_enabled(self):
        self.worker.read_retries=2;self.worker.opener=SimpleNamespace(open=Mock(side_effect=failure(503)))
        with self.assertRaises(L.StopLoad):self.worker.query('BEGIN; INSERT INTO ids.staff(staff_id) VALUES (\'invented\'); COMMIT;')
        self.assertEqual(self.worker.opener.open.call_count,1)
    def test_read_envelope_cannot_hide_a_write_or_early_commit(self):
        self.worker.read_retries=2;self.worker.opener=SimpleNamespace(open=Mock())
        for sql in ('SELECT \'READ ONLY\';','BEGIN; SELECT 1; COMMIT;',
                    'BEGIN READ ONLY; COMMIT; INSERT INTO ids.staff(staff_id) VALUES (\'invented\'); COMMIT;',
                    'BEGIN READ ONLY; SET transaction_read_only=off; SELECT 1; COMMIT;',
                    "BEGIN READ ONLY; DO $$BEGIN PERFORM 1; END$$; SELECT 1; COMMIT;"):
            with self.assertRaises(L.StopLoad):self.worker.read_query(sql)
        self.worker.opener.open.assert_not_called()
    def test_timeout_and_invalid_json_are_sanitized_and_not_retried(self):
        for error in (TimeoutError('PRIVATE'),Response(b'PRIVATE JSON')):
            self.worker.opener=SimpleNamespace(open=Mock(side_effect=error if isinstance(error,Exception)else None,return_value=error))
            with self.assertRaises(L.StopLoad):self.worker.read_query(READ)
            d=self.worker.last_response
            self.assertIn(d['error'],('timeout','invalid_response'))
            self.assertNotIn('PRIVATE',json.dumps(d));self.assertEqual(self.worker.opener.open.call_count,1)
    def test_request_pacing_and_header_redaction(self):
        self.worker.opener=SimpleNamespace(open=Mock(side_effect=[Response(),Response()]))
        self.worker.read_query(READ);self.worker.read_query(READ)
        self.assertGreaterEqual(self.now,100.6)
        headers=Message();headers['Retry-After']='Sat, 14 Nov 2026 12:00:00 GMT';headers['X-RateLimit-Limit']='PRIVATE'
        d=L.Worker.response_metadata(503,headers,1.25,'http_error')
        self.assertEqual(d['headers']['retry-after'],'Sat, 14 Nov 2026 12:00:00 GMT')
        self.assertEqual(d['headers']['x-ratelimit-limit'],'[redacted-invalid]')
    def test_retry_budget_is_bounded_and_declines_not_retried(self):
        self.worker.read_retries=2;self.worker.opener=SimpleNamespace(open=Mock(side_effect=failure(403)))
        with self.assertRaises(L.StopLoad):self.worker.read_query(READ)
        self.assertEqual(self.worker.opener.open.call_count,1)
        self.worker.read_retries=3
        with self.assertRaises(L.StopLoad):self.worker.read_query(READ)
        self.assertEqual(self.worker.opener.open.call_count,1)
