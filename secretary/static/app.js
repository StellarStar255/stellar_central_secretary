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
function readerMarkdown(text){
 const lines=text.replace(/\r\n?/g,'\n').split('\n');let html='',paragraph=[],list=null;
 const flushParagraph=()=>{if(paragraph.length){html+='<p>'+paragraph.map(readerInline).join('<br>')+'</p>';paragraph=[]}};
 const closeList=()=>{if(list){html+='</'+list+'>';list=null}};
 for(let i=0;i<lines.length;i++){
  const line=lines[i];
  if(/^\s*```/.test(line)){
   flushParagraph();closeList();const code=[];
   while(++i<lines.length&&!/^\s*```/.test(lines[i]))code.push(lines[i]);
   html+='<pre><code>'+readerEscape(code.join('\n'))+'</code></pre>';continue;
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
   const user=/^(用户|你|user|human)$/i.test(role[1]);current={role:user?'user':'assistant',label:user?'你':/^claude$/i.test(role[1])?'Claude':/^chatgpt$/i.test(role[1])?'ChatGPT':'助手',lines:[]};
  }else if(current)current.lines.push(line);
  else if(line.trim())return [];
 }
 if(current)turns.push({...current,text:current.lines.join('\n').trim()});
 return turns.length>=2&&turns.some(t=>t.role==='user')&&turns.some(t=>t.role==='assistant')?turns:[];
}
function renderArchivedBody(item){
 const text=item.text||'',turns=item.kind==='file'||item.kind==='note'?[]:parseArchivedConversation(text);
 if(!turns.length)return `<h3>正文 <span class="muted">${text.length.toLocaleString()} 字符</span></h3><div class="detail-text">${readerEscape(text||'还没有正文。点击「补充 / 编辑正文」，或使用浏览器采集扩展。')}</div>`;
 return `<section class="archive-conversation" aria-label="已归档的对话"><div class="reader-heading"><h3>会话记录</h3><span>${turns.length} 条消息 · 点击角色可收起</span></div>${turns.map((turn,index)=>`<details class="reader-turn reader-${turn.role}" open><summary><span class="reader-avatar" aria-hidden="true">${turn.role==='user'?'<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.6"><circle cx="12" cy="8" r="3.2"/><path d="M5 21v-2a7 7 0 0 1 14 0v2"/></svg>':'✳'}</span><span>${readerEscape(turn.label)}</span><span class="reader-turn-number">${String(index+1).padStart(2,'0')}</span><span class="reader-chevron" aria-hidden="true">⌄</span></summary><div class="reader-message ${turn.role==='assistant'?'reader-prose':''}">${turn.role==='user'?readerEscape(turn.text):readerMarkdown(turn.text)}</div></details>`).join('')}<details class="reader-original"><summary>查看原始文本 · ${text.length.toLocaleString()} 字符</summary><div>${readerEscape(text)}</div></details></section>`;
}

const $ = s => document.querySelector(s);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const states = {pending:'等待整理',processing:'正在整理',ready:'已整理',error:'待重试',needs_content:'待补正文',confirming_login:'正在准备读取',waiting_browser_close:'等待专用窗口退出',opening_browser:'正在打开浏览器',waiting_login:'等待你登录',reading:'正在读取正文'};
const captureActions=new Map();
let lastMessageMarkup='';
let supportsCapture=false;
let token='', allItems=[], selectedId='', detailVersion='', searchTimer, attachedFiles=[], sending=false;
const storageKey='stellar.conversations.v1';
let conversations=[], activeId='';
try { const saved=JSON.parse(localStorage.getItem(storageKey)||'{}'); conversations=Array.isArray(saved.conversations)?saved.conversations:[];activeId=saved.activeId||''; } catch {}
const uid=()=>crypto.randomUUID();
function currentChat(){return conversations.find(c=>c.id===activeId)}
function saveChats(){try{localStorage.setItem(storageKey,JSON.stringify({conversations,activeId}))}catch{toast('浏览器对话记录存储空间已满；归档资料仍保存在知识库中。')}}
function toast(message){$('#toast').textContent=message;$('#toast').classList.add('show');clearTimeout(toast.timer);toast.timer=setTimeout(()=>$('#toast').classList.remove('show'),4200)}
async function api(path,body,retry=true){
 const controller=new AbortController();const timer=setTimeout(()=>controller.abort(),path==='/api/ask'?300000:path==='/api/ingest'?90000:12000);
 let response;
 try{response=await fetch(path,body===undefined?{signal:controller.signal}:{method:'POST',headers:{'Content-Type':'application/json','X-Knowledge-Token':token},body:JSON.stringify(body),signal:controller.signal})}
 catch(e){throw Error(e.name==='AbortError'?'本地服务响应超时，请检查程序是否仍在运行。':e.message)}
 finally{clearTimeout(timer)}
 const data=await response.json();
 if(response.status===403&&body!==undefined&&retry){const status=await api('/api/status');token=status.token;return api(path,body,false)}
 if(!response.ok)throw Error(data.error||'请求失败');return data;
}

