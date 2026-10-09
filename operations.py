"""Versioned factory resources and explicitly reviewed, object-based workflow packages.

No seed writes, hardware actions, or inferred drawing geometry. Callers own the
SQLite write transaction, so validation and each mutation are atomic.
"""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import math
import re
from uuid import uuid4

import fulfillment

FACTORY_TYPES = ('cabinet', 'machinery', 'site')
RESOURCE_KINDS = {'factory': 'factories', 'team': 'teams', 'workcenter': 'workcenters'}
INDUSTRY_METADATA_KEYS = ('industry_id', 'variant_id', 'industry_name', 'variant_name', 'industry_origin', 'object_fields',
                          'measurement_note', 'source_requirements', 'object_label', 'object_unit')


class OperationError(Exception):
    def __init__(self, status, message, details=None):
        self.status, self.message, self.details = status, message, details
        super().__init__(message)


def fail(message, status=400, code='invalid_operation', **details):
    raise OperationError(status, message, {'code': code, **details})


def stamp():
    return datetime.now(timezone.utc).isoformat(timespec='microseconds')


def uid(prefix):
    return prefix + '_' + uuid4().hex[:16]


def string(value, label, required=False, limit=1000):
    value = '' if value is None else value
    if not isinstance(value, str) or len(value.strip()) > limit or (required and not value.strip()):
        fail(label + '须为有效文字' + ('，不能为空' if required else ''))
    return value.strip()


def integer(value, label, minimum=0, maximum=1000000000):
    if type(value) not in (int, float) or not math.isfinite(value) or int(value) != value or not minimum <= value <= maximum:
        fail(label + '须为有效整数')
    return int(value)


def positive(value, label, maximum=10000000, nullable=True):
    if value is None and nullable:
        return None
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 < value <= maximum:
        fail(label + '须为正数，未知时留空')
    return round(value, 4)


def string_list(value, label, maximum=30, required=False, item_limit=500):
    if not isinstance(value, list) or len(value) > maximum:
        fail(label + '须为列表')
    result = list(dict.fromkeys(string(item, label, True, item_limit) for item in value))
    if required and not result:
        fail(label + '不能为空')
    return result


def check_fields(data, allowed):
    if not isinstance(data, dict) or set(data) - set(allowed):
        fail('提交内容包含未知字段', fields=sorted(set(data) - set(allowed)) if isinstance(data, dict) else [])


def get(store, con, kind, identifier):
    identifier = string(identifier, '记录编号', True, 128)
    result = next((row for row in store.all(con, kind) if row['id'] == identifier), None)
    if not result:
        fail('未找到记录：' + identifier, 404, 'not_found')
    return result


def expected(item, data):
    if integer(data.get('expected_version'), '数据版本') != item.get('version', 0):
        fail('记录已更新，请刷新后重新保存', 409, 'version_conflict', version=item.get('version', 0))


def factory_type(value):
    if value not in FACTORY_TYPES:
        fail('请选择展柜工厂、机械设备工厂或工程现场')
    return value


def ensure_factory(store, con, identifier, required=True):
    if not identifier and not required:
        return None
    return get(store, con, 'factories', identifier)


def ensure_team(store, con, identifier, factory_id):
    if not identifier:
        return None
    team = get(store, con, 'teams', identifier)
    if team['factory_id'] != factory_id:
        fail('班组与工厂归属不一致', 409, 'factory_mismatch')
    return team


def active_tasks(store, con):
    projects = {p['id']: p for p in store.all(con, 'projects')}
    return [t for t in store.all(con, 'tasks') if not t.get('archived') and t.get('status') not in ('done', 'invalidated')
            and not fulfillment.is_closed(projects.get(t.get('project_id'), {}))
            and not projects.get(t.get('project_id'), {}).get('archived')]


def assignment_issues(project, person):
    """Legacy unbound projects remain usable; explicitly bound projects isolate staff."""
    if not person:
        return ['请先分派负责人']
    issues = []
    if person.get('employment_status', 'active') != 'active':
        issues.append('负责人已离职，请重新分派')
    if project.get('factory_id') and person.get('factory_id') != project['factory_id']:
        issues.append('负责人未归属本工厂，请先调整人员归属或分派')
    if bool(project.get('demo')) != bool(person.get('demo')):
        issues.append('真实项目与演示人员不能混用')
    return issues


def resource_base(store, con, kind, data, identifier):
    item = deepcopy(get(store, con, kind, identifier)) if identifier else {'id': uid(kind[:-1]), 'created_at': stamp(), 'version': 0}
    if identifier:
        expected(item, data)
    elif 'expected_version' in data and integer(data['expected_version'], '数据版本') != 0:
        fail('新记录版本须为 0')
    item.update(name=string(data.get('name', item.get('name')), '名称', True, 120),
                note=string(data.get('note', item.get('note')), '备注', limit=2000))
    return item


def finish_resource(store, con, kind, item):
    item.update(version=item.get('version', 0) + 1, updated_at=stamp())
    store.put(con, kind, item)
    store.event(con, None, 'resource_saved', '保存组织资源：' + item['name'], resource_kind=kind, resource_id=item['id'])
    return item


def save_factory(store, con, data, identifier=None):
    check_fields(data, {'name', 'factory_type', 'note', 'expected_version'})
    item = resource_base(store, con, 'factories', data, identifier)
    typ = factory_type(data.get('factory_type', item.get('factory_type')))
    if identifier and typ != item['factory_type']:
        linked = any(p.get('factory_id') == identifier for p in store.all(con, 'projects'))
        if linked:
            fail('已有项目使用此工厂，不能改变行业类型', 409)
    item['factory_type'] = typ
    return {'factory': finish_resource(store, con, 'factories', item)}


