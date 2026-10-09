"""BootstrapService: application behavior, independent of HTTP startup.

Initialization owns one write transaction. Seed work uses that same connection,
so settings, personnel, demo orders and their audit records remain atomic.
"""
from __future__ import annotations

import json

from kanpace.application.ports import ManufacturingPort
from kanpace.core.constants import DEFAULT_SETTINGS, ROLES
from kanpace.core.validation import now
from kanpace.core.validation import uid


class BootstrapService:
    def __init__(self, store: ManufacturingPort):
        self.store = store

    def initialize(self, seed=True, empty=False):
        """Preserve legacy startup defaults without making persistence seed data."""
        with self.store.write_transaction() as con:
            # Recheck the persisted identity under the writer lock. Reopening a
            # customer instance must never introduce demo business records.
            empty = empty or bool(con.execute("SELECT 1 FROM config WHERE key='factory_instance'").fetchone())
            con.execute('INSERT OR IGNORE INTO config VALUES (?,?)', ('settings', json.dumps({'material_rates':{},'hourly_rates':{},'currency':'CNY','rates_note':'请填写本厂核实的人工与材料单价','rates_confirmed':False} if empty else DEFAULT_SETTINGS, ensure_ascii=False)))
            if not empty and not self.store.all(con, 'people'):
                names = ['张师傅', '陈师傅', '刘师傅', '吴师傅', '赵师傅', '李师傅', '周师傅', '孙师傅']
                for i, role in enumerate(ROLES):
                    self.store.put(con, 'people', {'id': 'person_' + str(i + 1), 'name': names[i], 'role': role,
                        'skills': [role], 'capacity_minutes': 480, 'demo': True})
            if seed and not empty and not self.store.all(con, 'projects'):
                self.store.seed(con)
            marker = con.execute("SELECT value FROM config WHERE key='factory_instance'").fetchone()
            self.store.instance_id = json.loads(marker['value']).get('id') if marker else None

    def seed(self, con):
        project = self.store.new_project(con, {'name': '璞玉 · 珠宝中岛展示柜', 'client': '演示项目 · 非真实生产数据',
                                       'due_date': '2026-09-18', 'quantity': 1}, demo=True)
        entries = [('柜体侧板', '阻燃夹板', 'wood', 1100, 580, 18, 2, '哑光烤漆'),
                   ('柜底板', '阻燃夹板', 'wood', 1464, 580, 18, 1, '哑光烤漆'),
                   ('拉丝不锈钢包边', '304不锈钢', 'metal', 1500, 80, 1.2, 2, '拉丝'),
                   ('超白钢化玻璃罩', '超白钢化玻璃', 'glass', 1500, 600, 8, 1, '磨边'),
                   ('高显指灯带', 'LED灯带', 'electrical', 1500, 10, 5, 2, ''),
                   ('缓冲铰链', '不锈钢铰链', 'hardware', 80, 40, 2, 4, '')]
        for name, material, category, length, width, thickness, quantity, finish in entries:
            self.store.put(con, 'parts', {'id': uid('part'), 'project_id': project['id'], 'name': name,
                'material': material, 'category': category, 'length': length, 'width': width, 'thickness': thickness,
                'quantity': quantity, 'finish': finish, 'unit': 'mm', 'review_status': 'approved', 'issues': [],
                'source': {'file': '内置演示 BOM', 'reference': '人工示例', 'revision': 'DEMO'},
                'revision': project['revision'], 'demo': True, 'created_at': now()})
        self.store.generate(con, project['id'])
        self.store.release(con, project['id'])
        self.store.auto_assign(con, project['id'])
        tasks = self.store.active_tasks(con, project['id'])
        for task in tasks:
            if not task['dependencies']:
                task['status'] = 'done'
                task['started_at'] = now()
                task['completed_at'] = now()
                self.store.put(con, 'tasks', task)
        self.store.event(con, project['id'], 'demo_initialized', '演示数据已初始化；报工状态与参考单价仅用于体验。')
