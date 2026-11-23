/* Local backup state, settings and nonmodal failure notices. */
(()=>{
 const $=s=>document.querySelector(s),t=s=>StellarI18n.t(s);let api,toast,dirty=new Set(),lastWarning='',configRevision=-1,stateRevision=-1,saving=false;
 let backupFolder='',creating=false,locationTimer,locationRevision=0,locationReady=false,pendingFolder='';
 let migrationResult,dismissedMigration;
 try{dismissedMigration=localStorage.getItem('stellar-library-migration-dismissed')}catch{}
 function backupButtons(){
  $('#backup-configure').disabled=saving||creating;
  $('#backup-create').disabled=saving||creating||!backupFolder||dirty.has('backup-folder');
  $('#backup-folder-open').disabled=saving||!backupFolder||dirty.has('backup-folder');
 }
 function showBackupError(message){
  const line=$('#backup-error');
  const text=(message||'').trim();
  line.textContent=text;
  line.hidden=!text;
 }
 function sync(status){if(!status)return;const version=status.config_revision||0,revision=status.state_revision||0;if(version<configRevision||version===configRevision&&revision<stateRevision)return;if(version>configRevision)stateRevision=-1;configRevision=version;stateRevision=revision;const line=$('#backup-status');if(line)line.textContent=(status.last_success?t('最近成功：')+new Date(status.last_success).toLocaleString():t(status.folder_available===false?'当前备份目录不可用。':status.snapshot_count===0?'此目录尚无备份':'尚无成功备份'))+' · '+t('当前目录占用：')+((status.used_bytes||0)/1073741824).toFixed(2)+' / '+(status.max_bytes/1073741824).toFixed(1)+' GB'+(status.state==='creating'?' · '+t('正在备份…'):'');
  backupFolder=status.folder;backupButtons();
  if(line&&status.last_verification){const check=status.last_verification;line.textContent+=' · '+t(check.state==='verified'?'最近验证通过：':check.state==='checking'?'正在验证备份…':'最近验证失败：')+(check.state==='checking'?'':new Date(check.checked_at).toLocaleString())}
  for(const [id,value] of Object.entries({'backup-folder':status.folder,'backup-limit':(status.max_bytes/1073741824).toFixed(1),'backup-daily-keep':status.daily_keep,'backup-other-keep':status.other_keep}))if(!dirty.has(id)&&$('#'+id))$('#'+id).value=value;
  $('#backup-folder').title=$('#backup-folder').value;
  const verificationError=status.last_verification?.state==='failed'?status.last_verification.error:'';const failed=status.state==='error'&&status.last_error||verificationError;$('#settings-open')?.setAttribute('data-backup-warning',String(Boolean(failed)));showBackupError(status.last_error||verificationError||status.warning);
  const warning=failed?(verificationError?status.last_verification.checked_at+verificationError:status.last_attempt+status.last_error):'';if(warning&&warning!==lastWarning){lastWarning=warning;try{if(localStorage.getItem('stellar-backup-notice')===warning)return;localStorage.setItem('stellar-backup-notice',warning)}catch{}toast?.(t(verificationError?'备份检查失败，当前资料未修改：':'备份失败，已有备份保留：')+(verificationError||status.last_error))}
 }
 function syncLocation(location){
  const line=$('#library-location-status');
  if(!location||!line)return;
  pendingFolder=location.pending||'';
  $('#library-restart-actions').hidden=!pendingFolder;
  migrationResult=location.result;
  const migrated=migrationResult?.state==='completed';
  const resultText=migrated?t('记忆已迁移到：')+migrationResult.folder:
   migrationResult?.state==='failed'?t('记忆迁移失败。当前仍在使用：')+migrationResult.folder+' · '+t(migrationResult.error):'';
  line.textContent=resultText||(location.error?t('记忆迁移失败，仍在使用原目录：')+t(location.error):location.pending?t('重启后将迁移记忆至：')+location.pending:'');
  $('#library-migration-notice').hidden=!resultText||migrationResult.id===dismissedMigration;
  $('#library-migration-open').hidden=!migrated;
  const message=$('#library-migration-message');
  if(message.textContent!==resultText)message.textContent=resultText;
 }
 function size(bytes){
  if(bytes==null)return t('无法检查');
  const units=['B','KB','MB','GB','TB'];
  let unit=0;
  while(bytes>=1024&&unit<units.length-1){bytes/=1024;unit++}
  return new Intl.NumberFormat(undefined,{maximumFractionDigits:1}).format(bytes)+' '+units[unit];
 }
 function queueLocationCheck(delay){
  clearTimeout(locationTimer);
  const revision=++locationRevision,field=$('#library-folder'),line=$('#library-location-preflight');
  const folder=field.value.trim(),save=$('#library-location-save');
  locationReady=false;
  save.disabled=true;
  save.hidden=!folder;
  line.textContent=folder?t('正在检查迁移目录…'):'';
  if(!folder)return;
  locationTimer=setTimeout(async()=>{
   try{
    const result=await api('/api/library-location/check',{folder});
    if(revision!==locationRevision)return;
    const empty=result.empty==null?'无法检查':result.empty?'目标文件夹为空':'目标文件夹非空';
    const writable=result.writable==null?'无法检查':result.writable?'目标文件夹可写':'目标文件夹不可写。';
    line.textContent=[t('预计迁移大小：')+size(result.estimated_bytes),t('目标磁盘可用：')+size(result.free_bytes),...new Set([t(empty),t(writable),result.error?t(result.error):t('目录检查通过，可以保存。')])].join(' · ');
    locationReady=!result.error;
    save.disabled=field.disabled||!locationReady;
   }catch(error){
    if(revision===locationRevision)line.textContent=error.message;
   }
  },delay);
 }
 function showLocationEditor(open){
  const change=$('#library-location-change'),field=$('#library-folder');
  $('#library-location-editor').hidden=!open;
  change.setAttribute('aria-expanded',String(open));
  if(open)field.focus();
  else{
   field.value='';
   queueLocationCheck(0);
   change.focus();
  }
 }
 async function saveLocation(folder){
  const save=$('#library-location-save');
  const controls=['library-location-change','library-location-cancel','library-location-restart','library-location-discard','library-folder','library-folder-browse'];
  $('#library-restart-status').textContent='';
  save.disabled=true;
  for(const id of controls)$('#'+id).disabled=true;
  try{
   const location=await api('/api/library-location',{folder});
   syncLocation(location);
   if(folder)showLocationEditor(false);
  }catch(error){
   if(folder)$('#library-location-preflight').textContent=error.message;
   else toast(error.message);
  }
  finally{
   for(const id of controls)$('#'+id).disabled=false;
   save.disabled=!locationReady;
   if($('#library-location-editor').hidden)$('#library-location-change').focus();
  }
 }
 async function browse(purpose,button){
  button.disabled=true;
  try{
   const {folder}=await api('/api/directory-picker',{purpose});
   if(folder){
    const id=purpose+'-folder';
    $('#'+id).value=folder;
    if(purpose==='backup'){$('#'+id).title=folder;dirty.add(id);backupButtons();$('#backup-create-result').textContent=t('请先保存新的备份目录。')}
    else queueLocationCheck(0);
   }
  }catch(error){toast(error.message)}
  finally{button.disabled=false}
 }
 async function browseLibrary(){
  const browseButton=$('#library-folder-browse'),field=$('#library-folder'),
        save=$('#library-location-save'),cancel=$('#library-location-cancel'),
        change=$('#library-location-change'),discard=$('#library-location-discard'),restart=$('#library-location-restart');
  change.disabled=discard.disabled=cancel.disabled=restart.disabled=field.disabled=save.disabled=true;
  try{await browse('library',browseButton)}
  finally{
   change.disabled=discard.disabled=cancel.disabled=restart.disabled=field.disabled=false;
   save.disabled=!locationReady;
   if($('#settings-dialog').open)field.focus();
  }
 }
 async function restartLibrary(prepare){
  const folder=pendingFolder,line=$('#library-restart-status');
  const controls=['library-location-change','library-location-cancel','library-location-restart'];
  for(const id of controls)$('#'+id).disabled=true;
  try{
   if(!await prepare())return;
   const current=await api('/api/status');
   await api('/api/library-location/restart',{folder});
   line.textContent=t('正在重启并迁移记忆…');
   for(let attempt=0;attempt<120;attempt++){
    await new Promise(resolve=>setTimeout(resolve,1000));
    try{
     const status=await api('/api/status');
     if(status.application===current.application&&status.token!==current.token){
      location.reload();return;
     }
    }catch{}
   }
   line.textContent=t('仍在等待程序启动。迁移完成后请重新打开窗口。');
  }catch(error){line.textContent=error.message}
  finally{for(const id of controls)$('#'+id).disabled=false}
 }
 async function openFolder(purpose,button,folder){
  button.disabled=true;
  try{await api('/api/data-directory/open',{purpose,folder})}
  catch(error){toast(error.message)}
  finally{
   if(purpose==='backup')backupButtons();
   else button.disabled=false;
  }
 }
 function bind(options){({api,toast}=options);
  const backupBrowse=$('#backup-folder-browse');
  backupBrowse.onclick=()=>void browse('backup',backupBrowse);
  $('#library-location-change').onclick=()=>{
   if(!$('#library-location-editor').hidden){showLocationEditor(false);return}
   showLocationEditor(true);
   void browseLibrary();
  };
  $('#library-folder-browse').onclick=()=>void browseLibrary();
  $('#library-location-discard').onclick=()=>showLocationEditor(false);
  $('#library-folder').addEventListener('input',()=>queueLocationCheck(400));
  $('#library-location-save').onclick=()=>void saveLocation($('#library-folder').value.trim());
  $('#library-location-cancel').onclick=()=>void saveLocation('');
  $('#library-location-restart').onclick=()=>void restartLibrary(options.prepareRestart);
  for(const purpose of ['library','backup']){
   const button=$('#'+purpose+'-folder-open');
   button.onclick=()=>void openFolder(purpose,button);
  }
  const openMigrated=$('#library-migration-open');
  openMigrated.onclick=()=>void openFolder('library',openMigrated,migrationResult.folder);
  $('#library-migration-dismiss').onclick=()=>{
   dismissedMigration=migrationResult.id;
   $('#library-migration-notice').hidden=true;
   try{localStorage.setItem('stellar-library-migration-dismissed',dismissedMigration)}catch{}
  };
  const result=$('#backup-create-result');
  for(const id of ['backup-folder','backup-limit','backup-daily-keep','backup-other-keep'])$('#'+id).addEventListener('input',()=>{
   dirty.add(id);
   if(id==='backup-folder'){$('#'+id).title=$('#'+id).value;backupButtons();result.textContent=t('请先保存新的备份目录。')}
  });
  $('#backup-configure').onclick=async()=>{
   const folder=$('#backup-folder').value, fields=['backup-folder','backup-folder-browse','backup-limit','backup-daily-keep','backup-other-keep'];
   saving=true;backupButtons();
   for(const id of fields)$('#'+id).disabled=true;
   try{
    const status=await api('/api/backups/configure',{folder,max_bytes:Math.round(Number($('#backup-limit').value)*1073741824),daily_keep:Number($('#backup-daily-keep').value),other_keep:Number($('#backup-other-keep').value)});
    dirty.clear();sync(status);
    result.textContent=t('已保存备份目录：')+status.folder;
    toast(t('备份设置已保存，原目录备份仍可恢复。'));
   }catch(error){showBackupError(error.message)}
   finally{
    saving=false;backupButtons();
    for(const id of fields)$('#'+id).disabled=false;
   }
  };
  $('#backup-create').onclick=async()=>{
   creating=true;backupButtons();
   result.textContent=t('正在创建并验证备份…');
   try{
    const snapshot=await api('/api/backups/create',{folder:backupFolder});
    result.textContent=t('备份已写入并通过验证：')+snapshot.folder;
   }catch(error){result.textContent=error.message}
   finally{
    try{await options.localBackupList()}catch{}
    creating=false;backupButtons();
   }
  };
 }
 globalThis.StellarBackups={bind,sync,syncLocation};
})();