def save_team(store, con, data, identifier=None):
    check_fields(data, {'name', 'factory_id', 'leader_id', 'note', 'expected_version'})
    item = resource_base(store, con, 'teams', data, identifier)
    factory = ensure_factory(store, con, data.get('factory_id', item.get('factory_id')))
    if identifier and item['factory_id'] != factory['id']:
        if any(p.get('team_id') == identifier for p in store.all(con, 'people')) or any(w.get('team_id') == identifier for w in store.all(con, 'workcenters')):
            fail('班组仍有关联人员或工作中心，不能跨工厂移动', 409)
    leader_id = data.get('leader_id', item.get('leader_id')) or None
    if leader_id:
        leader = get(store, con, 'people', leader_id)
        if leader.get('factory_id') != factory['id'] or leader.get('demo'):
            fail('班组负责人须为本工厂真实人员', 409)
    item.update(factory_id=factory['id'], leader_id=leader_id)
    return {'team': finish_resource(store, con, 'teams', item)}


def save_workcenter(store, con, data, identifier=None):
    check_fields(data, {'name', 'factory_id', 'team_id', 'kind', 'capacity_minutes', 'note', 'expected_version'})
    item = resource_base(store, con, 'workcenters', data, identifier)
    factory = ensure_factory(store, con, data.get('factory_id', item.get('factory_id')))
    if identifier and factory['id'] != item['factory_id']:
        if (any(t.get('workcenter_id') == identifier for t in active_tasks(store, con))
                or any(n.get('workcenter_id') == identifier for t in store.all(con, 'workflow_templates') for n in t.get('nodes', []))):
            fail('工作中心仍有关联流程模板或在途任务，不能跨工厂移动', 409)
    team = ensure_team(store, con, data.get('team_id', item.get('team_id')), factory['id'])
    kind = data.get('kind', item.get('kind', 'station'))
    if kind not in ('equipment', 'station', 'area'):
        fail('工作中心类型须为设备、工位或作业面')
    item.update(factory_id=factory['id'], team_id=team['id'] if team else None, kind=kind,
                capacity_minutes=positive(data.get('capacity_minutes', item.get('capacity_minutes')), '每日容量', maximum=1440))
    return {'workcenter': finish_resource(store, con, 'workcenters', item)}


def validate_person_update(store, con, person, data):
    """Returns fields safe to merge into an existing person; does not write."""
    skills = string_list(data.get('skills', person.get('skills', [])), '技能', required=False, item_limit=40)
    factory = ensure_factory(store, con, data.get('factory_id', person.get('factory_id')), required=False)
    team = ensure_team(store, con, data.get('team_id', person.get('team_id')), factory['id'] if factory else None)
    if team and not factory:
        fail('选择班组前请先选择工厂')
    employee_no = string(data.get('employee_no', person.get('employee_no')), '员工号', limit=200)
    if employee_no and any(p.get('employee_no') == employee_no and p.get('id') != person.get('id')
                           and p.get('factory_id') == (factory['id'] if factory else None) for p in store.all(con, 'people')):
        fail('员工号已被同工厂其他人员使用', 409, 'employee_no_conflict')
    employment_status = data.get('employment_status', person.get('employment_status', 'active'))
    if employment_status not in ('active', 'left'):
        fail('人员状态须为在职或离职')
    future = dict(person, factory_id=factory['id'] if factory else None, skills=skills,
                  employment_status=employment_status, demo=False)
    managed = [t['name'] for t in store.all(con, 'teams') if t.get('leader_id') == person.get('id')
               and t['factory_id'] != future['factory_id']]
    if managed:
        fail('此人仍担任原工厂班组负责人，请先调整班组负责人', 409, 'team_leadership_conflict', teams=managed)
    if employment_status == 'left' and any(t.get('leader_id') == person.get('id') for t in store.all(con, 'teams')):
        fail('此人仍是班组负责人，请先更换班组负责人', 409, 'team_leadership_conflict')
    if person.get('id') and person.get('employment_status', 'active') != 'left' and employment_status == 'left':
        import access_control
        access_control.validate_person_departure(store, con, person['id'])
    fields = {'name': string(data.get('name', person.get('name')), '人员姓名', True, 100), 'skills': skills,
            'role': string(data.get('role', person.get('role') or (skills[0] if skills else '待分工')), '岗位', True, 100),
            'workshop': string(data.get('workshop', person.get('workshop')), '车间', limit=100),
            'employee_no': string(data.get('employee_no', person.get('employee_no')), '员工号', limit=200),
            'factory_id': factory['id'] if factory else None, 'team_id': team['id'] if team else None,
            'capacity_minutes': positive(data.get('capacity_minutes', person.get('capacity_minutes')), '每日可用分钟', maximum=1440),
            'employment_status': employment_status, 'demo': False}
    handoff = person_handoff_tasks(store, con, person, fields)
    running = [t['title'] for t in handoff if t['status'] == 'in_progress']
    if running:
        fail('人员有执行中任务，请先暂停并记录交接，再更新岗位或离职', 409,
             'active_assignment_conflict', tasks=running)
    return fields


def person_handoff_tasks(store, con, person, future):
    """Tasks that need an explicit new owner after a placement/status change."""
    placement = lambda record: (record.get('role') or '', record.get('workshop') or '',
                                tuple(record.get('skills') or ()), record.get('factory_id') or None,
                                record.get('team_id') or None, record.get('employment_status', 'active'))
    if not person.get('id') or placement(person) == placement(future):
        return []
    return [t for t in active_tasks(store, con) if t.get('assignee') == person['id']]


