"""Optional local optimization engines; advice never changes execution or material ledgers.

Only schedule_preview persists a normal, explicitly applicable scheduling scenario.
Both solvers run as isolated processes and their outputs are independently checked.
"""

# Third-party licensing: see THIRD_PARTY_NOTICES.md and licenses/optimization/.
# OR-Tools is Apache-2.0; PackingSolver is MIT. HiGHS/Boost and embedded
# components retain their own notices. The source release supplies pinned
# installers, not the local solver binary or its build/dependency tree.
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
import csv
import json
import math
import os
import subprocess
import tempfile
import time as clock

import planning
import production as p
import scheduling

ROOT = Path(__file__).resolve().parent
WORKER = ROOT / 'optimization_worker.py'


def _python():
    name = 'Scripts/python.exe' if os.name == 'nt' else 'bin/python'
    return Path(os.environ.get('KANPACE_OPTIMIZATION_PYTHON', str(ROOT / '.venv-optimization' / name)))


def _packing_binary():
    suffix = '.exe' if os.name == 'nt' else ''
    return Path(os.environ.get('KANPACE_PACKINGSOLVER', str(ROOT / 'bin/optimization' / ('packingsolver_rectangleguillotine' + suffix))))


def _worker(payload, timeout):
    proc = subprocess.run([str(_python()), str(WORKER)], input=json.dumps(payload, ensure_ascii=False),
                          text=True, capture_output=True, timeout=timeout, cwd=str(ROOT))
    try:
        result = json.loads(proc.stdout)
    except (ValueError, TypeError):
        raise RuntimeError('优化进程未返回有效 JSON') from None
    if not isinstance(result,dict):
        raise RuntimeError('优化进程未返回有效 JSON 对象')
    if proc.returncode or result.get('error'):
        raise RuntimeError(result.get('message', '优化进程失败'))
    return result


def status():
    ortools = {'available': False, 'name': 'Google OR-Tools CP-SAT', 'version': None}
    if _python().is_file():
        try:
            ortools.update(_worker({'operation': 'status'}, 20))
        except (OSError, subprocess.SubprocessError, RuntimeError) as error:
            ortools['reason'] = str(error)
    else:
        ortools['reason'] = '请运行优化引擎安装脚本'
    manifest_path = ROOT / 'licenses/optimization/manifest.json'
    manifest = json.loads(manifest_path.read_text()) if manifest_path.is_file() else {}
    packing = {'available': _packing_binary().is_file(), 'name': 'PackingSolver rectangle-guillotine',
               'version': manifest.get('packingsolver', {}).get('commit')}
    return {'ortools': ortools, 'packingsolver': packing}


def _limit(value, default=10):
    value = default if value is None else value
    if type(value) not in (int, float) or not math.isfinite(value) or not 1 <= value <= 60:
        p.fail('求解时限须为 1–60 秒')
    return float(value)


