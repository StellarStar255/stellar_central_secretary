/* Keys are write-only inputs and never stored in browser caches. */
(()=>{
 const $=s=>document.querySelector(s),t=s=>StellarI18n.t(s);let dirty=false,config=null;
 function toggle(){$('#model-api-settings').hidden=$('#backend').value!=='api';$('#api-key').disabled=$('#api-no-key').checked}
 function sync(value){if(value)config=value;if(!dirty&&config){$('#api-base-url').value=config.base_url;$('#api-model').value=config.model;$('#api-vision').checked=config.vision;$('#api-json').checked=config.json_mode;$('#api-max-tokens').value=config.max_tokens;$('#api-token-parameter').value=config.token_parameter||'max_tokens';$('#api-no-key').checked=!config.use_key;$('#api-key').placeholder=t(config.has_key?'密钥已保存，留空保持':'输入 API Key')}toggle()}
 function collect(){return {base_url:$('#api-base-url').value.trim(),model:$('#api-model').value.trim(),api_key:$('#api-key').value.trim(),vision:$('#api-vision').checked,json_mode:$('#api-json').checked,max_tokens:Number($('#api-max-tokens').value),token_parameter:$('#api-token-parameter').value,use_key:!$('#api-no-key').checked}}
 function saved(value){$('#api-key').value='';dirty=false;sync(value)}
 function bind({api}){for(const node of $('#model-api-settings').querySelectorAll('input,select'))node.addEventListener('input',()=>{dirty=true;toggle()});$('#backend').addEventListener('change',toggle);
  $('#api-deepseek').onclick=()=>{dirty=true;$('#api-base-url').value='https://api.deepseek.com';$('#api-model').value='deepseek-flash';$('#api-vision').checked=true;$('#api-json').checked=true;$('#api-no-key').checked=false;$('#api-max-tokens').value=8192;$('#api-token-parameter').value='max_tokens';toggle()};
  $('#api-test').onclick=async()=>{const button=$('#api-test');button.disabled=true;$('#api-test-result').textContent=t('正在测试 API 连接…');try{await api('/api/model-api/test',collect());$('#api-test-result').textContent=t('API 连接测试成功')}catch(error){$('#api-test-result').textContent=StellarI18n.message(error.message)}finally{button.disabled=false}}}
 globalThis.StellarModelAPI={sync,collect,saved,bind};
})();