def reassign_person_tasks(store, con, person, future):
    """Remove stale pending assignments; completed attribution is immutable."""
    tasks = person_handoff_tasks(store, con, person, future)
    running = [t['title'] for t in tasks if t['status'] == 'in_progress']
    if running:
        fail('人员有执行中任务，请先暂停并记录交接，再更新岗位或离职', 409,
             'active_assignment_conflict', tasks=running)
    for task in tasks:
        task = deepcopy(task)
        task.update(assignee=None, reassignment_reason='人员调岗或离职，待重新分派',
                    reassignment_from=person['id'])
        store.bump_execution(task)
        store.put(con, 'tasks', task)
        store.event(con, task.get('project_id'), 'task_reassignment_required',
                    (task.get('title') or task['id']) + '：人员资料变化，待重新分派', task_id=task['id'],
                    previous_assignee=person['id'], execution_version=task['execution_version'])
    affected = {task['id'] for task in tasks}
    if affected:
        for job in store.all(con, 'project_dispatches'):
            if job.get('status') in ('completed', 'cancelled'):
                continue
            changed = False
            for worker in job.get('workers', []):
                if worker.get('person_id') != person['id']:
                    continue
                for entry in worker.get('entries', []):
                    if entry.get('task_id') in affected and entry.get('status') != 'completed':
                        entry.update(status='failed', error='负责人调岗或离职，待重新分派')
                        changed = True
                if changed:
                    worker['status'] = 'failed'
            if changed:
                job.update(status='partial_failure', version=job.get('version', 0) + 1, updated_at=stamp())
                store.put(con, 'project_dispatches', job)
                store.event(con, job.get('project_id'), 'project_dispatch_handoff_required',
                            '人员资料变化，项目派工队列需要重新核对', dispatch_id=job['id'],
                            person_id=person['id'], task_ids=sorted(affected))
    return [t['id'] for t in tasks]


def release_person_badges(store, con, person, future):
    if (not person.get('id') or person.get('employment_status', 'active') == 'left'
            or future.get('employment_status', 'active') != 'left'):
        return []
    import access_control
    access_control.revoke_person_accounts(store, con, person['id'])
    released = []
    for binding in store.all(con, 'device_bindings'):
        if binding.get('person_id') != person['id'] or binding.get('archived'):
            continue
        binding.update(archived=True, released_at=stamp(), release_reason='人员离职',
                       version=binding.get('version', 0) + 1, updated_at=stamp())
        store.put(con, 'device_bindings', binding)
        store.event(con, None, 'person_badge_released', '离职人员胸牌已释放，可重新绑定',
                    person_id=person['id'], device_id=binding['device_id'], binding_id=binding['id'])
        released.append(binding['device_id'])
    return released


def save_person(store, con, data, identifier=None):
    check_fields(data, {'name', 'role', 'skills', 'workshop', 'employee_no', 'factory_id', 'team_id', 'capacity_minutes',
                        'employment_status', 'expected_version'})
    item = deepcopy(get(store, con, 'people', identifier)) if identifier else {'id': uid('person'), 'version': 0, 'created_at': stamp()}
    if identifier:
        expected(item, data)
    fields = validate_person_update(store, con, item, data)
    reassign_person_tasks(store, con, item, fields)
    release_person_badges(store, con, item, fields)
    item.update(fields)
    return {'person': finish_resource(store, con, 'people', item)}


def node(identifier, name, trade, predecessors=(), checks=(), acceptance=(), quality=False):
    return {'id': identifier, 'name': name, 'trade': trade, 'predecessors': list(predecessors), 'start_checks': list(checks),
            'acceptance': list(acceptance), 'instructions': '', 'estimated_minutes': None, 'quality_gate': quality, 'workcenter_id': None}


def builtin_templates():
    templates = [
        ('cabinet', '综合展柜工厂', [
            node('technical', '技术拆单与图纸确认', '技术', checks=('施工图与版本已确认',), acceptance=('构件范围与加工要求已复核',)),
            node('wood', '木作加工', '木工', ('technical',), ('木作材料与封边配件齐套',), ('按确认图纸核对尺寸和孔位',)),
            node('paint', '油漆与固化', '油漆', ('wood',), ('色号及表面处理已确认',), ('色泽外观及固化状态合格',)),
            node('metal', '五金加工', '五金', ('technical',), ('型材五金及加工图齐套',), ('尺寸焊接与表面处理合格',)),
            node('glass', '玻璃与外协配套', '外协', ('technical',), ('外协规格与到货计划已确认',), ('到货尺寸及外观检查合格',)),
            node('assembly', '柜体总装', '装配', ('paint', 'metal', 'glass'), ('所需部件与附件齐套',), ('结构连接及开启功能合格',)),
            node('electrical', '灯光接线与测试', '电工', ('assembly',), ('电源与灯具齐套',), ('按确认方案完成回路及功能检查',)),
            node('quality', '成品验收', '质检', ('electrical',), (), ('尺寸外观功能及附件清单已核验',), True),
            node('packing', '装箱与分批交付', '包装', ('quality',), ('验收通过及箱单已核对',), ('柜号部件箱号一致且交付附件齐全',)),
        ]),
        ('machinery', '机械设备装配', [
            node('engineering', '设备图纸与制造清单确认', '工艺工程', checks=('设计版本及设备配置已确认',), acceptance=('装配与检验要求已发布',)),
            node('frame', '机架及机械模块装配', '机械装配', ('engineering',), ('关键机械件齐套',), ('装配尺寸及紧固要求已核验',)),
            node('cabinet', '电控柜与配线准备', '电气装配', ('engineering',), ('电控物料及接线图齐套',), ('端子标识及接线核对完成',)),
            node('assembly', '设备总装', '机械装配', ('frame', 'cabinet'), ('各子装配验收与配置齐套',), ('设备序列号与实际装机清单已核对',)),
            node('debug', '联调与功能测试', '调试', ('assembly',), ('测试方案与场地条件已确认',), ('按测试方案记录结果并关闭异常',)),
            node('quality', '出厂验收', '质检', ('debug',), (), ('出厂测试记录及遗留项已验收',), True),
            node('delivery', '包装交付及设备档案', '交付', ('quality',), ('出厂放行与资料齐套',), ('设备档案和装箱交接清单齐全',)),
        ]),
        ('site', '装修工程现场', [
            node('release', '区域作业面交接', '现场管理', checks=('施工图与区域边界已确认', '前序验收及通道条件已满足'), acceptance=('作业面交接已确认',)),
            node('mep', '隐蔽水电施工', '水电', ('release',), ('作业面放行且材料送达区域',), ('隐蔽部位及回路位置符合确认图纸',)),
            node('hidden', '隐蔽工程验收', '工程验收', ('mep',), (), ('隐蔽验收记录及整改闭环完成',), True),
            node('carpentry', '区域木作与基层', '现场木工', ('hidden',), ('基层材料及施工条件齐备',), ('尺寸基层与收口条件符合要求',)),
            node('finish', '饰面与涂装', '装饰', ('carpentry',), ('湿度养护及表面条件已确认',), ('饰面色泽与收口质量合格',)),
            node('installation', '灯具设备及附件安装', '安装', ('finish',), ('安装物料齐套且区域允许作业',), ('安装与功能检查完成',)),
            node('acceptance', '分区验收与整改交接', '工程验收', ('installation',), (), ('验收及整改记录已确认',), True),
        ]),
    ]
    return [{'id': 'builtin_' + typ + '_v1', 'name': name, 'factory_type': typ, 'factory_id': None,
             'status': 'reference', 'version': 1, 'template_version': 1, 'nodes': nodes, 'source_kind': 'industry_reference'}
            for typ, name, nodes in templates]


