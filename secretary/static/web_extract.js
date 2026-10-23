/* Read displayed document content; never inspect form values or credentials. */
function extractWebPage(options={}) {
 const limit=options.limit||120000,english=options.language==='en',styles=new WeakMap(),exposure=new WeakMap();
 const style=node=>{if(!styles.has(node))styles.set(node,getComputedStyle(node));return styles.get(node)};
 const parent=node=>node.assignedSlot||node.parentElement||node.getRootNode()?.host;
 function exposed(node){
  if(!node||node.nodeType!==1)return true;
  if(exposure.has(node))return exposure.get(node);
  const css=style(node),value=!node.hidden&&node.getAttribute('aria-hidden')!=='true'&&css.display!=='none'&&!['hidden','collapse'].includes(css.visibility)&&css.opacity!=='0'&&exposed(parent(node));
  exposure.set(node,value);return value;
 }
 const visible=node=>!!node&&node.nodeType===1&&exposed(node)&&(style(node).display==='contents'||node.getClientRects().length>0);
 const elements=Array.from(document.querySelectorAll('*')).slice(0,50000);
 for(let i=0;i<elements.length&&i<50000;i++)if(elements[i].shadowRoot)elements.push(...Array.from(elements[i].shadowRoot.querySelectorAll('*')).slice(0,50000-elements.length));
 const select=selector=>elements.filter(node=>node.matches(selector));
 const docRoots='[role="document"],article,[data-document-root],[data-testid="document-content"],.zone-container,.docx-editor-container,.lark-doc-content';
 const editableRoots='[role="document"],[data-document-root],[data-testid="document-content"],.zone-container,.docx-editor-container,.lark-doc-content';
 const blocksSelector='.ace-line,[data-block-id],[data-block-type]';
 function draftContext(node){
  if(node.closest('form,.comment-editor,.comment-input,.reply-editor,.chat-input,[data-comment-editor],[data-testid*="comment-editor"],[data-testid*="composer"]'))return true;
  const label=[node.getAttribute('aria-label'),node.getAttribute('data-placeholder'),node.getAttribute('placeholder')].filter(Boolean).join(' ');
  return /评论|回复|输入消息|\b(?:comment|reply|message|composer)\b/i.test(label);
 }
 function documentEditable(node){
  if(draftContext(node))return false;
  return node.matches(editableRoots)||node.matches(blocksSelector)||node.querySelectorAll(blocksSelector).length>=2||!!node.closest(editableRoots)&&!!node.querySelector(blocksSelector);
 }
 const editors=select('[contenteditable="true"],[contenteditable="plaintext-only"]').filter(node=>visible(node)&&documentEditable(node)&&!node.matches(blocksSelector));
 const documents=Array.from(new Set([...select(docRoots),...editors])).filter(node=>visible(node)&&!draftContext(node));
 const candidates=select('[role="dialog"],main,[role="main"],article').filter(visible).filter(node=>(node.innerText||'').trim().length>=80);
 const dialogs=candidates.filter(node=>node.getAttribute('role')==='dialog');
 const roots=dialogs.length?dialogs:documents.length?documents:candidates;
 const root=roots.sort((a,b)=>(b.innerText||'').length-(a.innerText||'').length)[0]||document.body;
 const documentRoot=documents.some(node=>(node===root||root.contains(node))&&(node.matches(editableRoots)||editors.includes(node)));
 const activeEditor=document.activeElement?.closest('[contenteditable="true"],[contenteditable="plaintext-only"]');
 let count=0,characters=0,truncated=false;
 const blockTags=new Set(['P','DIV','SECTION','ARTICLE','LI','H1','H2','H3','H4','H5','H6','TR','UL','OL','BLOCKQUOTE']);
 function walk(node){
  if(++count>50000||characters>=limit){truncated=true;return '';}
  if(node.nodeType===3){const text=node.textContent.slice(0,Math.max(0,limit-characters));characters+=text.length;return text;}
  if(node.nodeType===11)return Array.from(node.childNodes).map(walk).join('');
  if(node.nodeType!==1||!visible(node)||node.matches('script,style,noscript,template,input,textarea,select,nav,header,footer'))return '';
  if(node.matches('[contenteditable="true"],[contenteditable="plaintext-only"]')&&!documentEditable(node)||node===activeEditor&&!documentEditable(node))return '';
  if(node.tagName==='BR')return '\n';
  if(node.matches('iframe,canvas'))return english?'\n[Embedded or canvas content not captured in this document.]\n':'\n[嵌入页面或画布内容未在此正文中采集。]\n';
  if(node.tagName==='TABLE'){
   const rows=Array.from(node.rows).filter(visible).map(row=>Array.from(row.cells).filter(visible).map(cell=>Array.from(cell.childNodes).map(walk).join('').trim().replace(/\n+/g,' ').replace(/\|/g,'&#124;')));
   if(!rows.length)return '';
   const width=Math.max(...rows.map(row=>row.length)),line=row=>'| '+Array.from({length:width},(_,index)=>row[index]||'').join(' | ')+' |';
   return '\n\n'+line(rows[0])+'\n'+line(Array(width).fill('---'))+'\n'+rows.slice(1).map(line).join('\n')+'\n\n';
  }
  const children=node.tagName==='SLOT'?(node.assignedNodes({flatten:true}).length?node.assignedNodes({flatten:true}):node.childNodes):node.shadowRoot?node.shadowRoot.childNodes:node.childNodes;
  return Array.from(children).map(walk).join('')+(blockTags.has(node.tagName)?'\n':'');
 }
 const text=walk(root).replace(/[\t ]+\n/g,'\n').replace(/\n{3,}/g,'\n\n').trim();
 const meaningful=text.replace(/\[(?:嵌入页面|Embedded or canvas)[^\]\n]*\]/gi,'').replace(/\s/g,'');
 const loginURL=/^(?:accounts?|passport|login)\./i.test(location.hostname)||/(?:^|\/)(?:login|signin|sign-in|passport|auth)(?:\/|$)/i.test(location.pathname);
 const password=select('input[type="password"]').some(visible);
 const signIn=!documentRoot&&text.length<1500&&/扫码登录|扫描二维码登录|登录飞书|Sign in to (?:Feishu|Lark)|Scan.{0,20}(?:log|sign) in/i.test(text);
 const denied=!documentRoot&&/没有访问权限|无访问权限|无权访问|你没有权限|您没有权限|Access denied|You do not have (?:access|permission)|Request access/i.test(text)&&text.length<1500;
 const loginButton=select('button,a').some(node=>visible(node)&&/^(?:登录|登入|Log in|Sign in)$/i.test((node.innerText||'').trim()));
 const progress=Array.from(root?.querySelectorAll('[aria-busy="true"],[role="progressbar"]')||[]).some(visible)||root?.getAttribute('aria-busy')==='true';
 const busy=documentRoot&&meaningful.length<40||progress&&meaningful.length<80||meaningful.length<120&&/正在加载|加载中|Loading\.\.\.|Please wait/i.test(text);
 return {title:document.title,text,url:location.href,login:loginURL||password||signIn||!documentRoot&&loginButton&&text.length<800,denied,busy,truncated,ready:document.readyState==='complete',document:documentRoot,readable_characters:meaningful.length};
}
