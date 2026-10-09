"""Optional local, whole-instance roles. Disabled until first admin setup.

This controls API writes, worker task ownership and account/session exposure.
It is not tenant/factory isolation, SSO, TLS, or fine-grained read authorization.
"""
import hashlib
import hmac
import json
import re
import secrets
import threading
import time
from http.cookies import SimpleCookie
from urllib.parse import urlsplit, parse_qs, unquote
from uuid import uuid4
from kanpace.core.errors import APIError

COOKIE = 'kanpace_session'
SESSION_SECONDS = 8 * 3600
FINANCIAL_ROLES = ('admin', 'supervisor', 'owner')
PASSWORD_ITERATIONS = 600000
_context = threading.local()
ROLES = {
    'admin': {'label': '管理员', 'permissions': ['*']},
    'supervisor': {'label': '主管', 'permissions': ['projects', 'engineering', 'planning', 'tasks', 'resources', 'materials', 'quality', 'costs', 'deliveries', 'device', 'exchange']},
    'technical': {'label': '技术', 'permissions': ['projects', 'engineering', 'planning', 'tasks', 'exchange']},
    'warehouse': {'label': '仓管', 'permissions': ['materials', 'deliveries', 'exchange']},
    'quality': {'label': '质检', 'permissions': ['quality', 'own_tasks']},
    'worker': {'label': '工人', 'permissions': ['own_tasks']},
    'owner': {'label': '老板查看', 'permissions': []},
}


class AccessError(Exception):
    def __init__(self, status, message, details=None):
        self.status, self.message, self.details = status, message, details
        super().__init__(message)


def fail(status, message):
    raise AccessError(status, message)


def get_actor():
    return getattr(_context, 'actor', None)


def clear_actor():
    _context.actor = None


def _public_user(user):
    return {key: user.get(key) for key in ('id', 'username', 'name', 'role', 'person_id', 'active', 'version')}


def _config(store, con):
    return next(iter(store.all(con, 'access_config')), {'id': 'local_access', 'enabled': False})


def authentication_enabled(store):
    with store.connect() as con:return bool(_config(store,con).get('enabled'))


def require_private_asset_auth(handler):
    """Private controller studies also require login once access is enabled."""
    store=handler.server.store
    with store.connect() as con:
        if _config(store,con).get('enabled') and not _session_user(store,con,handler):
            fail(401,'请先登录管理工作台再查看这份资料')


def _users(store, con):
    return store.all(con, 'access_users')


def _person_is_active(store, con, user):
    person_id = user.get('person_id')
    if not person_id:
        return True
    try:
        person = store.get(con, 'people', person_id)
    except APIError:
        return False
    return not person.get('demo') and person.get('employment_status', 'active') == 'active'


def validate_person_departure(store, con, person_id):
    """Require a replacement administrator before departing staff lose access."""
    linked = [u for u in _users(store, con) if u.get('person_id') == person_id and u.get('active')]
    if any(u['role'] == 'admin' for u in linked) and not any(
            u['role'] == 'admin' and u.get('active') and u.get('person_id') != person_id
            and _person_is_active(store, con, u) for u in _users(store, con)):
        fail(409, '此人员关联最后一个管理员账号，请先交接管理员权限')


def revoke_person_accounts(store, con, person_id):
    """Stop Web access in the same transaction as a confirmed departure."""
    validate_person_departure(store, con, person_id)
    revoked = []
    for user in _users(store, con):
        if user.get('person_id') != person_id or not user.get('active'):
            continue
        user.update(active=False, version=user.get('version', 0) + 1, updated_at=time.time())
        store.put(con, 'access_users', user)
        for session in store.all(con, 'access_sessions'):
            if session.get('user_id') == user['id'] and not session.get('revoked'):
                session['revoked'] = True
                store.put(con, 'access_sessions', session)
        _audit(store, con, 'access_user_departed', '离职人员 Web 账号已停用',
               user_id=user['id'], person_id=person_id)
        revoked.append(user['id'])
    return revoked


def _username(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_.@-]{3,64}', value):
        fail(400, '账号使用 3 至 64 位字母、数字、点、下划线、@ 或短横线')
    return value.lower()


