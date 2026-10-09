"""Auditable local cabinet-production rules and explicit CAD/BOM import.

No network, model service, native CAD SDK or hidden default material prices.
DXF support is deliberately a documented ASCII subset, not a DWG/SolidWorks reader.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import math
from pathlib import Path
import re

import order_drafts

RULE_VERSION = "cabinet-v1.0"
CATEGORIES = {"wood", "metal", "glass", "electrical", "hardware"}
ALIASES = {
    "id": ("id", "part_id", "part_number", "零件编号", "构件编号", "编号", "物料编码"),
    "name": ("name", "part_name", "名称", "零件名称", "构件名称", "物料名称"),
    "material": ("material", "材料", "材质"),
    "category": ("category", "类别", "分类", "类型"),
    "length": ("length", "length_mm", "长度", "长", "长度mm", "长度(mm)", "长(mm)"),
    "width": ("width", "width_mm", "宽度", "宽", "宽度mm", "宽度(mm)", "宽(mm)"),
    "thickness": ("thickness", "thickness_mm", "厚度", "厚", "厚度mm", "厚度(mm)", "厚(mm)"),
    "quantity": ("quantity", "qty", "数量", "用量"),
    "unit": ("unit", "units", "dimension_unit", "单位", "尺寸单位"),
    "finish": ("finish", "surface", "表面处理", "饰面", "油漆"),
    "revision": ("revision", "rev", "版本", "图纸版本"),
    "source_file": ("source_file", "来源文件"),
    "source_reference": ("source_reference", "来源配置", "来源引用"),
    "unit_price": ("unit_price", "单价"),
    "pricing_unit": ("pricing_unit", "计价单位"),
    "weight_kg": ("weight_kg", "单件重量kg"),
}
CATEGORY_ALIASES = {
    "木工": "wood", "木作": "wood", "木质": "wood", "板材": "wood", "木": "wood",
    "五金": "metal", "金属": "metal", "钣金": "metal", "铁": "metal",
    "玻璃": "glass", "电工": "electrical", "电气": "electrical", "灯具": "electrical",
    "配件": "hardware", "标准件": "hardware", "五金配件": "hardware",
}
UNIT_FACTORS = {"mm": 1, "毫米": 1, "cm": 10, "厘米": 10, "m": 1000, "米": 1000,
                "in": 25.4, "inch": 25.4, "inches": 25.4, "英寸": 25.4}
PRICE_UNITS = {"m2": "m2", "㎡": "m2", "m²": "m2", "平方米": "m2",
               "m3": "m3", "m³": "m3", "立方米": "m3", "piece": "piece",
               "pcs": "piece", "件": "piece", "个": "piece", "kg": "kg", "千克": "kg",
               "meter": "meter", "m": "meter", "米": "meter"}


def _number(value):
    if value is None or isinstance(value, bool) or str(value).strip() == "":
        return None
    try:
        value = float(str(value).strip())
        return value if math.isfinite(value) else None
    except (ValueError, TypeError):
        return None


def _positive(value):
    value = _number(value)
    return value if value is not None and value > 0 else None


def _text(value):
    return str(value).strip() if value is not None else ""


def _stable_id(*items):
    return "P-" + hashlib.sha256("|".join(map(str, items)).encode()).hexdigest()[:12]


def _canonical(row):
    lowered = {_text(k).lower().replace("（", "(").replace("）", ")"): v for k, v in row.items() if k is not None}
    return {key: next((lowered[a] for a in aliases if a in lowered), None) for key, aliases in ALIASES.items()}


def _normalise_part(row, filename, reference, default_unit=None):
    item = _canonical(row)
    issues = []
    name = _text(item["name"])
    if not name:
        issues.append("缺少构件名称")
        name = "未命名构件"
    material = _text(item["material"])
    if not material:
        issues.append("缺少材料/型号")
    category = _text(item["category"]).lower()
    category = CATEGORY_ALIASES.get(category, category)
    if category not in CATEGORIES:
        category = None
        issues.append("缺少或无法识别构件类别，需选择 wood/metal/glass/electrical/hardware")
    unit = _text(item["unit"] or default_unit).lower()
    if not unit and any("_mm" in str(k).lower() or "(mm)" in str(k).lower() for k in row):
        unit = "mm"
    factor = UNIT_FACTORS.get(unit)
    dimensions = {}
    for key in ("length", "width", "thickness"):
        raw = item[key]
        value = _positive(raw)
        if value is None and _text(raw):
            issues.append(f"{key} 必须为大于 0 的有限数字")
        dimensions[key] = round(value * factor, 6) if value is not None and factor else None
    if factor is None and any(_text(item[k]) for k in dimensions):
        issues.append(f"尺寸单位未明确或不支持：{unit or '空'}；尺寸尚未转换")
    if category in {"wood", "metal", "glass"}:
        for key in dimensions:
            if dimensions[key] is None:
                issues.append(f"缺少有效 {key}（毫米）")
    quantity = _positive(item["quantity"])
    if quantity is None:
        issues.append("缺少有效数量；不能用图形数量代替构件用量")
    elif not quantity.is_integer():
        issues.append("构件件数应为整数，请核对数量与计量方式")
    else:
        quantity = int(quantity)
    finish = _text(item["finish"])
    if category in {"wood", "metal"} and not finish:
        issues.append("表面处理未明确，油漆/饰面工序待确认")
    part = {
        "id": _text(item["id"]) or _stable_id(filename, reference), "name": name,
        "material": material, "category": category, **dimensions, "quantity": quantity,
        "unit": "mm", "finish": finish,
        "source": {"file": filename, "reference": reference, "revision": _text(item["revision"])},
        "review_status": "pending", "issues": list(dict.fromkeys(issues)),
    }
    if item["source_file"]:
        part["source"]["model_file"] = _text(item["source_file"])
    if _text(item["id"]):
        part["source"]["part_number"] = _text(item["id"])
    if item["source_reference"]:
        part["source"]["model_reference"] = _text(item["source_reference"])
    if item["unit_price"] is not None and _text(item["unit_price"]):
        part["unit_price"] = _number(item["unit_price"])
        part["pricing_unit"] = PRICE_UNITS.get(_text(item["pricing_unit"]).lower())
        if part["unit_price"] is None or part["unit_price"] < 0 or not part["pricing_unit"]:
            part["issues"].append("单价或计价单位无效，报价时需补充")
    if item["weight_kg"] is not None:
        part["weight_kg"] = _positive(item["weight_kg"])
    return part


def _deduplicate(parts, warnings):
    """Disambiguate duplicate identifiers without deciding their physical quantities."""
    seen = {}
    result = []
    for part in parts:
        identity = part["id"]
        if identity in seen:
            previous = seen[identity]
            issue = f"重复编号需确认，整单BOM须明确汇总：{identity}；记录均保留，未自动累加或去重"
            if issue not in previous["issues"]:
                previous["issues"].append(issue)
            part["issues"].append(issue)
            if issue not in warnings:
                warnings.append(issue)
            new_identity = identity + "-" + hashlib.sha256(part["source"]["reference"].encode()).hexdigest()[:6]
            sequence = 2
            while new_identity in seen:
                new_identity = identity + "-" + hashlib.sha256((part["source"]["reference"] + f"-{sequence}").encode()).hexdigest()[:6]
                sequence += 1
            part["id"] = new_identity
        seen[part["id"]] = part
        result.append(part)
    return result


def _decode(content):
    for encoding in ("utf-8-sig", "gb18030", "utf-16"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError("文本编码无法识别，请导出 UTF-8 CSV/JSON/ASCII DXF")


def parse_document(filename: str, content: bytes) -> dict:
    """Parse explicit BOM facts or supported ASCII DXF entities; never invent CAD facts."""
    suffix = Path(filename).suffix.lower()
    result = {"parts": [], "geometry": [], "warnings": [], "format": suffix.lstrip(".") or "unknown", "status": "needs_review"}
    if suffix not in {".csv", ".json", ".dxf"}:
        result["status"] = "needs_conversion"
        guidance = {".pdf": "图纸已保存，可逐页查看；尚未提取结构化构件，请补充 BOM 或人工拆单。", ".dwg": "DWG 已保存；请导出 PDF 查看图纸，或导出带构件属性的 ASCII DXF / BOM 进行拆单。", ".sldprt": "零件模型已保存；请从 SolidWorks 导出工程图 PDF 和 BOM CSV。", ".sldasm": "装配模型已保存；请从 SolidWorks 导出工程图 PDF 和 BOM CSV。", ".slddrw": "工程图已保存；请从 SolidWorks 导出 PDF 图纸和 BOM CSV。"}
        if suffix in {".stl", ".obj", ".glb", ".step", ".stp", ".iges", ".igs", ".brep"}:
            guidance[suffix] = "模型已保存，可在 3D 工作区查看；待关联拆单。"
        result["warnings"] = [guidance.get(suffix, "文件已保存，当前格式尚未提取结构化构件；请补充 PDF 图纸或 BOM CSV / JSON。")]
        return result
    if not content:
        result["status"] = "error"
        result["warnings"] = ["文件为空"]
        return result
    try:
        if suffix == ".dxf":
            return _parse_dxf(filename, content)
        text = _decode(content)
        if suffix == ".json":
            payload = json.loads(text)
            if isinstance(payload, dict) and payload.get('schema') == order_drafts.SCHEMA:
                return order_drafts.parse(payload, filename)
            rows = payload.get("parts") if isinstance(payload, dict) else payload
            default_unit = payload.get("unit") if isinstance(payload, dict) else None
            if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
                raise ValueError("JSON 必须是构件对象数组，或包含 parts 数组的对象")
            numbered_rows = [(f"JSON parts[{i}]", row) for i, row in enumerate(rows)]
        else:
            try:
                dialect = csv.Sniffer().sniff(text[:8192], delimiters=",;\t")
            except csv.Error:
                dialect = csv.excel
            reader = csv.DictReader(io.StringIO(text), dialect=dialect)
            if not reader.fieldnames:
                raise ValueError("CSV 缺少表头")
            normalized_headers = [_text(x).lower() for x in reader.fieldnames]
            if len(set(normalized_headers)) != len(normalized_headers):
                raise ValueError("CSV 包含重复表头，无法确定字段含义")
            numbered_rows = []
            for row in reader:
                if None in row:
                    raise ValueError(f"CSV 第 {reader.line_num} 行列数超过表头；请检查逗号与引号")
                if any(_text(v) for v in row.values()):
                    numbered_rows.append((f"CSV 第 {reader.line_num} 行", row))
            default_unit = None
        parts = [_normalise_part(row, filename, reference, default_unit) for reference, row in numbered_rows]
        result["parts"] = _deduplicate(parts, result["warnings"])
        if not parts:
            result["warnings"].append("未发现 BOM 构件记录")
        result["status"] = "needs_review" if any(p["issues"] for p in parts) or result["warnings"] else "parsed"
        return result
    except (ValueError, TypeError, csv.Error, OverflowError) as exc:
        result["status"] = "error"
        result["warnings"].append(str(exc))
        return result


def _pair_records(text):
    lines = text.splitlines()
    if len(lines) % 2:
        raise ValueError("ASCII DXF 组码和值未成对，请重新导出")
    pairs = []
    for i in range(0, len(lines), 2):
        try:
            pairs.append((int(lines[i].strip()), lines[i + 1].strip()))
        except ValueError as exc:
            raise ValueError(f"DXF 第 {i + 1} 行不是有效组码") from exc
    return pairs


def _all_values(record, code):
    return [value for key, value in record if key == code]


def _first(record, code, default=None):
    return next((value for key, value in record if key == code), default)


def _dxf_metadata(record, layer):
    metadata = {}
    active = False
    chunks = []
    for code, value in record:
        if code == 1001:
            active = value.upper() == "CABINET_PART"
        elif active and code == 1000:
            chunks.append(value)
    if chunks:
        try:
            obj = json.loads("".join(chunks))
            if isinstance(obj, dict):
                metadata.update(obj)
        except (ValueError, TypeError):
            for chunk in chunks:
                if "=" in chunk:
                    key, value = chunk.split("=", 1)
                    metadata[key.strip().lower()] = value.strip()
            if not metadata:
                metadata["_metadata_error"] = "CABINET_PART XDATA 无法读取，请检查 JSON 或 key=value"
    if layer.upper().startswith("CABINET::"):
        fields = layer.split("::")[1:]
        for key, value in zip(("category", "name", "material", "thickness", "finish", "quantity"), fields):
            metadata.setdefault(key, value)
    return metadata


def _rectangle_size(points, bulged=False):
    """Only axis-aligned rectangles are safe for inferred planar cut dimensions."""
    if bulged:
        return None
    points = list(points)
    if len(points) == 5 and points[0] == points[-1]:
        points.pop()
    if len(points) != 4:
        return None
    xs = sorted(set(round(p[0], 6) for p in points))
    ys = sorted(set(round(p[1], 6) for p in points))
    if len(xs) != 2 or len(ys) != 2:
        return None
    expected = {(xs[0], ys[0]), (xs[0], ys[1]), (xs[1], ys[0]), (xs[1], ys[1])}
    if {(round(x, 6), round(y, 6)) for x, y in points} != expected:
        return None
    for p, q in zip(points, points[1:] + points[:1]):
        if not (abs(p[0] - q[0]) < 1e-6 or abs(p[1] - q[1]) < 1e-6):
            return None
    return xs[-1] - xs[0], ys[-1] - ys[0]


def _parse_dxf(filename, content):
    result = {"parts": [], "geometry": [], "warnings": [], "format": "dxf", "status": "needs_review"}
    if content.startswith(b"AutoCAD Binary DXF"):
        result["status"] = "needs_conversion"
        result["warnings"] = ["仅支持 ASCII DXF，当前文件为二进制 DXF，请重新导出 ASCII 格式"]
        return result
    pairs = _pair_records(_decode(content))
    factor, drawing_unit = None, None
    for i, pair in enumerate(pairs):
        if pair == (9, "$INSUNITS") and i + 1 < len(pairs):
            code = pairs[i + 1][1]
            drawing_unit = {"1": "in", "4": "mm", "5": "cm", "6": "m"}.get(code)
            factor = UNIT_FACTORS.get(drawing_unit)
            break
    result["units"] = "mm" if factor else "drawing"
    if factor is None:
        result["warnings"].append("DXF $INSUNITS 缺失、无单位或暂不支持；仅保留绘图坐标，不从几何推算毫米尺寸")
    records, section, current = [], None, None
    for i, (code, value) in enumerate(pairs):
        if code == 0 and value == "SECTION":
            section = pairs[i + 1][1] if i + 1 < len(pairs) and pairs[i + 1][0] == 2 else None
            current = None
        elif code == 0 and value == "ENDSEC":
            if section == "ENTITIES" and current:
                records.append(current)
            section, current = None, None
        elif section == "ENTITIES":
            if code == 0:
                if current:
                    records.append(current)
                current = [(code, value)]
            elif current is not None:
                current.append((code, value))
    if section == "ENTITIES" and current:
        records.append(current)
    # Attach INSERT attributes and legacy POLYLINE vertices before reading facts.
    prepared, index = [], 0
    while index < len(records):
        record = records[index]
        kind = _first(record, 0)
        extra = []
        index += 1
        if kind in {"POLYLINE", "INSERT"}:
            while index < len(records) and _first(records[index], 0) in {"VERTEX", "ATTRIB"}:
                extra.append(records[index])
                index += 1
            if index < len(records) and _first(records[index], 0) == "SEQEND":
                index += 1
        prepared.append((record, extra))
    unknown_layers, skipped_types = set(), set()
    for entity_index, (record, extra) in enumerate(prepared):
        kind, handle, layer = _first(record, 0), _first(record, 5, str(entity_index + 1)), _first(record, 8, "0")
        scale = factor or 1
        def coord(code, default=0):
            value = _number(_first(record, code, default))
            if value is None:
                raise ValueError(f"DXF 实体 {handle} 有无效坐标")
            return value * scale
        g = {"handle": handle, "layer": layer, "units": "mm" if factor else "drawing"}
        points, closed, bulged = [], False, False
        if kind == "LWPOLYLINE":
            px = None
            for code, value in record:
                if code == 10:
                    px = _number(value)
                elif code == 20 and px is not None:
                    py = _number(value)
                    if py is None:
                        raise ValueError(f"DXF 实体 {handle} 有无效顶点")
                    points.append([px * scale, py * scale])
                    px = None
                elif code == 42 and (_number(value) or 0) != 0:
                    bulged = True
            closed = bool(int(_first(record, 70, "0")) & 1)
            g.update(type="polyline", points=points, closed=closed)
        elif kind == "POLYLINE":
            for vertex in extra:
                if _first(vertex, 0) == "VERTEX":
                    x, y = _number(_first(vertex, 10)), _number(_first(vertex, 20))
                    if x is not None and y is not None:
                        points.append([x * scale, y * scale])
                    bulged |= (_number(_first(vertex, 42)) or 0) != 0
            closed = bool(int(_first(record, 70, "0")) & 1)
            g.update(type="polyline", points=points, closed=closed)
        elif kind == "LINE":
            g.update(type="line", points=[[coord(10), coord(20)], [coord(11), coord(21)]])
        elif kind == "CIRCLE":
            g.update(type="circle", x=coord(10), y=coord(20), radius=coord(40))
        elif kind in {"TEXT", "MTEXT"}:
            text = "".join(value for code, value in record if code in {1, 3})
            g.update(type="text", x=coord(10), y=coord(20), text=text, height=coord(40, 12))
        elif kind == "INSERT":
            g.update(type="insert", x=coord(10), y=coord(20), block=_first(record, 2, ""))
            result["warnings"].append(f"块 {g['block']}（实体 {handle}）保留插入点和属性；此版本不展开块几何，尺寸须由属性明确提供")
        else:
            skipped_types.add(kind)
            continue
        if bulged:
            g["approximate"] = True
            result["warnings"].append(f"实体 {handle} 含 bulge 曲线；预览为顶点连线，不据此计算下料尺寸")
        result["geometry"].append(g)
        metadata = _dxf_metadata(record, layer)
        for attr in extra:
            if _first(attr, 0) == "ATTRIB":
                tag = _first(attr, 2, "").lower()
                if tag.startswith("cabinet_"):
                    tag = tag[8:]
                if tag in ALIASES:
                    metadata[tag] = _first(attr, 1, "")
        if metadata:
            error = metadata.pop("_metadata_error", None)
            if error:
                result["warnings"].append(f"实体 {handle}：{error}")
            # Geometry is eligible only with explicitly tagged production parts.
            rect = _rectangle_size(points, bulged) if closed and factor else None
            canon = _canonical(metadata)
            if rect and (canon["length"] is None or canon["width"] is None):
                # Rect dimensions already in mm, so convert into the metadata unit first.
                target_factor = UNIT_FACTORS.get(_text(canon["unit"] or drawing_unit).lower())
                if target_factor:
                    if canon["length"] is None:
                        metadata["length"] = rect[0] / target_factor
                    if canon["width"] is None:
                        metadata["width"] = rect[1] / target_factor
            metadata.setdefault("id", f"DXF-{handle}")
            part = _normalise_part(metadata, filename, f"DXF 实体 {handle} · 图层 {layer}", drawing_unit)
            part["source"]["handle"] = handle
            part["source"]["layer"] = layer
            part["source"]["geometry_dimension_basis"] = "矩形封闭轮廓" if rect else "显式属性（如有）"
            if metadata.get("schematic") or metadata.get("demo"):
                part["issues"].append("示意样本，尺寸与用量仅用于演示，不能直接投产")
            result["parts"].append(part)
        elif kind not in {"TEXT", "MTEXT"}:
            unknown_layers.add(layer)
    result["parts"] = _deduplicate(result["parts"], result["warnings"])
    if unknown_layers:
        result["warnings"].append("以下图层仅解析几何，未提供 CABINET_PART 属性或 CABINET:: 命名，未自动认定构件：" + "、".join(sorted(unknown_layers)))
    if skipped_types:
        result["warnings"].append("以下实体类型暂不解析：" + "、".join(sorted(x for x in skipped_types if x)))
    if not result["parts"]:
        result["warnings"].append("未发现带明确物料属性的构件；几何线条不等于 BOM，请补充构件属性或导入 BOM")
    result["status"] = "needs_review" if result["warnings"] or any(p["issues"] for p in result["parts"]) else "parsed"
    return result


# Hours below are editable planning hypotheses, not geometry-derived actual cycle times.
ROUTES = {
    "wood": [("cut", "木工", "板材开料", .16, "核对材质、板厚、纹理方向与下料尺寸"),
             ("machine", "木工", "铣槽钻孔与封边", .22, "按确认图纸复核孔位、槽位、封边及装配接口")],
    "metal": [("cut", "五金", "金属下料", .18, "核对材料牌号、厚度和已审核展开/型材尺寸"),
              ("fabricate", "五金", "成形焊接与修磨", .35, "折弯/焊接做法适用性待工艺员确认，核对定位尺寸与接合质量")],
    "glass": [("prepare", "玻璃", "玻璃加工与外协确认", .12, "复核开孔、磨边和钢化要求；钢化前完成适用加工并确认供应商"),
              ("incoming", "质检", "玻璃来料检验", .08, "检查尺寸、边角、外观与约定的安全玻璃资料")],
    "electrical": [("prepare", "电工", "灯具电源备料与线路预制", .20, "核对灯具/电源型号、回路及线缆规格；最终安装按确认电气方案执行")],
    "hardware": [("procure", "装配", "标准配件采购与齐套", .04, "按型号清点数量，确认铰链、锁具等接口与样品一致")],
}


def generate_tasks(parts: list) -> list:
    """Generate traceable draft routes with a complete assembly dependency barrier."""
    tasks, terminals, identifiers = [], [], set()
    eligible_parts = []
    for part in parts:
        category = part.get("category")
        if category not in ROUTES:
            continue
        part_id = str(part.get("id") or _stable_id(part.get("name"), len(eligible_parts)))
        if part_id in identifiers:
            raise ValueError(f"构件编号重复：{part_id}；请先审核去重")
        identifiers.add(part_id)
        eligible_parts.append(part)
        route = list(ROUTES[category])
        finish = _text(part.get("finish")).lower()
        no_paint = any(word in finish for word in ("免漆", "无漆", "不喷漆", "不油漆", "unpainted", "no paint", "unfinished"))
        if category in {"wood", "metal"} and not no_paint and any(word in finish for word in ("漆", "喷粉", "喷涂", "烤", "paint", "coat", "powder")):
            route.append(("finish", "油漆", "表面处理与固化", .30, "确认色号、光泽、基材处理和固化要求，检查成品外观"))
        quantity = _positive(part.get("quantity"))
        previous = None
        for process, trade, title, per_piece, acceptance in route:
            task_id = f"T-{part_id}-{process}"
            tasks.append({
                "id": task_id, "part_id": part_id, "title": f"{part.get('name', '构件')} · {title}",
                "trade": trade, "process": process, "hours": round(per_piece * quantity, 3) if quantity else None,
                "dependencies": [previous] if previous else [], "status": "draft", "assignee": None,
                "completed_quantity": 0, "progress_recorded": True, "priority": 0, "execution_version": 0,
                "rule_id": f"{RULE_VERSION}/{category}/{process}", "acceptance": acceptance,
                "source": dict(part.get("source") or {}), "quantity": part.get("quantity"),
                "estimate_basis": f"初始工时假设 {per_piece:.2f} 小时/件 × 构件数量；班组需按设备和实际做法校准",
                "issues": list(part.get("issues") or []),
            })
            previous = task_id
        if previous:
            terminals.append(previous)
    if not terminals:
        return tasks
    all_known = all(_positive(part.get("quantity")) is not None for part in eligible_parts)
    # Final per-order times are deliberately explicit hypotheses, not part count × a phantom assembly quantity.
    final_steps = [("assembly", "装配", "展示柜柜体总装", 2.0, "部件齐套后总装；复核柜体接口、玻璃安装、五金功能和电气预留位置")]
    if any(p.get("category") == "electrical" for p in eligible_parts):
        final_steps.append(("electrical", "电工", "整柜接线与通电功能核验", .5, "柜体装配完成后，按确认电气方案完成接线及适用检验，记录灯光/回路功能结果"))
    final_steps += [("quality", "质检", "整柜终检", .75, "核对外观、尺寸、稳定性、开启功能及适用电气检验项目，记录检验结果"),
                    ("pack", "包装", "成品包装与发货交接", .5, "完成保护、装箱清单、件号标签与出货交接，检验不合格项须先关闭")]
    previous = None
    for process, trade, title, hours, acceptance in final_steps:
        task_id = "T-FINAL-" + process
        tasks.append({"id": task_id, "part_id": None, "title": title, "trade": trade, "process": process,
                      "hours": hours if all_known else None, "dependencies": [previous] if previous else list(terminals),
                      "status": "draft", "assignee": None, "rule_id": f"{RULE_VERSION}/final/{process}",
                      "completed_quantity": 0, "progress_recorded": True, "priority": 0, "execution_version": 0,
                      "acceptance": acceptance, "source": {"file": "", "reference": "本订单全部已识别构件"},
                      "quantity": 1, "estimate_basis": f"初始单订单工时假设 {hours} 小时；按整柜数量和难度审核调整",
                      "issues": [] if all_known else ["构件数量不完整，最终工时待确认"]})
        previous = task_id
    return tasks


def _measure(part, unit):
    qty = _positive(part.get("quantity"))
    if qty is None:
        return None, "缺少有效构件数量"
    if unit == "piece":
        return qty, None
    if unit == "kg":
        weight = _positive(part.get("weight_kg"))
        return (qty * weight, None) if weight else (None, "按千克计价缺少明确单件重量 weight_kg")
    keys = {"meter": ["length"], "m2": ["length", "width"], "m3": ["length", "width", "thickness"]}.get(unit)
    if keys is None:
        return None, "计价单位不支持"
    values = [_positive(part.get(key)) for key in keys]
    if any(v is None for v in values):
        return None, "计价缺少有效尺寸 " + "/".join(keys)
    return qty * math.prod(values) / (1000 ** len(values)), None


def estimate_quote(parts: list, tasks: list, settings: dict | None = None) -> dict:
    """Calculate known costs and explicitly incomplete quotations without zero-price substitution."""
    settings = settings or {}
    missing, assumptions, lines = [], [], []
    def nonnegative_setting(key, default=0, below_one=False):
        raw = settings.get(key, default)
        value = _number(raw)
        if value is None or value < 0 or (below_one and value >= 1):
            missing.append(f"{key} 无效，应为{'[0,1)' if below_one else '非负数'}")
            return default
        return value
    loss_rate = nonnegative_setting("loss_rate")
    overhead_rate = nonnegative_setting("overhead_rate")
    margin_rate = nonnegative_setting("margin_rate", below_one=True)
    outsourcing = nonnegative_setting("outsourcing_cost")
    material_rates = settings.get("material_rates") or {}
    hourly_rates = settings.get("hourly_rates") or {}
    if not isinstance(material_rates, dict):
        missing.append("material_rates 必须为材料或类别到单价的映射")
        material_rates = {}
    if not isinstance(hourly_rates, dict):
        missing.append("hourly_rates 必须为工种到时薪的映射")
        hourly_rates = {}
    material_cost = waste_cost = labor_cost = 0
    if not parts:
        missing.append("没有构件，不能生成完整报价")
    for part in parts:
        label = part.get("name") or part.get("id") or "未命名构件"
        material = part.get("material")
        rate = material_rates.get(material, material_rates.get(part.get("category")))
        if part.get("unit_price") is not None:
            rate = {"unit_price": part.get("unit_price"), "pricing_unit": part.get("pricing_unit")}
        if isinstance(rate, (int, float)) and not isinstance(rate, bool):
            rate = {"unit_price": rate, "pricing_unit": "piece"}
        rate = rate if isinstance(rate, dict) else {}
        price = _number(rate.get("unit_price"))
        unit = PRICE_UNITS.get(_text(rate.get("pricing_unit")).lower())
        quantity, measure_error = _measure(part, unit)
        reasons = []
        if not material:
            reasons.append("缺少材料/型号")
        if price is None or price < 0:
            reasons.append("缺少有效材料单价")
        if not unit:
            reasons.append("缺少有效计价单位")
        elif measure_error:
            reasons.append(measure_error)
        local_loss = _number(rate.get("loss_rate", loss_rate))
        if local_loss is None or local_loss < 0:
            reasons.append("材料损耗率无效")
        amount = round(price * quantity, 4) if not reasons else None
        line = {"kind": "material", "item_id": part.get("id"), "name": label, "quantity": quantity,
                "unit": unit, "unit_price": price, "amount": amount, "status": "unpriced" if reasons else "priced"}
        if reasons:
            line["reason"] = "；".join(reasons)
            missing.append(f"{label}：{line['reason']}")
        else:
            material_cost += amount
            waste = amount * local_loss
            waste_cost += waste
            line["waste_cost"] = round(waste, 4)
            line["loss_rate"] = local_loss
        lines.append(line)
    if parts and not tasks:
        missing.append("尚无工艺任务或工种未明确，人工成本未计价")
    known_part_ids = {task.get("part_id") for task in tasks if task.get("part_id")}
    for part in parts:
        if part.get("id") not in known_part_ids:
            missing.append(f"{part.get('name', part.get('id'))}：缺少工艺任务，人工成本不完整")
    for task in tasks:
        hours, price = _number(task.get("hours")), _number(hourly_rates.get(task.get("trade")))
        reasons = []
        if hours is None or hours < 0:
            reasons.append("缺少有效工时")
        if price is None or price < 0:
            reasons.append(f"缺少 {task.get('trade')} 工种时薪")
        amount = hours * price if not reasons else None
        line = {"kind": "labor", "item_id": task.get("id"), "name": task.get("title"), "quantity": hours,
                "unit": "hour", "unit_price": price, "amount": round(amount, 4) if amount is not None else None,
                "status": "unpriced" if reasons else "priced"}
        if reasons:
            line["reason"] = "；".join(reasons)
            missing.append(f"{task.get('title')}：{line['reason']}")
        else:
            labor_cost += amount
        lines.append(line)
    known_subtotal = material_cost + labor_cost + waste_cost + outsourcing
    overhead_cost = known_subtotal * overhead_rate
    total = known_subtotal + overhead_cost
    assumptions.append("币种 CNY；不含税、运输、现场安装、设备折旧等未显式计入的费用")
    assumptions.append("工时来自可修改的初始规则假设，需按本厂历史工时校准；总装按单订单估算")
    if any(part.get("review_status") != "approved" for part in parts):
        assumptions.append("包含待审核构件；此结果为测算草稿，须完成图纸/BOM/工艺与价格审核后使用")
    missing = list(dict.fromkeys(missing))
    return {"currency": "CNY", "complete": not missing, "material_cost": round(material_cost, 2),
            "labor_cost": round(labor_cost, 2), "waste_cost": round(waste_cost, 2),
            "outsourcing_cost": round(outsourcing, 2), "overhead_cost": round(overhead_cost, 2),
            "total_cost": round(total, 2) if not missing else None,
            "suggested_price": round(total / (1 - margin_rate), 2) if not missing else None,
            "margin_rate": margin_rate, "known_subtotal": round(known_subtotal, 2),
            "missing": missing, "lines": lines, "assumptions": assumptions}
