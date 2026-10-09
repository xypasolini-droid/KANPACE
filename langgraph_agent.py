"""Isolated LangGraph workflow worker. Never opens the manufacturing database.

The parent supplies an authorized, minimal facts snapshot. Checkpoints contain
only this factory/user/scope's snapshot; no LangSmith tracing or remote models.
"""

# Third-party licensing: LangGraph is MIT; runtime dependencies retain
# their separate licenses (including MPL/Apache alternatives). This does
# not license LangSmith cloud services or any LLM weights. See
# THIRD_PARTY_NOTICES.md and docs/open-source/licenses/langgraph-runtime/.
from pathlib import Path
import hashlib
import json
import os
import re
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent
VERSION = '1'
_STATUS_CACHE = None


class WorkflowError(Exception):
    pass


def _environment():
    return {'PATH': os.environ.get('PATH', ''), 'LANG': 'en_US.UTF-8',
            'LANGCHAIN_TRACING_V2': 'false', 'LANGSMITH_TRACING': 'false', 'DO_NOT_TRACK': '1'}


def status():
    """Cached import health check only; never opens a factory or checkpoints."""
    global _STATUS_CACHE
    executable = ROOT / '.venv-agent' / 'bin' / 'python'
    key = (str(executable), executable.stat().st_mtime_ns if executable.is_file() else None)
    cache_seconds = 60 if _STATUS_CACHE and _STATUS_CACHE[2].get('available') else 3
    if _STATUS_CACHE and _STATUS_CACHE[0] == key and time.monotonic() - _STATUS_CACHE[1] < cache_seconds:
        result = dict(_STATUS_CACHE[2])
    else:
        result = {'available': False, 'name': 'LangGraph', 'version': None, 'reasoning': 'deterministic'}
        if not executable.is_file():
            result['reason'] = '请运行 tools/setup_agent.py'
        else:
            try:
                proc = subprocess.run([str(executable), str(Path(__file__).resolve()), '--status'],
                                      text=True, capture_output=True, timeout=8, env=_environment())
                payload = json.loads(proc.stdout)
                if proc.returncode or not payload.get('available'):
                    raise ValueError('Unavailable')
                result.update(payload)
            except subprocess.TimeoutExpired:
                result['reason'] = '本地工作流检测超时，请稍后刷新'
            except (OSError, subprocess.SubprocessError, ValueError, TypeError):
                result['reason'] = '本地工作流依赖不可用，请重新运行安装脚本'
        _STATUS_CACHE = (key, time.monotonic(), dict(result))
    try:
        result['local_model_configured'] = model_settings() is not None
    except WorkflowError:
        result['local_model_configured'] = False
        result['model_reason'] = '本机模型配置无效'
    result['model_verified'] = False
    return result


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(',', ':')).encode()).hexdigest()


def private_directory(data_dir):
    root = Path(data_dir).resolve()
    folder = root / 'agent-workflows'
    if folder.is_symlink():
        raise WorkflowError('助手记录目录无效')
    folder.mkdir(mode=0o700, exist_ok=True)
    if folder.resolve().parent != root:
        raise WorkflowError('助手记录目录无效')
    folder.chmod(0o700)
    for name in ('checkpoints.sqlite', 'workflow.lock'):
        if (folder / name).is_symlink():
            raise WorkflowError('助手记录文件无效')
    return folder


def model_settings():
    """Server-owned opt-in only. No request can configure a destination/model."""
    from urllib.parse import urlsplit
    if os.environ.get('KANPACE_AGENT_LOCAL_MODEL_ENABLE') != '1':
        return None
    endpoint = os.environ.get('KANPACE_AGENT_MODEL_ENDPOINT', '')
    model = os.environ.get('KANPACE_AGENT_MODEL_NAME', '')
    try:
        parsed = urlsplit(endpoint)
    except ValueError as exc:
        raise WorkflowError('本机模型地址无效') from exc
    if parsed.scheme != 'http' or parsed.hostname not in ('127.0.0.1', '::1') or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise WorkflowError('本机模型仅允许明确配置的回环 HTTP 地址')
    if not model or len(model) > 100 or len(endpoint) > 200:
        raise WorkflowError('请配置有效的本机模型名称和地址')
    return {'endpoint': endpoint.rstrip('/') + '/chat/completions', 'model': model}


