"""Local three-level workbench app factory assembling modular page, action, and API routes."""
import hmac
import ipaddress
import os
from pathlib import Path
from urllib.parse import urlsplit

from flask import Flask, abort, request, session

from ai_lib_qor.sources.layout import library_folder
from ai_lib_qor.sources.config_reader import load_work_config, raw_root_values
from .jobs import JobManager
from .read_cache import WorkbenchReadCache
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
    settings = load_work_config(work).get('workbench', {})
    if not isinstance(settings, dict):
        raise ValueError('workbench 必须为对象')
    host, port = settings.get('host', '127.0.0.1'), settings.get('port', 5050)
    if not isinstance(host, str) or not host.strip() or type(port) is not int or not 1 <= port <= 65535:
        raise ValueError('workbench.host 或 workbench.port 无效')
    clients = settings.get('allowed_clients', [])
    hosts = settings.get('allowed_hosts', [])
    if any(not isinstance(values, list) or any(not isinstance(value, str) or not value.strip() for value in values)
           for values in (clients, hosts)):
        raise ValueError('workbench.allowed_clients 和 allowed_hosts 必须为字符串数组')
    networks = tuple(ipaddress.ip_network(value) for value in ['127.0.0.0/8', '::1/128', *clients])
    allowed_hosts = {'localhost', '127.0.0.1', '::1', *(value.lower().strip('[]') for value in hosts)}
    from ai_lib_qor.application.path_config import workbench_runtime_settings
    runtime_cfg = workbench_runtime_settings(work)
    app.config.update(
        QOR_BIND_HOST=host,
        QOR_BIND_PORT=port,
        QOR_MAX_WORKERS=runtime_cfg['max_workers'],
        QOR_INDEX_PAGE_SIZE=runtime_cfg['index_page_size'],
        QOR_JSON_INVENTORY_PAGE_SIZE=runtime_cfg['json_inventory_page_size'],
    )
    jobs = JobManager(max_workers=runtime_cfg['max_workers'], work_root=work)
    read_cache = WorkbenchReadCache(work)
    app.extensions['jobs'] = jobs
    app.extensions['read_cache'] = read_cache

    @app.before_request
    def security():
        try:
            addr = ipaddress.ip_address(request.remote_addr)
            request_host = urlsplit('//' + request.host).hostname
        except ValueError:
            abort(403)
        if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
            addr = addr.ipv4_mapped
        if request_host not in allowed_hosts or not any(addr in network for network in networks):
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
        raw_paths = raw_root_values(value)
        return {**value, **update_options(value),
                'raw_roots': [raw_paths] if isinstance(raw_paths, str) else raw_paths or []}

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

    @app.template_filter('baseline_label')
    def _baseline_label_filter(baseline):
        if baseline == '__prev_file__':
            return '按文件上一时间版本'
        if baseline in (None, '', '__none__'):
            return '无基线'
        return str(baseline)

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

    @app.after_request
    def _invalidate_cache_after_write(response):
        if request.method in ('POST', 'PUT', 'PATCH', 'DELETE'):
            read_cache.invalidate()
        return response

    @app.context_processor
    def common():
        def _load_libs():
            out = []
            try:
                for f in sorted((work / 'libraries').glob('*/*')):
                    if f.is_dir() and not f.is_symlink() and not f.parent.is_symlink():
                        out.append({'vendor': f.parent.name, 'library': f.name})
            except OSError:
                pass
            return out

        lib_list = read_cache.get_or_compute('sidebar_all_libraries', _load_libs)
        return {
            'csrf': session.get('csrf'),
            'work_root': str(work),
            'notice': session.pop('path_notice', None),
            'all_libraries': lib_list,
        }

    ctx = {
        'work': work,
        'jobs': jobs,
        'read_cache': read_cache,
        'scope': scope,
        'index_state': index_state,
        'source_config': source_config,
    }
    register_page_routes(app, ctx)
    register_action_routes(app, ctx)
    register_api_routes(app, ctx)
    return app
