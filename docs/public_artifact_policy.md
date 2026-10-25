# Generated Report and Public Artifact Policy

## Purpose

Keep source code, repeatable test fixtures, and generated review evidence separate. A successful run or a `SIMULATION` label does not by itself grant permission to publish library metadata or vendor data.

## Classification

| Content | Default handling | Version-control rule |
| --- | --- | --- |
| Source code and tests | Maintain and review as code | Commit normally |
| Small synthetic fixtures or explicitly approved open data | Keep minimal and reproducible | Commit only after provenance and license are recorded |
| Per-run JSON, Excel, HTML, parser evidence, and logs | Treat as generated review artifacts; may contain paths, library identifiers, hashes, and vendor metadata | Keep outside routine source commits; publish only as an explicitly reviewed milestone package |
| Script bundles and restore archives | Treat as source archives; inspect contents before sharing | Do not add generated bundles to routine source commits |
| RAW libraries and formal release links/targets | Treat as vendor-controlled engineering inputs | Do not copy or commit through the report workflow |

The repository ignores future untracked output under `bundle/`, `outputs/`, `html/`, and `src_qor/test-results/`. This does not untrack or delete files already committed. Curated fixtures should live under the test fixture tree with their source and license documented.

## Before publishing a report package

1. Confirm the source and redistribution permission for every library or report input. Simulation labeling is not a license.
2. Review JSON, spreadsheets, HTML, and bundle contents for machine paths, user names, internal IP identifiers, vendor metadata, checksums that identify controlled material, and embedded source code.
3. Select only the files needed for the review; do not archive an entire run tree by default.
4. Generate `artifact_manifest.json` for the selected files and verify it after moving or extracting the package:

   ```bash
   PYTHONPATH=src_qor python3 -m lib_guard.review_artifact_manifest build \
     --root /path/to/package --output artifact_manifest.json \
     ip_checks/index.html libraries/example/runs/review-id/review_result.json

   PYTHONPATH=src_qor python3 -m lib_guard.review_artifact_manifest verify \
     --root /path/to/moved-package --manifest artifact_manifest.json
   ```

   The manifest records relative paths, sizes, SHA-256 values, and available Review identity. Verification also checks local HTML links. It is an integrity aid, not a quality or licensing decision.
5. Use a separately reviewed milestone commit/package. Do not mix generated reports into routine source changes.

## Existing public history

The audit of the current checkout found 158 tracked files under `src_qor/test-results` (about 53.5 MB) and 59 tracked files under `bundle/` (about 22.5 MB). Of the test-result files, 129 contain `/home/` paths and 21 contain `/tmp/` paths. This confirms environment-path disclosure; it does not establish whether vendor-derived metadata or bundled source is licensed for redistribution. No credential-safety or vendor-license certification is claimed here.

Ignore rules only prevent future untracked additions; they do not remove tracked files or erase public Git history. This change does not delete historical files, rewrite history, or claim that their redistribution permissions have been confirmed. Until an authorized owner reviews the specific content and its provenance, these existing artifacts are **not certified for further redistribution**. A repository owner must decide whether any historical artifact requires access restriction or a separately approved history-remediation procedure.
