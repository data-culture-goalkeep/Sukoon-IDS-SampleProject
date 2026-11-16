"""Real PostgreSQL tests; only a disposable network-isolated local Docker DB."""
import copy
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import time
import unittest
import uuid
from test_load_ids import L, fixture, approval, RUN

ROOT = Path(__file__).resolve().parents[1]
IMAGE = 'postgres:17.11-bookworm@sha256:665dc7b37ac52a17e298511414c21d23ffa4e6a6ef6225b3e5d59c7afb35e994'
DOCKER = ['docker','--host=unix:///var/run/docker.sock']
ENV = {k:v for k,v in os.environ.items() if not k.startswith(('SUPABASE_','PG','DOCKER_HOST','DOCKER_CONTEXT','DOCKER_TLS','DOCKER_CERT_PATH'))}

def run(args, data=None, check=True):
    p = subprocess.run(args,input=data,text=True,capture_output=True,env=ENV,timeout=90)
    if check and p.returncode: raise RuntimeError('LOCAL_POSTGRES_COMMAND_FAILED: '+p.stderr[:300])
    return p

class LocalWorker(L.Worker):
    def __init__(self, test):
        self.test=test;self.writes=0;self.queries=[];self.lose_response=False
        self.started=None;self.release=None;self.read_retries=0
    def request(self, suffix, payload=None):
        if suffix=='':return {'id':L.PROJECT,'name':'Sukoon-IDS-SampleProject','status':'ACTIVE_HEALTHY'}
        if suffix=='/postgrest':return {'db_schema':'public,graphql_public'}
        if suffix=='/advisors/security':return {'lints':[]}
        raise AssertionError('No remote or HTTP route is available in integration tests')
    def query(self, sql):
        readonly='READ ONLY' in sql or ' AS safe;' in sql
        if not readonly:
            self.writes+=1
            if self.started:self.started.set();self.release.wait(timeout=10)
        self.queries.append(sql)
        try:result=self.test.sql(sql)
        except RuntimeError:raise L.StopLoad('WRITE_FAILED_OR_UNCERTAIN') from None
        if not readonly and self.lose_response:
            self.lose_response=False
            raise TimeoutError('synthetic response loss after real COMMIT')
        if ' AS safe;' in sql:return [{'safe':result.strip()=='t'}]
        lines=[]
        for line in result.splitlines():
            if line in ('t','f'):
                lines.append(line=='t');continue
            try:lines.append(json.loads(line))
            except json.JSONDecodeError:pass
        from pglast import parse_sql,ast
        selects=[statement.stmt for statement in parse_sql(sql)if isinstance(statement.stmt,ast.SelectStmt)]
        alias=selects[-1].targetList[0].name if selects else None
        return [{alias or 'receipt':lines[-1]}]if lines else []

    def read_query(self,sql):return self.query(sql)

class PostgreSQLLoaderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.name='ids-loader-test-'+uuid.uuid4().hex[:10]
        run(DOCKER+['info','--format','{{.ServerVersion}}'])
        run(DOCKER+['run','--detach','--rm','--name',cls.name,'--network','none',
                    '-e','POSTGRES_HOST_AUTH_METHOD=trust','-e','POSTGRES_DB=ids_template',IMAGE])
        try:
            for _ in range(100):
                if run(DOCKER+['exec',cls.name,'pg_isready','-h','127.0.0.1','-U','postgres','-d','ids_template'],check=False).returncode==0:break
                time.sleep(.1)
            else:raise RuntimeError('Local PostgreSQL readiness failed')
            cls.command=DOCKER+['exec','-i',cls.name,'psql','-X','-qAt','-v','ON_ERROR_STOP=1','-U','postgres']
            def setup(sql):run(cls.command+['-d','ids_template'],sql)
            setup((ROOT/'tests/supabase_compat.sql').read_text())
            for migration in sorted((ROOT/'supabase/migrations').glob('*.sql')):setup(migration.read_text())
            setup("CREATE SCHEMA supabase_migrations; CREATE TABLE supabase_migrations.schema_migrations(version text PRIMARY KEY,name text);")
            for migration in sorted((ROOT/'supabase/migrations').glob('*.sql')):
                version,name=migration.stem.split('_',1)
                setup(f"INSERT INTO supabase_migrations.schema_migrations VALUES ('{version}','{name}');")
        except BaseException:
            run(DOCKER+['rm','-f',cls.name],check=False);raise
    @classmethod
    def tearDownClass(cls):run(DOCKER+['rm','-f',cls.name],check=False)
    def setUp(self):
        self.database='case_'+uuid.uuid4().hex
        run(DOCKER+['exec',self.name,'createdb','-U','postgres','-T','ids_template',self.database])
        self.addCleanup(lambda:run(DOCKER+['exec',self.name,'dropdb','-U','postgres',self.database],check=False))
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.journal=L.Journal(Path(self.temp.name)/'state'/(RUN+'.json'))
        self.worker=LocalWorker(self);self.failures=[]
    def sql(self, sql):return run(self.command+['-d',self.database],sql).stdout
    def scalar(self, sql):return int(self.sql(sql).strip())
    def rows(self):return [fixture('4.Partner Organisation',row=i) for i in (3,4)]
    def loader(self, rows, worker=None):return L.Loader(approval(rows),worker or self.worker,lambda *x:(self.failures.append(x) or True),self.journal)
    def prepare(self, rows):
        loader=self.loader(rows)
        receipt=loader.reconcile(rows,copy.deepcopy(rows),authorized=True)
        self.assertEqual(receipt['mode'],'first');self.assertEqual(self.worker.writes,0)
        return loader
    def state(self):
        with self.journal.exclusive():return self.journal.read()
    def counts(self):
        return [self.scalar('SELECT count(*) FROM '+t) for t in ('ids.partner_organisation','ids_import.source_row','ids_import.import_chunk')]
    def bootstrap(self, invalid=False):
        result=[]
        for tab in ('24.Reference List','23.Staff'):
            for n in range(3,L.TABS[tab]['last_data_row']+1):
                values={'created_by':'SYNTH_STAFF_3','updated_by':'SYNTH_STAFF_3'}
                if tab=='24.Reference List':
                    values.update(reference_value_id=f'staff_type.SYNTH_{n}',list_name='staff_type',display_label=f'Synthetic option {n}')
                    if invalid and n==3:values['updated_by']='SYNTH_MISSING'
                else:values.update(staff_id=f'SYNTH_STAFF_{n}',staff_type_id='staff_type.SYNTH_3')
                cells=[{'userEnteredValue':{'stringValue':values[h.split(' (')[0]]}} if h.split(' (')[0] in values else {} for h in L.TABS[tab]['source_headers']]
                result.append(L.transform(tab,n,cells,L.TABS[tab]['source_headers']))
        return result
    def clean_security_defaults(self):
        # Only this disposable test database: the compatibility fixture deliberately
        # grants global defaults, which the extended verifier must now reject.
        for kind in ('TABLES','SEQUENCES','FUNCTIONS','TYPES'):
            self.sql('ALTER DEFAULT PRIVILEGES REVOKE ALL ON '+kind+' FROM PUBLIC, anon, authenticated, service_role;')

    def test_security_clean_case_including_null_schema_acl_passes(self):
        import ids_runner as R
        self.clean_security_defaults()
        # NULL ACL means PostgreSQL's owner-only schema defaults, not no ACL check.
        self.sql("UPDATE pg_catalog.pg_namespace SET nspacl=NULL WHERE nspname='ids_import';")
        report=R.verify_security(self.worker)
        self.assertEqual(report['rls'],28)
        self.assertEqual(report['policies'],0)
        for key in ('forbidden_grants','forbidden_schema_grants','forbidden_default_grants'):
            self.assertEqual(report[key],0)
        self.assertEqual(report['catalog']['access']['schema_grants'],[])
        self.assertEqual(report['catalog']['access']['default_grants'],[])
        self.assertEqual(self.worker.writes,0)
        acl_queries=[q for q in self.worker.queries if "'schema_grants'" in q]
        self.assertEqual(len(acl_queries),1)
        self.assertTrue(acl_queries[0].startswith('BEGIN READ ONLY;'))

    def test_security_null_schema_acl_still_checks_owner_defaults(self):
        import ids_runner as R
        self.clean_security_defaults()
        self.sql('ALTER SCHEMA ids OWNER TO anon;')
        self.sql("UPDATE pg_catalog.pg_namespace SET nspacl=NULL WHERE nspname='ids';")
        access=R.read_sql(self.worker,R.ACL_SQL,'access')
        self.assertEqual({g['privilege'] for g in access['schema_grants'] if g['role']=='anon'},{'USAGE','CREATE'})
        with self.assertRaisesRegex(L.StopLoad,'PREFLIGHT_FAILED'):
            R.verify_security(self.worker)
        self.assertEqual(self.worker.writes,0)

    def test_security_schema_grant_to_each_forbidden_role_is_refused(self):
        import ids_runner as R
        self.clean_security_defaults()
        for schema in ('ids','ids_import'):
            for role in ('PUBLIC','anon','authenticated','service_role'):
                with self.subTest(schema=schema,role=role):
                    self.sql('GRANT USAGE ON SCHEMA '+schema+' TO '+role+';')
                    access=R.read_sql(self.worker,R.ACL_SQL,'access')
                    self.assertTrue(any(g['schema']==schema and g['role']==role and g['privilege']=='USAGE' for g in access['schema_grants']))
                    with self.assertRaisesRegex(L.StopLoad,'PREFLIGHT_FAILED'):
                        R.verify_security(self.worker)
                    self.sql('REVOKE USAGE ON SCHEMA '+schema+' FROM '+role+';')
        self.assertEqual(self.worker.writes,0)

    def test_security_schema_default_grant_to_each_forbidden_role_is_refused(self):
        import ids_runner as R
        self.clean_security_defaults()
        for schema in ('ids','ids_import'):
            for role in ('PUBLIC','anon','authenticated','service_role'):
                with self.subTest(schema=schema,role=role):
                    prefix='ALTER DEFAULT PRIVILEGES IN SCHEMA '+schema
                    self.sql(prefix+' GRANT SELECT ON TABLES TO '+role+';')
                    access=R.read_sql(self.worker,R.ACL_SQL,'access')
                    self.assertEqual(access['grants'],[])  # Future grants only.
                    self.assertTrue(any(g['scope']==schema and g['role']==role and g['privilege']=='SELECT' for g in access['default_grants']))
                    with self.assertRaisesRegex(L.StopLoad,'PREFLIGHT_FAILED'):
                        R.verify_security(self.worker)
                    self.sql(prefix+' REVOKE SELECT ON TABLES FROM '+role+';')
        self.assertEqual(self.worker.writes,0)

    def test_security_global_default_grants_are_not_hidden_by_schema_revokes(self):
        import ids_runner as R
        self.clean_security_defaults()
        for role in ('PUBLIC','anon','authenticated','service_role'):
            with self.subTest(role=role):
                self.sql('ALTER DEFAULT PRIVILEGES GRANT SELECT ON TABLES TO '+role+';')
                self.sql('ALTER DEFAULT PRIVILEGES IN SCHEMA ids REVOKE SELECT ON TABLES FROM '+role+';')
                access=R.read_sql(self.worker,R.ACL_SQL,'access')
                self.assertTrue(any(g['scope']=='*' and g['role']==role and g['privilege']=='SELECT' for g in access['default_grants']))
                with self.assertRaisesRegex(L.StopLoad,'PREFLIGHT_FAILED'):
                    R.verify_security(self.worker)
                self.sql('ALTER DEFAULT PRIVILEGES REVOKE SELECT ON TABLES FROM '+role+';')
        self.assertEqual(self.worker.writes,0)

    def test_first_run_inventory_is_constant_and_rejects_foreign_rows(self):
        rows=self.rows();self.prepare(rows)
        reads=[q for q in self.worker.queries if 'READ ONLY' in q]
        self.assertEqual(len(reads),1)
        self.assertNotIn('raw_values',reads[0])
        self.sql("INSERT INTO ids.partner_organisation(partner_organisation_id) VALUES ('untracked');")
        with self.assertRaisesRegex(L.StopLoad,'RECONCILIATION_REQUIRED'):
            self.loader(rows).reconcile(rows,copy.deepcopy(rows),authorized=True)
        self.assertEqual(self.worker.writes,0)

    def test_public_runner_reconciles_committed_and_absent_attempts(self):
        import ids_runner as R
        from unittest.mock import patch
        manifest=R.Manifest(ROOT/'docs/source-audit-v2.json')
        rows=self.rows()
        with patch.object(R,'WORK',Path(self.temp.name)/'work'):
            run=R.Run(manifest,RUN,L.private_snapshot(rows),self.worker)
            run.initial_reconcile()
            chunk=rows
            body,receipt=run.loader._chunk_sql(chunk)
            expected={'run':RUN,'chunks':[receipt]}
            with run.journal.exclusive():
                run.journal.begin(run.approval,'synthetic_pending',expected)
                # Nothing was written: accept only a read-only proof of absence.
                outcome=run.reconcile_pending(accept=True)
                self.assertEqual(outcome['outcome'],'not_committed')
                self.assertEqual(self.worker.writes,0)
                run.loader._send(L.transaction(run.loader._run_guard(create=True)+body,expected),expected)
                run.journal.begin(run.approval,'synthetic_lost_response',expected)
                outcome=run.reconcile_pending(accept=True)
                self.assertEqual(outcome['outcome'],'committed')
                self.assertEqual(self.worker.writes,1)
                self.sql("UPDATE ids_import.source_row SET raw_values='[]'::jsonb;")
                with self.assertRaises(L.StopLoad):run.reconcile_pending(accept=True)
                self.assertEqual(self.worker.writes,1)

    def test_public_runner_trial_and_row_clear_preserve_schema(self):
        self.clean_security_defaults()  # Clear requires the extended clean ACL preflight.
        import ids_runner as R
        from unittest.mock import patch
        from types import SimpleNamespace
        policy=SimpleNamespace(digest='invented_manifest',value={'load_order':['4.Partner Organisation'],'trial_tabs':['4.Partner Organisation'],'batch_rows':100,'pause_seconds':0,'health_every_batches':1,'approved_warning_rows':{}},tabs={'4.Partner Organisation':dict(L.TABS['4.Partner Organisation'],records=2,last_data_row=4)})
        with patch.object(R,'WORK',Path(self.temp.name)/'work'):
            run=R.Run(policy,RUN,L.private_snapshot(self.rows()),self.worker)
            run.initial_reconcile()
            with run.journal.exclusive():
                result=run.execute(trial=True,pause=0,health_every=1)
            self.assertEqual(result['loaded'],2)
            self.assertEqual(self.scalar('SELECT count(*) FROM ids.partner_organisation'),2)
            manifest=R.Manifest(ROOT/'docs/source-audit-v2.json')
            with R.operator_lock():report=R.clear_rows(manifest,self.worker,approve_delete=True)
            self.assertEqual(report['rows'],0)
            self.assertEqual(self.scalar('SELECT count(*) FROM ids.partner_organisation'),0)
            self.assertEqual(self.scalar("SELECT count(*)FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname IN('ids','ids_import')AND c.relkind='r'AND c.relrowsecurity"),28)
            self.assertFalse(run.journal.path.exists())

    def test_public_runner_full_continuation_and_lost_finalize_response(self):
        import ids_runner as R
        from unittest.mock import patch
        from types import SimpleNamespace
        policy=SimpleNamespace(digest='invented_manifest',value={'load_order':['4.Partner Organisation'],'trial_tabs':['4.Partner Organisation'],'batch_rows':100,'pause_seconds':0,'health_every_batches':1,'approved_warning_rows':{}},tabs={'4.Partner Organisation':dict(L.TABS['4.Partner Organisation'],records=2,last_data_row=4)})
        with patch.object(R,'WORK',Path(self.temp.name)/'work'):
            run=R.Run(policy,RUN,L.private_snapshot(self.rows()),self.worker)
            run.initial_reconcile()
            with run.journal.exclusive():
                run.execute(trial=True,pause=0,health_every=1)
                self.worker.lose_response=True
                with self.assertRaises(TimeoutError):run.execute(trial=False,pause=0,health_every=1)
                self.assertEqual(self.scalar('SELECT count(*)FROM ids.partner_organisation'),2)
                writes=self.worker.writes
                result=run.reconcile_pending(accept=True)
                self.assertEqual(result['outcome'],'finalized')
                self.assertEqual(self.worker.writes,writes)
                self.assertEqual(run.journal.read()['state'],'ready')
                self.assertEqual(R.verify_loaded(policy,self.worker,RUN)['loaded'],2)

    def test_goal_review_new_boundaries_preserve_lower_limits(self):
        sections={'SMART_GOALS':1,'FUNCTIONAL_LEARNING':0,'HOSPITALITY':0}
        self.sql("INSERT INTO ids.reference_list(reference_value_id,list_name,display_label) VALUES ('programme.ILS','programme','Synthetic ILS'),('goal_section.SMART_GOALS','goal_section','Synthetic SMART'),('goal_section.FUNCTIONAL_LEARNING','goal_section','Synthetic Functional'),('goal_section.HOSPITALITY','goal_section','Synthetic Hospitality'); INSERT INTO ids.learner_profile(learner_id) VALUES ('learner'); INSERT INTO ids.batch(batch_id,program_id) VALUES ('batch','programme.ILS'); INSERT INTO ids.enrolment(enrolment_id,learner_id,batch_id) VALUES ('enrolment','learner','batch');")
        for n,(section,minimum) in enumerate(sections.items(),1):
            self.sql(f"INSERT INTO ids.goal(goal_id,enrolment_id,goal_number,goal_section_id) VALUES ('goal{n}','enrolment',{n},'goal_section.{section}'); INSERT INTO ids.goal_review(goal_review_id,goal_id,milestone_week) VALUES ('review{n}','goal{n}',24);")
            for column in ('faculty_rating_score','family_rating_score'):
                for score in (minimum,5):
                    self.sql(f"UPDATE ids.goal_review SET {column}={score} WHERE goal_review_id='review{n}';")
                for score in (minimum-1,5.01,6):
                    with self.assertRaises(RuntimeError):
                        self.sql(f"UPDATE ids.goal_review SET {column}={score} WHERE goal_review_id='review{n}';")
                self.assertEqual(self.sql(f"SELECT {column} FROM ids.goal_review WHERE goal_review_id='review{n}';").strip(),'5')
                self.sql(f"UPDATE ids.goal_review SET {column}=NULL WHERE goal_review_id='review{n}';")

    def test_month_conversion_database_and_raw_lineage(self):
        row=fixture();headers=L.TABS[row['tab']]['source_headers']
        cells=[{'userEnteredValue':v} for v in row['raw']]
        index=next(i for i,h in enumerate(headers) if h.split(' (')[0]=='month')
        cells[index]={'userEnteredValue':{'stringValue':'2026-11'}}
        rows=[L.transform(row['tab'],3,cells,headers)]
        loader=self.prepare(rows)
        self.sql("INSERT INTO ids.staff(staff_id) VALUES ('fixture_staff_id3');")
        loader.load(rows,copy.deepcopy(rows))
        self.assertEqual(self.sql('SELECT month FROM ids.monthly_target;').strip(),'2026-11-01')
        self.assertEqual(self.sql(f"SELECT raw_values->{index}->>'stringValue' FROM ids_import.source_row;").strip(),'2026-11')

    def test_mid_chunk_error_rolls_back_everything(self):
        rows=self.rows();rows[1]['raw'][0]=copy.deepcopy(rows[0]['raw'][0]);rows[1]['record']['partner_organisation_id']=rows[0]['record']['partner_organisation_id']
        loader=self.prepare(rows)
        with self.assertRaises(L.StopLoad):loader.load(rows,copy.deepcopy(rows))
        self.assertEqual(self.counts(),[0,0,0]);self.assertEqual(self.scalar('SELECT count(*) FROM ids_import.import_run'),0)
        self.assertEqual(self.worker.writes,1);self.assertEqual(self.state()['state'],'in_flight')
    def test_deferred_bootstrap_failure_rolls_back_all_185_rows(self):
        rows=self.bootstrap(invalid=True);loader=self.prepare(rows)
        with self.assertRaises(L.StopLoad):loader.load(rows,copy.deepcopy(rows))
        for t in ('ids.reference_list','ids.staff','ids_import.source_row','ids_import.import_chunk','ids_import.import_run'):
            self.assertEqual(self.scalar('SELECT count(*) FROM '+t),0)
        self.assertEqual(self.worker.writes,1)
    def test_bootstrap_preserves_audit_cycle(self):
        rows=self.bootstrap();loader=self.prepare(rows);loader.load(rows,copy.deepcopy(rows))
        self.assertEqual(self.scalar('SELECT count(*) FROM ids.reference_list'),165)
        self.assertEqual(self.scalar('SELECT count(*) FROM ids.staff'),20)
        self.assertEqual(self.scalar("SELECT count(*) FROM ids.reference_list WHERE created_by='SYNTH_STAFF_3' AND updated_by='SYNTH_STAFF_3'"),165)
    def test_identical_replay_adds_no_records(self):
        rows=self.rows();self.prepare(rows).load(rows,copy.deepcopy(rows));before=self.counts()
        self.loader(rows).load(rows,copy.deepcopy(rows));self.assertEqual(self.counts(),before)
        self.assertEqual(before,[2,2,1])
    def test_changed_replay_rejected_by_python_and_database(self):
        rows=self.rows();loader=self.prepare(rows);loader.load(rows,copy.deepcopy(rows))
        changed=copy.deepcopy(rows);changed[0]['raw'][1]={'stringValue':'Synthetic changed'};changed[0]['record']['organisation_name']='Synthetic changed'
        writes=self.worker.writes
        with self.assertRaises(L.StopLoad):self.loader(changed).load(changed,copy.deepcopy(changed))
        self.assertEqual(self.worker.writes,writes)
        body,_=loader._chunk_sql(changed)
        with self.assertRaises(L.StopLoad):self.worker.query(L.transaction(loader._run_guard()+body,{'test':'changed_chunk'}))
        self.assertEqual(self.counts(),[2,2,1]);self.assertEqual(self.scalar("SELECT count(*) FROM ids.partner_organisation WHERE organisation_name='Synthetic changed'"),0)
    def test_tampered_lineage_replay_and_reconciliation_rejected(self):
        rows=self.rows();self.prepare(rows).load(rows,copy.deepcopy(rows))
        self.sql("UPDATE ids_import.source_row SET raw_values='[]'::jsonb WHERE original_row=3;")
        with self.assertRaises(L.StopLoad):self.loader(rows).load(rows,copy.deepcopy(rows))
        with self.assertRaises(L.StopLoad):self.loader(rows).reconcile(rows,copy.deepcopy(rows),authorized=True)
        self.assertEqual(self.counts(),[2,2,1]);self.assertEqual(self.state()['state'],'in_flight')
    def test_two_concurrent_attempts_only_one_enters_database(self):
        rows=self.rows();self.prepare(rows)
        self.worker.started=threading.Event();self.worker.release=threading.Event();errors=[]
        def first():
            try:self.loader(rows).load(rows,copy.deepcopy(rows))
            except BaseException as exc:errors.append(type(exc).__name__)
        thread=threading.Thread(target=first);thread.start()
        try:
            self.assertTrue(self.worker.started.wait(timeout=10))
            second=LocalWorker(self)
            other=L.Loader(approval(rows),second,lambda *x:True,L.Journal(self.journal.path))
            with self.assertRaisesRegex(L.StopLoad,'RUN_LOCKED'):other.load(rows,copy.deepcopy(rows))
            self.assertEqual(second.queries,[])
        finally:self.worker.release.set();thread.join(timeout=15)
        self.assertFalse(thread.is_alive());self.assertEqual(errors,[]);self.assertEqual(self.counts(),[2,2,1]);self.assertEqual(self.state()['state'],'ready')
    def test_commit_succeeded_response_lost_requires_readonly_reconciliation(self):
        rows=self.rows();loader=self.prepare(rows);self.worker.lose_response=True
        with self.assertRaises(L.StopLoad):loader.load(rows,copy.deepcopy(rows))
        self.assertEqual(self.counts(),[2,2,1]);self.assertEqual(self.state()['state'],'in_flight')
        self.journal.path.unlink() # Simulate journal loss; separate durable marker remains.
        writes=self.worker.writes
        with self.assertRaisesRegex(L.StopLoad,'RECONCILIATION_REQUIRED'):self.loader(rows).load(rows,copy.deepcopy(rows))
        self.assertEqual(self.worker.writes,writes)
        new=self.loader(rows);receipt=new.reconcile(rows,copy.deepcopy(rows),authorized=True)
        self.assertEqual(receipt['mode'],'resume');self.assertEqual(self.worker.writes,writes)
        new.load(rows,copy.deepcopy(rows));self.assertEqual(self.counts(),[2,2,1])
        self.assertEqual(self.scalar("SELECT count(*) FROM ids_import.import_run WHERE status='completed'"),1)

if __name__=='__main__':unittest.main()
