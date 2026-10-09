// Read-only presentation geometry. Never supplies manufacturing dimensions or tasks.
const dimensionKeys = ['length_mm', 'width_mm', 'height_mm'];
const validDimension = value => typeof value === 'number' && Number.isFinite(value) && value > 0 && value <= 50000;

export function previewDimensions(part) {
  const raw = String(part.specification || '').trim();
  // A diameter and height are explicit; a round-sounding name alone is not geometry.
  const cylinder = raw.match(/^[φΦϕØ⌀直径]*\s*(\d+(?:\.\d+)?)\s*[×xX*]\s*(\d+(?:\.\d+)?)\s*(?:mm|毫米)?$/);
  if (/^[φΦϕØ⌀]|^直径/.test(raw) && cylinder && (part.unit === 'mm' || /(?:mm|毫米)$/.test(raw))) {
    const diameter = Number(cylinder[1]), height = Number(cylinder[2]);
    if ([diameter, height].every(validDimension)) return {x: diameter, y: height, z: diameter, shape: 'cylinder', basis: '直径 × 高度'};
  }
  let values = dimensionKeys.map(key => part.overall_dimensions?.[key]);
  if (!values.every(validDimension)) {
    // Some order cells contain "6010*690*3990=1组" followed by a finish note.
    // Only read a complete, plain three-axis first line; never evaluate sums or arc lengths.
    const firstLine = raw.split(/[\r\n]/)[0];
    const explicit = firstLine.match(/^(\d+(?:\.\d+)?)\s*[×xX*]\s*(\d+(?:\.\d+)?)\s*[×xX*]\s*(\d+(?:\.\d+)?)\s*(mm|毫米)?\s*(?:=\s*\d+(?:\.\d+)?\s*(?:组|套|件|个))?$/);
    if (!explicit || (part.unit !== 'mm' && !explicit[4])) return null;
    values = explicit.slice(1, 4).map(Number);
    if (!values.every(validDimension)) return null;
  }
  // The original order's three axes are retained, never silently swapped.
  return {x: values[0], y: values[2], z: values[1], shape: 'box', basis: '清单三轴外形'};
}

export function appearance(part) {
  const material = [part.material, part.finish].filter(Boolean).join(' ');
  if (/古铜|钛金|闪金|金色/.test(material)) return {color: '#a58b5b', label: '金属色示意'};
  if (/木纹|木饰面|麻布|皮革/.test(material)) return {color: '#c8ad8c', label: '饰面色示意'};
  if (/黑色|黑哑|黑.*烤漆/.test(material)) return {color: '#51565c', label: '深色示意'};
  if (/玻璃/.test(material)) return {color: '#a8c1c7', label: '玻璃色示意'};
  if (/钢|铁|五金|铝/.test(material)) return {color: '#9fa7ad', label: '金属色示意'};
  return {color: '#d0c4b0', label: '中性色示意'};
}

export function buildOverview(state, projectId) {
  const project = (state.projects || []).find(p => p.id === projectId);
  if (!project) throw new Error('未找到当前项目，请返回项目订单重新选择。');
  const parts = (state.parts || []).filter(p => p.project_id === projectId && !p.archived && p.item_level === 'assembly' && !p.procurement_reference_only);
  const items = [], missing = [];
  for (const part of parts) {
    const dimensions = previewDimensions(part);
    if (!dimensions) { missing.push({id: part.id, name: part.name, specification: part.specification || ''}); continue; }
    items.push({id: part.id, name: part.name || '未命名柜型', dimensions, appearance: appearance(part),
      quantity: part.quantity, quantityUnit: part.quantity_unit || '套', specification: part.specification || '',
      source: part.source_file || part.source?.model_file || part.source?.file || '',
      reference: part.source_reference || part.source?.reference || '',
      material: part.material || '', workScopes: part.work_scopes || [],
      outlinePending: dimensions.shape === 'box' && /弧|曲|异形|圆|造型|转角|门楣|吊楣/.test(part.name || '')});
  }
  return {project: {id: project.id, name: project.name, demo: Boolean(project.demo), closed: Boolean(project.is_closed || ['completed','shipped'].includes(project.fulfillment_status))}, items, missing, total: parts.length};
}
