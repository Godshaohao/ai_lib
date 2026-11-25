"""Read-only EDA check script generator (PT / Innovus .csh) projected directly from saved EffectiveVersion members."""
from pathlib import Path
import re

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from ai_lib_qor.application.path_query import PathDataQuery
from ai_lib_qor.sources.timestamps import utc_text

BUILTIN_TEMPLATES_DIR = Path(__file__).resolve().parent / 'script_templates'
_SAFE_TEMPLATE_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z')

BUILTIN_TEMPLATE_META = {
    'pt_check': {
        'label': 'PrimeTime 库检查 (.csh)',
        'tool': 'PrimeTime',
        'description': '针对有效版本 .db / .lib 生成 PrimeTime read_db + check_library + report_lib 模板脚本',
        'required_views': ['DB', 'LIBERTY'],
    },
    'innovus_check': {
        'label': 'Innovus 物理库检查 (.csh)',
        'tool': 'Innovus',
        'description': '针对有效版本 .lef + .db/.lib 生成 Innovus read_physical + Macro/Pin/Site 体检模板脚本',
        'required_views': ['LEF', 'DB', 'LIBERTY'],
    },
}


def _workspace_templates_dir(work) -> Path | None:
    if not work:
        return None
    cand = Path(work).resolve() / 'script_templates'
    if cand.is_dir() and not cand.is_symlink():
        return cand
    return None


def _template_stem(filename: str) -> str:
    if filename.endswith('.csh.j2'):
        return filename[:-7]
    if filename.endswith('.j2'):
        return filename[:-3]
    if filename.endswith('.csh'):
        return filename[:-4]
    return Path(filename).stem


def list_script_templates(work=None) -> list[dict]:
    """List built-in and optional workspace-overridden EDA script templates."""
    found: dict[str, dict] = {}
    if BUILTIN_TEMPLATES_DIR.is_dir():
        for p in sorted(BUILTIN_TEMPLATES_DIR.glob('*.j2')):
            if p.is_symlink() or not p.is_file():
                continue
            name = _template_stem(p.name)
            meta = BUILTIN_TEMPLATE_META.get(name) or {}
            found[name] = {
                'name': name,
                'label': meta.get('label') or f'{name} (.csh)',
                'tool': meta.get('tool') or name,
                'description': meta.get('description') or f'内置脚本模板 {p.name}',
                'required_views': list(meta.get('required_views') or []),
                'source': 'builtin',
                'filename': p.name,
                'path': str(p),
            }

    ws_dir = _workspace_templates_dir(work)
    if ws_dir is not None:
        for p in sorted([*ws_dir.glob('*.csh.j2'), *ws_dir.glob('*.csh')]):
            if p.is_symlink() or not p.is_file():
                continue
            name = _template_stem(p.name)
            prev = found.get(name) or {}
            found[name] = {
                'name': name,
                'label': prev.get('label') or f'{name} (工作区自定义 .csh)',
                'tool': prev.get('tool') or name,
                'description': prev.get('description') or f'工作区自定义脚本模板 {p.name}',
                'required_views': prev.get('required_views') or [],
                'source': 'workspace_override' if name in found else 'workspace_custom',
                'filename': p.name,
                'path': str(p),
            }
    return [found[k] for k in sorted(found)]


def _resolve_template_file(work, template: str) -> tuple[str, Path, str]:
    name = str(template or '').strip()
    if name.endswith('.csh.j2'):
        name = name[:-7]
    elif name.endswith('.csh'):
        name = name[:-4]
    if not name or not _SAFE_TEMPLATE_RE.fullmatch(name) or name in ('.', '..'):
        raise ValueError(f'脚本模板名称无效: {template}')

    ws_dir = _workspace_templates_dir(work)
    if ws_dir is not None:
        for suffix in ('.csh.j2', '.csh'):
            cand = ws_dir / f'{name}{suffix}'
            if cand.is_file() and not cand.is_symlink():
                return name, cand, f'workspace:script_templates/{cand.name}'

    for suffix in ('.csh.j2', '.csh'):
        cand = BUILTIN_TEMPLATES_DIR / f'{name}{suffix}'
        if cand.is_file() and not cand.is_symlink():
            return name, cand, f'builtin:{cand.name}'

    available = ', '.join(t['name'] for t in list_script_templates(work))
    raise ValueError(f'未找到脚本模板: {template}（可用模板：{available or "无"}）')


