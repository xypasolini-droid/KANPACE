"""Draw a standalone, illustrated product requirements plan, not firmware UI.

Only invented sample labels/line drawings are used; no customer data is read.
Run with the bundled Python containing ReportLab and pypdfium2.
"""
from pathlib import Path
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.colors import HexColor
import pypdfium2 as pdfium

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'output/pdf'
OUT.mkdir(parents=True, exist_ok=True)
PDF = OUT / 'KANPACE-智能胸牌功能与界面规划-20260907.pdf'
pdfmetrics.registerFont(TTFont('CJK', '/System/Library/Fonts/Supplemental/Arial Unicode.ttf'))
W, H = 1320, 960
c = canvas.Canvas(str(PDF), pagesize=(W, H))
c.setTitle('KANPACE 智能胸牌功能与界面规划 · 2026-09-07')
c.setAuthor('KANPACE')
INK, MUTED, BG, LINE = '#152D36', '#567078', '#F5F7F6', '#DCE5E4'
TEAL, BLUE, AMBER = '#087F72', '#2667A8', '#AC650F'
NAVY, WHITE, LIGHT = '#102B36', '#FFFFFF', '#B9D0D5'

def rect(x, y, w, h, fill, radius=0, stroke=None, line=1):
    c.setFillColor(HexColor(fill))
    c.setStrokeColor(HexColor(stroke or fill))
    c.setLineWidth(line)
    if radius:
        c.roundRect(x, H-y-h, w, h, radius, stroke=int(bool(stroke)), fill=1)
    else:
        c.rect(x, H-y-h, w, h, stroke=int(bool(stroke)), fill=1)

def text(s, x, y, size=18, color=INK, font='CJK', align='left'):
    c.setFillColor(HexColor(color)); c.setFont(font, size)
    func = c.drawRightString if align == 'right' else c.drawCentredString if align == 'center' else c.drawString
    func(x, H-y, s)

def line(x1, y1, x2, y2, color=LINE, width=1):
    c.setStrokeColor(HexColor(color)); c.setLineWidth(width)
    c.line(x1, H-y1, x2, H-y2)

def paragraph(s, x, y, width, size=17, leading=28, color=MUTED):
    buf=''
    for ch in s:
        if ch=='\n' or pdfmetrics.stringWidth(buf+ch, 'CJK', size)>width:
            text(buf, x, y, size, color); y+=leading; buf='' if ch=='\n' else ch
        else: buf+=ch
    if buf: text(buf, x, y, size, color); y+=leading
    return y

def page(number, title, subtitle):
    rect(0,0,W,H,BG)
    text('KANPACE  /  产品方案',56,42,15,TEAL)
    text('2026.09.07',W-56,42,15,MUTED,align='right')
    text(title,56,96,34)
    text(subtitle,56,132,18,MUTED)
    line(56,909,W-56,909)
    text('界面规划示意，非实机照片；示例尺寸与图形不用于生产。',56,936,14,MUTED)
    text(f'{number} / 3',W-56,936,15,MUTED,align='right')

def wifi(ox, oy, scale):
    c.setStrokeColor(HexColor(WHITE)); c.setLineWidth(1.4*scale)
    for r in (8,5):
        c.arc(ox-r*scale, H-(oy+r*scale), ox+r*scale, H-(oy-r*scale), 42, 96)
    c.setFillColor(HexColor(WHITE)); c.circle(ox,H-(oy+4*scale),1.2*scale,stroke=0,fill=1)

