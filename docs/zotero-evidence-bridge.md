# Zotero Evidence Bridge

GitHub is the versioned source of truth for citations used by NEXUS ADRs. Zotero is the working research library.

## Export from Zotero

1. In Zotero Desktop, select the `NEXUS` collection.
2. Export as BibTeX (or Better BibTeX when installed).
3. Replace `references/references.bib` with the export.
4. Preserve citation keys already referenced by ADRs.
5. Run:

```bash
python scripts/validate_bibtex.py references/references.bib
python -m unittest tests.test_validate_bibtex
```

6. Commit through a branch and pull request. Never copy PDFs, credentials, private notes, or attachment paths into GitHub.

## Import into Zotero

NEXUS-generated candidate records should be reviewed before import. Import only BibTeX/RIS records with a verified title, author or issuing organization, publication date, and authoritative identifier such as DOI or an official URL.

## Evidence placement

- `ADR`: sources actually cited by accepted architecture decisions.
- `Standards`: official standards and platform guidance.
- `Academic Papers`: independent peer-reviewed or rigorous academic work.
- `CVEs & Incidents`: vulnerability and incident records.
- `Rejected Evidence`: limitations, dissenting evidence, superseded material, and rejected alternatives.

## Trust boundary

A syntactically valid BibTeX record does not prove that a source is authentic, current, applicable, peer reviewed, or correctly interpreted. High-impact decisions still require evidence triangulation and source verification in the ADR.

## Recovery

If an export damages citation keys or metadata, restore the previous version from Git history, correct the Zotero records, and export again. Do not rewrite citation keys already merged into ADRs without a migration PR.
