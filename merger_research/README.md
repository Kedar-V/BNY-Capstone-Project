# Merger research deliverables

Start with **[the findings report](docs/merger_research.md)** and **[the executed notebook](notebooks/merger_eda.ipynb)**.

- `data/mergers/manifest.json`: 35 SEC source URLs and document identities.
- `data/mergers/raw/`: cached original HTML filings.
- `data/mergers/normalized/`: searchable text used by evidence offsets.
- `outputs/mergers/extractions.json`: candidate values, evidence passages, flags, hashes and unresolved conflicts.
- `outputs/mergers/summary.json`: measured sample results; unsupported accuracy metrics remain null.
- `outputs/mergers/spot_checks.json`: five assistant-inspected examples, not independent gold.
- `outputs/mergers/review_template.json`: blank independent-annotation template; do not label by copying predictions.
- `outputs/mergers/method_comparison.json`: broad dollar matching versus contextual cash candidate counts.
- `outputs/mergers/metadata_inventory.json`: filing-accession versus document-hit audit.

Run using an environment with this folder's requirements.txt:

```sh
python scripts/run_merger_research.py
python scripts/audit_merger_metadata.py
python scripts/build_merger_deliverables.py
python -m unittest discover -s tests/mergers -v
```

The extraction run is offline by default. To retrieve missing sources, add `--download --user-agent 'Your name contact@example.com'`. The notebook also runs offline. Development examples, candidate detection and field values require review; no canonical event or client notification has been approved. The small, early-2020 sample is not a representative benchmark.

This local workspace has cached SEC source files and a copy of the shared metadata corpus at `data/processed/documents.parquet`. Those large caches are gitignored for GitHub; a fresh clone must retrieve the source documents with `--download` and rebuild the corpus before reproducing the metadata audit. The team’s original corpus remains in place.

Install dependencies with `python -m pip install -r requirements.txt`. Run all commands above from this folder.

## 2025 SEC merger candidate archive

The project also has a separate, partial 2025 download of 8,638 SEC filing documents from all filers. The selection is based on merger-related forms and keywords; these are candidate documents, not 8,638 confirmed mergers or unique deals. The archive contains parsed document text and source metadata, not original HTML. Its source archive, 8,638-row manifest, and 28-filer curated sample are in the gitignored `../data/mergers/sec_2025/` directory. This dataset does not replace the 35-document early-2020 development study above.

From `merger_research/`, run the offline importer with this folder's Python dependencies:

```sh
python scripts/import_sec_merger_2025.py
python scripts/import_sec_merger_2025.py --mode all --limit 100
```

The first command processes the 28-document sample; the second processes the first 100 manifest rows as a bounded larger run. Output is written to `outputs/mergers/sec_2025/` as evidence-linked, **unreviewed** extraction candidates and a summary. No canonical merger events, deal links, database rows, or notifications are created. Independent document review and deal-level linkage are the next validation steps.

## Build a reviewed mergers-only filing set

From the project root, create or refresh the review queue (the command retains existing review fields when source text is unchanged):

```sh
python merger_research/scripts/build_mergers_only.py screen
```

Open `merger_research/outputs/mergers/sec_2025/review_queue.csv`. The queue covers all 8,638 downloaded filing documents and shows their SEC URLs, source-text hashes, screening evidence, and review priority. Priority is for ordering review; even `high` is **not** a merger label. For each document you review, set `review_label` to `merger`, `not_merger`, or `uncertain`. For `merger`, also fill `reviewer`, `reviewed_at` (YYYY-MM-DD), and `confirmed_evidence` with an exact passage copied from that filing's saved text (at least 20 characters). `deal_id` is optional and should be assigned only after deal-level reconciliation. Leave documents you have not reviewed blank.

After saving the CSV, export the confirmed filing documents:

```sh
python merger_research/scripts/build_mergers_only.py export
```

The command creates `merger_research/outputs/mergers/sec_2025/confirmed_merger_filings.zip`, containing only the reviewed-and-confirmed source JSON files plus `confirmed_manifest.csv`. It checks the document hash, review identity/date, metadata, and exact supporting quote, and refuses invalid confirmed rows. The export is filing-level: multiple filings can still describe one deal. No unreviewed documents are promoted into it. If nothing has been confirmed, it contains only the manifest header.

The publishable 28-filer example inventory is in [`examples/sec_merger_sample_2025.csv`](examples/sec_merger_sample_2025.csv), with sampling limitations in [`examples/README.md`](examples/README.md). The larger downloaded archives remain under gitignored project `data/`.
