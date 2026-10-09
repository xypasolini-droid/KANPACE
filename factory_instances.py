"""Separate local customer instances; never repartition the existing database.

Isolation is application/process storage separation under one OS account. This
is not a sandbox against the host administrator or arbitrary code execution.
Only the controller can create/list children. Child processes bind loopback,
require their own account before startup, and never serve controller studies.
"""
from __future__ import annotations
try:
    import fcntl
except ImportError:  # Existing single-instance Web remains usable on Windows.
    fcntl=None
import json
import os
from pathlib import Path
import plistlib
import re
import secrets
import socket
import subprocess
import sys
import tempfile
import time
from urllib.request import Request, urlopen, build_opener, ProxyHandler
from uuid import uuid4
import access_control
import industry_templates

BASE = Path(__file__).resolve().parent
KINDS = {'cabinet', 'machinery', 'site'}
MAX_INSTANCES = 40

class InstanceError(Exception):
    def __init__(self,status,message,details=None):
        self.status,self.message,self.details=status,message,details
        super().__init__(message)


def _private_dir(path):
    path=Path(path)
    if path.is_symlink(): raise InstanceError(409,'工厂目录不可使用符号链接')
    path.mkdir(parents=True,exist_ok=True,mode=0o700)
    os.chmod(path,0o700)
    return path


