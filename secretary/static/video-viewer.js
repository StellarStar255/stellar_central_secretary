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
   dialog.addEventListener('close',()=>{remember(video,true);video.pause();video.removeAttribute('src');video.load();if(opener?.isConnected)opener.focus()});
   dialog.addEventListener('click',event=>{if(event.target===dialog){const box=dialog.getBoundingClientRect();if(event.clientX<box.left||event.clientX>box.right||event.clientY<box.top||event.clientY>box.bottom)dialog.close()}});
   video.addEventListener('loadedmetadata',()=>{const state=progress(video.dataset.source);if(state.position>0&&state.position<video.duration-Math.min(2,video.duration*.05))video.currentTime=state.position});
   video.addEventListener('timeupdate',()=>remember(video));
   video.addEventListener('pause',()=>remember(video,true));
   video.addEventListener('error',()=>{dialog.querySelector('p').hidden=false});
  }
  opener=trigger;dialog.querySelector('h2').textContent=trigger.dataset.videoName||t('视频播放器');dialog.setAttribute('aria-label',t('视频播放器'));
  dialog.querySelector('[data-video-close]').setAttribute('aria-label',t('关闭'));
  const error=dialog.querySelector('p');error.textContent=t('当前播放器不支持此视频编码，或文件无法读取。可用默认程序打开，或下载原件。');error.hidden=true;
  const external=dialog.querySelector('[data-video-external]');external.textContent=t('默认程序打开');external.dataset.editorPath=url.slice(0,-8)+'/editor';external.dataset.editorAction='open';external.hidden=trigger.dataset.videoExternal!=='true';
  const download=dialog.querySelector('[data-video-download]');download.textContent=t('下载附件');download.href=trigger.dataset.videoDownload||url.slice(0,-8);
  try{const saved=await options.api(url.slice(0,-8)+'/video-state');localStorage.setItem('stellar-video:'+url,JSON.stringify(saved))}catch{}
  video.dataset.source=url;video.src=url;if(!dialog.open)dialog.showModal();video.play().catch(()=>{});dialog.querySelector('[data-video-close]').focus();
 }
 function progress(url){try{return JSON.parse(localStorage.getItem('stellar-video:'+url)||'{}')}catch{return {}}}
 function remember(player,force=false){if(!player.dataset.source||!Number.isFinite(player.duration)||!player.duration)return;const now=Date.now();if(!force&&now-(player._savedAt||0)<5000)return;player._savedAt=now;const value={position:player.currentTime>=player.duration-Math.min(2,player.duration*.05)?0:player.currentTime,duration:player.duration};try{localStorage.setItem('stellar-video:'+player.dataset.source,JSON.stringify(value))}catch{}void options?.api(player.dataset.source.slice(0,-8)+'/video-state',value).catch(()=>{})}
 // Decode one visible cover at a time. Browser decoding uses the installed platform codecs.
 const seen=new WeakSet();let queue=Promise.resolve();
 const observer=globalThis.IntersectionObserver?new IntersectionObserver(entries=>{for(const entry of entries)if(entry.isIntersecting){observer.unobserve(entry.target);queue=queue.then(()=>cover(entry.target)).catch(()=>{})}}):{observe(){},unobserve(){}};
 async function cover(trigger){
  if(!trigger.isConnected||!options)return;const url=trigger.dataset.videoSrc,base=url.slice(0,-8);let state={};try{state=await options.api(base+'/video-state')}catch{}
  const paint=value=>{if(!trigger.isConnected)return;if(value.poster)trigger.querySelector('img').src=base+'/video-poster';if(value.duration){let badge=trigger.querySelector('.video-duration');if(!badge){badge=document.createElement('span');badge.className='video-duration';trigger.append(badge)}badge.textContent=Math.floor(value.duration/60)+':'+String(Math.floor(value.duration%60)).padStart(2,'0')}};paint(state);if(state.poster)return;
  const player=document.createElement('video');player.muted=true;player.preload='metadata';player.src=url;player.playsInline=true;
  try{await new Promise((resolve,reject)=>{const timer=setTimeout(()=>reject(Error('metadata timeout')),6000);player.onloadedmetadata=()=>{clearTimeout(timer);resolve()};player.onerror=()=>{clearTimeout(timer);reject(Error('decode'))}});
   if(!Number.isFinite(player.duration)||!player.duration)return;await new Promise((resolve,reject)=>{const timer=setTimeout(()=>reject(Error('frame timeout')),5000);player.onseeked=()=>{clearTimeout(timer);resolve()};player.currentTime=Math.min(.5,player.duration/4)});
   const canvas=document.createElement('canvas'),ratio=Math.min(480/player.videoWidth,320/player.videoHeight,1);canvas.width=Math.max(1,Math.round(player.videoWidth*ratio));canvas.height=Math.max(1,Math.round(player.videoHeight*ratio));canvas.getContext('2d').drawImage(player,0,0,canvas.width,canvas.height);
   paint(await options.api(base+'/video-state',{duration:player.duration,poster:canvas.toDataURL('image/jpeg',.82).split(',')[1]}));
  }finally{player.removeAttribute('src');player.load()}
 }
 function scan(){for(const trigger of document.querySelectorAll('.material-thumb[data-video-src]'))if(!seen.has(trigger)){seen.add(trigger);observer.observe(trigger)}}
 if(globalThis.MutationObserver)new MutationObserver(scan).observe(document.documentElement,{childList:true,subtree:true});
 document.addEventListener('click',event=>{const trigger=event.target.closest('[data-video-src]');if(!trigger)return;event.preventDefault();event.stopImmediatePropagation();open(trigger)},true);
 globalThis.StellarVideoViewer={open,bind:config=>{options=config}};
})();
