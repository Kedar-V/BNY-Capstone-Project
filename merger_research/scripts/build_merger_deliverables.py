from pathlib import Path
import json,re,io,contextlib,os,hashlib
root=Path(__file__).resolve().parents[1]
rows=json.loads((root/'outputs/mergers/extractions.json').read_text())
examples=[]
for acc,field,value,phrase,note in [
 ('0001193125-20-000113','cash_amount','47.60','entitled to receive','Proposed cash consideration in this filing; not eventual closing terms.'),
 ('0001193125-20-001590','cash_amount','135.00','entitled to receive','Proposed cash consideration; exclude par value and historical trading prices.'),
 ('0001104659-20-000535','cash_amount','15.25','right to receive','Per target common share, conditional on completion.'),
 ('0001193125-20-003953','conversion_ratio','0.400','right to receive','Cliffs shares per AK Steel share; fractional-share cash is separate.'),
 ('0001193125-20-003085','conversion_ratio','0.5924','right to receive','Base ratio only: may adjust to 1.2739 or 1.8006. Do not resolve as unconditional.'),
]:
 r=next(x for x in rows if x['accession']==acc);t=(root/r['normalized_path']).read_text()
 match=next(m for m in re.finditer(phrase,t,re.I) if value in t[m.start():m.end()+250]);lo=max(0,match.start()-160);hi=min(len(t),match.end()+450)
 examples.append({'accession':acc,'entity_name':r['entity_name'],'url':r['url'],'field':field,'observed_value':value,'note':note,'quote':t[lo:hi],'evidence_start':lo,'evidence_end':hi,'extractor_found_value':any(c['field']==field and c['value']==value for c in r['candidates']),'review_status':'assistant_inspected_development_example_not_independent_gold'})
(root/'outputs/mergers/spot_checks.json').write_text(json.dumps(examples,indent=2))
comparison=[]
for r in rows:
 t=(root/r['normalized_path']).read_text();naive=list(re.finditer(r'\$\s*\d[\d,]*(?:\.\d+)?',t))
 comparison.append({'accession':r['accession'],'entity_name':r['entity_name'],'form':r['form'],'all_dollar_mentions':len(naive),'context_cash_candidates':sum(c['field']=='cash_amount' for c in r['candidates']),'detection':r['detection']})
