'use strict';
const $ = id => document.getElementById(id);
const escapeHTML = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const list = value => Array.isArray(value) ? value : value && typeof value === 'object' ? Object.entries(value).map(([k,v])=>`${k}：${v}`) : value ? [value] : [];
const bullets = value => `<ul>${list(value).map(x=>`<li>${escapeHTML(x)}</li>`).join('')}</ul>`;
const link = (url,label) => /^https:\/\//.test(url||'') ? `<a href="${escapeHTML(url)}" target="_blank" rel="noopener noreferrer">${escapeHTML(label)}</a>` : escapeHTML(label);
let data;
const priorityOrder=['沿用完善','优先验证','按需引入','模式参考','后期考虑','备选','谨慎评估'];
function card(c) {
  const cautious=c.priority==='谨慎评估';
  return `<details class="candidate" id="candidate-${escapeHTML(c.id)}"><summary><div class="card-top"><span>${escapeHTML(c.category)}</span><span class="badge ${cautious?'caution':''}">${escapeHTML(c.priority)}</span></div><h3>${escapeHTML(c.name)}</h3><p>${escapeHTML(c.features.join(' · '))}</p><div class="license-line">${escapeHTML(c.license)}<br>${escapeHTML(c.activity_label)}</div></summary><div class="details"><h4>可以借用的能力</h4>${bullets(c.capabilities)}<h4>怎么接到 KANPACE</h4><p>${escapeHTML(c.integration).replace(/\n/g,'<br>')}</p>${c.fit?`<h4>场景适配</h4>${bullets(c.fit)}`:''}<h4>能力与版本边界</h4>${bullets(c.limits)}${c.license_notes?`<h4>组件许可说明</h4>${bullets(c.license_notes)}`:''}<div class="evidence">${link(c.repo_url,'项目仓库 ↗')}${link(c.license_url,'许可证原文 ↗')}${c.activity_url?link(c.activity_url,'维护记录 ↗'):''}</div><details><summary class="detail-note">全部官方来源（${c.sources.length}）</summary><div class="evidence">${c.sources.map((s,i)=>link(s,`${i+1}. ${new URL(s).hostname} · ${decodeURI(new URL(s).pathname).slice(0,70)}`)).join('')}</div></details><p class="detail-note">${escapeHTML(c.validation_status)}</p></div></details>`;
}
function render(){
  const q=$('search').value.trim().toLowerCase(), category=$('category').value, priority=$('priority').value,license=$('license').value;
  const found=data.candidates.filter(c=>(!category||c.category===category)&&(!priority||c.priority===priority)&&(!license||c.license_group===license)&&(!q||c.search_text.toLowerCase().includes(q))).sort((a,b)=>priorityOrder.indexOf(a.priority)-priorityOrder.indexOf(b.priority));
  $('results').innerHTML=found.length?found.map(card).join(''):'<p class="empty">没有匹配的条目。试试其他关键词，或重置筛选。</p>';
  $('result-count').textContent=`${found.length} / ${data.candidates.length} 条`;
}
function reset(){['search','category','priority','license'].forEach(id=>$(id).value='');render();}
async function init(){
  try{
    const response=await fetch('catalog.json');if(!response.ok)throw new Error(`HTTP ${response.status}`);
    data=await response.json();
    $('count-all').textContent=data.candidates.length;$('count-coverage').textContent=data.coverage.length;
    for(const [id,key] of [['category','category'],['priority','priority'],['license','license_group']]){
      const values=[...new Set(data.candidates.map(c=>c[key]))];
      if(id==='priority')values.sort((a,b)=>priorityOrder.indexOf(a)-priorityOrder.indexOf(b));
      for(const value of values){const option=document.createElement('option');option.value=value;option.textContent=value;$(id).append(option);}
      $(id).addEventListener('change',render);
    }
    $('search').addEventListener('input',render);$('reset').addEventListener('click',reset);
    $('find-omni').addEventListener('click',()=>{reset();$('search').value='omniverse';render();const first=$('results').querySelector('details');if(first)first.open=true;});
    $('coverage-list').innerHTML=data.coverage.map(c=>`<details class="coverage-item"><summary><b>${escapeHTML(c.feature)}</b><span>${escapeHTML(c.priority)}</span></summary><div class="details"><h4>场景与现有基础</h4>${bullets(c.scene)}${bullets(c.current_state)}<h4>推荐项目</h4>${bullets(c.recommended_projects)}<h4>KANPACE 需要自己掌握</h4>${bullets(c.must_build)}<h4>实际验收条件</h4>${bullets(c.acceptance)}</div></details>`).join('');
    render();
  }catch(error){$('error').hidden=false;$('error').textContent='选型资料加载失败，请确认本地服务已启动后刷新。';$('result-count').textContent='未加载';}
}
init();
