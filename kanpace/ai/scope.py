"""Server-owned authorization scope and minimal facts for the local assistant.

Request context, conversation history and extracted document text never enter
this constructor. A scope is built from the current factory Store and the
server's authenticated actor; a requested factory type can only narrow it.

The scoped records remain private application inputs for existing business
checks. They are NOT model context. Only ``workflow_facts`` may cross the
workflow-process boundary; it explicitly projects the necessary fields and
does not include raw documents, notes, finance, paths or credentials.
"""
from copy import deepcopy
from dataclasses import dataclass

import access_control
import fulfillment
import operations
import planning
import production


def permissions_for(actor):
    if not actor or not actor.get('access_enabled'):
        return frozenset({'*'})
    return frozenset(access_control.ROLES.get(actor.get('role'), {}).get('permissions', []))


@dataclass(frozen=True)
class AgentScope:
    actor: dict | None
    factory_type: str
    permissions: frozenset
    own_only: bool
    financial: bool
    projects: tuple
    tasks: tuple
    people: tuple

    @property
    def project_ids(self):
        return frozenset(project['id'] for project in self.projects)

    def allows(self, capability):
        return '*' in self.permissions or capability in self.permissions

    def workflow_facts(self, project_ids, materials, *, today, pause_labels):
        """Build a fresh, JSON-compatible projection for the isolated worker.

        Project selection must be a subset of the already-authorized scope.
        Planning permission comes from the server scope, never a requested flag.
        A worker/quality scope cannot be promoted to full-order analysis.
        """
        if self.own_only:
            raise access_control.AccessError(403, '整单分析需要主管或技术员权限')
        selected_ids = frozenset(project_ids)
        if not selected_ids <= self.project_ids:
            raise access_control.AccessError(404, '分析项目不在当前可见范围内')
        projects = {p['id']: p for p in self.projects if p['id'] in selected_ids}
        tasks = [t for t in self.tasks if t.get('project_id') in projects
                 and t.get('revision') == projects[t['project_id']].get('revision')]
        facts = {
            'today': today,
            'can_plan': self.allows('planning'),
            'projects': [
                {'id': p['id'], 'name': p.get('name', ''), 'due_date': p.get('due_date'),
                 'revision': p.get('revision'), 'closed': fulfillment.is_closed(p)}
                for p in projects.values()
            ],
            'tasks': [
                {'id': t['id'], 'project_id': t['project_id'], 'title': t.get('title', ''),
                 'status': t.get('status'), 'dependencies': list(t.get('dependencies', [])),
                 'assignee': t.get('assignee'), 'minutes_known': bool(planning.estimate(t)),
                 'pause_label': pause_labels.get(t.get('pause_reason'), ''),
                 'execution_version': t.get('execution_version', 0)}
                for t in tasks
            ],
            'materials': [],
        }
        task_ids = {t['id'] for t in tasks}
        for material in materials:
            linked = [key for key in material.get('task_ids', []) if key in task_ids]
            if material.get('project_id') not in projects or not linked:
                continue
            facts['materials'].append({
                'id': material['id'], 'name': material.get('name', ''), 'task_ids': linked,
                'shortage_quantity': production.material_view(material)['shortage_quantity'],
                'unit': material.get('unit', ''), 'expected_date': material.get('expected_date'),
            })
        return facts


def build_scope(store, con, *, actor=None, factory_type=''):
    """Resolve authorization from the server; only read current-factory records."""
    if factory_type and factory_type not in operations.FACTORY_TYPES:
        raise access_control.AccessError(400, '请选择有效工厂类型')
    actor = access_control.get_actor() if actor is None else actor
    actor = deepcopy(actor)
    permissions = permissions_for(actor)
    own_only = bool(actor and actor.get('access_enabled') and actor.get('role') in ('worker', 'quality'))
    financial = not actor or not actor.get('access_enabled') or actor.get('role') in access_control.FINANCIAL_ROLES
    projects = [p for p in store.all(con, 'projects') if not p.get('demo') and not p.get('archived')
                and (not factory_type or p.get('factory_type', 'cabinet') == factory_type)]
    tasks = [t for t in store.all(con, 'tasks') if not t.get('demo') and not t.get('archived')
             and t.get('status') != 'invalidated']
    if own_only:
        tasks = [t for t in tasks if actor.get('person_id') and t.get('assignee') == actor['person_id']]
        owned_projects = {t['project_id'] for t in tasks}
        projects = [p for p in projects if p['id'] in owned_projects]
    visible_ids = {p['id'] for p in projects}
    tasks = [t for t in tasks if t.get('project_id') in visible_ids]
    people = [p for p in store.all(con, 'people') if not p.get('demo') and not p.get('archived')
              and (not own_only or p['id'] == actor.get('person_id'))]
    return AgentScope(actor=actor, factory_type=factory_type, permissions=permissions,
                      own_only=own_only, financial=financial,
                      projects=tuple(deepcopy(projects)), tasks=tuple(deepcopy(tasks)),
                      people=tuple(deepcopy(people)))
