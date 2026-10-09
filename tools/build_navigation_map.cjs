/* Rebuild the shareable diagram from the same destinations used by the Web. */
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.resolve(__dirname,'..');
const context={window:{},URLSearchParams};vm.createContext(context);
for(const file of ['static/navigation-data.js','static/navigation-map/features.js'])vm.runInContext(fs.readFileSync(path.join(root,file),'utf8'),context);
const {KANPACE_MENU:groups,KANPACE_FEATURES:features,KANPACE_MAP_GLOBAL:global,KANPACE_MAP_HELP:help}=context.window;
const esc=x=>String(x).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const split=(s,n=21)=>{let lines=[''],size=0;for(const c of String(s)){const weight=c.charCodeAt(0)>255?1:.55;if(size+weight>n){lines.push('');size=0;}lines[lines.length-1]+=c;size+=weight;}return lines;};
const W=3000,C=480,G=16,left=20;let marks=[];
const text=(x,y,s,size=20,color='#4d5968',weight=400)=>marks.push(`<text x="${x}" y="${y}" font-size="${size}" fill="${color}" font-weight="${weight}">${esc(s)}</text>`);
const line=(x1,y1,x2,y2,color='#b7c0cc')=>marks.push(`<path d="M${x1} ${y1}H${x2}V${y2}" fill="none" stroke="${color}" stroke-width="1.5"/>`);
function item(item,x,y,lines=features[item.id]||[]){
  text(x+24,y,item.label,26,'#214bcb',600);line(x,y-8,x+15,y-8);y+=32;
  for(const f of lines){for(const l of split(typeof f==='string'?f:f.label)){text(x+24,y,l);y+=27;}}
  return y+25;
}
text(32,62,'KANPACE · 全部功能地图',44,'#202935',600);
text(32,103,'6 个大标题 → 直接进入的小标题 → 页面里能做的事',24);
text(32,139,'先找到要做的工作，再进入项目核对和操作。图中不含任何客户订单或生产数据。',21);
const colEnds=[];
groups.forEach((group,i)=>{
  const x=left+i*(C+G);text(x+22,235,group.label,32,'#202935',600);
  line(x+22,249,x+C-22,249);line(x+C/2,167,x+C/2,200);
  let y=294;
  for(const entry of group.items){const start=y;y=item(entry,x+10,y);line(x+10,start-8,x+10,y-28);}
  colEnds.push(y);
});
line(left+C/2,167,left+5*(C+G)+C/2,167);
let top=Math.max(...colEnds)+40;
text(32,top,'全局入口与资料页',30,'#202935',600);top+=48;
const extra=[...global,...help];let row=top;
for(let i=0;i<extra.length;i+=6){let ends=[];extra.slice(i,i+6).forEach((entry,j)=>ends.push(item(entry,left+j*(C+G)+10,row,entry.features)));row=Math.max(...ends)+28;}
text(32,row+15,'开通工厂要准备：工厂与产品 / 人员与设备 / 订单与图纸 / 排程与流程。不同客户工厂在各自独立空间导入。',23,'#202935');
text(32,row+54,'说明：登记交付不等于整单发货；参考模板需本厂确认；真实三维模型与旧尺寸示意分别标注。',21);
const H=row+90;
const svg=`<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" role="img" aria-labelledby="title desc"><title id="title">KANPACE 全部 Web 功能层级图</title><desc id="desc">包含工作台、项目、生产、经营、工牌、工厂管理六组、所有二级菜单、页内操作和帮助研究页。</desc><rect width="100%" height="100%" fill="#fff"/><g font-family="PingFang SC,Microsoft YaHei,Noto Sans CJK SC,sans-serif">${marks.join('')}</g></svg>`;
const out=path.join(root,'static/navigation-map/KANPACE-全部功能地图.svg');fs.writeFileSync(out,svg);console.log(JSON.stringify({output:out,width:W,height:H,groups:groups.length,entries:groups.reduce((n,g)=>n+g.items.length,0),features:Object.values(features).reduce((n,f)=>n+f.length,0)}));
