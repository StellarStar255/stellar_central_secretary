/* Local image viewing stays inside the app, above the current detail dialog. */
(()=>{
 const t=value=>StellarI18n.t(value);
 let dialog,stage,picture,caption,status,items=[],index=0,scale=1,x=0,y=0,drag=null,opener;
 function paint(){picture.style.transform=`translate(${x}px,${y}px) scale(${scale})`;dialog.querySelector('[data-viewer="zoom"]').textContent=Math.round(scale*100)+'%'}
 function reset(){scale=1;x=y=0;paint()}
 function show(offset=0){
  index=(index+offset+items.length)%items.length;reset();
  picture.removeAttribute('src');picture.alt=items[index].name;status.textContent=t('正在加载图片…');
  caption.textContent=items[index].name+(items.length>1?` · ${index+1} / ${items.length}`:'');
  for(const button of dialog.querySelectorAll('[data-viewer="previous"],[data-viewer="next"]'))button.disabled=items.length<2;
  picture.src=items[index].src;
 }
 function zoom(factor){scale=Math.max(.25,Math.min(8,scale*factor));paint()}
 function build(){
  if(dialog)return;
  dialog=document.createElement('dialog');dialog.id='image-viewer';dialog.setAttribute('aria-label',t('图片查看器'));
  const header=document.createElement('header');caption=document.createElement('strong');caption.id='image-viewer-caption';header.append(caption);
  for(const [action,label,text] of [['previous','上一张','‹'],['next','下一张','›'],['out','缩小','−'],['zoom','适应窗口','100%'],['in','放大','＋'],['close','关闭','×']]){
   const button=document.createElement('button');button.type='button';button.dataset.viewer=action;button.textContent=text;button.title=t(label);button.setAttribute('aria-label',t(label));header.append(button);
   button.onclick=()=>({previous:()=>show(-1),next:()=>show(1),out:()=>zoom(1/1.25),in:()=>zoom(1.25),zoom:reset,close:()=>dialog.close()})[action]();
  }
  stage=document.createElement('div');stage.className='image-viewer-stage';picture=document.createElement('img');picture.draggable=false;
  status=document.createElement('p');status.className='image-viewer-status';status.setAttribute('role','status');
  picture.onload=()=>{status.textContent=''};picture.onerror=()=>{status.textContent=t('图片加载失败，请关闭后重试。')};
  stage.append(picture,status);dialog.append(header,stage);document.body.append(dialog);
  stage.addEventListener('wheel',event=>{event.preventDefault();zoom(event.deltaY<0?1.15:1/1.15)},{passive:false});
  stage.ondblclick=()=>scale===1?zoom(2):reset();
  stage.onpointerdown=event=>{if(event.button!==0)return;drag={id:event.pointerId,x:event.clientX-x,y:event.clientY-y};stage.setPointerCapture(event.pointerId)};
  stage.onpointermove=event=>{if(drag&&drag.id===event.pointerId){x=event.clientX-drag.x;y=event.clientY-drag.y;paint()}};
  stage.onpointerup=stage.onpointercancel=()=>{drag=null};
  dialog.addEventListener('keydown',event=>{
   if(event.key==='Escape'){event.preventDefault();event.stopPropagation();dialog.close();return}
   const action={ArrowLeft:()=>show(-1),ArrowRight:()=>show(1),'+':()=>zoom(1.25),'=':()=>zoom(1.25),'-':()=>zoom(1/1.25),'0':reset}[event.key];
   if(action){event.preventDefault();event.stopPropagation();action()}
  },true);
  dialog.addEventListener('close',()=>{picture.removeAttribute('src');items=[];drag=null;if(opener?.isConnected)opener.focus()});
 }
 function open(images,selected=0,trigger=null){
  if(!images.length)return;build();items=images;index=Math.max(0,Math.min(selected,items.length-1));opener=trigger;
  dialog.setAttribute('aria-label',t('图片查看器'));
  const labels={previous:'上一张',next:'下一张',out:'缩小',zoom:'适应窗口',in:'放大',close:'关闭'};
  for(const button of dialog.querySelectorAll('[data-viewer]')){button.title=t(labels[button.dataset.viewer]);button.setAttribute('aria-label',button.title)}
  show();if(!dialog.open)dialog.showModal();dialog.querySelector('[data-viewer="close"]').focus();
 }
 document.addEventListener('click',event=>{
  const trigger=event.target.closest('[data-image-view]');if(!trigger)return;
  const group=trigger.closest('.note-images,.message-images,.bundle-files,#attachments,#append-files')||trigger.parentElement;
  const nodes=[...group.querySelectorAll('[data-image-view]')];
  const images=nodes.map(node=>{const img=node.matches('img')?node:node.querySelector('img');return {src:img.currentSrc||img.src,name:img.alt||t('图片')}});
  event.preventDefault();event.stopImmediatePropagation();open(images,nodes.indexOf(trigger),trigger);
 },true);
 // Capture before app.js, keeping zoom shortcuts local to the image viewer.
 document.addEventListener('keydown',event=>{if(dialog?.open&&(event.metaKey||event.ctrlKey)&&['+','=','-','0'].includes(event.key)){event.preventDefault();event.stopImmediatePropagation();event.key==='0'?reset():zoom(event.key==='-'?1/1.25:1.25)}},true);
 globalThis.StellarImageViewer={open};
})();
