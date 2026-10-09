'use strict';
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const fixtureText=fs.readFileSync(path.join(__dirname,'test_navigation_frontend.cjs'),'utf8').split('const startAction =')[0];
const context={require,__dirname,module:{exports:null},console,URLSearchParams,AbortController};
vm.runInNewContext(fixtureText+'\nmodule.exports=fixture;',context);
const fixture=context.module.exports,tests=[],test=(name,fn)=>tests.push([name,fn]);
test('home queries the whole factory and returning to a drawing restores the current order',async()=>{
 const f=fixture();f.c.window.KanpaceAgent.close();f.c.page='overview';f.c.window.KanpaceAgent.open();
 await f.agent.ask('今天先做什么');assert.equal(f.c.reads.at(-1).data.project_id,undefined);
 f.c.window.KanpaceAgent.close();f.c.page='drawing';f.c.window.KanpaceAgent.open();
 await f.agent.ask('检查拆单依据');assert.equal(f.c.reads.at(-1).data.project_id,'prj_a');assert.equal(f.c.writes.length,0);
});
test('an order action explicitly prefills the selected order without submitting or writing',()=>{
 const f=fixture();f.c.window.KanpaceAgent.close();f.c.page='overview';
 assert.equal(f.c.window.KanpaceAgent.open({projectId:'prj_b',prompt:'检查这单的漏项'}),true);
 assert.equal(f.elements.get('#ka-input').value,'检查这单的漏项');assert.equal(f.elements.get('#ka-project').value,'prj_b');assert.equal(f.c.reads.length,0);assert.equal(f.c.writes.length,0);
 f.c.window.KanpaceAgent.close();assert.equal(f.c.window.KanpaceAgent.open({projectId:'foreign',prompt:'检查'}),false);
});
test('engineering results label checks and sources without disguising them as orders',async()=>{
 const f=fixture();f.c.readReply=async()=>({ok:true,json:async()=>({mode:'local_commands',analysis_kind:'engineering_readiness',message:'有待核对项',results:[{kind:'check',title:'材料未填写',detail:'请核对',route:{page:'drawing',projectId:'prj_a'}},{kind:'source',title:'施工图.pdf',detail:'版本待核对',route:{page:'drawing',projectId:'prj_a'}}],actions:[]})});
 await f.agent.ask('检查拆单依据');const html=f.elements.get('#ka-transcript').innerHTML;assert.match(html,/待处理/);assert.match(html,/依据/);assert.equal(f.c.writes.length,0);
});
test('the next action preserves only permitted production tabs and exact project scope',async()=>{
 const f=fixture();await f.agent.openBusiness({type:'navigate',route:{page:'readiness',projectId:'prj_b',opTab:'inspections',opProject:'foreign',url:'/api/device/flash'}});
 const params=new URLSearchParams(f.c.location.hash);assert.equal(params.get('opTab'),'inspections');assert.equal(params.get('opProject'),'prj_b');assert.equal(params.get('project'),'prj_b');assert.equal(params.has('url'),false);
 assert.equal(f.agent.checkedRoute({page:'readiness',projectId:'prj_a',opTab:'access'}).opTab,undefined);
 assert.equal(f.agent.checkedRoute({page:'tasks',projectId:'prj_a',taskFocus:'paused'}).taskFocus,'paused');
 assert.throws(()=>f.agent.checkedRoute({page:'readiness',projectId:'foreign',opTab:'materials'}));assert.equal(f.c.writes.length,0);
});
(async()=>{let failed=0;for(const[name,fn]of tests){try{await fn();console.log('PASS',name);}catch(error){failed++;console.error('FAIL',name,error.stack);}}console.log(`${tests.length-failed}/${tests.length} contextual assistant checks passed`);if(failed)process.exitCode=1;})();