def _password(value):
    if not isinstance(value, str) or not 10 <= len(value) <= 256 or '\0' in value:
        fail(400, '密码须为 10 至 256 个字符')
    try:
        value.encode('utf-8')
    except UnicodeEncodeError:
        fail(400, '密码字符无效')
    return value


def password_hash(password):
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac('sha256', _password(password).encode(), bytes.fromhex(salt), PASSWORD_ITERATIONS).hex()
    return f'pbkdf2_sha256${PASSWORD_ITERATIONS}${salt}${digest}'


def password_matches(password, encoded):
    if not isinstance(password, str) or len(password) > 256:
        return False
    try:
        algorithm, iterations, salt, expected = encoded.split('$')
        if algorithm != 'pbkdf2_sha256' or not 100000 <= int(iterations) <= 1000000:
            return False
        actual = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), int(iterations)).hex()
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError, UnicodeError):
        return False


def cookie_name(store):
    identifier=getattr(store,'instance_id',None)
    return COOKIE+'_'+identifier if identifier else COOKIE


def _token(handler):
    try:
        cookie = SimpleCookie()
        cookie.load(handler.headers.get('Cookie', ''))
        name=cookie_name(handler.server.store)
        return cookie[name].value if name in cookie else None
    except Exception:
        return None


def _session_user(store, con, handler):
    token = _token(handler)
    if not isinstance(token, str) or not re.fullmatch(r'[A-Za-z0-9_-]{40,100}', token):
        return None
    identifier = hashlib.sha256(token.encode()).hexdigest()
    session = next((r for r in store.all(con, 'access_sessions') if r['id'] == identifier), None)
    if not session or session.get('revoked') or session['expires_at'] <= time.time():
        return None
    user = next((u for u in _users(store, con) if u['id'] == session['user_id']), None)
    if not user or not user.get('active') or not _person_is_active(store, con, user):
        return None
    return user


def _actor(user=None):
    return {'id': user['id'], 'name': user['name'], 'role': user['role'], 'person_id': user.get('person_id'), 'access_enabled': True} if user else {
        'id': None, 'name': '本机操作者', 'role': 'local_operator', 'person_id': None, 'access_enabled': False}


def _cookie(token=None,store=None):
    name=cookie_name(store) if store else COOKIE
    return f'{name}={token or ""}; Path=/; HttpOnly; SameSite=Strict; Max-Age={SESSION_SECONDS if token else 0}' + ('; Secure' if getattr(store, 'web_origin', None) else '')


def _create_session(store, con, user):
    token = secrets.token_urlsafe(32)
    store.put(con, 'access_sessions', {'id': hashlib.sha256(token.encode()).hexdigest(), 'user_id': user['id'],
              'created_at': time.time(), 'expires_at': time.time() + SESSION_SECONDS, 'revoked': False})
    return token


def canonical_path(raw):
    # Match the API dispatcher: decode once, then collapse empty segments.
    return '/' + '/'.join(x for x in unquote(urlsplit(raw).path).split('/') if x)


def _permission(path):
    if path.startswith('/api/material-planning/'):
        return 'materials'
    if path == '/api/device-bindings' or path.startswith('/api/project-dispatches/') or path.endswith('/dispatch'):
        return 'device'
    if path.startswith('/api/daily-workflow/locations') or (path.startswith('/api/daily-workflow/labels/') and path.endswith('/location')):
        return 'materials'
    if path.startswith('/api/daily-workflow/labels/'):
        return 'planning' if path.endswith('/prepare') else 'tasks'
    if path.startswith('/api/daily-workflow/handovers/'):
        return 'device'
    if path.endswith('/packing'):
        return 'costs'
    if path.startswith('/api/access/'):
        return 'accounts'
    if path.startswith('/api/operations/'):
        return 'engineering' if '/templates' in path else 'resources'
    if path.startswith('/api/device/') or path.endswith('/send-device'):
        return 'device'
    if path.startswith('/api/exchange'):
        return 'exchange'
    if path.startswith('/api/production/'):
        part = path.split('/')[3]
        if part in ('materials', 'issues', 'checks'):
            return 'materials'
        if part in ('inspections', 'reworks'):
            return 'quality'
        if part in ('costs', 'financials', 'changes', 'milestones'):
            return 'costs'
        if part == 'deliveries':
            return 'deliveries'
    if path.endswith('/costs') or path == '/api/settings':
        return 'costs'
    if path == '/api/import' or path == '/api/parts':
        return 'engineering'
    if path.startswith('/api/calibration'):
        return 'engineering'
    if path.startswith(('/api/planning', '/api/schedule-reference', '/api/scheduling')):
        return 'planning'
    if path.startswith('/api/tasks/'):
        return 'tasks'
    if path == '/api/projects' or path.endswith('/fulfillment'):
        return 'projects'
    if path.startswith(('/api/projects/', '/api/parts/', '/api/documents/', '/api/order-drafts/')):
        return 'engineering'
    if path == '/api/people' or path.startswith('/api/people/'):
        return 'resources'
    return 'admin_only'