def template_by_id(store, con, identifier, published=False):
    template = next((t for t in builtin_templates() + store.all(con, 'workflow_templates') if t['id'] == identifier), None)
    if not template:
        fail('流程模板不存在', 404)
    if published and template.get('status') != 'published':
        fail('请先核对并发布企业流程模板，再用于项目', 409, 'template_not_published')
    return template


def dag_order(nodes):
    ids = {n['id'] for n in nodes}
    done, output = set(), []
    for n in nodes:
        missing = set(n['predecessors']) - ids
        if missing or n['id'] in n['predecessors']:
            fail('工序前置关系包含不存在节点或自身引用', 400, 'invalid_graph', node_id=n['id'], missing=sorted(missing))
    while len(done) < len(nodes):
        ready = [n for n in nodes if n['id'] not in done and set(n['predecessors']) <= done]
        if not ready:
            fail('工序前后关系存在循环，请调整', 400, 'cyclic_graph')
        for n in ready:
            done.add(n['id'])
            output.append(n['id'])
    return output


def validate_nodes(store, con, raw, factory_id=None, publishing=False):
    if not isinstance(raw, list) or not 1 <= len(raw) <= 80:
        fail('流程须包含 1 至 80 个工序')
    nodes = []
    for value in raw:
        check_fields(value, {'id', 'name', 'trade', 'predecessors', 'start_checks', 'acceptance', 'instructions',
                             'estimated_minutes', 'quality_gate', 'workcenter_id'})
        ident = string(value.get('id'), '工序编号', True, 64)
        if not re.fullmatch(r'[A-Za-z0-9_-]+', ident):
            fail('工序编号仅支持字母、数字、横线与下划线')
        wc_id = value.get('workcenter_id') or None
        if wc_id:
            wc = get(store, con, 'workcenters', wc_id)
            if not factory_id or wc['factory_id'] != factory_id:
                fail('模板工作中心必须归属所选工厂', 409, 'factory_mismatch')
        quality = value.get('quality_gate', False)
        if type(quality) is not bool:
            fail('验收放行标记须为布尔值')
        nodes.append({'id': ident, 'name': string(value.get('name'), '工序名称', True, 120),
                      'trade': string(value.get('trade'), '工种', True, 40),
                      'predecessors': string_list(value.get('predecessors', []), '前置工序', maximum=80, item_limit=64),
                      'start_checks': string_list(value.get('start_checks', []), '开工条件'),
                      'acceptance': string_list(value.get('acceptance', []), '验收要求', required=publishing),
                      'instructions': string(value.get('instructions'), '操作要求', limit=3000),
                      'estimated_minutes': positive(value.get('estimated_minutes'), '单工作对象估计工时'),
                      'quality_gate': quality, 'workcenter_id': wc_id})
    if len({n['id'] for n in nodes}) != len(nodes):
        fail('工序编号重复')
    dag_order(nodes)
    return nodes


def save_template(store, con, data, identifier=None, *, industry_metadata=None):
    check_fields(data, {'name', 'factory_type', 'factory_id', 'nodes', 'note', 'source_template_id', 'expected_version'})
    if identifier:
        old = deepcopy(get(store, con, 'workflow_templates', identifier))
        expected(old, data)
        if old['status'] == 'published':
            fail('已发布模板不可修改，请复制为新版本草稿', 409, 'immutable_template')
    else:
        source_id = data.get('source_template_id')
        source = deepcopy(template_by_id(store, con, source_id)) if source_id else {}
        old = {key: value for key, value in source.items() if key in ('name', 'factory_type', 'factory_id', 'nodes', 'note') + INDUSTRY_METADATA_KEYS}
        old.update(id=uid('tpl'), status='draft', version=0, template_version=(source.get('template_version', 0) if source.get('status') != 'reference' else 0) + 1,
                   parent_template_id=source_id, lineage_id=source.get('lineage_id') or source.get('id'), created_at=stamp())
        old['lineage_id'] = old['lineage_id'] or old['id']
    typ = factory_type(data.get('factory_type', old.get('factory_type')))
    factory = ensure_factory(store, con, data.get('factory_id', old.get('factory_id')), required=False)
    if factory and factory['factory_type'] != typ:
        fail('模板行业与工厂类型不一致', 409, 'factory_mismatch')
    old.update(name=string(data.get('name', old.get('name')), '模板名称', True, 120), factory_type=typ,
               factory_id=factory['id'] if factory else None, note=string(data.get('note', old.get('note')), '模板说明', limit=3000),
               nodes=validate_nodes(store, con, data.get('nodes', old.get('nodes')), factory['id'] if factory else None),
               version=old['version'] + 1, updated_at=stamp())
    # Only the reviewed configuration installer supplies an origin snapshot.
    # Ordinary template edits may change a local route but cannot forge its source.
    if industry_metadata is not None:
        for key in INDUSTRY_METADATA_KEYS:
            old[key] = deepcopy(industry_metadata.get(key))
        old['object_fields'] = validate_object_fields(old.get('object_fields', []))
    store.put(con, 'workflow_templates', old)
    store.event(con, None, 'workflow_template_saved', '保存流程模板草稿：' + old['name'], template_id=old['id'])
    return {'template': old}