def render_eda_script(
    work,
    vendor: str,
    library: str,
    revision: str | None = None,
    *,
    template: str = 'pt_check',
    business_ip: str | None = None,
    output_dir: str | None = None,
    extra_vars: dict | None = None,
) -> dict:
    """Render an EDA `.csh` check script directly from saved EffectiveVersion members (zero RAW rescan)."""
    query = PathDataQuery(work)
    resolved_name, tpl_path, tpl_source = _resolve_template_file(work, template)

    if not revision:
        idx = query.index(vendor, library)
        if business_ip:
            from ai_lib_qor.application.path_query import build_track_index_view
            from ai_lib_qor.sources.layout import library_folder
            idx, _, _ = build_track_index_view(library_folder(work, vendor, library), vendor, library, idx, business_ip)
        revs = idx.get('revisions') or []
        if not revs:
            raise ValueError('当前库/轨道尚无有效版本，无法生成 EDA 检查脚本')
        revision = revs[-1]

    ctx = query.get_check_context(vendor, library, revision, business_ip=business_ip)
    members = ctx.get('members') or []
    members_by_view: dict[str, list[dict]] = {}
    deliveries_used = set()
    for m in members:
        v = m['view']
        members_by_view.setdefault(v, []).append({
            'view': v,
            'path': m['path'],
            'version': m['version'],
            'absolute_path': m['absolute_path'],
        })
        if m.get('version'):
            deliveries_used.add(m['version'])
    for v in members_by_view:
        members_by_view[v].sort(key=lambda r: r['path'])

    ip_part = f'__{business_ip}' if business_ip else ''
    default_out_dir = f'./run_{resolved_name}_{library}{ip_part}_{revision}'
    out_dir_str = str(output_dir).strip() if output_dir else default_out_dir
    download_filename = f'{resolved_name}_{library}{ip_part}_{revision}.csh'

    counts = {
        'LEF': len(members_by_view.get('LEF', [])),
        'DB': len(members_by_view.get('DB', [])),
        'LIBERTY': len(members_by_view.get('LIBERTY', [])),
        'VERILOG': len(members_by_view.get('VERILOG', [])),
        'GDS': len(members_by_view.get('GDS', [])),
        'CDL': len(members_by_view.get('CDL', [])),
        'TOTAL': len(members),
    }

    warnings = []
    if resolved_name == 'pt_check' and counts['DB'] == 0:
        warnings.append(f'当前有效版本 {revision} 尚未包含 .db 文件（共有 {counts["LIBERTY"]} 个 .lib），脚本中 db_files 为空，执行前需先补充 .db 或改用 read_lib。')
    if resolved_name == 'innovus_check' and counts['LEF'] == 0:
        warnings.append(f'当前有效版本 {revision} 尚未包含 .lef 文件，Innovus 物理检查前需确认 LEF 交付。')

    env = Environment(
        loader=FileSystemLoader(str(tpl_path.parent)),
        autoescape=False,
        keep_trailing_newline=True,
        undefined=StrictUndefined,
    )
    tpl = env.get_template(tpl_path.name)
    render_vars = {
        'vendor': vendor,
        'library': library,
        'business_ip': business_ip,
        'ip_type': ctx.get('ip_type'),
        'revision': revision,
        'generated_at': utc_text(),
        'template': resolved_name,
        'template_source': tpl_source,
        'output_dir': out_dir_str,
        'deliveries_used': sorted(deliveries_used),
        'members': members,
        'members_by_view': members_by_view,
        'lef_files': members_by_view.get('LEF', []),
        'db_files': members_by_view.get('DB', []),
        'lib_files': members_by_view.get('LIBERTY', []),
        'verilog_files': members_by_view.get('VERILOG', []),
        'gds_files': members_by_view.get('GDS', []),
        'cdl_files': members_by_view.get('CDL', []),
        'counts': counts,
    }
    if isinstance(extra_vars, dict):
        for k, val in extra_vars.items():
            if k not in render_vars:
                render_vars[k] = val

    content = tpl.render(**render_vars)
    return {
        'template': resolved_name,
        'template_source': tpl_source,
        'filename': download_filename,
        'vendor': vendor,
        'library': library,
        'business_ip': business_ip,
        'ip_type': ctx.get('ip_type'),
        'revision': revision,
        'output_dir': out_dir_str,
        'counts': counts,
        'deliveries_used': sorted(deliveries_used),
        'warnings': warnings,
        'content': content,
    }


def export_eda_script(
    work,
    vendor: str,
    library: str,
    revision: str | None,
    out_path,
    *,
    template: str = 'pt_check',
    business_ip: str | None = None,
    output_dir: str | None = None,
    overwrite: bool = False,
) -> dict:
    """Write rendered `.csh` script atomically with executable permission (0o755)."""
    import os
    import tempfile

    rendered = render_eda_script(
        work,
        vendor,
        library,
        revision,
        template=template,
        business_ip=business_ip,
        output_dir=output_dir,
    )
    dest = Path(out_path).expanduser().resolve()
    if dest.is_symlink():
        raise ValueError('脚本输出路径不能为软链接')
    if dest.exists() and not overwrite:
        raise ValueError(f'输出文件已存在（如需覆盖请传 --overwrite）: {dest}')
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='.tmp-script-', dir=dest.parent)
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(rendered['content'].encode('utf-8'))
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, 0o755)
        os.replace(tmp, dest)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return {
        **{k: v for k, v in rendered.items() if k != 'content'},
        'path': str(dest),
        'bytes': len(rendered['content'].encode('utf-8')),
    }