def _prepare(store, con, config, ctx, non_interruptible):
    first = date.fromisoformat(config['start_date'])
    origin = datetime.combine(first, time())
    horizon = config['horizon_days'] * 1440
    def offset(stamp):
        return math.ceil((stamp-origin).total_seconds()/60)
    days = [first+timedelta(days=i) for i in range(config['horizon_days']) if (first+timedelta(days=i)).isoweekday() in ctx['calendar']['weekdays']]
    candidates = [t for t in ctx['tasks'].values() if scheduling.eligible(t, ctx, config['factory_type']) and (not config['task_ids'] or t['id'] in config['task_ids'])]
    fixed = planning.effective_plans(ctx)
    fixed_ids = {x['task_id'] for x in fixed}
    occupied, ready = defaultdict(set), {}
    for plan in fixed:
        task = ctx['tasks'][plan['task_id']]
        resources = ['person:'+plan['person_id']] + (['wc:'+task['workcenter_id']] if task.get('workcenter_id') else [])
        if plan.get('minute_segments'):
            for seg in plan['minute_segments']:
                for resource in resources:
                    occupied[(resource, seg['date'])].update(range(seg['start_minute'], seg['end_minute']))
        else:
            for alloc in plan.get('allocations', []):
                beginning = max((max(occupied[(r,alloc['date'])],default=-1)+1 for r in resources),default=0)
                for resource in resources:
                    occupied[(resource,alloc['date'])].update(range(beginning, beginning+math.ceil(alloc['minutes'])))
        ready[task['id']] = offset(datetime.fromisoformat(plan['ready_at'])) if plan.get('ready_at') else offset(datetime.combine(date.fromisoformat(plan['end_date'])+timedelta(days=1),time()))
    overrides = {x['task_id']:x for x in config['overrides']}
    pending = {t['id']:t for t in candidates if t['id'] not in fixed_ids}
    jobs, details, rejected = [], {}, {}
    for key, task in pending.items():
        project = ctx['projects'][task['project_id']]
        errors, warnings = planning.person_issues(task,ctx), []
        opt = overrides.get(key,{})
        minutes = opt.get('minutes') if opt.get('minutes') is not None else planning.estimate(task)
        setup, wait = opt.get('setup_minutes',0), opt.get('wait_hours',0)
        if minutes is None or minutes <= 0: errors.append('加工时间待确认')
        release, deps = 480, []
        for dep in task.get('dependencies',[]):
            previous = ctx['tasks'].get(dep)
            if not previous or previous.get('project_id') != task['project_id'] or previous.get('archived') or previous.get('revision') != task['revision']:
                errors.append('前置任务不存在或工程版本无效')
            elif previous['status'] == 'done': pass
            elif dep in ready: release=max(release,ready[dep])
            elif dep in pending: deps.append(dep)
            else: errors.append('前置工序未完成且未纳入排程：'+previous['title'])
        for material in ctx['materials']:
            if key in material.get('task_ids',[]) and p.material_view(material)['shortage_quantity']:
                if material.get('expected_date'):
                    release=max(release,offset(datetime.combine(date.fromisoformat(material['expected_date']),time(8))))
                    warnings.append('以 '+material['name']+' 预计到料日排程，开工仍需实际齐套')
                else: errors.append('物料缺口未确认到货日：'+material['name'])
        for issue in ctx['issues']:
            if issue.get('task_id')==key and issue['status']!='resolved' and issue['type']!='urgent':
                errors.append('现场异常未解除：'+issue['title'])
        for check in p.check_sheet(store,con,task)['items']:
            if check['status']!='ready': warnings.append('开工前确认：'+check['label'])
        if task['status']=='blocked': warnings.append('已暂停，排程不会自动恢复开工')
        resource_caps=[('person:'+str(task.get('assignee')),ctx['people'].get(task.get('assignee'),{}).get('capacity_minutes'))]
        if task.get('workcenter_id'):
            wc=ctx['workcenters'].get(task['workcenter_id'])
            if not wc or wc.get('factory_id')!=project.get('factory_id'): errors.append('工作中心归属无效')
            resource_caps.append(('wc:'+task['workcenter_id'],wc.get('capacity_minutes') if wc else None))
        if any(type(cap) not in (int,float) or not math.isfinite(cap) or not 0<cap<=960 for _,cap in resource_caps):
            errors.append('需确认人员和工作中心每日有效容量（最多 16 小时）')
        if errors:
            rejected[key]={'task_id':key,'title':task['title'],'blockers':list(dict.fromkeys(errors))}; continue
        windows=[]
        for day in days:
            base=offset(datetime.combine(day,time(8)))
            free=[i for i in range(int(min(cap for _,cap in resource_caps))) if base+i>=release and all(i not in occupied[(r,day.isoformat())] for r,_ in resource_caps)]
            for minute in free:
                absolute=base+minute
                if windows and windows[-1][1]==absolute: windows[-1][1]+=1
                else: windows.append([absolute,absolute+1])
        due=offset(datetime.combine(date.fromisoformat(project['due_date'])+timedelta(days=1),time())) if project.get('due_date') else horizon+math.ceil(wait*60)
        job={'id':key,'duration':math.ceil(minutes+setup),'wait_minutes':math.ceil(wait*60),'release':release,
             'due':max(0,due),'windows':windows,'resources':[r for r,_ in resource_caps],'dependencies':deps,
             'priority':task.get('priority',0),'rush':key in config['rush_task_ids'],'non_interruptible':key in non_interruptible}
        jobs.append(job)
        details[key]={'task':task,'minutes':minutes,'setup':setup,'wait':wait,'warnings':warnings,
                      'source':'manual' if opt.get('minutes') is not None else 'task_estimate'}
    # Eliminate cycles and every successor of rejected/missing predecessors.
    accepted=set(); ordered=[]
    todo={j['id']:j for j in jobs}
    while todo:
        ready_jobs=[j for j in todo.values() if all(d in accepted for d in j['dependencies'])]
        if not ready_jobs: break
        for job in ready_jobs:
            ordered.append(job); accepted.add(job['id']); del todo[job['id']]
    for key in todo:
        rejected[key]={'task_id':key,'title':pending[key]['title'],'blockers':['前置工序不可排或前置关系循环']}
    return {'operation':'schedule','jobs':ordered,'horizon_minutes':horizon},details,list(rejected.values()),[x['id'] for x in fixed],origin


