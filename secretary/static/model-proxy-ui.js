/* A shared route for model calls; browser capture keeps its existing route. */
(()=>{
 const $=s=>document.querySelector(s),t=s=>StellarI18n.t(s);let dirty=false;
 function toggle(){$('#model-proxy-url-row').hidden=$('#model-proxy-mode').value!=='custom';$('#model-proxy-url').disabled=$('#model-proxy-mode').value!=='custom'}
 function collect(){return {mode:$('#model-proxy-mode').value,url:$('#model-proxy-mode').value==='custom'?$('#model-proxy-url').value.trim():''}}
 function sync(value){if(!dirty){$('#model-proxy-mode').value=value?.mode||'auto';$('#model-proxy-url').value=value?.url||''}toggle()}
 function saved(value){dirty=false;sync(value)}
 function bind({api}){
  for(const id of ['#model-proxy-mode','#model-proxy-url'])$(id).addEventListener('input',()=>{dirty=true;toggle();$('#model-connection-result').textContent=''});
  $('#model-proxy-mode').addEventListener('change',()=>{dirty=true;toggle()});
  $('#model-connection-test').onclick=async()=>{const button=$('#model-connection-test');button.disabled=true;$('#model-connection-result').textContent=t('正在测试模型连接…');try{const body={backend:$('#backend').value,model_proxy:collect()};if(body.backend==='api')body.model_api=StellarModelAPI.collect();await api('/api/model-connection/test',body);$('#model-connection-result').textContent=t('模型连接测试成功')}catch(error){$('#model-connection-result').textContent=t(error.message)}finally{button.disabled=false}};
 }
 globalThis.StellarModelProxy={sync,collect,saved,bind};
})();
