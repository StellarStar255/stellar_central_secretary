/* Local semantic indexing is independent of the model used to answer questions. */
(()=>{
 const $=s=>document.querySelector(s),t=s=>StellarI18n.t(s);let api,dirty=false,loading=false;
 function collect(){return {enabled:$('#semantic-enabled').checked,base_url:$('#semantic-url').value.trim(),model:$('#semantic-model').value.trim(),min_score:Number($('#semantic-score').value)}}
 function sync(state){
  if(!dirty){$('#semantic-enabled').checked=state.config.enabled;$('#semantic-url').value=state.config.base_url;$('#semantic-model').value=state.config.model;$('#semantic-score').value=state.config.min_score}
  $('#semantic-progress').textContent=t(state.config.enabled?'已建立语义索引：':'语义检索已关闭；已保留索引：')+state.indexed+' / '+state.total+t(' 个片段')+(state.building?' · '+t('正在补建索引…'):'');
  error(state.error?StellarI18n.message(state.error):'');
 }
 function error(message){$('#semantic-error').textContent=message;$('#semantic-error').hidden=!message}
 async function refresh(){if(loading||!api)return;loading=true;try{sync(await api('/api/semantic'))}catch(exc){error(exc.message)}finally{loading=false}}
 async function save(){if(!dirty)return;const result=await api('/api/semantic/settings',collect());dirty=false;sync(result)}
 function bind(options){api=options.api;
  for(const node of $('#semantic-settings').querySelectorAll('input'))node.addEventListener('input',()=>{dirty=true});
  $('#semantic-save').onclick=async()=>{const button=$('#semantic-save');button.disabled=true;try{await save();options.toast(t('语义检索设置已保存，索引会在后台自动更新。'))}catch(exc){error(exc.message)}finally{button.disabled=false}};
  $('#semantic-test').onclick=async()=>{const button=$('#semantic-test');button.disabled=true;$('#semantic-test-result').textContent=t('正在测试本机嵌入服务…');try{const result=await api('/api/semantic/test',collect());$('#semantic-test-result').textContent=t('本机嵌入服务可用，向量维度：')+result.dimensions}catch(error){$('#semantic-test-result').textContent=error.message}finally{button.disabled=false}};
  $('#semantic-rebuild').onclick=async()=>{const button=$('#semantic-rebuild');button.disabled=true;try{const result=await api('/api/semantic/rebuild',collect());dirty=false;sync(result);options.toast(t('已开始重建语义索引，原资料保持不变。'))}catch(exc){error(exc.message)}finally{button.disabled=false}};
  for(const id of ['#settings-open','#model-open'])$(id).addEventListener('click',refresh);
  async function poll(){if($('#settings-dialog').open)await refresh();setTimeout(poll,3000)}setTimeout(poll,3000);
 }
 globalThis.StellarSemantic={bind,save,refresh};
})();