def validate_schedule(payload, output):
    """Independent arithmetic validator; no solver internals or DB writes."""
    jobs={j['id']:j for j in payload['jobs']}; rows={}; busy=defaultdict(list); errors=[]
    if not isinstance(output,dict) or not isinstance(output.get('rows'),list):
        return {'valid':False,'errors':['求解结果时间片格式无效'],'checked_tasks':0}
    for row in output.get('rows',[]):
        if not isinstance(row,dict): errors.append('工序结果须为对象'); continue
        key=row.get('task_id')
        if not isinstance(key,str) or key not in jobs or key in rows: errors.append('未知或重复工序'); continue
        job=jobs[key]; segments=row.get('segments',[])
        if not isinstance(segments,list) or not segments or any(not isinstance(s,list) or len(s)!=2 or any(type(v) is not int for v in s) or s[0]>=s[1] for s in segments):
            errors.append(key+' 无效时间片'); continue
        segments=sorted(segments)
        if sum(b-a for a,b in segments)!=job['duration']: errors.append(key+' 作业分钟不一致')
        if job.get('non_interruptible') and len(segments)!=1: errors.append(key+' 不可中断工序被拆分')
        if type(row.get('start')) is not int or type(row.get('end')) is not int:
            errors.append(key+' 起止须为整数分钟'); continue
        if row['start']!=segments[0][0] or row['end']!=segments[-1][1] or row['start']<job['release']:
            errors.append(key+' 起止或最早开工不一致')
        for a,b in segments:
            if not any(left<=a<b<=right for left,right in job['windows']): errors.append(key+' 超班次或撞冻结计划')
            for resource in job['resources']: busy[resource].append((a,b,key))
        rows[key]=row
    excluded=output.get('unplaced',[])
    if not isinstance(excluded,list) or any(not isinstance(k,str) or k not in jobs for k in excluded) or len(set(excluded))!=len(excluded) or set(rows)&set(excluded) or set(rows)|set(excluded)!=set(jobs):
        errors.append('求解结果必须逐一列明已排和未排工序')
    for resource, intervals in busy.items():
        intervals.sort()
        if any(intervals[i][0]<intervals[i-1][1] for i in range(1,len(intervals))): errors.append(resource+' 资源冲突')
    for key,row in rows.items():
        for dep in jobs[key]['dependencies']:
            if dep not in rows or row['start']<rows[dep]['end']+jobs[dep]['wait_minutes']:
                errors.append(key+' 前置或等待不满足')
    return {'valid':not errors,'errors':errors,'checked_tasks':len(rows)}


def validate_baseline(payload, baseline, origin):
    """Convert heuristic minute segments to the same independent certificate."""
    rows=[]
    try:
        for row in baseline['rows']:
            segments=[]
            for segment in row['minute_segments']:
                day=datetime.combine(date.fromisoformat(segment['date']),time(8))
                base=int((day-origin).total_seconds()/60)
                segments.append([base+segment['start_minute'],base+segment['end_minute']])
            rows.append({'task_id':row['task_id'],
                         'start':int((datetime.fromisoformat(row['start_at'])-origin).total_seconds()/60),
                         'end':int((datetime.fromisoformat(row['end_at'])-origin).total_seconds()/60),
                         'segments':segments})
        selected={row['task_id'] for row in rows}
        certificate={'rows':rows,'unplaced':[job['id'] for job in payload['jobs'] if job['id'] not in selected]}
        return validate_schedule(payload,certificate)
    except (KeyError,TypeError,ValueError,OverflowError):
        return {'valid':False,'errors':['启发式时间片无法转换为独立校验凭证'],'checked_tasks':0}


