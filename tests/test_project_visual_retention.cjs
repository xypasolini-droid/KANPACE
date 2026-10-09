const fs=require('fs'),path=require('path'),vm=require('vm'),assert=require('assert');
const source=fs.readFileSync(path.join(__dirname,'../static/project-visual.js'),'utf8').split("document.addEventListener('click'")[0];
// Small DOM fixture models identity/connection and attributes, not browser rendering.
class Element {
  constructor(tag,attrs={}){this.tagName=tag.toUpperCase();this.attrs={...attrs};this.childNodes=[];this.parentElement=null;}
  get attributes(){return Object.entries(this.attrs).map(([name,value])=>({name,value}));}
  get dataset(){return Object.fromEntries(Object.entries(this.attrs).filter(([key])=>key.startsWith('data-')).map(([key,value])=>[key.slice(5),value]));}
  get classList(){return {contains:name=>(this.attrs.class||'').split(' ').includes(name)};}
  get isConnected(){return this===root||!!this.parentElement?.isConnected;}
  getAttribute(key){return this.attrs[key]??null;} hasAttribute(key){return key in this.attrs;}
  setAttribute(key,value){this.attrs[key]=String(value);} removeAttribute(key){delete this.attrs[key];}
  matches(selector){return selector[0]==='#'?this.attrs.id===selector.slice(1):selector[0]==='.'?this.classList.contains(selector.slice(1)):this.tagName===selector.toUpperCase();}
  querySelector(selector){for(const child of this.childNodes){if(child.matches(selector))return child;const found=child.querySelector(selector);if(found)return found;}return null;}
  closest(selector){return this.matches(selector)?this:this.parentElement?.closest(selector);}
  remove(){if(this.parentElement){const list=this.parentElement.childNodes;list.splice(list.indexOf(this),1);this.parentElement=null;}if(this.tagName==='IFRAME')this.disconnected=true;}
  append(child){if(child.parentElement)child.remove();child.parentElement=this;this.childNodes.push(child);}
  insertBefore(child,before){if(child.parentElement)child.remove();child.parentElement=this;this.childNodes.splice(this.childNodes.indexOf(before),0,child);}
  cloneNode(deep){const clone=new Element(this.tagName,this.attrs);if(deep)for(const child of this.childNodes)clone.append(child.cloneNode(true));return clone;}
  set innerHTML(key){for(const child of [...this.childNodes])child.remove();for(const child of templates[key].childNodes)this.append(child.cloneNode(true));}
}
const el=(tag,attrs,...children)=>{const node=new Element(tag,attrs);children.forEach(child=>node.append(child));return node;};
function shell(project,url,{mode='model',filter='old',stale=false,frame=false}={}){
  const slot=el('div',{class:'project-model-slot','data-src':url,'data-title':project},...(frame?[el('iframe',{class:'project-model-frame',src:url})]:[]));
  const mainAttrs={id:'main',class:`page ${filter}`};if(stale)mainAttrs['data-stale']='remove';
  return el('div',{},el('aside',{'data-label':filter}),el('main',mainAttrs,el('header',{'data-label':project}),el('section',{class:'project-visual-panel','data-project':project,'data-mode':mode},el('div',{class:'actions','data-label':mode}),el('div',{class:'project-model-view',...(mode==='effects'?{hidden:''}:{})},slot)),el('input',{'data-label':filter})));
}
const urlA='/model/index.html?project=a&document=a-model&embed=1',urlB='/model/index.html?project=b&document=b-model&embed=1';
const templates={initial:shell('a',urlA,{stale:true,frame:true}),refresh:shell('a',urlA,{filter:'new',mode:'effects'}),other:shell('b',urlB),newDoc:shell('a','/model/index.html?project=a&document=new&embed=1'),projects:el('div',{},el('main',{id:'main'},el('h1',{'data-label':'项目订单'})))};
let root=new Element('div',{id:'app'});root.innerHTML='initial';const frame=root.querySelector('iframe');frame.camera={view:'front',cabinet:'高柜1'};
const context={Map,document:{querySelector:selector=>selector==='#app'?root:root.querySelector(selector),createElement:tag=>new Element(tag)}};vm.createContext(context);vm.runInContext(source,context);
const render=key=>vm.runInContext(`renderAppWithProjectVisual(${JSON.stringify(key)})`,context);
render('refresh');assert.equal(root.querySelector('iframe'),frame);assert(frame.isConnected);assert(!frame.disconnected);assert.deepEqual(frame.camera,{view:'front',cabinet:'高柜1'});
assert.equal(root.querySelector('#main').attrs.class,'page new');assert(!root.querySelector('#main').hasAttribute('data-stale'));assert(root.querySelector('.project-model-view').hasAttribute('hidden'));assert.equal(root.querySelector('input').dataset.label,'new');assert.equal(root.querySelector('aside').dataset.label,'new');
render('other');assert(!frame.isConnected);assert.equal(root.querySelector('.project-visual-panel').dataset.project,'b');assert.equal(root.querySelector('iframe'),null);
root.innerHTML='initial';const replaced=root.querySelector('iframe');render('newDoc');assert(!replaced.isConnected);assert.equal(root.querySelector('.project-model-slot').dataset.src,'/model/index.html?project=a&document=new&embed=1');
root.innerHTML='initial';const removed=root.querySelector('iframe');render('projects');assert(!removed.isConnected);assert.equal(root.querySelector('.project-model-slot'),null);
console.log('PASS: same-project iframe remains connected with camera state; sibling content and attributes refresh; page/project/document changes discard old frame.');
