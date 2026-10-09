#!/usr/bin/env python3
"""Development-only generator for the checked-in synthetic PNGs.

Requires Pillow and a Chinese system font on the developer's computer. The
portable demo copies the generated files and never imports this module.
Every illustrated object and measurement comes from the built-in seed or the
public synthetic samples. No customer files, database, or CAD files are read.
"""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parent
FONT = '/System/Library/Fonts/STHeiti Light.ttc'
BOLD = '/System/Library/Fonts/STHeiti Medium.ttc'
S = 2
INK = '#183b3c'
TEAL = '#16635d'
MUTED = '#697c79'
GOLD = '#b39965'


def canvas(title, subtitle):
    im = Image.new('RGB', (1600*S, 1000*S), '#f5f4ef')
    d = ImageDraw.Draw(im)
    return im, d


def font(size, bold=False):
    return ImageFont.truetype(BOLD if bold else FONT, size*S)


def text(d, xy, value, size=24, fill=INK, bold=False):
    d.text((xy[0]*S, xy[1]*S), value, font=font(size, bold), fill=fill)


def line(d, pts, fill=INK, width=2):
    d.line([(x*S, y*S) for x,y in pts], fill=fill, width=width*S)


def poly(d, pts, fill, outline=None):
    d.polygon([(x*S, y*S) for x,y in pts], fill=fill)
    if outline:
        line(d, pts+[pts[0]], outline, 2)


def rect(d, box, fill, outline=None, radius=0):
    d.rounded_rectangle(tuple(v*S for v in box), radius=radius*S, fill=fill, outline=outline, width=2*S)


def heading(d, title, subtitle, sheet):
    text(d, (65, 46), 'KANPACE  /  柜序', 25, bold=True)
    rect(d, (1320, 39, 1535, 91), '#e6ded0', radius=25)
    text(d, (1354, 49), '合成演示', 28, bold=True)
    text(d, (65, 122), title, 42, bold=True)
    text(d, (65, 182), subtitle, 23, MUTED)
    line(d, [(65, 227), (1535, 227)], '#d7ddd6', 1)
    line(d, [(65, 908), (1535, 908)], '#d7ddd6', 1)
    text(d, (65, 933), '合成演示 · 非真实订单 · 未经工程校核 · 不可用于加工', 24, TEAL, True)
    text(d, (1340, 936), sheet, 19, MUTED)


def render(name, title, seed):
    im,d = canvas(title, '')
    heading(d, title, '效果示意 / 木作、五金、玻璃与灯光的组合表达', 'DEMO / 01')
    # An intentionally illustrated scene, not photorealistic evidence.
    rect(d, (66, 260, 1093, 870), '#ecece4', radius=18)
    poly(d, [(123,740),(687,844),(1011,696),(503,601)], '#d2d6ca')
    # The cabinet's front, side, upper frame and metal base.
    poly(d, [(212,456),(746,552),(746,774),(212,674)], '#e8e4da', '#87998c')
    poly(d, [(746,552),(948,433),(948,649),(746,774)], '#cdc7b9', '#87998c')
    poly(d, [(212,674),(746,774),(948,649),(948,669),(746,797),(212,694)], '#b8ac8e', '#928774')
    poly(d, [(212,456),(411,340),(948,433),(746,552)], '#f2ead4', GOLD)
    # Glass enclosure with visible edges and a white reflection.
    poly(d, [(212,333),(746,429),(746,552),(212,456)], '#d9e7dd', '#6a9a93')
    poly(d, [(746,429),(948,310),(948,433),(746,552)], '#c8ded6', '#6a9a93')
    poly(d, [(212,333),(411,217+70),(948,310),(746,429)], '#e7eeea', '#6a9a93')
    # LED lines, the metal lip, and a clean cupboard seam.
    line(d, [(239,449),(742,539),(926,430)], '#fff6c6', 8)
    line(d, [(212,456),(746,552),(948,433)], GOLD, 5)
    line(d, [(480,504),(480,724)], '#adae9f', 2)
    line(d, [(450,572),(450,612)], '#8c8e79', 4)
    line(d, [(509,583),(509,623)], '#8c8e79', 4)
    line(d, [(250,345),(330,359)], '#ffffff', 5)
    line(d, [(271,368),(449,400)], '#ffffff', 3)
    # Generic blank display blocks: no customer jewelry or brand assets.
    poly(d, [(339,426),(429,442),(482,411),(392,395)], '#b7bcad')
    poly(d, [(543,462),(633,478),(686,447),(596,431)], '#b7bcad')
    poly(d, [(339,417),(429,433),(482,402),(392,386)], '#faf8ef')
    poly(d, [(543,453),(633,469),(686,438),(596,422)], '#faf8ef')
    text(d, (1150, 280), '四类工种，一张订单', 26, bold=True)
    notes = [('01 木作', '夹板柜体与饰面'), ('02 五金', '金属包边 / 底座与连接件'),
             ('03 玻璃', '玻璃构件及磨边工序'), ('04 灯光', '灯带安装与电气检查')]
    for i,(a,b) in enumerate(notes):
        y=355+i*105
        text(d,(1150,y),a,24,TEAL,True)
        text(d,(1150,y+38),b,20,MUTED)
    text(d,(1150,806),'外观表达，不承担尺寸依据',19,MUTED)
    text(d,(95,823),'概念构图 · 材质与装配关系仅作软件体验',21,MUTED)
    im.resize((1600,1000), Image.Resampling.LANCZOS).save(OUT/name, optimize=True)


