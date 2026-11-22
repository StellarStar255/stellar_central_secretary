/* Guided model and app-owned browser routes. URLs stay in the storage/API format. */
(()=>{
 const $=s=>document.querySelector(s),t=s=>StellarI18n.t(s);let dirty=false,revision=0;
 const id=(prefix,part)=>$('#'+prefix+'-proxy-'+part);
 function route(prefix,validate=true){
  const host=id(prefix,'location').value==='local'?'127.0.0.1':id(prefix,'host').value.trim(),port=id(prefix,'port').value.trim();
  if(!/^\d+$/.test(port)||Number(port)<1||Number(port)>65535){if(validate)throw Error(t(prefix==='model'?'模型代理：':'浏览器代理：')+t('请填写代理软件显示的端口数字（1–65535）。'));return ''}
  if(!host||host.includes('://')||/[\s/?#@]/.test(host)){if(validate)throw Error(t('这里填写代理所在电脑的 IP 或主机名；同一台电脑用 127.0.0.1。'));return ''}
  const type=prefix==='capture'?id(prefix,'type').value:'http';
  return type+'://'+(host.includes(':')&&!host.startsWith('[')?'['+host+']':host)+':'+port;
 }
 function toggle(){for(const prefix of ['model','capture']){const custom=id(prefix,'mode').value==='custom';id(prefix,'url-row').hidden=!custom;id(prefix,'host-row').hidden=id(prefix,'location').value!=='other';const url=route(prefix,false);id(prefix,'url').value=url;id(prefix,'preview').textContent=url?t('已填写端口：')+id(prefix,'port').value:t('请把代理软件中显示的端口数字填到上面。')}}
 function collect(){return {mode:id('model','mode').value,url:id('model','mode').value==='custom'?route('model'):''}}
 function collectBrowser(){return {mode:id('capture','mode').value,url:id('capture','mode').value==='custom'?route('capture'):''}}
 function fill(prefix,value){id(prefix,'mode').value=value?.mode||(prefix==='model'?'auto':'system');let parsed;try{parsed=new URL(value?.url||'')}catch{}id(prefix,'host').value=parsed?.hostname||'127.0.0.1';id(prefix,'location').value=parsed&&parsed.hostname!=='127.0.0.1'?'other':'local';id(prefix,'port').value=parsed?(parsed.port||(parsed.protocol==='socks5:'?'1080':'80')):'';if(prefix==='capture')id(prefix,'type').value=parsed?.protocol==='socks5:'?'socks5':'http'}
 function sync(value,browser,expected=revision){if(expected!==revision)return;if(!dirty){fill('model',value);fill('capture',browser)}toggle()}
 function saved(value,browser){revision++;dirty=false;sync(value,browser)}
 function bind({api}){
  const captureResult=$('#capture-connection-result');
  for(const prefix of ['model','capture']){
   for(const part of ['mode','location','host','port',...(prefix==='capture'?['type']:[])])for(const event of ['input','change'])id(prefix,part).addEventListener(event,()=>{dirty=true;revision++;toggle();$('#model-connection-result').textContent='';captureResult.textContent=''});
   id(prefix,'example').addEventListener('change',()=>{const sample=id(prefix,'example').value;if(!sample)return;const [type,port]=sample.includes(':')?sample.split(':'):['http',sample];dirty=true;revision++;id(prefix,'mode').value='custom';id(prefix,'host').value='127.0.0.1';id(prefix,'location').value='local';id(prefix,'port').value=port;if(prefix==='capture')id(prefix,'type').value=type;toggle();$('#model-connection-result').textContent='';id(prefix,'example').value=''});
  }
  for(const prefix of ['model','capture'])id(prefix,'example').addEventListener('change',()=>{captureResult.textContent=''});
  $('#capture-connection-test').onclick=async event=>{
   const button=event.currentTarget, expected=revision;
   button.disabled=true;
   captureResult.textContent=t('正在测试采集浏览器连接…');
   try{
    const capture_proxy=collectBrowser();
    const result=await api('/api/capture-connection/test',{capture_proxy,model_proxy:capture_proxy.mode==='model'?collect():undefined});
    if(expected!==revision)return;
    const route={direct:'直连',system:'由 Chrome 使用系统代理'}[result.route]||result.route;
    const messages={
     ok:'采集浏览器已访问 ChatGPT 首页。',
     proxy_port:'无法连接代理，请核对代理类型和端口。',
     proxy_tunnel:'代理未能建立到目标网站的连接。',
     tls:'到 ChatGPT 的 TLS 握手或证书校验失败。',
     blocked:'已连接到网站，网站拒绝了本次测试请求。',
     http:'已连接到网站，网站返回错误。',
     timeout:'等待 ChatGPT 首页响应超时。',
     network:'采集浏览器未能访问 ChatGPT 首页。',
     browser:'无法启动用于测试的 Chrome。',
     no_chrome:'未找到 Google Chrome。'
    };
    const mode={system:'使用系统浏览器代理',model:'与上面的模型连接一致',direct:'不使用代理',custom:'使用另一个代理'}[result.mode];
    captureResult.textContent=[t(mode),route&&t(route),t(messages[result.stage]),result.status&&'HTTP '+result.status,result.code].filter(Boolean).join(' · ');
   }catch(error){if(expected===revision)captureResult.textContent=error.message}
   finally{button.disabled=false}
  };
  for(const prefix of ['model','capture'])id(prefix,'check').onclick=async()=>{const button=id(prefix,'check');button.disabled=true;$('#proxy-port-result').textContent=t('正在检查代理端口…');try{const browser=prefix==='capture',capture_proxy=browser?collectBrowser():undefined;const result=await api('/api/proxy/check',{browser,model_proxy:!browser||capture_proxy.mode==='model'?collect():undefined,capture_proxy});$('#proxy-port-result').textContent=t(result.message)}catch(error){$('#proxy-port-result').textContent=t(error.message)}finally{button.disabled=false}};
  $('#model-connection-test').onclick=async()=>{const button=$('#model-connection-test');button.disabled=true;let timer;const start=Date.now();$('#model-connection-result').textContent=t('正在检查代理端口…');try{const body={backend:$('#backend').value,model_proxy:collect()};if(body.backend==='api')body.model_api=StellarModelAPI.collect();await api('/api/proxy/check',{model_proxy:body.model_proxy,backend:body.backend,base_url:body.model_api?.base_url});$('#model-connection-result').textContent=t('代理检查完成，正在等待模型响应…');timer=setInterval(()=>{$('#model-connection-result').textContent=t('正在等待模型响应，已用时 ')+Math.floor((Date.now()-start)/1000)+t(' 秒')},1000);await api('/api/model-connection/test',body);$('#model-connection-result').textContent=t('模型连接测试成功')+' · '+Math.round((Date.now()-start)/1000)+t(' 秒')}catch(error){$('#model-connection-result').textContent=t(error.message)}finally{clearInterval(timer);button.disabled=false}};

 }
 globalThis.StellarModelProxy={sync,collect,collectBrowser,saved,bind,revision:()=>revision};
})();
