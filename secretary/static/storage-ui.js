/* A preview is mandatory; no cleanup target is selected automatically. */
(()=>{
 let api,toast,dialog,plan,busy=false;const t=s=>StellarI18n.t(s),names={originals:'原件',backups:'本机备份',deleted_attachments:'已删附件恢复副本',uploads:'上传暂存',working_files:'编辑工作文件',video_cache:'视频缓存',database:'数据库',other:'其他本机文件'};
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
   <button type="button" class="danger" data-storage-clean disabled>${t('清理所选项目')}</button>`;
  document.body.append(dialog);
  field('[data-storage-refresh]').onclick=load;
  field('[data-storage-clean]').onclick=clean;
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
   target.append(label);
  }
  status.textContent=t(plan.items.length?'预览有效期 10 分钟；清理恢复副本后将无法撤销该附件删除。':'没有可清理的过期上传、恢复副本或旧备份。');
 }
 async function load(){
  if(busy)return;
  busy=true;
  try{await scan()}
  catch(error){field('[data-storage-status]').textContent=error.message}
  finally{busy=false;selection()}
 }
 async function clean(){
  if(busy)return;
  const ids=selection();
  if(!ids.length||!confirm(t('确定清理所选项目？选中的恢复副本和旧备份将被永久移除。')))return;
  busy=true;selection();
  try{
   const result=await api('/api/storage/clean',{token:plan.token,ids,confirmed:true});
   toast(t('已清理项目：')+result.removed.length+(result.failed.length?' · '+t('部分文件被占用，未能清理：')+result.failed.join(', '):''));
   await scan();
  }catch(error){field('[data-storage-status]').textContent=error.message}
  finally{busy=false;selection()}
 }
 globalThis.StellarStorage={bind(options){({api,toast}=options);document.querySelector('#storage-open').onclick=()=>{create();dialog.showModal();void load()}}};
})();