def publish_template(store, con, identifier, data):
    check_fields(data, {'expected_version'})
    template = deepcopy(get(store, con, 'workflow_templates', identifier))
    expected(template, data)
    if template['status'] != 'draft':
        fail('模板已经发布，请使用该版本或复制新版本', 409)
    template['nodes'] = validate_nodes(store, con, template['nodes'], template.get('factory_id'), publishing=True)
    template.update(status='published', version=template['version'] + 1, published_at=stamp(), updated_at=stamp())
    # Serialize full approved content: later consumers never resolve a mutable draft.
    content = {'nodes': template['nodes'], **{k: template[k] for k in INDUSTRY_METADATA_KEYS if k in template}}
    template['content_hash'] = hashlib.sha256(json.dumps(content, ensure_ascii=False, sort_keys=True, allow_nan=False).encode()).hexdigest()
    store.put(con, 'workflow_templates', template)
    store.event(con, None, 'workflow_template_published', '发布流程模板：' + template['name'], template_id=identifier, content_hash=template['content_hash'])
    return {'template': template}


def require_project(store, con, identifier, revision=None):
    project = get(store, con, 'projects', identifier)
    if project.get('archived') or fulfillment.is_closed(project):
        fail('项目已完成或关闭，请先重新开启', 409, 'project_closed')
    if revision is not None and integer(revision, '工程版本', minimum=1) != project['revision']:
        fail('工程版本已变化，请刷新后重试', 409, 'revision_conflict')
    return project


def validate_object_fields(raw):
    """Small per-industry data schemas; physical amounts do not change batch counts."""
    if raw is None:
        raw = []
    if not isinstance(raw, list) or len(raw) > 20:
        fail('行业对象字段须为最多 20 项的列表')
    fields = []
    for field in raw:
        check_fields(field, {'id', 'label', 'type', 'required', 'unit', 'example', 'help'})
        identifier = string(field.get('id'), '行业字段编号', True, 64)
        if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,63}', identifier):
            fail('行业字段编号须以字母开头，仅支持字母、数字和下划线')
        typ = field.get('type', 'text')
        if typ not in ('text', 'decimal') or type(field.get('required', False)) is not bool:
            fail('行业字段类型或必填标记无效')
        fields.append({'id': identifier, 'label': string(field.get('label'), '行业字段名称', True, 80),
                       'type': typ, 'required': field.get('required', False),
                       'unit': string(field.get('unit'), '行业字段单位', limit=20),
                       'example': string(field.get('example'), '行业字段示例', limit=300),
                       'help': string(field.get('help'), '行业字段说明', limit=500)})
    if len({f['id'] for f in fields}) != len(fields):
        fail('行业字段编号重复')
    return fields


def validate_industry_values(raw, fields):
    raw = {} if raw is None else raw
    definitions = {f['id']: f for f in fields}
    if not isinstance(raw, dict) or set(raw) - set(definitions):
        fail('工作对象包含当前流程未定义的行业字段', 400, 'unknown_industry_field')
    result = {}
    for key, value in raw.items():
        field = definitions[key]
        if value is None or value == '':
            continue
        if field['type'] == 'decimal':
            if type(value) not in (int, float) or not math.isfinite(value) or not 0 < value <= 1000000000000:
                fail(field['label'] + '须为有限正数', 400, 'invalid_industry_value')
            # Keep the provided precision. This is a recorded physical quantity,
            # not an integer batch count or a fabricated unit conversion.
            result[key] = value
        else:
            result[key] = string(value, field['label'], limit=500)
    return result


def missing_industry_fields(objects, fields):
    return [{'object_code': obj['code'], 'field_id': field['id'], 'label': field['label']}
            for obj in objects for field in fields
            if field.get('required') and obj.get('industry_fields', {}).get(field['id']) in (None, '')]


def industry_instructions(obj, fields):
    values = obj.get('industry_fields', {})
    return '；'.join(f['label'] + '：' + str(values[f['id']]) +
                    ((' ' + f['unit']) if f.get('unit') else '')
                    for f in fields if f['id'] in values)


def validate_objects(store, con, project_id, raw, object_fields=None):
    if not isinstance(raw, list) or not 1 <= len(raw) <= 200:
        fail('请填写 1 至 200 个明确工作对象')
    fields = validate_object_fields(object_fields)
    documents = {d['id']: d for d in store.all(con, 'documents', project_id)}
    objects = []
    for value in raw:
        check_fields(value, {'code', 'name', 'location', 'quantity', 'unit', 'instructions', 'document_ids', 'batch_code', 'delivery_group', 'industry_fields'})
        ids = string_list(value.get('document_ids', []), '来源文件', maximum=100, item_limit=128)
        if any(d not in documents for d in ids):
            fail('工作对象引用的文件不存在或不属于此项目', 409, 'foreign_document')
        if any(documents[d].get('superseded') for d in ids):
            fail('工作对象引用的文件已被替代，请选择最新工艺依据', 409, 'superseded_document')
        objects.append({'code': string(value.get('code'), '对象编号', True, 80),
                        'name': string(value.get('name'), '对象名称', True, 150),
                        'location': string(value.get('location'), '位置', limit=250),
                        'quantity': integer(value.get('quantity', 1), '工作对象数量', minimum=1, maximum=100000),
                        'unit': string(value.get('unit', '项'), '数量单位', True, 20),
                        'instructions': string(value.get('instructions'), '工作范围与技术要求', limit=5000),
                        'document_ids': ids, 'batch_code': string(value.get('batch_code'), '批次编号', limit=100),
                        'delivery_group': string(value.get('delivery_group'), '交付批次', limit=100),
                        'industry_fields': validate_industry_values(value.get('industry_fields'), fields)})
    if len({o['code'] for o in objects}) != len(objects):
        fail('工作对象编号重复；分批工作请使用独立对象编号')
    return objects


