"""Reviewed factory configuration, separate from production work packages.

The caller owns the SQLite transaction and HTTP authorization. Every operation
is scoped to one factory and, in a customer instance, to its persisted identity.
A preview never persists tasks. Installation publishes a reusable workflow
version and an immutable factory profile; existing orders and tasks keep their
original versions and still require the normal engineering review/release.
"""
from copy import deepcopy
import hashlib
import json
import re

import operations as ops
import industry_templates

SCHEMA_VERSION = 2
PLAN_KIND = 'factory_config_plans'
PROFILE_KIND = 'factory_profiles'
RECEIPT_KIND = 'factory_config_receipts'
CORE_MODULES = ('projects', 'drawing', 'tasks')
DEFAULT_PAGES = ('overview', 'projects', 'planning', 'tasks')
MODULES = (
    'overview', 'projects', 'drawing', 'planning', 'tasks', 'readiness', 'issues',
    'checks', 'inspections', 'deliveries', 'scheduling', 'device', 'people',
    'templates', 'exchange', 'quote', 'owner', 'costs', 'commercial', 'calibration',
)
DEFAULT_MODULES = ['overview', 'projects', 'drawing', 'planning', 'tasks', 'readiness',
                   'issues', 'inspections', 'deliveries', 'device', 'people', 'exchange', 'owner']
SOURCE_TYPES = ('engineering', 'bom', 'render', 'acceptance', 'schedule', 'people')
SOURCE_LABELS = {'engineering': '确认版工程依据 / 工艺单', 'bom': '制造清单 / BOM',
                 'render': '整体效果图', 'acceptance': '验收要求', 'schedule': '原生产排程表', 'people': '人员与技能表'}
SCENE_LABELS = {'cabinet': ('柜号 / 构件', '件'), 'machinery': ('设备 / 装配单元', '台'), 'site': ('施工区域 / 工作面', '区')}


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def _instance(store, con):
    row = con.execute("SELECT value FROM config WHERE key='factory_instance'").fetchone()
    return json.loads(row['value']) if row else None


def _factory(store, con, identifier):
    factory = ops.ensure_factory(store, con, identifier)
    instance = _instance(store, con)
    if instance and (factory['id'] != instance.get('factory_id') or factory.get('factory_type') != instance.get('factory_type')):
        ops.fail('配置目标不属于当前独立工厂', 403, 'factory_mismatch')
    return factory


def _scoped_record(store, con, kind, identifier):
    record = ops.get(store, con, kind, identifier)
    _factory(store, con, record.get('factory_id'))
    return record


def _definitions(plan):
    keys = ('schema_version', 'factory_id', 'factory_type', 'name', 'object_label', 'object_unit',
            'enabled_modules', 'default_page', 'source_requirements', 'nodes', 'note',
            'industry_id', 'variant_id', 'industry_name', 'variant_name', 'industry_origin', 'object_fields', 'measurement_note')
    return {key: deepcopy(plan.get(key, [] if key == 'object_fields' else None)) for key in keys}


def _industry_reference(industry_id, variant_id=None):
    try:
        return industry_templates.resolve(industry_id, variant_id)
    except (ValueError, KeyError):
        ops.fail('未找到此行业或生产类型，请重新选择', 400, 'unknown_industry_template')


def _assert_current_origin(plan):
    origin = plan.get('industry_origin')
    if not origin:
        return
    current = _industry_reference(plan['industry_id'], plan['variant_id'])
    if current['hash'] != origin.get('hash'):
        ops.fail('行业参考流程已更新，请重新选择参考版本并保存草稿后预览', 409, 'stale_industry_reference',
                 current_hash=current['hash'])


