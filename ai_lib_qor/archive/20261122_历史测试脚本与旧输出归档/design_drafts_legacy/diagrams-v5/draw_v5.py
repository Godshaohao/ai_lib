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

# 01: architecture stages; arrows connect stage groups, not every record.
L=svg(1600,860,'01  总体框图：从输入到七类产物','v5 提议以业务产物为中心；每类产物由指定组装器或写入者发布')
for args in [(40,145,275,565,'输入与规则'),(350,145,285,565,'脚本与组装'),(670,145,535,565,'七类业务产物'),(1240,145,320,565,'查询与交付')]: frame(L,*args)
box(L,60,215,235,110,'RAW 交付',['供应商文件与交付'], '#eff6ff','#bfdbfe')
box(L,60,355,235,110,'正式 NL',['固定链接状态'], '#eff6ff','#bfdbfe')
box(L,60,495,235,110,'已确认规则',['归属、顺序与包范围'], '#eff6ff','#bfdbfe')
box(L,370,215,245,110,'发现与解析',['扫描、来源匹配、提取'], '#f0fdf4','#bbf7d0')
box(L,370,355,245,110,'专业检查',['差异、跨 View、测量'], '#f0fdf4','#bbf7d0')
box(L,370,495,245,110,'对应组装器',['校验、合并、单一发布'], '#f0fdf4','#bbf7d0')
items=[('交付记录','delivery.json'),('正式快照','snapshot.json'),('文件解析事实','file_facts.json'),('有效版本','rev_*.json'),('检查结果','run_*.json'),('采纳事件','acceptance.jsonl'),('当前索引','index.json')]
for i,(a,b) in enumerate(items):
    x=690+(i%2)*250; y=210+(i//2)*112
    box(L,x,y,230,90,a,[b],'#faf5ff','#e9d5ff')
box(L,1260,250,280,120,'可重建查询视图',['Read Model / 索引'], '#fff7ed','#fed7aa')
box(L,1260,440,280,120,'面向用户',['Web · HTML · Excel'], '#fff7ed','#fed7aa')
line(L,315,425,347,425); line(L,635,425,667,425); line(L,1205,425,1237,425); line(L,1400,370,1400,437)
text(L,50,760,'每类是一个契约类别，可以有多份记录；历史版本固定，Index 可重建。','body')
footer(L,815); save(L,'01-总体框图')

# 02: check assembly, with explicit gate dependency.
L=svg(1600,1030,'02  多个检查脚本如何汇总为一份 Run','目标、文件来源、Corner、插件版本和参数由检查计划固定')
box(L,475,135,650,105,'固定本次检查输入',['Delivery 或 Effective Revision + File Facts + Profile'], '#eff6ff','#bfdbfe')
box(L,475,300,650,95,'Planner / Input Resolver',['选择插件和锁定输入；插件不自行猜测最新文件'], '#eff6ff','#bfdbfe')
line(L,800,240,800,297)
# input fan-out bus
line(L,800,395,800,425,False); line(L,220,425,1380,425,False)
for cx in [220,606,992,1378]: line(L,cx,425,cx,457)
box(L,60,460,320,130,'内容 / Macro 差异',['DIFF：记录变化事实','本身不产生 PASS / FAIL'], '#f0fdf4','#bbf7d0')
box(L,446,460,320,130,'跨 View 检查',['QUALITY：质量检查','覆盖不足时 NOT_CHECKED'], '#f0fdf4','#bbf7d0')
box(L,832,460,320,130,'STA 测量',['MEASUREMENT：WNS 数值','记录 Corner 与来源'], '#f0fdf4','#bbf7d0')
box(L,1218,460,320,130,'QoR Gate',['EVALUATION：引用 WNS','按阈值产生 PASS / FAIL'], '#f0fdf4','#bbf7d0')
line(L,1152,525,1215,525); text(L,1160,510,'引用','small')
for cx in [220,606,992,1378]: line(L,cx,590,cx,625,False)
line(L,220,625,1378,625,False); line(L,800,625,800,667)
box(L,400,670,800,108,'Check Assembler：一个 check_id 一个命名空间',['检查目标、来源、参数、覆盖与冲突；计算汇总；发布一份 Run'], '#faf5ff','#e9d5ff')
line(L,800,778,800,817)
box(L,475,820,650,100,'run_001.json',['同一目标的一组检查与证据；已发布历史保持固定'], '#fff7ed','#fed7aa')
footer(L,990); save(L,'02-检查结果组装')

# 03: revision and acceptance are distinct decisions.
L=svg(1600,1010,'03  有效版本与采纳：两条不同的事实','来源按场景选择：RAW-only 可不依赖正式 NL；跨库成员通过固定引用关联')
box(L,50,165,420,115,'Delivery 交付记录',['这次交付实际出现的文件','未归属文件保留，不能自动采用'], '#eff6ff','#bfdbfe')
box(L,590,165,420,115,'Formal Snapshot 正式快照',['某次正式 NL 的固定链接状态','无法匹配 RAW 时仍保留正式来源'], '#eff6ff','#bfdbfe')
box(L,1130,165,420,115,'上一版 Revision',['完整成员集合与固定来源引用'], '#eff6ff','#bfdbfe')
# fan-in bus
for cx in [260,800,1340]: line(L,cx,280,cx,330,False)
line(L,260,330,1340,330,False); line(L,800,330,800,377)
box(L,470,380,660,120,'Effective Composer',['继承旧成员，应用明确可采用的变更','members 是全集；changes 是相对父版的差异'], '#f0fdf4','#bbf7d0')
line(L,800,500,800,557)
box(L,470,560,660,110,'rev_0008.json：固定有效版本',['成员没有变化则不新建 Rev；质量检查可多次运行'], '#faf5ff','#e9d5ff')
line(L,1130,615,1247,615); box(L,1250,550,300,130,'index.json',['最新计算 Rev','当前已采纳 Rev'], '#fff7ed','#fed7aa')
box(L,50,755,330,110,'人工采纳 / 回退',['明确决定与对象'], '#fff7ed','#fed7aa')
box(L,470,755,460,110,'acceptance.jsonl',['真实决策事件只追加'], '#fff7ed','#fed7aa')
line(L,380,810,467,810); path(L,'M 930 810 H 1400 V 683')
text(L,1050,780,'事件更新采纳指针','small')
footer(L,965); save(L,'03-版本与采纳')

# 04: exact synthetic values and actual statuses in packaged runs.
L=svg(1600,900,'04  增量示例：同一 Rev，检查结果可以重用','合成示例：修改阈值与新增插件，产生新 Run；固定的旧 Run 和 Rev 保留')
box(L,50,145,1500,90,'固定输入：rev_0008 + input_gen_008',['相同目标与输入代次；仅在版本、参数、来源和环境满足条件时复用'], '#eff6ff','#bfdbfe')
frame(L,50,285,650,440,'Run 001：已发布')
box(L,75,345,600,110,'STA 测量',['setup WNS = -0.08 ns'], '#f0fdf4','#bbf7d0')
box(L,75,485,600,110,'QoR Gate',['阈值 -0.10 ns  →  PASS'], '#faf5ff','#e9d5ff')
box(L,75,625,600,75,'整体：INCOMPLETE',['LEF / Liberty 未检查'], '#fff7ed','#fed7aa')
frame(L,900,285,650,440,'Run 002：新一轮检查')
box(L,925,345,600,110,'STA 测量：复用 Run 001',['setup WNS 仍为 -0.08 ns'], '#f0fdf4','#bbf7d0')
box(L,925,485,600,110,'QoR Gate：重新判定',['阈值 -0.05 ns  →  FAIL'], '#faf5ff','#e9d5ff')
box(L,925,625,600,75,'整体：FAIL',['新增 pin_count；跨 View 仍未执行'], '#fff7ed','#fed7aa')
line(L,700,400,897,400); text(L,720,385,'可追溯复用','small')
line(L,700,540,897,540); text(L,720,525,'阈值改变，重判','small')
text(L,50,785,'复用条件未满足、结果失败或不完整时，应重新执行或明确标记未检查。','body')
footer(L,850); save(L,'04-增量运行示例')

# 05: mapping as a legible grid; proposals only.
L=svg(1600,1000,'05  七类产物：谁组装、记录什么','单写入者是 v5 的设计原则；贡献脚本、临时片段和读模型不是新增的权威业务契约')
xs=[50,390,820,1160]; widths=[320,410,320,390]
for x,w,h in zip(xs,widths,['贡献来源','组装器 / 写入者','产物','主要职责']):
    L.append(f'<rect x="{x}" y="145" width="{w}" height="58" rx="8" fill="#eaf2ff"/>'); text(L,x+16,182,h,'label')
rows=[
 ('RAW 扫描 + 交付规则','Delivery Assembler','delivery.json','记录一次交付'),
 ('正式链接 + 来源匹配','Formal Snapshot Builder','snapshot.json','固定正式链接状态'),
 ('元数据 + 多个 Parser','Facts Assembler','file_facts.json','一个文件实例的事实'),
 ('前版成员 + 文件选择','Effective Composer','rev_*.json','完整成员与采用差异'),
 ('差异 / 质量 / STA 插件','Check Assembler','run_*.json','同一目标的检查集合'),
 ('人工或授权流程决定','Acceptance Writer','acceptance.jsonl','追加采纳与回退事件'),
 ('版本记录 + 采纳事件','Index Projector','index.json','可重建的当前指针')]
for i,row in enumerate(rows):
    y=220+i*90
    for j,val in enumerate(row):
        fills=['#ffffff','#f0fdf4','#faf5ff','#ffffff']
        L.append(f'<rect x="{xs[j]}" y="{y}" width="{widths[j]}" height="72" rx="7" fill="{fills[j]}" stroke="#d1d5db"/>')
        text(L,xs[j]+14,y+44,val,'body')
text(L,50,890,'备注：检查结果的 v5 示例字段与 v3 Schema 不同，实施前需要逐字段映射与兼容性审查。','body')
footer(L,955); save(L,'05-七类产物与组装器')

# 06: different extractors may contribute to a single file instance, not cross-file facts.
L=svg(1600,1010,'06  文件解析事实：多个提取器汇总同一个文件','每个 FileInstance 独立建立事实；LEF 和 Liberty 的关系放在跨 View 检查中')
box(L,70,150,860,105,'LEF 文件实例',['固定来源引用与文件实例身份'], '#eff6ff','#bfdbfe')
box(L,1040,150,490,105,'Liberty 文件实例',['独立来源，独立解析'], '#eff6ff','#bfdbfe')
line(L,500,255,500,295,False); line(L,195,295,805,295,False)
for cx in [195,500,805]: line(L,cx,295,cx,337)
box(L,70,340,250,120,'元数据提取',['来源 / 类型 / 属性'], '#f0fdf4','#bbf7d0')
box(L,375,340,250,120,'LEF Parser',['Macro / SIZE'], '#f0fdf4','#bbf7d0')
box(L,680,340,250,120,'Pin 提取',['名称 / 方向 / 几何'], '#f0fdf4','#bbf7d0')
for cx in [195,500,805]: line(L,cx,460,cx,510,False)
line(L,195,510,805,510,False); line(L,500,510,500,557)
box(L,200,560,600,110,'Facts Assembler',['按文件实例与对象键合并；字段冲突拒绝'], '#faf5ff','#e9d5ff')
line(L,500,670,500,727)
box(L,100,730,500,110,'LEF file_facts',['解析范围、对象和来源证据'], '#fff7ed','#fed7aa')
line(L,1285,255,1285,427)
box(L,1040,430,490,120,'Liberty Parser / Assembler',['Cell / Pin 等独立文件事实'], '#f0fdf4','#bbf7d0')
line(L,1285,550,1285,727)
box(L,1000,730,500,110,'Liberty file_facts',['解析范围、对象和来源证据'], '#fff7ed','#fed7aa')
box(L,680,730,240,110,'跨 View 检查',['引用两份事实'], '#faf5ff','#e9d5ff')
line(L,600,785,677,785); line(L,1000,785,923,785)
text(L,70,910,'解析器升级时生成受影响文件的新事实代次；未提取的范围不能当作已验证。','body')
footer(L,975); save(L,'06-文件事实组装')