def phone(x,y,kind):
    S=1.4
    rect(x-12,y-21,170*S+24,320*S+42,'#D9E2E2',25)
    rect(x-7,y-16,170*S+14,320*S+32,'#18343E',22)
    rect(x,y,170*S,320*S,NAVY,12)
    def r(a,b,w,h,col,rad=5): rect(x+a*S,y+b*S,w*S,h*S,col,rad*S)
    def t(s,a,b,sz=12,col=WHITE,align='left'): text(s,x+a*S,y+b*S,sz*S,col,align=align)
    def l(a,b,d,e,col=LIGHT,wd=.6): line(x+a*S,y+b*S,x+d*S,y+e*S,col,wd*S)
    def button(s,a,b,w=146,h=34,col='#244652',fg=WHITE):
        r(a,b,w,h,col); t(s,a+w/2,b+h/2+4,12,fg,'center')
    wifi(x+151*S,y+15*S,S)
    if kind=='home':
        t('木工 · 张师傅',12,24,11)
        l(12,34,158,34,'#35515A')
        t('珠宝店 · A01 高柜',12,53,11,LIGHT)
        t('柜体侧板',12,81,20)
        t('铣槽、钻孔、封边',12,106,14,'#FFDD8C')
        t('18mm 板 / 图纸 Rev.C',12,128,10,LIGHT)
        t('已做 7 / 共 18 件',12,155,15)
        r(12,167,146,5,'#2D4951',2);r(12,167,57,5,'#68D3B1',2)
        button('看图',12,187,70,37)
        button('报数量',88,187,70,37)
        button('暂停 / 换任务',12,235,146,34,'#534333','#FFE0A5')
        button('完成任务',12,279,146,30,'#127E70')
    elif kind=='drawing':
        t('任务图册',12,24,12)
        button('施工图',12,42,70,31,'#E6F2F0',INK)
        button('效果图',88,42,70,31)
        t('柜体侧板 · Rev.C',12,95,11,LIGHT)
        r(12,108,146,133,'#FFFFFF',3)
        # Original engineering line schematic. Not a customer drawing/render.
        a,b=x+12*S,y+108*S
        def dl(u,v,p,q,co='#2D4149',wd=.7):line(a+u*S,b+v*S,a+p*S,b+q*S,co,wd*S)
        dl(35,28,110,28);dl(110,28,110,107);dl(110,107,35,107);dl(35,107,35,28)
        dl(40,34,105,34);dl(40,34,40,100);dl(105,34,105,100)
        for yy in (45,76,93):
            for xx in (46,99):
                c.setStrokeColor(HexColor('#2D4149'));c.setLineWidth(.6*S)
                c.circle(a+xx*S,H-(b+yy*S),1.3*S,fill=0,stroke=1)
        dl(35,20,110,20);dl(35,17,35,24);dl(110,17,110,24)
        text('560',a+72*S,b+16*S,8*S,INK,align='center')
        dl(25,28,25,107);dl(21,28,29,28);dl(21,107,29,107)
        c.saveState();c.translate(a+18*S,H-(b+88*S));c.rotate(90)
        c.setFont('CJK',8*S);c.setFillColor(HexColor(INK));c.drawString(0,0,'1150');c.restoreState()
        text('18mm',a+76*S,b+122*S,8*S,INK,align='center')
        button('－',12,253,43,29);t('1×',85,274,12,LIGHT,'center');button('＋',115,253,43,29)
        button('返回任务',12,291,146,22)
    else:
        t('暂停任务',12,24,12)
        t('这件先停一下',12,57,17)
        t('选一个原因',12,80,11,LIGHT)
        button('✓ 缺少物料',12,98,146,36,'#E6F2F0',INK)
        button('设备 / 质量问题',12,143,146,36)
        button('急单优先',12,188,146,36)
        t('已做 7 件，保留当前进度',12,247,10,LIGHT)
        button('暂停并选下一单',12,267,146,36,'#127E70')
    return y+448

page(1,'智能胸牌：工作只围绕一个任务','常驻任务首页，按需打开图纸和操作；无线状态只用图标，状态变化才给简短提示。')
columns=[(56,'01','我现在做什么','home'),(460,'02','这件应该怎么做','drawing'),(864,'03','做不了，先做下一件','pause')]
for left,num,title,kind in columns:
    text(num,left,188,16,TEAL,font='Helvetica-Bold')
    text(title,left+38,188,23)
    phone(left+66,222,kind)
    if kind=='home':
        text('一眼看到：部件、工序、数量',left,730,21)
        paragraph('图纸与操作放在手边；开工、恢复和完成按任务状态替换主按钮。',left,765,350,18,29)
        rect(left,837,344,41,'#EAF1FC',7)
        text('新增重点：板端输入分批完成数量',left+13,864,17,BLUE)
    elif kind=='drawing':
        text('施工图做依据，效果图看整体',left,730,21)
        paragraph('先呈现本工序局部，再放大查看。任务、构件、图纸版本始终对应。',left,765,350,18,29)
        rect(left,837,344,41,'#E7F3EF',7)
        text('已有 USB 双图；局部定位待完善',left+13,864,17,TEAL)
    else:
        text('先交接，再换单，之后能接着做',left,730,21)
        paragraph('保存已做数量和停工原因；只选本人的可开工任务，恢复时看剩余量。',left,765,350,18,29)
        rect(left,837,344,41,'#EAF1FC',7)
        text('新增重点：任务列表与板端换单',left+13,864,17,BLUE)
c.showPage()

