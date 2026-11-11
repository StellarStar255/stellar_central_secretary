/* Local image viewing stays inside the app, above the current detail dialog. */
(()=>{
 const t=value=>StellarI18n.t(value);
 let dialog,stage,picture,caption,status,motionHint,motionButton,items=[],index=0,scale=1,x=0,y=0,drag=null,opener,revision=0;
 const catalogs=new Map();
 async function motion(image,request){
  let url;try{url=new URL(image.src,location.href)}catch{return}
  if(url.origin!==location.origin)return;
  const match=/^\/api\/items\/([a-f0-9]{32})(?:\/(?:additions\/[a-f0-9]{32}\/)?attachments\/[a-f0-9]{32})?\/preview$/.exec(url.pathname);
  if(!match)return;
  try{
   if(!catalogs.has(match[1]))catalogs.set(match[1],fetch('/api/items/'+match[1]+'/quick-preview',{cache:'no-store'}).then(response=>{if(!response.ok)throw Error('metadata');return response.json()}));
   const item=await catalogs.get(match[1]);if(request!==revision||!dialog.open)return;
   const file=item.all_attachments?.find(file=>file.preview_url===url.pathname),video=file?.live_video;
   if(video){
    motionButton.dataset.videoSrc=video.preview_url;motionButton.dataset.videoDownload=video.download_url;
    motionButton.dataset.videoName=image.name+' · '+t('实况');motionButton.dataset.videoExternal=String(Boolean(video.can_open));
    motionButton.hidden=false;motionHint.textContent=t('已找到同名 MOV，点击“播放实况”查看动态画面。');
   }else if(/\.(heic|heif|hif)$/i.test(file?.name||image.name))motionHint.textContent=t('当前仅有静态照片。可在“追加材料”中补入同名 MOV，再重新打开照片播放实况。');
  }catch{if(request===revision&&dialog.open)motionHint.textContent=t('未能检查实况视频，请关闭预览后重试。')}
 }
 function paint(){picture.style.transform=`translate(${x}px,${y}px) scale(${scale})`;dialog.querySelector('[data-viewer="zoom"]').textContent=Math.round(scale*100)+'%'}
 function reset(){scale=1;x=y=0;paint()}
 function show(offset=0){
  index=(index+offset+items.length)%items.length;reset();
  motionButton.hidden=true;delete motionButton.dataset.videoSrc;motionHint.textContent='';const request=++revision;
  picture.removeAttribute('src');picture.alt=items[index].name;status.textContent=t('正在加载图片…');
  caption.textContent=items[index].name+(items.length>1?` · ${index+1} / ${items.length}`:'');
  for(const button of dialog.querySelectorAll('[data-viewer="previous"],[data-viewer="next"]'))button.disabled=items.length<2;
  picture.src=items[index].src;
  void motion(items[index],request);
 }
 function zoom(factor){scale=Math.max(.25,Math.min(8,scale*factor));paint()}
 function build(){
  if(dialog)return;
  dialog=document.createElement('dialog');dialog.id='image-viewer';dialog.setAttribute('aria-label',t('图片查看器'));
  const header=document.createElement('header');caption=document.createElement('strong');caption.id='image-viewer-caption';header.append(caption);
  for(const [action,label,text] of [['previous','上一张','‹'],['next','下一张','›'],['motion','播放实况','▶'],['out','缩小','−'],['zoom','适应窗口','100%'],['in','放大','＋'],['close','关闭','×']]){
   const button=document.createElement('button');button.type='button';button.dataset.viewer=action;button.textContent=text;button.title=t(label);button.setAttribute('aria-label',t(label));header.append(button);
   if(action==='motion'){motionButton=button;button.hidden=true}
   button.onclick=()=>({previous:()=>show(-1),next:()=>show(1),motion:()=>globalThis.StellarVideoViewer?.open(button),out:()=>zoom(1/1.25),in:()=>zoom(1.25),zoom:reset,close:()=>dialog.close()})[action]();
  }
  stage=document.createElement('div');stage.className='image-viewer-stage';picture=document.createElement('img');picture.draggable=false;
  status=document.createElement('p');status.className='image-viewer-status';status.setAttribute('role','status');
  picture.onload=()=>{status.textContent=''};picture.onerror=()=>{status.textContent=t('图片加载失败，请关闭后重试。')};
  motionHint=document.createElement('p');motionHint.className='image-viewer-motion-hint';motionHint.setAttribute('role','status');
  stage.append(picture,status,motionHint);dialog.append(header,stage);document.body.append(dialog);
  stage.addEventListener('wheel',event=>{event.preventDefault();zoom(event.deltaY<0?1.15:1/1.15)},{passive:false});
  stage.ondblclick=()=>scale===1?zoom(2):reset();
  stage.onpointerdown=event=>{if(event.button!==0)return;drag={id:event.pointerId,x:event.clientX-x,y:event.clientY-y};stage.setPointerCapture(event.pointerId)};
  stage.onpointermove=event=>{if(drag&&drag.id===event.pointerId){x=event.clientX-drag.x;y=event.clientY-drag.y;paint()}};
  stage.onpointerup=stage.onpointercancel=()=>{drag=null};
  // Only a press and release outside the frame dismisses the viewer; panning stays local.
  const outside=event=>{const rect=dialog.getBoundingClientRect();return event.clientX<rect.left||event.clientX>rect.right||event.clientY<rect.top||event.clientY>rect.bottom};
  let backdropPress=false;
  dialog.addEventListener('pointerdown',event=>{backdropPress=event.button===0&&outside(event)});
  dialog.addEventListener('pointerup',event=>{if(backdropPress&&outside(event))dialog.close();backdropPress=false});
  dialog.addEventListener('pointercancel',()=>{backdropPress=false});
  dialog.addEventListener('keydown',event=>{
   if(event.key==='Escape'){event.preventDefault();event.stopPropagation();dialog.close();return}
   const action={ArrowLeft:()=>show(-1),ArrowRight:()=>show(1),'+':()=>zoom(1.25),'=':()=>zoom(1.25),'-':()=>zoom(1/1.25),'0':reset}[event.key];
   if(action){event.preventDefault();event.stopPropagation();action()}
  },true);
  dialog.addEventListener('close',()=>{revision++;catalogs.clear();picture.removeAttribute('src');items=[];drag=null;if(opener?.isConnected)opener.focus()});
 }
 function open(images,selected=0,trigger=null){
  if(!images.length)return;build();items=images;index=Math.max(0,Math.min(selected,items.length-1));opener=trigger;
  dialog.setAttribute('aria-label',t('图片查看器'));
  const labels={previous:'上一张',next:'下一张',motion:'播放实况',out:'缩小',zoom:'适应窗口',in:'放大',close:'关闭'};
  for(const button of dialog.querySelectorAll('[data-viewer]')){button.title=t(labels[button.dataset.viewer]);button.setAttribute('aria-label',button.title)}
  motionButton.textContent='▶ '+t('实况');
  show();if(!dialog.open)dialog.showModal();dialog.querySelector('[data-viewer="close"]').focus();
 }
 document.addEventListener('click',event=>{
  const trigger=event.target.closest('[data-image-view]');if(!trigger)return;
  const group=trigger.closest('.note-images,.message-images,.bundle-files,.material-grid,#attachments,#append-files')||trigger.parentElement;
  const nodes=[...group.querySelectorAll('[data-image-view]')];
  const images=nodes.map(node=>{const img=node.matches('img')?node:node.querySelector('img');return {src:node.dataset.imageSrc||img.currentSrc||img.src,name:img.alt||t('图片')}});
  event.preventDefault();event.stopImmediatePropagation();open(images,nodes.indexOf(trigger),trigger);
 },true);
 // Capture before app.js, keeping zoom shortcuts local to the image viewer.
 document.addEventListener('keydown',event=>{if(dialog?.open&&(event.metaKey||event.ctrlKey)&&['+','=','-','0'].includes(event.key)){event.preventDefault();event.stopImmediatePropagation();event.key==='0'?reset():zoom(event.key==='-'?1/1.25:1.25)}},true);
 globalThis.StellarImageViewer={open};
})();
