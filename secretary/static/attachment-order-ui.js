/* Reorder presentation only; attachment URLs and originals stay stable. */
(()=>{
 const t=s=>StellarI18n.t(s),saving=new Set();let config,drag=null,suppressClick=0;
 const section=node=>node?.closest?.('[data-attachment-item]');
 const cards=root=>[...root.querySelector('.material-grid').children];
 const keys=root=>cards(root).map(card=>(card.dataset.batch||'original')+':'+card.dataset.attachment);
 const roots=id=>[...document.querySelectorAll('[data-attachment-item="'+id+'"]')];
 function message(root,value,error=false){let line=root.querySelector('[data-order-status]');if(!line){line=document.createElement('p');line.dataset.orderStatus='';line.setAttribute('role','status');root.append(line)}line.className=error?'warning':'muted';line.textContent=value}
 function arrange(root,order){const grid=root.querySelector('.material-grid'),map=new Map(cards(root).map(card=>[(card.dataset.batch||'original')+':'+card.dataset.attachment,card]));for(const key of order){const card=map.get(key);if(card)grid.append(card)}}
 function controls(root,busy){root.classList.toggle('order-saving',busy);const values=cards(root);for(const card of values){card.draggable=!busy&&values.length>1;const handle=card.querySelector('[data-order-handle]');if(handle)handle.disabled=busy}}
 async function save(root,order,focusKey){
  const id=root.dataset.attachmentItem,before=keys(root);if(saving.has(id)||before.every((key,index)=>key===order[index]))return;
  saving.add(id);for(const node of roots(id)){arrange(node,order);controls(node,true);message(node,t('正在保存附件顺序…'))}
  try{const result=await config.api('/api/items/'+id+'/attachment-order',{order,expected_order:before});
   for(const node of roots(id)){arrange(node,result.order);for(const button of node.querySelectorAll('[data-delete-version]'))button.dataset.deleteVersion=result.updated;message(node,t('附件顺序已保存'))}
  }catch(error){for(const node of roots(id)){arrange(node,before);message(node,t('附件排序未保存：')+error.message,true)}}
  finally{saving.delete(id);for(const node of roots(id))controls(node,false);if(focusKey&&root.isConnected){const card=cards(root).find(card=>(card.dataset.batch||'original')+':'+card.dataset.attachment===focusKey);card?.querySelector('[data-order-handle]')?.focus({preventScroll:true})}}
 }
 function clear(){for(const node of document.querySelectorAll('.attachment-dragging,.attachment-drop-target'))node.classList.remove('attachment-dragging','attachment-drop-target');drag=null}
 document.addEventListener('dragstart',event=>{
  const card=event.target.closest?.('.material-card'),root=section(card);if(!card||!root)return;
  if(saving.has(root.dataset.attachmentItem)||event.target.closest('details')||cards(root).length<2){event.preventDefault();return}
  drag={id:root.dataset.attachmentItem,key:(card.dataset.batch||'original')+':'+card.dataset.attachment,order:keys(root)};card.classList.add('attachment-dragging');suppressClick=Date.now()+800;
  event.dataTransfer.effectAllowed='move';event.dataTransfer.setData('application/x-stellar-attachment',drag.key);
 });
 document.addEventListener('dragover',event=>{
  const root=section(event.target);if(!drag||!root||drag.id!==root.dataset.attachmentItem)return;event.preventDefault();event.stopPropagation();event.dataTransfer.dropEffect='move';
  for(const node of document.querySelectorAll('.attachment-drop-target'))node.classList.remove('attachment-drop-target');event.target.closest('.material-card')?.classList.add('attachment-drop-target');
 });
 document.addEventListener('drop',event=>{
  const root=section(event.target);if(!drag||!root||drag.id!==root.dataset.attachmentItem)return;event.preventDefault();event.stopPropagation();
  const current=keys(root),source=current.indexOf(drag.key),target=event.target.closest('.material-card'),index=target?cards(root).indexOf(target):current.length-1;
  if(source<0||current.join('|')!==drag.order.join('|')){clear();message(root,t('附件列表已变化，请重新查看后排序。'),true);return}
  current.splice(source,1);current.splice(index,0,drag.key);clear();suppressClick=Date.now()+500;void save(root,current);
 });
 document.addEventListener('dragend',()=>{if(drag)suppressClick=Date.now()+500;clear()});
 document.addEventListener('click',event=>{if(Date.now()<suppressClick&&section(event.target)){event.preventDefault();event.stopImmediatePropagation()}},true);
 document.addEventListener('keydown',event=>{
  const handle=event.target.closest?.('[data-order-handle]');if(!handle||!['ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(event.key))return;
  event.preventDefault();event.stopPropagation();const root=section(handle);if(saving.has(root.dataset.attachmentItem))return;
  const order=keys(root),index=cards(root).indexOf(handle.closest('.material-card')),next=index+(['ArrowLeft','ArrowUp'].includes(event.key)?-1:1);if(next<0||next>=order.length)return;
  const key=order[index];order.splice(index,1);order.splice(next,0,key);void save(root,order,key);
 });
 addEventListener('beforeunload',event=>{if(saving.size){event.preventDefault();event.returnValue=''}});
 globalThis.StellarAttachmentOrder={bind:options=>{config=options},isBusy:id=>saving.has(id)||drag?.id===id};
})();