async function busy(button,action,label='处理中…'){const old=button.textContent;button.disabled=true;button.textContent=label;try{return await action()}catch(e){toast(e.message)}finally{button.disabled=false;button.textContent=old}}
function date(value){return new Date(value).toLocaleDateString('zh-CN',{month:'short',day:'numeric'})}
function newChat(){activeId='';attachedFiles=[];$('#message-input').value='';resizeInput();renderAttachments();renderChat();renderSidebar();saveChats();$('#message-input').focus()}
function renderSidebar(){
 $('#conversations').innerHTML=conversations.map(c=>`<button class="conversation ${c.id===activeId?'active':''}" data-chat="${esc(c.id)}">${esc(c.title)}</button>`).join('');
 $('#conversations').querySelectorAll('button').forEach(b=>b.onclick=()=>{activeId=b.dataset.chat;saveChats();renderChat();renderSidebar();document.body.classList.remove('mobile-sidebar')});
 $('#recent-items').innerHTML=allItems.slice(0,6).map(i=>`<button class="recent-item" data-id="${i.id}" title="${esc(i.title)}"><span>${i.kind==='link'?'↗':i.kind==='file'?'▧':'✎'}</span>${esc(i.title)}</button>`).join('');
 bindDetails($('#recent-items'));
}
function bindDetails(container){container.querySelectorAll('[data-id]').forEach(b=>b.onclick=()=>detail(b.dataset.id).catch(e=>toast(e.message)))}
function archiveCard(id){const item=allItems.find(i=>i.id===id);if(!item)return '';return `<button class="archive-card" data-id="${id}"><div class="archive-top"><span class="file-icon">${item.kind==='link'?'↗':item.kind==='file'?'▧':'✎'}</span><div><strong>${esc(item.title)}</strong><small>${esc(item.category)} · 查看资料与原件 ↗</small></div><span class="archive-status">${states[item.state]||''}</span></div>${item.summary?`<p class="archive-summary">${esc(item.summary)}</p>`:''}</button>${captureControls(item)}`}
function renderChat(scroll=true){
 const chat=currentChat();const messages=chat?.messages||[];
 const container=$('#chat-scroll');const atBottom=container.scrollHeight-container.scrollTop-container.clientHeight<120;
 $('#workspace').classList.toggle('empty',messages.length===0);
 const markup=messages.map(m=>`<article class="message ${m.role} ${m.pending?'pending':''} ${m.error?'error':''}" data-message="${esc(m.id)}">${m.role==='assistant'?'<div class="assistant-label"><span>✳</span>Secretary</div>':''}${m.files?.length?`<div class="user-files">${m.files.map(f=>`<span>▧ ${esc(f)}</span>`).join('')}</div>`:''}${m.text?`<div class="message-body">${esc(m.text)}</div>`:''}${(m.items||[]).map(archiveCard).join('')}${m.sources?.length?`<div class="source-list">${m.sources.map(s=>`<button class="source" data-id="${s.item_id}">[${s.number}] ${esc(s.title)}<br><span>查看来源 ↗</span></button>`).join('')}</div>`:''}${m.role==='assistant'&&!m.pending?`<div class="message-tools"><button data-copy="${esc(m.id)}">复制回答</button></div>`:''}</article>`).join('');
 if(markup===lastMessageMarkup)return;lastMessageMarkup=markup;$('#messages').innerHTML=markup;
 bindDetails($('#messages'));$('#messages').querySelectorAll('[data-copy]').forEach(b=>b.onclick=()=>{const message=messages.find(m=>m.id===b.dataset.copy);navigator.clipboard.writeText(message.text).then(()=>toast('已复制')).catch(()=>toast('复制失败，请手动选择文字'))});
 if(scroll||atBottom)container.scrollTop=container.scrollHeight;
}
function addMessage(chat,role,text,extras={}){const message={id:uid(),role,text,...extras};chat.messages.push(message);saveChats();if(chat.id===activeId)renderChat();return message}
function updateMessage(chat,message,values){Object.assign(message,values);saveChats();if(chat.id===activeId)renderChat()}
async function refresh(){
 allItems=await api('/api/items');
 for(const [id,action] of captureActions){
  const item=allItems.find(i=>i.id===id);
  if(action.accepted&&item?.state!=='waiting_login')captureActions.delete(id);
  else if(action.accepted&&Date.now()-action.at>30000){action.accepted=false;action.error=true;action.text='后台已收到确认，但 30 秒内未进入读取。可以再次确认；若仍停在此处，请停止任务后重试，已保存的浏览器登录状态会保留。'}
 }
 let changed=false;
 for(const chat of conversations)for(const m of chat.messages){
  if(m.role==='assistant'&&!m.pending&&m.archiveOnly&&m.items?.length){
   const text=m.items.map(id=>allItems.find(i=>i.id===id)).filter(Boolean).map(item=>archiveReply({item,created:true})).filter((v,i,a)=>a.indexOf(v)===i).join('\n\n');
   if(text&&text!==m.text){m.text=text;changed=true}
  }
 }
 if(changed)saveChats();
 $('#count').textContent=allItems.length;renderSidebar();renderChat(false);
 if($('#library-dialog').open)await renderLibrary();
 if($('#detail-dialog').open&&selectedId&&!$('#detail-edit')){const item=allItems.find(i=>i.id===selectedId);if(item&&item.updated!==detailVersion)await detail(selectedId)}
}
async function renderLibrary(){
 const q=$('#search').value.trim(),kind=$('#kind-filter').value,category=$('#category-filter').value;
 const items=await api('/api/items?'+new URLSearchParams({q,kind,category}));
 const cats=[...new Set(allItems.map(i=>i.category))].sort();$('#category-filter').innerHTML='<option value="">全部主题</option>'+cats.map(c=>`<option ${c===category?'selected':''}>${esc(c)}</option>`).join('');
 $('#result-count').textContent=items.length+' 份资料';$('#empty').hidden=items.length>0;
 $('#items').innerHTML=items.map(i=>`<button class="library-row" data-id="${i.id}"><span class="file-icon">${i.kind==='file'?'▧':i.kind==='link'?'↗':'✎'}</span><div class="library-info"><strong>${esc(i.title)}</strong><p>${esc(i.summary||i.error||'正文已保存，可随时查阅。')}</p></div><small>${states[i.state]}<br>${date(i.created)}</small></button>`).join('');bindDetails($('#items'));
}
async function openLibrary(){document.body.classList.remove('mobile-sidebar');$('#library-dialog').showModal();await renderLibrary();$('#search').focus()}
$('#library-open').onclick=$('#library-shortcut').onclick=()=>openLibrary().catch(e=>toast(e.message));
$('#search').oninput=()=>{clearTimeout(searchTimer);searchTimer=setTimeout(()=>renderLibrary().catch(e=>toast(e.message)),180)};
$('#kind-filter').onchange=$('#category-filter').onchange=()=>renderLibrary().catch(e=>toast(e.message));
$('#new-chat').onclick=newChat;
$('#sidebar-toggle').onclick=()=>{if(window.innerWidth<=700)document.body.classList.toggle('mobile-sidebar');else{document.body.classList.toggle('sidebar-hidden');$('#workspace').classList.toggle('sidebar-hidden')}};
$('#chat-scroll').onclick=()=>document.body.classList.remove('mobile-sidebar');
document.addEventListener('keydown',e=>{if((e.metaKey||e.ctrlKey)&&['k','j'].includes(e.key.toLowerCase())){e.preventDefault();e.key.toLowerCase()==='k'?openLibrary().catch(e=>toast(e.message)):newChat()}});
function resizeInput(){const input=$('#message-input');input.style.height='auto';input.style.height=Math.min(input.scrollHeight,220)+'px';updateSend()}
function updateSend(){$('#send-button').disabled=sending||(!$('#message-input').value.trim()&&!attachedFiles.length)}
$('#message-input').oninput=resizeInput;
$('#message-input').onkeydown=e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.isComposing){e.preventDefault();if(!$('#send-button').disabled)$('#composer-form').requestSubmit()}};
function renderAttachments(){$('#attachments').innerHTML=attachedFiles.map((f,i)=>`<div class="attachment"><span title="${esc(f.name)}">▧ ${esc(f.name)}</span><button type="button" data-remove="${i}" aria-label="移除 ${esc(f.name)}">×</button></div>`).join('');$('#attachments').querySelectorAll('button').forEach(b=>b.onclick=()=>{attachedFiles.splice(Number(b.dataset.remove),1);renderAttachments()});updateSend()}
function attach(files){for(const file of files){if(file.size>50*1024*1024){toast(file.name+' 超过 50 MB');continue}attachedFiles.push(file)}renderAttachments();$('#message-input').focus()}
$('#attach-button').onclick=()=>$('#file-input').click();$('#file-input').onchange=e=>{attach([...e.target.files]);e.target.value=''};
$('#message-input').addEventListener('paste',e=>{if(e.clipboardData.files.length){e.preventDefault();attach([...e.clipboardData.files])}});
let dragDepth=0;
window.addEventListener('dragenter',e=>{if([...e.dataTransfer.types].includes('Files')){e.preventDefault();dragDepth++;$('#drag-overlay').hidden=false}});
window.addEventListener('dragover',e=>{if([...e.dataTransfer.types].includes('Files'))e.preventDefault()});
window.addEventListener('dragleave',()=>{dragDepth=Math.max(0,dragDepth-1);if(!dragDepth)$('#drag-overlay').hidden=true});
window.addEventListener('drop',e=>{if(e.dataTransfer.files.length){e.preventDefault();attach([...e.dataTransfer.files])}dragDepth=0;$('#drag-overlay').hidden=true});
document.querySelectorAll('[data-suggestion]').forEach(b=>b.onclick=()=>{if(b.dataset.suggestion==='file')$('#file-input').click();else{$('#message-input').value=b.dataset.suggestion==='archive'?'':'帮我找一下之前收藏的资料：';$('#message-input').placeholder=b.dataset.suggestion==='archive'?'在这里粘贴链接，然后按 Enter…':'输入你想找的资料或问题…';resizeInput();$('#message-input').focus()}});
async function readFile(file){return new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result.split(',')[1]);reader.onerror=()=>reject(Error('无法读取 '+file.name));reader.readAsDataURL(file)})}
function canReadChatGPT(url){try{const u=new URL(url);return u.protocol==='https:'&&['chatgpt.com','chat.openai.com'].includes(u.hostname)&&/^\/(c|share)\/[a-zA-Z0-9_-]+\/?$/.test(u.pathname)}catch{return false}}
function isReading(item){return ['opening_browser','waiting_login','confirming_login','waiting_browser_close','reading'].includes(item.state)}
function captureControls(item){
 if(!canReadChatGPT(item.url))return '';
 const action=captureActions.get(item.id);
 const hasText=item.text_length>0||item.text?.trim()||(item.text_length===undefined&&['error','ready','processing','pending'].includes(item.state));
 const summaryButton=hasText?`<button data-summarize="${item.id}" ${item.state==='processing'?'disabled':''}>${item.state==='processing'?'摘要生成中…':item.summary?'重新生成摘要':'重试摘要'}</button>`:'';
 const feedback=action?`<span class="capture-feedback ${action.error?'capture-error':''}" role="status">${esc(action.text)}</span>`:'';
 const pending=action?.pending||action?.accepted&&item.state==='waiting_login';
 const disabled=pending||item.state==='processing'?'disabled aria-busy="true"':'';
 if(isReading(item))return `<div class="capture-actions">${feedback}<span>${item.state==='opening_browser'?'正在启动普通 Chrome…':item.state==='waiting_login'?'请在普通 Chrome 中登录并打开目标会话，然后点击下方确认。':item.state==='confirming_login'?'已收到登录确认，正在连接原窗口读取正文…':item.state==='waiting_browser_close'?'请关闭本项目的专用 Chrome 窗口，程序会自动继续；你的登录资料会保留。':esc(item.error||'正在读取会话正文…')}</span>${item.state==='waiting_login'&&supportsCapture?`<button class="confirm-login" data-confirm-login="${item.id}" ${disabled}>${pending?'确认中…':'我已登录，开始读取'}</button>`:''}<button data-cancel-capture="${item.id}" ${action?.pending?'disabled':''}>停止读取</button></div>`;
 return `<div class="capture-actions">${feedback}${item.error&&!item.error.startsWith('会话链接已收藏')?`<span class="capture-error">${esc(item.error.slice(0,450))}</span>`:''}${summaryButton}<button data-capture="${item.id}" ${disabled}>${!supportsCapture?'后台需要重启':item.state==='needs_content'?'打开普通浏览器登录':'重新读取网页'}</button><button data-extension-help>使用常用浏览器采集</button></div>`;
}
function refreshCaptureUI(){renderChat(false);if($('#detail-dialog').open&&!$('#detail-edit'))detail(selectedId).catch(()=>{})}
async function performCaptureAction(id,action){
 if(captureActions.get(id)?.pending)return;
 captureActions.set(id,{pending:true,text:action==='confirm'?'正在提交登录确认…':action==='cancel'?'正在停止读取…':action==='summary'?'正在提交摘要任务…':'正在提交读取请求…'});refreshCaptureUI();
 try{
  if(action==='summary'){try{await api('/api/items/'+id,{})}catch(e){if(!e.message.includes('正在处理'))throw e}captureActions.set(id,{text:'摘要任务已提交，使用已保存的正文，无需重新读取网页。'});await refresh()}
  else if(action==='confirm')await confirmLogin(id);
  else if(action==='cancel'){await api('/api/items/'+id+'/cancel-capture',{});captureActions.set(id,{text:'已发送停止请求，浏览器窗口将保持打开。'});await refresh()}
  else{await requestCapture(id);captureActions.delete(id)}
 }catch(e){captureActions.set(id,{error:true,text:'操作失败：'+e.message});toast(e.message)}
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
 const status=await api('/api/status');token=status.token;supportsCapture=status.capabilities?.conversation_capture===true&&status.capabilities?.manual_browser_login===true&&status.capabilities?.in_place_browser_read===true;
 $('#service-alert').hidden=supportsCapture;
 if(!supportsCapture)throw Error('后台仍是旧版本，没有启动浏览器。请双击「启动知识秘书.command」重启服务，再刷新此页面。');
 const result=await api('/api/items/'+id+'/capture',{});
 if(result.capture_started!==true)throw Error('后台未确认读取任务，浏览器未启动。请重启知识秘书后重试。');
 if(['needs_content','error'].includes(result.item?.state))throw Error(result.item.error||'浏览器启动失败，请查看资料详情。');
 await refresh();
 const current=allItems.find(i=>i.id===id)||result.item;
 if(['needs_content','error'].includes(current?.state))throw Error(current.error||'浏览器启动失败。');
 toast(current?.state==='waiting_login'?'已请求 Chrome 打开会话。请登录后点击「我已登录，开始读取」。':'读取任务已提交，正在启动普通 Chrome…');
}
async function confirmLogin(id){
 const result=await api('/api/items/'+id+'/confirm-login',{});
 if(result.login_confirmed!==true)throw Error('后台未确认登录，请重启知识秘书后重试。');
 if(result.item){const index=allItems.findIndex(i=>i.id===id);if(index>=0)allItems[index]=result.item}
 captureActions.set(id,{accepted:true,at:Date.now(),text:'后台已收到登录确认。正在连接同一个浏览器窗口，登录状态保持在原实例中。'});
 await refresh();
}