def authorize(handler, path=None, data=None):
    """Call after host/origin validation, before dispatch. Sets thread-local actor."""
    clear_actor()
    path = canonical_path(path if path is not None else handler.path)
    store = handler.server.store
    with store.connect() as con:
        config = _config(store, con)
        if not config.get('enabled'):
            _context.actor = _actor()
            return get_actor()
        user = _session_user(store, con, handler)
        if user:
            _context.actor = _actor(user)
        # Generic industry definitions contain no customer data and are browsable
        # before account setup. All factory configuration writes remain private.
        if handler.command in ('GET','HEAD') and (path == '/api/industry-templates' or re.fullmatch(r'/api/industry-templates/[a-z0-9_-]+/[a-z0-9_-]+',path)):
            return get_actor()
        # Assets load a local login screen; no production API is anonymous.
        if not path.startswith('/api/') or path in ('/api/access', '/api/access/login', '/api/access/setup', '/api/access/logout', '/api/health'):
            return get_actor()
        if not user:
            fail(401, '请先登录本机账号')
        if handler.command == 'POST' and path == '/api/agent/message':
            # The assistant only reads an explicitly filtered projection and
            # proposes typed actions; each confirmed write uses its original
            # endpoint and the normal role/ownership/concurrency checks.
            return get_actor()
        if handler.command in ('GET', 'HEAD'):
            if re.fullmatch(r'/api/projects/[^/]+/(?:workflow|recognition)(?:/[^/]+)?', path) and user['role'] in ('worker', 'quality'):
                fail(403, '整单流程与识别证据需要整单查看权限')
            # V1 read access is instance-wide; account administration stays private.
            if path.startswith('/api/access/') and user['role'] != 'admin':
                fail(403, '此操作需要管理员账号')
            query = parse_qs(urlsplit(handler.path).query)
            financial_route = (path.endswith(('/quote', '/costs', '/financials', '/packing')) or
                               (path.endswith('/export') and not path.startswith('/api/exchange') and query.get('format', ['json'])[0] == 'json'))
            if financial_route and user['role'] not in FINANCIAL_ROLES:
                fail(403, '当前角色没有财务数据查看权限')
            return get_actor()
        permissions = ROLES[user['role']]['permissions']
        if '*' not in permissions and 'costs' not in permissions and isinstance(data, dict):
            if path == '/api/parts' or path.startswith('/api/parts/'):
                pricing_keys = {'unit_price', 'pricing_unit'}
                edits = data.get('edits') if isinstance(data.get('edits'), dict) else {}
                if pricing_keys.intersection(data) or pricing_keys.intersection(edits):
                    fail(403, '当前角色不能修改构件单价或计价单位')
        if '*' in permissions:
            return get_actor()
        if path.startswith('/api/exchange'):
            if 'exchange' not in permissions:
                fail(403, '当前角色没有文件互联操作权限')
            parts = path.split('/')
            if path == '/api/exchange/preview':
                kind = (data or {}).get('entity_type')
            elif len(parts) == 5 and parts[4] == 'apply':
                preview = next((r for r in store.all(con, 'exchange_previews') if r['id'] == parts[3]), None)
                if not preview:
                    fail(404, '互联预览不存在')
                kind = preview.get('entity_type')
            else:
                fail(403, '文件互联操作未授权')
            required = {'projects': 'projects', 'people': 'resources', 'materials': 'materials', 'progress': 'tasks'}.get(kind) if isinstance(kind, str) else None
            if not required or required not in permissions:
                fail(403, '当前角色没有此类数据的导入权限')
            return get_actor()
        if _permission(path) in permissions:
            return get_actor()
        parts = path.split('/')
        if ('own_tasks' in permissions and len(parts) == 6 and parts[2:4] == ['daily-workflow', 'labels']
                and parts[5] == 'confirm'):
            label = next((item for item in store.all(con, 'daily_labels') if item['id'] == parts[4]), None)
            task = next((item for item in store.all(con, 'tasks') if label and item['id'] == (data or {}).get('task_id')), None)
            if task and user.get('person_id') and task.get('assignee') == user['person_id']:
                return get_actor()
            fail(403, '只能确认自己任务的标签')
        if ('own_tasks' in permissions and len(parts) == 5 and parts[2] == 'tasks'
                and parts[4] in ('status', 'progress', 'pause', 'resume')):
            task = next((t for t in store.all(con, 'tasks') if t['id'] == parts[3]), None)
            if task and user.get('person_id') and task.get('assignee') == user['person_id']:
                return get_actor()
            fail(403, '只能报工分派给自己的任务')
        fail(403, '当前角色没有这项操作权限')


