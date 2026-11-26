"""Translate the synchronous and background refresh forms into one call."""

import re

from ai_lib_qor.application import path_refresh
from ai_lib_qor.application.path_config import update_options
from ai_lib_qor.sources.config_reader import raw_root_values


def _parse_int_opt(raw, label):
    text = (raw or '').strip()
    if not text or text == '0':
        return None
    try:
        val = int(text)
    except ValueError as exc:
        raise ValueError(f'{label} 必须是正整数（留空或 0 表示关闭）') from exc
    if val < 1:
        raise ValueError(f'{label} 必须是大于等于 1 的整数')
    return val


def _parse_keywords_opt(raw):
    text = (raw or '').strip()
    if not text:
        return []
    tokens = [tok.strip() for tok in re.split(r'[,，;\s]+', text) if tok.strip()]
    out = []
    seen = set()
    for tok in tokens:
        folded = tok.casefold()
        if folded not in seen:
            seen.add(folded)
            out.append(tok)
    return out


def refresh_form(form, config, *, settings=False):
    fields = {
        'update_raw': 'raw',
        'update_formal': 'formal',
        'update_index': 'index',
        'auto_effective': 'auto_effective',
    }
    raw_paths = form.get('raw_roots', form.get('raw_root'))
    if raw_paths is None:
        raw_paths = raw_root_values(config)
    else:
        raw_paths = [line.strip() for line in raw_paths.splitlines() if line.strip()]
    if isinstance(raw_paths, str):
        raw_paths = [raw_paths] if raw_paths else []
    opts = {
        **update_options(config, **{
            option: form.get(field) == '1'
            for option, field in fields.items() if settings or field in form
        }),
        'raw_roots': raw_paths if raw_paths is not None else [],
        'nl_root': form['nl_root'].strip() if 'nl_root' in form else config.get('nl_root') or '',
        'nl_version': form.get('nl_version', '').strip() or config.get('nl_version') or '',
    }
    if settings and any(k in form for k in ('lib_filter_threshold', 'lib_filter_keywords', 'lib_filter_exclude', 'lib_filter_max_selected')):
        threshold = _parse_int_opt(form.get('lib_filter_threshold'), 'Liberty 抽样阈值')
        max_sel = _parse_int_opt(form.get('lib_filter_max_selected'), 'Liberty 最多解析文件数')
        keywords = _parse_keywords_opt(form.get('lib_filter_keywords'))
        exclude_keywords = _parse_keywords_opt(form.get('lib_filter_exclude'))
        fallback = form.get('lib_filter_fallback', 'first_n').strip() or 'first_n'
        if fallback not in ('first_n', 'skip'):
            raise ValueError('Liberty 未命中回退策略必须是 first_n 或 skip')
        opts['liberty_parse_filter'] = {
            'enabled': threshold is not None,
            'threshold': threshold,
            'keywords': keywords,
            'exclude_keywords': exclude_keywords,
            'max_selected': max_sel,
            'fallback': fallback,
        }
    if settings and form.get('skip_parse_views_present') == '1':
        raw_views = form.getlist('skip_parse_views') if hasattr(form, 'getlist') else ([form.get('skip_parse_views')] if form.get('skip_parse_views') else [])
        opts['skip_parse_views'] = sorted({str(v).strip().upper() for v in raw_views if str(v).strip()})
    if settings and 'initial_delivery_tail' in form:
        raw_tail = (form.get('initial_delivery_tail') or '').strip()
        if not raw_tail or raw_tail == '0':
            opts['initial_delivery_tail'] = 0
        else:
            try:
                tval = int(raw_tail)
            except ValueError as exc:
                raise ValueError('初始尾部演进窗口必须是非负整数') from exc
            if tval < 0:
                raise ValueError('初始尾部演进窗口必须是非负整数')
            opts['initial_delivery_tail'] = tval
    if settings and any(k in form for k in ('wb_max_workers', 'wb_index_page_size', 'wb_inventory_page_size')):
        wb = dict(config.get('workbench') or {})
        for form_key, cfg_key, label, lo, hi in (
            ('wb_max_workers', 'max_workers', '后台并发任务数', 1, 32),
            ('wb_index_page_size', 'index_page_size', '文件索引每页行数', 10, 500),
            ('wb_inventory_page_size', 'json_inventory_page_size', 'JSON 盘点每页行数', 10, 500),
        ):
            if form_key not in form:
                continue
            raw_v = (form.get(form_key) or '').strip()
            if not raw_v:
                wb.pop(cfg_key, None)
            else:
                try:
                    iv = int(raw_v)
                except ValueError as exc:
                    raise ValueError(f'{label} 必须是 {lo}~{hi} 之间的整数') from exc
                if not (lo <= iv <= hi):
                    raise ValueError(f'{label} 必须在 {lo}~{hi} 之间')
                wb[cfg_key] = iv
        if wb:
            opts['workbench'] = wb
    return opts


def run_refresh_form(work, layer, form, options, **common):
    source = {
        'raw_root': options['raw_roots'],
        'nl_root': options['nl_root'],
        'nl_version': options['nl_version'] or None,
        'raw': options['update_raw'],
        'formal': options['update_formal'],
        'verify_raw': form.get('verify_raw') == '1',
    }
    auto_init = form.get('auto_init', '1') == '1'
    force_verify = form.get('force_verify') == '1'
    business_ip = (form.get('ip') or form.get('business_ip') or '').strip() or None
    strict_partition = form.get('strict_partition') == '1'
    if layer == 'l1':
        return path_refresh.refresh_l1(work, **source, **common)
    if layer == 'l2':
        return path_refresh.refresh_l2(
            work,
            auto_init_from_formal=auto_init,
            refresh_indexes=options['update_index'],
            business_ip=business_ip,
            strict_partition=strict_partition,
            **common,
        )
    if layer == 'l3':
        return path_refresh.refresh_l3(work, force_verify=force_verify, **common)
    if layer == 'all':
        return path_refresh.refresh_all(
            work, **source, auto_effective=options['auto_effective'], update_index=options['update_index'],
            auto_init_from_formal=auto_init, force_verify=force_verify,
            business_ip=business_ip, strict_partition=strict_partition, **common,
        )
    raise ValueError('无效的刷新层级')
