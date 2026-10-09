"""ExecutionService: application behavior, independent of HTTP startup.

The caller owns the transaction. Cross-service work uses the manufacturing port,
so state transitions, source revision checks and audit records stay atomic.
"""
from __future__ import annotations

from kanpace.application.ports import ManufacturingPort
from kanpace.core.constants import PAUSE_REASONS
from kanpace.core.errors import APIError
from kanpace.core.validation import now
from kanpace.core.validation import short_text
from kanpace.core.validation import whole_number
import fulfillment
import operations
import planning
import production


class ExecutionService:
    def __init__(self, store: ManufacturingPort):
        self.store = store

    def assign(self, con, task_id, person_id, data=None):
        task = self.store.get(con, 'tasks', task_id)
        self.store.check_execution_version(task, data or {})
        project = self.store.get(con, 'projects', task['project_id'])
        self.store.require_project_open(project)
        if task.get('archived') or task['status'] in ('invalidated', 'done') or task['revision'] != project['revision']:
            raise APIError(409, '已完成或旧版任务不能重新分派')
        if task['status'] == 'in_progress':
            raise APIError(409, '执行中的任务请先暂停/阻塞，再调整负责人')
        person = None
        if person_id:
            person = self.store.get(con, 'people', str(person_id))
            assignment_issues = operations.assignment_issues(project, person)
            if assignment_issues:
                raise APIError(409, '负责人不适用于此项目', assignment_issues)
            if task.get('trade') not in person.get('skills', []):
                raise APIError(409, '工种技能不匹配', [task.get('trade'), person.get('name')])
        task['assignee'] = person['id'] if person else None
        if person:
            task.pop('reassignment_reason', None)
            task.pop('reassignment_from', None)
        self.store.bump_execution(task)
        self.store.put(con, 'tasks', task)
        self.store.event(con, task['project_id'], 'task_assigned', task['title'] + ' → ' + (person['name'] if person else '待分派'), task_id=task_id)
        return task

    def auto_assign(self, con, project_id):
        project = self.store.get(con, 'projects', project_id)
        self.store.require_project_open(project)
        tasks = self.store.active_tasks(con, project_id)
        people = self.store.all(con, 'people')
        loads = {p['id']: 0.0 for p in people}
        closed_ids = {p['id'] for p in self.store.all(con, 'projects') if fulfillment.is_closed(p) or p.get('archived')}
        for task in self.store.all(con, 'tasks'):
            if task.get('project_id') not in closed_ids and not task.get('archived') and task['status'] not in ('done', 'invalidated') and task.get('assignee') in loads:
                loads[task['assignee']] += self.store.remaining_minutes(task)
        assignments, skipped = [], []
        for task in sorted(tasks, key=lambda t: (-t['priority'], t.get('created_at', ''))):
            if task['status'] in ('done', 'in_progress', 'invalidated') or task.get('assignee') or task['revision'] != project['revision']:
                continue
            candidates = [p for p in people if task['trade'] in p.get('skills', []) and not operations.assignment_issues(project, p)
                          and type(p.get('capacity_minutes')) in (int, float) and 0 < p['capacity_minutes'] <= 1440]
            if not candidates:
                skipped.append({'task_id': task['id'], 'reason': '无匹配技能、工厂归属和已确认容量的人员'})
                continue
            person = min(candidates, key=lambda p: (loads[p['id']] / max(p.get('capacity_minutes', 480), 1), p['id']))
            before = loads[person['id']]
            self.store.assign(con, task['id'], person['id'])
            loads[person['id']] += self.store.remaining_minutes(task)
            assignments.append({'task_id': task['id'], 'person_id': person['id'],
                                'reason': '技能 ' + task['trade'] + ' 匹配；分派前在途负载 ' + str(round(before)) + ' 分钟'})
        return {'assignments': assignments, 'skipped': skipped, 'method': '技能过滤 + 当前在途预计工时/日容量最小优先（启发式；未计算班次与设备日历）'}

    @staticmethod

    def bump_execution(task):
        if task.get('execution_version', 0) >= 2147483647:
            raise APIError(409, '执行版本达到上限，请联系管理员归档')
        task['execution_version'] = task.get('execution_version', 0) + 1
        task['updated_at'] = now()

    @staticmethod
    def check_execution_version(task, data, key='expected_execution_version'):
        if key in data:
            expected = whole_number(data[key], '执行版本', 2147483647)
            if expected != task['execution_version']:
                raise APIError(409, '任务已被其他操作更新，请刷新后重试',
                               {'task_id': task['id'], 'execution_version': task['execution_version']})

    @staticmethod
    def remaining_minutes(task):
        quantity = task.get('quantity') or 0
        return (task.get('estimated_minutes') or 0) * (task['remaining_quantity'] / quantity if quantity else 1)

    def execution_task(self, con, task_id, data=None, allow_done=False):
        task = self.store.get(con, 'tasks', task_id)
        self.store.check_execution_version(task, data or {})
        project = self.store.get(con, 'projects', task['project_id'])
        self.store.require_project_open(project)
        if task.get('archived') or task['status'] == 'invalidated' or project['status'] != 'released' or task['revision'] != project.get('released_revision') or task['revision'] != project['revision']:
            raise APIError(409, '当前任务版本未发布或已失效，禁止执行操作')
        if task['status'] == 'done' and not allow_done:
            raise APIError(409, '已完成任务不可回退；请以部件变更建立新版本')
        return task

    def start_blockers(self, con, task, ignore_task_id=None, completing=False):
        blockers = []
        project = self.store.get(con, 'projects', task['project_id'])
        if fulfillment.is_closed(project) or project.get('archived'):
            blockers.append('项目已完成或发货')
        if task.get('archived') or project['status'] != 'released' or task['revision'] != project.get('released_revision') or task['revision'] != project['revision']:
            blockers.append('当前任务版本未发布或已失效')
        if task['status'] not in ('ready', 'blocked', 'in_progress'):
            blockers.append('当前状态不可开工')
        person = None
        if task.get('assignee'):
            try:
                person = self.store.get(con, 'people', task['assignee'])
            except APIError:
                pass
        if not person:
            blockers.append(task.get('reassignment_reason') or '请先分派具备对应技能的负责人')
        elif task.get('trade') not in person.get('skills', []):
            blockers.append('负责人工种技能不匹配')
        if person:
            blockers.extend(operations.assignment_issues(project, person))
        if not completing:
            blockers.extend(planning.material_blockers(self.store, con, task))
            blockers.extend(production.start_blockers(self.store, con, task))
        blockers.extend('排程前序尚未对应任务：' + name for name in task.get('schedule_unmapped_predecessors', []))
        for dep_id in planning.task_dependencies(task):
            try:
                dep = self.store.get(con, 'tasks', dep_id)
            except APIError:
                blockers.append('前置工序不存在：' + dep_id)
                continue
            if dep['status'] != 'done' or dep.get('archived') or dep.get('revision') != task['revision'] or dep.get('project_id') != task['project_id']:
                blockers.append('前置工序尚未完成：' + dep['title'])
        if person and not completing:
            closed_ids = {p['id'] for p in self.store.all(con, 'projects') if fulfillment.is_closed(p) or p.get('archived')}
            for other in self.store.all(con, 'tasks'):
                if other.get('project_id') not in closed_ids and other['id'] not in (task['id'], ignore_task_id) and not other.get('archived') and other['status'] == 'in_progress' and other.get('assignee') == person['id']:
                    blockers.append('负责人已有执行中任务，请先暂停或切换：' + other['title'])
        return blockers

    def require_start(self, con, task, ignore_task_id=None, completing=False):
        blockers = self.store.start_blockers(con, task, ignore_task_id, completing)
        if blockers:
            raise APIError(409, '任务暂不能执行', blockers)

    @staticmethod
    def progress_value(task, value):
        try:
            total = whole_number(task.get('quantity'), '原任务数量')
        except APIError:
            raise APIError(409, '原任务数量不是有效整件数，请核对部件数量后重新生成并发布任务；不能将半件登记为完工')
        completed = whole_number(value, '已完成数量', total)
        if completed < task['completed_quantity']:
            raise APIError(409, '累计已完成数量不能减少；返工请建立变更记录')
        return completed

    def save_execution(self, con, task, action, message, **details):
        self.store.bump_execution(task)
        self.store.put(con, 'tasks', task)
        self.store.event(con, task['project_id'], action, message, task_id=task['id'],
                   completed_quantity=task['completed_quantity'], remaining_quantity=task['remaining_quantity'],
                   execution_version=task['execution_version'], **details)
        production.after_execution(self.store, con, task, action, details)
        return task

    def report_progress(self, con, task_id, data):
        task = self.store.execution_task(con, task_id, data)
        if task['status'] != 'in_progress':
            raise APIError(409, '仅执行中的任务可登记进度；暂停任务请先恢复')
        self.store.require_start(con, task, completing=True)
        completed = self.store.progress_value(task, data.get('completed_quantity'))
        note = short_text(data.get('note'), '进度/交接说明', True, 2000)
        previous = task['completed_quantity']
        task.update(completed_quantity=completed, progress_recorded=True, handover_note=note)
        return self.store.save_execution(con, task, 'task_progress', task['title'] + '：登记部分进度',
                                   previous_completed_quantity=previous, note=note)

    def pause_values(self, task, data, legacy=False):
        reason = data.get('reason', 'other' if legacy else None)
        if not isinstance(reason, str) or reason not in PAUSE_REASONS:
            raise APIError(400, '请选择暂停原因类别', sorted(PAUSE_REASONS))
        note = short_text(data.get('note'), '暂停原因说明', True, 1000)
        handover = short_text(data.get('handover_note', note if legacy else None), '现场交接说明', True, 2000)
        values = {'status': 'blocked', 'pause_reason': reason, 'pause_note': note,
                  'handover_note': handover, 'notes': note, 'paused_at': now(), 'interrupted_by_task_id': None}
        if 'completed_quantity' in data:
            values.update(completed_quantity=self.store.progress_value(task, data['completed_quantity']), progress_recorded=True)
        return values

    def pause_task(self, con, task_id, data, legacy=False):
        task = self.store.execution_task(con, task_id, data)
        if task['status'] not in (('ready', 'in_progress', 'blocked') if legacy else ('ready', 'in_progress')):
            raise APIError(409, '仅待执行或执行中任务可暂停')
        previous = task['status']
        previous_quantity = task['completed_quantity']
        values = self.store.pause_values(task, data, legacy)
        if task['status'] != 'in_progress' and values.get('completed_quantity', previous_quantity) != previous_quantity:
            raise APIError(409, '未开工任务不能登记新增完成数量')
        task.update(values)
        return self.store.save_execution(con, task, 'task_paused', task['title'] + '：暂停并保留现场',
                                   previous_status=previous, previous_completed_quantity=previous_quantity,
                                   reason=task['pause_reason'], note=task['pause_note'], handover_note=task['handover_note'])

    def resume_task(self, con, task_id, data, to_ready=False):
        task = self.store.execution_task(con, task_id, data)
        if task['status'] != 'blocked':
            raise APIError(409, '仅暂停/阻塞任务可恢复')
        note = short_text(data.get('note'), '解除暂停依据', True, 2000)
        # Even returning to the runnable queue requires release, dependencies and skill.
        # Returning to ready may ignore a worker's current job, but must not
        # clear a material pause before the associated plan is reconfirmed.
        if to_ready:
            material = planning.material_blockers(self.store, con, task) + production.start_blockers(self.store, con, task)
            if material:
                raise APIError(409, '任务暂不能执行', material)
        self.store.require_start(con, task, completing=to_ready)
        handover = short_text(data.get('handover_note', task['handover_note']), '现场交接说明', limit=2000)
        pause = {k: task[k] for k in ('pause_reason', 'pause_note', 'paused_at', 'interrupted_by_task_id')}
        task.update(status='ready' if to_ready else 'in_progress', pause_reason=None, pause_note='',
                    handover_note=handover, resumed_at=now(), interrupted_by_task_id=None, notes=note)
        if not to_ready and not task.get('started_at'):
            task['started_at'] = now()
        return self.store.save_execution(con, task, 'task_resumed', task['title'] + '：恢复待执行' if to_ready else task['title'] + '：恢复执行',
                                   note=note, handover_note=handover, previous_pause=pause)

    def set_priority(self, con, task_id, data):
        task = self.store.execution_task(con, task_id, data)
        priority = whole_number(data.get('priority'), '优先级', 3)
        reason = short_text(data.get('reason'), '调整优先级依据', True, 1000)
        previous = task['priority']
        task['priority'] = priority
        return self.store.save_execution(con, task, 'task_priority', task['title'] + '：调整派工优先级',
                                   previous_priority=previous, priority=priority, reason=reason)

    def switch_task(self, con, task_id, data):
        current = self.store.execution_task(con, task_id, data)
        if current['status'] != 'in_progress':
            raise APIError(409, '只有执行中的任务可以暂停并切换')
        target_id = short_text(data.get('target_task_id'), '目标任务', True, 128)
        if target_id == task_id:
            raise APIError(400, '目标任务不能是当前任务')
        target = self.store.execution_task(con, target_id)
        self.store.check_execution_version(target, data, 'target_expected_execution_version')
        if target['status'] not in ('ready', 'blocked'):
            raise APIError(409, '目标任务须为待执行或暂停状态')
        if not current.get('assignee') or target.get('assignee') != current['assignee']:
            raise APIError(409, '切换目标须与原任务为同一负责人，请先按技能分派')
        self.store.require_start(con, target, ignore_task_id=task_id)
        target_note = short_text(data.get('target_note'), '目标任务解除依据', target['status'] == 'blocked', 2000)
        # Every validation precedes writes. The HTTP caller also holds BEGIN IMMEDIATE.
        values = self.store.pause_values(current, data)
        old_quantity, old_target_status = current['completed_quantity'], target['status']
        current.update(values, interrupted_by_task_id=target_id)
        self.store.save_execution(con, current, 'task_paused', current['title'] + '：暂停并切换任务',
                            reason=current['pause_reason'], note=current['pause_note'], handover_note=current['handover_note'],
                            previous_completed_quantity=old_quantity, target_task_id=target_id)
        previous_pause = {k: target[k] for k in ('pause_reason', 'pause_note', 'paused_at', 'interrupted_by_task_id')}
        target.update(status='in_progress', pause_reason=None, pause_note='', interrupted_by_task_id=None)
        if old_target_status == 'blocked':
            target['resumed_at'] = now()
        if target_note:
            target['notes'] = target_note
        if not target.get('started_at'):
            target['started_at'] = now()
        self.store.save_execution(con, target, 'task_switched_in', target['title'] + '：切入执行',
                            previous_status=old_target_status, previous_pause=previous_pause,
                            note=target_note, source_task_id=task_id)
        return {'task': current, 'target_task': target}

    def task_queue(self, con, person_id=None, project_id=None, from_task_id=None):
        source = self.store.get(con, 'tasks', from_task_id) if from_task_id else None
        closed_ids = {p['id'] for p in self.store.all(con, 'projects') if fulfillment.is_closed(p) or p.get('archived')}
        tasks = [t for t in self.store.all(con, 'tasks', project_id) if t.get('project_id') not in closed_ids and not t.get('archived')
                 and t['status'] in ('ready', 'blocked', 'in_progress') and (not person_id or t.get('assignee') == person_id)]
        result = []
        for task in sorted(tasks, key=lambda t: (-t['priority'], t.get('created_at', ''))):
            blockers = self.store.start_blockers(con, task)
            if task['status'] == 'blocked':
                blockers.append('恢复前须填写解除暂停依据')
            if task['status'] == 'in_progress':
                blockers.append('当前任务已在执行')
            switch_blockers = self.store.start_blockers(con, task, ignore_task_id=from_task_id) if source else ['请选择正在执行的原任务']
            if source:
                try:
                    self.store.execution_task(con, source['id'])
                except APIError:
                    switch_blockers.append('原任务版本未发布或已失效')
                if source['status'] != 'in_progress':
                    switch_blockers.append('原任务须为执行中')
                if source['id'] == task['id'] or task['status'] not in ('ready', 'blocked'):
                    switch_blockers.append('目标须为另一项待执行或暂停任务')
                if not source.get('assignee') or task.get('assignee') != source['assignee']:
                    switch_blockers.append('目标须与原任务为同一负责人')
            result.append(dict(task, can_start=not blockers, start_blockers=blockers,
                               can_switch=not switch_blockers, switch_blockers=switch_blockers,
                               resolution_required=task['status'] == 'blocked'))
        return {'tasks': result, 'sort': 'priority_desc_then_created'}

    def set_status(self, con, task_id, data):
        target = data.get('status')
        if target not in ('in_progress', 'done', 'blocked', 'ready'):
            raise APIError(400, '无效任务状态')
        task = self.store.execution_task(con, task_id, data, allow_done=True)
        if task['status'] == 'done':
            if target == 'done':
                if 'completed_quantity' in data:
                    self.store.progress_value(task, data['completed_quantity'])
                return task
            raise APIError(409, '已完成任务不可回退；请以部件变更建立新版本')
        if target == 'blocked':
            return self.store.pause_task(con, task_id, data, legacy=True)
        if target == 'ready' or (target == 'in_progress' and task['status'] == 'blocked'):
            return self.store.resume_task(con, task_id, data, to_ready=target == 'ready')
        previous = task['status']
        if target == 'in_progress':
            self.store.require_start(con, task)
        if target == 'done':
            if previous != 'in_progress':
                raise APIError(409, '请先开工，再完成报工')
            self.store.require_start(con, task, completing=True)
            inspection_blockers = production.completion_blockers(self.store, con, task)
            if inspection_blockers:
                raise APIError(409, '完工前请完成质量验收', inspection_blockers)
            completed = self.store.progress_value(task, data.get('completed_quantity', task['quantity']))
            if completed != task['quantity']:
                raise APIError(409, '完工须确认原任务全部数量；部分完成请登记进度并暂停')
            task.update(completed_quantity=completed, progress_recorded=True)
            needs_inspection = task.get('trade') == '质检' or (task.get('part_id') is None and task.get('process') == 'electrical')
            if needs_inspection:
                task['inspection_result'] = short_text(data.get('note'), '检验结果', True, 2000)
                task['inspection_recorded_at'] = now()
            task['completed_at'] = now()
        note = short_text(data.get('note'), '备注', limit=2000)
        task['status'] = target
        if note:
            task['notes'] = note
        if target == 'in_progress' and not task.get('started_at'):
            task['started_at'] = now()
        return self.store.save_execution(con, task, 'task_status', task['title'] + '：' + previous + ' → ' + target,
                                   previous_status=previous, status=target, note=note)
