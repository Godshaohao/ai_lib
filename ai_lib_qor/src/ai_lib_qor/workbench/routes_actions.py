"""POST action routes for refresh, checks, effective curation, and human acceptance."""
import json
from pathlib import Path
import re

from flask import redirect, render_template, request, session, url_for

from ai_lib_qor.versions.store import locked, write_atomic
from .refresh_forms import refresh_form, run_refresh_form


def register_action_routes(app, ctx):
    work = ctx['work']
    scope = ctx['scope']
    source_config = ctx['source_config']

    @app.post('/path/update', endpoint='update')
    @app.post('/path/refresh')
    def refresh_layer():
        settings = request.path == '/path/update'
        layer = 'all' if settings else (request.form.get('layer') or 'all').lower()
        vendor = request.form.get('vendor') or None
        library = request.form.get('library') or None
        try:
            options = refresh_form(request.form, source_config(), settings=settings)
            res = run_refresh_form(work, layer, request.form, options, vendor=vendor, library=library, actor='web')
            if settings and request.form.get('save_settings') == '1':
                from ai_lib_qor.application.path_config import load_path_config
                cp = work / 'path_sources.json'
                with locked(work):
                    if cp.is_symlink():
                        raise ValueError('来源配置不能为软链接')
                    write_atomic(cp, {**load_path_config(work), **options})
            title = '更新完成' if settings else {
                'l1': 'L1 来源刷新完成', 'l2': 'L2 有效版本推进完成',
                'l3': 'L3 索引刷新完成', 'all': '三层自动同步完成',
            }[layer]
            if res.get('indexes_failed'):
                title = f"索引刷新失败（{res['indexes_failed']} 个库）"
            elif res.get('status') == 'SKIPPED':
                title = '同步选项均已关闭'
            elif res['warnings']:
                title += '（有待处理）'
            stages = {r['layer']: r for r in ([res['l1'], res['l2'], res['l3']] if layer == 'all' else [res])}
            details = []
            for name, stage in stages.items():
                if stage.get('status') == 'SKIPPED':
                    details.append(f'{name} 已关闭')
                elif name == 'L1':
                    details.append(f"L1 新增交付 {stage['delivery_created']} · 新增快照 {stage['formal_created']}")
                elif name == 'L2':
                    details.append(f"L2 初始化 {stage['initialized']} · 新版本 {stage['effective_published']} · 待处理 {stage['effective_pending']}")
                else:
                    details.append(f"L3 更新索引 {stage['indexes_updated']} · 跳过重建 {stage['indexes_skipped_rebuild']} · 失败 {stage['indexes_failed']}")
            session['path_notice'] = {'title': title, 'details': ' · '.join(details), 'warnings': res['warnings'][:8]}
        except (OSError, ValueError, KeyError, TypeError) as exc:
            session['path_notice'] = {'title': '刷新未完成', 'details': str(exc), 'warnings': []}
        return redirect(url_for('library_page', vendor=vendor, library=library) if vendor and library else url_for('overview'))

    @app.post('/path/check')
    def check():
        from ai_lib_qor.application.minimal_checks import run_library, run_revision
        from ai_lib_qor.reporting.check_renderer import render_excel_from_check, render_overall_excel_rows
        vendor, library, _ = scope()
        revision = request.form.get('revision', '')
        baseline = request.form.get('baseline') or None
        lazy_excel = request.form.get('lazy_excel') == '1'
        try:
            result = (
                run_library(work, vendor, library, rerun=request.form.get('rerun') == '1', render_single_excel=not lazy_excel, single_renderer=render_excel_from_check, overall_renderer=render_overall_excel_rows)
                if request.form.get('kind') == 'all'
                else run_revision(work, vendor, library, revision, baseline=baseline, render=not lazy_excel, single_renderer=render_excel_from_check)
            )
            aggregate = request.form.get('kind') == 'all' and request.form.get('rerun') != '1'
            session['path_notice'] = {
                'title': ('汇总已生成' if aggregate else ('检查已完成' if result['state'] == 'SUCCEEDED' else '检查部分完成')),
                'details': '报告已保存到本库，可在下方在线查看或按需导出 Excel。' + ('未检查版本在报告中标为「未检查」。' if aggregate else ''),
                'warnings': [],
            }
        except (OSError, ValueError, KeyError, TypeError) as exc:
            session['path_notice'] = {'title': '检查未完成', 'details': str(exc), 'warnings': []}
        params = {'vendor': vendor, 'library': library, 'revision': revision}
        if baseline:
            params['baseline'] = baseline
        return redirect(url_for('library_page', **params))

    @app.post('/path/facts')
    def facts():
        from ai_lib_qor.application.minimal_facts import build_facts
        vendor, library, _ = scope()
        view = request.form.get('view', '')
        path = request.form.get('path', '')
        revision = request.form.get('revision') or None
        version = request.form.get('version') or None
        try:
            result = build_facts(work, vendor, library, view, path, revision=revision, version=version)
            session['path_notice'] = {'title': '结构明细文件已生成', 'details': Path(result['path']).name, 'artifact': Path(result['path']).name, 'warnings': []}
        except (OSError, ValueError, KeyError, TypeError) as exc:
            session['path_notice'] = {'title': '未能生成结构明细文件', 'details': str(exc), 'warnings': []}
        return redirect(url_for('index_page', vendor=vendor, library=library))

    @app.post('/path/effective/preview')
    def effective_preview():
        from ai_lib_qor.application.minimal_effective import _history, preview_update, restore_issues
        from ai_lib_qor.application.path_query import PathDataQuery
        vendor, library, folder = scope()
        action = request.form.get('action')
        try:
            if action in ('set', 'remove', 'batch'):
                view = request.form.get('view', '')
                path = request.form.get('path', '')
                operations = {'set': [], 'remove': []}
                if action == 'set':
                    operations['set'].append({'view': view, 'path': path, 'version': request.form.get('version', '')})
                elif action == 'remove':
                    operations['remove'].append({'view': view, 'path': path})
                else:
                    selected = request.form.getlist('selection')
                    for key in request.form:
                        if re.fullmatch(r'selection_\d+', key):
                            values = request.form.getlist(key)
                            if len(values) != 1:
                                raise ValueError('每个文件只能选择一个操作')
                            if values[0]:
                                selected.append(values[0])
                    if not selected or len(selected) > 50 or sum(len(x.encode('utf-8')) for x in selected) > 2000:
                        raise ValueError('请选择 1 至 50 项，单次选择内容不超过 2000 字节')
                    for value in selected:
                        item = json.loads(value)
                        if not isinstance(item, dict):
                            raise ValueError('文件选择无效')
                        if item.get('action') == 'set' and set(item) == {'action', 'view', 'path', 'version'}:
                            operations['set'].append({k: item[k] for k in ('view', 'path', 'version')})
                        elif item.get('action') == 'remove' and set(item) == {'action', 'view', 'path'}:
                            operations['remove'].append({k: item[k] for k in ('view', 'path')})
                        else:
                            raise ValueError('文件选择无效')
                preview = preview_update(work, vendor, library, operations)
                draft = {'vendor': vendor, 'library': library, 'action': action, 'operations': operations, 'parent': preview['parent']}
                changes = preview['changes']
                issues = []
            elif action == 'restore':
                revision = request.form.get('revision', '')
                query = PathDataQuery(work)
                index = query.index(vendor, library)
                if not index['revisions'] or revision not in index['revisions']:
                    raise ValueError('有效版本不存在')
                parent = index['revisions'][-1]
                before = query.get_check_context(vendor, library, parent)['members']
                after = query.get_check_context(vendor, library, revision)['members']
                a = {(x['view'], x['path']): x for x in before}
                b = {(x['view'], x['path']): x for x in after}
                changes = [
                    {'view': v, 'path': p, 'before': a.get((v, p), {}).get('version'), 'after': b.get((v, p), {}).get('version')}
                    for v, p in sorted(a.keys() | b.keys())
                    if a.get((v, p), {}).get('version') != b.get((v, p), {}).get('version')
                ]
                target = next(row for _, _, row in _history(folder, library) if row['revision'] == revision)
                issues = restore_issues(work, vendor, library, target['views'])
                draft = {'vendor': vendor, 'library': library, 'action': action, 'revision': revision, 'parent': parent, 'issues': issues}
            else:
                raise ValueError('操作类型无效')
            session['effective_draft'] = draft
            return render_template('path_effective_preview.html', vendor=vendor, library=library, draft=draft, changes=changes, issues=issues, csrf=session['csrf'])
        except (OSError, ValueError, KeyError, TypeError) as exc:
            session.pop('effective_draft', None)
            session['path_notice'] = {'title': '无法预览', 'details': str(exc), 'warnings': []}
            return redirect(url_for('library_page', vendor=vendor, library=library))

    @app.post('/path/effective/apply')
    def effective_apply():
        from ai_lib_qor.application.minimal_effective import apply_update, restore_revision
        vendor, library, _ = scope()
        draft = session.pop('effective_draft', None)
        try:
            if not isinstance(draft, dict) or (draft.get('vendor'), draft.get('library')) != (vendor, library):
                raise ValueError('预览已失效，请重新选择')
            if draft['action'] == 'restore':
                result = restore_revision(work, vendor, library, draft['revision'], expected_parent=draft['parent'], actor='web', expected_issues=draft['issues'])
            else:
                result = apply_update(work, vendor, library, draft['operations'], expected_parent=draft['parent'], actor='web')
            state_map = {
                'PUBLISHED': '已发布',
                'PUBLISHED_INDEX_STALE': '已发布（索引待刷新）',
                'UNCHANGED': '无变化',
            }
            session['path_notice'] = {
                'title': '有效版本已处理',
                'details': state_map.get(result['state'], result['state']) + ' · ' + result['revision'],
                'warnings': [result['index_error']] if result.get('index_error') else [],
            }
        except (OSError, ValueError, KeyError, TypeError) as exc:
            session['path_notice'] = {'title': '发布未完成', 'details': str(exc), 'warnings': []}
        return redirect(url_for('library_page', vendor=vendor, library=library))

    @app.post('/path/acceptance')
    def acceptance_action():
        from ai_lib_qor.application.path_acceptance import accept_revision, rollback_acceptance
        vendor, library, _ = scope()
        action = request.form.get('action', 'accept')
        revision = request.form.get('revision', '')
        reason = request.form.get('reason', '')
        try:
            if action == 'rollback':
                res = rollback_acceptance(work, vendor, library, revision, actor='web', reason=reason)
                session['path_notice'] = {'title': '人工采纳已回退', 'details': f"已将采纳版本回退至 {res['revision']}（原采纳：{res.get('previous_accepted') or '无'}）", 'warnings': []}
            else:
                res = accept_revision(work, vendor, library, revision, actor='web', reason=reason)
                session['path_notice'] = {'title': '已记录人工采纳', 'details': f"已将 {res['revision']} 设为当前采纳版本（与最新有效版本独立维护）", 'warnings': []}
        except (OSError, ValueError, KeyError, TypeError) as exc:
            session['path_notice'] = {'title': '采纳未完成', 'details': str(exc), 'warnings': []}
        return redirect(url_for('library_page', vendor=vendor, library=library, revision=revision) + '#ops')

    @app.post('/path/unadopted/ignore')
    def unadopted_ignore_action():
        from ai_lib_qor.application.path_config import set_unadopted_ignored
        vendor, library, _ = scope()
        view = request.form.get('view', '')
        rel_path = request.form.get('path', '')
        ignored = request.form.get('ignored', '1') == '1'
        try:
            set_unadopted_ignored(work, vendor, library, view, rel_path, ignored=ignored)
            session['path_notice'] = {
                'title': '已忽略未纳入文件提醒' if ignored else '已恢复未纳入文件提醒',
                'details': f'{view}:{rel_path}（不影响 Effective 版本成员）',
                'warnings': [],
            }
        except (OSError, ValueError, KeyError, TypeError) as exc:
            session['path_notice'] = {'title': '操作未完成', 'details': str(exc), 'warnings': []}
        return redirect(url_for('library_page', vendor=vendor, library=library))
