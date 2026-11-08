/* Upload large files in bounded chunks; failed uploads can be retried independently. */
(()=>{
 let api=null;const active=new Set();
 async function encode(file,onProgress=()=>{}){
  if(file.size<=8*1024*1024)return {name:file.name,data:await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(String(reader.result).split(',')[1]);reader.onerror=()=>reject(Error('无法读取 '+file.name));reader.readAsDataURL(file)})};
  const created=await api('/api/uploads/start',{name:file.name,size:file.size}),id=created.id;active.add(id);
  try{
   const status=await api('/api/status');
   for(let offset=0;offset<file.size;){const chunk=file.slice(offset,offset+4*1024*1024);const response=await fetch('/api/uploads/'+id+'/chunk',{method:'POST',headers:{'Content-Type':'application/octet-stream','X-Knowledge-Token':status.token,'X-Upload-Offset':String(offset)},body:chunk});const value=await response.json();if(!response.ok)throw Error(value.error||'上传失败');offset=value.offset;onProgress(file.name,Math.round(offset/file.size*100))}
   return {name:file.name,upload_id:id};
  }catch(error){await api('/api/uploads/'+id+'/cancel',{}).catch(()=>{});active.delete(id);throw error}
 }
 async function cleanup(){for(const id of [...active]){await api('/api/uploads/'+id+'/cancel',{}).catch(()=>{});active.delete(id)}}
 globalThis.StellarUploads={encode,cleanup,bind:fn=>{api=fn}};
})();