def prepare_schedule(store,con,data):
    config=scheduling.request(data)
    # Reuse current validation of scope, ids, overrides and all business gates.
    ctx=scheduling.context(store,con)
    baseline=scheduling.simulate(store,con,config,ctx)
    limit=_limit(data.get('time_limit_seconds'))
    fallback=data.get('allow_fallback',True)
    if type(fallback) is not bool: p.fail('allow_fallback 须为布尔值')
    non_interruptible=data.get('non_interruptible_task_ids',[])
    if not isinstance(non_interruptible,list) or len(non_interruptible)>300 or any(not isinstance(x,str) for x in non_interruptible): p.fail('不可中断工序列表无效')
    payload,details,rejected,frozen,origin=_prepare(store,con,config,ctx,set(non_interruptible))
    scope={t['id'] for t in ctx['tasks'].values() if scheduling.eligible(t,ctx,config['factory_type']) and (not config['task_ids'] or t['id'] in config['task_ids'])}
    if set(non_interruptible)-scope: p.fail('不可中断工序必须在当前可排范围内')
    config['engine_options']={'time_limit_seconds':limit,'non_interruptible_task_ids':non_interruptible}
    payload['time_limit_seconds']=limit
    return {'config':config,'ctx':ctx,'baseline':baseline,'payload':payload,'details':details,'rejected':rejected,
            'frozen':frozen,'origin':origin.isoformat(),'limit':limit,'fallback':fallback,'non_interruptible':non_interruptible}


def solve_prepared(prepared):
    config=prepared['config']; ctx=prepared['ctx']; baseline=prepared['baseline']; payload=prepared['payload']
    details=prepared['details']; rejected=prepared['rejected']; frozen=prepared['frozen']; origin=datetime.fromisoformat(prepared['origin'])
    limit=prepared['limit']; fallback=prepared['fallback']
    engine={'requested':'Google OR-Tools CP-SAT','used':'Google OR-Tools CP-SAT','status':'NOT_RUN','version':None,'fallback_reason':None}
    validation={'valid':False,'errors':[]}; result=None
    try:
        output=_worker(payload,limit+15)
        if not isinstance(output,dict): raise RuntimeError('优化进程返回格式无效')
        engine.update({k:output.get(k) for k in ('status','version','wall_time_seconds','objective_value','best_objective_bound')})
        if output.get('status') not in ('FEASIBLE','OPTIMAL'): raise RuntimeError('CP-SAT 返回 '+str(output.get('status','UNKNOWN')))
        validation=validate_schedule(payload,output)
        if not validation['valid']: raise RuntimeError('求解结果独立校验失败：'+'；'.join(validation['errors']))
        rows=[]
        for raw in output['rows']:
            detail=details[raw['task_id']]; task=detail['task']; project=ctx['projects'][task['project_id']]
            start=origin+timedelta(minutes=raw['start']); end=origin+timedelta(minutes=raw['end']); ready=end+timedelta(minutes=math.ceil(detail['wait']*60))
            segments=[]; allocs=defaultdict(int)
            for a,b in sorted(raw['segments']):
                when=origin+timedelta(minutes=a); day=when.date().isoformat(); start_minute=when.hour*60+when.minute-480
                segments.append({'date':day,'start_minute':start_minute,'end_minute':start_minute+b-a}); allocs[day]+=b-a
            rows.append({'task_id':task['id'],'title':task['title'],'project_id':task['project_id'],'person_id':task['assignee'],
                'workcenter_id':task.get('workcenter_id'),'start_at':scheduling.iso(start),'end_at':scheduling.iso(end),'ready_at':scheduling.iso(ready),
                'minutes':round(detail['minutes'],2),'setup_minutes':detail['setup'],'wait_hours':detail['wait'],'planned_minutes':sum(allocs.values()),
                'allocations':[{'date':d,'minutes':m} for d,m in sorted(allocs.items())],'minute_segments':segments,'warnings':detail['warnings'],
                'delay_days':max(0,(ready.date()-date.fromisoformat(project['due_date'])).days) if project.get('due_date') else None,
                'task_revision':task['revision'],'task_execution_version':task.get('execution_version',0),'minutes_source':detail['source']})
        unplaced=rejected+[{'task_id':key,'title':details[key]['task']['title'],'blockers':['求解时限与容量条件下未排入；请核对日历、前序及工时']} for key in output['unplaced']]
        result={'rows':sorted(rows,key=lambda r:(r['start_at'],r['task_id'])),'unplaced':unplaced,'frozen_plan_ids':frozen,
                'summary':{'scheduled':len(rows),'unplaced':len(unplaced),'late_tasks':sum(bool(r['delay_days']) for r in rows),
                           'finish_date':max((r['ready_at'][:10] for r in rows),default=None),'frozen_plans':len(frozen)}}
    except (OSError,subprocess.SubprocessError,RuntimeError) as error:
        if not fallback or prepared['non_interruptible']: p.fail('优化引擎未产生可用建议：'+str(error),503)
        engine.update(used='KANPACE heuristic',fallback_reason=str(error))
        if engine['status']=='NOT_RUN': engine['status']='UNAVAILABLE'
        validation=validate_baseline(payload,baseline,origin)
        if not validation['valid']:
            p.fail('启发式回退未通过当前资源与前序约束校验：'+'；'.join(validation['errors']),503)
        result=baseline
        validation['note']='现有启发式通过同一独立约束校验；不是 OR-Tools 解'
        engine['solver_status']=engine['status']
        if engine['status']!='UNAVAILABLE': engine['status']='FALLBACK_VALIDATED'
        for name in ('objective_value','best_objective_bound'):
            engine.pop(name,None)
    prior={r['task_id']:r for r in baseline['rows']}; current={r['task_id']:r for r in result['rows']}
    impact=[]
    for key in sorted(set(prior)|set(current)):
        old,new=prior.get(key),current.get(key)
        if old and new and old['ready_at']==new['ready_at']: continue
        impact.append({'task_id':key,'title':(new or old)['title'],'before_end':old['ready_at'] if old else None,'after_end':new['ready_at'] if new else None,
                       'change':'rescheduled' if old and new else 'scheduled' if new else 'unplaced',
                       'shift_days': (date.fromisoformat(new['ready_at'][:10])-date.fromisoformat(old['ready_at'][:10])).days if old and new else None,
                       'shift_minutes': round((datetime.fromisoformat(new['ready_at'])-datetime.fromisoformat(old['ready_at'])).total_seconds()/60) if old and new else None})
    model_jobs={j['id']:j for j in payload['jobs']}
    def metrics(rows):
        total=0; weighted=0
        for row in rows:
            job=model_jobs.get(row['task_id'])
            if not job: continue
            end=math.ceil((datetime.fromisoformat(row['ready_at'])-origin).total_seconds()/60)
            delay=max(0,end-job['due']); total+=delay
            weighted+=delay*(1+min(100,max(0,job.get('priority',0)))+(100 if job.get('rush') else 0))
        span=round((max(datetime.fromisoformat(r['ready_at']) for r in rows)-min(datetime.fromisoformat(r['start_at']) for r in rows)).total_seconds()/60) if rows else 0
        return {'scheduled':len(rows),'total_tardiness_minutes':total,'weighted_tardiness_minutes':weighted,'completion_span_minutes':span}
    baseline_metrics=metrics(baseline['rows']); optimized_metrics=metrics(result['rows'])
    scenario={'id':p.uid('scenario'),'version':1,'status':'preview','created_at':p.stamp(),'factory_type':config['factory_type'],
              'name':config['name'],'start_date':config['start_date'],'config':config,'fingerprint':scheduling.fingerprint(ctx),'impact':impact,
              'engine':engine,'validation':validation,'comparison':{'baseline':baseline['summary'],'optimized':result['summary'],
                 'changed_tasks':len(impact),'baseline_metrics':baseline_metrics,'optimized_metrics':optimized_metrics,
                 'not_worse_on_coverage_and_tardiness': optimized_metrics['scheduled']>=baseline_metrics['scheduled'] and optimized_metrics['weighted_tardiness_minutes']<=baseline_metrics['weighted_tardiness_minutes'],
                 'basis':'相同人员、工位、前序、料期与冻结计划；不改变实际状态'},**result}
    scenario['status'] = 'advice'
    return scenario


