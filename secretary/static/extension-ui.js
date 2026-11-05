/* Export packaged extension files without asking users to find the source checkout. */
(()=>{
 const $=selector=>document.querySelector(selector),t=key=>StellarI18n.t(key);
 let options,preparing=false;
 async function prepare(){
  if(preparing)return;preparing=true;$('#extension-open-folder').disabled=true;$('#extension-copy-path').disabled=true;$('#extension-retry').hidden=true;$('#extension-directory').value='';$('#extension-prepare-status').textContent=t('正在准备扩展文件…');
  try{const result=await options.api('/api/browser-extension/prepare',{});$('#extension-directory').value=result.path;$('#extension-open-folder').disabled=false;$('#extension-copy-path').disabled=false;$('#extension-prepare-status').textContent=t('扩展文件已准备好，版本：')+result.version}
  catch(error){$('#extension-prepare-status').textContent=StellarI18n.message(error.message);$('#extension-retry').hidden=false}
  finally{preparing=false}
 }
 function open(config){
  options=config;if(!$('#extension-dialog').open)$('#extension-dialog').showModal();
  $('#extension-directory').onclick=event=>event.target.select();
  $('#extension-copy-path').onclick=async()=>{const path=$('#extension-directory').value;try{await navigator.clipboard.writeText(path);options.toast(t('扩展文件夹路径已复制'))}catch{const input=$('#extension-directory');input.focus();input.select();options.toast(t('请按 ⌘ / Ctrl + C 复制已选中的路径。'))}};
  $('#extension-open-folder').onclick=async()=>{const button=$('#extension-open-folder');button.disabled=true;try{await options.api('/api/browser-extension/open',{});options.toast(t('扩展文件夹已打开'))}catch(error){options.toast(error.message)}finally{button.disabled=false}};
  $('#extension-retry').onclick=prepare;return prepare();
 }
 globalThis.StellarExtensionUI={open};
})();
