"""Authorized local commands and persisted LangGraph production analysis.

The manufacturing connection stays read-only. Compound analysis saves minimal
checkpoints in a separate factory-local database and runs read-only scheduling
engines. Only explicit user requests propose typed actions; existing endpoints
retain authorization, version checks and confirmed writes. Documents/history
remain data. Optional loopback model summaries cannot choose or execute tools.
"""
from datetime import date
import re

import access_control
import fulfillment
import operations
import production
import scheduling
import langgraph_agent
import engineering_readiness
from kanpace.ai.scope import build_scope

MAX_MESSAGE = 1000
MAX_RESULTS = 12
TASK_LABELS = {'ready': '待开工', 'in_progress': '进行中', 'blocked': '已暂停',
               'done': '已完成', 'invalidated': '已失效', 'pending': '待安排'}
PAUSE_LABELS = {'material': '缺料', 'quality': '质量异常', 'equipment': '设备异常',
                'urgent': '插单', 'other': '其他问题'}
NEGATED = re.compile(r'不要|不用|不必|无需|取消|禁止|暂不|先不|不想|不能|不允许|不得|勿|别|不(?:暂停|恢复|开工|开始|分配|分派|标急|执行|上传|新建)')
QUERY = re.compile(r'查看|看看|查询|搜索|寻找|找一下|有哪些|哪些|多少|情况|为什么|如何|怎么|能否|可以吗|是否|请问')
SOURCE_TEXT = re.compile(r'原文[：:]|(?:图纸|文档|施工图|文件)(?:里|中|上)?(?:写着|写了|说|要求)|忽略.{0,16}(?:规则|指令)|系统提示|```|<script', re.I)
ID_TOKEN = re.compile(r'(?<![A-Za-z0-9_])(?:task|tsk|prj)_[A-Za-z0-9_-]+')
NAVIGATION = (
    ('经营分析', 'owner', '经营看板', 'finance'), ('老板', 'owner', '经营看板', 'finance'),
    ('成本', 'quote', '成本报价', 'finance'), ('报价', 'quote', '成本报价', 'finance'),
    ('利润', 'owner', '经营看板', 'finance'), ('回款', 'owner', '经营看板', 'finance'),
    ('排产', 'scheduling', '资源排产', None), ('排程', 'planning', '生产排程', None),
    ('甘特', 'planning', '生产排程', None), ('工牌', 'device', '工牌联动', None),
    ('开发板', 'device', '工牌联动', None), ('硬件', 'device', '工牌联动', None),
    ('无线', 'device', '工牌联动', None), ('wifi', 'device', '工牌联动', None),
    ('施工图', 'drawing', '图纸拆单', None), ('图纸', 'drawing', '图纸拆单', None),
    ('效果图', 'drawing', '图纸拆单', None), ('3d', 'drawing', '图纸拆单', None),
    ('工艺模板', 'templates', '工艺模板', None), ('模板', 'templates', '工艺模板', None),
    ('excel', 'exchange', '文件互联', 'exchange'), ('文件互联', 'exchange', '文件互联', 'exchange'),
    ('人员', 'people', '工种与人员', None), ('账户', 'access', '账号权限', 'admin'),
    ('账号', 'access', '账号权限', 'admin'),
    ('计价设置', 'settings', '工艺与计价设置', 'finance'), ('工艺设置', 'settings', '工艺与计价设置', 'finance'),
    ('设置', 'manage', '设置与管理', None),
    ('齐套', 'readiness', '生产准备', None), ('质检', 'readiness', '质量与生产准备', None),
    ('任务', 'tasks', '工种任务', None), ('项目', 'projects', '项目订单', None),
    ('工作台', 'overview', '工作台', None),
)


def _fail(message):
    raise access_control.AccessError(400, message)


def _text(value, label, limit=128, optional=True):
    if value is None and optional:
        return ''
    if not isinstance(value, str) or len(value) > limit or '\0' in value:
        _fail(label + '格式无效或过长')
    return value.strip()


def validate(data):
    if not isinstance(data, dict):
        _fail('请填写一条操作指令')
    message = _text(data.get('message'), '消息', MAX_MESSAGE, False)
    if not message:
        _fail('请填写要查询或操作的内容')
    project_id = _text(data.get('project_id'), '项目标识')
    factory_type = _text(data.get('factory_type'), '工厂类型', 30)
    if factory_type and factory_type not in operations.FACTORY_TYPES:
        _fail('请选择有效工厂类型')
    context = data.get('context') or {}
    if not isinstance(context, dict) or len(context) > 8:
        _fail('页面上下文格式无效')
    # Unknown context keys cannot alter actor, permissions or executable tools.
    for key, value in context.items():
        _text(key, '上下文键', 40, False)
        _text(value, '上下文值', 200)
    history = data.get('history', [])
    if not isinstance(history, list) or len(history) > 8:
        _fail('对话历史最多 8 条')
    for item in history:
        if not isinstance(item, dict) or item.get('role') not in ('user', 'assistant'):
            _fail('对话历史格式无效')
        _text(item.get('content'), '历史消息', MAX_MESSAGE, False)
    return message, project_id, factory_type, context