def local_summary(candidates, settings):
    """Optional wording only; output cannot change graph edges, facts or tools."""
    import urllib.request
    import urllib.error
    if not settings:
        return None
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None
    summaries = [{'label': item['label'], 'summary': item['summary'], 'error': bool(item.get('error'))} for item in candidates]
    body = {'model': settings['model'], 'temperature': 0, 'max_tokens': 180,
            'messages': [{'role': 'system', 'content': '只将给定统计概括为一句中文；不要推测原因、补数字或要求操作。'},
                         {'role': 'user', 'content': json.dumps(summaries, ensure_ascii=False)}]}
    request = urllib.request.Request(settings['endpoint'], data=json.dumps(body).encode(),
                                     headers={'Content-Type': 'application/json'}, method='POST')
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    try:
        with opener.open(request, timeout=5) as response:
            result = json.loads(response.read(20000))
        text = result['choices'][0]['message']['content']
        return text[:800] if isinstance(text, str) else None
    except urllib.error.HTTPError as error:
        error.close()
        return None
    except Exception:
        return None


def run(data_dir, payload, timeout=35):
    """Main interpreter entry point; imports no LangGraph dependencies."""
    executable = ROOT / '.venv-agent' / 'bin' / 'python'
    if not executable.is_file():
        raise WorkflowError('多步骤助手尚未安装，请运行 tools/setup_agent.py')
    folder = private_directory(data_dir)
    payload = dict(payload, local_model=model_settings())
    raw = json.dumps(payload, ensure_ascii=False)
    if len(raw.encode()) > 2_000_000:
        raise WorkflowError('本次分析资料过多，请选择一个项目')
    # Whitelist environment: never inherit cloud keys or tracing configuration.
    env = _environment()
    try:
        result = subprocess.run([str(executable), str(Path(__file__).resolve()), str(folder)],
                                input=raw, text=True, capture_output=True, timeout=timeout, env=env)
    except subprocess.TimeoutExpired as exc:
        raise WorkflowError('分析超时；可使用同一请求继续，不会派发任务') from exc
    if result.returncode:
        raise WorkflowError('多步骤助手运行失败，请重试或检查本地运行环境')
    try:
        response = json.loads(result.stdout)
    except (ValueError, TypeError) as exc:
        raise WorkflowError('多步骤助手返回格式错误') from exc
    if response.get('error'):
        raise WorkflowError(response['error'])
    return response