def active_profile(store, con, factory_id=None):
    """Return this factory's immutable active profile, never guess between tenants."""
    instance = _instance(store, con)
    if instance:
        factory_id = factory_id or instance['factory_id']
    if not factory_id:
        profiles = store.all(con, PROFILE_KIND)
        ids = {p.get('factory_id') for p in profiles}
        if len(ids) != 1:
            return None
        factory_id = next(iter(ids))
    _factory(store, con, factory_id)
    row = con.execute('SELECT value FROM config WHERE key=?', ('active_factory_profile:' + factory_id,)).fetchone()
    if not row:
        return None
    identifier = json.loads(row['value'])
    profile = _scoped_record(store, con, PROFILE_KIND, identifier)
    if profile['factory_id'] != factory_id:
        ops.fail('工厂配置索引不一致', 409, 'profile_mismatch')
    return deepcopy(profile)


def catalog(store, con, factory_id):
    factory = _factory(store, con, factory_id)
    label, unit = SCENE_LABELS[factory['factory_type']]
    references = [deepcopy(t) for t in ops.builtin_templates() if t['factory_type'] == factory['factory_type']]
    return {'schema_version': SCHEMA_VERSION, 'factory': factory, 'references': references,
            'industries': industry_templates.catalog(),
            'active_profile': active_profile(store, con, factory_id),
            'plans': [p for p in store.all(con, PLAN_KIND) if p['factory_id'] == factory_id],
            'receipts': [r for r in store.all(con, RECEIPT_KIND) if r['factory_id'] == factory_id],
            'defaults': {'object_label': label, 'object_unit': unit, 'enabled_modules': list(DEFAULT_MODULES),
                         'default_page': 'overview', 'source_requirements': ['engineering', 'bom', 'acceptance'],
                         'industry_id': factory.get('industry_id'), 'variant_id': factory.get('variant_id'), 'object_fields': []},
            'available_modules': list(MODULES), 'source_types': [{'id': k, 'label': SOURCE_LABELS[k]} for k in SOURCE_TYPES],
            'limits': {'objects_per_preview': 20, 'nodes_per_route': 80, 'route_scope': 'same_route_per_object'}}


