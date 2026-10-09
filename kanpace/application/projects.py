"""ProjectService: application behavior, independent of HTTP startup.

The caller owns the transaction. Cross-service work uses the manufacturing port,
so state transitions, source revision checks and audit records stay atomic.
"""
from __future__ import annotations

from kanpace.application.ports import ManufacturingPort
from datetime import datetime, timezone
from kanpace.core.errors import APIError
from kanpace.core.validation import now
from kanpace.core.validation import number
from kanpace.core.validation import short_text
from kanpace.core.validation import uid
from kanpace.core.validation import whole_number
import factory_config
import fulfillment
import operations
import production


class ProjectService:
    def __init__(self, store: ManufacturingPort):
        self.store = store

    def new_project(self, con, data, demo=False):
        instance=factory_config._instance(self.store, con)
        data=dict(data)
        if instance:
            if data.get('factory_id') and data['factory_id'] != instance['factory_id']:
                raise APIError(403,'订单须属于当前工厂')
            data['factory_id']=instance['factory_id']
        factory_type = data.get('factory_type', (instance or {}).get('factory_type','cabinet'))
        if not isinstance(factory_type, str) or factory_type not in ('cabinet', 'machinery', 'site'):
            raise APIError(400, '工厂类型须为 cabinet、machinery 或 site')
        project = {'id': uid('prj'), 'name': short_text(data.get('name'), '项目名', True, 200),
            'client': short_text(data.get('client'), '客户', limit=200),
            'due_date': short_text(data.get('due_date'), '交期', limit=30),
            'quantity': number(data.get('quantity', 1), '套数', positive=True, maximum=100000),
            'status': 'draft', 'revision': 1, 'released_revision': None, 'demo': demo, 'factory_type': factory_type,
            'evidence_policy': 'staged' if factory_type == 'cabinet' and not demo else 'workflow',
            'document_confirmations': {}, 'document_confirmation_version': 0,
            'created_at': now(), 'updated_at': now(), 'quote_settings': {'outsourcing_cost': 0},
            'quantity_note': 'BOM 数量按本项目整单计算；项目套数仅作记录，不重复乘算。'}
        if project['due_date']:
            try:
                datetime.strptime(project['due_date'], '%Y-%m-%d')
            except ValueError:
                raise APIError(400, '交期格式应为 YYYY-MM-DD')
        if data.get('factory_id'):
            factory = operations.ensure_factory(self.store, con, data['factory_id'])
            if factory['factory_type'] != factory_type:
                raise APIError(409, '所选工厂与项目类型不一致')
            project['factory_id'] = factory['id']
            profile=factory_config.active_profile(self.store, con, factory['id'])
            origin=profile if profile and profile.get('industry_id') else factory
            if origin.get('industry_id'):
                project.update({key:origin.get(key) for key in ('industry_id','variant_id','industry_name','variant_name')})
                if profile:project['industry_profile_id']=profile['id']
        self.store.put(con, 'projects', project)
        self.store.event(con, project['id'], 'project_created', '创建' + ('演示' if demo else '') + '项目：' + project['name'])
        return project

    @staticmethod
    def require_project_open(project):
        if fulfillment.is_closed(project) or project.get('archived'):
            raise APIError(409, '项目已完成或发货，请先重新开启项目再安排生产',
                           {'code': 'project_closed', 'project_id': project['id'],
                            'fulfillment_status': project.get('fulfillment_status', 'active')})

    def set_fulfillment(self, con, project_id, data):
        target = data.get('status')
        if not isinstance(target, str) or target not in fulfillment.LABELS:
            raise APIError(400, '项目状态须为 active、completed 或 shipped')
        if 'confirm_unfinished' in data and not isinstance(data['confirm_unfinished'], bool):
            raise APIError(400, 'confirm_unfinished 须为布尔值')
        if 'confirm_reopen_pause' in data and not isinstance(data['confirm_reopen_pause'], bool):
            raise APIError(400, 'confirm_reopen_pause 须为布尔值')
        if data.get('confirm_reopen_pause') and target != 'active':
            raise APIError(400, '暂停冲突任务确认仅用于重新开启项目')
        reviewed_versions = data.get('reopen_task_versions')
        if 'reopen_task_versions' in data:
            if not isinstance(reviewed_versions, dict) or len(reviewed_versions) > 10000:
                raise APIError(400, '待暂停任务版本须为对象')
            for identifier, version in reviewed_versions.items():
                if not isinstance(identifier, str) or not identifier or len(identifier) > 128:
                    raise APIError(400, '待暂停任务标识无效')
                whole_number(version, '待暂停任务执行版本', 2147483647)
        project = self.store.get(con, 'projects', project_id)
        previous = project.get('fulfillment_status', 'active')
        unfinished = [t for t in self.store.active_tasks(con, project_id) if t.get('status') not in ('done', 'invalidated')]
        if target == previous:
            return {'project': project, 'unchanged': True, 'unfinished_task_count': len(unfinished)}
        if previous == 'shipped' and target == 'completed':
            raise APIError(409, '已发货项目如需重新处理，请先重新开启项目')
        if target in fulfillment.CLOSED:
            quality_blockers = production.project_quality_blockers(self.store, con, project_id)
            if quality_blockers:
                raise APIError(409, '存在未解除的质量问题，暂不能完成或发货', quality_blockers)
        if target in fulfillment.CLOSED and previous == 'active' and unfinished and not data.get('confirm_unfinished', False):
            raise APIError(409, '仍有 ' + str(len(unfinished)) + ' 项未完成任务，请核对后确认关闭项目',
                           {'code': 'unfinished_tasks', 'unfinished_task_count': len(unfinished),
                            'in_progress_count': sum(t.get('status') == 'in_progress' for t in unfinished),
                            'unfinished_tasks': [{key: t.get(key) for key in ('id', 'title', 'trade', 'status', 'remaining_quantity', 'assignee')} for t in unfinished]})
        paused_on_reopen = []
        if target == 'active':
            running = [t for t in unfinished if t.get('status') == 'in_progress']
            restarting = {t.get('assignee') for t in running if t.get('assignee')}
            closed_ids = {p['id'] for p in self.store.all(con, 'projects') if fulfillment.is_closed(p) or p.get('archived')}
            conflicts = [t for t in self.store.all(con, 'tasks') if t.get('project_id') != project_id
                         and t.get('project_id') not in closed_ids and not t.get('archived')
                         and t.get('status') == 'in_progress' and t.get('assignee') in restarting]
            people = {p['id']: p for p in self.store.all(con, 'people')}
            blocked_tasks = []
            for task in running:
                worker = people.get(task.get('assignee'))
                reasons = []
                if worker is None:
                    reasons.append('原负责人不存在' if task.get('assignee') else '未分派负责人')
                elif task.get('trade') not in worker.get('skills', []):
                    reasons.append(worker['name'] + '当前未具备' + task.get('trade', '') + '技能')
                occupied = [t for t in conflicts if t.get('assignee') == task.get('assignee')]
                if occupied:
                    reasons.append('负责人正在执行：' + '、'.join(t['title'] for t in occupied))
                if reasons:
                    blocked_tasks.append((task, reasons))
            if blocked_tasks:
                details = {'code': 'reopen_conflicts',
                           'conflicting_tasks': [{key: t.get(key) for key in ('id', 'title', 'project_id', 'assignee')} for t in conflicts],
                           'reopening_tasks': [dict({key: t.get(key) for key in ('id', 'title', 'trade', 'assignee', 'status', 'remaining_quantity', 'execution_version')},
                                                    reasons=reasons) for t, reasons in blocked_tasks]}
                versions = {t['id']: t['execution_version'] for t, _ in blocked_tasks}
                if not data.get('confirm_reopen_pause') or reviewed_versions != versions:
                    message = '原执行任务需要重新安排，请确认后重新开启并暂停这些任务'
                    if data.get('confirm_reopen_pause'):
                        message = '任务安排已变化，请核对更新后的待暂停任务'
                    raise APIError(409, message, details)
                for task, reasons in blocked_tasks:
                    previous_pause = {key: task.get(key) for key in ('pause_reason', 'pause_note', 'paused_at', 'interrupted_by_task_id')}
                    previous_notes = task.get('notes', '')
                    note = '项目重新开启，待重新安排；' + '；'.join(reasons)
                    task.update(status='blocked', pause_reason='other', pause_note=note, paused_at=now(),
                                interrupted_by_task_id=None, notes=note)
                    self.store.save_execution(con, task, 'task_paused', task['title'] + '：重新开启项目，暂停待安排',
                                        previous_status='in_progress', reason='other', note=note,
                                        handover_note=task['handover_note'], previous_notes=previous_notes,
                                        previous_pause=previous_pause, reopened_project=True, reasons=reasons)
                    paused_on_reopen.append(task['id'])
        stamp = now()
        prior_times = {key: project.get(key) for key in ('completed_at', 'shipped_at', 'closed_at', 'reopened_at')}
        project['fulfillment_status'] = target
        project['updated_at'] = stamp
        if target == 'active':
            project['closed_at'] = None
            project['reopened_at'] = stamp
        else:
            if previous == 'active':
                project['closed_at'] = stamp
                project['completed_at'] = stamp
                project['shipped_at'] = None
            if target == 'shipped':
                project['shipped_at'] = stamp
        self.store.put(con, 'projects', project)
        production.project_transition(self.store, con, project_id, target)
        self.store.event(con, project_id, 'project_fulfillment_changed', '项目：' + fulfillment.LABELS[previous] + ' → ' + fulfillment.LABELS[target],
                   previous_status=previous, fulfillment_status=target, unfinished_task_count=len(unfinished),
                   unfinished_task_ids=[t['id'] for t in unfinished], confirm_unfinished=bool(data.get('confirm_unfinished')),
                   previous_timestamps=prior_times, tasks_preserved=not paused_on_reopen,
                   confirm_reopen_pause=bool(data.get('confirm_reopen_pause')), paused_task_ids=paused_on_reopen)
        return {'project': project, 'unchanged': False, 'unfinished_task_count': len(unfinished),
                'paused_task_ids': paused_on_reopen}
