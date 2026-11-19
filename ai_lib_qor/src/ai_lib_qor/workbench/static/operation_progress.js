(() => {
  const paths = new Set(['/scan-all','/scan','/formal-sync','/runs','/version-run','/effective-v2/run','/ip-run','/effective/apply','/evidence','/registration']);
  const overlay=document.getElementById('operation-overlay'), reopen=document.getElementById('operation-reopen');
  const title=document.getElementById('operation-title'), message=document.getElementById('operation-message');
  const bar=document.getElementById('operation-bar'), count=document.getElementById('operation-count');
  const events=document.getElementById('operation-events'), result=document.getElementById('operation-result');
  const close=document.getElementById('operation-close');
  let active=false;
  document.getElementById('operation-minimize').addEventListener('click',()=>{overlay.hidden=true;reopen.hidden=false;});
  reopen.addEventListener('click',()=>{overlay.hidden=false;reopen.hidden=true;});
  close.addEventListener('click',()=>{overlay.hidden=true;reopen.hidden=true;});
  function display(data) {
    if (!data) return;
    const labels={RUNNING:'正在运行',SUCCEEDED:'操作完成',FAILED:'操作失败',PARTIAL:'部分完成'};
    title.textContent=`${data.label} · ${labels[data.state] || data.state}`;
    message.textContent=data.message || '';
    if (Number.isInteger(data.total) && data.total>0 && Number.isInteger(data.completed)) {
      bar.max=data.total;bar.value=Math.max(0,Math.min(data.completed,data.total));
      count.textContent=`已处理 ${data.completed} / ${data.total} 项；仅表示处理数量`;
    } else {bar.removeAttribute('value');count.textContent='当前阶段没有可计算的百分比';}
    events.replaceChildren(...(data.events || []).map(text=>{const item=document.createElement('li');item.textContent=text;return item;}));
  }
  document.addEventListener('submit',async event=>{
    const form=event.target;
    if (!(form instanceof HTMLFormElement) || form.method.toLowerCase()!=='post' || !paths.has(new URL(form.action,location.href).pathname) || event.defaultPrevented || !window.crypto?.getRandomValues) return;
    event.preventDefault();
    if(active)return;
    active=true;const bytes=new Uint8Array(16);crypto.getRandomValues(bytes);
    const id=Array.from(bytes,x=>x.toString(16).padStart(2,'0')).join('');
    const data=new FormData(form);data.set('_operation_id',id);
    const submitters=Array.from(form.querySelectorAll('button[type="submit"],button:not([type]),input[type="submit"]'));
    submitters.forEach(button=>button.disabled=true);
    title.textContent='正在准备操作';message.textContent='正在连接工作台…';bar.removeAttribute('value');count.textContent='当前阶段没有可计算的百分比';events.replaceChildren();result.hidden=true;close.hidden=true;overlay.hidden=false;reopen.hidden=true;
    let polling=true,last=null;
    const poll=async()=>{
      if(!polling)return;
      try {const response=await fetch(`/operations/${id}`,{cache:'no-store'});if(response.ok){last=await response.json();display(last);}} catch (_) { /* The original request determines whether the operation failed. */ }
      if(polling)setTimeout(poll,600);
    };
    poll();
    try {
      const response=await fetch(form.action || location.href,{method:'POST',body:data,credentials:'same-origin'});
      try {const status=await fetch(`/operations/${id}`,{cache:'no-store'});if(status.ok){last=await status.json();display(last);}} catch (_) {}
      if(!response.ok){
        const page=new DOMParser().parseFromString(await response.text(),'text/html');
        title.textContent='操作失败';message.textContent=page.querySelector('.warning')?.textContent?.trim() || `请求失败（HTTP ${response.status}）`;
      } else if(!last || last.state==='RUNNING') {
        title.textContent='操作请求已结束';message.textContent='未能读取最终进度，请查看结果确认状态。';
      }
      if(response.redirected && new URL(response.url).origin===location.origin){result.href=response.url;result.hidden=false;}
    } catch (_) {title.textContent='连接中断';message.textContent='无法确认操作是否完成，请查看运行记录后再决定是否重试。';}
    finally {polling=false;active=false;submitters.forEach(button=>button.disabled=false);close.hidden=false;}
  });
})();