def persist_schedule(store, con, scenario):
    if scenario['fingerprint'] != scheduling.fingerprint(scheduling.context(store, con)):
        p.fail('求解期间生产数据或资源已变化，请重新模拟',409,code='scenario_stale')
    scenario = dict(scenario, status='preview')
    store.put(con,'scheduling_scenarios',scenario)
    return {'scenario':scenario}


def schedule_preview(store, con, data):
    return persist_schedule(store, con, solve_prepared(prepare_schedule(store, con, data)))


def schedule_advice(store, con, data):
    """Read-only context snapshot + genuine solver; no scenario/event writes."""
    return solve_prepared(prepare_schedule(store, con, data))


schedule_compare = schedule_advice


def _scaled(value, label, zero=False):
    if isinstance(value,bool): p.fail(label+'无效')
    try:
        n=Decimal(str(value))
    except (InvalidOperation,ValueError): p.fail(label+'须为毫米数值')
    if not n.is_finite() or n < (0 if zero else Decimal('0.01')) or n>100000 or n*100 != (n*100).to_integral_value():
        p.fail(label+'须在有效范围内并最多保留两位小数')
    return int(n*100)


def _quantity(value,label,maximum):
    if type(value) is not int or not 1<=value<=maximum: p.fail(label+'须为 1–'+str(maximum)+' 的整数')
    return value


