/* Quick-note file input appends originals; note text remains independent. */
(()=>{
 const states=new Map(),t=s=>StellarI18n.t(s);
 const image=file=>(file.type||'').startsWith('image/')||/\.(png|jpe?g|gif|webp|heic|heif|hif)$/i.test(file.name);
 const pending=id=>{const state=states.get(id);return !!state&&(state.running||state.files.length>0)};
 function bind(id,config){
  let state=states.get(id);if(!state){state={id,files:[],running:false,error:'',message:'',deleted:false};states.set(id,state)}
  state.config=config;
  const container=document.querySelector('.quick-note'),panel=container.querySelector('#note-attachment-status');container.dataset.noteItem=id;
  function paint(){if(!panel.isConnected)return;panel.replaceChildren();if(!state.files.length&&!state.message)return;
   const line=document.createElement('p');line.className=state.error?'warning':'muted';line.textContent=state.error?t('附件追加失败，待重试：')+state.error:state.message;panel.append(line);
   if(state.files.length){const names=document.createElement('p');names.className='muted';names.textContent=state.files.map(file=>file.name).join(' · ');panel.append(names)}
   if(state.error){for(const [label,action]of [[t('重试追加'),()=>void start()],[t('移除待追加附件'),()=>{StellarUploads.abandon(state.files);state.files=[];state.error='';state.message='';paint()}]]){const button=document.createElement('button');button.type='button';button.className='secondary';button.textContent=label;button.onclick=action;panel.append(button)}}
  }
  state.paint=paint;
  async function start(){
   if(state.running||!state.files.length||state.deleted)return;state.running=true;state.error='';state.message=t('正在追加附件…');state.paint();
   try{while(state.files.length&&!state.deleted){
    const files=state.files.slice(),attachments=[];
    try{
     for(const file of files)attachments.push(await StellarUploads.encode(file,(name,percent)=>{state.message=t('正在上传：')+name+' '+percent+'%';state.paint()},'quick-note:'+id));
     if(state.deleted)return;
     const latest=await config.api('/api/items/'+id);
     await config.api('/api/items/'+id+'/additions',{text:'',attachments,expected_updated:latest.updated,summarize:false,read_links:false});
    }catch(error){StellarUploads.abandon(files);state.error=error.message;return}
    state.files.splice(0,files.length);state.message=t('附件已追加到全部附件');state.paint();
    await StellarUploads.cleanup(attachments).catch(()=>{});
    try{await state.config.onSaved()}catch(error){config.toast(error.message)}
   }}finally{state.running=false;state.paint()}
  }
  function add(files){
   files=Array.from(files);if(!files.length||state.deleted)return;
   const all=[...state.files,...files];
   if(all.length>20||all.filter(image).length>8||all.some(file=>file.size>1024**3)||all.reduce((n,file)=>n+file.size,0)>2*1024**3){config.toast(t('每批最多 20 个文件、8 张图片，单个 1 GB、总计 2 GB'));return}
   state.files.push(...files);state.paint();if(!state.error)void start();
  }
  container.querySelector('#note-add-image').onclick=()=>container.querySelector('#note-file').click();
  container.querySelector('#note-file').onchange=event=>{add(event.target.files);event.target.value=''};
  container.ondragover=event=>{if(Array.from(event.dataTransfer.types).includes('Files')){event.preventDefault();event.stopPropagation()}};
  container.ondrop=event=>{if(event.dataTransfer.files.length){event.preventDefault();event.stopPropagation();add(event.dataTransfer.files)}};
  paint();return add;
 }
 function discard(id){const state=states.get(id);if(state){state.deleted=true;state.files=[];states.delete(id)}}
 addEventListener('beforeunload',event=>{if([...states.keys()].some(pending)){event.preventDefault();event.returnValue=''}});
 globalThis.StellarNoteAttachments={bind,pending,discard,hasPending:()=>[...states.keys()].some(pending)};
})();
