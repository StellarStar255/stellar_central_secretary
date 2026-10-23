/* Translate only UI source strings. Never walk newly rendered user content. */
(()=>{
 const messages=globalThis.StellarTranslations||{};
 const escape=value=>value.replace(/[.*+?^${}()|[\]\\]/g,'\\$&');
 const pattern=new RegExp(Object.keys(messages).sort((a,b)=>b.length-a.length).map(escape).join('|'),'g');
 let language='zh';try{language=new URLSearchParams(globalThis.location?.search||'').get('lang')||localStorage.getItem('stellar.ui-language')||'zh'}catch{}
 if(!['zh','en'].includes(language))language='zh';
 const originalNodes=[],originalAttributes=[];const originalTitle=typeof document!=='undefined'?document.title:'';
 function t(value){if(typeof value!=='string'||language!=='en')return value;return Object.hasOwn(messages,value)?messages[value]:value.replace(pattern,key=>messages[key]);}
 function message(value){return language==='en'&&Object.hasOwn(messages,value)?messages[value]:value;}
 function capture(){
  if(typeof document?.createTreeWalker!=='function')return;
  const walker=document.createTreeWalker(document.body,4);let node;
  while(node=walker.nextNode()){if(/[\u3400-\u9fff]/u.test(node.data)&&!node.parentElement?.closest('script,style,textarea'))originalNodes.push([node,node.data]);}
  for(const element of document.querySelectorAll('[placeholder],[title],[aria-label]'))for(const name of ['placeholder','title','aria-label']){const value=element.getAttribute(name);if(value&&/[\u3400-\u9fff]/u.test(value))originalAttributes.push([element,name,value]);}
 }
 function apply(){if(document.documentElement)document.documentElement.lang=language==='en'?'en':'zh-CN';if(originalTitle)document.title=t(originalTitle);for(const [node,value] of originalNodes)if(node.isConnected)node.data=t(value);for(const [element,name,value] of originalAttributes)if(element.isConnected)element.setAttribute(name,t(value));}
 function setLanguage(value,{persist=true}={}){if(!['zh','en'].includes(value))throw Error('Unsupported display language');language=value;if(persist)try{localStorage.setItem('stellar.ui-language',value)}catch{}apply();}
 function ui(strings,...values){return strings.reduce((result,part,index)=>result+t(part)+(index<values.length?values[index]:''),'');}
 globalThis.StellarI18n={t,ui,message,count:(n,zh,one,many)=>n+' '+(language==='en'?(n===1?one:many):zh),setLanguage,apply,get language(){return language},get locale(){return language==='en'?'en-US':'zh-CN'}};
 capture();apply();
})();
