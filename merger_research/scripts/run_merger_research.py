#!/usr/bin/env python3
"""Run offline extraction; optionally fetch missing sources explicitly with --download.
Usage: python scripts/run_merger_research.py [--download --user-agent 'Name email']
"""
import argparse,json,sys,time,hashlib,urllib.request
from pathlib import Path
from collections import Counter
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from src.eda.merger import normalize_html,extract

def run(root,download=False,user_agent=None):
 manifest=json.loads((root/'data/mergers/manifest.json').read_text())
 out=root/'outputs/mergers';out.mkdir(parents=True,exist_ok=True)
 normalized=root/'data/mergers/normalized';normalized.mkdir(parents=True,exist_ok=True)
 results=[];timings=[]
 for r in manifest:
  raw=root/r['raw_path']; rec=dict(r)
  if not raw.exists() and download:
   if not user_agent: raise ValueError('--user-agent with a contact address is required')
   try:
    req=urllib.request.Request(r['url'],headers={'User-Agent':user_agent})
    raw.parent.mkdir(parents=True,exist_ok=True);raw.write_bytes(urllib.request.urlopen(req,timeout=45).read());time.sleep(.3)
   except Exception as e:rec['error']=str(e)
  if not raw.exists():
   rec['status']='missing_source';results.append(rec);continue
  start=time.perf_counter()
  text,stats=normalize_html(raw.read_text(errors='replace'))
  if len(text)<100 or 'Your Request Originates from an Undeclared Automated Tool' in text:
   rec['status']='invalid_source';results.append(rec);continue
  textpath=normalized/(raw.stem+'.txt');textpath.write_text(text)
  result=extract(text,r['form'])
  rec.update(result);rec.update(stats);rec['status']='ok';rec['normalized_path']=str(textpath.relative_to(root));rec['raw_sha256']=hashlib.sha256(raw.read_bytes()).hexdigest()
  rec['processing_seconds']=time.perf_counter()-start;timings.append(rec['processing_seconds'])
  for c in rec['candidates']+rec['passages']:
   assert text[c['evidence_start']:c['evidence_end']]==c['source_quote']
  results.append(rec)
 (out/'extractions.json').write_text(json.dumps(results,indent=2))
 ok=[r for r in results if r['status']=='ok']
 summary={'documents_requested':len(results),'documents_processed':len(ok),'document_detection':dict(Counter(r['detection'] for r in ok)),'by_form':dict(Counter(r['form'] for r in ok)),'documents_with_value_candidates':sum(bool(r['candidates']) for r in ok),'candidate_counts':dict(Counter(c['field'] for r in ok for c in r['candidates'])),'documents_with_conflicting_values':sum(bool(r['conflicting_values']) for r in ok),'processing_seconds_total':sum(timings),'processing_seconds_median':sorted(timings)[len(timings)//2] if timings else None,'llm_tokens':0,'llm_api_cost_usd':0,'total_compute_cost_usd':None,'detection_f1':None,'event_level_accuracy':None,'discovery_recall':None,'metric_note':'Development sample; candidates are unverified. No independent gold labels or complete discovery denominator. Timing excludes network; local compute cost unmeasured.'}
 (out/'summary.json').write_text(json.dumps(summary,indent=2))
 # Explicitly blank gold fields prevent predictions from silently becoming ground truth.
 review=[{'accession':r['accession'],'url':r['url'],'entity_name':r['entity_name'],'form':r['form'],'deal_id':None,'gold_is_merger':None,'gold_fields':{},'reviewer':None,'review_status':'unreviewed'} for r in ok]
 reviewpath=out/'review_template.json'
 if not reviewpath.exists():reviewpath.write_text(json.dumps(review,indent=2))
 print(json.dumps(summary,indent=2))
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--root',type=Path,default=ROOT);p.add_argument('--download',action='store_true');p.add_argument('--user-agent');a=p.parse_args();run(a.root,a.download,a.user_agent)
