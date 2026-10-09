"""Local, evidence-first order packets from Excel and exported engineering PDFs.

Uses Python's standard library for OOXML and the existing Poppler installation
for PDF text. Never interprets SolidWorks geometry, executes workbook formulas,
or promotes suggestions to released manufacturing instructions.
"""
from __future__ import annotations
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import posixpath
import re
import subprocess
import unicodedata
import xml.etree.ElementTree as ET
import zipfile

from kanpace.core.errors import APIError
from kanpace.core.validation import now, uid
from upload_preview import executable, preview_pdf

VERSION = 'order-packet-v5'
SHEET_NS = {'m': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
REL_NS = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id'
TRADES = [('木工', r'高密度板|密度板|木制|木质|木作|木工|免漆板|包布板|软包板|多层板|胶合板|刨花板|实木|木板', '木作件加工'),
          ('五金', r'不锈钢|冷轧|铁件|铁管|钢管|钢板|钢架|方管|金属|焊件|焊接|剪折|折弯|五金|金工|钣金', '五金件加工'),
          ('玻璃', r'玻璃|镜片|银镜|水银镜|防水镜', '玻璃与镜片加工'),
          ('油漆', r'烤漆|油漆|喷漆|喷涂|开放漆|底漆|面漆', '油漆与表面处理'),
          ('电工', r'LED|灯带|灯条|发光|电源|接线|灯箱|灯具|内打灯', '灯光与电气安装')]

HANDOFF_ROWS = {'包装要求': 'packaging', '包装说明': 'packaging', '装箱要求': 'packaging',
                '发货要求': 'delivery', '运输要求': 'delivery'}


def _handoff_kind(item):
    """An explicit instruction row is not a cabinet or a purchased component."""
    name = re.sub(r'\s+', '', item['name'])
    if name in HANDOFF_ROWS and not item['overall_dimensions'] and item['quantity_unit'] in ('项', '条', '份', ''):
        return HANDOFF_ROWS[name]
    return None

def relative_path(value, filename):
    value = value or filename
    if not isinstance(value, str) or len(value) > 1600:
        raise APIError(400, '文件相对路径无效')
    value = value.replace('\\', '/')
    p = PurePosixPath(value)
    if p.is_absolute() or any(s in ('.', '..', '') for s in value.split('/')) or ':' in value or any(ord(c) < 32 for c in value) or p.name != filename:
        raise APIError(400, '文件相对路径须位于所选订单文件夹内')
    return str(p)

def source_bytes(store, doc):
    name = doc.get('storage_name', '')
    if not name or Path(name).name != name:
        raise APIError(409, '来源文件记录无效')
    root = store.uploads.resolve()
    path = (root / name).resolve()
    if path.parent != root or not path.is_file():
        raise APIError(409, '来源文件缺失，请重新上传')
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != doc.get('sha256'):
        raise APIError(409, '来源文件内容已变化，请重新上传核对')
    return raw, path

def _xml(archive, name):
    info = archive.getinfo(name)
    if info.file_size > 30_000_000:
        raise ValueError('工作表过大，请分表导入')
    return ET.fromstring(archive.read(name))

def xlsx_orders(raw):
    """Select an actual named order table. Ignore hidden/auxiliary sheets.

    Merged material cells use their explicit anchor; unmerged empty cells never
    inherit another product's material. Whole-cabinet height stays height.
    """
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        if sum(i.file_size for i in z.infolist()) > 180_000_000:
            raise ValueError('工作簿解压后过大，请拆分')
        shared = []
        if 'xl/sharedStrings.xml' in z.namelist():
            shared = [''.join(e.itertext()) for e in _xml(z, 'xl/sharedStrings.xml')]
        book = _xml(z, 'xl/workbook.xml')
        rels = {e.get('Id'): e.get('Target') for e in _xml(z, 'xl/_rels/workbook.xml.rels') if e.get('TargetMode') != 'External'}
        candidates, ignored = [], []
        for sheet in book.findall('m:sheets/m:sheet', SHEET_NS):
            title = sheet.get('name', '')
            if sheet.get('state', 'visible') != 'visible':
                ignored.append({'sheet': title, 'reason': '隐藏工作表'}); continue
            target = rels.get(sheet.get(REL_NS), '')
            name = target.lstrip('/') if target.startswith('/') else 'xl/' + target
            if '..' in PurePosixPath(name).parts or not name.startswith('xl/'):
                continue
            xml = _xml(z, name)
            rows, cells = {}, {}
            for row in xml.findall('m:sheetData/m:row', SHEET_NS):
                rn = int(row.get('r', '0'))
                if not 0 < rn <= 5000: continue
                values = {}
                for c in row.findall('m:c', SHEET_NS):
                    ref = c.get('r', '')
                    column = re.sub(r'\d', '', ref)
                    value = c.find('m:v', SHEET_NS)
                    value = value.text if value is not None else ''
                    if c.get('t') == 's': value = shared[int(value)] if value else ''
                    elif c.get('t') == 'inlineStr': value = ''.join(c.find('m:is', SHEET_NS).itertext())
                    if c.find('m:f', SHEET_NS) is not None:
                        # Formula text is retained only for picture lookup; numeric
                        # caches are not fresh enough to authorize an order count.
                        value = '=' + (c.find('m:f', SHEET_NS).text or '')
                    if value:
                        values[column] = str(value).strip(); cells[ref] = str(value).strip()
                if values: rows[rn] = values
            merges = [m.get('ref') for m in xml.findall('m:mergeCells/m:mergeCell', SHEET_NS)]
            header = None
            for rn, row in rows.items():
                names = {re.sub(r'\s', '', v): c for c, v in row.items()}
                if '名称' in names and '数量' in names and ('规格' in names or '尺寸' in names) and '单位' in names:
                    header = (rn, names); break
            if not header:
                ignored.append({'sheet': title, 'reason': '没有明确的名称、规格、单位、数量表头'}); continue
            hr, heads = header
            def val(rn, col):
                ref = col + str(rn)
                if ref in cells: return cells[ref], ref
                for merged in merges:
                    a,b = merged.split(':')
                    ac, ar = re.match(r'([A-Z]+)(\d+)', a).groups()
                    bc, br = re.match(r'([A-Z]+)(\d+)', b).groups()
                    if ac == bc == col and int(ar) <= rn <= int(br): return cells.get(a, ''), a
                return '', ref
            items = []
            for rn in sorted(r for r in rows if r > hr):
                title_value, title_ref = val(rn, heads['名称'])
                spec, spec_ref = val(rn, heads.get('尺寸') or heads['规格'])
                unit, unit_ref = val(rn, heads['单位'])
                count, count_ref = val(rn, heads['数量'])
                if not title_value or not (spec or unit or count) or title_value.startswith('='): continue
                material, material_ref = val(rn, heads.get('备注', 'ZZZ'))
                qty = float(count) if re.fullmatch(r'\d+(?:\.\d+)?', count) else None
                if qty is not None and not 0 < qty <= 100000: qty = None
                dims = re.fullmatch(r'\s*(\d+(?:\.\d+)?)\s*[*×xX]\s*(\d+(?:\.\d+)?)\s*[*×xX]\s*(\d+(?:\.\d+)?)\s*', spec)
                item = {'name': title_value, 'specification': spec, 'quantity': qty, 'quantity_unit': unit,
                        'material': material, 'sheet': title, 'row': rn, 'cell': f'{title_ref}:{count_ref}',
                        'image_column': heads.get('图示', ''),
                        'material_cell': material_ref, 'overall_dimensions': dict(zip(('length_mm','width_mm','height_mm'),map(float,dims.groups()))) if dims else {},
                        'questions': []}
                if '弧' in spec or '⌒' in spec: item['questions'].append('弧长、弦长与半径需按工程图分别核对，不能当作直板长度')
                if qty is None or qty != int(qty): item['questions'].append('数量未明确为整套数，请核对原单元格')
                if not material: item['questions'].append('本行没有明确材料说明，需从施工图核对')
                image_value, image_ref = val(rn, heads.get('图示','ZZZ'))
                match = re.search(r'DISPIMG\("([^"]+)"', image_value)
                if match: item['image_key'], item['image_cell'] = match[1], image_ref
                items.append(item)
            products, handoff_rules = [], []
            for item in items:
                kind = _handoff_kind(item)
                if kind:
                    handoff_rules.append({**item, 'kind': kind})
                else:
                    products.append(item)
            if products:
                candidates.append({'sheet': title, 'items': products,
                                   'handoff_rules': handoff_rules, 'header_row': hr,
                                   'order_text': ' '.join(v for r, row in rows.items() if r < hr for v in row.values())})
            else:
                ignored.append({'sheet': title, 'reason': '只有包装/发货说明，没有可拆柜体' if handoff_rules else '表头下没有可用订单行'})
        return {'sheets': candidates, 'ignored_sheets': ignored}

def pdf_pages(path):
    tool = executable('pdftotext')
    if not tool: raise ValueError('缺少 Poppler pdftotext，无法读取 PDF 页码与文字')
    res = subprocess.run([tool, '-layout', str(path), '-'], capture_output=True, timeout=45)
    if res.returncode: raise ValueError('PDF 文字无法读取，请检查加密或文件完整性')
    pages = res.stdout.decode('utf-8', errors='replace').split('\f')
    if not pages[-1].strip(): pages.pop()
    if len(pages)>600: raise ValueError('单份 PDF 超过 600 页，请分册导入')
    return [{'page':i+1, 'text':s, 'text_sha256':hashlib.sha256(re.sub(r'\s+', '', s).encode()).hexdigest() if s.strip() else None} for i,s in enumerate(pages)]

def page_bom(text):
    """Extract only clear table rows, retaining printed quantity per assembly.

    Does not assume a dimension order or multiply nested/subassembly counts.
    """
    active=False; result=[]
    for line in text.splitlines():
        if '名称' in line and ('材质' in line or '图号' in line): active=True; continue
        if not active: continue
        if '未注线性' in line or re.search(r'材料\s{2,}', line): break
        fields = re.split(r'\s{2,}', line.strip())
        # Some pages have nearby drawing labels before the table columns.
        for start in range(min(3,len(fields))):
            fs = fields[start:]
            if len(fs)<3 or not fs[0].isdigit() or not re.search(r'[\u4e00-\u9fff]',fs[1]): continue
            if not 1<=int(fs[0])<=300: continue
            qi = next((j for j in range(2,min(4,len(fs))) if re.fullmatch(r'\d{1,4}',fs[j])),None)
            if qi is None or not 0<int(fs[qi])<=1000: continue
            name=fs[1]; spec=fs[2] if qi==3 else ''
            if name in ('页','材料','版本','面积'):continue
            note=' '.join(fs[qi+1:]); note=re.split(r'模 具|包 装|资 料|批 准|U 8',note)[0].strip()
            questions=[]
            if re.search('软包|包布',name) and '玻璃' in note: questions.append('软包板的材料栏写了玻璃，需核对材质')
            result.append({'number':int(fs[0]),'name':name,'specification':spec,'per_assembly_quantity':int(fs[qi]),'note':note,'questions':questions})
            break
    if not result:
        # Some workshop cutting sheets use two parallel text columns instead
        # of a numbered BOM. Keep only explicitly named dimension/material/count
        # expressions. An unnamed continuation is not silently another panel.
        pattern = re.compile(r'([\u4e00-\u9fff][\u4e00-\u9fff0-9.（）/]{0,18})\s+'
                             r'(\d+(?:\.\d+)?\s*[*×]\s*\d+(?:\.\d+)?\s*[*×]\s*\d+(?:\.\d+)?)'
                             r'([\u4e00-\u9fff]{1,8})\s*[=＝]\s*(\d{1,4})(?![\d.])')
        for line in text.splitlines():
            matches = list(pattern.finditer(line))
            for index, match in enumerate(matches):
                name, spec, material, count = match.groups()
                if not 0 < int(count) <= 1000: continue
                note = line[match.end():matches[index+1].start() if index+1 < len(matches) else len(line)].strip()
                result.append({'number':len(result)+1,'name':name,'specification':re.sub(r'\s+', '', spec),
                    'per_assembly_quantity':int(count),'note':material + ('；' + note if note else ''),
                    'questions':[],'extraction_kind':'named_cutting_expression','source_quote':match.group(0)})
    return result

def _title(text, fallback):
    # The title block follows a repeated drawing number, unlike annotations.
    match=re.search(r'图号\s+([^\n]+?)\s+版本',text)
    name=re.sub(r'\s+',' ',match[1]).strip() if match else ''
    return name if name and len(name)<60 else fallback

def source_evidence(doc, page=None, **extra):
    result={'document_id':doc['id'],'file':doc['filename'],'source_path':doc.get('relative_path') or doc['filename'],
            'sha256':doc['sha256'],**extra}
    if page:result['page']=page
    return result


def _effect_only_pdf(doc):
    """A design-render PDF is a project reference, not a cabinet drawing.

    Deduplicated source bytes may also have an engineering-folder alias. In
    that case keep the engineering copy eligible for matching.
    """
    paths = doc.get('source_paths') or [doc.get('relative_path') or doc.get('filename', '')]
    if not isinstance(paths, list):
        paths = [paths]
    return bool(paths) and all(
        any(unicodedata.normalize('NFKC', part).strip() == '效果图'
            for part in PurePosixPath(str(path).replace('\\', '/')).parts[:-1])
        for path in paths)

def _identified_media(entry, project_id):
    """Stable source identity, including legacy records without a stored id.

    Read-time normalization does not rebuild orders or change source evidence.
    Titles and list positions are deliberately excluded from the identity.
    """
    result = dict(entry)
    if not isinstance(result.get('id'), str) or not result['id'].strip():
        identity = [project_id, entry.get('document_id'), entry.get('url'),
                    entry.get('page'), entry.get('sheet'), entry.get('cell')]
        digest = hashlib.sha256(json.dumps(identity, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()
        result['id'] = 'packet_image_' + digest
    return result

def _media(doc, page, title, kind='工程图'):
    base=f'/api/documents/{doc["id"]}/preview-image?page={page}'
    return _identified_media({'document_id':doc['id'],'source_file':doc.get('relative_path') or doc['filename'],'page':page,'title':title,
            'kind':kind,'url':base,'thumb_url':base+'&thumb=1'}, doc['project_id'])


def _package_relationships(archive, source):
    """Resolve only internal OOXML relationships beneath xl/."""
    rels = posixpath.join(posixpath.dirname(source), '_rels', posixpath.basename(source) + '.rels')
    if rels not in archive.namelist():
        return {}
    result = {}
    for relation in _xml(archive, rels):
        target = relation.get('Target', '')
        if (relation.get('TargetMode') == 'External' or not target or '\\' in target
                or ':' in target or any(ord(c) < 32 for c in target)):
            continue
        resolved = posixpath.normpath(posixpath.join(posixpath.dirname(source), target)) if not target.startswith('/') else target.lstrip('/')
        if resolved.startswith('xl/') and resolved in archive.namelist():
            result[relation.get('Id')] = (relation.get('Type', ''), resolved)
    return result


def _column_index(column):
    value = 0
    for letter in column:
        if not 'A' <= letter <= 'Z':
            return -1
        value = value * 26 + ord(letter) - ord('A') + 1
    return value - 1


def _floating_pictures(archive, items):
    """Map ordinary Excel drawing pictures to the exact 图示 cell row.

    A drawing may contain logos or nearby pictures. Only an image anchored in
    the order table's 图示 column and product row becomes product evidence.
    """
    wanted = {(item['sheet'], item['row'], _column_index(item.get('image_column', ''))): item
              for item in items if item.get('image_column')}
    if not wanted:
        return []
    book = _xml(archive, 'xl/workbook.xml')
    book_rels = _package_relationships(archive, 'xl/workbook.xml')
    ns = {'m': SHEET_NS['m'], 'xdr': 'http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing',
          'a': 'http://schemas.openxmlformats.org/drawingml/2006/main'}
    found = []
    for sheet in book.findall('m:sheets/m:sheet', ns):
        title = sheet.get('name', '')
        if not any(key[0] == title for key in wanted):
            continue
        sheet_rel = book_rels.get(sheet.get(REL_NS))
        if not sheet_rel or not sheet_rel[1].startswith('xl/worksheets/'):
            continue
        sheet_path = sheet_rel[1]
        sheet_rels = _package_relationships(archive, sheet_path)
        for drawing in _xml(archive, sheet_path).findall('m:drawing', ns):
            drawing_rel = sheet_rels.get(drawing.get(REL_NS))
            if not drawing_rel or not drawing_rel[0].endswith('/drawing') or not drawing_rel[1].startswith('xl/drawings/'):
                continue
            drawing_path = drawing_rel[1]
            image_rels = _package_relationships(archive, drawing_path)
            for anchor in _xml(archive, drawing_path):
                if not anchor.tag.endswith(('oneCellAnchor', 'twoCellAnchor')):
                    continue
                row = anchor.find('xdr:from/xdr:row', ns)
                col = anchor.find('xdr:from/xdr:col', ns)
                if row is None or col is None or not (row.text or '').isdigit() or not (col.text or '').isdigit():
                    continue
                item = wanted.get((title, int(row.text) + 1, int(col.text)))
                if not item:
                    continue
                blip = anchor.find('.//a:blip', ns)
                image_rel = image_rels.get(blip.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed')) if blip is not None else None
                if image_rel and image_rel[0].endswith('/image') and image_rel[1].startswith('xl/media/'):
                    found.append((item, image_rel[1], item['image_column'] + str(item['row'])))
    return found


def workbook_pictures(raw, store, doc, items):
    """Resolve WPS cell images and Excel anchored pictures from this workbook."""
    from drawing_media import validate_render
    result={}
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        candidates=[]
        if 'xl/cellimages.xml' in z.namelist():
            rels=_package_relationships(z,'xl/cellimages.xml')
            mapping={}
            for picture in _xml(z,'xl/cellimages.xml'):
                props=next((e for e in picture.iter() if e.tag.endswith('}cNvPr')),None)
                blip=next((e for e in picture.iter() if e.tag.endswith('}blip')),None)
                if props is not None and blip is not None:
                    relation=rels.get(blip.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed'))
                    if relation and relation[0].endswith('/image'):
                        mapping[props.get('name')]=relation[1]
        for item in items:
            member=mapping.get(item.get('image_key')) if 'xl/cellimages.xml' in z.namelist() else None
            if member:
                candidates.append((item,member,item.get('image_cell')))
        candidates.extend(_floating_pictures(z,items))
        assets=store.data_dir/'drawing-previews'/'assets'
        for item,member,cell in candidates:
            if item['name'] in result or not member.startswith('xl/media/'):
                continue
            info=z.getinfo(member)
            if info.file_size>20*1024*1024:continue
            picture=z.read(member)
            try:image=validate_render(Path(member).name,picture)
            except (ValueError,RuntimeError):continue
            assets.mkdir(parents=True,exist_ok=True)
            ext=Path(member).suffix.lower();digest=hashlib.sha256(picture).hexdigest()
            dest=assets/(digest+ext)
            if not dest.exists():dest.write_bytes(picture)
            url='/api/drawing-media/assets/'+dest.name
            result[item['name']]=_identified_media({'document_id':doc['id'],'source_file':doc['filename'],'sheet':item['sheet'],'cell':cell,
                'title':item['name']+' · 清单效果图','kind':'效果图','source_role':'order_cell_image',
                'project_id':doc['project_id'],'url':url,'thumb_url':url,'width':image['width'],'height':image['height']}, doc['project_id'])
    return result

def _positive_material_text(value):
    # A quoted exclusion such as “不含灯带” cannot create an electrical job.
    return re.sub(r'(?:不含|不带|无需|未配置|没有)[^，,；;。\n（）()]{0,50}', '', value or '')


def _trade_hits(text, pattern):
    return list(dict.fromkeys(re.findall(pattern, _positive_material_text(text), re.I)))[:8]


def _scopes(material, components, pages):
    """Draft trades from cabinet-row or identified component evidence only.

    A drawing-page keyword can flag a review question, but an unrelated title
    block or adjacent subassembly must not silently create a shop-floor task.
    """
    found=[];uncertain=[]
    component_text='\n'.join((c.get('name','')+' '+c.get('note','')) for c in components)
    page_text='\n'.join(p['text'] for _,p in pages)
    for trade,pattern,title in TRADES:
        order_hits=_trade_hits(material,pattern)
        component_hits=_trade_hits(component_text,pattern)
        hits=list(dict.fromkeys(order_hits+component_hits))
        if not hits:
            if _trade_hits(page_text,pattern):
                uncertain.append(trade+'：工程页提及相关材料，但未定位到本柜清单或构件，需技术员核对')
            continue
        basis=[]
        if order_hits:basis.append('本柜清单：'+'、'.join(order_hits))
        if component_hits:basis.append('构件明细：'+'、'.join(component_hits))
        found.append({'trade':trade,'title':title,'basis':'；'.join(basis),
                      'instructions':'核对'+('、'.join(hits))+'对应的构件、尺寸与数量；具体做法按确认图纸复核。',
                      'status':'suggested'})
    if found:
        found.extend([{'trade':trade,'title':title,'basis':'建议交付工序，待本厂复核',
                       'instructions':instruction,'status':'suggested'}
                      for trade,title,instruction in (
                          ('装配','组装与配件核对','核对本柜各工种完工件与配件，按确认装配图组装。'),
                          ('质检','尺寸、外观与功能核对','核对本柜成品尺寸、外观与功能。'),
                          ('包装','按柜号包装与贴标','按本柜编号核对成品数量、包装与标签。'))])
    return found,uncertain

def analyze(store, con, project_id, data):
    project=store.get(con,'projects',project_id);store.require_project_open(project)
    if project.get('factory_type','cabinet')!='cabinet' or project.get('industry_id') or project.get('workflow_id'):
        raise APIError(409,'此入口用于展柜下单清单；本项目请在已配置的行业工作包中核对工序')
    if data.get('expected_revision')!=project['revision']:raise APIError(409,'资料版本已更新，请刷新后重新拆单')
    docs=[d for d in store.all(con,'documents',project_id) if not d.get('superseded')]
    by_id={d['id']:d for d in docs}
    master=by_id.get(data.get('master_document_id'))
    if not master or Path(master['filename']).suffix.lower()!='.xlsx':raise APIError(400,'请选择本项目的 Excel 下单清单')
    raw,_=source_bytes(store,master)
    try:book=xlsx_orders(raw)
    except (ValueError,KeyError,zipfile.BadZipFile,ET.ParseError) as exc:raise APIError(422,'清单读取失败：'+str(exc))
    choices=book['sheets'];selection=data.get('sheet')
    if selection: choices=[s for s in choices if s['sheet']==selection]
    if len(choices)!=1:raise APIError(409,'请明确选择本订单工作表',{'sheets':[s['sheet'] for s in book['sheets']]})
    chosen=choices[0]
    handoff_rules=[{'kind':item['kind'],'title':item['name'],
                    'instruction':item['material'] or item['specification'],
                    'source':source_evidence(master,sheet=chosen['sheet'],cell=item['cell'],row=item['row'])}
                   for item in chosen.get('handoff_rules',[])]
    previous = project.get('order_packet', {})
    findings=data.get('findings',previous.get('findings',[]) if previous.get('master_document_id') == master['id'] else [])
    if not isinstance(findings,list) or len(findings)>200:raise APIError(400,'核对记录格式无效')
    for f in findings:
        if not isinstance(f,dict) or not isinstance(f.get('note'),str) or len(f['note'])>1000 or f.get('name') not in [i['name'] for i in chosen['items']]:raise APIError(400,'核对记录须指定本清单柜号与说明')
        if f.get('document_id') and f['document_id'] not in by_id:raise APIError(409,'核对依据不属于本项目')
    pictures=workbook_pictures(raw,store,master,chosen['items'])
    sources, pdfs, issues=[],[],[
        rule['title']+'：'+(re.sub(r'\s+', ' ', rule['instruction']).strip()[:180] or '具体要求待补齐')
        +f'（{chosen["sheet"]} 第{rule["source"]["row"]}行；包装/发货前核对）'
        for rule in handoff_rules]
    for d in docs:
        sources.append({'document_id':d['id'],'filename':d['filename'],'source_path':d.get('relative_path') or d['filename'],
                        'source_paths':d.get('source_paths') or [d.get('relative_path') or d['filename']],
                        'kind':'效果图' if d.get('purpose')=='render' else '工程资料','sha256':d['sha256']})
        if (Path(d['filename']).suffix.lower()!='.pdf' or d.get('purpose')=='render'
                or _effect_only_pdf(d)):
            continue
        _,path=source_bytes(store,d)
        try:
            pages=pdf_pages(path)
            if not any(p['text'].strip() for p in pages):issues.append(d['filename']+'：扫描件没有文字层，须看图复核或 OCR')
            pdfs.extend((d,p) for p in pages)
        except (ValueError,subprocess.TimeoutExpired) as exc:issues.append(d['filename']+'：'+str(exc))
    names=[i['name'] for i in chosen['items']]
    output=[];media={};bom_rows=[];duplicate_pages=[];pixel_cache={}
    def pixels(d,p):
        key=(d['id'],p['page'])
        if key not in pixel_cache:
            _,path=source_bytes(store,d)
            pv=preview_pdf(store.data_dir,d,path,p['page'])
            from drawing_media import asset_path, content_hash
            pixel_cache[key]=content_hash(asset_path(store.data_dir,pv['url'].split('/')[-1]))
        return pixel_cache[key]
    for i,item in enumerate(chosen['items'],1):
        code=f'ORDER-{i:03d}';name=item['name']
        own=[]
        for d,p in pdfs:
            text=p['text'];stem=Path(d['filename']).stem
            # A cabinet title must not match another cabinet's longer name.
            normalized=re.sub(r'\s+','',text)
            matches=[n for n in names if n in normalized]
            direct=stem==name
            if direct or (name in matches and not any(n!=name and name in n for n in matches)):
                if direct or ('物料属性' in normalized and re.search(re.escape(name)+r'(?:材料|\d|图号)',normalized)) or ('物料属性' not in normalized and len(matches)==1):
                    own.append((d,p))
        # Prefer the individual engineering booklet; retain every matching source.
        own.sort(key=lambda pair:(Path(pair[0]['filename']).stem!=name, '施工' in pair[0]['filename'],len(pair[0]['filename']),pair[1]['page']))
        unique=[];seen={}
        for d,p in own:
            h=p['text_sha256']
            if h and h in seen:
                oldd,oldp=seen[h]; duplicate_pages.append({'file':d['filename'],'page':p['page'],'same_text_as':oldd['filename'],'same_text_page':oldp['page']})
                # Matching text alone is insufficient: mirrored geometry can
                # carry identical labels. Collapse only identical rendered pages.
                if pixels(d,p) and pixels(d,p)==pixels(oldd,oldp):
                    duplicate_pages[-1]['same_pixels']=True
                    continue
            if h:seen[h]=(d,p)
            unique.append((d,p))
        evidence=[source_evidence(master,sheet=chosen['sheet'],cell=item['cell'],row=item['row'],quote=f'{name} {item["specification"]} {item["quantity"]}{item["quantity_unit"]}')]
        refs=[];components=[]
        if name in pictures:refs.append(pictures[name])
        for d,p in unique:
            page_name=_title(p['text'],name)
            is_engineering='物料属性' in p['text'] or '工程图' in (d.get('relative_path') or '') or '料单' in d['filename']
            refs.append(_media(d,p['page'],page_name,'工程图' if is_engineering else '施工图'))
            evidence.append(source_evidence(d,p['page'],reference=page_name))
            for row in page_bom(p['text']):
                components.append({**row,'parent':page_name,'evidence':source_evidence(d,p['page'])})
        questions=list(item['questions'])
        if not own:questions.append('尚未匹配到此柜号的 PDF 图纸')
        questions.extend(q for r in components for q in r['questions'])
        questions.extend(f['note'] for f in findings if f['name']==name)
        scopes,scope_questions=_scopes(item['material'],components,unique)
        questions.extend(scope_questions)
        output.append({'id':code,'name':name,'item_level':'assembly','quantity':item['quantity'],'quantity_unit':item['quantity_unit'],
            'specification':item['specification'],'overall_dimensions':item['overall_dimensions'],'material':item['material'],
            'source_file':master['filename'],'source_reference':chosen['sheet']+'!'+item['cell'],
            'quantity_basis':'下单清单整柜数量；装配表为单柜用量，未将嵌套组件重复相乘',
            'evidence':evidence,'review_questions':list(dict.fromkeys(questions)),'work_scopes':scopes,
            'engineering_bom':components,'notes':'工种分工草稿，尺寸、零件用量和工序须复核后发布。',
            'image_key':item.get('image_key'),'image_cell':item.get('image_cell')})
        media[code]=refs;bom_rows.extend(components)
    native_count=sum(Path(d['filename']).suffix.lower() in ('.sldasm','.sldprt','.slddrw','.dwg') for d in docs)
    return {'version':VERSION,'project_id':project_id,'expected_revision':project['revision'],'master_document_id':master['id'],
            'master_sheet':chosen['sheet'],'sources':sources,'parts':output,'media':media,'issues':issues,
            'handoff_rules':handoff_rules,
            'ignored_sheets':book['ignored_sheets'],'similar_pages':duplicate_pages,'pdf_pages':len(pdfs),
            'bom_row_count':len(bom_rows),'scope_count':sum(len(p['work_scopes']) for p in output),
            'quantity_total':sum(p['quantity'] for p in output if p['quantity'] is not None),
            'findings':findings,'native_file_count':native_count,'created_at':now()}

def save(store,con,project_id,data):
    project=store.get(con,'projects',project_id);store.require_project_open(project)
    old_parts=store.active_parts(con,project_id);old_tasks=store.active_tasks(con,project_id)
    from operations import workflow_task_replaceable
    if any(not p.get('packet_generated') for p in old_parts) or any(not t.get('packet_generated') or not workflow_task_replaceable(t) for t in old_tasks):
        raise APIError(409,'已有人工部件或生产任务，请先在独立项目核对整单拆解，当前记录未覆盖')
    result=analyze(store,con,project_id,data)
    fingerprint=hashlib.sha256(json.dumps({k:result[k] for k in ('version','master_document_id','master_sheet','sources','findings')},sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    if (project.get('order_packet',{}).get('fingerprint')==fingerprint and old_parts
            and project['order_packet'].get('revision')==project['revision']):
        return {'project':project,'parts':old_parts,'tasks':old_tasks,'unchanged':True}
    store.invalidate(con,project,'按下单清单与工程图更新拆单草稿')
    for p in old_parts:p['archived']=True;store.put(con,'parts',p)
    for t in old_tasks:t['archived']=True;store.put(con,'tasks',t)
    parts=[];tasks=[]
    for row in result['parts']:
        code=row['id'];p={**row,'id':uid('part'),'project_id':project_id,'document_id':result['master_document_id'],
           'packet_generated':True,'draft_only':True,'unit':'mm','length':None,'width':None,'thickness':None,
           'review_status':'pending','issues':row['review_questions'],'source_issues':row['review_questions'],
           'source':{'file':row['source_file'],'reference':row['source_reference'],'part_number':code},
           'revision':project['revision'],'created_at':now(),'demo':False,'archived':False}
        store.put(con,'parts',p);parts.append(p)
        mapping={s['trade']:uid('task') for s in row['work_scopes']}
        for scope in row['work_scopes']:
            trade=scope['trade'];before=[]
            if trade=='油漆':before=[v for k,v in mapping.items() if k in ('木工','五金')]
            elif trade=='装配':before=[v for k,v in mapping.items() if k in ('木工','五金','玻璃','油漆','电工')]
            elif trade=='质检':before=[mapping['装配']] if '装配' in mapping else []
            elif trade=='包装':before=[mapping['质检']] if '质检' in mapping else []
            t={'id':mapping[trade],'project_id':project_id,'part_id':p['id'],'packet_generated':True,'revision':project['revision'],
               'title':name_for_task(row,scope),'trade':trade,'process':trade,'quantity':row['quantity'],'unit':row['quantity_unit'],
               'status':'draft','assignee':None,'dependencies':before,'hours':None,'estimate_basis':'待生产排程表或班组估时',
               'source':{**p['source'],'document_ids':list(dict.fromkeys(e['document_id'] for e in row['evidence']))},
               'instructions':scope['instructions'],'acceptance':'按已确认图纸核对本工种的构件、尺寸和数量','issues':row['review_questions'],
               'rule_id':VERSION,'execution_version':0,'completed_quantity':0,'progress_recorded':True,'created_at':now(),'archived':False,'demo':False}
            store.put(con,'tasks',t);tasks.append(t)
    project['order_draft']={'schema':'cabinet-order-draft-v1','order_key':project.get('code') or project_id,
        'source_revision':str(project['revision']),'sources':result['sources'],'issues':result['issues'],
        'handoff_rules':result['handoff_rules'],'part_count':len(parts),'scope_count':len(tasks),
        'version_note':'下单清单与导出工程 PDF 拆单草稿','document_id':result['master_document_id']}
    project['order_packet']={k:v for k,v in result.items() if k not in ('parts','media')}
    project['order_packet'].update(fingerprint=fingerprint,revision=project['revision'])
    project['order_packet']['cover'] = next((r for refs in result['media'].values() for r in refs if r['kind']=='效果图'), None)
    project['planned_revision']=project['revision'];store.put(con,'projects',project)
    # Associations are project-owned records. No absolute filesystem references
    # or arbitrary URLs from a client are accepted by the drawing-media endpoint.
    store.put(con,'order_packet_media',{'id':'packet_media_'+project_id,'project_id':project_id,'revision':project['revision'],
              'parts':result['media'],'master_document_id':result['master_document_id']})
    store.event(con,project_id,'order_packet_generated','按来源生成 '+str(len(parts))+' 项柜体与 '+str(len(tasks))+' 项工种草稿',
                master_document_id=result['master_document_id'],source_count=len(result['sources']),fingerprint=fingerprint)
    return {'project':project,'parts':parts,'tasks':tasks,'packet':project['order_packet'],'unchanged':False}

def name_for_task(row,scope):
    return row['name']+' · '+scope['title']

def media_for_project(store,con,project_id):
    project=store.get(con,'projects',project_id)
    if not project.get('order_packet') or project['order_packet'].get('revision')!=project['revision']:return {}
    records=store.all(con,'order_packet_media',project_id)
    if not records:return {}
    record=records[0]
    docs={d['id']:d for d in store.all(con,'documents',project_id) if not d.get('superseded')}
    return {key:[_identified_media(r, project_id) for r in refs if r.get('document_id') in docs] for key,refs in record['parts'].items()}

def project_media(store,con,project_id):
    from drawing_media import project_media as base_media
    import project_overview
    docs=store.all(con,'documents',project_id)
    result=base_media(store.data_dir,project_id,docs)
    project=store.get(con,'projects',project_id)
    result['renders']=project_overview.media(project,docs)+result['renders']
    result['panorama_url']=project_overview.panorama_url(project.get('overview_panorama',''))
    packet=media_for_project(store,con,project_id)
    if packet:
        result['parts'].update(packet)
        seen={r.get('url') for r in result['renders']}
        for refs in packet.values():
            for r in refs:
                if r['kind']=='效果图' and r['url'] not in seen:
                    result['renders'].append(r);seen.add(r['url'])
    for index, r in enumerate(result.get('renders',[]),1):
        if re.fullmatch(r'[a-fA-F0-9]{20,64}',r.get('title','')):
            r['title']=('柜体参考图 ' if r.get('scope')=='cabinet' else '项目效果图 ')+str(index)
    cover_id=(project.get('overview_cover') or {}).get('id')
    if cover_id:result['renders'].sort(key=lambda r:r.get('id')!=cover_id)
    return result
