"""Export the generated diagram as a printable PDF and a complete PNG.

Uses the bundled reportlab / pypdfium2 runtime. No customer data is read.
"""
from pathlib import Path
import re
import xml.etree.ElementTree as ET
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.colors import HexColor
import pypdfium2 as pdfium

root = Path(__file__).resolve().parents[1]
svg = root / 'static/navigation-map/KANPACE-全部功能地图.svg'
tree = ET.parse(svg).getroot()
width, height = float(tree.attrib['width']), float(tree.attrib['height'])
font = '/System/Library/Fonts/Supplemental/Arial Unicode.ttf'
pdfmetrics.registerFont(TTFont('MenuCJK', font))
out = svg.with_suffix('.pdf')
c = canvas.Canvas(str(out), pagesize=(width, height))
c.setTitle('KANPACE 全部功能地图')
c.setFillColor(HexColor('#ffffff'))
c.rect(0, 0, width, height, fill=1, stroke=0)
for e in tree.iter():
    kind = e.tag.rsplit('}', 1)[-1]
    if kind == 'text':
        c.setFillColor(HexColor(e.get('fill', '#202935')))
        c.setFont('MenuCJK', float(e.get('font-size', '20')))
        c.drawString(float(e.get('x', 0)), height-float(e.get('y', 0)), ''.join(e.itertext()))
    elif kind == 'path':
        values = re.fullmatch(r'M([\d.]+) ([\d.]+)H([\d.]+)V([\d.]+)', e.get('d', ''))
        if values:
            x1, y1, x2, y2 = map(float, values.groups())
            c.setStrokeColor(HexColor(e.get('stroke', '#b7c0cc')))
            c.setLineWidth(float(e.get('stroke-width', '1.5')))
            c.line(x1, height-y1, x2, height-y1)
            c.line(x2, height-y1, x2, height-y2)
c.showPage()
c.save()
doc = pdfium.PdfDocument(str(out))
doc[0].render(scale=1).to_pil().save(svg.with_suffix('.png'))
doc.close()
print(f'Diagram exported: {int(width)} × {int(height)}; PNG and PDF')
