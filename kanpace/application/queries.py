"""QueryService: application behavior, independent of HTTP startup.

The caller owns the transaction. Cross-service work uses the manufacturing port,
so state transitions, source revision checks and audit records stay atomic.
"""
from __future__ import annotations

from kanpace.application.ports import ManufacturingPort
from kanpace.core.constants import COLLECTIONS


class QueryService:
    def __init__(self, store: ManufacturingPort):
        self.store = store

    def state(self, con):
        state = {name: self.store.all(con, name) for name in COLLECTIONS}
        for doc in state['documents']:
            doc['existing_drafts'] = self.store.related_order_drafts(con, doc.get('sha256'), state['projects'])
        state['settings'] = self.store.settings(con)
        state['capabilities'] = {
            'mode': 'isolated_local_factory' if self.store.instance_id else 'local_single_workstation', 'native_cad_extraction': False,
            'imports': ['CSV BOM', 'JSON BOM', '有明确元数据的 ASCII DXF'],
            'archive_only': ['SLDPRT', 'SLDASM', 'DWG', 'STEP'],
            'visual_imports': ['PDF 图纸预览（不自动推算 BOM）', 'JPG / PNG / WebP 项目效果图（外观参考）'],
            'assignment': '按工种技能与在途预计工时的确定性启发式分派',
            'notice': '原生 CAD 需在 CAD 软件导出 BOM 或带元数据的 DXF；无在线 AI 调用。工艺、成本与派工均须人工复核。',
        }
        return state
