"""Isolated OR-Tools worker. Reads one JSON request; never opens a KANPACE store."""

# Third-party licensing: OR-Tools 9.15.6755 is Apache-2.0; preserve its
# license/NOTICE and independent dependency notices when redistributing.
# See THIRD_PARTY_NOTICES.md and licenses/optimization/manifest.json.
import json
import sys
import time


def schedule(data):
    import ortools
    from ortools.sat.python import cp_model
    started = time.monotonic()
    model = cp_model.CpModel()
    jobs = data['jobs']
    horizon = data['horizon_minutes']
    max_wait = max((j['wait_minutes'] for j in jobs), default=0)
    bound = horizon + max_wait + 1
    resources, variables = {}, {}
    penalties, benefits = [], []
    for job in jobs:
        key = job['id']
        selected = model.new_bool_var('selected_' + key)
        segs, starts, ends, amounts = [], [], [], []
        for i, (left, right) in enumerate(job['windows']):
            if right <= left:
                continue
            present = model.new_bool_var(f'{key}_{i}_present')
            length = model.new_int_var(0, min(job['duration'], right-left), f'{key}_{i}_minutes')
            start = model.new_int_var(left, right, f'{key}_{i}_start')
            end = model.new_int_var(left, right, f'{key}_{i}_end')
            model.add(length >= 1).only_enforce_if(present)
            model.add(length == 0).only_enforce_if(present.Not())
            model.add(present <= selected)
            interval = model.new_optional_interval_var(start, length, end, present, f'{key}_{i}_interval')
            for resource in job['resources']:
                resources.setdefault(resource, []).append(interval)
            active_start = model.new_int_var(0, horizon, f'{key}_{i}_active_start')
            active_end = model.new_int_var(0, horizon, f'{key}_{i}_active_end')
            model.add(active_start == start).only_enforce_if(present)
            model.add(active_start == horizon).only_enforce_if(present.Not())
            model.add(active_end == end).only_enforce_if(present)
            model.add(active_end == 0).only_enforce_if(present.Not())
            starts.append(active_start); ends.append(active_end); amounts.append(length)
            segs.append((present, start, end))
        model.add(sum(amounts) == job['duration'] * selected)
        if job.get('non_interruptible'):
            model.add(sum(x[0] for x in segs) == selected)
        start = model.new_int_var(0, horizon, key + '_start')
        end = model.new_int_var(0, horizon, key + '_end')
        if starts:
            model.add_min_equality(start, starts)
            model.add_max_equality(end, ends)
        else:
            model.add(selected == 0); model.add(start == horizon); model.add(end == 0)
        model.add(start >= job['release']).only_enforce_if(selected)
        weight = 1 + min(100, max(0, job.get('priority', 0))) + (100 if job.get('rush') else 0)
        late = model.new_int_var(0, bound, key + '_late')
        model.add(late >= end + job['wait_minutes'] - job['due']).only_enforce_if(selected)
        model.add(late == 0).only_enforce_if(selected.Not())
        penalties.append(late * weight * 10)
        penalties.append(end * weight)
        benefits.append(selected * (201 * max(1, len(jobs)) + 1 + weight))
        variables[key] = (selected, start, end, segs)
    for intervals in resources.values():
        model.add_no_overlap(intervals)
    for job in jobs:
        selected, start, _, _ = variables[job['id']]
        for predecessor in job['dependencies']:
            parent_selected, _, parent_end, _ = variables[predecessor]
            model.add(selected <= parent_selected)
            parent = next(j for j in jobs if j['id'] == predecessor)
            model.add(start >= parent_end + parent['wait_minutes']).only_enforce_if(selected)
    # Lexicographic dominance: a scheduled task outweighs all timing penalties.
    timing_scale = 10
    selection_scale = max(1, len(jobs)) * 201 * (bound * timing_scale + horizon) + 1
    model.minimize(sum(penalties) - sum(benefits) * selection_scale)
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = data.get('time_limit_seconds', 10)
    solver.parameters.num_search_workers = 4
    solver.parameters.random_seed = 0
    status = solver.solve(model)
    result = {'engine': 'Google OR-Tools CP-SAT', 'version': ortools.__version__,
              'status': solver.status_name(status), 'wall_time_seconds': round(time.monotonic()-started, 4),
              'rows': [], 'unplaced': []}
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        result['objective_value'] = solver.objective_value
        result['best_objective_bound'] = solver.best_objective_bound
        for job in jobs:
            selected, start, end, segs = variables[job['id']]
            if not solver.value(selected):
                result['unplaced'].append(job['id'])
                continue
            result['rows'].append({'task_id': job['id'], 'start': solver.value(start), 'end': solver.value(end),
                                  'segments': [[solver.value(a), solver.value(b)] for present, a, b in segs if solver.value(present)]})
    return result


if __name__ == '__main__':
    try:
        request = json.load(sys.stdin)
        if request.get('operation') == 'status':
            import ortools
            from ortools.sat.python import cp_model
            probe=cp_model.CpSolver(); probe_status=probe.solve(cp_model.CpModel())
            response = {'available': probe_status == cp_model.OPTIMAL, 'version': ortools.__version__, 'probe_status':probe.status_name(probe_status)}
        elif request.get('operation') == 'schedule':
            response = schedule(request)
        else:
            raise ValueError('Unsupported optimization operation')
        print(json.dumps(response, ensure_ascii=False, allow_nan=False))
    except Exception as error:
        print(json.dumps({'error': type(error).__name__, 'message': str(error)}, ensure_ascii=False))
        sys.exit(1)
