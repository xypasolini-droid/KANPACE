"""Order fulfillment is independent from engineering review/release status."""
LABELS = {'active': '进行中', 'completed': '已完成·待发货', 'shipped': '已发货'}
CLOSED = frozenset({'completed', 'shipped'})


def is_closed(project):
    return project.get('fulfillment_status', 'active') in CLOSED


def project_aliases(project):
    project.setdefault('fulfillment_status', 'active')
    project['fulfillment_label'] = LABELS.get(project['fulfillment_status'], '进行中')
    project['is_closed'] = is_closed(project)
    for field in ('completed_at', 'shipped_at', 'closed_at', 'reopened_at'):
        project.setdefault(field, None)
    return project