def status(store, handler):
    with store.connect() as con:
        config = _config(store, con)
        user = _session_user(store, con, handler) if config.get('enabled') else None
        result = {'enabled': bool(config.get('enabled')), 'setup_required': not bool(_users(store, con)),
                  'user': _public_user(user) if user else None,
                  'roles': [{'id': key, **value} for key, value in ROLES.items()],
                  'scope': 'local_instance_roles', 'factory_data_isolation': False,
                  'financial_access': bool(user and user['role'] in FINANCIAL_ROLES) if config.get('enabled') else True,
                  'notice': '同一实例共享项目与原文件；角色限制操作、本人报工及结构化财务数据，不提供工厂隔离' if config.get('enabled') else '当前为本机单操作者模式，尚未启用账号权限'}
        if getattr(store,'instance_id',None):
            result.update(scope='isolated_local_factory',factory_data_isolation=True,instance_id=store.instance_id,notice='当前为独立工厂空间；账号、原文件、任务、设备凭证与其他实例分开保存。')
        if user and user['role'] == 'admin':
            result['users'] = [_public_user(u) for u in _users(store, con)]
            result['people'] = [{key:p.get(key) for key in ('id', 'name', 'factory_id')} for p in store.all(con, 'people') if not p.get('demo')]
        return result


def _audit(store, con, action, title, **details):
    store.event(con, None, action, title, **details)


def setup(store, handler, data):
    with store.connect() as con:
        con.execute('BEGIN IMMEDIATE')
        if _config(store, con).get('enabled') or _users(store, con):
            fail(409, '管理员已经配置，请直接登录')
        user = _new_user(store, con, dict(data, role='admin'))
        store.put(con, 'access_config', {'id':'local_access','enabled':True,'created_at':time.time()})
        _context.actor = _actor(user)
        _audit(store, con, 'access_enabled', '启用本机账号权限', user_id=user['id'])
        token = _create_session(store, con, user)
    return {'user':_public_user(user),'enabled':True}, _cookie(token,store)


def _new_user(store, con, data):
    username = _username(data.get('username'))
    if any(u['username'] == username for u in _users(store, con)):
        fail(409, '此账号已存在')
    if len(_users(store, con)) >= 100:
        fail(409, '本机账号达到 100 个上限')
    user = {'id':'user_'+uuid4().hex,'username':username,'created_at':time.time(),'version':0}
    return _save_user(store, con, user, data)


