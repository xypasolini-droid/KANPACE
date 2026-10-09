"""Compatibility projections for existing saved records. Reads do not write."""
import fulfillment


def part_aliases(part):
    for key in ('length', 'width', 'thickness'):
        part[key + '_mm'] = part.get(key)
    part['approved'] = part.get('review_status') == 'approved'
    part['source_doc_id'] = part.get('document_id')
    part.setdefault('notes', '')
    return part


def task_aliases(task):
    task['name'] = task.get('title', '')
    task['role'] = task.get('trade', '')
    task['assignee_id'] = task.get('assignee')
    hours = task.get('hours')
    task['estimated_minutes'] = round(hours * 60, 1) if isinstance(hours, (float, int)) else None
    task.setdefault('notes', '')
    # Read-time defaults expose old saved tasks without inventing production events.
    task.setdefault('progress_recorded', 'completed_quantity' in task)
    task.setdefault('completed_quantity', task.get('quantity', 0) if task.get('status') == 'done' else 0)
    task['remaining_quantity'] = max(0, (task.get('quantity') or 0) - task['completed_quantity'])
    for field, default in {'priority': 0, 'pause_reason': None, 'pause_note': '', 'handover_note': '',
                           'paused_at': None, 'resumed_at': None, 'interrupted_by_task_id': None,
                           'execution_version': 0}.items():
        task.setdefault(field, default)
    return task


def project_aliases(project):
    project.setdefault('factory_type', 'cabinet')
    return fulfillment.project_aliases(project)