def packing_request(data):
    if not isinstance(data,dict): p.fail('排料参数须为对象')
    if data.get('dimensions_confirmed') is not True: p.fail('请先复核本单下料尺寸、单位、材质和数量，再确认试算')
    raw=data.get('items'); stock=data.get('stock')
    if not isinstance(raw,list) or not 1<=len(raw)<=300 or not isinstance(stock,dict): p.fail('须填写 1–300 种零件及原板规格')
    material=p.text(data.get('material') or stock.get('material'),'材质',True,120)
    thickness=_scaled(data.get('thickness_mm',stock.get('thickness_mm')),'板厚')
    grain=data.get('grain',stock.get('grain','none'))
    if stock.get('material',material)!=material or _scaled(stock.get('thickness_mm',thickness/100),'原板板厚')!=thickness or stock.get('grain',grain)!=grain:
        p.fail('原板材质、厚度及纹理必须与本次零件组一致')
    if grain not in ('none','width','height'): p.fail('纹理须为 none、width 或 height')
    width=_scaled(stock.get('width_mm'),'原板宽'); height=_scaled(stock.get('height_mm'),'原板高')
    trim=_scaled(data.get('trim_mm',0),'四边裁边',True); kerf=_scaled(data.get('kerf_mm',0),'锯缝',True)
    if min(width,height)<=2*trim: p.fail('裁边后原板无可用面积')
    count=_quantity(stock.get('quantity',100),'可用原板数',500)
    cost=stock.get('cost_per_sheet')
    if cost is not None:
        if isinstance(cost,bool): p.fail('原板单价无效')
        try: cost=Decimal(str(cost))
        except InvalidOperation: p.fail('原板单价无效')
        if not cost.is_finite() or cost<0 or cost>10000000 or cost*100!=(cost*100).to_integral_value(): p.fail('原板单价须为有效金额，最多两位小数')
    items=[]; seen=set()
    for r in raw:
        if not isinstance(r,dict): p.fail('零件须为对象')
        key=p.text(r.get('id'),'零件编号',True,128)
        if key in seen: p.fail('零件编号不能重复')
        seen.add(key)
        if r.get('material',material)!=material or _scaled(r.get('thickness_mm',thickness/100),'零件板厚')!=thickness or r.get('grain',grain)!=grain:
            p.fail('本次只能排同材质、同厚度、同纹理约束的零件，请分组试算')
        rotate=r.get('allow_rotate',grain=='none')
        if type(rotate) is not bool or (grain!='none' and rotate): p.fail('有纹理的板材不能允许 90° 旋转')
        items.append({'id':key,'label':p.text(r.get('label') or key,'零件名称',True,200),
                      'width':_scaled(r.get('width_mm'),'零件宽'),'height':_scaled(r.get('height_mm'),'零件高'),
                      'quantity':_quantity(r.get('quantity'),'零件数量',1000),'allow_rotate':rotate})
    if sum(i['quantity'] for i in items)>5000: p.fail('每次最多排 5000 件，请分批试算')
    baseline=data.get('baseline_sheet_count')
    if baseline is not None: baseline=_quantity(baseline,'原方案板数',100000)
    return {'items':items,'width':width,'height':height,'trim':trim,'kerf':kerf,'stock_quantity':count,
            'cost_per_sheet':cost,'material':material,'thickness_mm':thickness/100,'grain':grain,
            'limit':_limit(data.get('time_limit_seconds'),5),'baseline_sheet_count':baseline}


