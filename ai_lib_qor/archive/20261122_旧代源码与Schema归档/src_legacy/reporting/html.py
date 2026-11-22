"""Self-contained read-only HTML representation of a v3 check result."""
from html import escape


def render_html(report):
    def e(x):return escape(str(x),quote=True)
    files=''.join('<tr><td>'+e(x['file_key'])+'</td><td>'+e(x['source_changed'])+'</td><td>'+e(x['content_status'])+'</td><td>'+e(len(x['object_changes']))+'</td></tr>' for x in report['file_changes'])
    objects=''.join('<tr><td>'+e(f['file_key'])+'</td><td>'+e(x['object_name'])+'</td><td>'+e(x['attribute'])+'</td><td>'+e(x['old_value'])+'</td><td>'+e(x['new_value'])+'</td><td>'+e(x['unit'] or '')+'</td></tr>' for f in report['file_changes'] for x in f['object_changes'])
    quality=''.join('<tr><td>'+e(x['check_id'])+'</td><td>'+e(', '.join(x['scope_file_keys']))+'</td><td>'+e(x['result'])+'</td><td>'+e(x['coverage'])+'</td><td>'+e(x['detail'])+'</td></tr>' for x in report['quality_checks'])
    return '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>库文件检查</title><style>body{font:15px/1.6 sans-serif;max-width:1100px;margin:2rem auto;padding:0 1rem;color:#173242}table{border-collapse:collapse;width:100%}th,td{border-bottom:1px solid #ddd;text-align:left;padding:.6rem}th{background:#eef5f3}</style><h1>库文件检查</h1><p>目标：'+e(report['target']['id'])+' · 运行：'+e(report['check_run_id'])+'</p><h2>文件变化</h2><table><tr><th>文件</th><th>来源变化</th><th>内容状态</th><th>对象变化</th></tr>'+files+'</table><h2>对象变化</h2><table><tr><th>文件</th><th>对象</th><th>属性</th><th>旧值</th><th>新值</th><th>单位</th></tr>'+objects+'</table><h2>质量检查</h2><table><tr><th>检查</th><th>范围</th><th>结果</th><th>覆盖</th><th>说明</th></tr>'+quality+'</table><p>'+e(report['evidence_note'])+'</p></html>'
