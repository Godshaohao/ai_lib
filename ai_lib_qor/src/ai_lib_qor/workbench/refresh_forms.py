"""Translate the synchronous and background refresh forms into one call."""

from ai_lib_qor.application import path_refresh
from ai_lib_qor.application.path_config import update_options


def refresh_form(form, config, *, settings=False):
    fields = {
        'update_raw': 'raw',
        'update_formal': 'formal',
        'update_index': 'index',
        'auto_effective': 'auto_effective',
    }
    return {
        **update_options(config, **{
            option: form.get(field) == '1'
            for option, field in fields.items() if settings or field in form
        }),
        'raw_root': form['raw_root'].strip() if 'raw_root' in form else config.get('raw_root') or '',
        'nl_root': form['nl_root'].strip() if 'nl_root' in form else config.get('nl_root') or '',
        'nl_version': form.get('nl_version', '').strip() or config.get('nl_version') or '',
    }


def run_refresh_form(work, layer, form, options, **common):
    source = {
        'raw_root': options['raw_root'],
        'nl_root': options['nl_root'],
        'nl_version': options['nl_version'] or None,
        'raw': options['update_raw'],
        'formal': options['update_formal'],
        'verify_raw': form.get('verify_raw') == '1',
    }
    auto_init = form.get('auto_init', '1') == '1'
    force_verify = form.get('force_verify') == '1'
    if layer == 'l1':
        return path_refresh.refresh_l1(work, **source, **common)
    if layer == 'l2':
        return path_refresh.refresh_l2(work, auto_init_from_formal=auto_init, refresh_indexes=options['update_index'], **common)
    if layer == 'l3':
        return path_refresh.refresh_l3(work, force_verify=force_verify, **common)
    if layer == 'all':
        return path_refresh.refresh_all(
            work, **source, auto_effective=options['auto_effective'], update_index=options['update_index'],
            auto_init_from_formal=auto_init, force_verify=force_verify, **common,
        )
    raise ValueError('无效的刷新层级')