def _allowed(permissions, capability):
    return '*' in permissions or capability in permissions


def _route(page, project_id=None):
    value = {'page': page}
    if project_id:
        value['projectId'] = project_id
    return value


def _nav(page, label, project_id=None):
    return {'id': 'open_' + page, 'type': 'navigate', 'label': label,
            'description': '', 'route': _route(page, project_id)}


def _project_result(project, tasks):
    related = [t for t in tasks if t['project_id'] == project['id'] and t.get('revision') == project.get('revision')]
    done = sum(t.get('status') == 'done' for t in related)
    return {'kind': 'project', 'id': project['id'], 'title': str(project.get('name', '未命名项目'))[:200],
            'detail': ' · '.join(filter(None, [project.get('fulfillment_label', '进行中'),
                      ('交期 ' + project['due_date']) if project.get('due_date') else '未设交期',
                      f'任务完成 {done}/{len(related)}'])),
            'route': _route('drawing', project['id'])}


def _task_result(task, projects, people):
    project = projects[task['project_id']]
    person = people.get(task.get('assignee'), {})
    detail = [str(project.get('name', ''))[:200], task.get('trade', ''),
              TASK_LABELS.get(task.get('status'), '待安排'), person.get('name') or '未分配',
              f"完成 {task.get('completed_quantity', 0)}/{task.get('quantity', 0)}"]
    if fulfillment.is_closed(project):
        detail.append(project.get('fulfillment_label', '项目已关闭'))
    if task.get('pause_reason'):
        detail.append(PAUSE_LABELS.get(task['pause_reason'], '暂停'))
    return {'kind': 'task', 'id': task['id'], 'title': str(task.get('title', '未命名任务'))[:300],
            'detail': ' · '.join(str(x) for x in detail if x),
            'route': _route('tasks', task['project_id'])}


def _trim_query(message):
    value = re.sub(r'^(?:请|帮我|麻烦|给我|我想|想要|现在|先|再|看下|看看|查看|查找|查询|搜索|找一下|寻找|找|打开|看看看)+', '', message)
    value = re.sub(r'(?:的)?(?:项目|订单|任务|工单|情况|状态|怎么样|有哪些|有哪些呢|列表|在哪里|在哪|吧|吗|呢)[？?。！! ]*$', '', value)
    return value.strip(' ：:,，。？?！!「」“”\"\'')


def _mutation_intent(message):
    if NEGATED.search(message) or QUERY.search(message) or SOURCE_TEXT.search(message):
        return None
    command = re.sub(r'^(?:(?:请|帮我|麻烦|现在|立即|先|给我)\s*)+', '', message)
    # A verb in a document/task name is not an imperative.
    verbs = {'pause': r'暂停', 'resume': r'恢复|继续执行', 'start': r'开工|开始执行|开始任务',
             'priority': r'标急|设为紧急|设为加急|标为紧急|加急',
             'assign': r'分配|分派|指派'}
    found = []
    for name, verbs_re in verbs.items():
        if re.search(r'^(?:' + verbs_re + r')', command) or re.search(r'^把.+(?:' + verbs_re + r')', command):
            found.append(name)
    if len(found) != 1:
        return 'multiple' if found else None
    # Do not turn one message containing multiple requested actions into a
    # partial batch. The user chooses a separate card for each explicit task.
    if re.search(r'(?:然后|并且|同时|再|，|,|；|;)\s*(?:请|帮我|把)?\s*(?:暂停|恢复|开工|分配|分派|标急|加急)', command):
        return 'multiple'
    return found[0]


def _matches(message, rows, field, prefix=None):
    lower = message.lower()
    identifiers = [row for row in rows if re.search(r'(?<![A-Za-z0-9_])' + re.escape(row['id']) + r'(?![A-Za-z0-9_])', message)]
    if identifiers:
        return identifiers
    named = [row for row in rows if len(str(row.get(field, '')).strip()) >= 2
             and str(row[field]).strip().lower() in lower]
    if named:
        longest = max(len(row[field]) for row in named)
        return [row for row in named if len(row[field]) == longest]
    return []