def _save_user(store, con, user, data):
    role = data.get('role', user.get('role'))
    if not isinstance(role, str) or role not in ROLES:
        fail(400, '请选择有效角色')
    name = data.get('name', user.get('name'))
    if not isinstance(name, str) or not name.strip() or len(name) > 100:
        fail(400, '请填写姓名，最长 100 个字符')
    active = data.get('active', user.get('active', True))
    if type(active) is not bool:
        fail(400, '账号状态须为布尔值')
    person_id = data.get('person_id', user.get('person_id')) or None
    if person_id:
        person = next((p for p in store.all(con, 'people') if p['id'] == person_id and not p.get('demo')), None)
        if not person:
            fail(400, '请选择本机真实人员档案')
        if active and person.get('employment_status', 'active') != 'active':
            fail(409, '离职人员不能启用 Web 账号；重新入职后由管理员手动启用')
    if role in ('worker', 'quality') and not person_id:
        fail(400, '工人和质检账号须关联人员档案')
    if person_id and any(u['id'] != user['id'] and u.get('person_id') == person_id and u.get('active') and active for u in _users(store, con)):
        fail(409, '这个人员档案已经关联其他启用账号')
    if user.get('role') == 'admin' and user.get('active') and (role != 'admin' or not active):
        others = [u for u in _users(store, con) if u['id'] != user['id'] and u.get('active') and u['role'] == 'admin']
        if not others:
            fail(409, '须保留至少一个启用的管理员账号')
    changed_password = data.get('password') not in (None, '')
    if not user.get('password_hash') and not changed_password:
        fail(400, '请设置账号密码')
    if changed_password:
        user['password_hash'] = password_hash(data['password'])
    user.update(name=name.strip(), role=role, person_id=person_id, active=active, version=user['version']+1, updated_at=time.time())
    store.put(con, 'access_users', user)
    if changed_password or not active:
        for session in store.all(con, 'access_sessions'):
            if session['user_id'] == user['id'] and not session.get('revoked'):
                session['revoked'] = True
                store.put(con, 'access_sessions', session)
    return user


def save_user(store, handler, data):
    with store.connect() as con:
        con.execute('BEGIN IMMEDIATE')
        actor = _session_user(store, con, handler)
        if not actor or actor['role'] != 'admin':
            fail(403, '此操作需要管理员账号')
        _context.actor = _actor(actor)
        if data.get('id'):
            user = next((u for u in _users(store, con) if u['id'] == data['id']), None)
            if not user:
                fail(404, '账号不存在')
            if type(data.get('expected_version')) is not int or data['expected_version'] != user['version']:
                fail(409, '账号已更新，请刷新后重试')
            if 'username' in data and _username(data['username']) != user['username']:
                fail(400, '账号标识不能修改')
            user = _save_user(store, con, user, data)
        else:
            user = _new_user(store, con, data)
        _audit(store, con, 'access_user_saved', '维护本机账号：'+user['name'], user_id=user['id'], role=user['role'], active=user['active'])
    return {'user':_public_user(user)}


def login(store, handler, data):
    # Failure counters commit too, then the error is returned outside the txn.
    clear_actor()
    failure = False
    username = _username(data.get('username'))
    with store.connect() as con:
        con.execute('BEGIN IMMEDIATE')
        if not _config(store, con).get('enabled'):
            fail(409, '请先创建本机管理员')
        key = hashlib.sha256(username.encode()).hexdigest()
        attempt = next((r for r in store.all(con, 'access_login_limits') if r['id'] == key), {'id':key,'failures':0,'window_start':time.time()})
        if time.time() - attempt['window_start'] > 900:
            attempt.update(failures=0,window_start=time.time())
        if attempt['failures'] >= 6:
            fail(429, '登录尝试过多，请 15 分钟后重试')
        user = next((u for u in _users(store, con) if u['username'] == username), None)
        encoded = user['password_hash'] if user else f'pbkdf2_sha256${PASSWORD_ITERATIONS}$'+('00'*16)+'$'+('00'*32)
        valid = password_matches(data.get('password'), encoded)
        if not valid or not user or not user.get('active') or not _person_is_active(store, con, user):
            attempt['failures'] += 1
            store.put(con, 'access_login_limits', attempt)
            _audit(store, con, 'access_login_failed', '本机账号登录失败', username=username)
            failure = True
        else:
            attempt.update(failures=0, window_start=time.time())
            store.put(con, 'access_login_limits', attempt)
            _context.actor = _actor(user)
            token = _create_session(store, con, user)
            _audit(store, con, 'access_login', '本机账号登录：'+user['name'], user_id=user['id'])
    if failure:
        fail(401, '账号或密码不正确')
    return {'user':_public_user(user)}, _cookie(token,store)


