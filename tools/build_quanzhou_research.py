"""Build a local, read-only industry research artifact; does not install workflows."""
from pathlib import Path
import html
import json
import re
import shutil

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / 'static/industry-map'
DOCS = ROOT / 'docs/product'


def inline(text):
    text = html.escape(text)
    text = re.sub(r'\[([^\]]+)\]\((https?://[^\s)]+)\)', r'<a href="\2" target="_blank" rel="noopener noreferrer">\1</a>', text)
    text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
    return re.sub(r'`([^`]+)`', r'<code>\1</code>', text)


def markdown(text):
    # The source uses only headings, prose, flat lists, tables and fenced diagrams.
    lines = text.splitlines()
    out, i = [], 0
    while i < len(lines):
        line = lines[i].strip()
        if not line:
            i += 1
            continue
        if line.startswith('```'):
            chunk = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith('```'):
                chunk.append(lines[i])
                i += 1
            out.append('<pre>' + html.escape('\n'.join(chunk)) + '</pre>')
            i += 1
            continue
        if line.startswith('|'):
            rows = []
            while i < len(lines) and lines[i].strip().startswith('|'):
                cells = [c.strip() for c in lines[i].strip().strip('|').split('|')]
                if not all(re.fullmatch(r'[:\- ]+', c or '-') for c in cells):
                    rows.append(cells)
                i += 1
            header, *body = rows
            out.append('<div class="table-wrap"><table><thead><tr>' + ''.join('<th>' + inline(c) + '</th>' for c in header) + '</tr></thead><tbody>' + ''.join('<tr>' + ''.join('<td>' + inline(c) + '</td>' for c in row) + '</tr>' for row in body) + '</tbody></table></div>')
            continue
        match = re.match(r'^(#{1,6}) (.*)', line)
        if match:
            level = min(4, max(2, len(match[1])))
            out.append(f'<h{level}>' + inline(match[2]) + f'</h{level}>')
            i += 1
            continue
        if re.match(r'^(?:- |\d+\. )', line):
            ordered = bool(re.match(r'^\d+\.', line))
            tag = 'ol' if ordered else 'ul'
            items = []
            pattern = r'^\d+\. ' if ordered else r'^- '
            while i < len(lines) and re.match(pattern, lines[i].strip()):
                items.append('<li>' + inline(re.sub(pattern, '', lines[i].strip())) + '</li>')
                i += 1
            out.append(f'<{tag}>' + ''.join(items) + f'</{tag}>')
            continue
        paragraph = [line]
        i += 1
        while i < len(lines) and lines[i].strip() and not re.match(r'^(?:#|\||```|- |\d+\. )', lines[i].strip()):
            paragraph.append(lines[i].strip())
            i += 1
        out.append('<p>' + inline(' '.join(paragraph)) + '</p>')
    return '\n'.join(out)


def main():
    data = json.loads((DOCS / 'quanzhou-industries-20260907.json').read_text())
    assert len(data) == len({d['id'] for d in data}) == 19
    for item in data:
        assert item['flow'] and item['sources']
        for source in item['sources']:
            assert source['url'].startswith('https://')
    report = (DOCS / '泉州产业业务链与KANPACE中台规划-20260907.md').read_text()
    evidence = '\n\n'.join((DOCS / name).read_text() for name in ['20260907-泉州链路-装备建材电子.md', '20260907-泉州链路-鞋服食品纸品.md', '20260907-泉州链路-工艺流程制造.md'])
    options = ''.join(f'<option value="{html.escape(d["id"])}">{html.escape(d["name"])} · {html.escape(d["area"])}</option>' for d in data)
    page = (DEST / 'index.template.html').read_text().replace('__OPTIONS__', options).replace('__REPORT__', markdown(report)).replace('__EVIDENCE__', markdown(evidence)).replace('__DATA__', json.dumps(data, ensure_ascii=False).replace('<', '\\u003c'))
    assert '__REPORT__' not in page and '__DATA__' not in page
    (DEST / 'index.html').write_text(page)
    shutil.copyfile(ROOT / 'static/brand/KANPACE-Handoff-Black.svg', DEST / 'brand.svg')
    (DEST / 'report.md').write_text(report + '\n\n---\n\n' + evidence)
    (DEST / 'industries.json').write_text(json.dumps(data, ensure_ascii=False, indent=2))
    shutil.copyfile(DOCS / '20260907-CAD资料与工程依据.md', DEST / 'source-audit.md')
    shutil.copyfile(DOCS / '20260907-工厂配置中台审计.md', DEST / 'platform-audit.md')
    print(f'Built {DEST / "index.html"}: {len(data)} scenes, {len(page.encode())} bytes')


if __name__ == '__main__':
    main()
