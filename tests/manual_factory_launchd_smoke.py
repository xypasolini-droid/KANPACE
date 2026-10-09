"""Explicit macOS smoke: real authenticated controller HTTP -> launchd child.
Creates only temporary data/a temporary LaunchAgent and cleans both up. Never
run automatically as part of unit discovery or against the production service.
"""
import json,os,secrets,subprocess,sys,tempfile,threading
from pathlib import Path
from urllib.request import build_opener,ProxyHandler,HTTPCookieProcessor,Request
from urllib.error import HTTPError
from http.cookiejar import CookieJar
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import app,factory_instances as instances,access_control as access
passed=[];job=None;plist=None;controller_server=None
scratch=tempfile.TemporaryDirectory(prefix='kanpace-launch-smoke-')
try:
 root=Path(scratch.name);parent=app.Store(root/'controller',seed=False,empty=True)
 fixture_static=root/'static';(fixture_static/'studies'/'test-customer').mkdir(parents=True)
 (fixture_static/'index.html').write_text('<!doctype html><title>Temporary controller</title>')
 (fixture_static/'studies'/'test-customer'/'private.pdf').write_bytes(b'%PDF-1.4\nTEMPORARY PRIVATE FIXTURE')
 controller_server=app.Server(('127.0.0.1',0),parent,fixture_static)
 threading.Thread(target=controller_server.serve_forever,daemon=True).start()
 controller_url=f'http://127.0.0.1:{controller_server.server_port}'
 bare=build_opener(ProxyHandler({}));root_cookie=CookieJar();controller=build_opener(ProxyHandler({}),HTTPCookieProcessor(root_cookie))
 def request(opener,base,path,data=None,expect=200):
  kwargs={} if data is None else {'data':json.dumps(data).encode(),'headers':{'Content-Type':'application/json','Origin':base}}
  try:
   with opener.open(Request(base+path,**kwargs),timeout=40) as response:code=response.status;body=response.read()
  except HTTPError as error:code=error.code;body=error.read();error.close()
  assert code==expect,(path,code,expect)
  return json.loads(body)
 before=request(bare,controller_url,'/api/factory-instances/status');assert before['controller_auth_required'] and not before['can_provision']
 password=secrets.token_urlsafe(24);controller_password=secrets.token_urlsafe(24)
 payload={'name':'隔离启动验证工厂','factory_type':'cabinet','request_id':'smoke-'+secrets.token_hex(8),'admin':{'name':'临时测试管理员','username':'smoke_admin','password':password}}
 request(bare,controller_url,'/api/factory-instances/provision',payload,409);assert not instances.root_path(parent).exists();passed.append('unprotected_controller_cannot_provision')
 request(controller,controller_url,'/api/access/setup',{'username':'controller_admin','name':'临时控制台管理员','password':controller_password})
 request(controller,controller_url,'/api/access/login',{'username':'controller_admin','password':controller_password})
 request(bare,controller_url,'/api/state',expect=401);request(bare,controller_url,'/studies/test-customer/private.pdf',expect=401);passed.append('authenticated_controller_private_state_and_static_deny_anonymous')
 ready=request(controller,controller_url,'/api/factory-instances/status');assert ready['can_provision'] and not ready['controller_auth_required']
 response=request(controller,controller_url,'/api/factory-instances/provision',payload,201)
 record=instances._read_registry(parent)[0];folder=instances.root_path(parent)/record['id'];url=response['url']
 job=f'gui/{os.getuid()}/com.kanpace.factory.'+record['id'];plist=Path.home()/'Library'/'LaunchAgents'/('com.kanpace.factory.'+record['id']+'.plist')
 health=request(bare,url,'/api/health');assert health['instance_id']==record['id'] and health['authentication_required'];passed.append('real_authenticated_http_provision_launchd_ready_identity')
 request(bare,url,'/api/state',expect=401);a=request(bare,url,'/api/access');assert a['enabled'] and a['user'] is None;passed.append('child_authentication_precedes_first_access')
 jar=CookieJar();browser=build_opener(ProxyHandler({}),HTTPCookieProcessor(jar));request(browser,url,'/api/access/login',{'username':'smoke_admin','password':password})
 initial=request(browser,url,'/api/state');assert not initial['projects'] and not initial['people'];passed.append('own_cookie_login_empty_projects_people')
 request(browser,controller_url,'/api/state',expect=401);request(browser,controller_url,'/studies/test-customer/private.pdf',expect=401);passed.append('child_admin_cookie_cannot_read_controller_state_or_private_pdf')
 project=request(browser,url,'/api/projects',{'name':'临时持久化检查','factory_type':'cabinet','factory_id':record['factory_id'],'quantity':1})['project']['id'];passed.append('temporary_record_written_only_to_private_child_store')
 again=request(controller,controller_url,'/api/factory-instances/provision',payload,201);assert again['reused'] and again['url']==url;passed.append('same_request_restores_running_job_without_new_store_or_port')
 stopped=subprocess.run(['/bin/launchctl','bootout',job],capture_output=True,timeout=15);assert stopped.returncode==0;passed.append('stopped_only_this_temporary_job')
 child=app.Store(folder,seed=False,empty=True);assert instances.start_instance(child,record)==url;passed.append('restored_same_port_directory_with_real_launcher')
 resumed=request(browser,url,'/api/state');assert any(p['id']==project for p in resumed['projects']) and not resumed['people'];passed.append('private_record_and_own_session_survive_restart')
 current=request(browser,url,'/api/access');assert current['factory_data_isolation'] and current['instance_id']==record['id'];passed.append('instance_status_truthfully_isolated')
 request(browser,url,'/api/device');passed.append('device_runtime_initializes_without_hardware_mutation')
 print(json.dumps({'passed':passed,'count':len(passed),'ephemeral_port':url.rsplit(':',1)[1],'real_launchd':True,'controller_authenticated':True},ensure_ascii=False))
finally:
 if job:
  subprocess.run(['/bin/launchctl','bootout',job],capture_output=True,timeout=15)
  check=subprocess.run(['/bin/launchctl','print',job],capture_output=True,timeout=10)
  assert check.returncode!=0,'test job still registered'
 if plist:plist.unlink(missing_ok=True)
 if controller_server:controller_server.shutdown();controller_server.server_close()
 scratch.cleanup()
 print(json.dumps({'cleanup':'temporary job removed and verified absent; only its plist/controller/child fixtures deleted','production_service_touched':False},ensure_ascii=False))
