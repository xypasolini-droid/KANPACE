"""Operator-only configuration of registered local factory instances.

No source drawings, orders, costs or worker credentials are copied between
instances. Controller access is authenticated even in the legacy local mode.
"""
from __future__ import annotations
import re
import access_control
import factory_instances
import factory_config
import operations
import industry_templates


def _registry(parent):
    rows = factory_instances._read_registry(parent)
    seen = set()
    for r in rows:
        if (not isinstance(r, dict) or not re.fullmatch(r'inst_[a-f0-9]{32}', str(r.get('id','')))
                or not isinstance(r.get('factory_id'), str) or not r['factory_id']
                or r.get('factory_type') not in factory_instances.KINDS or r['id'] in seen):
            raise factory_instances.InstanceError(409, '工厂登记文件需要检查')
        seen.add(r['id'])
    return rows


def _target(parent, identifier):
    factory_instances._require_controller(parent)
    if identifier == 'local':
        return parent, None
    if not re.fullmatch(r'inst_[a-f0-9]{32}', identifier):
        raise factory_instances.InstanceError(404, '未找到已登记的工厂')
    record = next((r for r in _registry(parent) if r.get('id') == identifier), None)
    if not record:
        raise factory_instances.InstanceError(404, '未找到已登记的工厂')
    root = factory_instances.root_path(parent)
    folder = root / identifier
    if root.is_symlink() or folder.is_symlink() or not (folder / 'cabinet-flow.sqlite3').is_file() or (folder / 'cabinet-flow.sqlite3').is_symlink():
        raise factory_instances.InstanceError(409, '工厂数据目录需要检查')
    from kanpace.application.store import Store
    child = Store(folder, seed=False, empty=True)
    info = factory_instances.assert_ready(child)
    if info['id'] != identifier or info['factory_id'] != record.get('factory_id') or info['factory_type'] != record.get('factory_type'):
        raise factory_instances.InstanceError(409, '工厂登记与数据空间不一致')
    return child, record


def overview(parent):
    factory_instances._require_controller(parent)
    with parent.connect() as con:
        local = [dict(id='local', target_id='local', factory_id=f['id'], name=f['name'], factory_type=f['factory_type'], status='legacy', url='/factory/index.html',**{k:f.get(k) for k in ('industry_id','variant_id','industry_name','variant_name')})
                 for f in parent.all(con, 'factories') if not f.get('demo')]
    children = [{**factory_instances._public(r), 'target_id':r['id']} for r in _registry(parent)]
    return {'factories':children + local, 'references':operations.builtin_templates(), 'local_factory_count':len(local),'industries':industry_templates.catalog()}


def catalog(parent, target_id, factory_id):
    target, record = _target(parent, target_id)
    if record and factory_id != record['factory_id']:
        raise factory_instances.InstanceError(403, '配置目标与工厂不一致')
    with target.connect() as con:
        con.execute('PRAGMA query_only=ON')
        return factory_config.catalog(target, con, factory_id)


def mutate(parent, target_id, action, data, identifier=None):
    target, record = _target(parent, target_id)
    if record and data.get('factory_id') not in (None, record['factory_id']):
        raise factory_instances.InstanceError(403, '配置目标与工厂不一致')
    functions = {'plans':factory_config.save_plan, 'preview':factory_config.preview, 'install':factory_config.install}
    if action not in functions:
        raise factory_instances.InstanceError(404, '配置操作不存在')
    with target.connect() as con:
        con.execute('BEGIN' if action == 'preview' else 'BEGIN IMMEDIATE')
        if action == 'preview':con.execute('PRAGMA query_only=ON')
        # Authority is checked again before touching the destination database.
        factory_instances._require_controller(parent)
        return factory_config.save_plan(target, con, data, identifier) if action == 'plans' else functions[action](target, con, data)


def workspace(store, factory_id=None):
    info = factory_instances.instance_info(store)
    with store.connect() as con:
        profile = factory_config.active_profile(store, con, info['factory_id'] if info else factory_id)
    return {'isolated':bool(info), 'instance':factory_instances._public(info) if info else None,
            'profile':profile, 'product':'factory', 'factory_url':'/factory/index.html'}


def industry_library(industry_id=None, variant_id=None):
    """Public generic definitions only; never reads customer stores or profiles."""
    try:
        if industry_id:
            return {'template':industry_templates.resolve(industry_id,variant_id)}
        rows=industry_templates.catalog()
        return {'catalog_version':1,'industries':rows,'templates':[
            industry_templates.resolve(row['id'],variant['id']) for row in rows for variant in row['variants']]}
    except (ValueError,KeyError,TypeError):
        raise factory_instances.InstanceError(404,'未找到这个行业或生产类型') from None
