/* Original attachments are served by fixed, same-origin archive endpoints. */
(()=>{
 const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const valid=value=>typeof value==='string'&&/^[a-f0-9]{32}$/.test(value);
 function render(item){
  if(!item.attachments?.length)return item.bundle_error?'<p class="warning">'+esc(StellarI18n.t(item.bundle_error))+'</p>':'';
  return '<section class="bundle-originals"><h3>'+StellarI18n.t('本次组合附件')+'</h3><div class="bundle-files">'+item.attachments.map(file=>{
   if(!valid(item.id)||!valid(file.id))return '';
   const path='/api/items/'+item.id+'/attachments/'+file.id;
   return '<div class="bundle-file">'+(file.media.startsWith('image/')?'<a href="'+path+'/preview" target="_blank" rel="noopener noreferrer"><img loading="lazy" src="'+path+'/preview" alt="'+esc(file.name)+'"></a>':'<span aria-hidden="true">▧</span>')+'<strong>'+esc(file.name)+'</strong><a href="'+path+'">'+StellarI18n.t('下载附件')+'</a>'+(/\.pdf$/i.test(file.name)?'<a href="'+path+'/preview" target="_blank" rel="noopener noreferrer">'+StellarI18n.t('浏览器查看')+'</a>':'')+(file.warning?'<small>'+esc(StellarI18n.message(file.warning))+'</small>':'')+'</div>';
  }).join('')+'</div></section>';
 }
 function chatImages(images){return '<div class="message-images">'+images.filter(image=>valid(image.item_id)&&valid(image.id)).map(image=>{const path='/api/items/'+image.item_id+'/attachments/'+image.id+'/preview';return '<a href="'+path+'" target="_blank" rel="noopener noreferrer"><img loading="lazy" src="'+path+'" alt="'+esc(image.name)+'"></a>'}).join('')+'</div>'}
 globalThis.StellarBundles={render,chatImages};
})();