def _task_candidates(message, tasks, projects, people, context, intent=None):
    ids = [token for token in ID_TOKEN.findall(message) if not token.startswith('prj_')]
    if ids:
        return [t for t in tasks if t['id'] in ids], True
    named = _matches(message, tasks, 'title')
    if named:
        return named, True
    if re.search(r'当前(?:的)?任务|这(?:个|项)(?:任务)?', message) and context.get('task_id'):
        return [t for t in tasks if t['id'] == context['task_id']], True
    trades = {t.get('trade') for t in tasks if t.get('trade')}
    aliases = {'木作': '木工', '钣金': '五金', '喷漆': '油漆', '电气': '电工', '安装': '装配'}
    matching_trades = {trade for trade in trades if trade in message}
    matching_trades |= {value for key, value in aliases.items() if key in message and value in trades}
    persons = [] if intent == 'assign' else _matches(message, list(people.values()), 'name')
    if matching_trades or persons:
        return [t for t in tasks if (not matching_trades or t.get('trade') in matching_trades)
                and (not persons or t.get('assignee') in {p['id'] for p in persons})], True
    if not intent and re.search(r'待办|待处理|未完成|缺料|缺少物料|物料不足|暂停|阻塞|卡住|逾期|超期|延期|今天|有哪些|哪些|多少|所有|全部|待开工|未开工|待执行|进行中|执行中|正在做|正在干|已完成|已完工', message):
        return list(tasks), False
    query = message
    for p in projects.values():
        query = query.replace(p.get('name', ''), '') if p.get('name') else query
        query = query.replace(p['id'], '')
    if intent:
        query = re.sub(r'^(?:请|帮我|麻烦|现在|立即|先|把)*', '', query)
        query = re.sub(r'^(?:暂停|恢复|继续执行|开工|开始执行|开始任务|标急|设为紧急|设为加急|标为紧急|加急|分配|分派|指派)', '', query)
        query = re.split(r'(?:分配给|分派给|指派给|给|，|,|原因[：:]|交接[：:])', query)[0]
    else:
        query = _trim_query(query)
    query = re.sub(r'(?:任务|工单|工种|当前|这个|这项|今天|全部|所有|的|待办|待处理|逾期|超期|缺料|暂停|进行中|待开工|未完成|已完成|情况|有哪些|哪些|进度|状态|为紧急|标急|暂停)$', '', query)
    query = query.strip(' 的：:,，。？?！!「」“”\"\'')
    if len(query) >= 2 and not re.search(r'任务|待办|情况|哪些|多少|进度|状态', query):
        matching = [t for t in tasks if query.lower() in str(t.get('title', '')).lower()]
        return matching, bool(intent or matching)
    return list(tasks), False


def _field(key, label, value=''):
    return {'key': key, 'label': label, 'type': 'textarea', 'required': True, 'value': value}


def _action(store, con, intent, task, project, people, message, permissions, own_only):
    """Return proposal, explanation. Never invoke a business mutation."""
    if not (_allowed(permissions, 'tasks') or ('own_tasks' in permissions and intent in ('start', 'pause', 'resume'))):
        return None, '当前账号没有这项任务操作权限。'
    if fulfillment.is_closed(project) or project.get('archived'):
        return None, '项目已完成或发货，不能继续安排生产任务。'
    if task.get('archived') or task.get('status') in ('done', 'invalidated'):
        return None, '该任务已完成或失效，不能继续执行。'
    if task.get('revision') != project.get('revision'):
        return None, '该任务属于旧工程版本，请查看最新任务。'
    if intent != 'assign' and (project.get('status') != 'released' or task.get('revision') != project.get('released_revision')):
        return None, '当前工程版本尚未发布，请先完成技术复核。'
    action = {'id': intent + '_' + task['id'], 'type': 'task_' + intent,
              'taskId': task['id'], 'projectId': project['id'],
              'description': project['name'] + ' · ' + task.get('title', '') + ' · ' + task.get('trade', ''),
              'payload': {'expected_execution_version': task.get('execution_version', 0)}}
    payload = action['payload']
    if intent == 'pause':
        if task.get('status') not in ('ready', 'in_progress'):
            return None, '这项任务已经暂停，无需重复暂停。'
        reason = next((key for key, words in [('material', ('缺料', '物料不足')), ('quality', ('质量', '质检异常')),
                       ('equipment', ('设备故障', '机器故障')), ('urgent', ('插单', '急单'))] if any(w in message for w in words)), 'other')
        payload['reason'] = reason
        action.update(label='确认暂停任务', fields=[
            {'key': 'reason', 'label': '暂停原因', 'type': 'select', 'required': True, 'value': reason,
             'options': [{'value': k, 'label': v} for k, v in PAUSE_LABELS.items()]},
            _field('note', '具体原因'), _field('handover_note', '现场交接（进度、物料和下一步）')])
    elif intent in ('start', 'resume'):
        expected = 'ready' if intent == 'start' else 'blocked'
        if task.get('status') != expected:
            return None, ('该任务已暂停，请使用“恢复任务”。' if intent == 'start' and task.get('status') == 'blocked'
                          else '当前任务状态不适合这项操作。')
        blockers = store.start_blockers(con, task)
        if blockers:
            detail = '任务尚未满足开工条件，请联系主管核对物料、前置工序与人员安排。' if own_only else '暂不能开工：' + '；'.join(blockers[:4])
            return None, detail
        if intent == 'start':
            payload['status'] = 'in_progress'
            action['label'] = '确认开工'
        else:
            action.update(label='确认恢复任务', fields=[_field('note', '解除暂停的依据')])
    elif intent == 'priority':
        payload['priority'] = 3
        action.update(label='确认标为紧急', fields=[_field('reason', '调整优先级的原因')])
    elif intent == 'assign':
        if task.get('status') == 'in_progress':
            return None, '任务正在执行，请先暂停并记录交接，再调整负责人。'
        matches = _matches(message, list(people.values()), 'name')
        if len(matches) != 1:
            return None, '请写明唯一的负责人姓名，例如“把这项任务分配给张师傅”，或到任务页选择负责人。'
        person = matches[0]
        if operations.assignment_issues(project, person) or task.get('trade') not in person.get('skills', []):
            return None, '该人员的工种技能或所属工厂不适用于这项任务，请重新选择负责人。'
        payload['person_id'] = person['id']
        action['label'] = '确认分配给' + person['name']
    return action, '已找到这项任务。请核对操作卡片后确认。'


