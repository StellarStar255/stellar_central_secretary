/* Local recovery drafts and save-before-navigation. Explicit Cancel/Escape discard edits. */
(()=>{
 // Native Command-W follows modal opening order, including reused dialogs.
 const layers=[];
 for(const method of ['show','showModal']){
  const original=HTMLDialogElement.prototype[method];
  HTMLDialogElement.prototype[method]=function(...args){
   const wasOpen=this.open,result=original.apply(this,args);
   if(!wasOpen){const old=layers.indexOf(this);if(old>=0)layers.splice(old,1);layers.push(this)}
   return result;
  };
 }
 globalThis.StellarCloseTopLayer=()=>{
  for(let i=layers.length-1;i>=0;i--)if(!layers[i].open||!layers[i].isConnected)layers.splice(i,1);
  const dialog=layers.at(-1);if(!dialog)return false;
  if(dialog.matches('#detail-dialog,#library-dialog')&&globalThis.StellarDrafts?.isFlushing())return true;
  // Use the existing cancel guards, draft saving and player cleanup paths.
  if(dialog.dispatchEvent(new Event('cancel',{cancelable:true})))dialog.close();
  return true;
 };
 const forms=new Set(),pending=new Set();let flushing=null,replaying=false,dbPromise=null;
 const t=value=>StellarI18n.t(value),prefix='stellar-edit-draft:';
 function database(){return dbPromise??=new Promise(resolve=>{try{const request=indexedDB.open('stellar-local-drafts',1);request.onupgradeneeded=()=>request.result.createObjectStore('drafts');request.onsuccess=()=>resolve(request.result);request.onerror=()=>resolve(null)}catch{resolve(null)}})}
 async function read(key){try{const value=localStorage.getItem(prefix+key);if(value)return JSON.parse(value)}catch{}const db=await database();if(!db)return null;return new Promise(resolve=>{const request=db.transaction('drafts').objectStore('drafts').get(key);request.onsuccess=()=>resolve(request.result||null);request.onerror=()=>resolve(null)})}
 async function cache(key,value){
  const encoded=JSON.stringify(value);let local=false;try{if(encoded.length<200000){localStorage.setItem(prefix+key,encoded);local=true}else localStorage.removeItem(prefix+key)}catch{}
  const db=await database();if(!db)return local;
  const promise=new Promise(resolve=>{const transaction=db.transaction('drafts','readwrite');transaction.objectStore('drafts').put(value,key);transaction.oncomplete=()=>resolve(true);transaction.onerror=()=>resolve(local)});pending.add(promise);try{return await promise}finally{pending.delete(promise)}
 }
 async function discard(key){try{localStorage.removeItem(prefix+key)}catch{}const db=await database();if(db)await new Promise(resolve=>{const transaction=db.transaction('drafts','readwrite');transaction.objectStore('drafts').delete(key);transaction.oncomplete=transaction.onerror=()=>resolve()})}
 function status(form,message,error=false){let node=form.querySelector('.edit-save-status');if(!node){node=document.createElement('p');node.className='edit-save-status muted';node.setAttribute('role','status');form.append(node)}node.textContent=t(message);node.classList.toggle('warning',error)}
 function track(input,key){
  const draft=input._draft={key,base:input.value,revision:0};input.addEventListener('input',()=>{input._draft.revision++;void cache(key,{value:input.value,base:input._draft.base,updated:Date.now()});status(input.closest('[data-draft-form]')||input.parentElement,'尚未保存')});
  void read(key).then(saved=>{if(!saved||!input.isConnected||input._draft!==draft||draft.revision||input.value!==input._draft.base||typeof saved.value!=='string')return;if(saved.value===input.value){void discard(key);return}input.value=saved.value;input._draft.base=saved.base;status(input.closest('[data-draft-form]')||input.parentElement,'已恢复本机草稿，请核对后保存')});
 }
 function dirty(form){return !!form&&form.isConnected&&!form.hidden&&Boolean(form.closest('dialog')?.open)&&[...form.querySelectorAll('input,textarea')].some(input=>input._draft&&input.value!==input._draft.base)}
 function register(form,save){form.dataset.draftForm='true';form._flush=save;forms.add(form)}
 function saved(form){for(const input of form.querySelectorAll('input,textarea'))if(input._draft){input._draft.revision++;input._draft.base=input.value;void discard(input._draft.key)}status(form,'已保存')}
 function cancel(form){for(const input of form.querySelectorAll('input,textarea'))if(input._draft){input._draft.revision++;input.value=input._draft.base;void discard(input._draft.key)}}
 async function flush(){
  if(flushing)return flushing;
  flushing=(async()=>{for(const form of [...forms]){if(!form.isConnected){forms.delete(form);continue}if(dirty(form)){status(form,'正在保存…');if(await form._flush()===false){for(const input of form.querySelectorAll('input,textarea'))if(input._draft&&!await cache(input._draft.key,{value:input.value,base:input._draft.base,updated:Date.now()}))return false}}}
   if(globalThis.StellarNotes?.flushAll&&await StellarNotes.flushAll()===false&&!await StellarNotes.cacheAll())return false;await Promise.all([...pending]);return true})();
  try{return await flushing}finally{flushing=null}
 }
 document.addEventListener('click',async event=>{
  if(replaying)return;
  const node=event.target.closest('#detail-dialog .dialog-head button,#library-dialog .dialog-head button,#preview-close,#preview-full,#items .library-row');
  const backdrop=event.target.matches?.('#detail-dialog,#library-dialog')&&(()=>{const rect=event.target.getBoundingClientRect();return event.clientX<rect.left||event.clientX>rect.right||event.clientY<rect.top||event.clientY>rect.bottom})();
  if(!node&&!backdrop||![...forms].some(dirty)&&!globalThis.StellarNotes?.hasDirty?.())return;
  event.preventDefault();event.stopImmediatePropagation();const target=node||event.target,id=node?.closest('[data-id]')?.dataset.id;
  if(await flush()){replaying=true;try{const current=target.isConnected?target:id?document.querySelector('#items [data-id="'+id+'"]'):null;current?.click()}finally{replaying=false}}
 },true);
 document.addEventListener('cancel',event=>{if(!event.target.matches?.('#detail-dialog,#library-dialog')||flushing)return;if([...forms].some(dirty)||globalThis.StellarNotes?.hasDirty?.()){event.preventDefault();void flush().then(ok=>{if(ok)event.target.close()})}},true);
 globalThis.addEventListener?.('beforeunload',event=>{if([...forms].some(dirty)||pending.size){event.preventDefault();event.returnValue=''}});
 async function clearAll(){await Promise.all([...pending]);for(let index=localStorage.length-1;index>=0;index--){const key=localStorage.key(index);if(key?.startsWith(prefix)||key?.startsWith('stellar-note-draft:'))localStorage.removeItem(key)}const db=await database();if(db)await new Promise(resolve=>{const tx=db.transaction('drafts','readwrite');tx.objectStore('drafts').clear();tx.oncomplete=tx.onerror=()=>resolve()})}
 globalThis.StellarDrafts={clearAll,track,register,saved,cancel,dirty,flush,cache,read,discard,status,base:input=>input?._draft?.base,isFlushing:()=>Boolean(flushing)};
})();