def logout(store, handler):
    token = _token(handler)
    with store.connect() as con:
        con.execute('BEGIN IMMEDIATE')
        user = _session_user(store, con, handler)
        if token:
            identifier = hashlib.sha256(token.encode()).hexdigest()
            session = next((s for s in store.all(con, 'access_sessions') if s['id'] == identifier), None)
            if session:
                session['revoked'] = True
                store.put(con, 'access_sessions', session)
        if user:
            _context.actor = _actor(user)
            _audit(store, con, 'access_logout', '本机账号退出：'+user['name'], user_id=user['id'])
    clear_actor()
    return {'logged_out':True}, _cookie(store=store)


def handle(handler, data=None):
    """After host/origin validation, dispatch access endpoints and write response.

    Return True if handled, False for other routes. Exceptions are AccessError.
    """
    path = canonical_path(handler.path)
    store = handler.server.store
    headers = {}
    if handler.command in ('GET', 'HEAD') and path == '/api/access':
        result = status(store, handler)
    elif handler.command == 'POST' and path in ('/api/access/setup', '/api/access/login', '/api/access/logout', '/api/access/users'):
        if path.endswith('/setup'):
            result, cookie = setup(store, handler, data or {})
            headers['Set-Cookie'] = cookie
        elif path.endswith('/login'):
            result, cookie = login(store, handler, data or {})
            headers['Set-Cookie'] = cookie
        elif path.endswith('/logout'):
            result, cookie = logout(store, handler)
            headers['Set-Cookie'] = cookie
        else:
            result = save_user(store, handler, data or {})
    else:
        return False
    handler.send_bytes(200, json.dumps(result, ensure_ascii=False).encode(), 'application/json; charset=utf-8', headers)
    return True


def filter_imported_part_prices(part):
    """Call on each parsed BOM part before Store.put; preserve original file.

    Non-financial importers can bring in geometry and quantities, but assigning
    material prices remains an explicit cost-authorized action.
    """
    actor = get_actor()
    if actor and actor.get('access_enabled') and actor.get('role') not in FINANCIAL_ROLES:
        return {key: value for key, value in part.items() if key not in ('unit_price', 'pricing_unit')}
    return dict(part)


def filter_response(handler, payload):
    """Apply from Handler.json_response after authorize; leave stored data intact.

    Original documents remain shared and may contain commercial information.
    This scrub targets structured finance, price settings, and financial events.
    """
    actor = get_actor()
    if not actor or not actor.get('access_enabled'):
        return payload
    forbidden = {'password_hash', 'payload_hash', 'access_sessions', 'access_login_limits', 'access_users', 'access_config'}
    financial = actor.get('role') in FINANCIAL_ROLES
    if not financial:
        forbidden |= {'quote_settings', 'material_rates', 'hourly_rates', 'labor_rates', 'rates', 'outsourcing_cost',
            'margin_rate', 'overhead_rate', 'markup', 'material_cost', 'labor_cost', 'total_cost', 'suggested_price',
            'unit_price', 'pricing_unit', 'cost_price', 'sale_price', 'contract_amount', 'budget_cost', 'remaining_cost',
            'received_amount', 'approved_change_amount', 'forecast_profit', 'forecast_cost', 'contract_total',
            'unreceived_amount', 'actual_cost', 'previous_outsourcing_cost', 'amount', 'estimated_cost', 'waste_cost', 'overhead_cost', 'known_subtotal', 'quote'}
    def clean(value):
        if isinstance(value, list):
            rows = []
            for row in value:
                if isinstance(row, dict):
                    action = str(row.get('action', ''))
                    if action.startswith('access_') and actor.get('role') != 'admin':
                        continue
                    if not financial and (any(word in action for word in ('cost', 'financial', 'price', 'quote', 'settings_')) or row.get('type') == 'cost'):
                        continue
                rows.append(clean(row))
            return rows
        if isinstance(value, dict):
            return {key: clean(child) for key, child in value.items() if key not in forbidden}
        return value
    result = clean(payload)
    if isinstance(result, dict) and not financial:
        path = canonical_path(handler.path)
        if path == '/api/production':
            for key in ('costs', 'financials', 'economics', 'milestones'):
                result[key] = []
            result['financial_access'] = False
        if path == '/api/state':
            result['settings'] = {}
            result['financial_access'] = False
    return result
