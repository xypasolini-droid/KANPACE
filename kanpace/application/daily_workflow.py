"""One factory's daily work packet, physical labels and badge custody.

Production progress remains in ExecutionService and dates remain in plans.
Labels identify one physical part unit and keep separate stage confirmations;
preparing or confirming a label
never increments production quantity. Callers own the SQLite transaction.
"""
from datetime import date
import math
import re

import access_control
import fulfillment
import planning
from kanpace.core.errors import APIError
from kanpace.core.validation import now, short_text, uid


class DailyWorkflowService:
    def __init__(self, store):
        self.store = store

    @staticmethod
    def day(value=None):
        return planning.parse_day(value if value is not None else date.today().isoformat()).isoformat()

    @staticmethod
    def identifier(value, name):
        if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}', value):
            raise APIError(400, name + '格式无效')
        return value

    @staticmethod
    def unit_count(task):
        value = task.get('quantity')
        if type(value) not in (int, float) or not math.isfinite(value) or value != int(value) or not 1 <= value <= 1000000:
            raise APIError(409, '贴标任务须有明确的整数件数')
        return int(value)

    @staticmethod
    def require_owner(task):
        actor = access_control.get_actor() or {}
        if actor.get('access_enabled') and actor.get('role') in ('worker', 'quality'):
            if not actor.get('person_id') or actor['person_id'] != task.get('assignee'):
                raise APIError(403, '只能操作分派给自己的任务')

    def valid_task(self, con, identifier, revision=None):
        task = self.store.get(con, 'tasks', identifier)
        self.require_owner(task)
        project = self.store.get(con, 'projects', task['project_id'])
        if (task.get('archived') or project.get('archived') or fulfillment.is_closed(project)
                or project.get('status') != 'released'
                or task.get('revision') != project.get('revision')
                or task.get('revision') != project.get('released_revision')):
            raise APIError(409, '任务已关闭或工程版本已失效')
        if revision is not None and (type(revision) is not int or revision != task.get('revision')):
            raise APIError(409, '标签与当前图纸版本不一致，请重新核对')
        return task

    def dated_tasks(self, con, day, person_id=None, project_id=None, factory_type=None):
        actor = access_control.get_actor() or {}
        if actor.get('access_enabled') and actor.get('role') in ('worker', 'quality'):
            if person_id and person_id != actor.get('person_id'):
                raise APIError(403, '只能查看自己的当日任务')
            person_id = actor.get('person_id') or '__unassigned_actor__'
        projects = {p['id']: p for p in self.store.all(con, 'projects')}
        people = {p['id']: p for p in self.store.all(con, 'people')}
        tasks = {t['id']: t for t in self.store.all(con, 'tasks')}
        parts = {p['id']: p for p in self.store.all(con, 'parts')}
        rows = {}
        for plan in self.store.all(con, 'plans'):
            if plan.get('status') != 'scheduled':
                continue
            allocations = [a for a in plan.get('allocations', []) if a.get('date') == day]
            # Legacy plans without allocations still carry an explicit date range.
            if not allocations and (plan.get('allocations') or not (plan.get('start_date', '') <= day <= plan.get('end_date', ''))):
                continue
            task = tasks.get(plan.get('task_id'))
            if not task:
                continue
            project = projects.get(task.get('project_id'), {})
            if (task.get('archived') or task.get('demo') or project.get('demo') or project.get('archived')
                    or fulfillment.is_closed(project) or project.get('status') != 'released'
                    or task.get('revision') != project.get('revision')
                    or task.get('revision') != project.get('released_revision')
                    or plan.get('task_revision') != task.get('revision')
                    or plan.get('person_id') != task.get('assignee')):
                continue
            if (person_id and task.get('assignee') != person_id) or (project_id and task['project_id'] != project_id):
                continue
            if factory_type and project.get('factory_type') != factory_type:
                continue
            row = dict(task, project_name=project.get('name', ''), part_name=parts.get(task.get('part_id'), {}).get('name', ''),
                       person_name=people.get(task.get('assignee'), {}).get('name', ''), plan_id=plan['id'],
                       plan_minutes=sum(a.get('minutes', 0) for a in allocations), scheduled_date=day,
                       can_dispatch=task.get('status') in ('ready', 'in_progress', 'blocked') and bool(task.get('assignee')))
            if row['id'] in rows:
                rows[row['id']]['plan_minutes'] += row['plan_minutes']
            else:
                rows[row['id']] = row
        return sorted(rows.values(), key=lambda row: (-row.get('priority', 0), row.get('schedule_position', 1000000), row.get('created_at', ''), row['id']))

    @staticmethod
    def physical_key(task):
        return (task['project_id'], 'part:' + task['part_id'] if task.get('part_id') else 'task:' + task['id'], task['revision'])

    def label_key(self, con, label):
        if label.get('physical_identity'):
            return tuple(label['physical_identity'])
        # Read legacy labels in place. Their original task supplies part identity;
        # existing printed IDs are never rewritten during a read or preparation.
        task = self.store.get(con, 'tasks', label['task_id'])
        return (label['project_id'], 'part:' + task['part_id'] if task.get('part_id') else 'task:' + task['id'], label['revision'])

    def contextual_label(self, con, label, task, *, confirmations=None, all_labels=None):
        aliases = [label] if label.get('physical_identity') else [row for row in (all_labels if all_labels is not None else self.store.all(con, 'daily_labels', task['project_id']))
                   if row['sequence'] == label['sequence'] and row['revision'] == label['revision']
                   and self.label_key(con, row) == self.label_key(con, label)]
        alias_ids = {row['id'] for row in aliases}
        confirmations = [row for row in (confirmations if confirmations is not None else self.store.all(con, 'label_confirmations', task['project_id']))
                         if row['label_id'] in alias_ids and row['task_id'] == task['id'] and row['revision'] == task['revision']]
        confirmation = confirmations[0] if confirmations else None
        legacy = next((row for row in aliases if not row.get('physical_identity') and row.get('status') == 'confirmed'
                       and row['task_id'] == task['id']), None)
        canonical = aliases[0] if aliases else label
        location = None
        if canonical.get('location_id'):
            location = self.store.get(con, 'stock_locations', canonical['location_id'])
        return dict(label, origin_task_id=label['task_id'], task_id=task['id'], task_title=task.get('title', ''),
                    trade=task.get('trade', ''), status='confirmed' if confirmation or legacy else 'prepared',
                    confirmed_at=confirmation['confirmed_at'] if confirmation else legacy.get('confirmed_at') if legacy else None,
                    confirmed_by=confirmation.get('confirmed_by') if confirmation else None,
                    confirmation_id=confirmation['id'] if confirmation else None,
                    canonical_label_id=canonical['id'], location_id=canonical.get('location_id'),
                    location_version=canonical.get('location_version', 0), current_location=location)

    def task_labels(self, con, task):
        key, by_sequence = self.physical_key(task), {}
        labels = self.store.all(con, 'daily_labels', task['project_id'])
        confirmations = self.store.all(con, 'label_confirmations', task['project_id'])
        for label in labels:
            if label['revision'] == task['revision'] and self.label_key(con, label) == key:
                # Historical task-specific duplicates remain readable by their old
                # ID, but preparation and printing choose one identity per unit.
                by_sequence.setdefault(label['sequence'], label)
        return [self.contextual_label(con, label, task, confirmations=confirmations, all_labels=labels)
                for _, label in sorted(by_sequence.items())]

    def label_metadata(self, con, task):
        part = self.store.get(con, 'parts', task['part_id']) if task.get('part_id') else {}
        if part and part.get('project_id') != task['project_id']:
            raise APIError(409, '任务与部件所属项目不一致')
        if part and self.unit_count(part) != self.unit_count(task):
            raise APIError(409, '工序件数与部件清单不一致，请先核对件数')
        return {'part_id': task.get('part_id'), 'part_name': part.get('name', ''),
                'cabinet_name': part.get('cabinet_name') or part.get('cabinet_code') or '',
                'material': part.get('material', ''), 'unit': '件', 'dimension_unit': 'mm',
                'dimensions_mm': {key: part.get(key + '_mm', part.get(key)) for key in ('length', 'width', 'thickness')},
                'piece_count': self.unit_count(task)}

    def label_summary(self, con, task):
        labels = self.task_labels(con, task)
        try:
            expected = self.unit_count(task)
        except APIError:
            expected = 0
        confirmed = sum(label['status'] == 'confirmed' for label in labels)
        pending_label = next((label for label in labels if label['status'] == 'prepared'), None)
        return {'expected': expected, 'total': len(labels), 'confirmed': confirmed, 'pending': max(0, expected - confirmed),
                'next_label_id': pending_label['id'] if pending_label else None,
                'next_label_code': pending_label['code'] if pending_label else None}

    def label(self, con, identifier, task_id=None):
        item = self.store.get(con, 'daily_labels', self.identifier(identifier, '标签编号'))
        task = self.store.get(con, 'tasks', task_id or item['task_id'])
        self.require_owner(task)
        if self.physical_key(task) != self.label_key(con, item):
            raise APIError(409, '标签不属于本任务的部件或版本')
        # Keep historical lookup useful while exposing stale labels explicitly.
        project = self.store.get(con, 'projects', task['project_id'])
        return dict(self.contextual_label(con, item, task), current=(not task.get('archived') and not project.get('archived')
                                  and task['revision'] == item['revision'] == project.get('released_revision') == project.get('revision')))

    def prepare_labels(self, con, data):
        day = self.day(data.get('date'))
        ids = data.get('task_ids')
        if not isinstance(ids, list) or not ids or len(ids) > 200 or any(not isinstance(i, str) for i in ids):
            raise APIError(400, '请选择 1 至 200 项当日任务')
        if len(set(ids)) != len(ids):
            raise APIError(400, '任务列表包含重复项')
        dated = {t['id']: t for t in self.dated_tasks(con, day)}
        tasks = []
        for identifier in ids:
            task = self.valid_task(con, identifier)
            if identifier not in dated:
                raise APIError(409, '任务不在所选日期的有效排程中', {'task_id': identifier, 'date': day})
            tasks.append(task)
        physical_counts = {}
        for task in tasks:
            key, count = self.physical_key(task), self.unit_count(task)
            if key in physical_counts and physical_counts[key] != count:
                raise APIError(409, '同一部件的工序件数不一致，请核对后准备标签')
            physical_counts[key] = count
        if sum(physical_counts.values()) > 500:
            raise APIError(400, '一次最多准备 500 张标签，请分批选择任务')
        results, created = [], 0
        for task in tasks:
            project = self.store.get(con, 'projects', task['project_id'])
            existing = {label['sequence']: label for label in self.task_labels(con, task)}
            metadata = self.label_metadata(con, task)
            if existing and any(label.get('piece_count', len(existing)) != self.unit_count(task) for label in existing.values()):
                raise APIError(409, '本工序数量与已有部件标签数量不一致，请先核对')
            for sequence in range(1, self.unit_count(task) + 1):
                label = existing.get(sequence)
                if label is None:
                    identifier = uid('label')
                    # Random factory-local identity prevents codes being derived
                    # from another factory's repeated human order numbers.
                    label = {'id': identifier, 'project_id': task['project_id'], 'task_id': task['id'],
                             'revision': task['revision'], 'sequence': sequence, 'quantity': 1, 'date': day,
                             'code': 'KP-' + identifier.removeprefix('label_').upper(), 'qr_payload': 'KANPACE:LABEL:' + identifier,
                             'status': 'prepared', 'task_title': task.get('title', ''), 'part_name': dated[task['id']]['part_name'],
                             'project_name': project['name'], 'trade': task.get('trade', ''),
                             'created_at': now(), 'confirmed_at': None, 'version': 1}
                    label.update(metadata, physical_identity=list(self.physical_key(task)), location_id=None, location_version=0)
                    self.store.put(con, 'daily_labels', label)
                    created += 1
                physical = self.store.get(con, 'daily_labels', label['id'])
                if not physical.get('physical_identity'):
                    # Enrich old printed labels without deleting their original
                    # confirmation or changing the identity printed on the piece.
                    missing = {key: value for key, value in metadata.items() if key not in physical or physical[key] in (None, '')}
                    if missing:
                        physical.update(missing)
                        self.store.put(con, 'daily_labels', physical)
                results.append(self.contextual_label(con, physical, task))
        if created:
            self.store.event(con, None, 'daily_labels_prepared', '准备当日二维码标签', date=day, task_ids=ids, label_count=created)
        return {'date': day, 'labels': results, 'created_count': created,
                'physical_label_count': len({label['id'] for label in results}), 'reused_count': len(results) - created}

    def confirm_label(self, con, identifier, data, *, device_id=None):
        label = self.store.get(con, 'daily_labels', self.identifier(identifier, '标签编号'))
        if type(data.get('revision')) is not int or data['revision'] != label['revision']:
            raise APIError(409, '标签不属于本任务或图纸版本不一致')
        task = self.valid_task(con, self.identifier(data.get('task_id'), '任务编号'), data['revision'])
        if self.physical_key(task) != self.label_key(con, label):
            raise APIError(409, '标签不属于本任务的部件')
        if task.get('status') != 'done' or task.get('completed_quantity') != task.get('quantity'):
            raise APIError(409, '请先完成本任务并确认数量，再确认贴标')
        if label['sequence'] > self.unit_count(task) or label.get('piece_count', self.unit_count(task)) != self.unit_count(task):
            raise APIError(409, '标签序号超过当前任务数量')
        view = self.contextual_label(con, label, task)
        if view['status'] == 'confirmed':
            return {'label': view, 'duplicate': True, 'task_labels': self.label_summary(con, task)}
        actor = access_control.get_actor() or {}
        self.store.put(con, 'label_confirmations', {'id': uid('labelconfirmation'), 'label_id': label['id'],
            'project_id': task['project_id'], 'task_id': task['id'], 'revision': task['revision'], 'confirmed_at': now(),
            'confirmed_by': actor.get('person_id') or actor.get('id'), 'device_id': device_id})
        self.store.save_execution(con, task, 'daily_label_confirmed', '确认部件贴标',
                                  label_id=label['id'], revision=label['revision'], sequence=label['sequence'])
        return {'label': self.contextual_label(con, label, task), 'duplicate': False, 'task_labels': self.label_summary(con, task)}

    def locations(self, con):
        return {'locations': sorted(self.store.all(con, 'stock_locations'), key=lambda row: row['code'])}

    def save_location(self, con, data):
        code = short_text(data.get('code'), '货位编号', True, 24).upper()
        if not re.fullmatch(r'[A-Z0-9][A-Z0-9-]{0,23}', code):
            raise APIError(400, '货位编号使用字母、数字和短横线，例如 01-007')
        name = short_text(data.get('name') or ('货位 ' + code), '货位名称', True, 80)
        for item in self.store.all(con, 'stock_locations'):
            if item['code'] == code:
                if item['name'] != name:
                    raise APIError(409, '这个货位编号已存在，请使用现有货位')
                return {'location': item, 'duplicate': True}
        item = {'id': uid('location'), 'code': code, 'name': name, 'active': True, 'version': 1, 'created_at': now()}
        item['qr_payload'] = 'KANPACE:LOCATION:' + item['id']
        self.store.put(con, 'stock_locations', item)
        self.store.event(con, None, 'stock_location_created', '建立货位标签', location_id=item['id'], code=code)
        return {'location': item, 'duplicate': False}

    def location(self, con, identifier):
        item = self.store.get(con, 'stock_locations', self.identifier(identifier, '货位编号'))
        actor = access_control.get_actor() or {}
        own = actor.get('person_id') if actor.get('access_enabled') and actor.get('role') in ('worker', 'quality') else None
        tasks = self.store.all(con, 'tasks')
        labels = []
        for label in self.store.all(con, 'daily_labels'):
            if label.get('location_id') != identifier:
                continue
            task = next((task for task in tasks if self.physical_key(task) == self.label_key(con, label)
                         and (not own or task.get('assignee') == own)), None)
            if task:
                labels.append(self.contextual_label(con, label, task))
        return {'location': item, 'labels': labels}

    def bind_location(self, con, identifier, data):
        label = self.store.get(con, 'daily_labels', self.identifier(identifier, '标签编号'))
        if not label.get('physical_identity'):
            label = next((row for row in self.store.all(con, 'daily_labels', label['project_id'])
                          if row['sequence'] == label['sequence'] and self.label_key(con, row) == self.label_key(con, label)), label)
        project = self.store.get(con, 'projects', label['project_id'])
        if (project.get('archived') or fulfillment.is_closed(project) or project.get('status') != 'released'
                or label['revision'] != project.get('revision') or label['revision'] != project.get('released_revision')):
            raise APIError(409, '标签所属项目或图纸版本已失效')
        location = self.store.get(con, 'stock_locations', self.identifier(data.get('location_id'), '货位编号'))
        if not location.get('active'):
            raise APIError(409, '货位已停用')
        expected = data.get('expected_location_version')
        current = label.get('location_version', 0)
        if type(expected) is not int or expected < 0:
            raise APIError(400, '请提供标签货位版本')
        duplicate = label.get('location_id') == location['id'] and expected in (current, current - 1)
        if not duplicate and expected != current:
            raise APIError(409, '部件货位已更新，请刷新后重新核对')
        if not duplicate:
            previous = label.get('location_id')
            label.update(location_id=location['id'], location_version=current + 1, location_updated_at=now())
            self.store.put(con, 'daily_labels', label)
            self.store.event(con, label['project_id'], 'piece_location_bound', '登记部件存放货位', label_id=label['id'],
                             from_location_id=previous, location_id=location['id'], location_version=label['location_version'])
        task = self.store.get(con, 'tasks', label['task_id'])
        return {'label': self.contextual_label(con, label, task), 'duplicate': duplicate}

    def handover_view(self, con, item):
        unresolved = []
        for identifier in item['task_ids']:
            try:
                task = self.store.get(con, 'tasks', identifier)
            except APIError:
                unresolved.append({'task_id': identifier, 'reason': '任务资料缺失', 'status': 'missing'})
                continue
            labels = self.label_summary(con, task)
            reason = '任务尚未完成' if task.get('status') != 'done' else '待确认贴标' if labels['pending'] else None
            if labels['expected'] == 0:
                reason = '任务件数需要核对'
            if task.get('archived') or task.get('revision') != item.get('task_revisions', {}).get(identifier):
                reason = '任务版本已变更，请先核对交接'
            if reason:
                unresolved.append({'task_id': identifier, 'title': task.get('title', ''), 'status': task.get('status'),
                                   'reason': reason, 'labels_pending': labels['pending'], 'pause_reason': task.get('pause_reason')})
        return dict(item, unresolved_tasks=unresolved, can_return=not unresolved and item['status'] == 'issued')

    def issue(self, con, data):
        day = self.day(data.get('date'))
        device_id = self.identifier(data.get('device_id'), '胸牌编号')
        person_id = self.identifier(data.get('person_id'), '人员编号')
        person = self.store.get(con, 'people', person_id)
        ids = data.get('task_ids')
        if not isinstance(ids, list) or not ids or len(ids) > 200 or any(not isinstance(i, str) for i in ids) or len(set(ids)) != len(ids):
            raise APIError(400, '请选择不重复的当日任务，最多 200 项')
        dated = {task['id']: task for task in self.dated_tasks(con, day, person_id)}
        if any(identifier not in dated for identifier in ids):
            raise APIError(409, '领取任务必须属于此人员及所选日期的有效排程')
        if all(dated[identifier]['status'] == 'done' for identifier in ids):
            raise APIError(409, '所选任务已全部完成，无需领取胸牌')
        for previous in self.store.all(con, 'badge_handovers'):
            if previous['status'] == 'issued' and (previous['device_id'] == device_id or previous['person_id'] == person_id):
                if (previous['date'] == day and previous['device_id'] == device_id and previous['person_id'] == person_id
                        and set(previous['task_ids']) == set(ids)):
                    return {'handover': self.handover_view(con, previous), 'duplicate': True}
                raise APIError(409, '人员或胸牌已有未归还的领取记录', {'handover': self.handover_view(con, previous)})
        item = {'id': uid('handover'), 'date': day, 'device_id': device_id, 'person_id': person_id,
                'person_name': person.get('name', ''), 'task_ids': ids, 'status': 'issued', 'version': 1,
                'issued_at': now(), 'returned_at': None, 'task_revisions': {i: dated[i]['revision'] for i in ids}}
        self.store.put(con, 'badge_handovers', item)
        self.store.event(con, None, 'badge_issued', '登记胸牌领取', handover_id=item['id'], person_id=person_id, date=day)
        return {'handover': self.handover_view(con, item), 'duplicate': False}

    def return_badge(self, con, identifier, data):
        item = self.store.get(con, 'badge_handovers', self.identifier(identifier, '领取记录编号'))
        expected = data.get('expected_version')
        if type(expected) is not int or expected < 1:
            raise APIError(400, '请提供领取记录版本')
        if item['status'] == 'returned':
            if expected in (item['version'] - 1, item['version']):
                return {'handover': self.handover_view(con, item), 'duplicate': True}
            raise APIError(409, '领取记录已更新，请刷新后重试')
        if expected != item['version']:
            raise APIError(409, '领取记录已更新，请刷新后重试')
        view = self.handover_view(con, item)
        if view['unresolved_tasks']:
            raise APIError(409, '还有未完成任务或待贴标签，请先处理后归还', {'unresolved_tasks': view['unresolved_tasks']})
        item.update(status='returned', returned_at=now(), version=item['version'] + 1)
        self.store.put(con, 'badge_handovers', item)
        self.store.event(con, None, 'badge_returned', '确认当日胸牌归还', handover_id=item['id'], date=item['date'])
        return {'handover': self.handover_view(con, item), 'duplicate': False}

    def build(self, con, day=None, person_id=None, project_id=None, factory_type=None):
        day = self.day(day)
        if factory_type is not None and factory_type not in ('cabinet', 'machinery', 'site'):
            raise APIError(400, '请选择有效工厂类型')
        tasks = self.dated_tasks(con, day, person_id, project_id, factory_type)
        ids = {task['id'] for task in tasks}
        labels = []
        for task in tasks:
            task['labels'] = self.label_summary(con, task)
            labels.extend(self.task_labels(con, task))
        actor = access_control.get_actor() or {}
        owned = actor.get('person_id') if actor.get('access_enabled') and actor.get('role') in ('worker', 'quality') else person_id
        handovers = [self.handover_view(con, item) for item in self.store.all(con, 'badge_handovers')
                     if item['date'] == day and (not owned or item['person_id'] == owned)
                     and (not project_id and not factory_type or any(identifier in ids for identifier in item['task_ids']))]
        ctx = planning.context(self.store, con)
        all_scheduled = {plan['task_id'] for plan in planning.effective_plans(ctx)}
        unscheduled = sum(planning.eligible(task, ctx) and not task.get('demo') and task['id'] not in all_scheduled
                          and (not owned or task.get('assignee') == owned)
                          and (not factory_type or ctx['projects'].get(task['project_id'], {}).get('factory_type') == factory_type)
                          and (not project_id or task['project_id'] == project_id) for task in ctx['tasks'].values())
        return {'date': day, 'tasks': tasks, 'labels': labels, 'handovers': handovers, 'unscheduled_count': unscheduled,
                'summary': {'task_count': len(tasks), 'completed_tasks': sum(task['status'] == 'done' for task in tasks),
                            'blocked_tasks': sum(task['status'] == 'blocked' for task in tasks),
                            'label_count': len({label['id'] for label in labels}), 'labels_pending': sum(task['labels']['pending'] for task in tasks),
                            'issued_badges': sum(item['status'] == 'issued' for item in handovers),
                            'returned_badges': sum(item['status'] == 'returned' for item in handovers)}}

    def badge_context(self, con, task):
        day = self.day()
        # Device callback threads have no HTTP actor; task owner comes from the
        # validated delivery and the task itself, never a supplied query filter.
        tasks = self.dated_tasks(con, day, task.get('assignee'))
        ids = [row['id'] for row in tasks]
        remaining = sum(row['status'] != 'done' or self.label_summary(con, row)['pending'] > 0 for row in tasks)
        return {'date': day, 'scheduled': task['id'] in ids, 'position': ids.index(task['id']) + 1 if task['id'] in ids else 0,
                'total': len(ids), 'remaining_tasks': remaining, 'return_ready': bool(ids) and task['id'] in ids and remaining == 0,
                'labels': self.label_summary(con, task)}
