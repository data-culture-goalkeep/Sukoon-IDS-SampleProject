"""Offline audit regressions with invented source values and a local Git diff."""
import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import uuid

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import audit_ids_diff as A

class SensitiveDiffAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.spec=json.loads((A.ROOT/'docs/model-spec.json').read_text())
        (self.root/'docs').mkdir();(self.root/'config').mkdir();(self.root/'work').mkdir()
        (self.root/'.gitignore').write_text('work/\n')
        (self.root/'docs/model-spec.json').write_text(json.dumps(self.spec))
        (self.root/'docs/source-audit-v2.json').write_text('{}')
        (self.root/'config/reference-options.json').write_text('{}')
        self.git('init','--quiet')
        self.git('add','.')
        self.git('-c','user.name=Offline Test','-c','user.email=offline@example.invalid',
                 'commit','--quiet','-m','Invented audit baseline')
        self.rootpatch=patch.object(A,'ROOT',self.root);self.rootpatch.start();self.addCleanup(self.rootpatch.stop)
    def git(self,*args):
        subprocess.run(['git',*args],cwd=self.root,check=True,capture_output=True)
    def audit(self,column,value,approved=False):
        (self.root/'candidate.txt').write_text(str(value)+'\n')
        if approved:
            (self.root/'docs/source-audit-v2.json').write_text(json.dumps({'invented_metadata':str(value)}))
        snapshot=self.root/'work/source.json';report=self.root/'work/report.json'
        snapshot.write_text(json.dumps({'batches':[{'tab':'invented.Sensitive', 'first':2,
                                                   'data':[[column],[value]]}]}))
        with patch.object(sys,'argv',['audit','--base','HEAD','--source-snapshot',str(snapshot),'--report',str(report)]),contextlib.redirect_stdout(io.StringIO()):
            status=A.main()
        return status,json.loads(report.read_text())
    def test_each_requested_measure_in_diff_fails_even_for_common_scalars(self):
        for column in A.SENSITIVE_MEASURES:
            for value in (0,1,'invented-sensitive-'+uuid.uuid4().hex):
                with self.subTest(column=column,scalar=isinstance(value,int)):
                    status,result=self.audit(column,value,approved=True)
                    self.assertEqual(status,1)
                    self.assertGreater(result['source_overlap_counts']['private_source_matches'],0)
                    self.assertTrue(all('line' in finding and 'context_redacted' not in finding for finding in result['review_findings']))
                    if isinstance(value,str):self.assertNotIn(value,json.dumps(result))
    def test_every_sensitive_detail_column_in_diff_fails(self):
        details=next(t for t in self.spec['tables'] if t['name']=='learner_sensitive_details')
        for field in details['fields']:
            with self.subTest(column=field['name']):
                status,result=self.audit(field['name']+' (FK)','invented-sensitive-'+uuid.uuid4().hex)
                self.assertEqual(status,1)
                self.assertGreater(result['source_overlap_counts']['private_source_matches'],0)
        self.assertIn('disability_percent',A.sensitive_columns())
    def test_absent_sensitive_value_passes(self):
        status,result=self.audit('iq_value','invented-sensitive-'+uuid.uuid4().hex)
        self.assertEqual(status,1)
        (self.root/'candidate.txt').write_text('Unrelated invented code\n')
        with patch.object(sys,'argv',['audit','--base','HEAD','--source-snapshot',str(self.root/'work/source.json'),'--report',str(self.root/'work/report.json')]),contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(A.main(),0)
    def rerun(self):
        with patch.object(sys,'argv',['audit','--base','HEAD','--source-snapshot',str(self.root/'work/source.json'),'--report',str(self.root/'work/report.json')]),contextlib.redirect_stdout(io.StringIO()):
            return A.main()
    def test_reviewed_context_does_not_hide_a_copy_in_a_new_file(self):
        value='invented-sensitive-'+uuid.uuid4().hex
        self.audit('iq_value',value)
        entry={'file':'candidate.txt','context_digest':A.review_digest(value),
               'value_digest':A.review_digest(value),'classification':'coincidental'}
        (self.root/'config/audit-reviewed-contexts.json').write_text(json.dumps({'entries':[entry]}))
        self.assertEqual(self.rerun(),0)
        (self.root/'unreviewed-copy.txt').write_text(value+'\n')
        self.assertEqual(self.rerun(),1)
        result=json.loads((self.root/'work/report.json').read_text())
        self.assertTrue(any(f['file']=='unreviewed-copy.txt' for f in result['review_findings']))
    def test_changed_line_or_later_copy_in_same_file_needs_new_review(self):
        value='invented-sensitive-'+uuid.uuid4().hex
        self.audit('height_value',value)
        entry={'file':'candidate.txt','context_digest':A.review_digest(value),
               'value_digest':A.review_digest(value),'classification':'schema_reference'}
        (self.root/'config/audit-reviewed-contexts.json').write_text(json.dumps({'entries':[entry]}))
        for text in ('copied = '+value, value+'\nsecond_copy = '+value):
            (self.root/'candidate.txt').write_text(text+'\n')
            self.assertEqual(self.rerun(),1)
    def test_review_does_not_cover_a_different_source_value_on_same_line(self):
        value='invented-sensitive-'+uuid.uuid4().hex
        self.audit('weight_value',value)
        entry={'file':'candidate.txt','context_digest':A.review_digest(value),
               'value_digest':A.review_digest('invented_other'),'classification':'coincidental'}
        (self.root/'config/audit-reviewed-contexts.json').write_text(json.dumps({'entries':[entry]}))
        self.assertEqual(self.rerun(),1)

    def test_review_entries_refuse_wildcard_paths_and_unreviewed_classification(self):
        value='invented-sensitive-'+uuid.uuid4().hex
        self.audit('iq_value',value)
        for file,kind in (('*','coincidental'),('candidate.txt','copied_source')):
            entry={'file':file,'context_digest':A.review_digest(value),
                   'value_digest':A.review_digest(value),'classification':kind}
            (self.root/'config/audit-reviewed-contexts.json').write_text(json.dumps({'entries':[entry]}))
            with self.assertRaisesRegex(ValueError,'INVALID_REVIEW_ENTRY'):self.rerun()

    def test_non_sensitive_common_scalar_remains_reported(self):
        status,result=self.audit('invented_non_sensitive_column',0)
        self.assertEqual(status,0)
        self.assertGreater(result['source_overlap_counts']['common_scalar_overlaps'],0)

if __name__=='__main__':unittest.main()
