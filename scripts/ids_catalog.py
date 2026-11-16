"""Read-only catalog queries extracted from the operational verification helper."""

CATALOG_SQL = "\nSELECT jsonb_build_object(\n 'relations',(select jsonb_agg(jsonb_build_array(c.oid,n.nspname,c.relname,c.relkind,c.relowner,c.relacl,c.reloptions,c.relrowsecurity,c.relforcerowsecurity) order by c.oid) from pg_class c join pg_namespace n on n.oid=c.relnamespace where n.nspname in('ids','ids_import')),\n 'columns',(select jsonb_agg(jsonb_build_array(a.attrelid,a.attnum,a.attname,a.atttypid,a.atttypmod,a.attnotnull,a.attidentity,a.attgenerated,a.attcollation,pg_get_expr(d.adbin,d.adrelid)) order by a.attrelid,a.attnum) from pg_attribute a join pg_class c on c.oid=a.attrelid join pg_namespace n on n.oid=c.relnamespace left join pg_attrdef d on d.adrelid=a.attrelid and d.adnum=a.attnum where n.nspname in('ids','ids_import') and a.attnum>0 and not a.attisdropped),\n 'constraints',(select jsonb_agg(jsonb_build_array(c.oid,c.conrelid,c.conname,pg_get_constraintdef(c.oid)) order by c.oid) from pg_constraint c join pg_namespace n on n.oid=c.connamespace where n.nspname in('ids','ids_import')),\n 'indexes',(select jsonb_agg(jsonb_build_array(i.indexrelid,pg_get_indexdef(i.indexrelid)) order by i.indexrelid) from pg_index i join pg_class c on c.oid=i.indrelid join pg_namespace n on n.oid=c.relnamespace where n.nspname in('ids','ids_import')),\n 'views',(select jsonb_agg(jsonb_build_array(c.oid,pg_get_viewdef(c.oid,true)) order by c.oid) from pg_class c join pg_namespace n on n.oid=c.relnamespace where n.nspname in('ids','ids_import') and c.relkind in('v','m')),\n 'functions',(select jsonb_agg(jsonb_build_array(p.oid,p.proowner,p.proacl,pg_get_functiondef(p.oid)) order by p.oid) from pg_proc p join pg_namespace n on n.oid=p.pronamespace where n.nspname in('ids','ids_import')),\n 'triggers',(select jsonb_agg(jsonb_build_array(t.oid,t.tgenabled,pg_get_triggerdef(t.oid)) order by t.oid) from pg_trigger t join pg_class c on c.oid=t.tgrelid join pg_namespace n on n.oid=c.relnamespace where n.nspname in('ids','ids_import')),\n 'sequences',(select jsonb_agg(to_jsonb(s) order by s.seqrelid) from pg_sequence s join pg_class c on c.oid=s.seqrelid join pg_namespace n on n.oid=c.relnamespace where n.nspname in('ids','ids_import')),\n 'schemas',(select jsonb_agg(jsonb_build_array(oid,nspname,nspowner,nspacl) order by oid) from pg_namespace where nspname in('ids','ids_import')),\n 'defaults',(select jsonb_agg(to_jsonb(d) order by d.oid) from pg_default_acl d left join pg_namespace n on n.oid=d.defaclnamespace where n.nspname in('ids','ids_import') or d.defaclnamespace=0)\n) AS definitions\n"

MIGRATIONS_SQL = "SELECT coalesce(jsonb_agg(to_jsonb(m) order by version),'[]'::jsonb) AS migrations FROM supabase_migrations.schema_migrations m;"

ACL_SQL = """SELECT jsonb_build_object(
 'rls',(select jsonb_agg(jsonb_build_object('schema',n.nspname,'table',c.relname,'enabled',c.relrowsecurity) order by n.nspname,c.relname) from pg_class c join pg_namespace n on n.oid=c.relnamespace where n.nspname in('ids','ids_import') and c.relkind in('r','p')),
 'policies',(select coalesce(jsonb_agg(to_jsonb(p) order by schemaname,tablename,policyname),'[]'::jsonb) from pg_policies p where schemaname in('ids','ids_import')),
 'schema_grants',(select coalesce(jsonb_agg(x order by schema,grantee,privilege),'[]'::jsonb) from (
  select n.nspname as schema,a.grantee,
   case when a.grantee=0 then 'PUBLIC' else pg_get_userbyid(a.grantee)::text end as role,
   a.privilege_type as privilege,a.is_grantable
  from pg_namespace n
  cross join lateral aclexplode(coalesce(n.nspacl,acldefault('n',n.nspowner)))a
  where n.nspname in('ids','ids_import')
   and (a.grantee=0 or a.grantee in(select oid from pg_roles where rolname in('anon','authenticated','service_role')))
 )x),
 'default_grants',(select coalesce(jsonb_agg(x order by scope,owner,object_type,grantee,privilege),'[]'::jsonb) from (
  select case when d.defaclnamespace=0 then '*' else n.nspname::text end as scope,
   pg_get_userbyid(d.defaclrole)::text as owner,d.defaclobjtype as object_type,a.grantee,
   case when a.grantee=0 then 'PUBLIC' else pg_get_userbyid(a.grantee)::text end as role,
   a.privilege_type as privilege,a.is_grantable
  from pg_default_acl d left join pg_namespace n on n.oid=d.defaclnamespace
  cross join lateral aclexplode(d.defaclacl)a
  where (n.nspname in('ids','ids_import') or (d.defaclnamespace=0 and d.defaclobjtype in('r','S','f','T')))
   and (a.grantee=0 or a.grantee in(select oid from pg_roles where rolname in('anon','authenticated','service_role')))
 )x),
 'grants',(select coalesce(jsonb_agg(x order by schema,object,grantee,privilege),'[]'::jsonb) from (
  select n.nspname as schema,c.relname as object,a.grantee,a.privilege_type as privilege from pg_class c join pg_namespace n on n.oid=c.relnamespace cross join lateral aclexplode(coalesce(c.relacl,acldefault(case when c.relkind='S' then 'S'::"char" else 'r'::"char" end,c.relowner)))a where n.nspname in('ids','ids_import') and c.relkind in('r','p','v','m','S','f') and (a.grantee=0 or a.grantee in(select oid from pg_roles where rolname in('anon','authenticated','service_role')))
  union all
  select n.nspname,p.proname,a.grantee,a.privilege_type from pg_proc p join pg_namespace n on n.oid=p.pronamespace cross join lateral aclexplode(coalesce(p.proacl,acldefault('f',p.proowner)))a where n.nspname in('ids','ids_import') and (a.grantee=0 or a.grantee in(select oid from pg_roles where rolname in('anon','authenticated','service_role')))
 )x)
)AS access;"""
