"""Reproduce accession-vs-document counts from the team's existing Parquet corpus."""
import json
from pathlib import Path
import pandas as pd
ROOT=Path(__file__).resolve().parents[1]
d=pd.read_parquet(ROOT/'data/processed/documents.parquet')
forms=['DEFM14A','PREM14A','S-4','S-4/A','SC 13E3','SC 13E3/A','425','8-K','8-K/A']
report=[]
for form,g in d[d.form.isin(forms)].groupby('form'):
 report.append(dict(form=form,metadata_rows=len(g),unique_accessions=g.accession.nunique(),unique_documents=len(g.drop_duplicates(['accession','filename'])),primary_document_rows=int(g.is_primary_form_doc.sum()),earliest=str(g.file_date.min().date()),latest=str(g.file_date.max().date()),tracks=sorted(g.collection_track.dropna().unique().tolist())))
p=ROOT/'outputs/mergers/metadata_inventory.json';p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(report,indent=2));print(p)
