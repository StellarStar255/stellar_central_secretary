'use strict';
const $=selector=>document.querySelector(selector);
const escapeHtml=value=>String(value).replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
const lessons=[
 {title:'存下第一份 PDF',short:'导入资料',sub:'原件与概览',instruction:'点击练习区的「导入示例 PDF」，看看原件和摘要如何放在一起。',hint:'无需选择自己的文件。这里使用虚构月刊和预置概览。',tip:'在输入框点「＋」或拖入文件后发送。原件会保存在本机；PDF 默认只用前 5 页生成概览，需要时再生成全文摘要。'},
 {title:'空格分词，准确找回',short:'组合搜索',sub:'全部包含，顺序不限',instruction:'在搜索框输入「科学月刊 6月」，只找同时包含两个词的资料。',hint:'也可以输入「6月 科学月刊」。连续空格和全角空格都可以。',tip:'左侧「搜索知识库」支持多个关键词，按全部包含、顺序不限匹配；关键词可分布在标题、正文、摘要和标签等字段中。'},
 {title:'把标题改成你习惯的名字',short:'修改标题',sub:'保留正文与摘要',instruction:'点击资料标题或小铅笔，改个名字，再保存。',hint:'试试「我的六月阅读清单」。Enter 保存，Esc 取消。',tip:'在资料详情点击标题即可修改。单独改名直接保存，不会触发 AI 重新整理，也不会改动正文、摘要或原件。'},
 {title:'随时打开 PDF 原件',short:'阅读 PDF',sub:'浏览器或默认程序',instruction:'点击「浏览器打开 PDF」，在新标签页看一眼示例文件。',hint:'关闭 PDF 标签页即可回到教程。这里没有访问你的真实文件。',tip:'真实 PDF 详情有「浏览器打开 PDF」和「默认程序打开」。两者都使用已保存的原件；下载原文件入口也会保留。'},
 {title:'选择桌面或网页模式',short:'切换模式',sub:'在模型与设置中',instruction:'先点练习区左侧「模型与设置」，再切换使用方式。',hint:'本步骤仅模拟切换位置，不会修改你真实程序的设置。',tip:'macOS 安装版在「模型与设置 → 使用方式」切换桌面窗口或网页模式。两种模式共用知识库和对话，程序记住选择；托盘也可切换。'},
 {title:'把知识库备份带走',short:'备份资料',sub:'原件也在里面',instruction:'点击练习区左下角「导出知识库备份」，查看备份中包含什么。',hint:'这里只展示备份清单，不会下载文件，也不会导出你的资料。',tip:'真实程序的「导出知识库备份」会生成 ZIP，包含原文件、数据库和 JSON 清单。换电脑后通过「导入知识库备份」合并恢复。'}
];
let current=0,done=new Set(),imported=false,renamedTitle='科学月刊 · 2026年6月',mode='browser',pdfUrl='';
const sampleSummary='《科学月刊》2026年6月的虚构示例，介绍月球探索、机器人与能源。概览为教程预置，不代表真实模型结果。';
function ensureFile(){imported=true;$('#recent-file').hidden=false;$('#recent-file').textContent='▧ '+renamedTitle;}
function progress(){
 $('#steps').innerHTML=lessons.map((lesson,index)=>`<button class="step ${index===current?'active':''} ${done.has(index)?'done':''}" data-step="${index}" ${index===current?'aria-current="step"':''}><span>${done.has(index)?'✓':index+1}</span><div><strong>${lesson.short}</strong><small>${lesson.sub}</small></div></button>`).join('');
 $('#steps').querySelectorAll('[data-step]').forEach(button=>button.onclick=()=>go(Number(button.dataset.step)));
 $('#previous').disabled=current===0;$('#next').disabled=!done.has(current);$('#next').textContent=current===5?'查看学习结果 →':'下一步 →';$('#completion').textContent=`已完成 ${done.size} / ${lessons.length}`;
}
function complete(index,message){done.add(index);progress();$('#feedback').textContent=message;}
function go(index){
 current=index;const lesson=lessons[index];$('#step-number').textContent=`练习 ${index+1} / ${lessons.length}`;$('#lesson-title').textContent=lesson.title;$('#instruction').textContent=lesson.instruction;$('#hint').textContent=lesson.hint;$('#real-tip').textContent=lesson.tip;$('#feedback').textContent=done.has(index)?'✓ 这一步已经完成，可以再次练习。':'';
 if(index>0)ensureFile();
 if(index===1)showSearch();else if(index===2||index===3)showDetail();else showHome();progress();
}
function showHome(){
 $('#workspace-content').innerHTML=`<div class="welcome"><span class="star">✳</span><h3>存下资料，留待以后找回。</h3><p>示例：一份六月月刊 PDF。教程不会请求文件权限，也不会调用模型。</p><button class="primary" id="import-sample">${imported?'再次导入示例 PDF':'导入示例 PDF'}</button></div>${imported?`<div class="file-card"><span class="status">示例资料已归档</span><strong>${escapeHtml(renamedTitle)}</strong><p>${sampleSummary}</p><button class="secondary" id="view-sample">查看资料详情 ↗</button></div>`:''}`;
 $('#import-sample').onclick=()=>{ensureFile();complete(0,'✓ 示例已归档。原件与预置概览放在同一份资料中。');showHome();};
 if($('#view-sample'))$('#view-sample').onclick=showDetail;
}
function showSearch(){
 ensureFile();$('#workspace-content').innerHTML='<label class="search-label" for="practice-search">搜索标题、正文和标签</label><input id="practice-search" autocomplete="off" placeholder="科学月刊 6月"><p id="search-count"></p><div id="search-results"></div>';
 const rows=[{id:'june',title:renamedTitle,text:sampleSummary},{id:'may',title:'科学月刊 · 2026年5月',text:'五月虚构示例，主题为气候与海洋。'},{id:'reading',title:'6月读书笔记',text:'虚构阅读计划与个人笔记。'}];
 function search(){const query=$('#practice-search').value;const keywords=query.toLocaleLowerCase().trim().split(/\s+/).filter(Boolean);const results=rows.filter(row=>keywords.every(word=>(row.title+' '+row.text).toLocaleLowerCase().includes(word)));$('#search-count').textContent=`${results.length} 份示例资料 · 全部关键词都要匹配`;$('#search-results').innerHTML=results.length?results.map(row=>`<button class="result" data-result="${row.id}"><strong>${escapeHtml(row.title)}</strong><p>${escapeHtml(row.text)}</p></button>`).join(''):'<p class="small">没有同时包含全部关键词的资料，试试调整搜索词。</p>';$('#search-results').querySelectorAll('[data-result]').forEach(button=>button.onclick=()=>{if(button.dataset.result==='june')showDetail();else $('#feedback').textContent='这份资料是用于对照的虚构示例。'});if(new Set(keywords).size>=2&&results.length===1&&results[0].id==='june')complete(1,'✓ 已用组合关键词找到六月月刊。调换两个词的顺序，结果仍然相同。');}
 $('#practice-search').oninput=search;search();$('#practice-search').focus();
}
function showDetail(){
 ensureFile();$('#workspace-content').innerHTML=`<button id="practice-title" class="title-button" title="点击修改标题">${escapeHtml(renamedTitle)} <span aria-hidden="true">✎</span></button><p class="small">科学与技术 · 已整理 · 虚构示例</p><div><span class="tag">月球探索</span><span class="tag">6月</span><span class="tag">前部概览</span></div><div class="row"><button class="secondary" id="practice-open-pdf">浏览器打开 PDF ↗</button><button class="secondary" id="practice-default">默认程序打开</button></div><div class="preview-box"><h4>资料摘要</h4><p>【PDF 前 5 页概览】${sampleSummary}</p></div><p class="small">示例原文件：练习月刊_2026年6月.pdf</p>`;
 $('#practice-title').onclick=editTitle;$('#practice-open-pdf').onclick=()=>{if(!pdfUrl)pdfUrl=URL.createObjectURL(new Blob([makePdf()],{type:'application/pdf'}));window.open(pdfUrl,'_blank','noopener');complete(3,'✓ 示例 PDF 已在新标签页打开。关掉它即可继续练习。');};$('#practice-default').onclick=()=>{$('#feedback').textContent='真实程序会调用系统默认 PDF 应用。教程只演示入口；请点击「浏览器打开 PDF」完成练习。';};
}
function editTitle(){
 const parent=$('#practice-title').parentElement;const form=document.createElement('form');form.id='practice-title-form';form.innerHTML=`<label class="search-label" for="practice-title-input">修改示例标题</label><input id="practice-title-input" maxlength="300" required value="${escapeHtml(renamedTitle)}"><div class="row"><button class="primary" type="submit">保存标题</button><button class="secondary" type="button" id="practice-title-cancel">取消</button></div>`;$('#practice-title').replaceWith(form);$('#practice-title-input').focus();$('#practice-title-input').select();const cancel=()=>showDetail();$('#practice-title-cancel').onclick=cancel;$('#practice-title-input').onkeydown=event=>{if(event.key==='Escape'){event.preventDefault();cancel();}};form.onsubmit=event=>{event.preventDefault();const title=$('#practice-title-input').value.trim();if(!title){$('#feedback').textContent='标题不能为空。';return;}const changed=title!==renamedTitle;renamedTitle=title;ensureFile();showDetail();if(changed)complete(2,'✓ 标题已修改。示例摘要和 PDF 内容保持不变。');else $('#feedback').textContent='试试换一个不同的名字，再保存。';};
}
function showSettings(){
 $('#workspace-content').innerHTML=`<div class="settings"><p class="settings-label">模型与设置</p><h3>使用方式</h3><p>桌面窗口与网页模式共用知识库和对话记录，程序记住上次选择。</p><button class="secondary" id="practice-mode">${mode==='browser'?'切到桌面模式':'切到网页模式'}</button><div class="preview-box"><strong>练习提示</strong><p>此处只改变练习界面的标记，不会切换你真实程序的窗口。</p></div></div>`;
 $('#practice-mode').onclick=()=>{mode=mode==='browser'?'desktop':'browser';$('#mode-badge').textContent=mode==='desktop'?'桌面练习':'网页练习';showSettings();complete(4,'✓ 找到切换入口了。真实程序会打开对应界面并记住选择。');};
}
function showBackup(){
 $('#workspace-content').innerHTML='<div class="settings"><p class="settings-label">导出知识库备份</p><h3>一个 ZIP，带上原件。</h3><p>以下是虚构的备份清单预览，本练习没有下载任何文件。</p><div class="tree">知识库备份.zip\n├── archive.sqlite3  数据库\n├── archive.json     资料清单与摘要\n└── files/\n    └── 示例资料编号   PDF 原文件内容</div><p class="small">归档原件可能使用资料编号命名。通过程序下载原文件时，会恢复原文件名。</p></div>';complete(5,'✓ 备份包括原文件。以后可通过「导入知识库备份」合并恢复资料。');
}
function showResult(){
 $('#lesson-title').textContent=done.size===6?'六个练习，都完成了。':'已经掌握 '+done.size+' 个步骤。';$('#instruction').textContent='真实程序中的操作位置与练习一致。现在可以回到知识秘书，处理自己的资料。';$('#hint').textContent='不确定时，可以随时从「模型与设置 → 使用教程」再次打开。';$('#workspace-content').innerHTML=`<div class="welcome"><span class="star">✳</span><h3>${done.size} / 6 项技能已完成</h3><p>归档、组合搜索、标题修改、PDF 阅读、模式切换，以及备份。</p><button class="primary" id="restart-finish">再练习一次</button></div>`;$('#restart-finish').onclick=reset;$('#feedback').textContent='练习数据只存在于本页面，刷新或重置后清空。';$('#next').disabled=true;
}
function reset(){current=0;done=new Set();imported=false;renamedTitle='科学月刊 · 2026年6月';mode='browser';$('#mode-badge').textContent='网页练习';$('#recent-file').hidden=true;go(0);}
function makePdf(){
 const stream='BT /F1 22 Tf 44 730 Td (Stellar Secretary - Tutorial PDF) Tj 0 -40 Td /F1 13 Tf (Fictional science magazine, June 2026.) Tj 0 -28 Td (Topics: Moon exploration, robots and clean energy.) Tj 0 -42 Td (This is a practice file. No private documents are used.) Tj ET';
 const objects=['<< /Type /Catalog /Pages 2 0 R >>','<< /Type /Pages /Kids [3 0 R] /Count 1 >>','<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>','<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',`<< /Length ${stream.length} >>\nstream\n${stream}\nendstream`];let pdf='%PDF-1.4\n';const offsets=[0];objects.forEach((object,index)=>{offsets.push(pdf.length);pdf+=`${index+1} 0 obj\n${object}\nendobj\n`;});const xref=pdf.length;pdf+=`xref\n0 ${objects.length+1}\n0000000000 65535 f \n`+offsets.slice(1).map(offset=>String(offset).padStart(10,'0')+' 00000 n \n').join('')+`trailer\n<< /Size ${objects.length+1} /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF\n`;return pdf;
}
$('#previous').onclick=()=>{if(current>0)go(current-1);};$('#next').onclick=()=>{if(!done.has(current))return;if(current<5)go(current+1);else showResult();};$('#reset').onclick=reset;$('#library').onclick=showSearch;$('#new-note').onclick=showHome;$('#recent-file').onclick=showDetail;$('#settings').onclick=showSettings;$('#backup').onclick=showBackup;
$('#return-app').href=location.protocol==='file:'?'http://127.0.0.1:8768/':location.origin+'/';window.addEventListener('beforeunload',()=>{if(pdfUrl)URL.revokeObjectURL(pdfUrl);});go(0);