def worker(folder, payload):
    import fcntl
    import sqlite3
    from typing import TypedDict
    from langgraph.graph import StateGraph, START, END
    from langgraph.types import interrupt, Command
    from langgraph.checkpoint.sqlite import SqliteSaver

    class State(TypedDict, total=False):
        id: str
        binding: str
        fingerprint: str
        facts: dict
        overdue: list
        causes: list
        sources: list
        steps: list
        simulations: list
        candidates: list
        message: str
        decision: str
        status: str
        model_summary: str

    def overdue(state):
        facts = state['facts']
        rows = [p for p in facts['projects'] if not p['closed'] and p.get('due_date')
                and p['due_date'] < facts['today']]
        return {'overdue': rows, 'steps': [{'id': 'overdue', 'title': '核对项目交期',
                'detail': f'可见范围内 {len(rows)} 个项目已过交期，按合同交期核对。', 'status': 'done'}]}

    def causes(state):
        overdue_ids = {p['id'] for p in state['overdue']}
        tasks = {t['id']: t for t in state['facts']['tasks']}
        rows, sources = [], []
        for project in state['overdue']:
            sources.append({'kind': 'project', 'id': project['id'], 'project_id': project['id'],
                            'label': project['name'] + ' · 交期 ' + project['due_date'], 'page': 'drawing'})
        for task in tasks.values():
            if task['project_id'] not in overdue_ids or task['status'] == 'done':
                continue
            evidence = []
            if task['status'] == 'blocked':
                evidence.append('暂停登记：' + (task.get('pause_label') or '原因待补充'))
            for material in state['facts']['materials']:
                if task['id'] in material['task_ids'] and material['shortage_quantity'] > 0:
                    evidence.append(f"物料 {material['name']} 缺 {material['shortage_quantity']} {material['unit']}"
                                    + (f"，预计 {material['expected_date']} 到料" if material.get('expected_date') else '，到料日期未确认'))
                    sources.append({'kind': 'material', 'id': material['id'], 'project_id': task['project_id'],
                                    'label': material['name'], 'page': 'readiness'})
            dependencies = [tasks.get(x) for x in task.get('dependencies', [])]
            if any(dep is None or dep['status'] != 'done' for dep in dependencies):
                evidence.append('存在未完成或待核对的前序工序')
            if not task.get('assignee'):
                evidence.append('尚未分派负责人')
            if not task.get('minutes_known'):
                evidence.append('加工工时待确认')
            rows.append({'task_id': task['id'], 'project_id': task['project_id'], 'title': task['title'],
                         'evidence': evidence or ['现有登记未发现明确阻塞，请负责人核对现场进度'],
                         'proven_cause': False})
            sources.append({'kind': 'task', 'id': task['id'], 'project_id': task['project_id'],
                            'label': task['title'], 'page': 'tasks'})
        unique = {(s['kind'], s['id']): s for s in sources}
        return {'causes': rows, 'sources': list(unique.values()), 'steps': state['steps'] + [
            {'id': 'causes', 'title': '核对暂停、物料与前序', 'status': 'done',
             'detail': f'找到 {len(rows)} 项未完成任务的登记依据；这些是风险线索，不等于已经证明延期根因。'}]}

    def review(state):
        reply = interrupt({'kind': 'schedule_review', 'label': '比较现有排程与 OR-Tools 优化方案',
                           'can_compare': state['facts']['can_plan']})
        decision = reply.get('decision') if isinstance(reply, dict) else 'cancel'
        if decision != 'compare' or not state['facts']['can_plan']:
            return {'decision': 'cancel', 'status': 'cancelled', 'message': '已保留诊断结果，没有调整排程。'}
        return {'decision': 'compare', 'simulations': reply.get('simulations', [])}

    def compare(state):
        candidates = []
        for simulation in state.get('simulations', []):
            rows = simulation.get('rows', [])
            candidates.append({**simulation, 'late_days': sum(r.get('delay_days') or 0 for r in rows)})
        comparison = '没有满足条件的可排工序，先补齐发布版本、人员、物料或工时。'
        if len(candidates) == 2:
            a, b = candidates
            comparison = (f"现有排程：{a['summary']['scheduled']} 项可排、{a['summary']['late_tasks']} 项预计逾期；"
                          f"优化方案：{b['summary']['scheduled']} 项可排、{b['summary']['late_tasks']} 项预计逾期。")
            if b.get('error'):
                comparison = '现有排程已计算；OR-Tools 未产生可用方案：' + b['error']
            elif a['summary'] == b['summary'] and a['late_days'] == b['late_days']:
                comparison += '本次没有看出改善，不自动推荐改期。'
            else:
                comparison += '请比较受影响任务、未排原因和完工时间后决定。'
        return {'candidates': candidates, 'steps': state['steps'] + [
            {'id': 'compare', 'title': '比较两种排程', 'status': 'done', 'detail': comparison}],
            'message': comparison}

    def proposal(state):
        return {'status': 'proposed', 'model_summary': local_summary(state.get('candidates', []), payload.get('local_model')),
                'steps': state['steps'] + [
            {'id': 'proposal', 'title': '选择方案并核对后采用', 'status': 'pending',
             'detail': '生成预览后显示工序安排和差异，确认采用仍经过生产数据版本与岗位权限检查。'}]}

    builder = StateGraph(State)
    for name, node in [('overdue', overdue), ('causes', causes), ('review', review), ('compare', compare), ('proposal', proposal)]:
        builder.add_node(name, node)
    builder.add_edge(START, 'overdue')
    builder.add_edge('overdue', 'causes')
    builder.add_edge('causes', 'review')
    builder.add_conditional_edges('review', lambda state: 'compare' if state.get('decision') == 'compare' else END)
    builder.add_edge('compare', 'proposal')
    builder.add_edge('proposal', END)
    identifier = payload.get('id', '')
    if not re.fullmatch(r'wf_[a-f0-9]{32}', identifier):
        return {'error': '分析记录编号无效'}
    os.umask(0o077)
    with open(folder / 'workflow.lock', 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        with sqlite3.connect(folder / 'checkpoints.sqlite', check_same_thread=False) as conn:
            graph = builder.compile(checkpointer=SqliteSaver(conn))
            config = {'configurable': {'thread_id': identifier}}
            saved = graph.get_state(config)
            if saved.values:
                if saved.values['binding'] != payload['binding']:
                    return {'error': '分析记录不在当前账号或项目范围内'}
                if saved.values['fingerprint'] != payload['fingerprint']:
                    return {'id': identifier, 'status': 'stale', 'steps': [], 'sources': [], 'causes': [], 'candidates': [],
                            'message': '生产资料已经变化，请按最新资料重新分析。'}
                if saved.next and not any(task.interrupts for task in saved.tasks):
                    # A previous process may have exited between two nodes.
                    # Continue persisted deterministic work before accepting a decision.
                    graph.invoke(None, config)
                    saved = graph.get_state(config)
                if saved.next and payload.get('decision') in ('compare', 'cancel'):
                    graph.invoke(Command(resume={'decision': payload['decision'],
                                                 'simulations': payload.get('simulations', [])}), config)
            elif payload.get('resume'):
                return {'error': '未找到当前工厂的分析记录，请重新分析'}
            else:
                graph.invoke({'id': identifier, 'binding': payload['binding'], 'fingerprint': payload['fingerprint'],
                              'facts': payload['facts'], 'status': 'review'}, config)
            current = graph.get_state(config)
            state = current.values
            return {'id': identifier, 'status': 'review' if current.next else state.get('status', 'proposed'),
                    'engine': 'LangGraph', 'engine_version': '1.2.11', 'reasoning': 'deterministic',
                    'steps': state.get('steps', []), 'sources': state.get('sources', []),
                    'causes': state.get('causes', []), 'candidates': state.get('candidates', []),
                    'model_summary': state.get('model_summary'),
                    'overdue_count': len(state.get('overdue', [])),
                    'message': state.get('message') or (f"已核对 {len(state.get('overdue', []))} 个过期项目。"
                        + ('可继续比较排程方案。' if state['facts']['can_plan'] else '可将诊断交给主管核对排程。'))}


if __name__ == '__main__':
    try:
        if sys.argv[1:] == ['--status']:
            from importlib.metadata import version
            from langgraph.graph import StateGraph
            from langgraph.checkpoint.sqlite import SqliteSaver
            print(json.dumps({'available': True, 'name': 'LangGraph', 'version': version('langgraph'),
                              'checkpoint_version': version('langgraph-checkpoint-sqlite'), 'reasoning': 'deterministic'}))
        else:
            request = json.loads(sys.stdin.read(2_000_001))
            print(json.dumps(worker(Path(sys.argv[1]), request), ensure_ascii=False))
    except Exception:
        print(json.dumps({'error': '本地工作流未完成，请重新分析或检查运行环境'}, ensure_ascii=False))