def _write_json(path,value):
    path=Path(path)
    fd,temp=tempfile.mkstemp(prefix='.'+path.name+'-',dir=path.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as stream:
            os.fchmod(stream.fileno(),0o600)
            json.dump(value,stream,ensure_ascii=False,allow_nan=False)
            stream.flush();os.fsync(stream.fileno())
        os.replace(temp,path)
    finally:
        if os.path.exists(temp):os.unlink(temp)


def instance_info(store):
    with store.connect() as con:
        row=con.execute("SELECT value FROM config WHERE key='factory_instance'").fetchone()
    if not row:return None
    value=json.loads(row['value'])
    return value if isinstance(value,dict) and re.fullmatch(r'inst_[a-f0-9]{32}',str(value.get('id',''))) else None


def assert_ready(store):
    info=instance_info(store)
    with store.connect() as con:
        config=access_control._config(store,con)
        users=access_control._users(store,con)
    if not info or not config.get('enabled') or not any(user.get('role')=='admin' and user.get('active') for user in users):
        raise InstanceError(409,'独立工厂未完成认证初始化，拒绝启动服务')
    return info


def root_path(store):
    # The directory is fixed by the controller's Store, never a submitted path.
    return Path(store.data_dir)/'factory-instances'


def _read_registry(store):
    path=root_path(store)/'registry.json'
    if not path.exists():return []
    if path.is_symlink():raise InstanceError(409,'工厂登记文件不可使用符号链接')
    try:
        rows=json.loads(path.read_text(encoding='utf-8'))
    except (ValueError,OSError):raise InstanceError(500,'工厂登记文件读取失败')
    if not isinstance(rows,list):raise InstanceError(500,'工厂登记文件无效')
    return rows


def _public(record):
    return {key:record.get(key) for key in ('id','name','factory_type','factory_id','url','status','created_at','industry_id','variant_id','industry_name','variant_name')}


def _controller_admin(store):
    actor=access_control.get_actor()
    with store.connect() as con:
        enabled=bool(access_control._config(store,con).get('enabled'))
        admin=next((u for u in access_control._users(store,con) if actor and u['id']==actor.get('id') and u.get('role')=='admin' and u.get('active')),None)
    return enabled,bool(enabled and actor and actor.get('role')=='admin' and admin)


def _require_controller(store):
    if getattr(store,'instance_id',None) or instance_info(store):raise InstanceError(403,'独立工厂空间不能创建或查看其他客户空间')
    enabled,admin=_controller_admin(store)
    if not enabled:raise InstanceError(409,'请先为管理工作台设置管理员账号，再开通独立工厂')
    if not admin:raise InstanceError(403,'仅管理工作台已登录的管理员可以开通独立工厂')


def status(store):
    info=instance_info(store)
    if info:return {'isolated':True,'can_provision':False,'controller_auth_required':False,'instance':_public(info),'isolation':'separate_local_instance'}
    enabled,allowed=_controller_admin(store)
    return {'isolated':False,'can_provision':allowed,'controller_auth_required':not enabled,
            'instances':[_public(row) for row in _read_registry(store)] if allowed else [],'isolation':'legacy_shared_instance'}


def _payload(data):
    if not isinstance(data,dict):raise InstanceError(400,'开通内容必须为对象')
    if set(data)-{'name','factory_type','product','admin','request_id','industry_id','variant_id'}:raise InstanceError(400,'开通内容含不支持的字段')
    name=data.get('name');kind=data.get('factory_type');product=data.get('product','')
    selected=None
    if data.get('industry_id'):
        try:selected=industry_templates.resolve(data['industry_id'],data.get('variant_id'))
        except (ValueError,KeyError,TypeError):raise InstanceError(400,'请选择有效行业与生产类型') from None
        if kind is not None and kind!=selected['factory_type']:raise InstanceError(400,'工厂场景与所选行业流程不一致')
        kind=selected['factory_type']
    elif data.get('variant_id'):
        raise InstanceError(400,'请先选择行业，再选择生产类型')
    if not isinstance(name,str) or not 1<=len(name.strip())<=100:raise InstanceError(400,'请填写工厂名称，最多100字')
    if not isinstance(kind,str) or kind not in KINDS:raise InstanceError(400,'请选择有效工厂类型')
    if not isinstance(product,str) or len(product)>500:raise InstanceError(400,'产品说明最多500字')
    admin=data.get('admin')
    if not isinstance(admin,dict) or set(admin)-{'username','name','password'}:raise InstanceError(400,'请填写独立管理员账号')
    username=access_control._username(admin.get('username'))
    password=access_control._password(admin.get('password'))
    admin_name=admin.get('name') or name.strip()+'管理员'
    if not isinstance(admin_name,str) or not 1<=len(admin_name.strip())<=100:raise InstanceError(400,'管理员姓名最多100字')
    request_id=data.get('request_id') or str(uuid4())
    if not isinstance(request_id,str) or not re.fullmatch(r'[a-zA-Z0-9_-]{8,100}',request_id):raise InstanceError(400,'开通请求编号无效')
    return {'name':name.strip(),'factory_type':kind,'product':product.strip(),'request_id':request_id,
            **({'industry_id':selected['industry_id'],'variant_id':selected['variant_id']} if selected else {}),
            'admin':{'username':username,'name':admin_name.strip(),'password':password}}


def create_store(parent_store,data):
    """Create a new authenticated empty Store, without listening or launching.

    This is also the test seam: returned (store, record) is ready for a temporary
    Server(('127.0.0.1',0), store). It never returns a login token or password.
    """
    from kanpace.application.store import Store
    if getattr(parent_store,'instance_id',None) or instance_info(parent_store):raise InstanceError(403,'独立工厂不能开通其他客户空间')
    data=_payload(data)
    root=_private_dir(root_path(parent_store));identifier='inst_'+uuid4().hex
    folder=_private_dir(root/identifier)
    # Every file generated while provisioning inherits the restrictive process
    # umask in production. Tests additionally harden all initial files below.
    store=Store(folder,seed=False,empty=True)
    record={'id':identifier,'name':data['name'],'factory_type':data['factory_type'],'factory_id':'factory_'+uuid4().hex,
            'created_at':time.time(),'status':'configured','url':None,'request_id':data['request_id'],'admin_username':data['admin']['username']}
    if data.get('industry_id'):
        selected=industry_templates.resolve(data['industry_id'],data['variant_id'])
        record.update(industry_id=selected['industry_id'],variant_id=selected['variant_id'],
                      industry_name=selected['industry_name'],variant_name=selected.get('variant_name',selected['name']))
    try:
        with store.connect() as con:
            con.execute('BEGIN IMMEDIATE')
            user=access_control._new_user(store,con,{**data['admin'],'role':'admin'})
            store.put(con,'access_config',{'id':'local_access','enabled':True,'created_at':time.time()})
            store.put(con,'factories',{'id':record['factory_id'],'name':record['name'],'factory_type':record['factory_type'],
                      **{k:record[k] for k in ('industry_id','variant_id','industry_name','variant_name') if k in record},
                      'note':data['product'],'version':1,'demo':False,'created_at':record['created_at'],'updated_at':record['created_at']})
            info={key:record[key] for key in ('id','name','factory_type','factory_id','created_at','industry_id','variant_id','industry_name','variant_name') if key in record}
            con.execute('INSERT INTO config(key,value) VALUES(?,?)',('factory_instance',json.dumps(info,ensure_ascii=False)))
            # Independent private seed for future signed exports/connectors;
            # never returned by Store.state or customer/controller APIs.
            con.execute('INSERT INTO config(key,value) VALUES(?,?)',('instance_secret',secrets.token_hex(32)))
        store.instance_id=identifier
        for directory in ('uploads','drawing-previews','cache','logs','service'):_private_dir(folder/directory)
        for path in folder.iterdir():
            if path.is_file():os.chmod(path,0o600)
        assert_ready(store)
        return store,record
    except Exception:
        # Keep failed files private, but do not register or expose an address.
        for path in folder.iterdir():
            if path.is_file():os.chmod(path,0o600)
        raise


def _port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0));return sock.getsockname()[1]