def validate_packing(config, layouts):
    expected={i['id']:i for i in config['items']}; counts=defaultdict(int); errors=[]
    if len(layouts)>config['stock_quantity']: errors.append('使用原板超过库存数量')
    for layout in layouts:
        pieces=layout['pieces']
        for item in pieces:
            ref=expected.get(item['item_id']); a,b,w,h=(round(item[k]*100) for k in ('x_mm','y_mm','width_mm','height_mm'))
            if not ref: errors.append('未知零件'); continue
            counts[ref['id']]+=1
            valid_size=(w==ref['width'] and h==ref['height']) or (ref['allow_rotate'] and w==ref['height'] and h==ref['width'])
            if not valid_size: errors.append(ref['id']+' 尺寸或纹理方向不一致')
            trim=config['trim']
            if not(trim<=a and trim<=b and a+w<=config['width']-trim and b+h<=config['height']-trim): errors.append(ref['id']+' 超出裁边后的原板')
        for i,a in enumerate(pieces):
            for b in pieces[i+1:]:
                ax,ay,aw,ah=(round(a[k]*100) for k in ('x_mm','y_mm','width_mm','height_mm'))
                bx,by,bw,bh=(round(b[k]*100) for k in ('x_mm','y_mm','width_mm','height_mm'))
                k=config['kerf']
                if not(ax+aw+k<=bx or bx+bw+k<=ax or ay+ah+k<=by or by+bh+k<=ay): errors.append('零件重叠或未留锯缝')
        nodes=layout.get('cut_nodes',[]); mapping={n['node_id']:n for n in nodes}; children=defaultdict(list)
        if len(mapping)!=len(nodes): errors.append('切割树节点重复')
        roots=[]
        for node in nodes:
            parent=node['parent_id']
            if parent is None: roots.append(node); continue
            if parent not in mapping: errors.append('切割树缺失父节点'); continue
            children[parent].append(node)
            pnode=mapping[parent]
            if not(pnode['x']<=node['x'] and pnode['y']<=node['y'] and node['x']+node['width']<=pnode['x']+pnode['width'] and node['y']+node['height']<=pnode['y']+pnode['height']): errors.append('切割子板越界')
        if len(roots)!=1: errors.append('切割树必须有一个原板根节点')
        elif (roots[0]['x'],roots[0]['y'],roots[0]['width'],roots[0]['height']) != (0,0,config['width']-2*config['trim'],config['height']-2*config['trim']):
            errors.append('切割树原板尺寸不一致')
        for node in nodes:
            visited=set(); current=node
            while current is not None:
                key=current['node_id']
                if key in visited: errors.append('切割树包含循环'); break
                visited.add(key); current=mapping.get(current['parent_id'])
            if node['parent_id'] is not None and node['type']>=0 and children.get(node['node_id']): errors.append('零件节点不能继续切分')
        for parent, group in children.items():
            pn=mapping[parent]
            vertical=all(n['y']==pn['y'] and n['height']==pn['height'] for n in group)
            horizontal=all(n['x']==pn['x'] and n['width']==pn['width'] for n in group)
            if not(vertical or horizontal): errors.append('切割树不是贯穿子板的直切'); continue
            axis,size=('x','width') if vertical else ('y','height')
            ordered=sorted(group,key=lambda n:n[axis])
            if any(ordered[i][axis] < ordered[i-1][axis]+ordered[i-1][size]+config['kerf'] for i in range(1,len(ordered))): errors.append('切割树子板重叠或锯缝不足')
    for key,item in expected.items():
        if counts[key]!=item['quantity']: errors.append(key+' 排入数量与审核数量不一致')
    return {'valid':not errors,'errors':list(dict.fromkeys(errors)),'checked_pieces':sum(counts.values()),
            'checks':['零件数量','尺寸与旋转','裁边边界','零件重叠与锯缝','原板数量','齐头切父子树']}


