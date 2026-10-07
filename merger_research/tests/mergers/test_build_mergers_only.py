import csv
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from scripts.build_mergers_only import export, read_csv, screen, write_csv, FIELDS


class MergerOnlyWorkflowTests(unittest.TestCase):
    def test_reviewed_export_excludes_unreviewed_and_rejects_bad_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / 'source.zip'
            manifest = root / 'manifest.csv'
            queue = root / 'review.csv'
            output = root / 'mergers.zip'
            records = []
            texts = {
                '0001': 'On January 2, 2025, A entered into an Agreement and Plan of Merger with B.',
                '0002': 'The company reported quarterly earnings and mentioned a prior transaction.',
            }
            with zipfile.ZipFile(archive, 'w') as stream:
                for accession, content in texts.items():
                    path = f'documents/{accession}.json'
                    evidence = [{'event_type': 'merger_agreement_signed', 'excerpt': content}] if accession == '0001' else []
                    stream.writestr(path, json.dumps({'text': content, 'evidence': evidence, 'screen_status': 'test'}))
                    records.append({
                        'accession_number': accession, 'filing_date': '2025-01-02',
                        'reporting_filer': 'A', 'cik': '1', 'form': '8-K',
                        'sec_source_url': 'https://www.sec.gov/example', 'archive_path': path,
                    })
            write_csv(manifest, records, list(records[0]))
            result = screen(archive, manifest, queue)
            self.assertEqual(result['screened'], 2)
            rows = read_csv(queue)
            self.assertEqual(rows[0]['suggested_priority'], 'high')
            rows[0].update(review_label='merger', reviewer='Reviewer', reviewed_at='2025-10-07',
                           confirmed_evidence='entered into an Agreement and Plan of Merger')
            write_csv(queue, rows, FIELDS)
            screen(archive, manifest, queue)
            self.assertEqual(read_csv(queue)[0]['review_label'], 'merger')
            summary = export(archive, manifest, queue, output)
            self.assertEqual(summary['confirmed_filings'], 1)
            with zipfile.ZipFile(output) as stream:
                self.assertIn('documents/0001.json', stream.namelist())
                self.assertNotIn('documents/0002.json', stream.namelist())
                self.assertIn('0001', stream.read('confirmed_manifest.csv').decode())
            rows = read_csv(queue)
            rows[0]['confirmed_evidence'] = 'This invented quote is nowhere in the filing.'
            write_csv(queue, rows, FIELDS)
            with self.assertRaisesRegex(ValueError, 'evidence not found'):
                export(archive, manifest, queue, output)


if __name__ == '__main__':
    unittest.main()
