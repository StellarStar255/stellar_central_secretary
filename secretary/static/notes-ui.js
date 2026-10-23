/* User-owned notes are saved independently from AI-generated content. */
(()=>{
 const drafts=new Map(),t=key=>StellarI18n.t(key),ui=(parts,...values)=>StellarI18n.ui(parts,...values);
 const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const storageKey=id=>'stellar-note-draft:'+id;
 function state(item){
  let draft=drafts.get(item.id);
  if(!draft||!draft.dirty&&!draft.busy&&draft.version!==item.note_version){
   draft={id:item.id,text:item.note||'',images:(item.note_images||[]).map(image=>({...image,key:image.id})),version:item.note_version,revision:0,dirty:false,busy:false,error:'',timer:null};
   try{const cached=JSON.parse(localStorage.getItem(storageKey(item.id))||'null');if(cached&&typeof cached.text==='string'&&cached.version===item.note_version&&cached.text!==draft.text){draft.text=cached.text;draft.dirty=true}}catch{}
   drafts.set(item.id,draft);
  }
  return draft;
 }
 function imageMarkup(draft){return draft.images.map((image,index)=>{const src=image.id?`/api/items/${draft.id}/note-images/${image.id}`:`data:${image.media};base64,${image.data}`;return `<div class="note-image">${image.id?`<a href="${src}" target="_blank" rel="noopener noreferrer">`:''}<img src="${esc(src)}" alt="${esc(image.name)}">${image.id?'</a>':''}<button type="button" data-note-remove="${index}" aria-label="${esc(t('删除图片：')+image.name)}">×</button></div>`}).join('')}
 function render(item){const draft=state(item);return ui`<section class="quick-note"><div class="note-heading"><h3>我的速记</h3><span id="note-status" role="status"></span></div><textarea id="note-text" maxlength="20000" rows="3" placeholder="记下自己的想法，也可以直接粘贴图片…">${esc(draft.text)}</textarea><div id="note-images" class="note-images">${imageMarkup(draft)}</div><div class="note-tools"><button type="button" id="note-add-image" class="secondary">＋ 添加图片</button><button type="button" id="note-save" class="secondary">保存速记</button><small>自动保存在本机，不参与 AI 摘要</small></div><input id="note-file" type="file" accept="image/png,image/jpeg,image/gif,image/webp" multiple hidden></section>`}
 function bind(item,{api,toast,onSaved}){
  const draft=state(item),container=document.querySelector('.quick-note');if(!container)return;
  const text=container.querySelector('#note-text'),status=container.querySelector('#note-status'),saveButton=container.querySelector('#note-save');
  const active=()=>document.querySelector('.quick-note')===container;
  function paint(){if(!active())return;status.textContent=draft.busy?t('正在保存…'):draft.error?t('保存失败：')+draft.error:draft.dirty?t('尚未保存'):t('已保存');status.classList.toggle('note-error',!!draft.error);saveButton.disabled=draft.busy}
  function cache(){try{localStorage.setItem(storageKey(item.id),JSON.stringify({text:draft.text,version:draft.version}))}catch{}}
  function changed(){draft.dirty=true;draft.error='';draft.revision++;cache();paint();clearTimeout(draft.timer);draft.timer=setTimeout(save,500)}
  function images(){if(!active())return;container.querySelector('#note-images').innerHTML=imageMarkup(draft);container.querySelectorAll('[data-note-remove]').forEach(button=>button.onclick=()=>{draft.images.splice(Number(button.dataset.noteRemove),1);images();changed()})}
  async function save(){
   clearTimeout(draft.timer);if(draft.busy||!draft.dirty)return;draft.busy=true;draft.error='';paint();
   const revision=draft.revision,snapshot=draft.images.map(image=>({...image}));
   try{
    const result=await api('/api/items/'+item.id+'/notes',{text:draft.text,images:snapshot.map(image=>image.id?{id:image.id}:{name:image.name,data:image.data}),version:draft.version});
    draft.version=result.item.note_version;
    snapshot.forEach((image,index)=>{const current=draft.images.findIndex(value=>value.key===image.key);if(current>=0)draft.images[current]={...result.item.note_images[index],key:image.key}});
    draft.dirty=draft.revision!==revision;
    if(!draft.dirty){try{localStorage.removeItem(storageKey(item.id))}catch{}}else cache();
    images();onSaved?.(result.item);
   }catch(error){draft.error=error.message}
   finally{draft.busy=false;paint();if(draft.dirty&&!draft.error)draft.timer=setTimeout(save,500)}
  }
  async function addFiles(files){
   try{
    if(draft.images.length+files.length>8)throw Error(t('每份速记最多添加 8 张图片。'));
    for(const file of files){
     if(file.size>5*1024*1024)throw Error(t('每张速记图片不能超过 5 MB。'));
     if(!['image/png','image/jpeg','image/gif','image/webp'].includes(file.type))throw Error(t('速记仅支持 PNG、JPEG、GIF 和 WebP 图片。'));
     const data=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result.split(',')[1]);reader.onerror=()=>reject(Error(t('无法读取图片')));reader.readAsDataURL(file)});
     draft.images.push({key:crypto.randomUUID(),name:file.name||'image.png',media:file.type,data});images();changed();
    }
   }catch(error){toast(error.message)}
  }
  draft.save=save;
  text.onblur=()=>void save();
  text.oninput=()=>{draft.text=text.value;changed()};
  text.onkeydown=event=>{if(event.key==='Enter'&&(event.metaKey||event.ctrlKey)){event.preventDefault();void save()}if(event.key==='Escape'&&(draft.busy||draft.dirty)){event.preventDefault();event.stopPropagation();void save()}};
  text.onpaste=event=>{const files=Array.from(event.clipboardData?.items||[]).filter(item=>item.kind==='file'&&item.type.startsWith('image/')).map(item=>item.getAsFile()).filter(Boolean);if(files.length){event.preventDefault();const plain=event.clipboardData.getData('text/plain');if(plain){text.setRangeText(plain,text.selectionStart,text.selectionEnd,'end');draft.text=text.value;changed()}void addFiles(files)}};
  container.ondragover=event=>{if(Array.from(event.dataTransfer.types).includes('Files'))event.preventDefault()};
  container.ondrop=event=>{if(event.dataTransfer.files.length){event.preventDefault();event.stopPropagation();void addFiles(Array.from(event.dataTransfer.files))}};
  container.querySelector('#note-add-image').onclick=()=>container.querySelector('#note-file').click();
  container.querySelector('#note-file').onchange=event=>{void addFiles(Array.from(event.target.files));event.target.value=''};
  saveButton.onclick=()=>void save();images();paint();if(draft.dirty&&!draft.error)draft.timer=setTimeout(save,500);
 }
 addEventListener('blur',()=>{for(const draft of drafts.values())if(draft.dirty)void draft.save?.()});
 addEventListener('beforeunload',event=>{if(Array.from(drafts.values()).some(draft=>draft.dirty||draft.busy)){event.preventDefault();event.returnValue=''}});
 globalThis.StellarNotes={render,bind,isDirty:id=>{const draft=drafts.get(id);return !!draft&&(draft.dirty||draft.busy)}};
})();
