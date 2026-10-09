'use strict';
(() => {
  const message=document.querySelector('#runtime-message');
  const button=document.querySelector('#runtime-refresh');
  async function check(){
    button.disabled=true;message.textContent='正在检查本机引擎…';
    try{
      const response=await fetch('/api/intelligence/status',{headers:{Accept:'application/json'}});
      if(!response.ok)throw new Error(response.status===401?'请先返回工作台登录，再检查本机状态。':'本机检查暂未完成，请重试。');
      const state=await response.json();
      const checks={paddleocr:state.engineering?.ocr?.ready,occt:state.engineering?.cad?.ready,
        ortools:state.optimization?.ortools?.available,packingsolver:state.optimization?.packingsolver?.available,
        langgraph:state.agent?.available};
      const probeState=state.engineering?.probe?.state;
      for(const [key,available] of Object.entries(checks)){
        const engineering=key==='paddleocr'||key==='occt';
        document.querySelector(`[data-engine="${key}"]`).textContent=available?'本机可用':engineering&&probeState==='running'?'正在检查':engineering&&probeState==='timeout'?'稍后重试':'需要检查安装';
      }
      const count=Object.values(checks).filter(Boolean).length;
      message.textContent=`${count} / 5 项本机可用。图纸和生产数据留在本厂；计算结果经过复核后用于生产。`;
    }catch(error){
      for(const element of document.querySelectorAll('[data-engine]'))element.textContent='尚未确认';
      message.textContent=error.message;
    }finally{button.disabled=false;}
  }
  button.addEventListener('click',check);check();
})();
