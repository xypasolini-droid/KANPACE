"""Existing local application defaults; no customer data or runtime state."""
from pathlib import Path

BASE = Path(__file__).resolve().parents[2]
MAX_UPLOAD = 20 * 1024 * 1024
MAX_CAD_UPLOAD = 128 * 1024 * 1024
MAX_PDF_UPLOAD = 64 * 1024 * 1024
# Base64 expands the largest allowed native CAD file by 4/3, plus metadata.
MAX_BODY = ((MAX_CAD_UPLOAD + 2) // 3) * 4 + 1024 * 1024
ROLES = ['木工', '五金', '油漆', '玻璃', '电工', '装配', '质检', '包装']
CATEGORIES = {'wood', 'metal', 'glass', 'electrical', 'hardware'}
PAUSE_REASONS = {'material', 'quality', 'equipment', 'urgent', 'other'}
COLLECTIONS = ('projects', 'documents', 'parts', 'tasks', 'events', 'people')
DEFAULT_SETTINGS = {
    'material_rates': {'wood': {'unit_price': 135, 'pricing_unit': 'm2'},
        'metal': {'unit_price': 420, 'pricing_unit': 'm2'},
        'glass': {'unit_price': 185, 'pricing_unit': 'm2'},
        'electrical': {'unit_price': 65, 'pricing_unit': 'piece'},
        'hardware': {'unit_price': 18, 'pricing_unit': 'piece'}},
    'hourly_rates': {'木工': 55, '五金': 65, '油漆': 60, '玻璃': 55,
                     '电工': 65, '装配': 50, '质检': 45, '包装': 40},
    'loss_rate': 0.08, 'overhead_rate': 0.12, 'margin_rate': 0.25,
    'outsourcing_cost': 0, 'currency': 'CNY', 'rates_note': '演示参考单价；请替换为本厂实际采购价及工时单价。', 'rates_confirmed': False,
}
