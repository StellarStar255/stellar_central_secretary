/* Company approval is a user acknowledgement, scoped to the current model configuration. */
(()=>{
 const t=s=>StellarI18n.t(s),esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 let pending=null,enabled=false,modeChanging=false,modeRevision=0;
 function confirm(info){
  if(pending)return pending;
  pending=new Promise(resolve=>{
   const dialog=document.createElement('dialog');dialog.id='company-model-dialog';
   dialog.innerHTML='<h2>'+t('确认公司资料的模型服务')+'</h2><p>'+t('总结和问答会将相关正文、图片或检索片段发送给下面的模型服务。确认后，后续公司资料可按设置自动总结。')+'</p><div class="detail-text"><strong>'+esc(t(info.destination))+'</strong><br>'+esc(t(info.model))+'</div><p>'+t('软件无法核实公司是否批准该服务。请核对当前账户；更换 CLI 登录账户后，应撤销并重新确认。')+'</p><label class="check"><input id="company-model-ack" type="checkbox">'+t('我已确认公司允许将这些资料交给上述服务和当前账户处理。')+'</label><div class="detail-actions"><button type="button" id="company-model-cancel" class="secondary">'+t('暂不确认，保留正文')+'</button><button type="button" id="company-model-approve" class="primary" disabled>'+t('确认此服务')+'</button></div>';
   const finish=value=>{dialog.close();dialog.remove();pending=null;resolve(value)};
   dialog.querySelector('#company-model-ack').onchange=e=>dialog.querySelector('#company-model-approve').disabled=!e.target.checked;
   dialog.querySelector('#company-model-approve').onclick=()=>finish(true);
   dialog.querySelector('#company-model-cancel').onclick=()=>finish(false);
   dialog.oncancel=e=>{e.preventDefault();finish(false)};
   document.body.append(dialog);dialog.showModal();
  });return pending;
 }
 async function review(api,info){
  if(!info.enabled)return true;
  if(!await confirm(info))return false;
  await api('/api/company-model/approve',{fingerprint:info.fingerprint,acknowledged:true});
  return true;
 }
 function render(item){
  if(!enabled)return '';
  if(!item.company_data)return '<p><button type="button" id="company-data-mark" class="secondary">'+t('按公司资料处理')+'</button></p>';
  return '<section class="company-data-policy"><strong>'+t('公司 / 浏览器采集资料')+'</strong><p>'+t('首次确认模型服务后可自动总结；未确认时只保存正文。全库问答和追加摘要也遵循此设置。')+'</p><button type="button" id="company-data-review" class="secondary">'+t('确认模型并总结')+'</button></section>';
 }
 function bind(item,{api,toast,onSaved}){
  const mark=document.querySelector('#company-data-mark');
  if(mark)mark.onclick=async()=>{try{await api('/api/items/'+item.id+'/company-data',{});await onSaved()}catch(e){toast(e.message)}};
  const button=document.querySelector('#company-data-review');
  if(button)button.onclick=async()=>{button.disabled=true;try{const status=await api('/api/status');if(status.company_model.enabled&&!status.company_model.approved&&!await review(api,status.company_model))return;await api('/api/items/'+item.id,{});toast(t('已加入整理队列'));await onSaved()}catch(e){toast(e.message)}finally{button.disabled=false}};
 }
 function sync(info,revision=modeRevision){
  if(!info||modeChanging||revision!==modeRevision)return;enabled=info.enabled===true;
  document.querySelector('#company-mode').checked=enabled;
  document.querySelector('#company-mode').setAttribute('aria-checked',String(enabled));
  document.querySelector('#company-mode-controls').hidden=!enabled;
  const target=document.querySelector('#company-model-status');if(!target||!info)return;
  target.textContent=(info.approved?t('已确认用于公司资料：'):t('公司资料的模型服务尚未确认：'))+t(info.destination)+' · '+t(info.model);
  document.querySelector('#company-model-revoke').hidden=!info.approved;
 }
 function setup(config){
  document.querySelector('#company-mode').onchange=async event=>{const control=event.target,value=control.checked,revision=++modeRevision;modeChanging=true;control.disabled=true;try{const data=await config.api('/api/company-mode',{enabled:value});modeChanging=false;sync(data.company_model,revision);await config.reload();await config.onModeChanged?.()}catch(e){modeChanging=false;control.checked=enabled;config.toast(e.message)}finally{modeChanging=false;control.disabled=false}};
  document.querySelector('#company-model-review').onclick=async()=>{try{const status=await config.api('/api/status');if(await review(config.api,status.company_model)){await config.reload();config.toast(t('已确认，后续公司资料可按设置自动总结。'))}}catch(e){config.toast(e.message)}};
  document.querySelector('#company-model-revoke').onclick=async()=>{try{await config.api('/api/company-model/revoke',{});await config.reload();config.toast(t('已撤销公司资料的模型服务确认。'))}catch(e){config.toast(e.message)}};
 }
 globalThis.StellarCompanyAI={confirm,review,render,bind,sync,setup,revision:()=>modeRevision};
})();
