"""Evidence-preserving merger candidate baseline; never a canonical event resolver.

Offsets refer to the saved normalized UTF-8 text (Python character offsets).
Rule scores are rankings, not calibrated probabilities. All candidates need review.
"""
from __future__ import annotations
import re
import hashlib
from bs4 import BeautifulSoup

MERGER_FORMS = {'DEFM14A','PREM14A','S-4','S-4/A','SC 13E3','SC 13E3/A','425','8-K','8-K/A'}
MONTH = r'(?:January|February|March|April|May|June|July|August|September|October|November|December)'
DATE = MONTH + r'\s+\d{1,2},?\s+20\d{2}'
CUE = re.compile(r'\b(?:agreement and plan of merger|merger agreement|merger consideration|business combination agreement)\b',re.I)
# Narrow value rules + broader passage retrieval. A passage is NOT a populated value.
RULES = {
 'cash_amount': [r'\$\s*(?P<value>\d[\d,]*(?:\.\d+)?)\s*(?:in cash\s*)?per\s+(?:share|ADS|unit)',r'\$\s*(?P<value>\d[\d,]*(?:\.\d+)?)\s*(?:in cash|cash)'],
 'conversion_ratio': [r'right to receive\s+(?P<value>\d+\.\d+)\s+(?:of a\s+)?(?:[A-Za-z][A-Za-z.-]*\s+){0,5}(?:common\s+)?shares?\b', r'(?:exchange ratio\s*(?:of|is|will be|equal to|:)\s*)(?P<value>\d+(?:\.\d+)?)',r'(?P<value>\d+\.\d+)\s+(?:of a\s+)?(?:share|shares)\s+of\s+'],
 'election_deadline': [r'election deadline[^.;]{0,100}?(?P<value>'+DATE+r')'],
 'effective_date': [r'(?:merger (?:became effective|was completed|was consummated)|completed the merger|consummated the merger)\s+on\s+(?P<value>'+DATE+r')'],
 'record_date': [r'record date[^.;]{0,90}?(?P<value>'+DATE+r')'],
}
PASSAGES = {
 'parties': r'agreement and plan of merger.{0,150}?\b(?:among|between)\b',
 'old_security_description': r'(?:each|every)\s+(?:outstanding\s+)?share\s+of',
 'new_security_description': r'shares? of.{0,100}?(?:common stock|ordinary shares)',
 'available_options': r'cash election|stock election|mixed election|elect to receive',
 'default_option': r'non[- ]electing|no election|fail.{0,40}election|do not.{0,30}elect',
 'proration_terms': r'\bprorat(?:ion|ed|e)\b',
 'conditions': r'conditions to (?:the )?(?:merger|completion|closing)|regulatory approvals?',
 'expected_closing_date': r'(?:expect|anticipat).{0,100}(?:clos|complet)|(?:clos|complet).{0,100}(?:expect|anticipat)',
 'termination': r'(?:terminated|termination of)\s+(?:the\s+)?merger agreement',
}

def normalize_html(raw: str) -> tuple[str,dict]:
 soup=BeautifulSoup(raw,'lxml')
 for tag in list(soup.find_all(True)):
  if tag.name and (tag.name.lower() in {'script','style','noscript','ix:header','ix:hidden'}): tag.decompose()
 tables=len(soup.find_all('table'))
 # Space-join inline text, retain block/table-row boundaries for local context.
 for tag in soup.find_all(['p','div','tr','h1','h2','h3','h4','li','br']): tag.insert_before('\n');tag.insert_after('\n')
 lines=[re.sub(r'\s+',' ',line).strip() for line in soup.get_text(' ').splitlines()]
 text='\n'.join(line for line in lines if line)
 return text,{'html_tables':tables,'characters':len(text),'sha256':hashlib.sha256(text.encode()).hexdigest()}

def context(text,start,end):
 lo=max(start-450,0)
 hi=min(len(text),end+450)
 return lo,hi,text[lo:hi]

def extract(text: str, form: str) -> dict:
 cues=list(CUE.finditer(text))
 # Full filing can mention historical mergers: candidate relevance only.
 front=text[:18000]
 debt_exchange=bool(re.search(r'exchange offer',front,re.I) and re.search(r'(?:senior|subordinated) notes',front,re.I))
 decision='review_exchange_offer_overlap' if debt_exchange else ('merger_candidate' if cues else 'review_no_strong_merger_cue')
 candidates=[]; passages=[]
 for field,patterns in RULES.items():
  for rule_i,pattern in enumerate(patterns):
   for m in re.finditer(pattern,text,re.I):
    lo,hi,quote=context(text,m.start(),m.end())
    local_merger=bool(re.search(r'merger|converted into|right to receive|consideration',quote,re.I))
    if field in {'cash_amount','conversion_ratio'} and not local_merger: continue
    if field=='cash_amount':
     if re.search(r'par value\s*$',text[max(0,m.start()-40):m.start()],re.I): continue
     if not re.search(r'per (?:share|ADS|unit)|(?:each|every) share|for each',quote,re.I): continue
    if decision != 'merger_candidate' and field in {'cash_amount','conversion_ratio'}: continue
    # Prices in trading history, valuations, rival bids, and option awards must not be auto-resolved.
    risks=[]
    for label,pat in [('historical_or_valuation',r'market price|closing price|trading|discounted cash|fairness|valuation'),('alternative_or_award',r'prior proposal|previous proposal|competing|unsolicited|stock option|equity award'),('conditional',r'\bif\b|subject to|expected|anticipated')]:
     if re.search(pat,quote,re.I): risks.append(label)
    value=m.group('value')
    if field in {'cash_amount','conversion_ratio'}: value=value.replace(',','')
    candidates.append({'field':field,'value':value,'value_start':m.start('value'),'value_end':m.end('value'),'evidence_start':lo,'evidence_end':hi,'source_quote':quote,'rule':f'{field}_{rule_i+1}','review_flags':risks,'rank':2 if local_merger and not risks else 1,'status':'unverified_candidate','currency':None,'amount_basis':'per_security_candidate' if field=='cash_amount' else None})
 for field,pattern in PASSAGES.items():
  for m in re.finditer(pattern,text,re.I):
   lo,hi,quote=context(text,m.start(),m.end())
   passages.append({'field':field,'evidence_start':lo,'evidence_end':hi,'source_quote':quote,'status':'passage_only'})
 # Deduplicate overlapping rules, keeping every distinct value occurrence.
 candidates=list({(c['field'],c['value_start'],c['value_end']):c for c in candidates}.values())
 conflicts={f:sorted({c['value'] for c in candidates if c['field']==f}) for f in RULES}
 conflicts={f:v for f,v in conflicts.items() if len(v)>1}
 return {'detection':decision,'cue_count':len(cues),'form':form,'candidates':candidates,'passages':passages,'conflicting_values':conflicts,'canonical_fields':{f:None for f in list(RULES)+list(PASSAGES)},'requires_review':True,'method':'context_regex_v1'}