def save_plan(store, con, data, identifier=None):
    allowed = {'name', 'factory_id', 'factory_type', 'source_template_id', 'source_plan_id', 'nodes', 'object_label',
               'object_unit', 'enabled_modules', 'default_page', 'source_requirements', 'note', 'expected_version',
               'industry_id', 'variant_id', 'source_industry_hash', 'object_fields'}
    ops.check_fields(data, allowed)
    if identifier:
        old = deepcopy(_scoped_record(store, con, PLAN_KIND, identifier))
        ops.expected(old, data)
        if old['status'] != 'draft':
            ops.fail('已安装的配置不可修改，请复制为新版本', 409, 'immutable_config')
        if data.get('factory_id', old['factory_id']) != old['factory_id']:
            ops.fail('配置草稿不能跨工厂移动', 409, 'factory_mismatch')
        if data.get('source_plan_id'):
            ops.fail('修改草稿时不能另行指定来源方案')
    else:
        source = _scoped_record(store, con, PLAN_KIND, data['source_plan_id']) if data.get('source_plan_id') else {}
        old = deepcopy(source)
        factory_id = data.get('factory_id', old.get('factory_id'))
        if source and source['factory_id'] != factory_id:
            ops.fail('不能复制其他工厂的配置', 403, 'factory_mismatch')
        factory = _factory(store, con, factory_id)
        plan_versions = [p.get('plan_version', 1) for p in store.all(con, PLAN_KIND) if p['factory_id'] == factory_id]
        old.update(id=ops.uid('fplan'), factory_id=factory_id, status='draft', version=0,
                   plan_version=max(plan_versions, default=0) + 1,
                   source_plan_id=source.get('id'), created_at=ops.stamp())
        old.pop('installed_profile_id', None)
        if 'expected_version' in data and ops.integer(data['expected_version'], '数据版本') != 0:
            ops.fail('新方案版本须为 0')
    factory = _factory(store, con, old['factory_id'])
    typ = ops.factory_type(data.get('factory_type', old.get('factory_type', factory['factory_type'])))
    if typ != factory['factory_type']:
        ops.fail('配置行业与目标工厂不一致', 409, 'factory_mismatch')
    default_industry = old.get('industry_id', factory.get('industry_id'))
    industry_id = ops.string(data.get('industry_id', default_industry), '行业编号', limit=80) or None
    # A variant from the previous industry must never leak into a new selection.
    variant_id = data.get('variant_id', old.get('variant_id', factory.get('variant_id')) if industry_id == default_industry else None)
    variant_id = ops.string(variant_id, '生产类型编号', limit=80) or None
    if not industry_id and variant_id:
        ops.fail('请先选择行业，再选择生产类型')
    reference = _industry_reference(industry_id, variant_id) if industry_id else None
    variant_id = reference['variant_id'] if reference else None
    changed = (industry_id, variant_id) != (old.get('industry_id'), old.get('variant_id'))
    if data.get('source_industry_hash') is not None:
        if not reference or data['source_industry_hash'] != reference['hash']:
            ops.fail('行业参考版本已变化，请重新选择后保存', 409, 'stale_industry_reference')
    # Local modifications remain local. Origin is an immutable snapshot of the
    # public research reference, never copied customer drawings or recipes.
    origin = (deepcopy(reference) if changed or not old.get('industry_origin') or 'source_industry_hash' in data
              else deepcopy(old['industry_origin'])) if reference else None
    basis = {} if changed else old
    source_id = data.get('source_template_id', old.get('source_template_id', 'builtin_' + typ + '_v1'))
    source_template = ops.template_by_id(store, con, source_id)
    if source_template.get('factory_type') != typ or source_template.get('factory_id') not in (None, factory['id']):
        ops.fail('配置不能引用其他工厂的流程模板', 403, 'factory_mismatch')
    label, unit = SCENE_LABELS[typ]
    route_defaults = reference or {'nodes': source_template['nodes'], 'object_label': label, 'object_unit': unit,
                                  'source_requirements': ['engineering', 'bom', 'acceptance'], 'object_fields': []}
    modules = ops.string_list(data.get('enabled_modules', old.get('enabled_modules', DEFAULT_MODULES)), '启用功能', maximum=len(MODULES), item_limit=40)
    if set(modules) - set(MODULES) or not set(CORE_MODULES) <= set(modules):
        ops.fail('启用功能须包含项目、图纸拆解和工种任务，且不能包含未知功能')
    default_page = data.get('default_page', old.get('default_page', 'overview'))
    if default_page not in DEFAULT_PAGES:
        ops.fail('首页须为工作台、项目订单、排程表或工种任务')
    if default_page not in modules:
        ops.fail('首页必须是已启用功能')
    sources = ops.string_list(data.get('source_requirements', basis.get('source_requirements', route_defaults['source_requirements'])), '需要资料', maximum=len(SOURCE_TYPES))
    if set(sources) - set(SOURCE_TYPES) or 'engineering' not in sources:
        ops.fail('需要资料须包含确认版工程依据，且不能包含未知用途')
    old.update(schema_version=SCHEMA_VERSION, factory_type=typ,
               name=ops.string(data.get('name', basis.get('name', reference['name'] if reference else factory['name'] + '现场流程')), '方案名称', True, 120),
               object_label=ops.string(data.get('object_label', basis.get('object_label', route_defaults['object_label'])), '工作对象叫法', True, 60),
               object_unit=ops.string(data.get('object_unit', basis.get('object_unit', route_defaults['object_unit'])), '工作对象单位', True, 20),
               enabled_modules=modules, default_page=default_page, source_requirements=sources,
               source_template_id=source_id,
               industry_id=industry_id, variant_id=variant_id, industry_origin=origin,
               industry_name=(reference.get('industry_name') or reference['name']) if reference else None,
               variant_name=(reference.get('variant_name') or reference['name']) if reference else None,
               measurement_note=reference.get('measurement_note', '') if reference else '',
               object_fields=ops.validate_object_fields(data.get('object_fields', basis.get('object_fields', route_defaults.get('object_fields', [])))),
               nodes=ops.validate_nodes(store, con, data.get('nodes', basis.get('nodes', route_defaults['nodes'])), factory['id']),
               note=ops.string(data.get('note', basis.get('note', reference.get('note', '') if reference else '')), '方案说明', limit=3000),
               version=old['version'] + 1, updated_at=ops.stamp())
    old['content_hash'] = digest(_definitions(old))
    store.put(con, PLAN_KIND, old)
    store.event(con, None, 'factory_config_draft_saved', '保存工厂配置草稿：' + old['name'], factory_id=factory['id'], plan_id=old['id'])
    return {'plan': old}


