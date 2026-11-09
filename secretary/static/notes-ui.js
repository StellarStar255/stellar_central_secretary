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
   void globalThis.StellarDrafts?.read('note:'+item.id).then(cached=>{if(cached&&typeof cached.text==='string'&&!draft.dirty&&!draft.busy&&!draft.deleted){draft.text=cached.text;draft.version=cached.version;draft.images=cached.images||draft.images;draft.dirty=true;draft.revision++;draft.onRestore?.()}});
  }
  return draft;
 }
 function imageMarkup(draft){return draft.images.map((image,index)=>{const src=image.id?`/api/items/${draft.id}/note-images/${image.id}`:`data:${image.media};base64,${image.data}`;return `<div class="note-image"><button type="button" class="note-image-open" data-note-open="${index}" data-image-view title="${esc(t('查看图片：')+image.name)}" aria-label="${esc(t('查看图片：')+image.name)}"><img src="${esc(src)}" alt="${esc(image.name)}"></button><button type="button" data-note-remove="${index}" aria-label="${esc(t('删除图片：')+image.name)}">×</button></div>`}).join('')}
 function render(item){const draft=state(item);return ui`<section class="quick-note"><div class="note-heading"><h3>我的速记</h3><span id="note-status" role="status"></span></div><textarea id="note-text" maxlength="20000" rows="3" placeholder="记下自己的想法，也可以粘贴图片、视频或文件…">${esc(draft.text)}</textarea><div id="note-images" class="note-images">${imageMarkup(draft)}</div><div id="note-attachment-status" role="status"></div><div class="note-tools"><button type="button" id="note-add-image" class="secondary">＋ 添加附件</button><button type="button" id="note-save" class="secondary">保存速记</button><small>文字自动保存；粘贴文件直接追加到全部附件，不参与 AI 摘要</small></div><input id="note-file" type="file" multiple hidden></section>`}
 function bind(item,{api,toast,onSaved,onAttachmentsSaved}){
  const draft=state(item),container=document.querySelector('.quick-note');if(!container)return;
  const text=container.querySelector('#note-text'),status=container.querySelector('#note-status'),saveButton=container.querySelector('#note-save');
  const active=()=>document.querySelector('.quick-note')===container;
  function paint(){if(!active())return;status.textContent=draft.busy?t('正在保存…'):draft.error?t('保存失败：')+draft.error:draft.dirty?t('尚未保存'):t('已保存');status.classList.toggle('note-error',!!draft.error);saveButton.disabled=draft.busy}
  function cache(){if(draft.deleted)return;void globalThis.StellarDrafts?.cache('note:'+item.id,{text:draft.text,images:draft.images,version:draft.version});try{localStorage.setItem(storageKey(item.id),JSON.stringify({text:draft.text,version:draft.version}))}catch{}}
  function changed(){if(draft.deleted)return;draft.dirty=true;draft.error='';draft.revision++;cache();paint();clearTimeout(draft.timer);draft.timer=setTimeout(save,500)}
  function images(){if(!active())return;container.querySelector('#note-images').innerHTML=imageMarkup(draft);container.querySelectorAll('[data-note-remove]').forEach(button=>button.onclick=()=>{draft.images.splice(Number(button.dataset.noteRemove),1);images();changed()})}
  async function save(){
   clearTimeout(draft.timer);if(draft.deleted||draft.busy||!draft.dirty)return;draft.busy=true;draft.error='';paint();
   const revision=draft.revision,snapshot=draft.images.map(image=>({...image}));
   try{
    const result=await api('/api/items/'+item.id+'/notes',{text:draft.text,images:snapshot.map(image=>image.id?{id:image.id}:{name:image.name,data:image.data}),version:draft.version});
    if(draft.deleted)return;
    draft.version=result.item.note_version;
    snapshot.forEach((image,index)=>{const current=draft.images.findIndex(value=>value.key===image.key);if(current>=0)draft.images[current]={...result.item.note_images[index],key:image.key}});
    draft.dirty=draft.revision!==revision;
    if(!draft.dirty){void globalThis.StellarDrafts?.discard('note:'+item.id);try{localStorage.removeItem(storageKey(item.id))}catch{}}else cache();
    draft.renderImages?.();onSaved?.(result.item);
   }catch(error){draft.error=error.message}
   finally{draft.busy=false;if(!draft.deleted){draft.paint?.();if(draft.dirty&&!draft.error)draft.timer=setTimeout(save,500)}}
  }
  const addFiles=StellarNoteAttachments.bind(item.id,{api,toast,onSaved:onAttachmentsSaved});
  draft.paint=paint;draft.renderImages=images;draft.save=save;draft.onRestore=()=>{if(active()){text.value=draft.text;images();paint();draft.timer=setTimeout(save,500)}};
  text.onblur=()=>void save();
  text.oninput=()=>{draft.text=text.value;changed()};
  text.onkeydown=event=>{if(event.key==='Enter'&&(event.metaKey||event.ctrlKey)){event.preventDefault();void save()}if(event.key==='Escape'&&(draft.busy||draft.dirty)){event.preventDefault();event.stopPropagation();void save()}};
  text.onpaste=event=>{const clipboard=event.clipboardData;if(!clipboard)return;const files=clipboard.files?.length?[...clipboard.files]:Array.from(clipboard.items||[]).filter(item=>item.kind==='file').map(item=>item.getAsFile()).filter(Boolean);if(files.length){event.preventDefault();event.stopPropagation();const plain=clipboard.getData('text/plain');if(plain){text.setRangeText(plain,text.selectionStart,text.selectionEnd,'end');draft.text=text.value;changed()}addFiles(files)}};
  saveButton.onclick=()=>void save();images();paint();if(draft.dirty&&!draft.error)draft.timer=setTimeout(save,500);
 }
 addEventListener('blur',()=>{for(const draft of drafts.values())if(draft.dirty)void draft.save?.()});
 addEventListener('beforeunload',event=>{if(Array.from(drafts.values()).some(draft=>draft.dirty||draft.busy)){event.preventDefault();event.returnValue=''}});
 function discard(id){StellarNoteAttachments.discard(id);void globalThis.StellarDrafts?.discard('note:'+id);const draft=drafts.get(id);if(draft){draft.deleted=true;draft.dirty=false;clearTimeout(draft.timer);drafts.delete(id)}try{localStorage.removeItem(storageKey(id))}catch{}}
 async function flushAll(){for(const draft of drafts.values()){const deadline=Date.now()+10000;while((draft.dirty||draft.busy)&&!draft.deleted){if(draft.error)return false;if(!draft.busy)await draft.save?.();else await new Promise(resolve=>setTimeout(resolve,25));if(Date.now()>deadline)return false}}return true}
 async function cacheAll(){for(const draft of drafts.values())if((draft.dirty||draft.busy)&&!draft.deleted&&!await StellarDrafts.cache('note:'+draft.id,{text:draft.text,images:draft.images,version:draft.version}))return false;return true}
 globalThis.StellarNotes={render,bind,discard,flushAll,cacheAll,hasDirty:()=>StellarNoteAttachments.hasPending()||[...drafts.values()].some(d=>d.dirty||d.busy),isDirty:id=>{const draft=drafts.get(id);return StellarNoteAttachments.pending(id)||!!draft&&(draft.dirty||draft.busy)}};
})();
