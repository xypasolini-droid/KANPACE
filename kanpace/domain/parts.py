"""Production BOM completeness rules, shared by review, release and the assistant."""
import math

from kanpace.core.constants import CATEGORIES


def part_blockers(part):
    missing = []
    if part.get('draft_only'):
        return [str(part.get('name') or '未命名项目') + '：拆单草稿须细化并复核为生产 BOM 后才能生成任务']
    if not part.get('name') or part.get('name') in ('未命名构件', '未命名部件'):
        missing.append('部件名称')
    if not part.get('material') or str(part.get('material')).lower() in ('unknown', '未知', '待确认'):
        missing.append('材质')
    if part.get('category') not in CATEGORIES:
        missing.append('类别（wood/metal/glass/electrical/hardware）')
    for key in ['quantity'] + (['length', 'width', 'thickness'] if part.get('category') in {'wood', 'metal', 'glass'} else []):
        value = part.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            missing.append({'length': '长度', 'width': '宽度', 'thickness': '厚度', 'quantity': '数量'}[key])
    qty = part.get('quantity')
    if isinstance(qty, (int, float)) and math.isfinite(qty) and qty > 0 and not float(qty).is_integer():
        missing.append('数量必须为整件数（长度计价请用计价单位）')
    if part.get('category') in {'wood', 'metal'} and not part.get('finish'):
        missing.append('表面处理（无需处理请明确填原色/免漆）')
    if part.get('unit') != 'mm':
        missing.append('尺寸单位需明确为 mm')
    return [str(part.get('name') or '未命名部件') + '：缺少/无效 ' + field for field in missing]