def launch_definition(store,record,port):
    python=BASE/'.venv/bin/python'
    if not python.is_file():python=Path(sys.executable).resolve()
    label='com.kanpace.factory.'+record['id']
    return {'Label':label,'ProgramArguments':[str(python),'-u',str(BASE/'app.py'),'--port',str(port),
               '--data-dir',str(store.data_dir),'--isolated-instance','--no-demo'],
            'WorkingDirectory':str(BASE),'RunAtLoad':True,'KeepAlive':True,'ThrottleInterval':5,'Umask':0o077,
            'EnvironmentVariables':{'PATH':'/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin',
                'TMPDIR':str(_private_dir(store.data_dir/'cache'/'tmp')),'PYTHONPYCACHEPREFIX':str(_private_dir(store.data_dir/'cache'/'python'))},
            'StandardOutPath':str(store.data_dir/'logs'/'server.log'),'StandardErrorPath':str(store.data_dir/'logs'/'server-error.log')}


def start_instance(store,record):
    """Start or restore this customer's persistent macOS job and attest it.

    Existing instance launch metadata must match the controlled definition;
    ports, data directory and authentication remain stable when restored.
    """
    assert_ready(store)
    if sys.platform!='darwin':raise InstanceError(501,'自动开通后台服务目前仅支持本机 macOS')
    label='com.kanpace.factory.'+record['id']
    launch_dir=Path.home()/'Library'/'LaunchAgents';launch_dir.mkdir(parents=True,exist_ok=True)
    path=launch_dir/(label+'.plist')
    existing=path.exists()
    if path.is_symlink():raise InstanceError(409,'实例启动项不可使用符号链接')
    if existing:
        try:
            with path.open('rb') as stream:saved=plistlib.load(stream)
            arguments=saved['ProgramArguments'];port=int(arguments[arguments.index('--port')+1])
            if not 1<=port<=65535:raise ValueError()
        except (ValueError,KeyError,TypeError,OSError,plistlib.InvalidFileException):raise InstanceError(409,'实例启动项无效，请联系本机管理员')
        definition=launch_definition(store,record,port)
        if saved!=definition:raise InstanceError(409,'实例启动项与当前工厂不匹配，拒绝启动')
    else:
        port=_port();definition=launch_definition(store,record,port)
        with path.open('xb') as stream:
            os.fchmod(stream.fileno(),0o600);plistlib.dump(definition,stream)
    target=f'gui/{os.getuid()}/{label}';started_here=False
    try:
        running=subprocess.run(['/bin/launchctl','print',target],capture_output=True,timeout=10)
        if running.returncode:
            started=subprocess.run(['/bin/launchctl','bootstrap',f'gui/{os.getuid()}',str(path)],capture_output=True,timeout=15)
            if started.returncode:raise InstanceError(503,'独立工厂后台服务未能启动，请重试')
            started_here=True
        else:
            result=subprocess.run(['/bin/launchctl','kickstart',target],capture_output=True,timeout=10)
            if result.returncode:raise InstanceError(503,'独立工厂后台服务暂时无法恢复')
        url=f'http://127.0.0.1:{port}'
        opener=build_opener(ProxyHandler({}));deadline=time.monotonic()+15
        while time.monotonic()<deadline:
            try:
                with opener.open(Request(url+'/api/health'),timeout=1) as response:health=json.load(response)
                if health.get('instance_id')==record['id'] and health.get('authentication_required') is True:return url
            except (OSError,ValueError):pass
            time.sleep(.2)
        raise InstanceError(503,'独立工厂已配置，但服务启动校验未通过')
    except Exception:
        if started_here:
            try:subprocess.run(['/bin/launchctl','bootout',target],capture_output=True,timeout=10)
            except (OSError,subprocess.TimeoutExpired):pass
        if not existing:path.unlink(missing_ok=True)
        raise


