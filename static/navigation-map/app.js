'use strict';
(() => {
  const escapeText=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const params=new URLSearchParams(location.search), project=params.get('project')||'', search=document.querySelector('#map-search');
  let access=null, isolated=true;
  const features=item=>window.KANPACE_FEATURES[item.id]||[];
  const featureLabel=item=>typeof item==='string'?item:item.label;
  const href=item=>item.href||window.kanpaceMenuHref(item.route||item,{projectId:project,prefix:'/'});
  const permitted=item=>!item.financial||access?.financial_access===true||access?.enabled===false;
  function entry(item,list=features(item)) {
    const title=permitted(item)?`<a href="${escapeText(href(item))}">${escapeText(item.label)}</a>`:`<span class="map-disabled">${escapeText(item.label)}<small>${access?'当前账号不可用':'登录后按权限进入'}</small></span>`;
    return `<li class="map-entry">${title}<ul>${list.map(feature=>`<li>${typeof feature==='object'&&feature.route&&permitted(item)?`<a href="${escapeText(href(feature))}">${escapeText(feature.label)}</a>`:escapeText(featureLabel(feature))}</li>`).join('')}</ul></li>`;
  }
  function render() {
    const q=search.value.trim().toLowerCase();let count=0;
    const groups=window.KANPACE_MENU.map(group=>{
      const items=group.items.filter(item=>[group.label,item.label,...features(item).map(featureLabel)].join(' ').toLowerCase().includes(q));count+=items.length;
      return items.length?`<section class="map-group"><h2>${escapeText(group.label)}</h2><ol class="map-entries">${items.map(item=>entry(item)).join('')}</ol></section>`:'';
    }).join('');
    document.querySelector('#map-tree').innerHTML=groups||'<p class="map-empty">没有找到这个名称，试试“缺料”“订单”或点击“查看全部”。</p>';
    document.querySelector('#map-result').textContent=q?`找到 ${count} 个菜单入口`:'';
    document.querySelector('#map-global').innerHTML=window.KANPACE_MAP_GLOBAL.map(item=>`<ul>${entry(item,item.features)}</ul>`).join('');
    document.querySelector('#map-help').innerHTML=window.KANPACE_MAP_HELP.filter(item=>!item.controllerOnly||!isolated).map(item=>`<ul>${entry(item,item.features)}</ul>`).join('');
  }
  document.querySelector('#map-changes').innerHTML=window.KANPACE_MENU_PROMOTIONS.map(row=>`<tr>${row.map(cell=>`<td>${escapeText(cell)}</td>`).join('')}</tr>`).join('');
  search.addEventListener('input',render);document.querySelector('#map-clear').addEventListener('click',()=>{search.value='';render();search.focus();});
  render();
  fetch('/api/factory-instances/status',{credentials:'same-origin'}).then(r=>r.ok?r.json():null).then(data=>{if(data&&typeof data.isolated==='boolean'){isolated=data.isolated;render();}}).catch(()=>{});
  fetch('/api/access',{credentials:'same-origin'}).then(r=>r.ok?r.json():null).then(data=>{if(data&&typeof data==='object'){access=data;render();}}).catch(()=>{});
})();
