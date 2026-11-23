"""Local three-level workbench app factory assembling modular page, action, and API routes."""
import hmac
import os
from pathlib import Path

from flask import Flask, abort, request, session

from ai_lib_qor.sources.layout import library_folder
from .jobs import JobManager
from .routes_actions import register_action_routes
from .routes_api import register_api_routes
from .routes_pages import register_page_routes


def create_path_app(work_root):
    work = Path(work_root).resolve(strict=True)
    if not work.is_dir():
        raise ValueError('工作目录不存在')
    from ai_lib_qor.application.plugin_loader import load_configured_plugins
    load_configured_plugins(work)
    app = Flask(__name__)
    app.secret_key = os.urandom(32)
    app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Strict')
    jobs = JobManager(max_workers=2, work_root=work)
    app.extensions['jobs'] = jobs

    @app.before_request
    def security():
        if request.remote_addr not in ('127.0.0.1', '::1') or request.host.split(':', 1)[0] not in ('localhost', '127.0.0.1', '['):
            abort(403)
        if 'csrf' not in session:
            session['csrf'] = os.urandom(32).hex()
        token = request.form.get('csrf') or request.headers.get('X-CSRF-Token', '')
        if request.method == 'POST' and not hmac.compare_digest(session['csrf'], token):
            abort(403)

    def scope():
        vendor = request.values.get('vendor', '')
        library = request.values.get('library', '')
        try:
            folder = library_folder(work, vendor, library)
        except ValueError:
            abort(400)
        if not folder.is_dir():
            abort(404)
        return vendor, library, folder

    def index_state(vendor, library, folder):
        try:
            from ai_lib_qor.application.path_query import PathDataQuery
            return PathDataQuery(work).index(vendor, library), None
        except (OSError, ValueError, KeyError, TypeError) as exc:
            return None, str(exc)

    def source_config():
        from ai_lib_qor.application.path_config import load_path_config, update_options
        value = load_path_config(work)
        return {**value, **update_options(value)}

    @app.template_filter('clean_warning')
    def _clean_warning_filter(text):
        s = str(text or '')
        prefix = str(work.resolve()) + '/libraries/'
        alt_prefix = str(work) + '/libraries/'
        for p in (prefix, alt_prefix):
            if s.startswith(p):
                s = s[len(p):]
                break
            elif p in s:
                s = s.replace(p, '')
        return s

    @app.template_filter('actor_label')
    def _actor_label_filter(actor):
        mapping = {
            'web': '页面操作',
            'web-async': '页面触发',
            'web-auto': '自动推进',
            'web-manual': '手工操作',
            'automatic': '自动推进',
            'local': '本地执行',
            'cli': '命令行',
        }
        key = str(actor or '').strip()
        return mapping.get(key, key or '系统')

    @app.template_filter('run_state_label')
    def _run_state_label_filter(state):
        mapping = {
            'SUCCEEDED': '已完成',
            'PARTIAL': '部分完成',
            'FAILED': '执行失败',
            'RUNNING': '运行中',
            'NOT_CHECKED': '未检查',
        }
        key = str(state or '').strip()
        return mapping.get(key, key or '未知')

    @app.template_filter('parse_status_label')
    def _parse_status_label_filter(state):
        mapping = {
            'PARSED': '已解析',
            'COMPLETE': '完整解析',
            'PARTIAL': '部分解析',
            'FAILED': '解析失败',
            'NOT_CHECKED': '未检查',
            'UNSUPPORTED': '暂不支持',
            'SKIPPED': '已跳过',
        }
        key = str(state or '').strip()
        return mapping.get(key, key or '未检查')

    @app.template_filter('acceptance_action_label')
    def _acceptance_action_label_filter(action):
        mapping = {
            'ACCEPT': '人工采纳',
            'ROLLBACK': '回退采纳',
        }
        key = str(action or '').strip()
        return mapping.get(key, key or '采纳变更')

    @app.template_filter('source_match_label')
    def _source_match_label_filter(match_code):
        mapping = {
            'MATCHED_RAW': '已匹配 RAW',
            'UNVERIFIED': '未核验',
            'UNRESOLVED': '未解析',
            'BROKEN': '软链失效',
        }
        key = str(match_code or '').strip()
        return mapping.get(key, key or '未核验')

    @app.template_filter('historical_content_label')
    def _historical_content_label_filter(status):
        mapping = {
            'UNVERIFIED': '未核验历史快照',
            'VERIFIED': '已核验一致',
            'MATCH': '历史内容一致',
            'CHANGED': '历史内容已变更',
            'MISMATCH': '历史内容已变更',
        }
        key = str(status or '').strip()
        return mapping.get(key, key or '未核验历史快照')

    @app.context_processor
    def common():
        lib_list = []
        try:
            for f in sorted((work / 'libraries').glob('*/*')):
                if f.is_dir() and not f.is_symlink() and not f.parent.is_symlink():
                    lib_list.append({'vendor': f.parent.name, 'library': f.name})
        except OSError:
            pass
        return {
            'csrf': session.get('csrf'),
            'work_root': str(work),
            'notice': session.pop('path_notice', None),
            'all_libraries': lib_list,
        }

    ctx = {
        'work': work,
        'jobs': jobs,
        'scope': scope,
        'index_state': index_state,
        'source_config': source_config,
    }
    register_page_routes(app, ctx)
    register_action_routes(app, ctx)
    register_api_routes(app, ctx)
    return app