def provision(server,data):
    parent=server.store;_require_controller(parent);payload=_payload(data)
    if fcntl is None:raise InstanceError(501,'自动开通后台服务目前仅支持本机 macOS')
    root=_private_dir(root_path(parent))
    lockpath=root/'.provision.lock'
    fd=os.open(lockpath,os.O_CREAT|os.O_RDWR|getattr(os,'O_NOFOLLOW',0),0o600)
    try:
        fcntl.flock(fd,fcntl.LOCK_EX)
        rows=_read_registry(parent)
        previous=next((r for r in rows if r.get('request_id')==payload['request_id']),None)
        if previous:
            if any(previous.get(key)!=payload.get(key) for key in ('name','factory_type','industry_id','variant_id')) or previous.get('admin_username')!=payload['admin']['username']:
                raise InstanceError(409,'开通请求编号已用于另一份配置，请重新填写')
            if previous.get('status') in ('ready','configured','start_failed'):
                from kanpace.application.store import Store
                child=Store(root/previous['id'],seed=False,empty=True)
                assert_ready(child)
                with child.connect() as con:
                    admin=next((u for u in access_control._users(child,con) if u['username']==payload['admin']['username']),None)
                if not admin or not access_control.password_matches(payload['admin']['password'],admin['password_hash']):
                    raise InstanceError(409,'这次开通请求的管理员密码已变化，请重新填写')
                try:
                    previous['url']=start_instance(child,previous);previous['status']='ready'
                except Exception as exc:
                    previous['status']='start_failed';_write_json(root/'registry.json',rows)
                    if isinstance(exc,InstanceError):raise
                    raise InstanceError(503,'独立工厂后台服务暂时无法恢复，请重试') from None
                _write_json(root/'registry.json',rows)
                return {'isolated':True,'instance':_public(previous),'url':previous['url'],'setup_url':previous['url']+'/factory-setup/index.html','factory_id':previous['factory_id'],'reused':True}
            raise InstanceError(409,'此开通请求状态无效，请联系本机管理员')
        if len(rows)>=MAX_INSTANCES:raise InstanceError(409,'本机已达到40个独立工厂上限')
        store,record=create_store(parent,payload)
        rows.append(record);_write_json(root/'registry.json',rows)
        try:
            record['url']=start_instance(store,record);record['status']='ready'
        except Exception as exc:
            record['status']='start_failed';_write_json(root/'registry.json',rows)
            if isinstance(exc,InstanceError):raise
            raise InstanceError(503,'独立工厂初始化成功，但后台服务未能启动') from None
        _write_json(root/'registry.json',rows)
        return {'isolated':True,'instance':_public(record),'url':record['url'],'setup_url':record['url']+'/factory-setup/index.html','factory_id':record['factory_id']}
    finally:
        fcntl.flock(fd,fcntl.LOCK_UN);os.close(fd)


def static_allowed(path):
    """Only audited application assets are shared. No customer study/sample data."""
    if str(path).strip('/') in ('factory','factory/index.html'):return True
    path=Path(path)
    if any(part in ('..','.') for part in path.parts):return False
    parts=path.parts
    if not parts:return False
    suffix=path.suffix.lower()
    if len(parts)==1:return path.name=='favicon.svg' or suffix in ('.js','.css','.html')
    if parts[0]=='brand':return len(parts)==2 and path.name in ('KANPACE-Handoff-Black.svg','KANPACE-Handoff-White.svg','brand.css')
    if parts[0]=='navigation-map' and len(parts)==2 and path.name in ('KANPACE-全部功能地图.svg','KANPACE-全部功能地图.png','KANPACE-全部功能地图.pdf'):return True
    if parts[0]=='core':return len(parts)==2 and path.name=='http-client.js'
    if parts[0]=='badge-studio':return len(parts)==2 and path.name in ('index.html','style.css','model.js','app.js')
    if parts[0]=='demo-assets':return len(parts)==2 and path.name in ('sample-drawing.png','sample-render.png','showcase-drawing.png','showcase-render.png')
    if parts[0] not in ('model','project-3d','bi','navigation-map','factory-setup'):return False
    if 'vendor' in parts:return suffix in ('.js','.mjs','.wasm','.woff','.woff2','.ttf')
    return suffix in ('.js','.mjs','.css','.html')
