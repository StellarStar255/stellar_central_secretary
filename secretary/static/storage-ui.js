/* A preview is mandatory; no cleanup target is selected automatically. */
(()=>{
 let api,dialog,confirmation,plan,pendingCleanup,busy=false;const t=s=>StellarI18n.t(s),names={originals:'原件',backups:'本机备份',deleted_attachments:'已删附件恢复副本',uploads:'上传暂存',working_files:'编辑工作文件',video_cache:'视频缓存',database:'数据库',other:'其他本机文件'};
 const field=selector=>dialog.querySelector(selector);
 const size=bytes=>(bytes/1048576).toFixed(2)+' MB';
 function create(){
  if(dialog)return;
  dialog=document.createElement('dialog');
  dialog.id='storage-dialog';
  dialog.innerHTML=`<form method="dialog" class="dialog-head"><h2>${t('存储空间与清理')}</h2><button type="submit" class="icon-button">×</button></form>
   <p class="muted">${t('先选择明细再清理。原件、数据库和编辑工作文件不会列为清理对象；每个备份目录至少保留最新一份备份。')}</p>
   <div data-storage-overview></div><p role="status" data-storage-status></p>
   <button type="button" class="secondary" data-storage-select-all aria-controls="storage-candidates" hidden>${t('全选')}</button>
   <div id="storage-candidates" data-storage-items></div><p data-storage-selected></p>
   <button type="button" class="secondary" data-storage-refresh>${t('重新扫描')}</button>
   <button type="button" class="secondary" data-storage-clean disabled>${t('清理所选项目')}</button>
   <p role="status" data-storage-result hidden></p>`;
  confirmation=document.createElement('dialog');
  confirmation.id='storage-confirm-dialog';
  confirmation.setAttribute('aria-labelledby','storage-confirm-title');
  confirmation.setAttribute('aria-describedby','storage-confirm-details');
  confirmation.innerHTML=`<h2 id="storage-confirm-title">${t('确认清理')}</h2>
   <p data-storage-confirm-selection></p>
   <p id="storage-confirm-details">${t('所选项目将被永久移除。')}</p>
   <form method="dialog">
    <button class="secondary" value="cancel" autofocus>${t('取消')}</button>
    <button class="danger-button" value="clean">${t('确认清理')}</button>
   </form>`;
  document.body.append(dialog,confirmation);
  confirmation.addEventListener('close',()=>{
   const request=pendingCleanup;
   pendingCleanup=null;
   if(confirmation.returnValue==='clean'&&request&&dialog.open)void clean(request);
  });
  field('[data-storage-refresh]').onclick=load;
  field('[data-storage-clean]').onclick=confirmCleanup;
  field('[data-storage-items]').onchange=selection;
  field('[data-storage-select-all]').onclick=()=>{
   const boxes=dialog.querySelectorAll('[data-storage-id]');
   const checked=Array.from(boxes).some(box=>!box.checked);
   for(const box of boxes)box.checked=checked;
   selection();
  };
 }
 function overview(data){const target=dialog.querySelector('[data-storage-overview]');target.replaceChildren();for(const [key,value] of Object.entries(data.groups)){const row=document.createElement('p');row.textContent=t(names[key])+' · '+size(value.bytes)+' · '+value.files;target.append(row)}}
 function selection(){
  const boxes=dialog.querySelectorAll('[data-storage-id]'),ids=new Set();
  for(const box of boxes){
   box.disabled=busy;
   if(box.checked)ids.add(box.dataset.storageId);
  }
  const bytes=plan?.items.reduce((sum,item)=>sum+(ids.has(item.id)?item.bytes:0),0)||0;
  field('[data-storage-selected]').textContent=t('已选项目：')+ids.size+' · '+size(bytes);
  const selectAll=field('[data-storage-select-all]');
  selectAll.hidden=!boxes.length;
  selectAll.disabled=busy;
  selectAll.textContent=t(boxes.length&&ids.size===boxes.length?'取消全选':'全选');
  field('[data-storage-clean]').disabled=busy||!ids.size;
  field('[data-storage-refresh]').disabled=busy;
  return [...ids];
 }
 async function scan(){
  const status=field('[data-storage-status]'),target=field('[data-storage-items]');
  plan=null;
  target.replaceChildren();
  selection();
  status.textContent=t('正在扫描存储空间…');
  plan=await api('/api/storage/preview',{});
  overview(plan.overview);
  for(const item of plan.items){
   const label=document.createElement('label'),box=document.createElement('input');
   label.className='check';
   box.type='checkbox';
   box.dataset.storageId=item.id;
   label.append(box,document.createTextNode(t(names[item.kind])+' · '+item.name+' · '+size(item.bytes)));
   if(item.backup_folder){
    const row=document.createElement('div'),details=document.createElement('details');
    const summary=document.createElement('summary'),path=document.createElement('span');
    summary.textContent=t(item.current_folder?'当前备份目录':'旧备份目录');
    path.textContent=item.backup_folder;
    details.className='cleanup-backup-location';
    details.append(summary,path);
    box.setAttribute('aria-label',label.textContent+' · '+summary.textContent+' · '+item.backup_folder);
    row.append(label,details);
    target.append(row);
   }else target.append(label);
  }
  status.textContent=t(plan.items.length?'预览有效期 10 分钟；清理恢复副本后将无法撤销该附件删除。':'没有可清理的过期上传、恢复副本或旧备份。');
 }
 async function load(){
  if(busy)return;
  busy=true;
  field('[data-storage-result]').hidden=true;
  try{await scan()}
  catch(error){field('[data-storage-status]').textContent=error.message}
  finally{busy=false;selection()}
 }
 function confirmCleanup(){
  if(busy||!plan||pendingCleanup)return;
  const ids=selection();
  if(!ids.length)return;
  pendingCleanup={token:plan.token,ids,confirmed:true};
  confirmation.querySelector('[data-storage-confirm-selection]').textContent=field('[data-storage-selected]').textContent;
  confirmation.returnValue='';
  confirmation.showModal();
 }
 async function clean(request){
  busy=true;selection();
  const feedback=field('[data-storage-result]');
  feedback.hidden=false;
  feedback.textContent=t('正在清理所选项目…');
  try{
   const result=await api('/api/storage/clean',request);
   feedback.textContent=t('已清理项目：')+result.removed.length+(result.failed.length?' · '+t('部分文件被占用，未能清理：')+result.failed.join(', '):'');
   try{await scan()}
   catch(error){field('[data-storage-status]').textContent=error.message}
  }catch(error){feedback.textContent=error.message}
  finally{busy=false;selection()}
 }
 globalThis.StellarStorage={bind(options){({api}=options);document.querySelector('#storage-open').onclick=()=>{create();dialog.showModal();void load()}}};
})();