def respond(store, con, data, actor=None):
    message, project_id, factory_type, context = validate(data)
    scope = build_scope(store, con, actor=actor, factory_type=factory_type)
    actor, permissions = scope.actor, scope.permissions
    own_only, financial = scope.own_only, scope.financial
    all_projects, tasks = list(scope.projects), list(scope.tasks)
    visible_ids = scope.project_ids
    people = {p['id']: p for p in scope.people}
    response = {'mode': 'local_commands', 'title': '本地指令助手', 'message': '', 'results': [], 'actions': [],
                'suggestions': ['当前项目情况', '有哪些待办任务', '查看缺料和暂停', '打开生产排程'],
                'scope': {'projectId': project_id or None, 'factoryType': factory_type or None, 'ownTasksOnly': own_only}}
    if project_id and project_id not in visible_ids:
        response['message'] = '当前项目不存在或不在你的可见范围内，请重新选择项目。'
        response['scope']['projectId'] = None
        return response
    named_projects = _matches(message, all_projects, 'name')
    if not named_projects and re.search(r'找|搜索|查询', message) and re.search(r'项目|订单', message) and not re.search(r'任务|工单', message):
        query = _trim_query(message)
        if query and not re.search(r'全部|所有|当前|有哪些|哪些|情况|进度|多少', query):
            named_projects = [p for p in all_projects if query.lower() in str(p.get('name', '')).lower()
                              or query.lower() in str(p.get('client', '')).lower()]
        elif not query:
            project_id = ''
    explicit_projects = [token for token in ID_TOKEN.findall(message) if token.startswith('prj_')]
    if explicit_projects and not all(x in visible_ids for x in explicit_projects):
        response['message'] = '未找到可查看的项目，请核对项目名称或编号。'
        return response
    if len(named_projects) == 1:
        project_id = named_projects[0]['id']
    elif len(named_projects) > 1:
        project_id = ''
    if re.search(r'全部项目|所有项目|跨项目|全厂', message) and not named_projects:
        project_id = ''
    selected = [p for p in all_projects if not project_id or p['id'] == project_id]
    if len(named_projects) > 1:
        selected = named_projects
    projects = {p['id']: p for p in selected}
    tasks = [t for t in tasks if t['project_id'] in projects]
    response['scope']['projectId'] = project_id or None
    intent = _mutation_intent(message)
    negated = bool(NEGATED.search(message))

    def result_tasks(rows, followup=False):
        response['truncated'] = len(rows) > MAX_RESULTS
        response['results'] = [_task_result(t, projects, people) for t in rows[:MAX_RESULTS]]
        if followup:
            for row in response['results']:
                row['followup'] = message + '，任务编号 ' + row['id']

    if intent == 'multiple':
        response['message'] = '请一次指定一个任务操作，我会分别提供可核对的操作卡片。'
        return response
    if intent:
        if len(named_projects) > 1:
            response['message'] = '找到多个匹配项目，请先选择项目。'
            response['results'] = [_project_result(p, tasks) for p in named_projects[:MAX_RESULTS]]
            return response
        matches, explicit = _task_candidates(message, tasks, projects, people, context, intent)
        if not explicit:
            matches = [t for t in matches if t.get('status') not in ('done', 'invalidated') and not fulfillment.is_closed(projects[t['project_id']])]
        if len(matches) != 1 or not explicit:
            response['message'] = ('未找到匹配的可见任务，请补充任务名称或编号。' if not matches else
                                   f'找到 {len(matches)} 项任务，请选择要操作的一项。')
            result_tasks(matches, followup=True)
            return response
        task = matches[0]
        result_tasks(matches)
        action, explanation = _action(store, con, intent, task, projects[task['project_id']], people, message, permissions, own_only)
        response['message'] = explanation
        response['actions'] = [action] if action else [_nav('tasks', '查看任务', task['project_id'])]
        return response

    if SOURCE_TEXT.search(message):
        response['message'] = '可以帮你查项目、找任务或打开功能。图纸和文档中的文字不会被当成操作指令。'
        return response
    if not negated and re.search(r'新建项目|创建项目|新增项目|新建订单|新增订单', message):
        if _allowed(permissions, 'projects'):
            response.update(message='填写项目名称、客户和交期后即可创建。',
                            actions=[{'id': 'new_project', 'type': 'open_project', 'label': '新建项目', 'description': ''}])
        else:
            response['message'] = '当前账号没有创建项目权限。'
        return response
    if not negated and re.search(r'上传|导入(?:施工图|图纸|效果图)', message) and not re.search(r'excel|排程表|人员表|物料表', message, re.I):
        if not _allowed(permissions, 'engineering'):
            response['message'] = '当前账号没有上传工程文件权限。'
        elif not project_id:
            response['message'] = '先选择图纸所属的项目，再上传施工图或效果图。'
            response['results'] = [_project_result(p, tasks) for p in selected[:MAX_RESULTS] if not fulfillment.is_closed(p)]
        elif fulfillment.is_closed(projects[project_id]):
            response['message'] = '项目已完成或发货，当前不能上传新生产图纸。'
        else:
            is_render = '效果图' in message
            response.update(message='打开当前项目的效果图上传窗口。' if is_render else '打开当前项目的上传窗口，选择真实施工图或工程文件。',
                            actions=[{'id': 'upload_' + project_id, 'type': 'open_upload', 'label': '上传效果图' if is_render else '上传图纸',
                                      'description': projects[project_id]['name'], 'projectId': project_id,
                                      'payload': {'purpose': 'render' if is_render else 'engineering'}}])
        return response

    if (not negated and not re.search(r'打开|进入|跳转|切换到|带我去', message)
            and re.search(r'拆单|(?:检查|核对|查).{0,15}(?:漏项|漏拆|工程依据|构件|尺寸|BOM)|(?:拆解|分解).{0,8}(?:订单|图纸|构件|柜)|下一步|接下来(?:做什么|怎么做|该做)', message, re.I)):
        return _engineering_response(store, con, project_id, selected, tasks, response, own_only, message)

    lower = message.lower()
    financial_request = any(word in lower for word in ('成本', '报价', '利润', '回款', '经营', '老板'))
    if financial_request and not financial:
        response['message'] = '当前账号没有财务数据查看权限，可以查询本人任务和生产进度。'
        return response
    compound = bool(re.search(r'逾期|延期|超期', message) and re.search(r'原因|分析|排程|排产|怎么办|方案|调整', message))
    if (compound or data.get('workflow')) and not negated and not re.search(r'打开|进入|跳转', message):
        return _workflow_response(store, con, data, scope, projects, tasks, response)
    # Navigation is explicit, or a supported feature request with no task verb.
    explicit_navigation = bool(re.search(r'打开|进入|带我去|跳转|在哪里|在哪|切换到', message))
    feature_navigation = financial_request or any(w in lower for w in ('排产', '排程', '甘特', '工牌', '开发板', '硬件', '无线', 'wifi', 'excel', '文件互联', '工艺模板'))
    if explicit_navigation or feature_navigation:
        found = next((item for item in NAVIGATION if item[0] in lower), None)
        if found:
            _, page, label, required = found
            if required == 'finance' and not financial:
                response['message'] = '当前账号没有财务与计价设置查看权限。'
                return response
            if required == 'admin' and not _allowed(permissions, '*'):
                response['message'] = '账号管理需要管理员权限。'
                return response
            if required == 'exchange' and not _allowed(permissions, 'exchange'):
                response['message'] = '当前账号没有文件互联操作权限。'
                return response
            response.update(message=('已找到' + label + '。' if not negated else '没有执行变更。可以打开页面查看。'),
                            actions=[_nav(page, '打开' + label, project_id or None)])
            return response

    if negated:
        response['message'] = '没有执行变更。可以继续查询项目或任务。'
        return response

    overdue = bool(re.search(r'逾期|超期|延期', message))
    shortage = bool(re.search(r'缺料|缺少物料|物料不足', message))
    paused = bool(re.search(r'暂停|阻塞|卡住', message))
    todo = bool(re.search(r'待办|待处理|未完成|要做|要干|今天', message))
    requested_status = ('done' if re.search(r'已完成|已完工', message) else
                        'in_progress' if re.search(r'进行中|执行中|正在做|正在干', message) else
                        'ready' if re.search(r'待开工|未开工|待执行', message) else None)
    overview = bool(re.search(r'当前项目|项目情况|项目进度|概览|总览|怎么样|进展', message))
    project_query = bool(re.search(r'项目|订单', message)) and not any((shortage, paused, todo)) and not ('任务' in message or '工单' in message)
    if project_query or overview:
        rows = selected
        query = _trim_query(message)
        if not named_projects and not overview and query and not re.search(r'全部|所有|当前|有哪些|哪些|情况|进度|多少|交期|逾期|超期|延期', query):
            rows = [p for p in rows if query.lower() in str(p.get('name', '')).lower() or query.lower() in str(p.get('client', '')).lower()]
        if overdue:
            rows = [p for p in rows if not fulfillment.is_closed(p) and p.get('due_date') and p['due_date'] < date.today().isoformat()]
        response['results'] = [_project_result(p, tasks) for p in rows[:MAX_RESULTS]]
        response['truncated'] = len(rows) > MAX_RESULTS
        response['message'] = f'找到 {len(rows)} 个可见项目。' if rows else '没有找到匹配的项目。'
        if len(rows) == 1 and (overview or project_id):
            p = rows[0]
            current = [t for t in tasks if t['project_id'] == p['id'] and t.get('revision') == p.get('revision')]
            counts = {status: sum(t.get('status') == status for t in current) for status in ('ready', 'in_progress', 'blocked', 'done')}
            scope_text = '本人任务' if own_only else '当前任务'
            response['message'] = (f"{p['name']} · {p.get('fulfillment_label', '进行中')}。{scope_text} {len(current)} 项："
                                   f"待开工 {counts['ready']}，进行中 {counts['in_progress']}，暂停 {counts['blocked']}，完成 {counts['done']}。")
            response['actions'] = [_nav('tasks', '查看任务', p['id']), _nav('drawing', '查看图纸', p['id'])]
        return response

    matches, explicit = _task_candidates(message, tasks, projects, people, context)
    task_request = explicit or any((overdue, shortage, paused, todo, requested_status)) or bool(re.search(r'任务|工单|工种|工作', message))
    if task_request:
        specific_task = bool(_matches(message, tasks, 'title') or any(not token.startswith('prj_') for token in ID_TOKEN.findall(message)))
        if requested_status:
            matches = [t for t in matches if t.get('status') == requested_status]
        if requested_status != 'done' and (not specific_task or any((overdue, shortage, paused, todo))):
            matches = [t for t in matches if not fulfillment.is_closed(projects[t['project_id']]) and t.get('status') != 'done'
                       and t.get('revision') == projects[t['project_id']].get('revision')]
        if overdue:
            # Use the project's contractual delivery date, never invent a task
            # deadline from its estimated hours or stale planning rows.
            matches = [t for t in matches if projects[t['project_id']].get('due_date')
                       and projects[t['project_id']]['due_date'] < date.today().isoformat()]
        if shortage or paused:
            filtered = []
            material_rows = store.all(con, 'materials') if shortage else []
            for task in matches:
                shortage_found = task.get('pause_reason') == 'material'
                if shortage and not shortage_found:
                    shortage_found = any(m.get('project_id') == task['project_id'] and task['id'] in m.get('task_ids', [])
                                         and production.material_view(m)['shortage_quantity'] > 0 for m in material_rows)
                if (shortage and shortage_found) or (paused and task.get('status') == 'blocked'):
                    filtered.append(task)
            matches = filtered
        matches.sort(key=lambda t: (-t.get('priority', 0), t.get('created_at', ''), t['id']))
        result_tasks(matches)
        suffix = '（按项目交期识别）' if overdue else ''
        response['message'] = (f'找到 {len(matches)} 项' + ('本人' if own_only else '') + '任务' + suffix + '。')
        if not matches:
            response['message'] = '没有找到符合条件的可见任务。'
            if project_id:
                p = projects[project_id]
                current = [t for t in tasks if t.get('revision') == p.get('revision')]
                if fulfillment.is_closed(p):
                    response['message'] = '当前项目已完成或发货，没有待执行任务。'
                    response['actions'] = [_nav('drawing', '查看项目图纸', p['id'])]
                elif not current:
                    response['message'] = '当前项目还没有工种任务。可先核对图纸和构件，再生成任务并完成技术复核。'
                    response['actions'] = [_nav('drawing', '查看图纸与构件', p['id'])]
                else:
                    response['actions'] = [_nav('tasks', '查看项目任务', p['id'])]
        if shortage:
            response['actions'] = [_nav('readiness', '查看物料齐套', project_id or None)]
        return response

    response['message'] = '我是本地指令助手，可以找项目、查待办与缺料任务、打开功能，并为明确的任务准备开工、暂停、恢复、标急或分配卡片。'
    response['suggestions'] = ['找项目', '有哪些待办任务', '打开生产排程', '上传施工图', '新建项目']
    return response