function archiveReply(result){const i=result.item;
 if(canReadChatGPT(i.url)&&i.state==='needs_content'&&!supportsCapture)return '链接已保存，但当前后台仍是旧版本，尚未启动浏览器读取正文。请双击项目里的「启动知识秘书.command」重启服务，再刷新此页面。';
 if(i.state==='opening_browser')return '读取任务已提交，正在启动专用浏览器。窗口打开后会提示你登录。';
 if(i.state==='waiting_login')return '普通 Chrome 已启动。请在该窗口中登录 ChatGPT 并打开目标会话，然后回到这里点击「我已登录，开始读取」。确认后直接从这个浏览器实例读取，窗口会保持打开。';
 if(i.state==='confirming_login')return '后台已收到登录确认，正在连接原浏览器实例，窗口保持打开。';
 if(i.state==='waiting_browser_close')return '登录确认已收到。专用浏览器仍占用配置目录，请关闭该专用窗口，程序会等待并继续；登录资料会保留。';
 if(i.state==='reading')return i.error||'已确认登录，正在识别目标会话消息。';
 if(i.state==='needs_content')return i.url?'这条资料目前只收藏了链接，还没有读到正文，因此尚未生成总结。'+(canReadChatGPT(i.url)?'点击下方「打开普通浏览器登录」，登录后回到这里确认读取；也可直接用常用浏览器中的采集扩展。':'可以用浏览器扩展采集已登录页面，或点击资料补充正文。'):'原件已保存，但这个格式暂不支持提取正文，可点击下方资料手动补充。';
 if(i.state==='error')return '正文已保存并建立检索索引，但自动总结失败了。具体原因在资料详情中，可以重新整理。';
 if(i.summary)return '已整理这份资料：\n\n'+i.summary;
 if(!result.created&&!result.updated)return '正文已在知识库中。'+(i.state==='processing'?'正在生成总结，请稍候。':'尚未生成总结，可点击资料中的「重新整理」。');
 return '已存入知识库，正文现在就可以检索。'+($('#auto-ai').checked?'我会继续在后台整理摘要和主题，结果会更新在下方。':'自动整理已关闭，之后可以在资料详情中生成摘要。')}

