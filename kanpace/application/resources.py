"""ResourceService: application behavior, independent of HTTP startup.

The caller owns the transaction. Cross-service work uses the manufacturing port,
so state transitions, source revision checks and audit records stay atomic.
"""
from __future__ import annotations

from kanpace.application.ports import ManufacturingPort
from kanpace.core.errors import APIError
from kanpace.core.validation import now
from kanpace.core.validation import number
from kanpace.core.validation import uid
import engine
import json
import operations


class ResourceService:
    def __init__(self, store: ManufacturingPort):
        self.store = store

    def save_person(self, con, data, person_id=None):
        person = self.store.get(con, 'people', person_id) if person_id else {'id': uid('person'), 'created_at': now()}
        fields = operations.validate_person_update(self.store, con, person, data)
        operations.reassign_person_tasks(self.store, con, person, fields)
        operations.release_person_badges(self.store, con, person, fields)
        person.update(fields)
        person['version'] = person.get('version', 0) + 1
        person['updated_at'] = now()
        self.store.put(con, 'people', person)
        self.store.event(con, None, 'person_updated' if person_id else 'person_created', '保存人员与技能：' + person['name'], person_id=person['id'])
        return person

    def update_settings(self, con, data):
        settings = self.store.settings(con)
        aliases = {'rates': 'material_rates', 'labor_rates': 'hourly_rates', 'scrap_rate': 'loss_rate', 'markup': 'margin_rate'}
        for alias, canonical in aliases.items():
            if alias in data and canonical not in data:
                data[canonical] = data[alias]
        for key in ('loss_rate', 'overhead_rate', 'margin_rate', 'outsourcing_cost'):
            if key in data:
                value = number(data[key], key, maximum=1e8 if key == 'outsourcing_cost' else 10)
                if key == 'margin_rate' and value >= 1:
                    raise APIError(400, '毛利率必须小于 1')
                settings[key] = value
        if 'hourly_rates' in data:
            if not isinstance(data['hourly_rates'], dict):
                raise APIError(400, 'hourly_rates 必须为对象')
            settings['hourly_rates'] = {str(k): number(v, '工时单价') for k, v in data['hourly_rates'].items()}
        if 'material_rates' in data:
            if not isinstance(data['material_rates'], dict):
                raise APIError(400, 'material_rates 必须为对象')
            rates = {}
            for material, value in data['material_rates'].items():
                if isinstance(value, dict):
                    unit = value.get('pricing_unit')
                    if unit not in ('m2', 'm3', 'piece', 'kg', 'meter'):
                        raise APIError(400, '计价单位无效：' + str(unit))
                    rates[str(material)] = {'unit_price': number(value.get('unit_price'), '材料单价'), 'pricing_unit': unit}
                    if 'loss_rate' in value:
                        rates[str(material)]['loss_rate'] = number(value['loss_rate'], '损耗率', maximum=10)
                else:
                    rates[str(material)] = number(value, '材料单价')
            settings['material_rates'] = rates
        if 'rates_confirmed' in data:
            if not isinstance(data['rates_confirmed'], bool):
                raise APIError(400, 'rates_confirmed 必须为 true 或 false')
            settings['rates_confirmed'] = data['rates_confirmed']
        settings['updated_at'] = now()
        con.execute("UPDATE config SET value=? WHERE key='settings'", (json.dumps(settings, ensure_ascii=False, allow_nan=False),))
        self.store.event(con, None, 'settings_changed', '更新本机报价参数')
        return settings

    def update_project_costs(self, con, project_id, data):
        project = self.store.get(con, 'projects', project_id)
        self.store.require_project_open(project)
        if 'outsourcing_cost' not in data:
            raise APIError(400, '请提供本订单 outsourcing_cost')
        cost = number(data['outsourcing_cost'], '本订单外协费用', maximum=1e8)
        settings = dict(project.get('quote_settings') or {})
        previous = settings.get('outsourcing_cost', self.store.settings(con).get('outsourcing_cost', 0))
        settings['outsourcing_cost'] = cost
        project['quote_settings'] = settings
        project['updated_at'] = now()
        self.store.put(con, 'projects', project)
        self.store.event(con, project_id, 'project_costs_changed', '更新本订单外协费用：¥' + str(cost),
                   previous_outsourcing_cost=previous, outsourcing_cost=cost)
        return project

    def quote(self, con, project_id):
        project = self.store.get(con, 'projects', project_id)
        parts = self.store.active_parts(con, project_id)
        tasks = self.store.active_tasks(con, project_id)
        fresh_tasks = [t for t in tasks if t.get('revision') == project['revision'] and t['status'] != 'invalidated']
        if not fresh_tasks and parts and not project.get('industry_id'):
            fresh_tasks = engine.generate_tasks(parts)
        settings = self.store.settings(con)
        rates_confirmed = settings.get('rates_confirmed', False)
        local_costs = project.get('quote_settings') or {}
        if 'outsourcing_cost' in local_costs:
            settings['outsourcing_cost'] = local_costs['outsourcing_cost']
        result = engine.estimate_quote(parts, fresh_tasks, settings)
        result['outsourcing_scope'] = 'project' if 'outsourcing_cost' in local_costs else 'legacy_global_default'
        result['rates_confirmed'] = rates_confirmed
        result['rate_provenance'] = '已确认的本厂参数' if rates_confirmed else '未确认的演示参考单价'
        result.update({'project_id': project_id, 'revision': project['revision'], 'demo': project.get('demo', False),
                       'items': result.get('lines', []), 'total': result.get('suggested_price'),
                       'subtotal': result.get('total_cost'), 'material_total': result.get('material_cost'),
                       'labor_total': result.get('labor_cost'), 'markup': result.get('margin_rate'),
                       'provisional': True, 'notes': result.get('assumptions', []) + [
                           '规则工时与参考单价形成估算；正式报价须本厂负责人复核。',
                           'BOM 数量按整单计算，项目套数不重复乘算。']})
        if not rates_confirmed:
            result['notes'].insert(0, '当前单价仍为未确认的演示参考值，即使项目为真实订单也不能据此对外报价。请在报价参数中核实并保存确认。')
        if not parts:
            result.update({'complete': False, 'total_cost': None, 'suggested_price': None, 'total': None, 'subtotal': None})
            result.setdefault('missing', []).append('项目没有部件')
        if project.get('industry_id') and not fresh_tasks:
            result.update({'complete': False, 'total_cost': None, 'suggested_price': None,
                           'total': None, 'subtotal': None, 'labor_cost': None, 'labor_total': None})
            result.setdefault('missing', []).append('尚未按本厂行业流程生成工序，人工成本待核定')
        if any(not p['approved'] for p in parts):
            result['notes'].append('存在未审核部件，报价未完成工程审核。')
        return result
