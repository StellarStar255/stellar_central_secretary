const fs=require('fs'),vm=require('vm'),assert=require('assert');
const html=fs.readFileSync('secretary/static/index.html','utf8');
const elements=new Map();
function element(){return {value:'',textContent:'',innerHTML:'',disabled:false,hidden:false,open:false,style:{},dataset:{},scrollHeight:100,scrollTop:0,clientHeight:500,classList:{add(){},remove(){},toggle(){}},querySelectorAll(){return[]},querySelector(){return element()},addEventListener(){},focus(){},showModal(){this.open=true},close(){this.open=false},append(){}}}
for(const id of html.matchAll(/id="([^"]+)"/g))elements.set('#'+id[1],element());
elements.get('#backend').value='codex';elements.get('#input-mode').value='auto';
const calls=[],stored=new Map(),listeners={};let rejectNextConfirmation=false,failNextConfirmation=false;let archive=[];let captureCapability=true,captureReplyMode='current';
const context={URL,AbortController,console,crypto:require('crypto').webcrypto,setTimeout:()=>1,clearTimeout(){},setInterval(){},navigator:{clipboard:{writeText:async()=>{}}},localStorage:{getItem:k=>stored.get(k),setItem:(k,v)=>stored.set(k,v)},window:{innerWidth:1200,addEventListener(){}},document:{body:{classList:{add(){},remove(){},toggle(){}}},hidden:false,querySelector(selector){if(!elements.has(selector))throw Error('Missing DOM element '+selector);return elements.get(selector)},querySelectorAll(){return[]},addEventListener(type,callback){(listeners[type]??=[]).push(callback)},createElement:()=>element()},fetch:async(path,options)=>{
 const body=options?.body?JSON.parse(options.body):undefined;calls.push({path,body});
 let data;if(path==='/api/status')data={token:'test',capabilities:captureCapability?{conversation_capture:true,manual_browser_login:true,profile_window_reuse:true,in_place_browser_read:true}:{},settings:{backend:'codex',auto_ai:true},backends:{codex:true,claude:true},data_dir:'/tmp/test'};
 else if(path.endsWith('/confirm-login')){
  if(rejectNextConfirmation){rejectNextConfirmation=false;return{ok:false,status:403,json:async()=>({error:'请求验证失败'})}}
  if(failNextConfirmation){failNextConfirmation=false;return{ok:false,status:400,json:async()=>({error:'登录任务已经结束，请重新打开浏览器'})}}
  archive[0].state='confirming_login';data={login_confirmed:true,item:archive[0]};
 }
 else if(path.endsWith('/capture'))data=captureReplyMode==='current'?{capture_started:true,item:archive[0]}:{ok:true};
 else if(path.startsWith('/api/items/')&&options?.method==='POST'){archive.find(i=>i.id===path.split('/').pop()).state='processing';data={ok:true}}
 else if(path.startsWith('/api/items'))data=archive;
 else if(path==='/api/ingest'){const item={id:'a'+archive.length,title:body.url||'笔记',url:body.url||'',kind:body.url?'link':'note',category:'未分类',state:'pending',text:body.text||'',summary:'',tags:[],created:new Date().toISOString()};archive.push(item);data={created:true,item}}
 else if(path==='/api/conversations')data=body||{conversations:[],activeId:''};
 else if(path==='/api/interface')data={ok:true,mode:body.mode};
 else if(path==='/api/ask')data={answer:'这是带来源的答案。',sources:[{number:1,item_id:'a0',title:'来源资料'}]};
 else throw Error('unexpected API '+path);
 return{ok:true,json:async()=>data};
}};
vm.createContext(context);for(const file of ['i18n-data.js','i18n.js','app.js'])vm.runInContext(fs.readFileSync('secretary/static/'+file,'utf8'),context);
const sample='用户：\n解释一下 ETF\n\nChatGPT：\n## 基金\n\n**重点**\n\n1. 第一项\n2. 第二项\n\n```text\n用户：\n<script>alert(1)</script>\n```\n\n用户：\n继续\n\nClaude：\n[原件](https://example.com)';
context.readerSample=sample;
assert.equal(vm.runInContext('parseArchivedConversation(readerSample).length',context),4);
const rendered=vm.runInContext('renderArchivedBody({kind:"link",text:readerSample})',context);
assert.equal((rendered.match(/class="reader-turn /g)||[]).length,4);
assert(rendered.includes('reader-user')&&rendered.includes('reader-assistant'));
assert(rendered.includes('<strong>重点</strong>')&&rendered.includes('<ol><li>第一项</li><li>第二项</li></ol>'));
assert(rendered.includes('&lt;script&gt;alert(1)&lt;/script&gt;')&&!rendered.includes('<script>'));
assert(rendered.includes('rel="noopener noreferrer"'));
assert(!vm.runInContext('readerMarkdown("[恶意](javascript:alert(1))")',context).includes('href='));
assert.equal(vm.runInContext('parseArchivedConversation("普通文章\\n用户：\\n正文\\nChatGPT：\\n正文").length',context),0);
assert(vm.runInContext('renderArchivedBody({kind:"file",text:readerSample})',context).includes('detail-text'));
async function flush(){for(let i=0;i<12;i++)await new Promise(r=>setImmediate(r))}
(async()=>{
 await flush();assert.equal(elements.get('#model-label').textContent,'ChatGPT · Codex');
 const input=elements.get('#message-input'),form=elements.get('#composer-form');
 input.value='https://chatgpt.com/c/test';await form.onsubmit({preventDefault(){}});
 assert(calls.some(c=>c.path==='/api/ingest'&&c.body.url===inputUrl));
 function countAsk(){return calls.filter(c=>c.path==='/api/ask').length}
 assert.equal(countAsk(),0);assert(elements.get('#messages').innerHTML.includes('archive-card'));
 input.value='知识管理有哪些结论？';await form.onsubmit({preventDefault(){}});
 assert.equal(countAsk(),1);assert(elements.get('#messages').innerHTML.includes('这是带来源的答案'));
 elements.get('#input-mode').value='note';input.value='今天的产品研究笔记';await form.onsubmit({preventDefault(){}});
 assert(calls.some(c=>c.path==='/api/ingest'&&c.body.text==='今天的产品研究笔记'));
 assert.equal(countAsk(),1);assert(JSON.parse(stored.get('stellar.conversations.v1')).conversations[0].messages.length===6);
 captureCapability=false;
 const captureCount=calls.filter(c=>c.path.endsWith('/capture')).length;
 await assert.rejects(vm.runInContext('requestCapture("a0")',context),/旧版本/);
 assert.equal(calls.filter(c=>c.path.endsWith('/capture')).length,captureCount);
 assert.equal(elements.get('#service-alert').hidden,false);
 captureCapability=true;captureReplyMode='legacy';
 await assert.rejects(vm.runInContext('requestCapture("a0")',context),/未确认/);
 captureReplyMode='current';
 await vm.runInContext('requestCapture("a0")',context);
 assert.equal(elements.get('#service-alert').hidden,true);
 assert(elements.get('#toast').textContent.includes('任务已提交'));
 await vm.runInContext('confirmLogin("a0")',context);
 assert(calls.some(c=>c.path.endsWith('/confirm-login')));
 archive[0].state='waiting_login';await vm.runInContext('refresh()',context);
 assert(elements.get('#messages').innerHTML.includes('data-confirm-login'));
 const button={disabled:false,dataset:{confirmLogin:'a0'},hasAttribute(){return false}};
 const click={target:{closest(){return button}},preventDefault(){}};
 const before=calls.filter(c=>c.path.endsWith('/confirm-login')).length;
 rejectNextConfirmation=true;
 for(const handler of listeners.click)handler(click);
 assert(elements.get('#messages').innerHTML.includes('正在提交登录确认'));
 await flush();
 assert.equal(calls.filter(c=>c.path.endsWith('/confirm-login')).length,before+2);
 assert(elements.get('#messages').innerHTML.includes('正在准备读取'));
 archive[0].state='waiting_login';await vm.runInContext('refresh()',context);
 failNextConfirmation=true;for(const handler of listeners.click)handler(click);await flush();
 assert(elements.get('#messages').innerHTML.includes('操作失败：登录任务已经结束'));
 assert(!elements.get('#messages').innerHTML.includes('确认中…'));
 archive[0].state='error';archive[0].text_length=3658;await vm.runInContext('refresh()',context);
 assert(elements.get('#messages').innerHTML.includes('data-summarize'));
 const readsBefore=calls.filter(c=>c.path.endsWith('/capture')).length;
 await vm.runInContext('performCaptureAction("a0","summary")',context);
 assert(calls.some(c=>c.path==='/api/items/a0'&&c.body));
 assert.equal(calls.filter(c=>c.path.endsWith('/capture')).length,readsBefore);
 assert(elements.get('#messages').innerHTML.includes('使用已保存的正文'));
 elements.get('#new-chat').onclick();assert.equal(elements.get('#messages').innerHTML,'');assert.equal(archive.length,2);
 const askBeforeNotes=countAsk();elements.get('#input-mode').value='auto';
 for(const text of ['cd /mnt/data/example\n  tar -czf samples.tar.gz samples/','curl https://example.invalid/data?format=json','```bash\necho "what?"\n```','量化校准集应覆盖实际输入分布。','请保存以下命令：\ngit status']){
  const before=calls.length;input.value=text;await form.onsubmit({preventDefault(){}});
  assert(calls.slice(before).some(c=>c.path==='/api/ingest'&&c.body.text===text&&!c.body.url),text);
  assert(!calls.slice(before).some(c=>c.path==='/api/ingest'&&c.body.url),text);
  assert.equal(countAsk(),askBeforeNotes,text);
 }
 elements.get('#input-mode').value='group';input.value='一份纯文字组合资料';await form.onsubmit({preventDefault(){}});
 assert(calls.some(c=>c.path==='/api/ingest'&&c.body.text==='一份纯文字组合资料'&&!c.body.attachments));
 elements.get('#input-mode').value='auto';input.value='什么是量化校准集';await form.onsubmit({preventDefault(){}});assert.equal(countAsk(),askBeforeNotes+1);
 input.value='量化校准集有哪些要求';await form.onsubmit({preventDefault(){}});assert.equal(countAsk(),askBeforeNotes+2);
 elements.get('#input-mode').value='note';input.value='为什么命令中需要引号？';await form.onsubmit({preventDefault(){}});assert.equal(countAsk(),askBeforeNotes+2);
 elements.get('#input-mode').value='ask';input.value='tar -czf samples.tar.gz samples/';await form.onsubmit({preventDefault(){}});assert.equal(countAsk(),askBeforeNotes+3);
 console.log('PASS: automatic command/knowledge archiving, literal whitespace and URLs retained, no retrieval or URL fetch for commands, explicit archive/ask overrides and text-only group');
 console.log('PASS: startup, link archive, question with sources, save note, history persistence, new chat preserves archive, legacy backend and false-success rejection, delegated confirmation click, expired-token retry, persistent failure feedback');
})().catch(e=>{console.error(e);process.exitCode=1});
const inputUrl='https://chatgpt.com/c/test';
// Rich text regression checks are also run by CI with the existing UI harness.
const markdownTable=vm.runInContext('readerMarkdown("| 需求 | 普通基金 | ETF |\\n| --- | --- | --- |\\n| **定投** | 更方便 | 取决于券商 |")',context);
assert(markdownTable.includes('<table>')&&markdownTable.includes('<th scope="col">需求</th>')&&markdownTable.includes('<strong>定投</strong>'));
assert(vm.runInContext('readerMarkdown("需求\\t普通基金\\tETF\\n定投\\t更方便\\t券商功能")',context).includes('<table>'));
const chartFixture={version:1,background:'#111',tree:{tag:'svg',attrs:{viewBox:'0 0 600 240',width:600,height:240},children:[{tag:'path',attrs:{d:'M0 100 L300 50 L600 10',stroke:'#e99a65','stroke-width':2},children:[]},{tag:'text',attrs:{x:20,y:200,fill:'white'},text:'2018 <标签>',children:[]}]}};
context.chartFixture=chartFixture;
const chartMarkup=vm.runInContext('readerMarkdown("```stellar-chart\\n"+JSON.stringify(chartFixture)+"\\n```")',context);
assert(chartMarkup.includes('<svg')&&chartMarkup.includes('<path')&&chartMarkup.includes('2018 &lt;标签&gt;'));
context.chartAttack={version:1,tree:{tag:'svg',attrs:{viewBox:'0 0 500 200',onload:'alert(1)'},children:[{tag:'text',attrs:{onclick:'alert(2)',fill:'url(https://example.com/track)'},text:'<img onerror=alert(3)>',children:[]}]}};
const safeChart=vm.runInContext('readerChart(JSON.stringify(chartAttack))',context);
assert(!safeChart.includes(' onload=')&&!safeChart.includes(' onclick=')&&!safeChart.includes('url(')&&safeChart.includes('&lt;img'));
context.chartAttack.tree.children.push({tag:'script',text:'alert(1)'});
assert(vm.runInContext('readerChart(JSON.stringify(chartAttack))',context).includes('无法显示'));
assert(!vm.runInContext('readerMarkdown("```json\\n{\\"x\\":\\"<svg onload=evil()>\\"}\\n```")',context).includes('<svg'));
assert.equal(fs.readFileSync('browser-extension/extract.js','utf8'),fs.readFileSync('secretary/static/extract.js','utf8'));
console.log('PASS: markdown and legacy tables, chart snapshots, untrusted SVG rejection, shared extension extractor');

context.legendChart={...chartFixture,legend:[{label:'系列 <甲>',color:'#123456'}],dataText:'原始数据 <script>test</script>'};
const withLegend=vm.runInContext('readerChart(JSON.stringify(legendChart))',context);
assert(withLegend.includes('reader-chart-legend')&&withLegend.includes('系列 &lt;甲&gt;')&&withLegend.includes('查看图表数据与说明'));
assert(withLegend.includes('&lt;script&gt;test&lt;/script&gt;')&&!withLegend.includes('<script>'));