$('#composer-form').onsubmit=async event=>{
 event.preventDefault();if(sending)return;const text=$('#message-input').value.trim(),files=[...attachedFiles],mode=$('#input-mode').value;if(!text&&!files.length)return;
 if(!token){toast('服务尚未连接，请稍后重试或刷新页面。');return}
 let chat=currentChat();if(!chat){chat={id:uid(),title:(text||files[0]?.name||'新对话').slice(0,36),messages:[]};conversations.unshift(chat);activeId=chat.id}
 addMessage(chat,'user',text,{files:files.map(f=>f.name)});const response=addMessage(chat,'assistant','正在处理…',{pending:true,items:[]});
 $('#message-input').value='';attachedFiles=[];sending=true;renderAttachments();resizeInput();renderSidebar();$('#composer-status').textContent='正在处理…';
 const results=[],errors=[];
 try{
  for(const file of files){updateMessage(chat,response,{text:'正在归档「'+file.name+'」…'});try{const result=await api('/api/ingest',{filename:file.name,data:await readFile(file)});results.push(result);response.items.push(result.item.id)}catch(e){errors.push(file.name+'：'+e.message)}}
  const urls=mode==='note'?[]:[...new Set(text.match(/https?:\/\/[^\s<>"，。！？；）)]+/g)||[])];
  for(const url of urls){updateMessage(chat,response,{text:'正在保存链接…'});try{const result=await api('/api/ingest',{url});results.push(result);response.items.push(result.item.id)}catch(e){errors.push(url+'：'+e.message)}}
  if(mode==='note'&&text){const result=await api('/api/ingest',{text});results.push(result);response.items.push(result.item.id)}
  await refresh();
  const remaining=urls.reduce((value,url)=>value.replace(url,''),text).trim();
  // URLs and attachments are archived by default. A plain-text turn asks the knowledge base.
  const shouldAsk=mode!=='note'&&text&&(!urls.length&&!files.length||/[?？]|总结|分析|比较|查找|找一下|哪些|什么|如何/.test(remaining));
  response.archiveOnly=!shouldAsk&&results.length>0&&!errors.length;
  let answer=results.map(archiveReply).filter((v,i,a)=>a.indexOf(v)===i).join('\n\n');
  if(shouldAsk){updateMessage(chat,response,{text:(answer?answer+'\n\n':'')+'正在检索知识库，整理答案…'});const data=await api('/api/ask',{question:remaining||text});answer+=(answer?'\n\n':'')+data.answer;response.sources=data.sources}
  if(errors.length)answer+=(answer?'\n\n':'')+'以下资料未能保存：\n'+errors.join('\n');
  updateMessage(chat,response,{text:answer||'已处理。',pending:false,error:errors.length>0&&!results.length});
 }catch(e){updateMessage(chat,response,{text:(results.length?'已保存 '+results.length+' 份资料。\n\n':'')+'本次处理未完成：'+e.message,pending:false,error:true})}
 finally{sending=false;$('#composer-status').textContent='';updateSend();$('#message-input').focus();await refresh().catch(()=>{})}
};
async function detail(id){const item=await api('/api/items/'+id);selectedId=id;detailVersion=item.updated;
 $('#detail-content').innerHTML=`<h1>${esc(item.title)}</h1><p>${esc(item.category)} · ${date(item.created)} · ${states[item.state]}</p><div class="tags">${item.tags.map(t=>`<span class="tag">${esc(t)}</span>`).join('')}</div><div class="detail-actions">${item.url?`<a class="primary" href="${esc(item.url)}" target="_blank" rel="noopener noreferrer">打开原链接 ↗</a><button class="secondary" id="copy-url">复制链接</button>`:''}${item.filename?`<a class="secondary" href="/api/items/${id}/file">下载原文件</a>`:''}<button class="secondary" id="edit-content">补充 / 编辑正文</button><button class="secondary" id="retry-ai" ${item.state==='processing'||isReading(item)?'disabled':''}>重新整理</button></div>${item.error?`<p class="warning">${esc(item.error)}</p>`:''}${captureControls(item)}<h3>资料摘要</h3><div class="detail-text">${esc(item.summary||'尚未生成 AI 摘要。正文和原件可独立保存、搜索及下载。')}</div>${renderArchivedBody(item)}`;
 if(!$('#detail-dialog').open)$('#detail-dialog').showModal();
 if($('#copy-url'))$('#copy-url').onclick=()=>navigator.clipboard.writeText(item.url).then(()=>toast('链接已复制')).catch(()=>toast('复制失败，请从原链接复制'));
 $('#retry-ai').onclick=()=>busy($('#retry-ai'),async()=>{await api('/api/items/'+id,{});toast(item.text?'已加入整理队列':'请先补充正文');await refresh()});
 $('#edit-content').disabled=isReading(item);
 $('#edit-content').onclick=()=>{const editor=document.createElement('div');editor.innerHTML='<label>标题<input id="detail-title"></label><label>正文<textarea class="edit-text" id="detail-edit"></textarea></label><button class="primary" id="save-content">保存并重新整理</button>';$('#detail-content').append(editor);$('#detail-title').value=item.title;$('#detail-edit').value=item.text;$('#detail-edit').focus();$('#edit-content').disabled=true;$('#save-content').onclick=()=>busy($('#save-content'),async()=>{await api('/api/items/'+id,{title:$('#detail-title').value,text:$('#detail-edit').value});await detail(id);await refresh();toast('正文已保存并重新索引')})};
}
$('#settings-open').onclick=()=>$('#settings-dialog').showModal();
async function loadStatus(){const data=await api('/api/status');token=data.token;supportsCapture=data.capabilities?.conversation_capture===true&&data.capabilities?.manual_browser_login===true&&data.capabilities?.in_place_browser_read===true;$('#service-alert').hidden=supportsCapture;$('#backend').value=data.settings.backend;$('#auto-ai').checked=data.settings.auto_ai;$('#backend-status').textContent=Object.entries(data.backends).map(([k,v])=>k+': '+(v?'已找到 CLI（登录状态需调用验证）':'未找到')).join('　');$('#data-dir').textContent='本机资料目录：'+data.data_dir}
$('#settings-save').onclick=()=>busy($('#settings-save'),async()=>{await api('/api/settings',{backend:$('#backend').value,auto_ai:$('#auto-ai').checked});$('#settings-dialog').close();toast('设置已保存；等待中的资料可手动重新整理')});
$('#model-open').onclick=()=>$('#settings-dialog').showModal();
function updateModelLabel(){$('#model-label').textContent=$('#backend').value==='claude'?'Claude':'ChatGPT · Codex'}
$('#settings-save').onclick=()=>busy($('#settings-save'),async()=>{await api('/api/settings',{backend:$('#backend').value,auto_ai:$('#auto-ai').checked});updateModelLabel();$('#settings-dialog').close();toast('设置已保存')});
(async()=>{for(const c of conversations)for(const m of c.messages||[]){if(m.text==='这份资料已经在知识库里了，可以直接打开查看。')m.archiveOnly=true;if(m.pending){m.pending=false;m.error=true;m.text='上次请求因页面关闭而中断。归档资料可在知识库中查看；提问请重新发送。'}}renderSidebar();renderChat();updateSend();try{await loadStatus();updateModelLabel();await refresh();setInterval(()=>{if(!document.hidden)refresh().catch(()=>{})},5000)}catch(e){toast('无法连接本地服务：'+e.message)}})();
