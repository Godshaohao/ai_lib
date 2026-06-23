# lib_guard Engineering Flow

## Goal

Keep lib_guard maintainable while it grows from scripts into a catalog-driven library management system.

## Steps

1. Identify whether the request is UI, data/rule, CLI, release, docs, or packaging.
2. Read only the relevant source files and docs.
3. State allowed and forbidden modification areas when the work is broad.
4. Change source files, not generated HTML.
5. Add or update focused tests for behavior changes.
6. Regenerate demo outputs when changing renderers.
7. Report what changed, what did not change, and how it was verified.

## Cleanup Priorities

1. Keep Catalog as the entry/control plane.
2. Keep Scan responsible for delivery structure evidence.
3. Keep Diff focused on structural changes, not noisy raw file diff.
4. Keep Release as file-level manifest/link/postcheck evidence.
5. Keep renderers separate from data logic.
6. Move shared low-level IO/state helpers only when duplication becomes painful.
