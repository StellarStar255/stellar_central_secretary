// Read rendered conversation content; never read input values or credentials.
function extractKnowledgeConversation() {
  const visible = node => {
    const style = getComputedStyle(node);
    return style.display !== 'none' && style.visibility !== 'hidden' &&
      !node.closest('[aria-hidden="true"]') && node.getClientRects().length > 0;
  };
  const main = document.querySelector('main') || document.body;
  const textOf = node => {
    // A reply may contain several markdown blocks. Read the whole turn.
    const clone = node.cloneNode(true);
    clone.querySelectorAll('button,nav,textarea,input,script,style,[aria-hidden="true"],h5.sr-only,h6.sr-only').forEach(n => n.remove());
    const blocks = new Set(['P','DIV','LI','PRE','BLOCKQUOTE','H1','H2','H3','H4','H5','H6','TR','UL','OL']);
    const walk = n => {
      if(n.nodeType === 3) return n.textContent;
      if(n.nodeType !== 1) return '';
      if(n.tagName === 'BR') return '\n';
      const content = Array.from(n.childNodes).map(walk).join('');
      return content + (blocks.has(n.tagName) ? '\n' : n.tagName === 'TD' || n.tagName === 'TH' ? '\t' : '');
    };
    return walk(clone).replace(/\n{3,}/g,'\n\n').trim();
  };
  const idOf = (node,index) => node.getAttribute('data-message-id') || node.closest('[data-message-id]')?.getAttribute('data-message-id') || node.getAttribute('data-testid') || '';
  const authorNodes = Array.from(main.querySelectorAll('[data-message-author-role]'));
  const legacy = authorNodes.filter(visible).map((node,index) => ({id:idOf(node,index),role:node.getAttribute('data-message-author-role'),text:textOf(node)}));
  const turns = Array.from(new Set(main.querySelectorAll('[data-testid^="conversation-turn"],article[data-turn],article[aria-label],[role="article"]'))).filter(visible);
  const turnMessages = turns.map((node,index) => {
    const author = node.querySelector('[data-message-author-role]');
    let role = node.getAttribute('data-turn') || node.getAttribute('data-message-author-role') || author?.getAttribute('data-message-author-role') || '';
    const label = (node.getAttribute('aria-label') || '') + '\n' + (node.querySelector('h5,h6,[data-testid="author"]')?.textContent || '');
    if(!['user','assistant'].includes(role)) {
      if(/ChatGPT|assistant|助手/i.test(label)) role='assistant';
      else if(/You said|your message|user|你说|你說|用户|使用者/i.test(label)) role='user';
    }
    return {id:idOf(author || node,index),role,text:textOf(author || node)};
  });
  const rawMain = main.innerText || '';
  const labeled=[];
  const pattern=/(?:^|\n)(You said|ChatGPT said|你说|你說|ChatGPT\s*说|ChatGPT\s*說)\s*[:：]\s*(?:\n|$)/g;
  const matches=Array.from(rawMain.matchAll(pattern));
  matches.forEach((match,index) => labeled.push({id:'',role:/ChatGPT/i.test(match[1])?'assistant':'user',text:rawMain.slice(match.index+match[0].length,index+1<matches.length?matches[index+1].index:rawMain.length).replace(/^(?:Worked for|Thought for|已思考|思考了)\s+[^\n]{1,60}$/gm,'').trim()}));
  const strategies=[['author-role',legacy],['conversation-turn',turnMessages],['visible-role-labels',labeled]].map(([name,messages]) => ({name,messages:messages.filter(m=>['user','assistant'].includes(m.role)&&m.text)}));
  const rank = strategy => strategy.messages.length + (strategy.messages.some(m=>m.role==='assistant')?10000:0);
  strategies.sort((a,b)=>rank(b)-rank(a));
  const chosen=strategies[0];
  const stopButtons=Array.from(document.querySelectorAll('[data-testid="stop-button"],button[aria-label="Stop generating"],button[aria-label="停止生成"]'));
  const generating=stopButtons.some(n=>visible(n)&&!n.disabled&&n.getAttribute('aria-disabled')!=='true');
  const loginNodes=Array.from(document.querySelectorAll('[data-testid="login-button"],a[href*="/auth/login"]'));
  const login=loginNodes.some(visible) || Array.from(document.querySelectorAll('button')).some(n=>visible(n)&&/^(Log in|Login|登录|登入)$/i.test(n.innerText.trim()));
  const pageText=(document.body.innerText||'').slice(0,8000);
  const denied=/Unable to load conversation|Conversation not found|You do not have access|无法加载对话|无法加载会话|找不到对话|没有权限/i.test(pageText);
  return {messages:chosen.messages,diagnostics:{url:location.origin+location.pathname,title:document.title,readyState:document.readyState,method:chosen.name,authorNodes:authorNodes.length,turnNodes:turns.length,messages:chosen.messages.length,assistantMessages:chosen.messages.filter(m=>m.role==='assistant').length,mainChars:rawMain.length,hints:Array.from(main.querySelectorAll('article,[data-testid],[data-turn],[data-message-author-role],[role="article"]')).slice(0,25).map(n=>({tag:n.tagName,testid:n.getAttribute('data-testid'),turn:n.getAttribute('data-turn'),author:n.getAttribute('data-message-author-role'),role:n.getAttribute('role'),textChars:(n.innerText||'').length})),stopButtons:stopButtons.length,visibleStopButtons:stopButtons.filter(visible).length,generating,login,denied}};
}