(root/'outputs/mergers/method_comparison.json').write_text(json.dumps(comparison,indent=2))
summary=json.loads((root/'outputs/mergers/summary.json').read_text())
report=root/'docs/merger_research.md'
s=report.read_text().split('\n## Observed run results')[0];s+='\n## Observed run results\n\n'
s+=f"All {summary['documents_processed']} requested sample documents were parsed. Routing: {summary['document_detection']}. {summary['documents_with_value_candidates']} documents yielded numerical/date candidates; {summary['documents_with_conflicting_values']} contained multiple values for at least one field. No event was auto-approved.\n\n"
s+=f"Candidate occurrences by field: {summary['candidate_counts']}. Explicit election deadlines and completed-merger effective dates were not extracted in this sample; this is not evidence that the fields never occur in merger filings.\n\n"
s+=f"The run used {summary['processing_seconds_total']:.2f} seconds total local processing, with a median of {summary['processing_seconds_median']:.3f} seconds per document. Whole-document dollar matching found {sum(x['all_dollar_mentions'] for x in comparison):,} occurrences versus {sum(x['context_cash_candidates'] for x in comparison):,} contextual cash candidates. This measures filtering volume, not a precision improvement. All five inspected development values were {'found' if all(e['extractor_found_value'] for e in examples) else 'not all found'} by the baseline; this is a smoke check, not held-out accuracy.\n"
report.write_text(s)
cells=[]
def md(s):cells.append({'cell_type':'markdown','metadata':{},'source':s.splitlines(True)})
def code(s):cells.append({'cell_type':'code','metadata':{},'source':s.splitlines(True),'execution_count':None,'outputs':[]})
md('# Merger filing research and extraction\n\nAaron’s merger contribution: validate forms → load real filings → inspect structure → experiment with extraction → map to BNY fields and evaluation. See [the full report](../docs/merger_research.md). All outputs are candidate evidence; canonical fields remain null.')
code("from pathlib import Path\nimport json\nfrom collections import Counter\nROOT = Path.cwd() if (Path.cwd() / 'data/mergers').exists() else Path.cwd().parent\ndef read(name):\n    return json.loads((ROOT / 'outputs/mergers' / name).read_text())\nrows = read('extractions.json')\nsummary = read('summary.json')\nprint(json.dumps(summary, indent=2))")
md('## Form validation and metadata coverage\n\nDEFM14A/PREM14A are merger-or-acquisition proxies; S-4 also covers exchanges; SC 13E3 covers certain going-private structures; 425 supplies communications. Merger 8-K discovery remains a gap because the existing 8-K track is conversion-filtered. See official SEC references in the report. Counts below are metadata, not verified merger events.')
code("for r in read('metadata_inventory.json'):\n    print(f\"{r['form']:10} hits={r['metadata_rows']:6,} accessions={r['unique_accessions']:6,} primary={r['primary_document_rows']:6,} tracks={r['tracks']}\")")
md('## Actual downloaded sample and structure\n\nFive documents per form, chosen from the existing early-2020 convenience sample. Several share deals; no held-out performance claim is possible. HTML tables are counted but flattened; section/table-aware extraction is the next improvement.')
code("for r in rows:\n    print(f\"{r['form']:10} {r['entity_name'][:35]:35} chars={r['characters']:9,} tables={r['html_tables']:4} {r['detection']}\")")
md('## Regex experiment\n\nCompare all dollar mentions with contextual per-security candidates. The baseline excludes labelled par values and routes debt-exchange overlaps to review. Reduced counts do not imply measured precision. Dates have distinct roles; passage retrieval does not populate values.')
code("comparison = read('method_comparison.json')\nprint('All dollar mentions:', sum(r['all_dollar_mentions'] for r in comparison))\nprint('Context cash candidates:', sum(r['context_cash_candidates'] for r in comparison))\nprint('Candidate fields:', summary['candidate_counts'])\nprint('Passage fields:', dict(Counter(p['field'] for r in rows for p in r['passages'])))")
md('## Inspected examples: cash, stock, and conditional terms\n\nThese assistant-inspected development examples help explain behavior. They are not independent human gold labels or final deal outcomes.')
code("for e in read('spot_checks.json'):\n    print('\\n', e['entity_name'], e['field'], e['observed_value'])\n    print(e['note'])\n    print(e['url'])\n    print(e['quote'])\n    print('Candidate retrieved:', e['extractor_found_value'])")
md('## Inspect a filing and its conflicting candidates\n\nChange `entity_query` to examine another company. Repeated values are kept with distinct source offsets; conflicts are not automatically reconciled. Ranks are heuristic, not confidence probabilities.')
code("entity_query = 'TIFFANY'\nr = next(x for x in rows if entity_query.lower() in x['entity_name'].lower())\nprint(r['url'])\nprint(json.dumps(r['conflicting_values'], indent=2))\nprint(json.dumps(r['candidates'][:3], indent=2))")
md('## Evidence integrity check\n\nOffsets refer to saved normalized text, not raw HTML bytes. This verifies grounding locations, not semantic correctness.')
code("checked = 0\nfor r in rows:\n    text = (ROOT / r['normalized_path']).read_text()\n    for c in r['candidates'] + r['passages']:\n        assert text[c['evidence_start']:c['evidence_end']] == c['source_quote']\n        checked += 1\nprint('Exact evidence spans checked:', checked)\nassert all(v is None for r in rows for v in r['canonical_fields'].values())\nprint('All canonical values remain unverified/null.')")
md('## Evaluation and next step\n\nUse `outputs/mergers/review_template.json` for independent labels, recording deal IDs and field evidence. Split by adjudicated deal, including all amendments and counterparties. Report detection F1, applicable critical-field accuracy, evidence support, latency, total cost, and escalation quality. EDGAR accession counts measure form retrieval, not semantic merger recall. LLM backward review supplements independent labels.\n\nNext: collect merger-specific 8-Ks and filing bundles; resolve referenced agreements; segment summary/terms/background and preserve table cells; compare GLiNER or LLM review on the same held-out sample. Accounts, holdings and BNY response deadlines remain internal enrichment.')
md('## Reproduce\n\nFrom the merger_research folder, run `python scripts/run_merger_research.py` and `python -m unittest discover -s tests/mergers -v`. Run `python scripts/audit_merger_metadata.py` to recreate the metadata inventory. Downloads are optional and explicit. Existing project requirements provide BeautifulSoup/lxml/pandas/pyarrow. Re-running extraction preserves any existing review template.')
# Execute every code cell with standard Python and persist its stdout; no external API calls.
os.chdir(root);ns={};execution=0
for c in cells:
 if c['cell_type']!='code':continue
 execution+=1;buf=io.StringIO()
 with contextlib.redirect_stdout(buf):exec(compile(''.join(c['source']),'<notebook>','exec'),ns)
 c['execution_count']=execution;c['outputs']=[{'output_type':'stream','name':'stdout','text':buf.getvalue().splitlines(True)}]
for i,c in enumerate(cells):c['id']=f'merger-{i:02d}'
nb={'cells':cells,'metadata':{'kernelspec':{'display_name':'Python 3','language':'python','name':'python3'},'language_info':{'name':'python','version':'3.13'}},'nbformat':4,'nbformat_minor':5}
(root/'notebooks/merger_eda.ipynb').write_text(json.dumps(nb,indent=2))
print('Notebook executed:',execution,'code cells. Spot checks:',[(e['entity_name'],e['extractor_found_value']) for e in examples])
