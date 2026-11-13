/* A bounded preview with inline title editing. */
(()=>{
 const $=selector=>document.querySelector(selector),t=value=>StellarI18n.t(value);
 let api,toast,openDetails,link,describe,onSaved,loadingId='',items=[],selected='',cached=null,revision=0,editing=null;
 const esc=value=>String(value).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 function timestamp(value){
  if(typeof value!=='string'||!value.trim())return null;
  const date=new Date(value);if(!Number.isFinite(date.getTime()))return null;
  const pad=value=>String(value).padStart(2,'0'),offset=-date.getTimezoneOffset();
  return {value,text:date.getFullYear()+'-'+pad(date.getMonth()+1)+'-'+pad(date.getDate())+' '+pad(date.getHours())+':'+pad(date.getMinutes())+':'+pad(date.getSeconds()),zone:'UTC'+(offset>=0?'+':'-')+pad(Math.floor(Math.abs(offset)/60))+':'+pad(Math.abs(offset)%60)};
 }
 function timestamps(item){
  const created=timestamp(item.created),updated=timestamp(item.updated);
  const row=(label,key,value)=>'<div><span>'+esc(t(label))+'</span> '+(value?'<time data-record-'+key+' datetime="'+esc(value.value)+'" title="'+esc(t('本地时间')+' · '+value.zone)+'">'+esc(value.text)+'</time>':'<span data-record-'+key+'>'+esc(t('未记录'))+'</span>')+'</div>';
  return '<div class="record-timestamps muted">'+row('建档时间','created',created)+(updated&&updated.text!==created?.text?row('最近更新','updated',updated):'')+'</div>';
 }
 function endEdit(focus=false){editing=null;$('#preview-title-editor').hidden=true;$('#preview-title').hidden=false;if(focus)$('#preview-title').focus()}
 function editTitle(){if(!cached||editing)return;editing={id:selected,saving:false};$('#preview-title-input').value=cached.title;StellarDrafts.track($('#preview-title-input'),selected+':title');$('#preview-title-input').disabled=false;$('#preview-title-save').disabled=false;$('#preview-title-cancel').disabled=false;$('#preview-title-error').textContent='';$('#preview-title').hidden=true;$('#preview-title-editor').hidden=false;$('#preview-title-input').focus();$('#preview-title-input').select()}
 async function saveTitle(event){
  event.preventDefault();const draft=editing;if(!draft||draft.saving)return false;
  const title=$('#preview-title-input').value.trim();if(!title){$('#preview-title-error').textContent=t('标题不能为空');$('#preview-title-input').focus();return false}
  if(cached&&title===cached.title){StellarDrafts.saved($('#preview-title-editor'));endEdit();return true}
  draft.saving=true;StellarDrafts.status($('#preview-title-editor'),'正在保存…');for(const control of $('#preview-title-editor').querySelectorAll('input,button'))control.disabled=true;
  try{
   const result=await api('/api/items/'+draft.id+'/title',{title,expected_title:StellarDrafts.base($('#preview-title-input'))??cached?.title});StellarDrafts.saved($('#preview-title-editor'));
   if(editing===draft){if(cached&&selected===draft.id){cached.title=result.item.title;cached.updated=result.item.updated;$('#preview-title').textContent=result.item.title;$('#preview-timestamps').innerHTML=timestamps(cached)}endEdit(true)}
   toast(t('标题已保存'));await onSaved?.();return true;
  }catch(error){if(editing===draft)$('#preview-title-error').textContent=StellarI18n.message(error.message);else toast(error.message);return false}
  finally{draft.saving=false;if(editing===draft)for(const control of $('#preview-title-editor').querySelectorAll('input,button'))control.disabled=false}
 }
 function markSelection(){for(const row of $('#items').querySelectorAll('.library-row')){const active=row.dataset.id===selected;row.classList.toggle('selected',active);row.setAttribute('aria-pressed',String(active))}}
 function clear(){endEdit();revision++;loadingId='';selected='';cached=null;$('#preview-attachments').innerHTML='';$('#preview-timestamps').innerHTML='';markSelection();$('#preview-empty').hidden=false;$('#preview-material').hidden=true;$('#preview-status').textContent='';$('#preview-full').disabled=true;$('#preview-trash').disabled=true;$('#preview-original').hidden=true;$('#preview-file').hidden=true}
 async function select(id,record=true){
  if(id!==selected&&!StellarDrafts.isFlushing()&&!await StellarDrafts.flush())return;
  if(id===selected&&cached){markSelection();return}
  endEdit();
  const same=id===selected,scroll=$('#preview-content').scrollTop,request=++revision;selected=id;loadingId=id;cached=null;markSelection();$('#preview-empty').hidden=true;$('#preview-material').hidden=true;$('#preview-full').disabled=true;$('#preview-trash').disabled=true;$('#preview-status').textContent=t('正在读取预览…');
  if(record)void api('/api/items/'+id+'/view',{}).catch(()=>{});
  try{
   const item=await api('/api/items/'+id+'/quick-preview');if(request!==revision)return;cached=item;loadingId='';$('#preview-status').textContent=item.error?StellarI18n.message(item.error):'';$('#preview-material').hidden=false;$('#preview-title').textContent=item.title;$('#preview-timestamps').innerHTML=timestamps(item);$('#preview-attachments').innerHTML=StellarBundles.renderAll(item,true);if($('#preview-pdf-coverage'))$('#preview-pdf-coverage').innerHTML=StellarPDF.coverage(item);const presentation=describe(item);$('#preview-scope').hidden=!presentation.scope&&!presentation.partial;$('#preview-scope').textContent=presentation.scope||t('这份资料仅包含已归档的部分内容。');$('#preview-scope').className=presentation.partial?'warning':'muted';$('#preview-summary-heading').textContent=item.summary_truncated?t('摘要预览（前 12000 字）'):t('摘要');$('#preview-summary').textContent=(item.summary?presentation.summary:'')||t('尚无摘要，原文和原件可独立查阅。');$('#preview-text').textContent=item.text||t('暂时没有可读取的正文。');$('#preview-text-heading').textContent=item.truncated?t('原文预览（前 6000 字）'):t('原文预览');$('#preview-source').textContent=presentation.source;$('#preview-source').title=link(item)||item.filename||'';
   const url=link(item);$('#preview-original').hidden=!url;if(url)$('#preview-original').href=url;$('#preview-file').hidden=!item.filename;if(item.filename)$('#preview-file').href='/api/items/'+id+'/file';$('#preview-full').disabled=false;$('#preview-trash').disabled=false;$('#preview-content').scrollTop=same?scroll:0;
  }catch(error){if(request===revision){loadingId='';$('#preview-status').textContent=error.message}}
 }
 function sync(values){items=values;if(selected&&!items.some(item=>item.id===selected)){clear();return}markSelection();if(editing)return;const current=items.find(item=>item.id===selected);if(current&&((!cached&&loadingId!==selected)||(cached&&cached.updated!==current.updated))){cached=null;void select(selected,false)}}
 function bind(options){({api,toast,openDetails,link,describe,onSaved}=options);clear();$('#preview-close').onclick=()=>{clear();$('#search').focus()};$('#preview-trash').onclick=()=>selected&&StellarArchiveActions.trash(selected);$('#preview-full').onclick=()=>selected&&openDetails(selected);
  $('#preview-content').ondblclick=event=>{
   if(!selected||!cached||$('#preview-full').disabled)return;
   if(event.target.closest('button,a,input,textarea,select,summary,details,[role="button"],[contenteditable]'))return;
   event.preventDefault();event.stopPropagation();
   // Follow the existing button path so unsaved drafts are handled before navigation.
   $('#preview-full').click();
  };
  $('#preview-title').ondblclick=editTitle;
  $('#preview-title').onkeydown=event=>{if(['Enter','F2',' '].includes(event.key)){event.preventDefault();event.stopPropagation();editTitle()}};
  $('#preview-title-editor').onsubmit=saveTitle;StellarDrafts.register($('#preview-title-editor'),()=>saveTitle({preventDefault(){}}));
  $('#preview-title-cancel').onclick=()=>{StellarDrafts.cancel($('#preview-title-editor'));endEdit(true)};
  $('#preview-title-editor').onkeydown=event=>{if(event.key==='Escape'){event.preventDefault();event.stopPropagation();if(!editing?.saving){StellarDrafts.cancel($('#preview-title-editor'));endEdit(true)}}};
  $('#library-dialog').addEventListener('cancel',event=>{if(selected){event.preventDefault();clear();$('#search').focus()}});
  $('#library-dialog').addEventListener('close',()=>{endEdit();revision++;loadingId=''});
  $('#library-dialog').addEventListener('keydown',event=>{
   if(!['ArrowDown','ArrowUp','Enter'].includes(event.key)||(!event.target.closest('#items .library-row')&&event.target.id!=='search'))return;
   const rows=[...$('#items').querySelectorAll('.library-row')];if(!rows.length)return;event.preventDefault();let index=rows.findIndex(row=>row.dataset.id===selected);
   if(event.key!=='Enter'){index=index<0?0:Math.max(0,Math.min(rows.length-1,index+(event.key==='ArrowDown'?1:-1)));const row=rows[index];row.focus({preventScroll:true});row.scrollIntoView({block:'nearest'});void select(row.dataset.id);return}
   const id=(index<0?rows[0]:rows[index]).dataset.id;
   if(event.metaKey||event.ctrlKey){const url=link(items.find(item=>item.id===id));if(url){window.open(url,'_blank','noopener,noreferrer');void api('/api/items/'+id+'/view',{}).catch(()=>{})}else toast(t('这份资料没有原网页链接，可在完整资料中打开原件。'))}else void select(id);
  });
 }
 globalThis.StellarLibraryPreview={bind,select,sync,clear,timestamps,refresh:()=>{if(editing)return;cached=null;if(selected&&$('#library-dialog').open)void select(selected,false)},selected:()=>selected};
})();
