/* Archive deletion and stale-history filtering. Cache identifiers, never copies. */
(()=>{
 const key='stellar.deleted-archive-refs',items=new Set(),messages=new Set(),affected=new Set();
 const t=value=>StellarI18n.t(value);
 function accept(value={}){
  for(const id of value.deletedItemIds||[])if(typeof id==='string'&&/^[a-f0-9]{32}$/.test(id))items.add(id);
  for(const pair of value.deletedMessages||[])if(Array.isArray(pair)&&pair.length===2&&pair.every(v=>typeof v==='string')){messages.add(JSON.stringify(pair));affected.add(pair[0])}
  for(const id of items){globalThis.StellarNotes?.discard?.(id);for(const node of document.querySelectorAll('[data-id="'+id+'"]'))node.remove()}
  if(typeof selectedId!=='undefined'&&items.has(selectedId)){
   const dialog=document.querySelector('#detail-dialog');if(dialog?.open)dialog.close();
   if(dialog)document.querySelector('#detail-content').innerHTML='';selectedId='';detailVersion='';
  }
  try{const encoded=JSON.stringify({deletedItemIds:[...items].sort(),deletedMessages:[...messages].sort().map(JSON.parse)});if(localStorage.getItem(key)!==encoded)localStorage.setItem(key,encoded)}catch{}
 }
 function clean(chats){return chats.flatMap(original=>{
  const list=original.messages||[],drop=new Set();
  list.forEach((message,index)=>{
   const refs=[...(Array.isArray(message.items)?message.items:[]),...(Array.isArray(message.sources)?message.sources:[]).map(source=>source?.item_id),...(Array.isArray(message.images)?message.images:[]).map(image=>image?.item_id)];
   if(messages.has(JSON.stringify([original.id,message.id]))||refs.some(id=>items.has(id))){drop.add(index);if(message.role==='assistant'&&index&&list[index-1].role==='user')drop.add(index-1)}
  });
  if(!drop.size&&!affected.has(original.id))return [original];
  const kept=list.filter((_,index)=>!drop.has(index));if(!kept.length)return [];
  const user=kept.find(message=>message.role==='user')||{};
  const title=String(user.text||user.files?.[0]||'Conversation').slice(0,36);
  if(!drop.size&&title===original.title)return [original];
  return [{...original,messages:kept,title}];
 })}
 try{accept(JSON.parse(localStorage.getItem(key)||'{}'))}catch{}
 globalThis.StellarArchiveActions={accept,clean,isDeleted:id=>items.has(id)};
 const menu=document.querySelector('#archive-context-menu'),dialog=document.querySelector('#delete-archive-dialog');
 let target='',candidate=null,deleting=false;
 document.addEventListener('contextmenu',event=>{
  const row=event.target.closest('.recent-item[data-id],.library-row[data-id],.archive-card[data-id],.source[data-id]');
  if(!row||typeof allItems==='undefined'||!allItems.some(item=>item.id===row.dataset.id))return;
  event.preventDefault();target=row.dataset.id;row.focus();
  menu.style.left='0px';menu.style.top='0px';if(!menu.open)menu.showModal();
  const rect=menu.getBoundingClientRect();menu.style.left=Math.max(8,Math.min(event.clientX,innerWidth-rect.width-8))+'px';menu.style.top=Math.max(8,Math.min(event.clientY,innerHeight-rect.height-8))+'px';
  document.querySelector('#archive-delete-menu').focus();
 });
 menu.addEventListener('keydown',event=>{if(['ArrowDown','ArrowUp','Home','End'].includes(event.key)){event.preventDefault();document.querySelector('#archive-delete-menu').focus()}});
 document.querySelector('#archive-delete-menu').onclick=async()=>{
  const id=target;menu.close();
  if(sending){toast(t('请等待当前消息处理完成后再删除。'));return}
  try{
   candidate=await api('/api/items/'+id);
   document.querySelector('#delete-archive-title').textContent=candidate.title;
   dialog.showModal();document.querySelector('#delete-archive-cancel').focus();
  }catch(error){toast(error.message)}
 };
 dialog.addEventListener('cancel',event=>{if(deleting)event.preventDefault()});
 dialog.addEventListener('close',()=>{document.querySelector('#delete-archive-title').textContent='';if(!deleting)candidate=null});
 document.querySelector('#delete-archive-cancel').onclick=()=>dialog.close();
 document.querySelector('#delete-archive-confirm').onclick=async()=>{
  if(!candidate||deleting)return;
  const item=candidate,button=document.querySelector('#delete-archive-confirm'),cancel=document.querySelector('#delete-archive-cancel');
  deleting=true;button.disabled=true;cancel.disabled=true;
  try{
   await sharedChatSaves;
   const result=await api('/api/items/'+item.id+'/delete',{confirmed:true,expected_updated:item.updated});
   accept(result.history);mergeChats(result.history);allItems=allItems.filter(value=>!items.has(value.id));
   candidate=null;dialog.close();lastMessageMarkup=null;renderSidebar();renderChat(false);await refresh();toast(result.warning?StellarI18n.message(result.warning):t('归档已删除'));
  }catch(error){toast(error.message)}
  finally{deleting=false;button.disabled=false;cancel.disabled=false}
 };
 addEventListener('storage',event=>{if(event.key!==key)return;try{accept(JSON.parse(event.newValue||'{}'));mergeChats({conversations:[]});allItems=allItems.filter(item=>!items.has(item.id));renderSidebar();renderChat(false);void refresh().catch(()=>{})}catch{}});
})();
