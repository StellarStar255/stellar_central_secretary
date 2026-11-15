/* Exercise popup orchestration and the actual injected extraction callback. */
const fs = require('fs'), vm = require('vm'), assert = require('assert');
const code = fs.readFileSync('browser-extension/popup.js', 'utf8');
async function scenario(options = {}) {
  const elements = Object.fromEntries(['capture','status','export','view'].map(id => [id, {hidden:true}]));
  const posts = [], downloads = [];
  const page = {window:{getSelection:()=>({toString:()=>options.selection || ''})}, document:{title:'Fixture'},
    location:{hostname:options.host || 'example.com', pathname:options.path || '/', href:'https://' + (options.host || 'example.com') + (options.path || '/')},
    extractKnowledgeConversation:()=>({text:options.empty ? '' : 'Synthetic article', messages:options.messages || [], diagnostics:options.diagnostics || {}}), Date};
  const ctx = {document:{getElementById:id=>elements[id]}, AbortSignal, Blob, URL, crypto:require('crypto').webcrypto, setTimeout:()=>{},
    chrome:{tabs:{create:async data=>downloads.push(data),query:async()=>[{id:1,title:'Fixture',url:options.url || page.location.href}]}, scripting:{executeScript:async request=>{
      if(request.files) return [];
      return [{result:vm.runInNewContext('(' + request.func.toString() + ')()', page)}];
    }}, downloads:{download:async data=>downloads.push(data)}},
    fetch:async (url, request)=>{
      if(url.endsWith('/api/status')) {
        if(options.offline) throw Error('network');
        return {ok:true,json:async()=>({application:'stellar-central-secretary',token:'fixture'})};
      }
      posts.push(JSON.parse(request.body));
      if(options.timeout) throw Error('timeout');
      return {ok:!options.reject,status:403,json:async()=>options.reject ? {error:'请先确认资料权限'} : {created:!options.existing,item:{id:'a'.repeat(32),title:'Fixture',text:options.mismatch ? 'Old content' : posts.at(-1).text}}};
    }};
  vm.createContext(ctx);vm.runInContext(code,ctx);
  await new Promise(resolve=>setImmediate(resolve));
  await elements.capture.onclick();
  return {elements,posts,downloads};
}
(async()=>{
  let r=await scenario();assert.equal(r.posts.length,1);assert.match(r.elements.status.textContent,/已归档/);assert.equal(r.elements.capture.disabled,false);
  r=await scenario({selection:'Selected paragraph'});assert.equal(r.posts[0].text,'Selected paragraph');
  r=await scenario({host:'claude.ai',messages:[{role:'assistant',text:'Synthetic reply'}]});assert.match(r.posts[0].text,/^Claude：/);
  r=await scenario({host:'claude.ai',path:'/restricted'});assert.equal(r.posts.length,1);assert.equal(r.posts[0].archive_only,true);assert.match(r.elements.status.textContent,/已收藏链接/);
  r=await scenario({host:'claude.ai',path:'/restricted',selection:'Intentionally selected notice'});assert.equal(r.posts[0].text,'Intentionally selected notice');
  r=await scenario({offline:true});assert.equal(r.posts.length,0);assert.equal(r.elements.export.hidden,false);assert.match(r.elements.status.textContent,/未连接/);await r.elements.export.onclick();assert.equal(r.downloads.length,1);
  r=await scenario({reject:true});assert.match(r.elements.status.textContent,/请先确认资料权限/);assert.doesNotMatch(r.elements.status.textContent,/未连接/);assert.equal(r.downloads.length,0);
  r=await scenario({timeout:true});assert.match(r.elements.status.textContent,/可能已保存/);assert.equal(r.downloads.length,0);
  r=await scenario({existing:true});assert.match(r.elements.status.textContent,/本次未新增/);assert.equal(r.elements.view.hidden,false);await r.elements.view.onclick();assert.match(r.downloads[0].url,/\?item=a{32}$/);
  r=await scenario({mismatch:true});assert.match(r.elements.status.textContent,/本次正文尚未写入/);assert.equal(r.elements.export.hidden,false);assert.doesNotMatch(r.elements.status.textContent,/已归档：/);
  r=await scenario({host:'excalidraw.com'});assert.equal(r.posts.length,1);assert.equal(r.posts[0].archive_only,true);assert.match(r.elements.status.textContent,/未采集正文或绘图/);
  r=await scenario({host:'excalidraw.com'});assert.equal(r.posts.length,1);assert.equal(r.posts[0].archive_only,true);assert.equal(r.posts[0].text,'');assert.match(r.elements.status.textContent,/已收藏链接/);
  r=await scenario({empty:true,existing:true,mismatch:true});assert.match(r.elements.status.textContent,/链接已存在/);assert.doesNotMatch(r.elements.status.textContent,/正文尚未写入/);
  r=await scenario({url:'chrome://extensions/'});assert.equal(r.posts.length,0);
  r=await scenario({url:'chrome://extensions/'});assert.equal(r.posts.length,0);assert.match(r.elements.status.textContent,/普通网页/);
  r=await scenario({empty:true});assert.equal(r.posts[0].archive_only,true);
  r=await scenario({host:'excalidraw.com',selection:'Selected text'});assert.equal(r.posts[0].text,'Selected text');assert.notEqual(r.posts[0].archive_only,true);
  assert(!fs.readFileSync('browser-extension/popup.html','utf8').includes('id="bookmark"'));
  console.log('PASS: popup capture, selection, roles, restricted page, offline export, server rejection, uncertain save, internal page');
})().catch(error=>{console.error(error);process.exitCode=1});
