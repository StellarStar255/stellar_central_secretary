/* Per-item task controls; archived contents are never sent by this panel. */
(()=>{
 const $=s=>document.querySelector(s),t=s=>StellarI18n.t(s),esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const stages={queued:'排队中',preparing:'正在准备摘要',reading_sources:'正在读取来源',starting_model:'正在启动模型',waiting_model:'等待模型响应',retrying_model:'正在分段重试',processing_result:'正在保存结果',done:'处理完成',saved:'正文已保存',error:'未完成',stopping:'正在停止',stopped:'已停止',queued_capture:'等待读取',opening_browser:'正在打开浏览器',waiting_login:'等待你登录',confirming_login:'正在确认登录',reading:'正在读取正文'};
 let api,openItem,toast,timer,rows=[],markup='',loading=false;
 function render(){
  const mode=$('#task-filter').value,list=rows.filter(task=>!mode||mode==='active'&&task.active||mode==='attention'&&!task.active&&['error','stopped'].includes(task.stage));
  const expanded=new Set([...$('#tasks-list').querySelectorAll('details[open]')].map(node=>node.closest('[data-task-key]').dataset.taskKey));
  const html=list.map(task=>`<article class="task-row" data-task-key="${task.kind}:${task.id}"><div class="task-heading"><strong>${esc(task.title)}</strong><span>${esc(t(stages[task.stage]||task.stage))}</span></div><p class="muted">${t(task.kind==='capture'?'网页读取':'资料整理')} · <span data-task-time="${task.kind}:${task.id}"></span></p>${task.error?`<p class="task-explanation">${esc(t(task.error.message))}</p><details><summary>${t('查看详细原因')}</summary><pre>${esc(task.error.detail)}</pre></details>`:''}<div class="detail-actions"><button class="secondary" data-task-action="open" data-id="${task.id}">${t('查看资料')}</button>${task.active?`<button class="secondary" data-task-action="cancel" data-id="${task.id}" data-kind="${task.kind}" ${task.stage==='stopping'?'disabled':''}>${t('停止这条任务')}</button>`:task.retryable&&['error','stopped'].includes(task.stage)?`<button class="secondary" data-task-action="retry" data-id="${task.id}" data-kind="${task.kind}">${t('重新尝试')}</button>`:''}</div></article>`).join('');
  if(html!==markup){markup=html;$('#tasks-list').innerHTML=html;for(const row of $('#tasks-list').querySelectorAll('[data-task-key]'))if(expanded.has(row.dataset.taskKey))row.querySelector('details')?.setAttribute('open','')}
  for(const task of list){const node=$('#tasks-list').querySelector('[data-task-time="'+task.kind+':'+task.id+'"]');if(node)node.textContent=Math.round(task.elapsed_seconds||0)+t(' 秒')}
  $('#tasks-empty').hidden=list.length>0;
 }
 async function refresh(){if(loading)return;loading=true;try{rows=(await api('/api/tasks')).tasks;$('#tasks-status').textContent='';render()}catch(error){$('#tasks-status').textContent=error.message}finally{loading=false}}
 function bind(options){({api,openItem,toast}=options);$('#tasks-open').onclick=()=>{if(!$('#tasks-dialog').open)$('#tasks-dialog').showModal();void refresh();clearInterval(timer);timer=setInterval(()=>{if($('#tasks-dialog').open)void refresh();else clearInterval(timer)},1000)};$('#library-tasks').onclick=$('#tasks-open').onclick;$('#task-filter').onchange=render;
  $('#tasks-dialog').addEventListener('close',()=>clearInterval(timer));
  $('#tasks-list').onclick=async event=>{const button=event.target.closest('[data-task-action]');if(!button)return;const action=button.dataset.taskAction,id=button.dataset.id;if(action==='open'){await openItem(id);return}button.disabled=true;try{await api('/api/tasks/'+id+'/'+action,{kind:button.dataset.kind});toast(t(action==='cancel'?'停止请求已提交，已有资料会保留。':'已提交重试。'));await refresh()}catch(error){toast(error.message)}finally{button.disabled=false}};
 }
 globalThis.StellarTasks={bind,refresh};
})();