def compile_tasks(project, workflow, template):
    tasks = []
    fields = template.get('object_fields') or []
    for obj in workflow['objects']:
        mapping = {n['id']: uid('task') for n in template['nodes']}
        for n in template['nodes']:
            minutes = n['estimated_minutes']
            tasks.append({'id': mapping[n['id']], 'project_id': project['id'], 'revision': project['revision'],
                          'part_id': None, 'workflow_id': workflow['id'], 'workflow_version': workflow['version'],
                          'template_id': template['id'], 'template_node_id': n['id'], 'factory_id': workflow['factory_id'],
                          'object_code': obj['code'], 'object_name': obj['name'], 'object_location': obj['location'],
                          'batch_code': obj['batch_code'], 'delivery_group': obj['delivery_group'], 'unit': obj['unit'],
                          'title': obj['code'] + ' ' + obj['name'] + ' · ' + n['name'], 'trade': n['trade'],
                          'process': n['id'], 'hours': round(minutes * obj['quantity'] / 60, 6) if minutes is not None else None,
                          'dependencies': [mapping[d] for d in n['predecessors']], 'status': 'draft', 'assignee': None,
                          'quantity': obj['quantity'], 'completed_quantity': 0, 'progress_recorded': True,
                          'priority': 0, 'execution_version': 0, 'archived': False, 'demo': bool(project.get('demo')),
                          'rule_id': 'workflow/' + template['id'] + '/' + n['id'], 'created_at': stamp(),
                          'instructions': '\n'.join(s for s in (industry_instructions(obj, fields), obj['instructions'], n['instructions']) if s),
                          'industry_id': template.get('industry_id'), 'variant_id': template.get('variant_id'),
                          'industry_fields': deepcopy(obj.get('industry_fields', {})),
                          'object_field_definitions': deepcopy(fields),
                          'acceptance': '；'.join(n['acceptance']), 'acceptance_checks': list(n['acceptance']),
                          'inspection_required': n['quality_gate'], 'start_checks': list(n['start_checks']),
                          'workcenter_id': n['workcenter_id'],
                          'source': {'kind': 'reviewed_work_package', 'reference': workflow['scope_note'],
                                     'document_ids': list(obj['document_ids']), 'object_code': obj['code'],
                                     'industry_origin_hash': (template.get('industry_origin') or {}).get('hash')},
                          'estimate_basis': '企业模板人工配置：分钟/工作对象 × 数量' if minutes is not None else '待班组确认工时',
                          'issues': []})
    return tasks


def workflow_task_replaceable(task):
    """Only untouched drafts can be rebuilt after their engineering source changes."""
    return (task.get('status') == 'draft' or (task.get('status') == 'invalidated' and task.get('previous_status') == 'draft')) \
        and not (task.get('started_at') or task.get('completed_at') or task.get('completed_quantity') or task.get('carried_status') == 'done')


def save_workflow(store, con, project_id, data):
    check_fields(data, {'template_id', 'factory_id', 'expected_revision', 'expected_version', 'objects', 'scope_note'})
    project = require_project(store, con, project_id, data.get('expected_revision'))
    if 'expected_revision' not in data:
        fail('须提供当前工程版本')
    previous = get(store, con, 'project_workflows', project['workflow_id']) if project.get('workflow_id') else None
    if previous:
        expected(previous, data)
    elif integer(data.get('expected_version', 0), '工作包版本') != 0:
        fail('新工作包版本须为 0')
    existing = [t for t in store.all(con, 'tasks', project_id) if not t.get('archived')]
    if any(not workflow_task_replaceable(t) or t.get('workflow_id') != (previous or {}).get('id') for t in existing):
        fail('项目已有生产任务，请使用流程版本影响预览；不能覆盖在制工序', 409, 'existing_production_tasks')
    template = template_by_id(store, con, data.get('template_id'), published=True)
    if template['factory_type'] != project.get('factory_type', 'cabinet'):
        fail('流程模板与项目行业类型不一致', 409, 'factory_mismatch')
    factory = ensure_factory(store, con, data.get('factory_id'))
    if factory['factory_type'] != template['factory_type'] or (template.get('factory_id') and template['factory_id'] != factory['id']):
        fail('所选工厂与流程模板不一致', 409, 'factory_mismatch')
    workflow = {'id': previous['id'] if previous else uid('wf'), 'project_id': project_id, 'revision': project['revision'],
                'factory_id': factory['id'], 'template_id': template['id'], 'template_version': template['template_version'],
                'template_hash': template['content_hash'], 'version': previous['version'] + 1 if previous else 1,
                'objects': validate_objects(store, con, project_id, data.get('objects'), template.get('object_fields')),
                'industry_id': template.get('industry_id'), 'variant_id': template.get('variant_id'),
                'object_fields': deepcopy(template.get('object_fields') or []),
                'scope_note': string(data.get('scope_note'), '工作包依据与范围', True, 5000),
                'status': 'draft', 'created_at': previous['created_at'] if previous else stamp(), 'updated_at': stamp()}
    tasks = compile_tasks(project, workflow, template)
    if len(tasks) > 4000:
        fail('一次工作包最多生成 4000 项工序，请分批组织对象')
    for task in existing:
        task.update(archived=True, status='invalidated', execution_version=task.get('execution_version', 0) + 1)
        store.put(con, 'tasks', task)
    for task in tasks:
        store.put(con, 'tasks', task)
    workflow['task_ids'] = [t['id'] for t in tasks]
    store.put(con, 'project_workflows', workflow)
    project.update(workflow_id=workflow['id'], factory_id=factory['id'], status='review', planned_revision=project['revision'])
    store.put(con, 'projects', project)
    store.event(con, project_id, 'workflow_drafted', '按企业流程建立工作包草稿', workflow_id=workflow['id'], objects=len(workflow['objects']), task_count=len(tasks))
    return {'workflow': workflow, 'tasks': tasks, 'project': project}


