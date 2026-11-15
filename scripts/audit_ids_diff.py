#!/usr/bin/env python3
"""Offline whole-PR audit; reports hashes/categories, never source values/secrets."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
PATTERNS=[rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',rb'gh[pousr]_[A-Za-z0-9]{25,}',rb'github_pat_[A-Za-z0-9_]{30,}',rb'sbp_[A-Za-z0-9]{25,}',rb'eyJ[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{15,}',rb'AKIA[0-9A-Z]{16}']

def leaves(value):
    if isinstance(value,dict):
        for v in value.values():yield from leaves(v)
    elif isinstance(value,list):
        for v in value:yield from leaves(v)
    elif isinstance(value,str):yield value

def source_values(path):
    raw=json.loads(path.read_text());headers={};values={}
    for b in raw['batches']:
        if b['first']<=2<b['first']+len(b['data']):headers[b['tab']]=b['data'][2-b['first']]
    for b in raw['batches']:
        for row,items in enumerate(b['data'],b['first']):
            for index,value in enumerate(items):
                if value is None or value=='':continue
                text=json.dumps(value)if type(value)in(int,float,bool)else str(value)
                header=headers.get(b['tab'],[])
                name=header[index]if row>=3 and index<len(header)else ''
                private=bool(name and ('(PK)'in name or re.search(r'(?:full_name|candidate_name|learner_name|contact_name|organisation_name|email|mobile|phone|aadhaar|pan_number|udid|diagnosis|medication|medical_condition)',name)))
                if b['tab'].split('.',1)[-1]=='Reference List':private=False
                old=values.setdefault(text,{'private':False,'columns':set()});old['private']|=private;old['columns'].add(name)
    return values

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--base',default='origin/main');p.add_argument('--source-snapshot',type=Path,required=True);p.add_argument('--report',type=Path,required=True);a=p.parse_args()
    require=lambda condition:condition or (_ for _ in ()).throw(ValueError('PRIVATE_PATH_REQUIRED'))
    require(a.source_snapshot.resolve().is_relative_to(ROOT/'work')and a.report.resolve().is_relative_to(ROOT/'work'))
    def git(*args):return subprocess.check_output(['git',*args],cwd=ROOT,text=True).splitlines()
    files=sorted(set(git('diff','--name-only',a.base)+git('ls-files','--others','--exclude-standard')))
    tracked=git('ls-files','work','raw','extracts');findings=[];overlaps=[]
    secrets=[v.encode()for k,v in os.environ.items()if any(x in k.upper()for x in ('TOKEN','SECRET','PASSWORD','API_KEY'))and len(v)>=8]
    allowed=set()
    for f in ('docs/model-spec.json','docs/source-audit-v2.json','config/reference-options.json'):
        allowed.update(leaves(json.loads((ROOT/f).read_text())))
    source=source_values(a.source_snapshot)
    counts={'private_source_matches':0,'review_required':0,'common_scalar_overlaps':0,'schema_reference_overlaps':0,'public_word_overlaps':0,'calendar_literal_overlaps':0}
    for name in files:
        path=ROOT/name
        if not path.is_file():continue
        if name.startswith(('work/','raw/','extracts/','.env'))or path.suffix in ('.csv','.tsv','.xlsx','.pickle','.pkl','.lock'):
            findings.append({'file':name,'kind':'private_path'})
        data=path.read_bytes();text=data.decode('utf-8',errors='replace')
        if any(re.search(pattern,data)for pattern in PATTERNS)or any(v in data for v in secrets):findings.append({'file':name,'kind':'credential_pattern_or_exact_secret'})
        for value,info in source.items():
            if value not in text:continue
            if info['private']and value not in allowed:category='private_source_matches'
            elif value in allowed:category='schema_reference_overlaps'
            elif re.fullmatch(r'\d{4}-\d{2}(?:-\d{2})?|\d{2}:\d{2}(?::\d{2})?',value):category='calendar_literal_overlaps'
            elif len(value)<=4 or re.fullmatch(r'[-+]?\d+(?:\.\d+)?',value)or value in ('true','false'):category='common_scalar_overlaps'
            elif re.fullmatch(r'[A-Za-z_]+',value):category='public_word_overlaps'
            else:category='review_required'
            counts[category]+=1
            if category in ('private_source_matches','review_required'):
                line=next((line for line in text.splitlines()if value in line),'')
                overlaps.append({'file':name,'category':category,'source_value_sha256':hashlib.sha256(value.encode()).hexdigest(),'length':len(value),'columns':sorted(info['columns']),'context_redacted':line.replace(value,'<source-value>')[:220]})
    result={'files':files,'tracked_private_files':len(tracked),'credential_findings':findings,'distinct_source_values_scanned':len(source),'source_overlap_counts':counts,'review_findings':overlaps,'interpretation':'Every nonempty source cell value was compared. Public words, common scalars and approved schema/reference metadata can legitimately overlap code/docs; these are reported, not represented as zero source-value overlaps. Private identifiers/contact/medical values and other exact phrase matches require review.'}
    a.report.parent.mkdir(parents=True,exist_ok=True);a.report.write_text(json.dumps(result,indent=2));a.report.chmod(0o600)
    print(json.dumps({k:v for k,v in result.items()if k!='review_findings'}))
    return 1 if findings or tracked or overlaps else 0
if __name__=='__main__':raise SystemExit(main())
