const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../static/task-references.js'),'utf8');
const escape=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function fixture(){
  const content={innerHTML:'',textContent:''},host={dataset:{referenceTask:'t1'}},handlers={},dialog={innerHTML:'',open:false};
  const c={URL,console,location:{origin:'http://127.0.0.1:8775'},esc:escape,num:String,executionRequest:async()=>c.reply,
    document:{addEventListener:(type,fn)=>handlers[type]=fn,querySelector:()=>host,getElementById:id=>id==='task-references-content'?content:dialog}};
  vm.createContext(c);vm.runInContext(source,c);
  return {c,content,host,handlers,dialog,run:s=>vm.runInContext(s,c)};
}
const task={id:'t1',project_id:'p1',title:'侧板开料'};
const response=()=>({project_id:'p1',task_id:'t1',revision:2,project_name:'多图项目',items:[
  {kind:'render',url:'/api/documents/r/image',source_file:'效果图.jpg',title:'整体外观'},
  {kind:'drawing',url:'/api/documents/d/image',source_file:'工程图.png',title:'部件工程图',task_linked:true},
  {kind:'drawing',url:'/api/documents/e/image',source_file:'施工图.png',title:'施工图'}]});
test('engineering filename stays recognizable when the source kind is generic',()=>{const f=fixture();assert.equal(f.c.taskReferencesKind({kind:'drawing',source_kind:'uploaded_drawing',source_file:'部件工程图.png'}),'工程图');});
test('all project reference images remain available and matched engineering is first',async()=>{const f=fixture();f.c.reply=response();await f.c.taskReferencesLoad(task);assert.equal(f.run('taskReferencesData.items.length'),3);assert.equal(f.run('taskReferencesData.items[0].source_file'),'工程图.png');assert.match(f.content.innerHTML,/本部件依据/);assert.match(f.content.innerHTML,/项目参考/);assert.match(f.content.innerHTML,/效果图.jpg/);});
test('foreign project/task response and unsafe URL are never rendered',async()=>{const f=fixture();f.c.reply={...response(),project_id:'another'};await f.c.taskReferencesLoad(task);assert.match(f.content.textContent,/范围不一致/);assert.equal(f.content.innerHTML,'');for(const url of ['https://evil.example/image','javascript:alert(1)','/not-api/a.jpg'])assert.equal(f.c.taskReferencesUrl(url),'');});
test('late response cannot replace the next task gallery',async()=>{const f=fixture();let resolve;f.c.executionRequest=()=>new Promise(r=>resolve=r);const request=f.c.taskReferencesLoad(task);f.host.dataset.referenceTask='t2';resolve(response());await request;assert.equal(f.content.innerHTML,'');assert.equal(f.run('taskReferencesData'),null);});
test('logout reset prevents a late gallery response restoring private sources',async()=>{const f=fixture();let resolve;f.c.executionRequest=()=>new Promise(r=>resolve=r);const request=f.c.taskReferencesLoad(task);f.c.taskReferencesReset();resolve(response());await request;assert.equal(f.content.innerHTML,'');assert.equal(f.run('taskReferencesData'),null);});
test('comparison preserves two real source images and navigation wraps',async()=>{const f=fixture();f.c.reply=response();await f.c.taskReferencesLoad(task);f.run('taskReferencesCompare=true;taskReferencesIndex=2;taskReferencesRender()');assert.equal((f.dialog.innerHTML.match(/<figure>/g)||[]).length,2);assert.match(f.dialog.innerHTML,/施工图.png/);assert.match(f.dialog.innerHTML,/工程图.png/);f.run('taskReferencesIndex=3;taskReferencesRender()');assert.equal(f.run('taskReferencesIndex'),0);});
test('source names are escaped and empty/error results are clear',async()=>{const f=fixture();f.c.reply=response();f.c.reply.items[0].source_file='<img src=x onerror=alert(1)>';await f.c.taskReferencesLoad(task);assert.doesNotMatch(f.content.innerHTML,/<img src=x/);assert.match(f.content.innerHTML,/&lt;img/);f.c.reply={...response(),items:[]};await f.c.taskReferencesLoad(task);assert.match(f.content.innerHTML,/还没有/);f.c.executionRequest=async()=>{throw Error('连接中断，请重试')};await f.c.taskReferencesLoad(task);assert.match(f.content.textContent,/连接中断/);});