def _resources(store, con, factory_id):
    return {kind: sorted([r for r in store.all(con, kind) if r.get('factory_id') == factory_id], key=lambda r: r['id'])
            for kind in ('people', 'workcenters', 'teams')}


def _preview(store, con, data):
    plan = deepcopy(_scoped_record(store, con, PLAN_KIND, data.get('plan_id')))
    ops.expected(plan, data)
    if plan['status'] != 'draft':
        ops.fail('此配置已经安装；如需调整请复制新版本', 409, 'immutable_config')
    _assert_current_origin(plan)
    factory = _factory(store, con, plan['factory_id'])
    resources = _resources(store, con, factory['id'])
    # The preview is illustrative. It cannot smuggle another project's private
    # document references into this plan or produce a reviewed production task.
    raw_objects = data.get('objects', [{'code': 'SAMPLE-01', 'name': plan['object_label'] + '示例',
                                       'quantity': 1, 'unit': plan['object_unit']}])
    if not isinstance(raw_objects, list) or not 1 <= len(raw_objects) <= 20:
        ops.fail('请使用 1 至 20 个明确工作对象进行预览')
    objects = ops.validate_objects(store, con, '__factory_config_preview__', raw_objects, plan.get('object_fields'))
    nodes = ops.validate_nodes(store, con, plan['nodes'], factory['id'])
    active = active_profile(store, con, factory['id'])
    binding = {'instance_id': (_instance(store, con) or {}).get('id'), 'factory': factory,
               'plan_id': plan['id'], 'plan_version': plan['version'], 'content_hash': plan['content_hash'],
               'objects': objects, 'resources': resources, 'active_profile_id': active['id'] if active else None}
    token = digest(binding)
    workflow = {'id': 'configuration_preview', 'version': 0, 'factory_id': factory['id'],
                'objects': objects, 'scope_note': '工厂配置预览，未发布生产任务'}
    template = {'id': 'configuration_preview', 'nodes': nodes,
                **{key: deepcopy(plan.get(key)) for key in ops.INDUSTRY_METADATA_KEYS}}
    tasks = ops.compile_tasks({'id': '__factory_config_preview__', 'revision': 1, 'demo': False}, workflow, template)
    identifiers = {t['id']: 'preview:' + t['object_code'] + ':' + t['template_node_id'] for t in tasks}
    for task in tasks:
        task.update(id=identifiers[task['id']], dependencies=[identifiers[d] for d in task['dependencies']], preview_only=True)
    warnings, missing = [], []
    available = [p for p in resources['people'] if not p.get('demo') and p.get('active', True)]
    for trade in sorted({n['trade'] for n in nodes}):
        matches = [p for p in available if trade in p.get('skills', [])]
        if not matches:
            missing.append({'kind': 'people', 'trade': trade, 'message': trade + '还没有绑定本厂人员', 'action': '#page=people'})
        elif not any(p.get('capacity_minutes') for p in matches):
            missing.append({'kind': 'capacity', 'trade': trade, 'message': trade + '人员每日可用工时待确认', 'action': '#page=people'})
    unknown = [n for n in nodes if n['estimated_minutes'] is None]
    if unknown:
        warnings.append({'code': 'unknown_duration', 'message': str(len(unknown)) + ' 道工序工时待班组确认，暂不能计算准确交期', 'node_ids': [n['id'] for n in unknown]})
    no_acceptance = [n for n in nodes if not n['acceptance']]
    blockers = [{'code': 'acceptance_required', 'message': '请补充「' + n['name'] + '」的验收要求', 'node_id': n['id']} for n in no_acceptance]
    if any(not o['instructions'] for o in objects):
        warnings.append({'code': 'sample_scope_missing', 'message': '示例对象的技术范围尚未填写；真实订单须关联确认图纸并逐项复核'})
    field_gaps = ops.missing_industry_fields(objects, plan.get('object_fields') or [])
    if field_gaps:
        warnings.append({'code': 'sample_industry_fields_missing', 'message': '示例对象有 ' + str(len(field_gaps)) + ' 项行业字段待填写；真实工作包复核前须补齐', 'fields': field_gaps})
    warnings.append({'code': 'engineering_review_required', 'message': '安装配置后，真实工作包仍须核对工程依据、齐套条件和工时，再发布派工'})
    ranks = {}
    by_node = {n['id']: n for n in nodes}
    for identifier in ops.dag_order(nodes):
        ranks[identifier] = 1 + max((ranks[p] for p in by_node[identifier]['predecessors']), default=0)
    stages = [[n['id'] for n in nodes if ranks[n['id']] == level] for level in range(1, max(ranks.values()) + 1)]
    node_times = {}
    for identifier in ops.dag_order(nodes):
        n = by_node[identifier]
        parents = [node_times[p] for p in n['predecessors']]
        node_times[identifier] = None if n['estimated_minutes'] is None or any(x is None for x in parents) else n['estimated_minutes'] + max(parents, default=0)
    source_requirements = [{'kind': k, 'label': SOURCE_LABELS[k], 'status': 'required_on_real_order'} for k in plan['source_requirements']]
    return {'preview_token': token, 'plan': plan, 'factory': factory, 'objects': objects, 'tasks': tasks,
            'stages': stages, 'warnings': warnings, 'missing_resources': missing,
            'source_requirements': source_requirements, 'install_blockers': blockers, 'can_install': not blockers,
            'summary': {'object_count': len(objects), 'node_count': len(nodes), 'task_count': len(tasks),
                        'parallel_stage_count': sum(len(s) > 1 for s in stages),
                        'known_work_minutes': round(sum((t['hours'] or 0) * 60 for t in tasks), 4),
                        'unknown_task_duration_count': sum(t['hours'] is None for t in tasks),
                        'critical_path_minutes_per_object': None if any(x is None for x in node_times.values()) else max(node_times.values()),
                        'duration_basis': '人工配置分钟 × 工作对象数量；并行层级不含人员设备竞争',
                        'route_scope': '每个工作对象应用同一条完整路线，前序只在同一对象内'},
            'changes': {'new_template_count': 1, 'new_profile_count': 1, 'new_production_tasks': 0,
                        'existing_projects_changed': 0, 'replaces_profile_id': active['id'] if active else None}}


