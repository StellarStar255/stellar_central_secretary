/* Bounded chunks, verified resume and per-operation leases. Original files remain local. */
(()=>{
 let api=null,panel=null;const tasks=new Set(),CHUNK=4*1024*1024;const t=s=>StellarI18n.t(s);
 let owner;try{owner=sessionStorage.getItem('stellar-upload-owner');if(!owner){owner=crypto.randomUUID();sessionStorage.setItem('stellar-upload-owner',owner)}}catch{owner=String(Date.now())+Math.random()}
 function mount(task){if(!panel){panel=document.createElement('section');panel.id='upload-progress';panel.setAttribute('aria-label',t('附件上传'));const hint=document.createElement('p');hint.textContent=t('中断后重新选择原文件可继续；已上传部分会先核对。');panel.append(hint);document.body.append(panel)}const target=task.context.startsWith('append:')?document.querySelector('#append-dialog[open]'):null;if(target)target.append(panel);else if(!panel.closest('dialog[open]'))document.body.append(panel);
  const row=task.row=document.createElement('div');row.className='upload-progress-row';const label=task.label=document.createElement('span');const pause=task.pause=document.createElement('button'),cancel=task.cancel=document.createElement('button'),restart=task.restartButton=document.createElement('button');for(const button of [pause,cancel,restart])button.type='button';restart.textContent=t('重新开始');
  pause.onclick=()=>{if(task.state==='uploading'){task.state='paused';task.pausedAbort=true;task.controller?.abort()}else{task.state='uploading';task.wake?.()}paint(task)};
  cancel.onclick=()=>{task.state='cancelled';task.controller?.abort();task.wake?.();if(task.session)void api('/api/uploads/'+task.session.id+'/cancel',{lease:task.session.lease}).catch(()=>{});paint(task)};
  restart.onclick=()=>{task.restart=true;task.state='uploading';task.wake?.();paint(task)};row.append(label,pause,cancel,restart);panel.append(row);paint(task)
 }
 function paint(task){const labels={uploading:'上传中',paused:'已暂停',failed:'等待继续',complete:'已上传，待归档',staged:'已暂存，可重新发送',cancelled:'已取消'};task.label.textContent=task.file.name+' · '+t(labels[task.state])+' '+task.percent+'%'+(task.error?' · '+task.error:'');task.pause.textContent=t(task.state==='uploading'?'暂停':'继续');task.pause.disabled=['complete','staged','cancelled'].includes(task.state);task.cancel.textContent=t(task.state==='cancelled'?'移除':'取消');task.cancel.disabled=task.state==='complete';if(task.state==='cancelled')task.cancel.onclick=()=>{task.row.remove();tasks.delete(task);if(!tasks.size){panel.remove();panel=null}};task.restartButton.hidden=task.state!=='failed'}
 async function wait(task){await new Promise(resolve=>{task.wake=resolve});task.wake=null;if(task.state==='cancelled')throw Error(t('上传已取消，原文件已保留'))}
 async function raw(task,suffix,offset,blob){const status=await api('/api/status');if(task.state==='cancelled')throw Error(t('上传已取消，原文件已保留'));if(task.state==='paused')await wait(task);task.controller=new AbortController();const response=await fetch('/api/uploads/'+task.session.id+'/'+suffix,{method:'POST',headers:{'Content-Type':'application/octet-stream','X-Knowledge-Token':status.token,'X-Upload-Offset':String(offset),'X-Upload-Lease':task.session.lease||''},body:blob,signal:task.controller.signal});const value=await response.json();if(!response.ok)throw Error(value.error||t('上传失败'));return value}
 async function verify(task){const state=await api('/api/uploads/'+task.session.id+'/status',{lease:task.session.lease}),keys=Object.keys(state.chunks||{}).map(Number).sort((a,b)=>a-b);if(state.offset&&keys[0]!==0)throw Error(t('上传校验记录缺失，请重新开始'));
  for(let index=0;index<keys.length;index++){if(task.state==='cancelled')throw Error(t('上传已取消，原文件已保留'));if(task.state==='paused')await wait(task);const offset=keys[index],end=index+1<keys.length?keys[index+1]:state.offset,blob=task.file.slice(offset,end);
   if(globalThis.crypto?.subtle){const digest=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',await blob.arrayBuffer()))).map(value=>value.toString(16).padStart(2,'0')).join('');if(digest!==state.chunks[String(offset)])throw Error(t('所选文件与已上传部分不同，请重新开始'))}else await raw(task,'verify',offset,blob)
  }return state.offset
 }
 async function encode(file,onProgress=()=>{},context='composer'){
  if(file.size<=8*1024*1024)return {name:file.name,data:await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(String(reader.result).split(',')[1]);reader.onerror=()=>reject(Error(t('无法读取 ')+file.name));reader.readAsDataURL(file)})};
  for(const previous of [...tasks])if(previous.file===file&&previous.context===context){previous.row.remove();tasks.delete(previous)}
  const task={file,context,state:'uploading',percent:0,error:'',session:null,restart:false};tasks.add(task);mount(task);
  while(true){
   try{
    if(task.state==='cancelled')throw Error(t('上传已取消，原文件已保留'));
    if(task.restart&&task.session)await api('/api/uploads/'+task.session.id+'/cancel',{lease:task.session.lease}).catch(()=>{});
    task.session=await api('/api/uploads/start',{name:file.name,size:file.size,fingerprint:JSON.stringify([file.name,file.size,file.lastModified]),owner:owner+':'+context,fresh:task.restart});task.restart=false;if(task.state==='cancelled')throw Error(t('上传已取消，原文件已保留'));
    let offset=await verify(task);task.error='';task.percent=Math.floor(offset/file.size*100);paint(task);onProgress(file.name,task.percent);
    while(offset<file.size){if(task.state==='cancelled')throw Error(t('上传已取消，原文件已保留'));if(task.state==='paused')await wait(task);if(task.restart)break;const result=await raw(task,'chunk',offset,file.slice(offset,offset+CHUNK));offset=result.offset;task.percent=Math.round(offset/file.size*100);paint(task);onProgress(file.name,task.percent)}
    if(task.restart)continue;if(task.state==='cancelled')throw Error(t('上传已取消，原文件已保留'));task.state='complete';paint(task);return {name:file.name,upload_id:task.session.id,lease:task.session.lease};
   }catch(error){if(task.state==='cancelled'){if(task.session)void api('/api/uploads/'+task.session.id+'/cancel',{lease:task.session.lease}).catch(()=>{});paint(task);throw Error(t('上传已取消，原文件已保留'))}if(error.name==='AbortError'&&task.pausedAbort){task.pausedAbort=false;if(task.state==='uploading')continue}if(task.state!=='paused'){task.state='failed';task.error=error.message}paint(task);await wait(task)}
  }
 }
 async function cleanup(files){const selected=files||[...tasks].filter(task=>task.state==='complete').map(task=>({upload_id:task.session.id,lease:task.session.lease}));for(const file of selected)if(file.upload_id){await api('/api/uploads/'+file.upload_id+'/cancel',{lease:file.lease}).catch(()=>{});for(const task of [...tasks])if(task.session?.id===file.upload_id&&task.session?.lease===file.lease){task.row.remove();tasks.delete(task)}}if(panel&&!tasks.size){panel.remove();panel=null}}
 function abandon(files){for(const task of tasks)if(files.includes(task.file)&&task.state==='complete'){task.state='staged';paint(task)}}
 document.addEventListener('close',event=>{if(event.target.id==='append-dialog'&&panel)document.body.append(panel)},true);
 globalThis.addEventListener?.('beforeunload',event=>{if([...tasks].some(task=>!['cancelled'].includes(task.state))){event.preventDefault();event.returnValue=''}});
 globalThis.StellarUploads={encode,cleanup,abandon,bind:fn=>{api=fn}};
})();
