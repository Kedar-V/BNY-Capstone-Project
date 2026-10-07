import unittest
from src.eda.merger import extract,normalize_html
class MergerTests(unittest.TestCase):
 def test_inline_money_and_evidence(self):
  t,_=normalize_html('<p>The merger consideration each share receives <b>$12.50</b> in cash per share.</p>')
  cs=extract(t,'DEFM14A')['candidates'];self.assertTrue(any(c['value']=='12.50' for c in cs))
  for c in cs:self.assertEqual(t[c['evidence_start']:c['evidence_end']],c['source_quote'])
 def test_unrelated_money(self):
  self.assertFalse(extract('Our closing market price was $25.00 per share.','S-4')['candidates'])
 def test_exchange_is_not_merger(self):
  self.assertEqual(extract('Exchange offer for outstanding senior notes.','S-4')['detection'],'review_exchange_offer_overlap')
 def test_conflicts_never_resolved(self):
  r=extract('Merger consideration is $10.00 per share.\nMerger consideration is $12.00 per share.','DEFM14A')
  self.assertEqual(r['conflicting_values']['cash_amount'],['10.00','12.00']);self.assertIsNone(r['canonical_fields']['cash_amount'])
 def test_expected_is_not_effective(self):
  self.assertFalse(any(c['field']=='effective_date' for c in extract('The merger is expected to close on January 4, 2020.','8-K')['candidates']))
 def test_actual_completion(self):
  r=extract('The merger was completed on January 4, 2020.','8-K');self.assertEqual(r['candidates'][0]['value'],'January 4, 2020')
 def test_record_is_not_election(self):
  cs=extract('The record date is January 4, 2020.','DEFM14A')['candidates'];self.assertEqual([c['field'] for c in cs],['record_date'])
 def test_par_value_rejected(self):
  r=extract('Merger consideration: common stock par value $0.01 per share receives $15.00 in cash per share.','DEFM14A')
  self.assertNotIn('0.01',[c['value'] for c in r['candidates']])
 def test_hidden_content(self):
  t,_=normalize_html('<html><ix:hidden>fake merger $90 in cash</ix:hidden><p>Visible text</p></html>');self.assertNotIn('fake',t)
if __name__=='__main__':unittest.main()
