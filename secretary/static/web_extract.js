/* Rendered webpage content only: never inspect form values or credentials. */
function extractWebPage(options={}) {
  const limit=options.limit||120000,english=options.language==='en';
  const visible=node=>{if(!node||node.nodeType!==1)return false;const style=getComputedStyle(node);return style.display!=='none'&&style.visibility!=='hidden'&&style.opacity!=='0'&&!node.closest('[hidden],[aria-hidden="true"]')&&node.getClientRects().length>0;};
  const bodyText=(document.body?.innerText||'').slice(0,6000);
  const loginURL=/^(?:accounts?|passport|login)\./i.test(location.hostname)||/(?:^|\/)(?:login|signin|sign-in|passport|auth)(?:\/|$)/i.test(location.pathname);
  const password=Array.from(document.querySelectorAll('input[type="password"]')).some(visible);
  const signIn=/扫码登录|扫描二维码登录|登录飞书|Sign in to (?:Feishu|Lark)|Scan.{0,20}(?:log|sign) in/i.test(bodyText);
  const denied=/没有访问权限|无访问权限|无权访问|你没有权限|您没有权限|Access denied|You do not have (?:access|permission)|Request access/i.test(bodyText)&&bodyText.length<1500;
  const candidates=Array.from(document.querySelectorAll('[role="dialog"],main,[role="main"],article')).filter(visible).filter(node=>(node.innerText||'').trim().length>=80);
  const dialogs=candidates.filter(node=>node.getAttribute('role')==='dialog');
  const roots=dialogs.length?dialogs:candidates;
  const root=roots.sort((a,b)=>(b.innerText||'').length-(a.innerText||'').length)[0]||document.body;
  const activeEditor=document.activeElement?.closest('[contenteditable="true"]');
  let count=0,characters=0,truncated=false;
  const blocks=new Set(['P','DIV','SECTION','ARTICLE','LI','H1','H2','H3','H4','H5','H6','TR','UL','OL','BLOCKQUOTE']);
  function walk(node){
    if(++count>50000||characters>=limit){truncated=true;return '';}
    if(node.nodeType===3){const value=node.textContent.slice(0,Math.max(0,limit-characters));characters+=value.length;return value;}
    if(node.nodeType!==1||!visible(node)||node===activeEditor||node.matches('script,style,noscript,template,input,textarea,select,nav,header,footer,[contenteditable="true"]'))return '';
    if(node.tagName==='BR')return '\n';
    if(node.matches('iframe,canvas'))return english?'\n[Embedded or canvas content: open the original page to view it.]\n':'\n[嵌入页面或画布内容未采集，请在原网页查看。]\n';
    if(node.tagName==='TABLE'){
      const rows=Array.from(node.rows).filter(visible).map(row=>Array.from(row.cells).filter(visible).map(cell=>Array.from(cell.childNodes).map(walk).join('').trim().replace(/\n+/g,' ').replace(/\|/g,'&#124;')));
      if(!rows.length)return '';
      const width=Math.max(...rows.map(row=>row.length)),line=row=>'| '+Array.from({length:width},(_,index)=>row[index]||'').join(' | ')+' |';
      return '\n\n'+line(rows[0])+'\n'+line(Array(width).fill('---'))+'\n'+rows.slice(1).map(line).join('\n')+'\n\n';
    }
    const content=Array.from(node.childNodes).map(walk).join('');
    return content+(blocks.has(node.tagName)?'\n':'');
  }
  const text=walk(root).replace(/[\t ]+\n/g,'\n').replace(/\n{3,}/g,'\n\n').trim();
  const loginButton=Array.from(document.querySelectorAll('button,a')).some(node=>visible(node)&&/^(?:登录|登入|Log in|Sign in)$/i.test((node.innerText||'').trim()));
  const busy=Array.from(root?.querySelectorAll('[aria-busy="true"],[role="progressbar"]')||[]).some(visible)||text.length<600&&/正在加载|加载中|Loading\.\.\.|Please wait/i.test(text);
  return {title:document.title,text,url:location.href,login:loginURL||password||signIn||loginButton&&text.length<800,denied,busy,truncated,ready:document.readyState==='complete'};
}
