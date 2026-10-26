const {t,ui}=globalThis.StellarI18n;
/* Local, escaped rendering only: archived HTML is never inserted as markup. */
const readerEscape = value => String(value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function readerInline(text){
 const pattern=/(`[^`\n]+`|\*\*[^*\n]+\*\*|\[[^\]\n]+\]\(https?:\/\/[^\s)]+\))/g;
 let html='',offset=0;
 for(const match of text.matchAll(pattern)){
  html+=readerEscape(text.slice(offset,match.index));const token=match[0];
  if(token.startsWith('`'))html+='<code>'+readerEscape(token.slice(1,-1))+'</code>';
  else if(token.startsWith('**'))html+='<strong>'+readerEscape(token.slice(2,-2))+'</strong>';
  else{const split=token.indexOf('](');html+='<a target="_blank" rel="noopener noreferrer" href="'+readerEscape(token.slice(split+2,-1))+'">'+readerEscape(token.slice(1,split))+'</a>'}
  offset=match.index+token.length;
 }
 return html+readerEscape(text.slice(offset));
}
function readerChart(raw){
 try{
  if(raw.length>160000)throw Error('size');
  const chart=JSON.parse(raw),tags=new Set(['svg','g','path','line','polyline','polygon','rect','circle','ellipse','text','tspan']);
  const attrs=new Set(['viewBox','width','height','x','y','x1','x2','y1','y2','cx','cy','r','rx','ry','d','points','transform','fill','stroke','stroke-width','stroke-dasharray','opacity','fill-opacity','stroke-opacity','text-anchor','dominant-baseline','font-size','font-weight','dx','dy']);
  const color=value=>typeof value==='string'&&/^(?:#[a-f\d]{3,8}|(?:rgba?|hsla?|oklch|oklab|lab|lch|color)\([a-z\d.,%+\/\s-]+\)|[a-z]+)$/i.test(value)?value:'white';
  let count=0;
  const draw=(node,depth=0)=>{
   if(!node||!tags.has(node.tag)||++count>1500||depth>40)throw Error('shape');
   let properties='';
   for(const [key,value] of Object.entries(node.attrs||{})){
    if(!attrs.has(key)||!['string','number'].includes(typeof value)||String(value).length>50000||/url\s*\(|javascript:|data:|[<>]/i.test(String(value)))continue;
    properties+=' '+key+'="'+readerEscape(value)+'"';
   }
   return '<'+node.tag+properties+'>'+readerEscape(node.text||'')+(node.children||[]).map(n=>draw(n,depth+1)).join('')+'</'+node.tag+'>';
  };
  if(chart.version!==1||chart.tree?.tag!=='svg')throw Error('version');
  const view=String(chart.tree.attrs?.viewBox||'').trim().split(/[ ,]+/).map(Number);
  if(view.length!==4||!view.every(Number.isFinite)||view[2]<=0||view[3]<=0||view.some(v=>Math.abs(v)>10000))throw Error('bounds');
  chart.tree.children=[{tag:'rect',attrs:{x:view[0],y:view[1],width:view[2],height:view[3],fill:color(chart.background)},children:[]},...(chart.tree.children||[])];
  const legend=(Array.isArray(chart.legend)?chart.legend:[]).slice(0,50).filter(item=>item&&typeof item.label==='string').map(item=>'<span><svg viewBox="0 0 12 12" width="12" height="12" aria-hidden="true"><circle cx="6" cy="6" r="5" fill="'+readerEscape(color(item.color))+'"></circle></svg>'+readerEscape(item.label.slice(0,200))+'</span>').join('');
  return '<figure class="reader-chart">'+(typeof chart.title==='string'&&chart.title?'<div class="reader-chart-title">'+readerEscape(chart.title.slice(0,300))+'</div>':'')+t('<div class="reader-chart-scroll" role="img" aria-label="归档图表快照">')+draw(chart.tree)+'</div>'+(legend?'<div class="reader-chart-legend">'+legend+'</div>':'')+(typeof chart.dataText==='string'&&chart.dataText?t('<details class="reader-chart-data"><summary>查看图表数据与说明</summary><pre>')+readerEscape(chart.dataText.slice(0,60000))+'</pre></details>':'')+t('<figcaption>图表快照 · 悬浮提示和交互请打开原链接查看</figcaption></figure>');
 }catch{return t('<p class="reader-chart-unavailable">图表快照无法显示，请打开原链接查看。</p>')}
}
function readerTable(rows){
 const width=Math.max(...rows.map(row=>row.length));
 const cell=value=>readerInline(String(value||'').replace(/&#124;|\\\|/g,'|'));
 return t('<div class="reader-table-scroll" role="region" aria-label="数据表格" tabindex="0"><table><thead><tr>')+Array.from({length:width},(_,i)=>'<th scope="col">'+cell(rows[0][i])+'</th>').join('')+'</tr></thead><tbody>'+rows.slice(1).map(row=>'<tr>'+Array.from({length:width},(_,i)=>'<td>'+cell(row[i])+'</td>').join('')+'</tr>').join('')+'</tbody></table></div>';
}
function readerMarkdown(text){
 const lines=text.replace(/\r\n?/g,'\n').split('\n');let html='',paragraph=[],list=null;
 const flushParagraph=()=>{if(paragraph.length){html+='<p>'+paragraph.map(readerInline).join('<br>')+'</p>';paragraph=[]}};
 const closeList=()=>{if(list){html+='</'+list+'>';list=null}};
 for(let i=0;i<lines.length;i++){
  const line=lines[i];
  if(/^\s*```/.test(line)){
   flushParagraph();closeList();const code=[];
   while(++i<lines.length&&!/^\s*```/.test(lines[i]))code.push(lines[i]);
   html+=line.trim()==='```stellar-chart'?readerChart(code.join('\n')):'<pre><code>'+readerEscape(code.join('\n'))+'</code></pre>';continue;
  }
  const pipeRow=value=>{let row=value.trim().replace(/^\|/,'').replace(/(?<!\\)\|$/,'').split(/(?<!\\)\|/);return row.map(v=>v.trim())};
  const separator=lines[i+1]&&pipeRow(lines[i+1]);
  if(line.includes('|')&&separator?.length>=2&&separator.every(v=>/^:?-{3,}:?$/.test(v))){
   flushParagraph();closeList();const rows=[pipeRow(line)];i++;
   while(i+1<lines.length&&lines[i+1].trim()&&lines[i+1].includes('|'))rows.push(pipeRow(lines[++i]));
   html+=readerTable(rows);continue;
  }
  if(line.includes('\t')&&lines[i+1]?.includes('\t')){
   flushParagraph();closeList();const rows=[line.trim().split('\t')];
   while(i+1<lines.length&&lines[i+1].includes('\t'))rows.push(lines[++i].trim().split('\t'));
   html+=readerTable(rows);continue;
  }
  if(!line.trim()){flushParagraph();closeList();continue}
  const heading=line.match(/^\s{0,3}(#{1,6})\s+(.+)$/);
  if(heading){flushParagraph();closeList();const level=Math.min(heading[1].length+1,6);html+=`<h${level}>${readerInline(heading[2])}</h${level}>`;continue}
  if(/^\s*(?:---+|\*\*\*+)\s*$/.test(line)){flushParagraph();closeList();html+='<hr>';continue}
  const bullet=line.match(/^\s*(?:([-*+])\s+|\d+[.．、)]\s*)(.+)$/);
  if(bullet){flushParagraph();const type=bullet[1]?'ul':'ol';if(list!==type){closeList();html+='<'+type+'>';list=type}html+='<li>'+readerInline(bullet[2])+'</li>';continue}
  if(/^\s*>\s?/.test(line)){flushParagraph();closeList();html+='<blockquote>'+readerInline(line.replace(/^\s*>\s?/,''))+'</blockquote>';continue}
  closeList();paragraph.push(line);
 }
 flushParagraph();closeList();return html;
}
function parseArchivedConversation(text){
 const turns=[];let current=null,fenced=false;
 for(const line of text.replace(/\r\n?/g,'\n').split('\n')){
  if(/^\s*```/.test(line))fenced=!fenced;
  const role=!fenced&&line.trim().match(/^(用户|你|User|Human|ChatGPT|Claude|助手|Assistant)[:：]\s*$/i);
  if(role){if(current)turns.push({...current,text:current.lines.join('\n').trim()});
   const user=/^(用户|你|user|human)$/i.test(role[1]);current={role:user?'user':'assistant',label:user?t('你'):/^claude$/i.test(role[1])?'Claude':/^chatgpt$/i.test(role[1])?'ChatGPT':t('助手'),lines:[]};
  }else if(current)current.lines.push(line);
  else if(line.trim())return [];
 }
 if(current)turns.push({...current,text:current.lines.join('\n').trim()});
 return turns.length>=2&&turns.some(t=>t.role==='user')&&turns.some(t=>t.role==='assistant')?turns:[];
}
function renderArchivedBody(item){
 const text=item.text||'',turns=item.kind==='file'||item.kind==='note'?[]:parseArchivedConversation(text);
 if(!turns.length)return ui`<h3>正文 <span class="muted">${text.length.toLocaleString()} 字符</span></h3><div class="detail-text">${readerEscape(text||t('还没有正文。点击「补充 / 编辑正文」，或使用浏览器采集扩展。'))}</div>`;
 return ui`<section class="archive-conversation" aria-label="已归档的对话"><div class="reader-heading"><h3>会话记录</h3><span>${turns.length} 条消息 · 点击角色可收起</span></div>${turns.map((turn,index)=>`<details class="reader-turn reader-${turn.role}" open><summary><span class="reader-avatar" aria-hidden="true">${turn.role==='user'?'<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.6"><circle cx="12" cy="8" r="3.2"/><path d="M5 21v-2a7 7 0 0 1 14 0v2"/></svg>':'✳'}</span><span>${readerEscape(turn.label)}</span><span class="reader-turn-number">${String(index+1).padStart(2,'0')}</span><span class="reader-chevron" aria-hidden="true">⌄</span></summary><div class="reader-message ${turn.role==='assistant'?'reader-prose':''}">${turn.role==='user'?readerEscape(turn.text):readerMarkdown(turn.text)}</div></details>`).join('')}<details class="reader-original"><summary>查看原始文本 · ${text.length.toLocaleString()} 字符</summary><div>${readerEscape(text)}</div></details></section>`;
}

const $ = s => document.querySelector(s);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const states = new Proxy({queued_capture:'等待读取',pending:'等待整理',processing:'正在整理',ready:'已整理',error:'待重试',needs_content:'待补正文',confirming_login:'正在准备读取',waiting_browser_close:'等待专用窗口退出',opening_browser:'正在打开浏览器',waiting_login:'等待你登录',reading:'正在读取正文'},{get:(values,key)=>t(values[key]||'')});
const captureActions=new Map();
let lastMessageMarkup='';
let supportsCapture=false;
let supportsWebCapture=false;
let latestStatus=null,lastUpdateState=null,uiLanguageRevision=0,languageChanging=false;
let token='', allItems=[], selectedId='', detailVersion='', searchTimer, attachedFiles=[], sending=false;
const storageKey='stellar.conversations.v1';
let conversations=[], activeId='';
let sharedChatsReady=false,historyLoaded=false,sharedChatSaves=Promise.resolve();
try { const saved=JSON.parse(localStorage.getItem(storageKey)||'{}'); conversations=Array.isArray(saved.conversations)?saved.conversations:[];activeId=saved.activeId||''; } catch {}
const uid=()=>crypto.randomUUID();
function currentChat(){return conversations.find(c=>c.id===activeId)}
function writeLocalChats(){if(globalThis.StellarArchiveActions)conversations=StellarArchiveActions.clean(conversations);if(!conversations.some(chat=>chat.id===activeId))activeId='';try{localStorage.setItem(storageKey,JSON.stringify({conversations,activeId}))}catch{toast(t('本机对话记录存储空间已满；归档资料仍保存在知识库中。'))}}
function saveChats(){writeLocalChats();if(sharedChatsReady){const snapshot=JSON.parse(JSON.stringify({conversations,activeId}));sharedChatSaves=sharedChatSaves.then(()=>api('/api/conversations',snapshot)).catch(e=>toast(t('对话同步未完成：')+e.message))}}
function mergeChats(remote){globalThis.StellarArchiveActions?.accept(remote);if(globalThis.StellarArchiveActions)conversations=StellarArchiveActions.clean(conversations);const merged=new Map((remote.conversations||[]).map(c=>[c.id,c]));for(const chat of conversations){if(!merged.has(chat.id)||(chat.updated||0)>(merged.get(chat.id).updated||0))merged.set(chat.id,chat)}conversations=[...merged.values()].sort((a,b)=>(b.updated||0)-(a.updated||0));writeLocalChats()}
async function loadSharedChats(){const remote=await api('/api/conversations');if(!conversations.length&&!activeId)activeId=remote.activeId||'';mergeChats(remote);const saved=await api('/api/conversations',{conversations,activeId});mergeChats(saved);sharedChatsReady=true;historyLoaded=true;writeLocalChats()}
async function pullSharedChats(){if(!sharedChatsReady||sending)return;await sharedChatSaves;mergeChats(await api('/api/conversations'))}
async function switchInterface(mode){if(sending){toast(t('请等待当前消息处理完成后再切换'));return}await sharedChatSaves;await api('/api/conversations',{conversations,activeId});await api('/api/interface',{mode});toast(mode==='desktop'?t('正在打开桌面窗口'):t('正在打开网页模式'))}
$('#interface-toggle').onclick=()=>busy($('#interface-toggle'),()=>switchInterface((globalThis.__stellarDesktop===true||(globalThis.location?.search||'').includes('desktop=1'))?'browser':'desktop'));

function toast(message){$('#toast').textContent=message;$('#toast').classList.add('show');clearTimeout(toast.timer);toast.timer=setTimeout(()=>$('#toast').classList.remove('show'),4200)}
async function api(path,body,retry=true){
 const controller=new AbortController();const timer=setTimeout(()=>controller.abort(),path==='/api/ask'?300000:path==='/api/ingest'?90000:12000);
 let response;
 try{response=await fetch(path,body===undefined?{signal:controller.signal}:{method:'POST',headers:{'Content-Type':'application/json','X-Knowledge-Token':token},body:JSON.stringify(body),signal:controller.signal})}
 catch(e){throw Error(e.name==='AbortError'?t('本地服务响应超时，请检查程序是否仍在运行。'):e.message)}
 finally{clearTimeout(timer)}
 const data=await response.json();
 if(response.status===403&&body!==undefined&&retry){const status=await api('/api/status');token=status.token;return api(path,body,false)}
 if(!response.ok){const error=new Error(StellarI18n.message(data.error)||t('请求失败'));error.originalMessage=data.error;throw error}return data;
}

async function busy(button,action,label=t('处理中…')){const old=button.textContent;button.disabled=true;button.textContent=label;try{return await action()}catch(e){toast(e.message)}finally{button.disabled=false;button.textContent=old}}
function displayCategory(value){return value==='未分类'?t('未分类'):value}
function date(value){return new Date(value).toLocaleDateString(StellarI18n.locale,{month:'short',day:'numeric'})}
function newChat(){activeId='';for(const file of attachedFiles)releaseAttachment(file);attachedFiles=[];$('#message-input').value='';resizeInput();renderAttachments();renderChat();renderSidebar();saveChats();$('#message-input').focus()}
function renderSidebar(){
 $('#conversations').innerHTML=(historyLoaded?conversations:[]).map(c=>`<button class="conversation ${c.id===activeId?'active':''}" data-chat="${esc(c.id)}">${esc(c.title)}</button>`).join('');
 $('#conversations').querySelectorAll('button').forEach(b=>b.onclick=()=>{activeId=b.dataset.chat;saveChats();renderChat();renderSidebar();document.body.classList.remove('mobile-sidebar')});
 $('#recent-items').innerHTML=allItems.slice(0,6).map(i=>`<button class="recent-item" data-id="${i.id}" title="${esc(i.title)}"><span>${i.kind==='link'?'↗':i.kind==='file'?'▧':'✎'}</span>${esc(i.title)}</button>`).join('');
 bindDetails($('#recent-items'));
}
function bindDetails(container){container.querySelectorAll('[data-id]').forEach(b=>b.onclick=()=>detail(b.dataset.id).catch(e=>toast(e.message)))}
function archiveCard(id){const item=allItems.find(i=>i.id===id);if(!item)return '';return ui`<button class="archive-card" data-id="${id}"><div class="archive-top"><span class="file-icon">${item.kind==='link'?'↗':item.kind==='file'?'▧':'✎'}</span><div><strong>${esc(item.title)}</strong><small>${esc(displayCategory(item.category))} · 查看资料与原件 ↗</small></div><span class="archive-status">${item.tags?.includes('部分对话')?t('部分对话 · '):''}${itemState(item)||''}</span></div>${item.summary?`<p class="archive-summary">${esc(item.summary)}</p>`:''}</button>${captureControls(item)}`}
function renderChat(scroll=true){
 if(globalThis.StellarArchiveActions)conversations=StellarArchiveActions.clean(conversations);
 const chat=historyLoaded?currentChat():null;const messages=chat?.messages||[];
 const container=$('#chat-scroll');const atBottom=container.scrollHeight-container.scrollTop-container.clientHeight<120;
 $('#workspace').classList.toggle('empty',messages.length===0);
 const markup=messages.map(m=>`<article class="message ${m.role} ${m.pending?'pending':''} ${m.error?'error':''}" data-message="${esc(m.id)}">${m.role==='assistant'?'<div class="assistant-label"><span>✳</span>Secretary</div>':''}${m.files?.length?`<div class="user-files">${m.files.map(f=>`<span>▧ ${esc(f)}</span>`).join('')}</div>`:''}${m.images?.length&&globalThis.StellarBundles?StellarBundles.chatImages(m.images):''}${m.text?`<div class="message-body">${esc(m.text)}</div>`:''}${(m.items||[]).map(archiveCard).join('')}${m.sources?.length?`<div class="source-list">${m.sources.map(s=>ui`<button class="source" data-id="${s.item_id}">[${s.number}] ${esc(s.title)}<br><span>查看来源 ↗</span></button>`).join('')}</div>`:''}${m.role==='assistant'&&!m.pending?ui`<div class="message-tools"><button data-copy="${esc(m.id)}">复制回答</button></div>`:''}</article>`).join('');
 if(markup===lastMessageMarkup)return;lastMessageMarkup=markup;$('#messages').innerHTML=markup;
 bindDetails($('#messages'));$('#messages').querySelectorAll('[data-copy]').forEach(b=>b.onclick=()=>{const message=messages.find(m=>m.id===b.dataset.copy);navigator.clipboard.writeText(message.text).then(()=>toast(t('已复制'))).catch(()=>toast(t('复制失败，请手动选择文字')))});
 if(scroll||atBottom)container.scrollTop=container.scrollHeight;
}
function addMessage(chat,role,text,extras={}){const message={id:uid(),role,text,...extras};chat.messages.push(message);chat.updated=Date.now();saveChats();if(chat.id===activeId)renderChat();return message}
function updateMessage(chat,message,values){Object.assign(message,values);chat.updated=Date.now();saveChats();if(chat.id===activeId)renderChat()}
async function refresh(){
 const contentRevision=contentFontChanging?-1:contentFontRevision,fontRevision=fontSizeChanging?-1:fontSizeRevision,languageRevision=uiLanguageRevision;const languageStatus=await api('/api/status');syncContentFontScale(languageStatus.settings,contentRevision);if(!fontSizeChanging&&fontRevision===fontSizeRevision)applyUIFontSize(languageStatus.settings.ui_font_size||14);const language=languageStatus.settings.ui_language||'zh';if(!languageChanging&&languageRevision===uiLanguageRevision&&language!==StellarI18n.language)await applyUILanguage(language);
 try{await pullSharedChats()}catch(e){sharedChatsReady=false;toast(t('对话同步未完成，知识库仍可使用：')+e.message)}
 allItems=(await api('/api/items')).filter(item=>!globalThis.StellarArchiveActions?.isDeleted(item.id));
 for(const [id,action] of captureActions){
  const item=allItems.find(i=>i.id===id);
  if(action.accepted&&item?.state!=='waiting_login')captureActions.delete(id);
  else if(action.accepted&&Date.now()-action.at>30000){action.accepted=false;action.error=true;action.text=t('后台已收到确认，但 30 秒内未进入读取。可以再次确认；若仍停在此处，请停止任务后重试，已保存的浏览器登录状态会保留。')}
 }
 let changed=false;
 for(const chat of conversations)for(const m of chat.messages){
  if(m.role==='assistant'&&!m.pending&&m.archiveOnly&&m.items?.length){
   const text=m.items.map(id=>allItems.find(i=>i.id===id)).filter(Boolean).map(item=>archiveReply({item,created:true})).filter((v,i,a)=>a.indexOf(v)===i).join('\n\n');
   if(text&&text!==m.text){m.text=text;chat.updated=Date.now();changed=true}
  }
 }
 if(changed)saveChats();
 $('#count').textContent=allItems.length;renderSidebar();renderChat(false);
 if($('#library-dialog').open)await renderLibrary();
 if($('#detail-dialog').open&&selectedId&&!$('#detail-edit')&&(!$('#title-editor')||$('#title-editor').hidden)&&(!$('#tag-editor')||$('#tag-editor').hidden)&&!StellarNotes.isDirty(selectedId)){const item=allItems.find(i=>i.id===selectedId);if(item&&item.updated!==detailVersion)await detail(selectedId)}
}
async function renderLibrary(){
 const q=$('#search').value.trim(),kind=$('#kind-filter').value,category=$('#category-filter').value;
 const items=(await api('/api/items?'+new URLSearchParams({q,kind,category}))).filter(item=>!globalThis.StellarArchiveActions?.isDeleted(item.id));
 if(q!==$('#search').value.trim()||kind!==$('#kind-filter').value||category!==$('#category-filter').value)return;
 const cats=[...new Set(allItems.map(i=>i.category))].sort();$('#category-filter').innerHTML=t('<option value="">全部主题</option>')+cats.map(c=>`<option value="${esc(c)}" ${c===category?'selected':''}>${esc(displayCategory(c))}</option>`).join('');
 $('#result-count').textContent=StellarI18n.count(items.length,'份资料','item','items');$('#empty').hidden=items.length>0;
 $('#items').innerHTML=items.map(i=>`<button class="library-row" data-id="${i.id}"><span class="file-icon">${i.kind==='file'?'▧':i.kind==='link'?'↗':'✎'}</span><div class="library-info"><strong>${esc(i.title)}</strong><p>${esc(i.summary||i.error||t('正文已保存，可随时查阅。'))}</p></div><small>${itemState(i)}<br>${date(i.created)}</small></button>`).join('');bindDetails($('#items'));
}
async function openLibrary(){document.body.classList.remove('mobile-sidebar');$('#library-dialog').showModal();await renderLibrary();$('#search').focus()}
$('#library-open').onclick=$('#library-shortcut').onclick=()=>openLibrary().catch(e=>toast(e.message));
$('#search').oninput=()=>{clearTimeout(searchTimer);searchTimer=setTimeout(()=>renderLibrary().catch(e=>toast(e.message)),180)};
$('#kind-filter').onchange=$('#category-filter').onchange=()=>renderLibrary().catch(e=>toast(e.message));
$('#new-chat').onclick=newChat;
$('#sidebar-toggle').onclick=()=>{if(window.innerWidth<=700)document.body.classList.toggle('mobile-sidebar');else{document.body.classList.toggle('sidebar-hidden');$('#workspace').classList.toggle('sidebar-hidden')}};
$('#chat-scroll').onclick=()=>document.body.classList.remove('mobile-sidebar');
// The backdrop targets the dialog itself; its padding and scrollbar do too.
document.querySelectorAll('dialog').forEach(dialog=>{
 let startedOutside=false;
 const outside=event=>{const rect=dialog.getBoundingClientRect();return event.clientX<rect.left||event.clientX>rect.right||event.clientY<rect.top||event.clientY>rect.bottom};
 dialog.addEventListener('pointerdown',event=>{startedOutside=event.button===0&&event.target===dialog&&outside(event)});
 dialog.addEventListener('pointercancel',()=>{startedOutside=false});
 dialog.addEventListener('click',event=>{
  const dismiss=startedOutside&&event.target===dialog&&outside(event);
  startedOutside=false;
  if(dismiss)dialog.close();
 });
 dialog.addEventListener('close',()=>{startedOutside=false});
});
document.addEventListener('keydown',e=>{if((e.metaKey||e.ctrlKey)&&['k','j'].includes(e.key.toLowerCase())){e.preventDefault();e.key.toLowerCase()==='k'?openLibrary().catch(e=>toast(e.message)):newChat()}});
function resizeInput(){const input=$('#message-input');input.style.height='auto';input.style.height=Math.min(input.scrollHeight,220)+'px';updateSend()}
function updateSend(){$('#send-button').disabled=sending||(!$('#message-input').value.trim()&&!attachedFiles.length)}
$('#message-input').oninput=resizeInput;
$('#message-input').onkeydown=e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.isComposing){e.preventDefault();if(!$('#send-button').disabled)$('#composer-form').requestSubmit()}};
const attachmentPreviews=new WeakMap();
const isImageFile=file=>(file.type||'').startsWith('image/')||/\.(png|jpe?g|gif|webp)$/i.test(file.name);
function releaseAttachment(file){const url=attachmentPreviews.get(file);if(url){URL.revokeObjectURL(url);attachmentPreviews.delete(file)}}
function renderAttachments(){
 $('#attachments').innerHTML=attachedFiles.map((file,index)=>{
  let image='';if(isImageFile(file)){try{let url=attachmentPreviews.get(file);if(!url){url=URL.createObjectURL(file);attachmentPreviews.set(file,url)}image='<img src="'+url+'" alt="'+esc(file.name)+'">'}catch{}}
  return ui`<div class="attachment">${image}<span title="${esc(file.name)}">▧ ${esc(file.name)}</span><button type="button" data-remove="${index}" aria-label="移除 ${esc(file.name)}">×</button></div>`;
 }).join('')+(attachedFiles.length?t('<p class="bundle-composer-hint">同次文字、图片和附件将归档在一起。启用 AI 摘要或提问时，文字和支持的图片会发送给所选模型。</p>'):'');
 $('#attachments').querySelectorAll('button').forEach(button=>button.onclick=()=>{const [removed]=attachedFiles.splice(Number(button.dataset.remove),1);releaseAttachment(removed);renderAttachments()});updateSend();
}
function attach(files){for(const file of files){
 if(file.size>50*1024*1024){toast(file.name+t(' 超过 50 MB'));continue}
 if(attachedFiles.length>=20||attachedFiles.reduce((sum,item)=>sum+item.size,0)+file.size>50*1024*1024){toast(t('每次最多 20 个附件，总计不超过 50 MB'));continue}
 if(isImageFile(file)&&attachedFiles.filter(isImageFile).length>=8){toast(t('每次最多 8 张图片'));continue}
 attachedFiles.push(file)
}renderAttachments();$('#message-input').focus()}
$('#attach-button').onclick=()=>$('#file-input').click();$('#file-input').onchange=e=>{attach([...e.target.files]);e.target.value=''};
$('#message-input').addEventListener('paste',event=>{const data=event.clipboardData;if(!data)return;const files=data.files?.length?[...data.files]:Array.from(data.items||[]).filter(item=>item.kind==='file').map(item=>item.getAsFile()).filter(Boolean);if(files.length){event.preventDefault();const text=data.getData('text/plain');if(text){const input=$('#message-input');input.setRangeText(text,input.selectionStart,input.selectionEnd,'end');resizeInput()}attach(files)}});
let dragDepth=0;
window.addEventListener('drop',()=>{dragDepth=0;$('#drag-overlay').hidden=true},true);
window.addEventListener('dragenter',e=>{if([...e.dataTransfer.types].includes('Files')){e.preventDefault();dragDepth++;$('#drag-overlay').hidden=false}});
window.addEventListener('dragover',e=>{if([...e.dataTransfer.types].includes('Files'))e.preventDefault()});
window.addEventListener('dragleave',()=>{dragDepth=Math.max(0,dragDepth-1);if(!dragDepth)$('#drag-overlay').hidden=true});
window.addEventListener('drop',e=>{if(e.dataTransfer.files.length){e.preventDefault();attach([...e.dataTransfer.files])}dragDepth=0;$('#drag-overlay').hidden=true});
document.querySelectorAll('[data-suggestion]').forEach(b=>b.onclick=()=>{if(b.dataset.suggestion==='file')$('#file-input').click();else{$('#message-input').value=b.dataset.suggestion==='archive'?'':t('帮我找一下之前收藏的资料：');$('#message-input').placeholder=b.dataset.suggestion==='archive'?t('在这里粘贴链接，然后按 Enter…'):t('输入你想找的资料或问题…');resizeInput();$('#message-input').focus()}});
async function readFile(file){return new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result.split(',')[1]);reader.onerror=()=>reject(Error(t('无法读取 ')+file.name));reader.readAsDataURL(file)})}
function canReadChatGPT(url){try{const u=new URL(url);return u.protocol==='https:'&&['chatgpt.com','chat.openai.com'].includes(u.hostname)&&/^\/(c|share)\/[a-zA-Z0-9_-]+\/?$/.test(u.pathname)}catch{return false}}
function canReadWebPage(url){try{const u=new URL(url);return ['http:','https:'].includes(u.protocol)&&!u.username&&!u.password&&!/\.(pdf|zip|rar|7z|dmg|exe|docx?|xlsx?|pptx?|png|jpe?g|gif|mp[34])$/i.test(u.pathname)}catch{return false}}
function itemState(item){if(item.state==='needs_content'&&item.addition_count)return t('有追加资料');return item.state==='waiting_login'&&!canReadChatGPT(item.url)?t('等待页面确认'):states[item.state]}
function isReading(item){return ['queued_capture','opening_browser','waiting_login','confirming_login','waiting_browser_close','reading'].includes(item.state)}
function captureControls(item){
 if(!canReadChatGPT(item.url))return webCaptureControls(item);
 const action=captureActions.get(item.id);
 const hasText=item.text_length>0||item.text?.trim()||(item.text_length===undefined&&['error','ready','processing','pending'].includes(item.state));
 const summaryButton=hasText?`<button data-summarize="${item.id}" ${item.state==='processing'?'disabled':''}>${item.state==='processing'?t('摘要生成中…'):item.summary?t('重新生成摘要'):t('重试摘要')}</button>`:'';
 const feedback=action?`<span class="capture-feedback ${action.error?'capture-error':''}" role="status">${esc(action.text)}</span>`:'';
 const pending=action?.pending||action?.accepted&&item.state==='waiting_login';
 const disabled=pending||item.state==='processing'?'disabled aria-busy="true"':'';
 if(isReading(item))return ui`<div class="capture-actions">${feedback}<span>${item.state==='queued_capture'?t('读取任务已排队，可随时停止。'):item.state==='opening_browser'?t('正在启动普通 Chrome…'):item.state==='waiting_login'?t('请在普通 Chrome 中登录并打开目标会话，然后点击下方确认。'):item.state==='confirming_login'?t('已收到登录确认，正在连接原窗口读取正文…'):item.state==='waiting_browser_close'?t('请关闭本项目的专用 Chrome 窗口，程序会自动继续；你的登录资料会保留。'):esc(item.error||t('正在读取会话正文…'))}</span>${item.state==='waiting_login'&&supportsCapture?`<button class="confirm-login" data-confirm-login="${item.id}" ${disabled}>${pending?t('确认中…'):t('我已登录，开始读取')}</button>`:''}<button data-cancel-capture="${item.id}" ${action?.pending?'disabled':''}>停止读取</button></div>`;
 return ui`<div class="capture-actions">${feedback}${item.error&&!item.error.startsWith('会话链接已收藏')?`<span class="capture-error">${esc(StellarI18n.message(item.error.slice(0,450)))}</span>`:''}${summaryButton}<button data-capture="${item.id}" ${disabled}>${!supportsCapture?t('后台需要重启'):item.state==='needs_content'?t('打开普通浏览器登录'):t('重新读取网页')}</button><button data-extension-help>使用常用浏览器采集</button></div>`;
}
function webCaptureControls(item){
 if(!canReadWebPage(item.url))return '';
 const action=captureActions.get(item.id),disabled=action?.pending||item.state==='processing'?'disabled':'';
 const feedback=action?`<span class="capture-feedback" role="status">${esc(action.text)}</span>`:'';
 if(isReading(item))return ui`<div class="capture-actions">${feedback}<span>${item.state==='waiting_login'?t('请在浏览器完成登录并展开目标内容，然后确认读取；只保存已加载的内容。'):esc(StellarI18n.message(item.error||t('正在读取网页…')))}</span>${item.state==='waiting_login'?`<button data-confirm-login="${item.id}" ${disabled}>${t('页面已打开，开始读取')}</button>`:''}<button data-cancel-capture="${item.id}" ${disabled}>停止读取</button></div>`;
 return ui`<div class="capture-actions">${feedback}${item.error?`<span class="capture-error">${esc(StellarI18n.message(item.error.slice(0,450)))}</span>`:''}<button data-capture="${item.id}" ${disabled}>浏览器读取网页</button><button data-extension-help>使用常用浏览器采集</button></div>`;
}
function refreshCaptureUI(){renderChat(false);if($('#detail-dialog').open&&!$('#detail-edit')&&(!$('#title-editor')||$('#title-editor').hidden)&&(!$('#tag-editor')||$('#tag-editor').hidden)&&!StellarNotes.isDirty(selectedId))detail(selectedId).catch(()=>{})}
async function performCaptureAction(id,action){
 if(captureActions.get(id)?.pending)return;
 captureActions.set(id,{pending:true,text:action==='confirm'?t('正在提交登录确认…'):action==='cancel'?t('正在停止读取…'):action==='summary'?t('正在提交摘要任务…'):t('正在提交读取请求…')});refreshCaptureUI();
 try{
  if(action==='summary'){try{await api('/api/items/'+id,{})}catch(e){if(!(e.originalMessage||e.message).includes('正在处理'))throw e}captureActions.set(id,{text:t('摘要任务已提交，使用已保存的正文，无需重新读取网页。')});await refresh()}
  else if(action==='confirm')await confirmLogin(id);
  else if(action==='cancel'){const result=await api('/api/items/'+id+'/cancel-capture',{});captureActions.set(id,{text:result.stopped===true?t('已停止读取，已有资料保持不变。'):t('正在停止读取…')});await refresh()}
  else{await requestCapture(id);captureActions.delete(id)}
 }catch(e){captureActions.set(id,{error:true,text:t('操作失败：')+e.message});toast(e.message)}
 finally{const state=captureActions.get(id);if(state)state.pending=false;refreshCaptureUI()}
}
// Delegate clicks once: polling may update cards without removing their handler.
document.addEventListener('click',event=>{
 const button=event.target.closest?.('[data-confirm-login],[data-capture],[data-cancel-capture],[data-summarize],[data-extension-help]');
 if(!button||button.disabled)return;
 event.preventDefault();
 if(button.hasAttribute('data-extension-help')){$('#extension-dialog').showModal();return}
 if(button.dataset.summarize)void performCaptureAction(button.dataset.summarize,'summary');
 else if(button.dataset.confirmLogin)void performCaptureAction(button.dataset.confirmLogin,'confirm');
 else if(button.dataset.cancelCapture)void performCaptureAction(button.dataset.cancelCapture,'cancel');
 else if(button.dataset.capture)void performCaptureAction(button.dataset.capture,'capture');
});

async function requestCapture(id){
 const status=await api('/api/status');token=status.token;supportsWebCapture=status.capabilities?.generic_page_capture===true;supportsCapture=status.capabilities?.conversation_capture===true&&status.capabilities?.manual_browser_login===true&&status.capabilities?.in_place_browser_read===true;
 $('#service-alert').hidden=supportsCapture;
 if(!(canReadChatGPT(allItems.find(i=>i.id===id)?.url)?supportsCapture:supportsWebCapture))throw Error(t('后台仍是旧版本，没有启动浏览器。请双击「启动知识秘书.command」重启服务，再刷新此页面。'));
 const result=await api('/api/items/'+id+'/capture',{});
 if(result.capture_started!==true)throw Error(t('后台未确认读取任务，浏览器未启动。请重启知识秘书后重试。'));
 if(['needs_content','error'].includes(result.item?.state))throw Error(result.item.error||t('浏览器启动失败，请查看资料详情。'));
 await refresh();
 const current=allItems.find(i=>i.id===id)||result.item;
 if(['needs_content','error'].includes(current?.state))throw Error(current.error||t('浏览器启动失败。'));
 if(!canReadChatGPT(current?.url)){toast(t('请在任务浏览器中登录并展开内容，然后点击「页面已打开，开始读取」。'));return}
 toast(current?.state==='waiting_login'?t('已请求 Chrome 打开会话。请登录后点击「我已登录，开始读取」。'):t('读取任务已提交，正在启动普通 Chrome…'));
}
async function confirmLogin(id){
 const result=await api('/api/items/'+id+'/confirm-login',{});
 if(result.login_confirmed!==true)throw Error(t('后台未确认登录，请重启知识秘书后重试。'));
 if(result.item){const index=allItems.findIndex(i=>i.id===id);if(index>=0)allItems[index]=result.item}
 captureActions.set(id,{accepted:true,at:Date.now(),text:t('后台已收到登录确认。正在连接同一个浏览器窗口，登录状态保持在原实例中。')});
 await refresh();
}

function archiveReply(result){const i=result.item;
 if(canReadChatGPT(i.url)&&i.state==='needs_content'&&!supportsCapture)return t('链接已保存，但当前后台仍是旧版本，尚未启动浏览器读取正文。请双击项目里的「启动知识秘书.command」重启服务，再刷新此页面。');
 if(!canReadChatGPT(i.url)&&isReading(i))return t('正在准备浏览器采集。请在任务网页完成登录并展开要保存的内容，再点击「页面已打开，开始读取」。仅采集已加载内容，成功后按设置关闭本次新开的标签页。');
 if(i.state==='queued_capture')return t('读取任务已排队，可随时停止。');
 if(i.state==='opening_browser')return t('读取任务已提交，正在启动专用浏览器。窗口打开后会提示你登录。');
 if(i.state==='waiting_login')return t('普通 Chrome 已启动。请在该窗口中登录 ChatGPT 并打开目标会话，然后回到这里点击「我已登录，开始读取」。确认后直接从这个浏览器实例读取，窗口会保持打开。');
 if(i.state==='confirming_login')return t('后台已收到登录确认，正在连接原浏览器实例，窗口保持打开。');
 if(i.state==='waiting_browser_close')return t('登录确认已收到。专用浏览器仍占用配置目录，请关闭该专用窗口，程序会等待并继续；登录资料会保留。');
 if(i.state==='reading')return i.error||t('已确认登录，正在识别目标会话消息。');
 if(i.user_context&&!i.text&&!i.summary&&i.state!=='error')return t('已按你提供的说明归档，原链接也已保留；尚未读取网页正文。')+(i.state==='processing'?t('正在根据说明整理摘要。'):'');
 if(i.state==='needs_content'&&i.addition_count)return i.summary?t('已整理这份资料：\n\n')+i.summary:t('追加资料已保存，可打开归档查看；原网页正文尚未读取。');
 if(i.state==='needs_content')return i.url?t('这条资料目前只收藏了链接，还没有读到正文，因此尚未生成总结。')+(canReadChatGPT(i.url)?t('点击下方按钮重新读取；长对话默认只读取最近最多 20 轮，无需加载全部历史。可在「模型与设置」切换范围，需要登录时程序会提示。'):t('可点击「浏览器读取网页」登录并采集已加载内容，也可用扩展或手动补充正文。')):t('原件已保存，但暂未取得正文。')+(i.error?t('原因：')+i.error:t('请在资料详情中查看解析状态。'))+t(' 可打开资料后重新解析原文件，或手动补充正文。');
 if(i.state==='error')return t('正文已保存并建立检索索引，但自动总结失败了。具体原因在资料详情中，可以重新整理。');
 if(i.summary)return t('已整理这份资料：\n\n')+i.summary;
 if(!result.created&&!result.updated)return t('正文已在知识库中。')+(i.state==='processing'?t('正在生成总结，请稍候。'):t('尚未生成总结，可点击资料中的「重新整理」。'));
 return t('已存入知识库，正文现在就可以检索。')+($('#auto-ai').checked?t('我会继续在后台整理摘要和主题，结果会更新在下方。'):t('自动整理已关闭，之后可以在资料详情中生成摘要。'))}

$('#composer-form').onsubmit=async event=>{
 event.preventDefault();if(sending)return;const text=$('#message-input').value.trim(),files=[...attachedFiles],mode=$('#input-mode').value;if(!text&&!files.length)return;
 if(!token){toast(t('服务尚未连接，请稍后重试或刷新页面。'));return}
 let chat=currentChat();if(!chat){chat={id:uid(),title:(text||files[0]?.name||t('新对话')).slice(0,36),messages:[]};conversations.unshift(chat);activeId=chat.id}
 const userMessage=addMessage(chat,'user',text,{files:files.map(f=>f.name)});const response=addMessage(chat,'assistant',t('正在处理…'),{pending:true,items:[]});
 $('#message-input').value='';for(const file of files)releaseAttachment(file);attachedFiles=[];sending=true;renderAttachments();resizeInput();renderSidebar();$('#composer-status').textContent=t('正在处理…');
 const results=[],errors=[];
 try{
  const grouped=files.length>1||files.some(isImageFile)||(files.length&&(text||mode==='ask'));
  if(grouped){
   const asking=mode==='ask'||mode!=='note'&&!!text&&/[?？]|总结|分析|比较|查找|哪些|什么|如何|怎么|为何|是否|能否|解释|帮我|看看|\b(?:summari[sz]e|analy[sz]e|compare|find|which|what|how|why|explain|describe|please)\b/i.test(text);
   updateMessage(chat,response,{text:t('正在保存这组资料…')});
   const attachments=[];for(const file of files)attachments.push({name:file.name,data:await readFile(file)});
   const result=await api('/api/ingest',{text,attachments,defer_summary:asking});results.push(result);response.items.push(result.item.id);
   updateMessage(chat,userMessage,{images:(result.item.attachments||[]).filter(file=>file.media.startsWith('image/')).map(file=>({item_id:result.item.id,id:file.id,name:file.name}))});
   await refresh();response.archiveOnly=!asking;
   let answer=archiveReply(result);
   if(asking){updateMessage(chat,response,{text:t('已归档，正在结合本次文字与附件回答…')});const data=await api('/api/ask',{question:text||t('请概览本次图片和附件'),item_ids:[result.item.id]});answer=data.answer;response.sources=data.sources}
   updateMessage(chat,response,{text:answer,pending:false,error:false});return;
  }
  for(const file of files){updateMessage(chat,response,{text:t('正在归档「')+file.name+'」…'});try{const result=await api('/api/ingest',{filename:file.name,data:await readFile(file)});results.push(result);response.items.push(result.item.id)}catch(e){errors.push(file.name+'：'+e.message)}}
  const urls=mode==='note'?[]:[...new Set(text.match(/https?:\/\/[^\s<>"，。！？；）)]+/g)||[])];
  for(const url of urls){updateMessage(chat,response,{text:t('正在保存链接…')});try{const context=urls.reduce((value,link)=>value.replace(link,''),text).trim();const result=await api('/api/ingest',{url,context});results.push(result);response.items.push(result.item.id)}catch(e){errors.push(url+'：'+e.message)}}
  if(mode==='note'&&text){const result=await api('/api/ingest',{text});results.push(result);response.items.push(result.item.id)}
  await refresh();
  const remaining=urls.reduce((value,url)=>value.replace(url,''),text).trim();
  // URLs and attachments are archived by default. A plain-text turn asks the knowledge base.
  const shouldAsk=mode!=='note'&&text&&(mode==='ask'||!urls.length&&!files.length||/[?？]|总结|分析|比较|查找|找一下|哪些|什么|如何|\b(?:summari[sz]e|analy[sz]e|compare|find|which|what|how|why)\b/i.test(remaining));
  response.archiveOnly=!shouldAsk&&results.length>0&&!errors.length;
  let answer=results.map(archiveReply).filter((v,i,a)=>a.indexOf(v)===i).join('\n\n');
  if(shouldAsk){updateMessage(chat,response,{text:(answer?answer+'\n\n':'')+t('正在检索知识库，整理答案…')});const data=await api('/api/ask',{question:remaining||text});answer+=(answer?'\n\n':'')+data.answer;response.sources=data.sources}
  if(errors.length)answer+=(answer?'\n\n':'')+t('以下资料未能保存：\n')+errors.join('\n');
  updateMessage(chat,response,{text:answer||t('已处理。'),pending:false,error:errors.length>0&&!results.length});
 }catch(e){if(files.length&&!results.length&&activeId===chat.id&&!$('#message-input').value&&!attachedFiles.length){attachedFiles=files;$('#message-input').value=text;renderAttachments();resizeInput()}updateMessage(chat,response,{text:(results.length?t('已保存 ')+results.length+t(' 份资料。\n\n'):'')+t('本次处理未完成：')+e.message,pending:false,error:true})}
 finally{sending=false;$('#composer-status').textContent='';updateSend();$('#message-input').focus();await refresh().catch(()=>{})}
};
async function detail(id){const item=await api('/api/items/'+id);if(globalThis.StellarArchiveActions?.isDeleted(id))return;selectedId=id;detailVersion=item.updated;
 $('#detail-content').innerHTML=ui`<h1><button type="button" id="edit-title" class="detail-title-button" title="点击修改标题" ${item.state==='processing'||isReading(item)?'disabled':''}>${esc(item.title)} <span aria-hidden="true">✎</span></button></h1><form id="title-editor" hidden><label for="rename-title">修改标题</label><input id="rename-title" maxlength="300" required><div class="detail-actions"><button class="primary" id="save-title" type="submit">保存标题</button><button class="secondary" id="cancel-title" type="button">取消</button></div></form><p>${esc(displayCategory(item.category))} · ${date(item.created)} · ${itemState(item)}</p><div class="tags editable-tags" aria-label="资料标签">${item.tags.map((tag,index)=>`<span class="tag"><span>${esc(tag)}</span><button type="button" data-remove-tag="${index}" aria-label="${esc(t('删除标签：')+tag)}" title="${esc(t('删除标签：')+tag)}">×</button></span>`).join('')}<button type="button" id="add-tag" class="tag-add">＋ 添加标签</button></div><form id="tag-editor" hidden><label for="tag-input">新标签</label><div class="tag-entry"><input id="tag-input" maxlength="60" placeholder="输入标签，按 Enter 添加" autocomplete="off"><button type="submit" class="primary" id="save-tag">添加</button><button type="button" class="secondary" id="cancel-tag">取消</button></div><p class="muted">标签参与搜索；手动修改后，重新整理会保留这些标签。</p></form><div class="detail-actions">${item.url?ui`<a class="primary" href="${esc(item.url)}" target="_blank" rel="noopener noreferrer">打开原链接 ↗</a><button class="secondary" id="copy-url">复制链接</button>`:''}${item.filename?ui`<a class="secondary" href="/api/items/${id}/file">下载原文件</a><button class="secondary" id="reparse-file" ${item.state==='processing'?'disabled':''}>重新解析原文件</button>`:''}${/\.pdf$/i.test(item.filename||'')?ui`<a class="secondary" id="open-pdf-browser" href="/api/items/${id}/preview" target="_blank" rel="noopener noreferrer">浏览器打开 PDF ↗</a><button class="secondary" id="open-pdf-default">默认程序打开</button><button class="secondary" id="full-pdf-summary" ${item.state==='processing'?'disabled':''}>生成全文摘要</button>`:''}<button class="secondary" id="append-material" ${item.append_busy?'disabled':''}>追加资料</button><button class="secondary" id="edit-content">补充 / 编辑正文</button><button class="secondary" id="retry-ai" ${item.state==='processing'||isReading(item)?'disabled':''}>重新整理</button></div>${item.error?`<p class="warning">${esc(StellarI18n.message(item.error))}</p>`:''}${captureControls(item)}${globalThis.StellarBundles?StellarBundles.render(item):''}${item.user_context?ui`<h3>你的链接说明</h3><div id="link-context" class="detail-text">${esc(item.user_context)}</div>`:''}${StellarNotes.render(item)}<h3>资料摘要</h3><div class="detail-text">${esc(item.summary||t('尚未生成 AI 摘要。正文和原件可独立保存、搜索及下载。'))}</div>${item.vision_text?ui`<h3>图片解读（AI 生成，请核对原图）</h3><div class="detail-text">${esc(item.vision_text)}</div>`:''}${renderArchivedBody(item)}${globalThis.StellarAdditions?StellarAdditions.render(item):''}`;
 const cancelTitle=()=>{$('#title-editor').hidden=true;$('#edit-title').hidden=false;$('#edit-content').disabled=isReading(item);$('#edit-title').focus()};
 StellarNotes.bind(item,{api,toast,onSaved:()=>{detailVersion=''}});
 if(globalThis.StellarAdditions){const options={api,toast,onSaved:async()=>{await detail(id);await refresh()}};$('#append-material').onclick=()=>StellarAdditions.open(item,{...options,autoAI:$('#auto-ai').checked});StellarAdditions.bind(item,options)}
 $('#add-tag').onclick=()=>{$('#tag-editor').hidden=false;$('#add-tag').hidden=true;$('#tag-input').focus()};
 const closeTagEditor=()=>{$('#tag-editor').hidden=true;$('#add-tag').hidden=false;$('#tag-input').value=''};
 $('#cancel-tag').onclick=closeTagEditor;
 $('#tag-input').onkeydown=event=>{if(event.key==='Escape'){event.preventDefault();event.stopPropagation();closeTagEditor()}};
 const saveTags=async tags=>{await api('/api/items/'+id+'/tags',{tags,expected_tags:item.tags});await detail(id);await refresh();toast(t('标签已保存，已更新搜索'))};
 $('#tag-editor').onsubmit=event=>{event.preventDefault();const tag=$('#tag-input').value.trim();if(!tag)return;if(item.tags.some(value=>value.toLocaleLowerCase()===tag.toLocaleLowerCase())){toast(t('这个标签已经存在'));return}busy($('#save-tag'),()=>saveTags([...item.tags,tag]))};
 document.querySelectorAll('#detail-content [data-remove-tag]').forEach(button=>button.onclick=()=>busy(button,()=>saveTags(item.tags.filter((_,index)=>index!==Number(button.dataset.removeTag)))));
 $('#edit-title').onclick=()=>{$('#rename-title').value=item.title;$('#title-editor').hidden=false;$('#edit-title').hidden=true;$('#edit-content').disabled=true;$('#rename-title').focus();$('#rename-title').select()};
 $('#cancel-title').onclick=cancelTitle;
 $('#rename-title').onkeydown=event=>{if(event.key==='Escape'){event.preventDefault();event.stopPropagation();cancelTitle()}};
 $('#title-editor').onsubmit=event=>{event.preventDefault();const title=$('#rename-title').value.trim();if(!title){toast(t('标题不能为空'));return}busy($('#save-title'),async()=>{await api('/api/items/'+id+'/title',{title});await detail(id);await refresh();toast(t('标题已保存'))})};
 if($('#open-pdf-default'))$('#open-pdf-default').onclick=()=>busy($('#open-pdf-default'),async()=>{await api('/api/items/'+id+'/open-file',{});toast(t('已交给系统默认 PDF 程序打开'))});
 if($('#full-pdf-summary'))$('#full-pdf-summary').onclick=()=>busy($('#full-pdf-summary'),async()=>{await api('/api/items/'+id,{full_pdf:true});toast(t('已加入全文整理队列，长文件可能需要较长时间'));await refresh()});
 if($('#reparse-file'))$('#reparse-file').onclick=()=>busy($('#reparse-file'),async()=>{const data=await api('/api/items/'+id+'/reextract',{});await detail(id);await refresh();toast(data.parsed?t('原文件已重新解析，将按当前设置生成摘要'):t('未取得正文，请查看详情中的原因'))});
 if(!$('#detail-dialog').open)$('#detail-dialog').showModal();
 if($('#copy-url'))$('#copy-url').onclick=()=>navigator.clipboard.writeText(item.url).then(()=>toast(t('链接已复制'))).catch(()=>toast(t('复制失败，请从原链接复制')));
 $('#retry-ai').onclick=()=>busy($('#retry-ai'),async()=>{await api('/api/items/'+id,{});toast(item.text||item.user_context?t('已加入整理队列'):t('请先补充正文'));await refresh()});
 $('#edit-content').disabled=isReading(item);
 $('#edit-content').onclick=()=>{$('#edit-title').disabled=true;const editor=document.createElement('div');editor.innerHTML=t('<label>标题<input id="detail-title"></label><label>正文<textarea class="edit-text" id="detail-edit"></textarea></label><button class="primary" id="save-content">保存并重新整理</button>');$('#detail-content').append(editor);$('#detail-title').value=item.title;$('#detail-edit').value=item.text;$('#detail-edit').focus();$('#edit-content').disabled=true;$('#save-content').onclick=()=>busy($('#save-content'),async()=>{await api('/api/items/'+id,{title:$('#detail-title').value,text:$('#detail-edit').value});await detail(id);await refresh();toast(t('正文已保存并重新索引'))})};
}
async function applyUILanguage(language){
 const changed=StellarI18n.language!==language;StellarI18n.setLanguage(language);$('#ui-language').value=language;$('#tutorial-open').href='/tutorial?lang='+language;
 $('#interface-toggle').textContent=(globalThis.__stellarDesktop===true||(globalThis.location?.search||'').includes('desktop=1'))?t('切到网页模式'):t('切到桌面模式');
 if(changed){lastMessageMarkup='';renderAttachments();if(sending)$('#composer-status').textContent=t('正在处理…');if(latestStatus){$('#backend-status').textContent=Object.entries(latestStatus.backends).map(([key,value])=>key+': '+t(value?'已找到 CLI（登录状态需调用验证）':'未找到')).join(' · ');$('#data-dir').textContent=t('本机资料目录：')+latestStatus.data_dir}if(lastUpdateState)renderUpdate(lastUpdateState);renderSidebar();renderChat(false);updateModelLabel();if($('#library-dialog').open)await renderLibrary();if($('#detail-dialog').open&&!$('#detail-edit')&&(!$('#title-editor')||$('#title-editor').hidden)&&(!$('#tag-editor')||$('#tag-editor').hidden)&&!StellarNotes.isDirty(selectedId))await detail(selectedId);}
}
let fontSizeRevision=0,fontSizeChanging=false,fontSaveQueue=Promise.resolve();
function applyUIFontSize(size){
 const value=Number(size);if(!Number.isInteger(value)||value<12||value>24)return;
 document.documentElement?.style?.setProperty('--ui-font-size',value+'px');
 $('#ui-font-size').value=String(value);$('#ui-font-size-value').textContent=value+' px';
 try{localStorage.setItem('stellar.ui-font-size',String(value))}catch{}
}
async function saveUIFontSize(){
 const size=Number($('#ui-font-size').value),revision=++fontSizeRevision,previous=latestStatus?.settings?.ui_font_size||14;
 fontSizeChanging=true;applyUIFontSize(size);
 try{const request=fontSaveQueue.catch(()=>{}).then(()=>api('/api/appearance',{ui_font_size:size}));fontSaveQueue=request;await request;if(latestStatus)latestStatus.settings.ui_font_size=size;if(revision===fontSizeRevision){fontSizeChanging=false;toast(t('字号已保存'))}}
 catch(error){if(revision===fontSizeRevision){fontSizeChanging=false;applyUIFontSize(latestStatus?.settings?.ui_font_size||previous);toast(error.message)}}
}
$('#ui-font-size').oninput=()=>{fontSizeChanging=true;applyUIFontSize($('#ui-font-size').value)};
$('#ui-font-size').onchange=saveUIFontSize;
$('#ui-font-size-reset').onclick=()=>{applyUIFontSize(14);return saveUIFontSize()};
try{applyUIFontSize(Number(localStorage.getItem('stellar.ui-font-size'))||14)}catch{}
let contentFontScale=100,savedContentFontScale=100,contentFontRevision=0,contentFontChanging=false,contentFontTimer,contentFontQueue=Promise.resolve();
function applyContentFontScale(scale){
 const value=Number(scale);if(!Number.isInteger(value)||value<70||value>200)return;
 contentFontScale=value;document.documentElement?.style?.setProperty('--content-font-scale',String(value/100));
 $('#content-font-scale-value').textContent=value+'%';
 try{localStorage.setItem('stellar.content-font-scale',String(value))}catch{}
}
function syncContentFontScale(settings,revision){
 if(contentFontChanging||revision!==contentFontRevision)return;
 savedContentFontScale=settings.content_font_scale||100;applyContentFontScale(savedContentFontScale);
}
function changeContentFontScale(value){
 const scale=Math.min(200,Math.max(70,value));
 if(scale===contentFontScale)return;
 const revision=++contentFontRevision;contentFontChanging=true;applyContentFontScale(scale);
 toast(t('正文大小：')+scale+'%');clearTimeout(contentFontTimer);
 contentFontTimer=setTimeout(async()=>{
  try{const request=contentFontQueue.catch(()=>{}).then(()=>api('/api/appearance',{content_font_scale:scale}));contentFontQueue=request;await request;savedContentFontScale=scale;if(revision===contentFontRevision)contentFontChanging=false}
  catch(error){if(revision===contentFontRevision){contentFontChanging=false;applyContentFontScale(savedContentFontScale);toast(error.message)}}
 },180);
}
$('#content-font-reset').onclick=()=>changeContentFontScale(100);
document.addEventListener('keydown',event=>{
 if(event.defaultPrevented||event.isComposing||event.altKey||!(event.metaKey||event.ctrlKey))return;
 const plus=['+','='].includes(event.key)||event.code==='NumpadAdd';
 const minus=event.key==='-'||event.code==='Minus'||event.code==='NumpadSubtract';
 const reset=event.key==='0'||event.code==='Numpad0';
 if(!plus&&!minus&&!reset)return;
 event.preventDefault();changeContentFontScale(reset?100:contentFontScale+(plus?10:-10));
},true);
try{applyContentFontScale(Number(localStorage.getItem('stellar.content-font-scale'))||100)}catch{}
$('#ui-language').onchange=async()=>{const select=$('#ui-language'),previous=StellarI18n.language,language=select.value;uiLanguageRevision++;languageChanging=true;select.disabled=true;try{await api('/api/language',{language});await applyUILanguage(language);toast(t('语言已切换'))}catch(error){select.value=previous;toast(error.message)}finally{languageChanging=false;select.disabled=false}};
$('#settings-open').onclick=()=>{$('#settings-dialog').showModal();loadStatus().catch(e=>toast(e.message))};
async function loadStatus(){const contentRevision=contentFontChanging?-1:contentFontRevision,fontRevision=fontSizeChanging?-1:fontSizeRevision,revision=uiLanguageRevision;const data=await api('/api/status');token=data.token;latestStatus=data;syncContentFontScale(data.settings,contentRevision);if(!fontSizeChanging&&fontRevision===fontSizeRevision)applyUIFontSize(data.settings.ui_font_size||14);if(!languageChanging&&revision===uiLanguageRevision)await applyUILanguage(data.settings.ui_language||'zh');$('#interface-toggle').hidden=!data.desktop?.supports_window;$('#interface-settings').hidden=$('#interface-toggle').hidden;$('#interface-toggle').textContent=(globalThis.__stellarDesktop===true||(globalThis.location?.search||'').includes('desktop=1'))?t('切到网页模式'):t('切到桌面模式');if(data.update)renderUpdate(data.update);supportsWebCapture=data.capabilities?.generic_page_capture===true;supportsCapture=data.capabilities?.conversation_capture===true&&data.capabilities?.manual_browser_login===true&&data.capabilities?.in_place_browser_read===true;$('#service-alert').hidden=supportsCapture;$('#backend').value=data.settings.backend;$('#auto-ai').checked=data.settings.auto_ai;$('#capture-background').checked=data.settings.capture_background!==false;$('#capture-scope').value=data.settings.capture_scope||'recent';$('#capture-close-tabs').checked=data.settings.capture_close_tabs!==false;$('#backend-status').textContent=Object.entries(data.backends).map(([k,v])=>k+': '+(v?t('已找到 CLI（登录状态需调用验证）'):t('未找到'))).join('　');$('#data-dir').textContent=t('本机资料目录：')+data.data_dir}
$('#close-capture-browsers').onclick=()=>busy($('#close-capture-browsers'),async()=>{await api('/api/browser/close',{});toast(t('专用浏览器已关闭，登录资料已保留'))});
$('#settings-save').onclick=()=>busy($('#settings-save'),async()=>{await api('/api/settings',{backend:$('#backend').value,auto_ai:$('#auto-ai').checked,capture_background:$('#capture-background').checked,capture_close_tabs:$('#capture-close-tabs').checked,capture_scope:$('#capture-scope').value});$('#settings-dialog').close();toast(t('设置已保存；等待中的资料可手动重新整理'))});
$('#model-open').onclick=()=>{$('#settings-dialog').showModal();loadStatus().catch(e=>toast(e.message))};
function updateModelLabel(){$('#model-label').textContent=$('#backend').value==='claude'?'Claude':'ChatGPT · Codex'}
$('#settings-save').onclick=()=>busy($('#settings-save'),async()=>{await api('/api/settings',{backend:$('#backend').value,auto_ai:$('#auto-ai').checked,capture_background:$('#capture-background').checked,capture_close_tabs:$('#capture-close-tabs').checked,capture_scope:$('#capture-scope').value});updateModelLabel();$('#settings-dialog').close();toast(t('设置已保存'))});
(async()=>{for(const c of conversations)for(const m of c.messages||[]){if(m.text==='这份资料已经在知识库里了，可以直接打开查看。')m.archiveOnly=true;if(m.pending){m.pending=false;m.error=true;m.text=t('上次请求因页面关闭而中断。归档资料可在知识库中查看；提问请重新发送。')}}renderSidebar();renderChat();updateSend();try{await loadStatus();try{await loadSharedChats()}catch(e){toast(t('对话同步未完成，已保留浏览器记录：')+e.message)}updateModelLabel();await refresh();setInterval(()=>{if(!document.hidden)refresh().catch(()=>{})},5000)}catch(e){toast(t('无法连接本地服务：')+e.message)}})();

let updateTimer;
function renderUpdate(s){
 lastUpdateState=s;
 const labels={checking:t('正在检查更新…'),downloading:t('正在下载 ')+s.progress+'%',verifying:t('正在校验安装包…'),installing:t('正在升级，程序即将重启，请稍后刷新页面。'),manual:t('安装包已打开，请完成安装。')};
 $('#update-status').textContent=t('当前版本 ')+s.current+' · '+(s.error||labels[s.phase]||(s.available?t('发现新版本 ')+s.latest:s.supported?t('已是最新版本或尚未检查'):t('源码运行；安装版支持一键升级')));
 const active=['checking','downloading','verifying','installing'].includes(s.phase);
 $('#update-check').disabled=active;
 $('#update-install').hidden=!s.supported||!s.available;
 $('#update-install').disabled=active;
}
$('#update-check').onclick=()=>busy($('#update-check'),async()=>renderUpdate(await api('/api/update/check',{})));
$('#update-install').onclick=()=>busy($('#update-install'),async()=>{
 renderUpdate(await api('/api/update/install',{}));
 clearInterval(updateTimer);
 updateTimer=setInterval(async()=>{try{const s=await api('/api/update');renderUpdate(s);if(['error','manual','idle'].includes(s.phase))clearInterval(updateTimer)}catch(e){clearInterval(updateTimer);$('#update-status').textContent=t('服务正在重启，请稍后刷新页面。')}},1000);
});

let importingBackup=false;
$('#import-backup').onclick=$('#library-import').onclick=()=>{if(!importingBackup)$('#backup-input').click()};
$('#backup-input').onchange=async()=>{
 const file=$('#backup-input').files[0];if(!file)return;
 importingBackup=true;$('#import-backup').disabled=$('#library-import').disabled=true;
 $('#import-status').textContent=t('正在导入备份，请稍候…');toast(t('正在导入知识库备份…'));
 try{
  if(file.size>256*1024*1024)throw Error(t('备份不能超过 256 MB'));
  const send=()=>fetch('/api/import',{method:'POST',headers:{'Content-Type':'application/zip','X-Knowledge-Token':token},body:file,signal:AbortSignal.timeout(300000)});
  let response=await send();
  if(response.status===403){token=(await api('/api/status')).token;response=await send()}
  const result=await response.json();if(!response.ok)throw Error(result.error||t('导入失败'));
  const message=t('导入完成：新增 ')+result.imported+t(' 条，重复跳过 ')+result.skipped+t(' 条。');
  $('#import-status').textContent=message;await refresh();toast(message);
 }catch(e){$('#import-status').textContent=t('导入失败：')+e.message;toast(t('导入失败：')+e.message)}
 finally{importingBackup=false;$('#import-backup').disabled=$('#library-import').disabled=false;$('#backup-input').value=''}
};