def dim(d, a, b, label, vertical=False):
    line(d,[a,b],TEAL,1)
    if vertical:
        for x,y in (a,b): line(d,[(x-7,y-7),(x+7,y+7)],TEAL,2)
        text(d,(a[0]-90,(a[1]+b[1])/2-15),label,20,TEAL)
    else:
        for x,y in (a,b): line(d,[(x-7,y+7),(x+7,y-7)],TEAL,2)
        text(d,((a[0]+b[0])/2-40,a[1]-33),label,21,TEAL)


def drawing(name, title, seed):
    im,d=canvas(title,'')
    heading(d,title,'施工示意 / 只展示资料关联；不构成施工或下料批准', 'DEMO / 02')
    rect(d,(65,260,910,872),'#ffffff',outline='#d7ddd6',radius=12)
    text(d,(97,287),'正面关系示意',25,bold=True)
    text(d,(97,325),'示意不按比例',19,MUTED)
    # Show a cabinet front with LED above wood body, two shelves, and base.
    rect(d,(235,427,776,743),'#f9f8f3',outline=INK)
    rect(d,(235,379,776,427),'#e6efeb',outline=TEAL)
    rect(d,(249,443,762,718),'#ffffff',outline=INK)
    line(d,[(505,443),(505,718)],INK)
    line(d,[(251,539),(760,539)],'#81a499',4)
    line(d,[(251,626),(760,626)],'#81a499',4)
    line(d,[(258,449),(752,449)],GOLD,5)
    rect(d,(235,743,776,763),'#d3cebc',outline=INK)
    for x in (276,723):
        for y in (539,626): rect(d,(x-4,y-3,x+4,y+7),TEAL)
    line(d,[(235,372),(235,354)],TEAL,1)
    line(d,[(776,372),(776,354)],TEAL,1)
    dim(d,(235,363),(776,363),'1500' if seed else '1200')
    text(d,(350,786),'毫米 mm / 数值仅来自合成清单',20,MUTED)
    line(d,[(782,414),(833,414),(833,393)],TEAL,1)
    text(d,(798,365),'玻璃',18,TEAL)
    line(d,[(780,450),(832,475)],GOLD,1)
    text(d,(792,486),'灯带',18,TEAL)
    line(d,[(231,582),(164,582)],TEAL,1)
    text(d,(111,548),'木作',18,TEAL)
    line(d,[(781,753),(821,753),(821,725)],TEAL,1)
    text(d,(788,695),'五金',18,TEAL)
    text(d,(97,835),'罩体/层板画法是说明性表达，勿从视图数量推算用量。',18,MUTED)
    text(d,(962,279),'清单中的已知字段',27,bold=True)
    rows = [
        ('柜体侧板','1100 × 580 × 18 mm / 2 件'),
        ('柜底板','1464 × 580 × 18 mm / 1 件'),
        ('不锈钢包边','1500 × 80 × 1.2 mm / 2 件'),
        ('玻璃构件','1500 × 600 × 8 mm / 1 件'),
        ('灯带','1500 × 10 × 5 mm / 2 件'),
        ('缓冲铰链','80 × 40 × 2 mm / 4 件'),
    ] if seed else [
        ('柜体侧板','900 × 450 × 18 mm / 2 件'),
        ('顶底板 / 背板','1164 × 450 × 18 / 1164 × 864 × 9'),
        ('金属底座','1200 × 450 × 2 mm / 1 件'),
        ('玻璃层板','1128 × 410 × 8 mm / 2 件'),
        ('灯条 / 电源','1100 mm 灯条 2 条 / 24V 60W 1 个'),
        ('层板托','不锈钢 / 8 件'),
    ]
    for i,(a,b) in enumerate(rows):
        y=345+i*71
        text(d,(965,y),a,21,TEAL,True)
        text(d,(965,y+30),b,18,MUTED)
    rect(d,(956,789,1535,869),'#ebe6d9',radius=8)
    text(d,(976,805),'缺少工程确认：孔位、连接、电气布线、安装公差',18,INK)
    text(d,(976,837),'演示中的审核/发布状态仅用于体验软件流程。',18,INK)
    im.resize((1600,1000), Image.Resampling.LANCZOS).save(OUT/name,optimize=True)


if __name__=='__main__':
    render('showcase-render.png','璞玉 · 珠宝中岛展示柜',True)
    drawing('showcase-drawing.png','璞玉 · 展柜构件与施工示意',True)
    render('sample-render.png','澄光 · 组合展示柜',False)
    drawing('sample-drawing.png','澄光 · 展柜清单与施工示意',False)