def preview(store, con, data):
    ops.check_fields(data, {'plan_id', 'expected_version', 'objects'})
    return _preview(store, con, data)


def install(store, con, data):
    ops.check_fields(data, {'plan_id', 'expected_version', 'objects', 'preview_token', 'reviewed', 'reviewer', 'review_note', 'request_id'})
    request_id = ops.string(data.get('request_id'), '安装请求编号', True, 100)
    if not re.fullmatch(r'[A-Za-z0-9_-]{8,100}', request_id):
        ops.fail('安装请求编号须为 8 至 100 位字母、数字、横线或下划线')
    plan = _scoped_record(store, con, PLAN_KIND, data.get('plan_id'))
    fingerprint = digest(data)
    receipts = [r for r in store.all(con, RECEIPT_KIND) if r['factory_id'] == plan['factory_id'] and r['request_id'] == request_id]
    if receipts:
        receipt = receipts[0]
        if receipt['request_hash'] != fingerprint:
            ops.fail('同一安装请求编号不能对应不同内容', 409, 'idempotency_conflict')
        profile = _scoped_record(store, con, PROFILE_KIND, receipt['profile_id'])
        template = ops.template_by_id(store, con, receipt['template_id'], published=True)
        return {'profile': profile, 'receipt': receipt, 'template': template, 'replayed': True}
    if data.get('reviewed') is not True:
        ops.fail('请核对预览结果后确认采用配置', 400, 'review_required')
    reviewer = ops.string(data.get('reviewer'), '复核人', True, 100)
    note = ops.string(data.get('review_note'), '复核说明', True, 2000)
    checked = _preview(store, con, {key: data[key] for key in ('plan_id', 'expected_version', 'objects') if key in data})
    token = ops.string(data.get('preview_token'), '预览标识', True, 64)
    if token != checked['preview_token']:
        ops.fail('配置、人员资源或当前采用版本已变化，请重新预览后安装', 409, 'stale_preview')
    if checked['install_blockers']:
        ops.fail('流程验收要求未完整，请补齐后重新预览', 409, 'install_blocked', blockers=checked['install_blockers'])
    plan = deepcopy(checked['plan'])
    old_profile = active_profile(store, con, plan['factory_id'])
    source_id = old_profile['template_id'] if old_profile else plan['source_template_id']
    template = ops.save_template(store, con, {'source_template_id': source_id, 'name': plan['name'],
        'factory_type': plan['factory_type'], 'factory_id': plan['factory_id'], 'nodes': plan['nodes'], 'note': plan['note']},
        industry_metadata={key: deepcopy(plan.get(key)) for key in ops.INDUSTRY_METADATA_KEYS})['template']
    template = ops.publish_template(store, con, template['id'], {'expected_version': template['version']})['template']
    profile = {**_definitions(plan), 'id': ops.uid('fprofile'), 'status': 'installed',
               'version': (old_profile['version'] if old_profile else 0) + 1,
               'plan_id': plan['id'], 'plan_version': plan['plan_version'], 'content_hash': plan['content_hash'],
               'factory_name': checked['factory']['name'], 'instance_id': (_instance(store, con) or {}).get('id'),
               'template_id': template['id'], 'template_version': template['template_version'], 'installed_at': ops.stamp(),
               'previous_profile_id': old_profile['id'] if old_profile else None,
               'review': {'reviewer': reviewer, 'note': note, 'reviewed_at': ops.stamp()},
               'readiness_at_install': {'missing_resources': checked['missing_resources'], 'warnings': checked['warnings']}}
    receipt = {'id': ops.uid('finstall'), 'factory_id': plan['factory_id'], 'instance_id': profile['instance_id'],
               'request_id': request_id, 'request_hash': fingerprint, 'plan_id': plan['id'],
               'profile_id': profile['id'], 'profile_version': profile['version'], 'template_id': template['id'],
               'content_hash': plan['content_hash'], 'installed_at': profile['installed_at'],
               'industry_id': plan.get('industry_id'), 'variant_id': plan.get('variant_id'),
               'source_industry_hash': (plan.get('industry_origin') or {}).get('hash'),
               'changes': checked['changes'], 'reviewer': reviewer}
    plan.update(status='installed', installed_profile_id=profile['id'], version=plan['version'] + 1, updated_at=ops.stamp())
    store.put(con, PLAN_KIND, plan)
    store.put(con, PROFILE_KIND, profile)
    store.put(con, RECEIPT_KIND, receipt)
    con.execute('INSERT INTO config(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                ('active_factory_profile:' + plan['factory_id'], json.dumps(profile['id'])))
    store.event(con, None, 'factory_config_installed', '采用工厂配置：' + plan['name'], factory_id=plan['factory_id'],
                profile_id=profile['id'], template_id=template['id'], content_hash=plan['content_hash'])
    return {'profile': profile, 'receipt': receipt, 'template': template, 'replayed': False}
