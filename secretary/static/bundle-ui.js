/* Original attachments are served by fixed, same-origin archive endpoints. */
(()=>{
 const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const valid=value=>typeof value==='string'&&/^[a-f0-9]{32}$/.test(value);
 function renderAll(item,compact=false){
  const files=item.all_attachments||[];if(!files.length)return '';
  return '<section class="material-attachments"'+(compact?'':' id="detail-attachments"')+'><h3>'+StellarI18n.t('全部附件')+' <span class="muted">('+files.length+')</span></h3><div class="material-grid">'+files.map(file=>{
   const path=file.path;if(!/^\/api\/items\/[a-f0-9]{32}(?:\/(?:additions\/[a-f0-9]{32}\/)?attachments\/[a-f0-9]{32})?$/.test(path))return '';
   const image=file.media.startsWith('image/'),pdf=/\.pdf$/i.test(file.name),name=esc(file.name);
   const thumb='<img loading="lazy" src="'+esc(file.thumbnail_url)+'" alt="'+name+'">';
   const action=image?'<button type="button" class="material-thumb image-open" data-image-view data-image-src="'+esc(file.preview_url)+'" aria-label="'+esc(StellarI18n.t('查看图片：')+file.name)+'">'+thumb+'</button>':pdf?'<a class="material-thumb" href="'+esc(file.preview_url)+'" target="_blank" rel="noopener noreferrer" aria-label="'+esc(StellarI18n.t('打开附件：')+file.name)+'">'+thumb+'</a>':file.can_open?'<button type="button" class="material-thumb" data-editor-path="'+path+'/editor" data-editor-action="open" aria-label="'+esc(StellarI18n.t('打开附件：')+file.name)+'">'+thumb+'</button>':'<a class="material-thumb" href="'+esc(file.download_url)+'" aria-label="'+esc(StellarI18n.t('下载附件')+' '+file.name)+'">'+thumb+'</a>';
   const source=file.batch_id?StellarI18n.t('追加附件')+' · '+new Date(file.created).toLocaleString(StellarI18n.locale):StellarI18n.t('原始附件');
   return '<article class="material-card" data-attachment="'+esc(file.id)+'" data-batch="'+esc(file.batch_id||'')+'">'+action+'<strong title="'+name+'">'+name+'</strong><small class="muted">'+esc(source)+'</small><details class="material-tools"'+(!compact&&file.editing?' open':'')+'><summary>'+StellarI18n.t('更多操作')+'</summary><a href="'+esc(file.download_url)+'">'+StellarI18n.t('下载附件')+'</a>'+(file.can_open?'<button type="button" class="secondary" data-editor-path="'+path+'/editor" data-editor-action="open">'+StellarI18n.t('默认程序打开')+'</button><button type="button" class="secondary" data-editor-path="'+path+'/editor" data-editor-action="reveal">'+StellarI18n.t('在文件夹中显示')+'</button>':'')+(!compact&&file.editing?'<button type="button" class="secondary" data-editor-path="'+path+'/editor" data-editor-action="save" '+(item.append_busy?'disabled':'')+'>'+StellarI18n.t('保存修改回归档')+'</button>':'')+(file.warning?'<small class="warning">'+esc(StellarI18n.message(file.warning))+'</small>':'')+'</details></article>';
  }).join('')+'</div></section>';
 }
 function render(item,batchId=''){
  const sources=item.group_links||item.links||[];
  const linkCards=sources.length?'<section class="group-links"><h3>'+StellarI18n.t('本档案的来源链接')+'</h3>'+sources.map(link=>'<article class="group-link"><a href="'+esc(link.url)+'" target="_blank" rel="noopener noreferrer">'+esc(link.url)+'</a><span>'+StellarI18n.t(({read:'已读取',unread:'未读取正文',pending:'等待读取'})[link.state]||'未读取正文')+'</span>'+(link.warning?'<p class="muted">'+esc(link.warning)+'</p>':'')+'</article>').join('')+'<p class="muted">'+StellarI18n.t('需要登录的页面会先保留链接；可打开页面，将正文追加到此档案。')+'</p></section>':'';
  if(!item.attachments?.length)return linkCards+(item.bundle_error?'<p class="warning">'+esc(StellarI18n.t(item.bundle_error))+'</p>':'');
  return linkCards+'<section class="bundle-originals"><h3>'+StellarI18n.t('本次组合附件')+'</h3><div class="bundle-files">'+item.attachments.map(file=>{
   if(!valid(item.id)||!valid(file.id))return '';
   const path='/api/items/'+item.id+(valid(batchId)?'/additions/'+batchId:'')+'/attachments/'+file.id;
   return '<div class="bundle-file">'+(file.media.startsWith('image/')?'<button type="button" class="image-open" data-image-view aria-label="'+esc(StellarI18n.t('查看图片：')+file.name)+'"><img loading="lazy" src="'+path+'/preview" alt="'+esc(file.name)+'"></button>':'<span aria-hidden="true">▧</span>')+'<strong>'+esc(file.name)+'</strong><a href="'+path+'">'+StellarI18n.t('下载附件')+'</a>'+(/\.pdf$/i.test(file.name)?'<a href="'+path+'/preview" target="_blank" rel="noopener noreferrer">'+StellarI18n.t('浏览器查看')+'</a>':'')+(file.can_open?'<button type="button" class="secondary" data-editor-path="'+path+'/editor" data-editor-action="open">'+StellarI18n.t('默认程序打开')+'</button><button type="button" class="secondary" data-editor-path="'+path+'/editor" data-editor-action="reveal">'+StellarI18n.t('在文件夹中显示')+'</button>'+(file.editing?'<button type="button" class="secondary" data-editor-path="'+path+'/editor" data-editor-action="save" '+(item.append_busy?'disabled':'')+'>'+StellarI18n.t('保存修改回归档')+'</button><small>'+StellarI18n.t('先在外部程序保存，再点击保存修改回归档。修改前版本保留在本机，摘要不会自动重跑。')+'</small>':''):'')+(file.warning?'<small>'+esc(StellarI18n.message(file.warning))+'</small>':'')+'</div>';
  }).join('')+'</div></section>';
 }
 function chatImages(images){return '<div class="message-images">'+images.filter(image=>valid(image.item_id)&&valid(image.id)).map(image=>{const path='/api/items/'+image.item_id+'/attachments/'+image.id;return '<button type="button" class="image-open" data-image-view aria-label="'+esc(StellarI18n.t('查看图片：')+image.name)+'"><img loading="lazy" src="'+path+'/preview" alt="'+esc(image.name)+'"></button>'}).join('')+'</div>'}
 let options=null,bound=false;
 function bind(config){options=config;if(bound)return;bound=true;document.addEventListener('click',async event=>{
  const button=event.target.closest('[data-editor-action]');if(!button||button.disabled||!options)return;
  const path=button.dataset.editorPath,action=button.dataset.editorAction;
  if(!/^\/api\/items\/[a-f0-9]{32}(?:\/(?:additions\/[a-f0-9]{32}\/)?attachments\/[a-f0-9]{32})?\/editor$/.test(path)||!['open','reveal','save'].includes(action))return;
  event.preventDefault();button.disabled=true;
  try{const result=await options.api(path+'/'+action,{});await options.onSaved(path.split('/')[3]);options.toast(StellarI18n.t(result.conflict?'归档附件已更新，本机编辑文件仍保留，请先核对版本。':action==='save'?(result.changed?'文件修改已保存，已有摘要可能过期；可手动重新整理。':'没有检测到文件内容变化，请先在外部程序中保存。'):action==='open'?(button.classList.contains('image-open')?'已在默认程序中打开图片':'已在默认程序中打开编辑副本'):'已在文件夹中显示编辑文件'))}
  catch(error){options.toast(StellarI18n.message(error.message))}finally{button.disabled=false}
 })}
 globalThis.StellarBundles={render,renderAll,chatImages,bind};
})();
