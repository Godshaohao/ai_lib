# Version Detail Review Report Refactor

Status: current

## Goal

将 Version Detail 收敛为一份可解释、可复用的审查投影：首屏只呈现 IP 使用者需要的判断和变化事实；完整的基准分析、交付分析、视图变化、重点文件、未知项和证据评估由同一个结构化 `review_report` 提供，并在本页折叠展示。

## Boundaries

- 不新增主审查页面，不新增 approval workflow。
- 不在 HTML 中读取 RAW、执行 `rglob` 或把 Markdown 当事实源。
- 不把 `review_report` 变成新的事实来源；它只能由现有 scan、diff、review model 和 evidence state 生成。
- Version Detail 仍是唯一审查投影；文件树仍是核对入口。
- 维持现有中文 IP 使用者首屏和管理门禁折叠区。

## Implementation Tasks

1. **Model contract and tests**
   - Extend `src/lib_guard/render/version_review_model.py` with `build_review_report(model, ip_user_view)`.
   - Include fixed sections: `base_analysis`, `delivery_analysis`, `view_delta_analysis`, `focus_file_analysis`, `unknown_analysis`, `evidence_assessment`, `open_questions`, `recommended_actions`.
   - Add reconciliation totals and source references without embedding raw JSON.
   - Add unit tests for first version, missing base/diff, required-view missing, stale evidence and normal change.

2. **Version Detail integration**
   - Attach `review_report` to the existing `version_review_model` and `version_update_detail_model`.
   - Render the report through a pure renderer in `version_review_render.py` or a focused sibling helper; do not move decision logic into HTML generation.
   - Add stable `data-section` markers for decision summary, comparison context, impact summary, view delta, focus files, file structure, review report and evidence status.
   - Keep detailed report sections collapsed and omit giant raw JSON/table payloads from the default projection.

3. **Browser and acceptance checks**
   - Extend `scripts/validate_version_detail_browser.cjs` to assert semantic section markers and report collapse behavior.
   - Cover semantic cases A-H through generated fixtures/model tests and browser assertions for first version, normal full update, missing required view, missing diff, adjacent fallback, UNKNOWN package, FULL+FIX/DOC composition and stale evidence.

4. **Documentation and verification**
   - Update `docs/version_detail_checklist.md` with VD-P0-08, VD-P0-09, VD-P1-08 and VD-P1-09, code mapping and current test evidence.
   - Run targeted tests, compileall, full unittest, `git diff --check`, render current real pages and run the browser validator. If browser dependencies are unavailable, record an explicit SKIP rather than claiming PASS.

## Review Gates

- Upstream Facts -> Review Model -> Version Detail Projection remains the only data path.
- Every displayed aggregate has a source field or an explicit “未形成/待确认” state.
- Added/deleted/changed totals reconcile with View Delta rows and focus-file counts.
- No stale historical browser result is reported as current validation.

## Final Verification Record

- Base commit: `fc59ba4ea5d6634b96bf5a17f51e09c2057da01a`.
- Validation date: `2026-08-18`.
- Workspace state: dirty; this record describes the current working tree and does not claim a commit or push.
- `PYTHONPATH=src python3 -m compileall -q src scripts`: PASS.
- `PYTHONPATH=src python3 -m unittest discover -s src/lib_guard/test -p 'test*.py' -q`: `477` tests, PASS.
- `git diff --check`: PASS.
- Real Version Detail page: `30/30` browser assertions, PASS.
- A-H generated browser scenarios: `8` scenarios, `31/31` assertions each, PASS.
- The browser result includes both basic interaction checks and business-semantic checks; it is not inferred from Python-only tests.