def _workflow_response(store, con, data, scope, projects, tasks, response):
    """Compile only authorized facts; graph never receives DB paths or raw documents."""
    actor = scope.actor
    if scope.own_only:
        response['message'] = '全项目延期分析由主管或技术员处理；你可以查询本人任务和暂停原因。'
        return response
    continuation = data.get('workflow') or {}
    if not isinstance(continuation, dict) or set(continuation) - {'id', 'decision'}:
        _fail('工作流请求格式无效')
    identifier = continuation.get('id', '')
    decision = continuation.get('decision', '')
    if identifier and (not isinstance(identifier, str) or not re.fullmatch(r'wf_[a-f0-9]{32}', identifier)):
        _fail('工作流编号无效')
    if decision not in ('', 'compare', 'refresh', 'cancel') or (decision in ('compare', 'cancel') and not identifier):
        _fail('请选择有效的工作流步骤')
    current = [t for t in tasks if t.get('revision') == projects[t['project_id']].get('revision')]
    if len(current) > 300:
        response['message'] = '本次分析最多 300 道工序，请先选择一个项目。'
        return response
    today = date.today().isoformat()
    can_plan = scope.allows('planning')
    if decision == 'compare' and not can_plan:
        response['message'] = '当前账号可以查看诊断，但没有生成或采用排程的权限。'
        return response
    facts = scope.workflow_facts(projects, store.all(con, 'materials'),
                                 today=today, pause_labels=PAUSE_LABELS)
    ctx = scheduling.context(store, con)
    fingerprint = langgraph_agent.digest({'version': langgraph_agent.VERSION, 'facts': facts,
                                         'schedule_fingerprint': scheduling.fingerprint(ctx)})
    binding = langgraph_agent.digest({'user': (actor or {}).get('id', 'local'),
                                     'role': (actor or {}).get('role', 'local'),
                                     'person_id': (actor or {}).get('person_id'), 'scope': response['scope']})
    fresh_id = 'wf_' + langgraph_agent.digest({'binding': binding, 'fingerprint': fingerprint})[:32]
    if identifier and decision == 'refresh':
        # Explicitly restarting a cancelled/stale record has a stable new ID.
        # Retrying the same restart restores that ID instead of creating copies.
        fresh_id = 'wf_' + langgraph_agent.digest({'binding': binding, 'fingerprint': fingerprint,
                                                  'restart_of': identifier})[:32]
    payload = {'id': identifier if identifier and decision != 'refresh' else fresh_id,
               'binding': binding, 'fingerprint': fingerprint, 'facts': facts,
               'decision': decision, 'resume': bool(identifier and decision != 'refresh')}
    workflow = None
    if identifier and decision in ('compare', 'cancel'):
        try:
            previous = langgraph_agent.run(store.data_dir, dict(payload, decision=''))
            if previous['status'] != 'review':
                workflow = previous
        except langgraph_agent.WorkflowError as exc:
            response['message'] = str(exc)
            return response
    if decision == 'compare' and workflow is None:
        typ = response['scope']['factoryType'] or next(iter(projects.values()), {}).get('factory_type', 'cabinet')
        eligible = [t['id'] for t in current if scheduling.eligible(t, ctx, typ)]
        payload['simulations'] = []
        if eligible:
            config = scheduling.request({'name': '延期分析 · 现有排程', 'start_date': today,
                                         'horizon_days': 30, 'factory_type': typ, 'task_ids': eligible})
            result = scheduling.simulate(store, con, config, ctx)
            payload['simulations'].append({'label': '现有排程', 'config': config, 'method': 'KANPACE 有限容量启发式',
                                           'summary': result['summary'], 'rows': result['rows'],
                                           'unplaced': result['unplaced'], 'frozen_plan_ids': result['frozen_plan_ids']})
            optimized_config = dict(config, name='延期分析 · OR-Tools 优化', engine='ortools',
                                    time_limit_seconds=10, allow_fallback=False)
            try:
                import optimization_engines
                optimized = optimization_engines.schedule_advice(store, con, optimized_config)
                payload['simulations'].append({'label': 'OR-Tools 优化', 'config': optimized_config,
                    'method': optimized['engine']['used'] + ' · ' + optimized['engine']['status'],
                    'summary': optimized['summary'], 'rows': optimized['rows'], 'unplaced': optimized['unplaced'],
                    'frozen_plan_ids': optimized['frozen_plan_ids'], 'validation': optimized.get('validation'),
                    'impact': optimized.get('impact', [])})
            except (ImportError, production.ProductionError, OSError, RuntimeError) as exc:
                payload['simulations'].append({'label': 'OR-Tools 优化', 'config': optimized_config,
                    'method': 'OR-Tools · 不可用', 'error': str(exc)[:300], 'rows': [], 'unplaced': [],
                    'summary': {'scheduled': 0, 'late_tasks': 0, 'unplaced': len(eligible), 'finish_date': None}})
    try:
        workflow = workflow or langgraph_agent.run(store.data_dir, payload)
    except langgraph_agent.WorkflowError as exc:
        response['message'] = str(exc)
        response['actions'] = [_nav('scheduling', '打开排程工作台', response['scope']['projectId'])]
        return response
    workflow['fingerprint'] = fingerprint
    response.update(workflow=workflow, message=workflow['message'], title='生产分析助手',
                    results=[], actions=[], suggestions=['查看缺料和暂停', '有哪些待办任务'])
    if workflow['status'] == 'review':
        if can_plan:
            response['actions'].append({'id': 'compare', 'type': 'workflow_continue', 'label': '继续：比较排程方案',
                                         'payload': {'id': workflow['id'], 'decision': 'compare'}})
        response['actions'].append({'id': 'cancel', 'type': 'workflow_continue', 'label': '保留诊断，暂不排程',
                                     'payload': {'id': workflow['id'], 'decision': 'cancel'}})
    if workflow['status'] == 'stale':
        response['actions'].append({'id': 'refresh', 'type': 'workflow_continue', 'label': '按最新资料重新分析',
                                     'payload': {'id': workflow['id'], 'decision': 'refresh'}})
    if workflow['status'] == 'cancelled':
        response['actions'].append({'id': 'refresh', 'type': 'workflow_continue', 'label': '重新分析',
                                     'payload': {'id': workflow['id'], 'decision': 'refresh'}})
    if workflow['status'] == 'proposed' and can_plan:
        for index, candidate in enumerate(workflow.get('candidates', [])):
            if candidate['rows']:
                response['actions'].append({'id': 'schedule_' + str(index), 'type': 'schedule_preview',
                    'label': '核对并生成预览：' + candidate['label'], 'payload': candidate['config'],
                    'description': '生成排程预览，确认后才采用；不会自动开工或恢复任务。'})
    return response


