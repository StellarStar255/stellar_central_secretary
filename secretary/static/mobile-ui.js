/* Local controls only: QR secrets and approvals never leave the desktop UI. */
(()=>{
 const $=s=>document.querySelector(s),t=k=>StellarI18n.t(k),esc=v=>String(v).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));let api,working=false,expiry=0,endpoint='',inviteEndpoint='',editingId='',deviceMarkup='';
 function deviceRow(device){
  const paired=new Date(device.created),pairedTime=device.created&&!Number.isNaN(paired.getTime())?paired.toLocaleString(StellarI18n.locale):'';
  const details=[device.nickname?device.name:'',pairedTime?t('配对时间')+' · '+pairedTime:''].filter(Boolean).join(' · ');
  return `<div class="mobile-device"><span class="mobile-device-name"><strong>${esc(device.nickname||device.name)}</strong>${details?`<small class="muted">${esc(details)}</small>`:''}</span><button class="secondary" data-rename="${esc(device.id)}">${esc(t('修改备注'))}</button><button class="secondary" data-revoke="${esc(device.id)}">${esc(t('移除设备'))}</button></div>`;
 }
 function endEdit(focus=false){
  const id=editingId;editingId='';$('#mobile-device-editor').hidden=true;
  if(focus)$('#mobile-devices').querySelector('[data-rename="'+CSS.escape(id)+'"]')?.focus();
 }
 function editDevice(device){
  if(!device)return;
  editingId=device.id;const editor=$('#mobile-device-editor'),input=$('#mobile-device-nickname');
  input.value=device.nickname||'';$('#mobile-device-edit-error').textContent='';editor.hidden=false;input.focus();input.select();
 }
 function render(data){
  endpoint=JSON.stringify([data.server_id,data.port,data.addresses]);if(expiry&&inviteEndpoint!==endpoint)expiry=1;
  $('#mobile-state').textContent=data.enabled?t('手机连接已开启'):t('手机连接已关闭');$('#mobile-enable').hidden=data.enabled;$('#mobile-disable').hidden=!data.enabled;$('#mobile-invite').hidden=!data.enabled;
  $('#mobile-address').textContent=data.enabled?(data.addresses.length?data.addresses.map(a=>'https://'+(a.includes(':')?'['+a+']':a)+':'+data.port).join(' · '):t('未找到局域网地址，请先连接 Wi-Fi')):'';
  $('#mobile-warning').textContent=data.error||'';
  $('#mobile-pending').innerHTML=data.pending.map(p=>`<div class="mobile-device"><strong>${esc(p.name)}</strong><p>${esc(t('请核对手机与电脑显示的数字一致：'))}<b>${esc(p.code)}</b></p><button class="primary" data-approve="${esc(p.id)}">${esc(t('允许配对'))}</button> <button class="secondary" data-reject="${esc(p.id)}">${esc(t('拒绝'))}</button></div>`).join('');
  const markup=data.devices.map(deviceRow).join('')||`<p>${esc(t('尚未配对手机'))}</p>`;
  if(markup!==deviceMarkup){$('#mobile-devices').innerHTML=markup;deviceMarkup=markup}
  $('#mobile-devices').querySelectorAll('[data-rename]').forEach(b=>b.onclick=()=>editDevice(data.devices.find(d=>d.id===b.dataset.rename)));
  $('#mobile-pending').querySelectorAll('[data-approve],[data-reject]').forEach(b=>b.onclick=()=>action(async()=>{render(await api('/api/mobile/decide',{id:b.dataset.approve||b.dataset.reject,approve:!!b.dataset.approve}));$('#mobile-qr').hidden=true}));
  $('#mobile-devices').querySelectorAll('[data-revoke]').forEach(b=>b.onclick=()=>action(async()=>render(await api('/api/mobile/revoke',{id:b.dataset.revoke}))));
  if(!data.enabled||expiry<Date.now()/1000){$('#mobile-qr').hidden=true;$('#mobile-qr-expiry').textContent=expiry&&data.enabled?t('二维码已失效，请刷新'):''}
 }
 async function action(fn){if(working)return;working=true;$('#mobile-warning').textContent='';try{await fn()}catch(e){$('#mobile-warning').textContent=e.message}finally{working=false}}
 async function invite(){render(await api('/api/mobile'));const result=await api('/api/mobile/invite',{});inviteEndpoint=endpoint;expiry=result.expires;$('#mobile-qr').src=result.qr;$('#mobile-qr').hidden=false;$('#mobile-qr-expiry').textContent=t('用 iPhone 配套 App 扫码，二维码 5 分钟内有效。')}
 function bind(options){({api}=options);$('#mobile-open').onclick=()=>action(async()=>{$('#mobile-dialog').showModal();render(await api('/api/mobile'))});$('#mobile-enable').onclick=()=>action(async()=>{render(await api('/api/mobile/enable',{}));await invite()});$('#mobile-disable').onclick=()=>action(async()=>{render(await api('/api/mobile/disable',{}));expiry=0});$('#mobile-invite').onclick=()=>action(invite);
  const editor=$('#mobile-device-editor');
  editor.onsubmit=event=>{
   event.preventDefault();if(!editingId)return;
   const id=editingId,nickname=$('#mobile-device-nickname').value;
   return action(async()=>{
    try{render(await api('/api/mobile/rename',{id,nickname}));if(editingId===id)endEdit(true)}
    catch(error){if(editingId===id)$('#mobile-device-edit-error').textContent=StellarI18n.message(error.message)}
   });
  };
  $('#mobile-device-cancel').onclick=()=>endEdit(true);
  $('#mobile-dialog').addEventListener('close',()=>endEdit());
  setInterval(()=>{if($('#mobile-dialog').open&&!working&&!editingId)action(async()=>render(await api('/api/mobile')))},2000);
 }
 globalThis.StellarMobile={bind};
})();
