/* Keep local video playback inside the application; no external navigation. */
(()=>{
 const t=value=>StellarI18n.t(value);
 let dialog=null,video=null,opener=null,options=null,opening=false;
 const valid=url=>/^\/api\/items\/[a-f0-9]{32}(?:\/(?:additions\/[a-f0-9]{32}\/)?attachments\/[a-f0-9]{32})?\/preview$/.test(url);
 async function open(trigger){
  const url=trigger.dataset.videoSrc;if(!valid(url))return;
  if(opening)return;
  if(options?.nativeVideo?.()){
   opening=true;
   try{if((await options.api(url.slice(0,-8)+'/video-player',{})).native)return}
   catch(error){options.toast(error.message);return}finally{opening=false}
  }
  if(!dialog){
   dialog=document.createElement('dialog');dialog.id='video-viewer';dialog.className='video-viewer';
   dialog.innerHTML='<div class="dialog-head"><h2></h2><button type="button" class="icon-button" data-video-close>×</button></div><video controls playsinline preload="metadata"></video><p class="warning" role="alert" hidden></p><div class="detail-actions"><button type="button" class="secondary" data-video-external></button><a class="secondary" data-video-download></a></div>';
   document.body.append(dialog);video=dialog.querySelector('video');
   dialog.querySelector('[data-video-close]').onclick=()=>dialog.close();
   dialog.addEventListener('close',()=>{video.pause();video.removeAttribute('src');video.load();if(opener?.isConnected)opener.focus()});
   dialog.addEventListener('click',event=>{if(event.target===dialog){const box=dialog.getBoundingClientRect();if(event.clientX<box.left||event.clientX>box.right||event.clientY<box.top||event.clientY>box.bottom)dialog.close()}});
   video.addEventListener('error',()=>{dialog.querySelector('p').hidden=false});
  }
  opener=trigger;dialog.querySelector('h2').textContent=trigger.dataset.videoName||t('视频播放器');dialog.setAttribute('aria-label',t('视频播放器'));
  dialog.querySelector('[data-video-close]').setAttribute('aria-label',t('关闭'));
  const error=dialog.querySelector('p');error.textContent=t('当前播放器不支持此视频编码，或文件无法读取。可用默认程序打开，或下载原件。');error.hidden=true;
  const external=dialog.querySelector('[data-video-external]');external.textContent=t('默认程序打开');external.dataset.editorPath=url.slice(0,-8)+'/editor';external.dataset.editorAction='open';external.hidden=trigger.dataset.videoExternal!=='true';
  const download=dialog.querySelector('[data-video-download]');download.textContent=t('下载附件');download.href=trigger.dataset.videoDownload||url.slice(0,-8);
  video.src=url;if(!dialog.open)dialog.showModal();video.play().catch(()=>{});dialog.querySelector('[data-video-close]').focus();
 }
 document.addEventListener('click',event=>{const trigger=event.target.closest('[data-video-src]');if(!trigger)return;event.preventDefault();event.stopImmediatePropagation();open(trigger)},true);
 globalThis.StellarVideoViewer={open,bind:config=>{options=config}};
})();
