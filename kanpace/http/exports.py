"""Existing project exports and spreadsheet-safe cell encoding."""
from __future__ import annotations

import csv
import io
import json
from kanpace.core.errors import APIError
from kanpace.core.validation import now


class ProjectExports:
    def export_project(self, con, project, fmt):
        store = self.server.store
        parts = store.active_parts(con, project['id'])
        tasks = store.active_tasks(con, project['id'])
        quote_data = store.quote(con, project['id'])
        stem = 'cabinet-flow-' + project['id'] + '-R' + str(project['revision'])
        if fmt == 'json':
            result = {'project': project, 'parts': parts, 'tasks': tasks, 'quote': quote_data,
                      'documents': store.all(con, 'documents', project['id']),
                      'events': store.all(con, 'events', project['id']), 'exported_at': now()}
            body = json.dumps(result, ensure_ascii=False, indent=2).encode('utf-8')
            mime = 'application/json; charset=utf-8'
        elif fmt in ('csv', 'bom_csv'):
            stream = io.StringIO(newline='')
            writer = csv.writer(stream)
            def safe(value):
                value = '' if value is None else str(value)
                if value.lstrip().startswith(('=', '+', '-', '@')) or value.startswith(('\t', '\r', '\n')):
                    value = "'" + value
                return value
            part_map = {p['id']: p for p in parts}
            people = {p['id']: p['name'] for p in store.all(con, 'people')}
            task_map = {t['id']: t for t in tasks}
            if fmt == 'csv':
                writer.writerow(['项目', '版本', '任务ID', '部件', '原始图号', '工种', '工序', '负责人', '状态',
                                 '预计工时h', '前置任务ID', '前置工序', '来源文件', '来源引用', '验收要求', '备注',
                                 '原数量件', '已完成件', '剩余件', '进度已记录', '优先级', '暂停类别', '暂停原因', '交接说明'])
                for task in tasks:
                    part = part_map.get(task.get('part_id'), {})
                    source = part.get('source') or task.get('source') or {}
                    if not isinstance(source, dict):
                        source = {'reference': str(source)}
                    writer.writerow([safe(v) for v in [project['name'], task.get('revision'), task['id'],
                        part.get('name', '整柜'), source.get('part_number') or source.get('external_id'),
                        task.get('trade'), task.get('title'), people.get(task.get('assignee'), '待分派'), task['status'],
                        task.get('hours'), ' | '.join(task.get('dependencies', [])),
                        ' | '.join(task_map.get(dep, {}).get('title', dep) for dep in task.get('dependencies', [])),
                        source.get('model_file') or source.get('file'), source.get('reference'),
                        task.get('acceptance'), task.get('notes'), task.get('quantity'),
                        task['completed_quantity'] if task['progress_recorded'] else None,
                        task['remaining_quantity'] if task['progress_recorded'] else None,
                        task['progress_recorded'], task['priority'], task['pause_reason'], task['pause_note'], task['handover_note']]])
            else:
                writer.writerow(['项目', '版本', '部件', '原始图号', '材质', '类别', '长mm', '宽mm', '厚mm', '整单数量', '表面处理', '审核', '来源'])
                for part in parts:
                    source = part.get('source', {})
                    writer.writerow([safe(v) for v in [project['name'], project['revision'], part.get('name'),
                        source.get('part_number') or source.get('external_id'), part.get('material'), part.get('category'),
                        part.get('length'), part.get('width'), part.get('thickness'), part.get('quantity'), part.get('finish'),
                        part.get('review_status'), source.get('model_file') or source.get('file')]])
            body = ('\ufeff' + stream.getvalue()).encode('utf-8')
            mime = 'text/csv; charset=utf-8'
        else:
            raise APIError(400, '仅支持 csv（任务）、bom_csv（部件）或 json 导出')
        self.send_bytes(200, body, mime, {'Content-Disposition': 'attachment; filename="' + stem + ('-bom.csv' if fmt == 'bom_csv' else '.' + fmt) + '"'})