page(2,'首发需要的 12 项能力','“已有”表示源码中具备；实板验证范围另列。目标是减少找人、找图、漏报和返工。')
rows=[
('任务清楚','项目、构件、工序、数量、交接要点；长内容按需展开。','已有任务首页','完善长名称与重点层级'),
('图纸对应','施工图局部 + 原始效果图；图纸版本与当前任务一致。','USB 双图已有','补版本变更与局部定位'),
('大字看图','施工图 1/2/4/8 倍放大、四向移动、一键回任务。','已有缩放和平移','实测小字可读性与触摸'),
('开工与完工','开始、暂停、恢复、完成；重要动作防误触、返回业务结果。','已有流程','补真实工人连续操作验收'),
('分批报量','输入本次合格数、不良数；累计不超量，避免重复报工。','目前只显示 Web 数量','新增板端报量输入'),
('暂停与交接','缺料、设备、质量、插单等原因；保留已做量与交接说明。','已有暂停原因与保留','补责任人、处理时限'),
('换单与恢复','我的可开工任务、急单标记、选下一单、回到暂停任务。','目前由 Web 重新下发','新增板端列表与选择'),
('问题有人接','求助自动带上任务和原因；负责人接单、处理、反馈到胸牌。','尚无完整班组问题闭环','新增问题单与到人提醒'),
('无线可用','Wi-Fi 收任务、收图和报工；重连、超时、重复发送可处理。','只具备部分无线能力','补无线图册与报工链路'),
('断网不丢','动作先本地保存；恢复后补传、去重；明确待同步和失败。','USB 持久待确认队列已有','扩展离线事件及冲突处理'),
('工厂保密','绑定工厂与人员；通信认证加密；只收必要资料，换绑清理。','完整生命周期待补','新增绑定、最小缓存与擦除'),
('能戴一班','实测电量、休眠唤醒、低电提醒；升级与恢复不丢任务。','电池能力未确认；USB 升级','电源选型、续航与 OTA 评估'),
]
xs=[56,236,786,1010]
rect(56,170,1208,42,INK,5)
for xx,label in zip(xs,['工人需要','目标功能','目前情况','下一步']):text(label,xx+13,198,17,WHITE)
y=212
for i,row in enumerate(rows):
    if i%2==0:rect(56,y,1208,51,'#FFFFFF')
    text(f'{i+1:02d}  {row[0]}',69,y+31,17,INK)
    paragraph(row[1],249,y+21,514,16,22,INK)
    paragraph(row[2],799,y+21,190,15,22,MUTED)
    paragraph(row[3],1023,y+21,225,15,22,BLUE)
    line(56,y+51,1264,y+51)
    y+=51
paragraph('先完成 5、7、9、10 的现场闭环，同时补 11、12 的交付条件。相机、语音、定位和复杂 3D 不进入这块胸牌的首发必备项。',56,866,1208,18,27,TEAL)
c.showPage()

page(3,'一个胸牌，适配三种现场','把工种、步骤、验收点配置在 Web；胸牌沿用相同交互，降低培训成本。')
types=[
('展柜工厂','高柜 A01 / 柜体侧板','铣槽、钻孔、封边','板材与厚度、封边面、孔位、数量'),
('机械装配厂','设备 M03 / 主轴组件','装配、紧固、检验','零件号、装配位置、扭矩、检验点'),
('工程现场','二层 B 区 / 配电箱','安装、接线、验收','楼层区域、施工版本、前序条件'),
]
for i,(title,project,action,key) in enumerate(types):
    x=56+i*410
    rect(x,175,388,176,WHITE,10,LINE)
    rect(x,175,5,176,TEAL,2)
    text(title,x+22,211,23)
    text(project,x+22,245,18)
    text(action,x+22,278,20,TEAL)
    text(key,x+22,317,16,MUTED)
text('从图纸到现场，再用真实结果改进计划',56,398,26)
nodes=[('原始资料','图纸 / CAD / 排程表'),('本地 Web','识图 / 复核 / 排产'),('当前工人','任务 / 图纸 / 数量'),('实际反馈','报量 / 缺料 / 返工')]
for i,(title,sub) in enumerate(nodes):
    x=56+i*309
    rect(x,425,281,92,'#E8F2EF',8)
    text(title,x+20,460,21,TEAL)
    text(sub,x+20,491,16,INK)
    if i<3:
        line(x+286,471,x+302,471,TEAL,2)
        line(x+297,467,x+302,471,TEAL,2);line(x+297,475,x+302,471,TEAL,2)
line(1123,527,1123,544,TEAL,1.5);line(1123,544,506,544,TEAL,1.5)
line(506,544,506,526,TEAL,1.5);line(502,532,506,526,TEAL,1.5);line(510,532,506,526,TEAL,1.5)
text('反馈用于本厂工时、缺料与排程规则；不流入其他工厂。',659,576,18,TEAL,align='center')
line(56,602,1264,602)
text('当前硬件边界',56,640,24)
paragraph('ESP32-C3，170 × 320 屏幕、4 MB Flash。保留 USB；复杂识图、排产与模型推理在本地电脑完成。电池、震动和充电电路尚需确认；当前单应用分区不能直接提供双槽 OTA 回滚。',56,676,555,18,29)
text('交付前必须实测',704,640,24)
paragraph('断网与断电后报工不丢、不重复；错版本图纸不可误派；换单后恢复的数量正确；无线任务、图片、报工完整闭环；一班续航与工人戴手套的触摸体验。',704,676,555,18,29)
rect(56,807,1208,70,'#FFF5DF',8)
paragraph('验证说明：已有记录覆盖 1.5.2 实板 USB 双图接收、摘要、重启保留与打开图册。人工触控报工、写入中断电、长时续航和全无线联动尚不能视为已验收。',77,835,1165,17,25,AMBER)
c.showPage(); c.save()
doc=pdfium.PdfDocument(str(PDF))
for i in range(len(doc)):
    name='KANPACE-智能胸牌界面示意.png' if i==0 else f'KANPACE-智能胸牌功能规划-{i+1}.png'
    doc[i].render(scale=1.25).to_pil().save(OUT/name)
doc.close()
print(PDF)
print('Rendered 3 pages, 1650 × 1200 each.')
