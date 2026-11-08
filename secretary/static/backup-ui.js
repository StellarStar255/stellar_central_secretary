/* Local backup state, settings and nonmodal failure notices. */
(()=>{
 const $=s=>document.querySelector(s),t=s=>StellarI18n.t(s);let api,toast,dirty=false,lastWarning='';
 function sync(status){if(!status)return;const line=$('#backup-status');if(line)line.textContent=(status.last_success?t('最近成功：')+new Date(status.last_success).toLocaleString():t('尚无成功备份'))+' · '+t('当前目录占用：')+((status.used_bytes||0)/1073741824).toFixed(2)+' / '+(status.max_bytes/1073741824).toFixed(1)+' GB'+(status.state==='creating'?' · '+t('正在备份…'):'');
  if(!dirty){if($('#backup-folder'))$('#backup-folder').value=status.folder;if($('#backup-limit'))$('#backup-limit').value=(status.max_bytes/1073741824).toFixed(1);if($('#backup-daily-keep'))$('#backup-daily-keep').value=status.daily_keep;if($('#backup-other-keep'))$('#backup-other-keep').value=status.other_keep}
  const failed=status.state==='error'&&status.last_error;$('#settings-open')?.setAttribute('data-backup-warning',String(Boolean(failed)));if($('#backup-error'))$('#backup-error').textContent=status.last_error||status.warning||'';
  const warning=failed?status.last_attempt+status.last_error:'';if(warning&&warning!==lastWarning){lastWarning=warning;try{if(localStorage.getItem('stellar-backup-notice')===warning)return;localStorage.setItem('stellar-backup-notice',warning)}catch{}toast?.(t('备份失败，已有备份保留：')+status.last_error)}
 }
 function bind(options){({api,toast}=options);for(const id of ['backup-folder','backup-limit','backup-daily-keep','backup-other-keep'])$('#'+id)?.addEventListener('input',()=>{dirty=true});$('#backup-configure').onclick=async()=>{const button=$('#backup-configure');button.disabled=true;try{const status=await api('/api/backups/configure',{folder:$('#backup-folder').value,max_bytes:Math.round(Number($('#backup-limit').value)*1073741824),daily_keep:Number($('#backup-daily-keep').value),other_keep:Number($('#backup-other-keep').value)});dirty=false;sync(status);toast(t('备份设置已保存，原目录备份仍可恢复。'))}catch(error){$('#backup-error').textContent=error.message}finally{button.disabled=false}}}
 globalThis.StellarBackups={bind,sync};
})();
