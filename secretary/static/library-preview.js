/* A bounded read-only preview. Full editing stays in the existing detail view. */
(()=>{
 const $=selector=>document.querySelector(selector),t=value=>StellarI18n.t(value);
 let api,toast,openDetails,link,describe,loadingId='',items=[],selected='',cached=null,revision=0;
 function markSelection(){for(const row of $('#items').querySelectorAll('.library-row')){const active=row.dataset.id===selected;row.classList.toggle('selected',active);row.setAttribute('aria-pressed',String(active))}}
 function clear(){revision++;loadingId='';selected='';cached=null;markSelection();$('#preview-empty').hidden=false;$('#preview-material').hidden=true;$('#preview-status').textContent='';$('#preview-full').disabled=true;$('#preview-original').hidden=true;$('#preview-file').hidden=true}
 async function select(id,record=true){
  if(id===selected&&cached){markSelection();return}
  const same=id===selected,scroll=$('#preview-content').scrollTop,request=++revision;selected=id;loadingId=id;cached=null;markSelection();$('#preview-empty').hidden=true;$('#preview-material').hidden=true;$('#preview-full').disabled=true;$('#preview-status').textContent=t('正在读取预览…');
  if(record)void api('/api/items/'+id+'/view',{}).catch(()=>{});
  try{
   const item=await api('/api/items/'+id+'/quick-preview');if(request!==revision)return;cached=item;loadingId='';$('#preview-status').textContent='';$('#preview-material').hidden=false;$('#preview-title').textContent=item.title;const presentation=describe(item);$('#preview-scope').hidden=!presentation.scope&&!presentation.partial;$('#preview-scope').textContent=presentation.scope||t('这份资料仅包含已归档的部分内容。');$('#preview-scope').className=presentation.partial?'warning':'muted';$('#preview-summary-heading').textContent=item.summary_truncated?t('摘要预览（前 12000 字）'):t('摘要');$('#preview-summary').textContent=(item.summary?presentation.summary:'')||t('尚无摘要，原文和原件可独立查阅。');$('#preview-text').textContent=item.text||t('暂时没有可读取的正文。');$('#preview-text-heading').textContent=item.truncated?t('原文预览（前 6000 字）'):t('原文预览');$('#preview-source').textContent=presentation.source;$('#preview-source').title=link(item)||item.filename||'';
   const url=link(item);$('#preview-original').hidden=!url;if(url)$('#preview-original').href=url;$('#preview-file').hidden=!item.filename;if(item.filename)$('#preview-file').href='/api/items/'+id+'/file';$('#preview-full').disabled=false;$('#preview-content').scrollTop=same?scroll:0;
  }catch(error){if(request===revision){loadingId='';$('#preview-status').textContent=error.message}}
 }
 function sync(values){items=values;if(selected&&!items.some(item=>item.id===selected)){clear();return}markSelection();const current=items.find(item=>item.id===selected);if(current&&((!cached&&loadingId!==selected)||(cached&&cached.updated!==current.updated))){cached=null;void select(selected,false)}}
 function bind(options){({api,toast,openDetails,link,describe}=options);clear();$('#preview-close').onclick=()=>{clear();$('#search').focus()};$('#preview-full').onclick=()=>selected&&openDetails(selected);
  $('#library-dialog').addEventListener('cancel',event=>{if(selected){event.preventDefault();clear();$('#search').focus()}});
  $('#library-dialog').addEventListener('close',()=>{revision++;loadingId=''});
  $('#library-dialog').addEventListener('keydown',event=>{
   if(!['ArrowDown','ArrowUp','Enter'].includes(event.key)||(!event.target.closest('#items')&&event.target.id!=='search'))return;
   const rows=[...$('#items').querySelectorAll('.library-row')];if(!rows.length)return;event.preventDefault();let index=rows.findIndex(row=>row.dataset.id===selected);
   if(event.key!=='Enter'){index=index<0?0:Math.max(0,Math.min(rows.length-1,index+(event.key==='ArrowDown'?1:-1)));const row=rows[index];row.focus({preventScroll:true});row.scrollIntoView({block:'nearest'});void select(row.dataset.id);return}
   const id=(index<0?rows[0]:rows[index]).dataset.id;
   if(event.metaKey||event.ctrlKey){const url=link(items.find(item=>item.id===id));if(url){window.open(url,'_blank','noopener,noreferrer');void api('/api/items/'+id+'/view',{}).catch(()=>{})}else toast(t('这份资料没有原网页链接，可在完整资料中打开原件。'))}else void select(id);
  });
 }
 globalThis.StellarLibraryPreview={bind,select,sync,clear,refresh:()=>{cached=null;if(selected&&$('#library-dialog').open)void select(selected,false)},selected:()=>selected};
})();
