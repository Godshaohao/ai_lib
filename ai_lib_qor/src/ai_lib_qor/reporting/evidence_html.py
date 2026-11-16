"""Standalone evidence preview, with source text HTML-escaped."""
import html
import json
from ai_lib_qor.facts.rich_evidence import validate_evidence


def render_evidence_html(evidence):
    validate_evidence(evidence)
    esc = lambda value: html.escape(str(value), quote=True)
    data = esc(json.dumps(evidence['data'], ensure_ascii=False, indent=2))
    return f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>解析证据</title><style>body{{max-width:1100px;margin:40px auto;padding:0 20px;font-family:sans-serif;color:#243748}}pre{{overflow:auto;background:#f2f6f8;padding:20px}}.note{{padding:14px;background:#fff4db}}code{{overflow-wrap:anywhere}}</style></head><body><h1>{esc(evidence['view'])} 解析证据</h1><p class="note">{esc(evidence['coverage_note'])}</p><p>来源：<code>{esc(evidence['source_ref'])}</code></p><p>文件 SHA-256：<code>{esc(evidence['source_sha256'])}</code></p><p>解析器：{esc(evidence['parser']['name'])} / {esc(evidence['parser']['version'])} · 覆盖：{esc(evidence['coverage'])}</p><h2>解析内容</h2><pre>{data}</pre></body></html>'''
