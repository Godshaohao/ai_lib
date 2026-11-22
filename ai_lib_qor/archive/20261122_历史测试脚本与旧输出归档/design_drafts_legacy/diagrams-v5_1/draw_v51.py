from pathlib import Path
from html import escape
import cairosvg

OUT = Path(__file__).parent
BLUE='#2563eb'; GREEN='#16a34a'; PURPLE='#9333ea'; DARK='#111827'; MUTED='#64748b'

def svg(w,h,title,subtitle):
    lines=[f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">']
    lines.append('<defs><marker id="arrow" markerWidth="10" markerHeight="8" refX="9" refY="4" orient="auto"><path d="M 0 0 L 10 4 L 0 8 z" fill="#2563eb"/></marker></defs>')
    lines.append('<style>text {font-family: "Noto Sans CJK SC", sans-serif;} .title{font-size:31px;font-weight:700;fill:#111827}.sub{font-size:17px;fill:#64748b}.label{font-size:21px;font-weight:700;fill:#111827}.body{font-size:17px;fill:#475569}.small{font-size:15px;fill:#64748b}.tiny{font-size:14px;fill:#64748b}</style>')
    lines.append(f'<rect width="{w}" height="{h}" fill="#ffffff"/>')
    text(lines,50,58,title,'title'); text(lines,50,95,subtitle,'sub')
    return lines

def text(L,x,y,s,cl='body',anchor=None):
    a=f' text-anchor="{anchor}"' if anchor else ''
    L.append(f'<text x="{x}" y="{y}" class="{cl}"{a}>{escape(s)}</text>')

def box(L,x,y,w,h,title,subs=(),fill='#ffffff',stroke='#d1d5db'):
    L.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="10" fill="{fill}" stroke="{stroke}" stroke-width="1.5"/>')
    text(L,x+18,y+32,title,'label')
    for i,s in enumerate(subs): text(L,x+18,y+60+i*24,s,'body')

def frame(L,x,y,w,h,title):
    L.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="14" fill="#ffffff" stroke="#cbd5e1" stroke-width="1.5" stroke-dasharray="7 6"/>')
    text(L,x+18,y+32,title,'label')

def line(L,x1,y1,x2,y2,arrow=True,color=BLUE,dash=None):
    mark=' marker-end="url(#arrow)"' if arrow else ''
    ds=f' stroke-dasharray="{dash}"' if dash else ''
    L.append(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{color}" stroke-width="2"{ds}{mark}/>')

def path(L,d,arrow=True,color=BLUE,dash=None):
    mark=' marker-end="url(#arrow)"' if arrow else ''
    ds=f' stroke-dasharray="{dash}"' if dash else ''
    L.append(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="2"{ds}{mark}/>')

def footer(L,y,s='依据：v5 Architecture 文档与合成示例  |  状态：设计讨论稿；并非生产系统运行图'):
    text(L,50,y,s,'small')

def save(L,name):
    L.append('</svg>')
    p=OUT/(name+'.svg'); p.write_text('\n'.join(L),encoding='utf-8')
    cairosvg.svg2png(url=str(p),write_to=str(OUT/(name+'.png')),scale=1.5)


note='依据：v5.1 补充文档、原型代码和现有 src_qor；区分现状与方案'
# Existing capabilities, not a claim that every box is a single pipeline.
L=svg(1600,930,'01  现有 src_qor：主要脚本如何分布','基于已有仓库与 README 梳理；每条流程可独立选择，正式 NL 不等于已采纳版本')
for a in [(40,145,350,590,'输入与选择'),(420,145,370,590,'发现与文件视图'),(820,145,360,590,'检查与证据'),(1210,145,350,590,'结果与查看')]: frame(L,*a)
box(L,60,220,310,100,'RAW 目录 / 登记',['Vendor / Library / 交付'], '#eff6ff','#bfdbfe')
box(L,60,360,310,100,'正式 NL / 清单',['链接目标与来源线索'], '#eff6ff','#bfdbfe')
box(L,60,500,310,100,'人工选择',['版本、文件与检查项'], '#eff6ff','#bfdbfe')
box(L,440,215,330,110,'raw_discovery.py',['RAW 发现与登记候选'], '#f0fdf4','#bbf7d0')
box(L,440,365,330,110,'ip_file_history.py',['名单、正式清单与 RAW'], '#f0fdf4','#bbf7d0')
box(L,440,515,330,110,'file_version_projection.py',['文件出现历史与来源视图'], '#f0fdf4','#bbf7d0')
box(L,840,215,320,110,'content_compare.py',['选定文件的内容比较'], '#faf5ff','#e9d5ff')
box(L,840,365,320,110,'lef_review.py',['LEF Macro / Pin 差异'], '#faf5ff','#e9d5ff')
box(L,840,515,320,110,'lef_liberty_check.py',['选定文件跨 View 检查'], '#faf5ff','#e9d5ff')
box(L,1230,215,310,110,'review_runner.py',['组织已选择的检查'], '#fff7ed','#fed7aa')
box(L,1230,365,310,110,'Review 结果 / Excel',['review_result 与工作簿'], '#fff7ed','#fed7aa')
box(L,1230,515,310,110,'workbench.py',['配置、运行与查看'], '#fff7ed','#fed7aa')
line(L,390,440,417,440); line(L,790,440,817,440); line(L,1180,440,1207,440)
text(L,50,790,'阶段箭头表达主要信息流；现有工作台、内容比较与 Review Runner 不是单一强制串行链。','body')
footer(L,870,note+'  |  来源：src_qor/README.md'); save(L,'01-现有脚本分布')

# v5.1 proposed flow, preserve status boundaries.
L=svg(1600,1010,'02  v5.1 建议：一次检查如何形成正式结果','蓝色为输入，绿色为计划与现有算法，紫色为拟新增处理；目前未证明已端到端接通')
box(L,425,135,750,100,'固定目标与输入',['已确认的 Delivery / Snapshot / Rev / File Facts'], '#eff6ff','#bfdbfe')
line(L,800,235,800,273)
box(L,425,275,750,95,'准备输入 + Check Plan',['明确文件、Corner、检查项与参数'], '#f0fdf4','#bbf7d0')
line(L,800,370,800,405,False);line(L,250,405,1350,405,False)
for cx in [250,800,1350]: line(L,cx,405,cx,437)
box(L,70,440,360,100,'content_compare',['文件正文比较'], '#f0fdf4','#bbf7d0')
box(L,620,440,360,100,'lef_review',['LEF Macro / Pin 差异'], '#f0fdf4','#bbf7d0')
box(L,1170,440,360,100,'lef_liberty_check',['跨 View 质量检查','绑定对应 LEF 证据'], '#f0fdf4','#bbf7d0')
for cx in [250,800,1350]:line(L,cx,540,cx,570,False)
line(L,250,570,1350,570,False);line(L,800,570,800,600)
box(L,250,603,1100,95,'Contribution：内存或暂存中的检查贡献',['统一目标、来源、覆盖范围和证据；不是新的正式业务契约'], '#faf5ff','#e9d5ff')
line(L,300,698,300,725)
box(L,70,728,455,110,'证据与来源门禁',['拟与真实可信登记对接','当前仅有独立演示原型'], '#faf5ff','#e9d5ff')
box(L,575,728,450,110,'v3 合并器 + Schema 校验',['字段映射、聚合、校验','尚待实现及真实数据验证'], '#faf5ff','#e9d5ff')
box(L,1075,728,455,110,'发布并提供读取',['check_result.v1 → HTML / Excel','发布失败不更新正式入口'], '#fff7ed','#fed7aa')
line(L,525,783,572,783);line(L,1025,783,1072,783)
footer(L,955,note+'  |  状态：目标流程，非生产调用链');save(L,'02-v5_1目标流程')

# Evidence guard scope vs intended.
L=svg(1600,920,'03  证据门禁：现有原型覆盖到哪里','原型验证 v5 合成 Run 的引用和摘要；正式 v3 组装、覆盖语义和真实来源接入仍待实现')
frame(L,50,150,700,585,'补充包已有：evidence_guard.py')
box(L,80,215,640,100,'输入',['v5 fixture Run + manifest + fixture 文件'], '#eff6ff','#bfdbfe')
box(L,80,350,640,145,'已演示的检查',['完成项需要输入引用及证据','来源路径须在指定目录内，SHA256 须匹配','默认拒绝 REUSED；Gate 有基本依赖检查'], '#f0fdf4','#bbf7d0')
box(L,80,535,640,120,'局限',['未接正式数据生产者与 v3 合并器','不证明文件内容是有效 Parser 结果'], '#fff7ed','#fed7aa')
line(L,400,315,400,347);line(L,400,495,400,532)
frame(L,850,150,700,585,'目标发布流程：仍待实现')
box(L,880,215,640,105,'可信输入与执行证据',['确认文件身份、上下文与关联关系'], '#eff6ff','#bfdbfe')
box(L,880,355,640,130,'检查结论和覆盖',['映射 v3 状态；无证据或覆盖不足不能 PASS','校验 Gate 的测量依赖与计算上下文'], '#faf5ff','#e9d5ff')
box(L,880,525,640,130,'v3 Schema + 发布',['字段映射、结构和业务校验通过后发布','失败保留旧结果'], '#fff7ed','#fed7aa')
line(L,1200,320,1200,352);line(L,1200,485,1200,522)
text(L,50,790,'复核发现：用普通文件引用替代 Gate 的测量引用，同时伪造不存在的依赖，原型仍会通过。','body')
footer(L,865,note+'  |  测试边界：合成夹具');save(L,'03-证据门禁边界')

# Table of real files, proposal deliberately named.
L=svg(1600,990,'04  文件结构与脚本分布','左列为职责，中列是已存在的文件，右列是 v5.1 提案中的拟新增模块')
xs=[45,350,1000]; ws=[285,630,550]
for x,w,t in zip(xs,ws,['职责','已存在：repo/src_qor 或补充包','建议：src_qor_next（未实现）']):
 L.append(f'<rect x="{x}" y="145" width="{w}" height="58" rx="8" fill="#eaf2ff"/>');text(L,x+15,183,t,'label')
rows=[('发现 / 来源','raw_discovery.py；ip_file_history.py','runner/prepare_inputs.py'),('版本 / 文件视图','current_library_set.py；file_version_projection.py','复用既有选择；确认输入身份'),('文件检查','content_compare.py；lef_review.py','adapters/lef_compare.py'),('跨 View 检查','lef_liberty_check.py','adapters/lef_liberty.py'),('汇总 / 证据','review_runner.py；v5.1 evidence_guard.py 原型','runner/assemble_check_result.py'),('输出 / 交互','workbench.py；export_review_excel.py','presentation/report_data.py 等'),('合同 / 测试','v3 schemas；v5.1 test_evidence_guard.py','contracts/；真实输入回归用例')]
for i,row in enumerate(rows):
 y=220+i*90
 for j,val in enumerate(row):
  fills=['#ffffff','#f0fdf4','#faf5ff'];L.append(f'<rect x="{xs[j]}" y="{y}" width="{ws[j]}" height="72" rx="7" fill="{fills[j]}" stroke="#d1d5db"/>');text(L,xs[j]+14,y+44,val,'body')
text(L,50,890,'说明：提案目录只是职责草图，不代表应复制现有 Runner 或一次性建立全部文件。','body')
footer(L,955,note);save(L,'04-文件与脚本分布')