def release_blockers(store, con, project):
    """Extra gates for Store.release; does not waive any existing document/BOM gates."""
    if not project.get('workflow_id'):
        return []
    workflow = get(store, con, 'project_workflows', project['workflow_id'])
    issues = []
    if workflow['status'] != 'reviewed':
        issues.append('工作包尚未由负责人复核')
    if workflow['revision'] != project['revision']:
        issues.append('工作包不属于当前工程版本')
    if workflow.get('industry_id'):
        docs = {d['id']: d for d in store.all(con, 'documents', project['id'])}
        if any(d not in docs or docs[d].get('superseded') for obj in workflow['objects'] for d in obj.get('document_ids', [])):
            issues.append('行业工作包仍引用已替代或缺失的工艺文件，请重新关联并复核')
    gaps = missing_industry_fields(workflow['objects'], workflow.get('object_fields') or [])
    if gaps:
        issues.append('行业对象资料未完整：' + '；'.join(g['object_code'] + ' · ' + g['label'] for g in gaps[:10]))
    actual = [t for t in store.all(con, 'tasks', project['id']) if not t.get('archived')]
    if {t['id'] for t in actual} != set(workflow['task_ids']):
        issues.append('工作包工序不完整或混入其他来源，请重新核对')
    if any(t.get('workflow_id') != workflow['id'] or t.get('workflow_version') != workflow['version'] for t in actual):
        issues.append('工作包任务版本不一致')
    return issues


def review_workflow(store, con, project_id, data):
    check_fields(data, {'expected_version', 'reviewer', 'review_note', 'acknowledge_manual_scope'})
    project = require_project(store, con, project_id)
    workflow = deepcopy(get(store, con, 'project_workflows', project.get('workflow_id')))
    expected(workflow, data)
    if workflow['revision'] != project['revision']:
        fail('工程版本已变化，请重建工作包', 409)
    if project.get('status') == 'released':
        fail('工作包已经发布，变更请使用流程迁移', 409)
    if data.get('acknowledge_manual_scope') is not True:
        fail('请确认工作对象、技术范围、来源及工序由人工复核', 409, 'scope_review_required')
    reviewer = string(data.get('reviewer'), '复核人', True, 100)
    note = string(data.get('review_note'), '复核记录', True, 3000)
    missing = [o['code'] for o in workflow['objects'] if not o['document_ids'] and not o['instructions']]
    if missing:
        fail('工作对象须关联来源文件或填写明确技术要求', 409, 'work_scope_missing', objects=missing)
    if workflow.get('industry_id'):
        validate_objects(store, con, project_id, workflow['objects'], workflow.get('object_fields'))
    industry_gaps = missing_industry_fields(workflow['objects'], workflow.get('object_fields') or [])
    if industry_gaps:
        fail('请先补齐工作对象的行业必填资料，再复核工作包', 409, 'industry_fields_missing', fields=industry_gaps)
    workflow.update(status='reviewed', reviewer=reviewer, review_note=note, reviewed_at=stamp(), updated_at=stamp())
    # Review does not alter compilation version; optimistic state update is stamped separately.
    workflow['version'] += 1
    for task_id in workflow['task_ids']:
        task = get(store, con, 'tasks', task_id)
        if task.get('status') not in ('draft', 'done') or task.get('revision') != project['revision']:
            fail('工序状态已改变，请重新核对工作包', 409)
        task['workflow_version'] = workflow['version']
        store.put(con, 'tasks', task)
    store.put(con, 'project_workflows', workflow)
    store.event(con, project_id, 'workflow_reviewed', '复核工作包：' + reviewer, workflow_id=workflow['id'], review_note=note)
    return {'workflow': workflow}


def migration_preview(store, con, project_id, data):
    check_fields(data, {'template_id'})
    project = require_project(store, con, project_id)
    workflow = get(store, con, 'project_workflows', project.get('workflow_id'))
    before = template_by_id(store, con, workflow['template_id'], published=True)
    after = template_by_id(store, con, data.get('template_id'), published=True)
    if after['factory_type'] != project.get('factory_type', 'cabinet') or (after.get('factory_id') and after['factory_id'] != workflow['factory_id']):
        fail('新流程模板不适用于项目所属工厂', 409)
    if (before.get('object_fields') or []) != (after.get('object_fields') or []):
        fail('新流程的行业字段结构已变化，请另建工作包并重新核对对象资料', 409, 'industry_schema_changed')
    old, new = {n['id']: n for n in before['nodes']}, {n['id']: n for n in after['nodes']}
    added, removed = sorted(set(new) - set(old)), sorted(set(old) - set(new))
    changed = sorted(k for k in set(new) & set(old) if old[k] != new[k])
    if (before.get('industry_id'), before.get('variant_id')) != (after.get('industry_id'), after.get('variant_id')):
        changed = sorted(set(new) & set(old))
    affected = set(removed + changed)
    # Downstream production must be reviewed whenever a preceding requirement changes.
    changed_new = set(added + changed)
    while True:
        previous = (len(affected), len(changed_new))
        affected.update(n['id'] for n in old.values() if set(n['predecessors']) & affected)
        changed_new.update(n['id'] for n in new.values() if set(n['predecessors']) & changed_new)
        affected.update(changed_new & set(old))
        if previous == (len(affected), len(changed_new)):
            break
    tasks = [t for t in store.all(con, 'tasks', project_id) if not t.get('archived')]
    ordinary = [t for t in tasks if not t.get('rework_of')]
    impacted = [t for t in ordinary if t.get('template_node_id') in affected]
    blockers = [t for t in tasks if t.get('status') == 'in_progress' or (t.get('rework_of') and t.get('status') != 'done')
                or (t in impacted and (t.get('started_at') or t.get('completed_quantity') or t.get('status') == 'done'))]
    context = {'project_id': project_id, 'revision': project['revision'], 'workflow_version': workflow['version'],
               'target_template_id': after['id'], 'target_hash': after['content_hash'],
               'tasks': sorted((t['id'], t.get('execution_version', 0), t.get('status')) for t in tasks)}
    token = hashlib.sha256(json.dumps(context, sort_keys=True).encode()).hexdigest()
    compact = lambda t: {key: t.get(key) for key in ('id', 'title', 'status', 'completed_quantity', 'execution_version')}
    return {'project_id': project_id, 'workflow_id': workflow['id'], 'current_template_id': before['id'],
            'template_id': after['id'], 'added': added, 'removed': removed, 'changed': changed,
            'affected_tasks': [compact(t) for t in impacted], 'preserved_tasks': [compact(t) for t in ordinary if t not in impacted],
            'historical_reworks': [compact(t) for t in tasks if t.get('rework_of') and t.get('status') == 'done'],
            'blockers': [dict(compact(t), reason=('仍有返工未完成，请先闭环返工及复检' if t.get('rework_of') and t.get('status') != 'done' else '工序执行中，请先暂停并交接' if t.get('status') == 'in_progress' else '受影响工序已有实绩，须先明确返工或另建工作范围')) for t in blockers],
            'can_migrate': not blockers, 'impact_token': token, 'expected_version': workflow['version'], 'expected_revision': project['revision']}