def packing_preview(data):
    config=packing_request(data)
    binary=_packing_binary()
    if not binary.is_file(): p.fail('PackingSolver 尚未构建，请运行优化引擎安装脚本',503)
    started=clock.monotonic()
    with tempfile.TemporaryDirectory(prefix='kanpace-packing-') as folder:
        base=Path(folder)
        with (base/'items.csv').open('w',newline='') as f:
            writer=csv.writer(f); writer.writerow(['WIDTH','HEIGHT','COPIES','ORIENTED'])
            for item in config['items']: writer.writerow([item['width'],item['height'],item['quantity'],0 if item['allow_rotate'] else 1])
        with (base/'bins.csv').open('w',newline='') as f:
            writer=csv.writer(f); writer.writerow(['WIDTH','HEIGHT','COPIES']); writer.writerow([config['width']-2*config['trim'],config['height']-2*config['trim'],config['stock_quantity']])
        command=[str(binary),'--items',str(base/'items.csv'),'--bins',str(base/'bins.csv'),'--objective','bin-packing',
                 '--number-of-stages','3','--cut-type','non-exact','--cut-thickness',str(config['kerf']),
                 '--linear-programming-solver','highs','--time-limit',str(config['limit']),'--verbosity-level','0',
                 '--certificate',str(base/'solution.csv'),'--output',str(base/'result.json'),'--only-write-at-the-end']
        try:
            proc=subprocess.run(command,capture_output=True,text=True,timeout=config['limit']+20,cwd=str(base))
        except (OSError,subprocess.SubprocessError) as error: p.fail('PackingSolver 未完成：'+str(error),503)
        if proc.returncode or not (base/'solution.csv').is_file():
            p.fail('PackingSolver 未产生切割方案：'+(proc.stderr.strip() or proc.stdout.strip())[-1200:],422)
        certificate=(base/'solution.csv').read_text()
        report=json.loads((base/'result.json').read_text()) if (base/'result.json').is_file() else {}
        raw=list(csv.DictReader(certificate.splitlines()))
    groups=defaultdict(list)
    for row in raw: groups[int(row['PLATE_ID'])].append(row)
    layouts=[]
    for plate_id,group in sorted(groups.items()):
        copies=int(group[0]['COPIES'])
        if not 1<=copies<=config['stock_quantity']: p.fail('求解输出原板副本数无效',422)
        children={int(r['PARENT']) for r in group if r['PARENT']}
        for copy in range(copies):
            layout={'id':f'plate_{plate_id}_{copy+1}','width_mm':config['width']/100,'height_mm':config['height']/100,
                    'pieces':[],'leftovers':[],'cut_nodes':[]}
            for r in group:
                node={'node_id':int(r['NODE_ID']),'parent_id':int(r['PARENT']) if r['PARENT'] else None,
                      'x':int(r['X']),'y':int(r['Y']),'width':int(r['WIDTH']),'height':int(r['HEIGHT']),'type':int(r['TYPE']),'depth':int(r['CUT'])}
                layout['cut_nodes'].append(node)
                rect={'x_mm':(node['x']+config['trim'])/100,'y_mm':(node['y']+config['trim'])/100,
                      'width_mm':node['width']/100,'height_mm':node['height']/100}
                if node['parent_id'] is not None and node['type']>=0:
                    if node['type']>=len(config['items']): p.fail('求解输出包含未知零件',422)
                    item=config['items'][node['type']]
                    layout['pieces'].append({'item_id':item['id'],'label':item['label'],
                        'rotated':node['width']!=item['width'] or node['height']!=item['height'],**rect})
                elif node['node_id'] not in children and node['width']>0 and node['height']>0:
                    layout['leftovers'].append({'kind':'residual' if node['type']==-3 else 'offcut',**rect})
            layouts.append(layout)
    validation=validate_packing(config,layouts)
    if not validation['valid']: p.fail('求解输出未通过独立校验：'+'；'.join(validation['errors']),422,validation=validation)
    total=len(layouts); gross=total*config['width']*config['height']/10000
    used=sum(i['width']*i['height']*i['quantity'] for i in config['items'])/10000
    leftover=sum(r['width_mm']*r['height_mm'] for l in layouts for r in l['leftovers'])
    cost=config['cost_per_sheet']; baseline=config['baseline_sheet_count']; manifest_path=ROOT/'licenses/optimization/manifest.json'
    manifest=json.loads(manifest_path.read_text()) if manifest_path.is_file() else {}
    return {'engine':{'requested':'PackingSolver rectangle-guillotine','used':'PackingSolver rectangle-guillotine',
                     'status':'FEASIBLE_VALIDATED','version':manifest.get('packingsolver',{}).get('commit'),
                     'wall_time_seconds':round(clock.monotonic()-started,4),'optimality_proven':False,'fallback_reason':None},
            'input_summary':{'material':config['material'],'thickness_mm':config['thickness_mm'],'grain':config['grain'],
                             'dimensions_confirmed':True,'item_types':len(config['items']),'quantity':sum(i['quantity'] for i in config['items']),
                             'kerf_mm':config['kerf']/100,'trim_mm':config['trim']/100,'coordinate_origin':'原板左下角，毫米','certificate_units_per_mm':100},
            'layouts':layouts,'summary':{'sheet_count':total,'stock_quantity':config['stock_quantity'],'placed_quantity':validation['checked_pieces'],
                 'material_cost':float(cost*total) if cost is not None else None,'cost_per_sheet':float(cost) if cost is not None else None,
                 'gross_area_mm2':gross,'parts_area_mm2':used,'utilization_percent':round(used/gross*100,2) if gross else 0,
                 'offcut_area_mm2':round(leftover,2),'non_part_area_mm2':round(gross-used,2),
                 'note':'余料为切割树空白子板；可复用价值需人工验收。成本仅原板金额，不含人工、锯缝工费与余料估值。'},
            'validation':validation,'baseline_comparison':{'baseline_sheet_count':baseline,'optimized_sheet_count':total,
                'sheets_saved':baseline-total if baseline is not None else None,
                'material_cost_saved':float((baseline-total)*cost) if baseline is not None and cost is not None else None,
                'basis':'用户提供且同规格同约束的原方案板数；未提供时不虚构节省'},
            'certificate_csv':certificate,'solver_report':report}
