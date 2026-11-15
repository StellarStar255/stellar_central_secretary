/* Paths come from archived source text; never turn them into file:// URLs. */
globalThis.StellarLocalPaths={note(text){
 const value=String(text||'').trim(),lines=value.split('\n').map(line=>line.trim()).filter(Boolean);
 if(value.length>8192||lines.length<1||lines.length>2||/[?？]|^(?:请问|为什么|怎么|如何|解释|分析|比较|查找|what\b|how\b|why\b|compare\b)|(?:是什么|在哪里|怎么办|吗|呢)/i.test(lines[0]))return null;
 const line=lines.at(-1),match=/^(?:(.{1,100}?)[:：]\s*)?["'`]?((?:[A-Za-z]:[\\/]|~[\\/]|\/(?!\/))[^\r\n]+?)["'`]?$/u.exec(line);
 if(!match||/https?:\/\//i.test(value))return null;
 const path=match[2].replace(/[.,;，。；]+$/u,''),title=(lines.length===2?lines[0]:match[1]||path.replaceAll('\\','/').replace(/\/$/,'').split('/').at(-1)).replace(/[:：]$/,'');
 return {path,title};
},bind(root,item,{api,toast}){
 const paths=(item.local_paths||[]).slice().sort((a,b)=>b.length-a.length);
 if(!paths.length)return;
 const walker=document.createTreeWalker(root,NodeFilter.SHOW_TEXT);
 const nodes=[];while(walker.nextNode())if(!walker.currentNode.parentElement.closest('a,button,summary'))nodes.push(walker.currentNode);
 for(const node of nodes){
  const text=node.textContent,fragment=document.createDocumentFragment();let offset=0,changed=false;
  while(offset<text.length){
   let start=text.length,path='';
   for(const value of paths){const index=text.indexOf(value,offset);if(index>=0&&index<start){start=index;path=value}}
   if(!path)break;
   fragment.append(document.createTextNode(text.slice(offset,start)));
   const link=document.createElement('span');link.className='local-path';link.role='link';link.tabIndex=0;link.textContent=path;
   link.title=StellarI18n.t('双击打开文件夹或定位文件；也可按 Enter');
   let opening=false;
   const open=async event=>{
    event.preventDefault();event.stopPropagation();if(opening)return;opening=true;
    try{const result=await api('/api/items/'+item.id+'/open-local-path',{path});toast(StellarI18n.t(result.directory?'已打开本地文件夹':'已在文件夹中定位文件'))}
    catch(error){toast(error.message)}finally{opening=false}
   };
   link.ondblclick=open;link.onkeydown=event=>{if(event.key==='Enter')void open(event)};
   fragment.append(link);offset=start+path.length;changed=true;
  }
  if(changed){fragment.append(document.createTextNode(text.slice(offset)));node.replaceWith(fragment)}
 }
}};