def _engineering_response(store, con, project_id, selected, tasks, response, own_only, message):
    """Read-only tool selection after caller authorization; documents stay data."""
    if own_only:
        response['message'] = '整单拆解与工程复核由技术员或主管处理；你可以查看本人任务和施工要求。'
        response['actions'] = [_nav('tasks', '查看本人任务', project_id or None)]
        return response
    if not project_id and len(selected) != 1:
        candidates = [p for p in selected if not fulfillment.is_closed(p)]
        response['message'] = '先选择要检查的订单，我会核对工程依据、构件漏项和当前版本。' if candidates else '当前没有可拆解的在制订单。'
        response['results'] = [_project_result(p, tasks) for p in candidates[:MAX_RESULTS]]
        for row in response['results']:
            row['followup'] = '检查拆单依据 ' + row['id']
        response['truncated'] = len(candidates) > MAX_RESULTS
        return response
    project = next((p for p in selected if not project_id or p['id'] == project_id), None)
    if not project:
        response['message'] = '请选择可查看的当前订单。'
        return response
    response['scope']['projectId'] = project['id']
    try:
        report = engineering_readiness.inspect_project(store, con, project)
    except operations.OperationError:
        response['message'] = '当前工艺工作包记录不完整，请在工艺工作包中核对关联关系后重新检查。'
        response['actions'] = [_nav('templates', '核对工艺工作包', project['id'])]
        return response
    response.update(analysis_kind='engineering_readiness', title='拆单检查助手', message=report['summary'],
                    readiness=report, results=[], actions=[],
                    suggestions=['检查漏项', '查看当前项目情况', '查看缺料和暂停'])
    response['results'] = [
        {'kind': 'check', 'id': check['id'], 'title': check['title'], 'detail': check['detail'],
         'severity': check['severity'], 'route': check['route']}
        for check in report['checks'][:8]
    ]
    response['results'].extend(
        {'kind': 'source', 'id': 'evidence_' + source['id'], 'title': source['filename'],
         'detail': source['role_label'] + ' · ' + source['ability'], 'route': source['route']}
        for source in report['sources'][:max(0, MAX_RESULTS - len(response['results']))]
    )
    next_step = report['next_step']
    response['actions'] = [{**_nav(next_step['route']['page'], next_step['label'], project['id']),
                            'route': next_step['route']}]
    response['truncated'] = len(report['checks']) + len(report['sources']) > MAX_RESULTS
    return response
