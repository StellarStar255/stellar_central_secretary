/* Local controls only: QR secrets and approvals never leave the desktop UI. */
(()=>{
 const $=s=>document.querySelector(s),t=k=>StellarI18n.t(k),esc=v=>String(v).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));let api,toast,working=false,expiry=0;
 function render(data){
  $('#mobile-state').textContent=data.enabled?t('手机连接已开启'):t('手机连接已关闭');$('#mobile-enable').hidden=data.enabled;$('#mobile-disable').hidden=!data.enabled;$('#mobile-invite').hidden=!data.enabled;
  $('#mobile-address').textContent=data.enabled?(data.addresses.length?data.addresses.map(a=>'https://'+a+':'+data.port).join(' · '):t('未找到局域网地址，请先连接 Wi-Fi')):'';
  $('#mobile-warning').textContent=data.error||'';
  $('#mobile-pending').innerHTML=data.pending.map(p=>`<div class="mobile-device"><strong>${esc(p.name)}</strong><p>${esc(t('请核对手机与电脑显示的数字一致：'))}<b>${esc(p.code)}</b></p><button class="primary" data-approve="${esc(p.id)}">${esc(t('允许配对'))}</button> <button class="secondary" data-reject="${esc(p.id)}">${esc(t('拒绝'))}</button></div>`).join('');
  $('#mobile-devices').innerHTML=data.devices.map(d=>`<div class="mobile-device"><span>${esc(d.name)}</span><button class="secondary" data-revoke="${esc(d.id)}">${esc(t('移除设备'))}</button></div>`).join('')||`<p>${esc(t('尚未配对手机'))}</p>`;
  $('#mobile-pending').querySelectorAll('[data-approve],[data-reject]').forEach(b=>b.onclick=()=>action(async()=>{render(await api('/api/mobile/decide',{id:b.dataset.approve||b.dataset.reject,approve:!!b.dataset.approve}));$('#mobile-qr').hidden=true}));
  $('#mobile-devices').querySelectorAll('[data-revoke]').forEach(b=>b.onclick=()=>action(async()=>render(await api('/api/mobile/revoke',{id:b.dataset.revoke}))));
  if(!data.enabled||expiry<Date.now()/1000){$('#mobile-qr').hidden=true;$('#mobile-qr-expiry').textContent=expiry&&data.enabled?t('二维码已失效，请刷新'):''}
 }
 async function action(fn){if(working)return;working=true;$('#mobile-warning').textContent='';try{await fn()}catch(e){$('#mobile-warning').textContent=e.message}finally{working=false}}
 async function invite(){const result=await api('/api/mobile/invite',{});expiry=result.expires;$('#mobile-qr').src=result.qr;$('#mobile-qr').hidden=false;$('#mobile-qr-expiry').textContent=t('用 iPhone 配套 App 扫码，二维码 5 分钟内有效。')}
 function bind(options){({api,toast}=options);$('#mobile-open').onclick=()=>action(async()=>{$('#mobile-dialog').showModal();render(await api('/api/mobile'))});$('#mobile-enable').onclick=()=>action(async()=>{render(await api('/api/mobile/enable',{}));await invite()});$('#mobile-disable').onclick=()=>action(async()=>{render(await api('/api/mobile/disable',{}));expiry=0});$('#mobile-invite').onclick=()=>action(invite);
 setInterval(()=>{if($('#mobile-dialog').open&&!working)action(async()=>render(await api('/api/mobile')))},2000);
 }
 globalThis.StellarMobile={bind};
})();