def migrate_workflow(store, con, project_id, data):
    check_fields(data, {'template_id', 'expected_version', 'expected_revision', 'impact_token', 'review_note'})
    project = require_project(store, con, project_id, data.get('expected_revision'))
    old_wf = get(store, con, 'project_workflows', project.get('workflow_id'))
    expected(old_wf, data)
    preview = migration_preview(store, con, project_id, {'template_id': data.get('template_id')})
    if data.get('impact_token') != preview['impact_token']:
        fail('流程或任务状态已变化，请重新预览迁移影响', 409, 'migration_changed')
    if not preview['can_migrate']:
        fail('受影响工序已有执行实绩，不能自动迁移', 409, 'migration_in_progress', tasks=preview['blockers'])
    note = string(data.get('review_note'), '迁移说明', True, 3000)
    if data['template_id'] == old_wf['template_id']:
        fail('当前项目已经使用该流程版本', 409)
    template = template_by_id(store, con, data['template_id'], published=True)
    previous = [t for t in store.all(con, 'tasks', project_id) if not t.get('archived')]
    preserve = {t['id'] for t in preview['preserved_tasks']}
    carried = {(t.get('object_code'), t.get('template_node_id')): t for t in previous if t['id'] in preserve and not t.get('rework_of')}
    workflow = deepcopy(old_wf)
    project.update(revision=project['revision'] + 1, status='review', planned_revision=project['revision'] + 1)
    workflow.update(id=uid('wf'), previous_workflow_id=old_wf['id'], revision=project['revision'], version=1,
                    template_id=template['id'], template_version=template['template_version'], template_hash=template['content_hash'],
                    status='draft', created_at=stamp(), updated_at=stamp(), migration_note=note)
    workflow.update(industry_id=template.get('industry_id'), variant_id=template.get('variant_id'),
                    object_fields=deepcopy(template.get('object_fields') or []))
    for key in ('reviewer', 'review_note', 'reviewed_at'):
        workflow.pop(key, None)
    tasks = compile_tasks(project, workflow, template)
    carry_fields = ('assignee', 'started_at', 'completed_at', 'completed_quantity', 'progress_recorded', 'notes', 'priority',
                    'pause_reason', 'pause_note', 'handover_note', 'paused_at', 'resumed_at', 'inspection_result', 'inspection_recorded_at', 'quality_hold_since')
    for task in tasks:
        before = carried.get((task['object_code'], task['template_node_id']))
        if before:
            for key in carry_fields:
                if key in before:
                    task[key] = before[key]
            task['carried_from_task_id'] = before['id']
            task['carried_status'] = before['status']
            # Publish gate remains mandatory. Unchanged finished work stays finished.
            if before['status'] == 'done':
                task['status'] = 'done'
            task['execution_version'] = before.get('execution_version', 0) + 1
        store.put(con, 'tasks', task)
    for task in previous:
        task.update(archived=True, previous_status=task['status'], status='invalidated', execution_version=task.get('execution_version', 0) + 1)
        store.put(con, 'tasks', task)
    workflow['task_ids'] = [t['id'] for t in tasks]
    store.put(con, 'project_workflows', workflow)
    project['workflow_id'] = workflow['id']
    store.put(con, 'projects', project)
    store.event(con, project_id, 'workflow_migrated', '迁移流程并建立待复核新版本', old_workflow_id=old_wf['id'], workflow_id=workflow['id'], note=note)
    return {'workflow': workflow, 'tasks': tasks, 'project': project, 'impact': preview}


def build(store, con, factory_type=None, include_demo=False):
    if factory_type is not None and factory_type not in FACTORY_TYPES:
        fail('工厂类型无效')
    factories = [f for f in store.all(con, 'factories') if not factory_type or f['factory_type'] == factory_type]
    factory_ids = {f['id'] for f in factories}
    people = [dict(p, version=p.get('version', 0), factory_id=p.get('factory_id'), team_id=p.get('team_id'))
              for p in store.all(con, 'people') if (include_demo or not p.get('demo'))
              and (not factory_type or not p.get('factory_id') or p['factory_id'] in factory_ids)]
    templates = [t for t in store.all(con, 'workflow_templates') if not factory_type or t['factory_type'] == factory_type]
    projects = {p['id']: p for p in store.all(con, 'projects') if (include_demo or not p.get('demo'))
                and (not factory_type or p.get('factory_type', 'cabinet') == factory_type)}
    workflows = [w for w in store.all(con, 'project_workflows') if w['project_id'] in projects and projects[w['project_id']].get('workflow_id') == w['id']]
    builtins = [t for t in builtin_templates() if not factory_type or t['factory_type'] == factory_type]
    trades = sorted({n['trade'] for t in builtins + templates for n in t['nodes']} | {s for p in people for s in p.get('skills', [])})
    return {'factories': factories, 'teams': [t for t in store.all(con, 'teams') if t['factory_id'] in factory_ids],
            'workcenters': [w for w in store.all(con, 'workcenters') if w['factory_id'] in factory_ids],
            'people': people, 'templates': templates, 'workflows': workflows, 'builtin_templates': builtins, 'trade_catalog': trades}
