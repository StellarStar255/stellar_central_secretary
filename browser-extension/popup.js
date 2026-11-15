/* Only the tab explicitly selected by the user is read. */
const endpoint = 'http://127.0.0.1:8768';
const button = document.getElementById('capture');
const statusLabel = document.getElementById('status');
const exportButton = document.getElementById('export');
const viewButton = document.getElementById('view');
let captured;
let busy = false;
function show(message) { statusLabel.textContent = message; }

async function connection() {
  let response;
  try {
    response = await fetch(endpoint + '/api/status', {signal: AbortSignal.timeout(2500)});
  } catch { return null; }
  if (!response.ok) throw Error('本机服务返回 ' + response.status + '，请检查知识秘书是否正常运行。');
  const status = await response.json();
  if (status.application !== 'stellar-central-secretary' || !status.token)
    throw Error('8768 端口不是可用的知识秘书服务。');
  return status;
}

async function exportCapture() {
  if (!captured || busy) return;
  const url = URL.createObjectURL(new Blob([JSON.stringify(captured, null, 2)], {type: 'application/json'}));
  try {
    await chrome.downloads.download({url, filename: (captured.title || '网页采集').replace(/[\\/:*?"<>|]/g, '_').slice(0, 80) + '.knowledge.json', saveAs: true});
    show('已提交文件下载。下载完成后，将 .knowledge.json 文件拖入知识秘书。');
  } catch (error) { show('文件未下载：' + error.message + '。可以再次点击保存。'); }
  finally { setTimeout(() => URL.revokeObjectURL(url), 60000); }
}
exportButton.onclick = exportCapture;

async function capturePage() {
  let linkOnly = false;
  if (busy) return;
  busy = true;
  button.disabled = true;
  button.textContent = '正在读取页面…';
  exportButton.hidden = true;
  viewButton.hidden = true;
  captured = null;
  show('正在读取当前标签页，请暂时保持此窗口打开。');
  try {
    const [tab] = await chrome.tabs.query({active: true, currentWindow: true});
    if (!tab?.id || !/^https?:\/\//i.test(tab.url || ''))
      throw Error('请在普通网页中使用采集，浏览器设置页和新标签页无法读取。');
    await chrome.scripting.executeScript({target: {tabId: tab.id}, files: ['extract.js']});
    const [result] = await chrome.scripting.executeScript({target: {tabId: tab.id}, func: () => {
      const selected = window.getSelection()?.toString().trim();
      if (!selected && /(^|\.)excalidraw\.com$/.test(location.hostname))
        return {bookmark_reason: '画布页面'};
      const capture = extractKnowledgeConversation();
      const chatSite = /(^|\.)(chatgpt\.com|claude\.ai|gemini\.google\.com)$/.test(location.hostname);
      if (!selected && chatSite && !capture.messages.length) {
        if (capture.diagnostics.denied || (location.hostname === 'claude.ai' && location.pathname === '/restricted'))
          return {bookmark_reason: '对话访问受限'};
        if (capture.diagnostics.login) return {bookmark_reason: '尚未登录'};
      }
      const assistant = location.hostname.endsWith('claude.ai') ? 'Claude' : location.hostname === 'gemini.google.com' ? 'Gemini' : 'ChatGPT';
      const text = selected || (capture.messages.length ? capture.messages.map(m => (m.role === 'user' ? '用户' : assistant) + '：\n' + m.text).join('\n\n') : capture.text);
      return {title: document.title, url: location.href, text, captured_at: new Date().toISOString()};
    }});
    if (!result?.result || result.error) throw Error('页面读取未完成，请刷新目标页面后重试。');
    linkOnly = Boolean(result.result.bookmark_reason || !result.result.text?.trim());
    captured = linkOnly ? {title: tab.title || tab.url, url: tab.url, text: '', archive_only: true} : result.result;
    captured.browser_extension = true;
    captured.extension_event_id = crypto.randomUUID().replaceAll('-', '');
    button.textContent = '正在连接知识秘书…';
    show(linkOnly ? '正在收藏当前网址…' : '已读取 ' + captured.text.length + ' 字符，正在连接本机知识秘书…');
    const status = await connection();
    if (!status) {
      show('未连接本机知识秘书（127.0.0.1:8768）。请启动应用后重试，或先保存采集文件。');
      exportButton.hidden = false;
      return;
    }
    button.textContent = '正在归档…';
    show('正在保存到知识秘书，请保持此窗口打开。');
    let saved;
    try {
      saved = await fetch(endpoint + '/api/ingest', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Knowledge-Token': status.token}, body: JSON.stringify(captured), signal: AbortSignal.timeout(30000)});
    } catch {
      throw Error('归档请求未收到确认，资料可能已保存。请先在知识库检查，避免重复提交；也可保存采集文件备用。');
    }
    const record = await saved.json();
    if (!saved.ok) throw Error(record.error || ('归档服务返回 ' + saved.status));
    const item = record.item;
    if (!item || !/^[a-f0-9]{32}$/.test(item.id || '')) throw Error('服务未返回有效归档记录，请在知识库核对。');
    viewButton.onclick = () => chrome.tabs.create({url: endpoint + '/?item=' + encodeURIComponent(item.id)});
    viewButton.hidden = false;
    if (!linkOnly && (item.text || '').trim() !== captured.text.trim())
      throw Error('此网址已有归档，但本次正文尚未写入，旧内容已保留。请点击查看归档核对，或保存本次采集文件备用。');
    show((linkOnly ? (record.created ? '已收藏链接：' : '链接已存在：') : record.created ? '已归档：' : record.updated ? '已补充正文：' : '已找到已有归档，本次未新增：') + item.title + (linkOnly ? '。仅收藏网址，未采集正文或绘图。' : '（' + item.text.length + ' 字符）。') + (record.chat_sync_error || (record.chat_synced ? '已同步归档卡片到当前聊天，也可点击下方查看。' : '可点击下方查看归档；聊天同步需要新版知识秘书。')));
  } catch (error) {
    show('采集未完成：' + error.message);
    exportButton.hidden = !captured;
  } finally {
    busy = false;
    button.disabled = false;
    button.textContent = '一键归档当前页面';
  }
}
button.onclick = capturePage;

connection().then(status => {
  if (!busy && !captured) show(status ? '已连接本机知识秘书，可以直接归档。' : '未连接本机知识秘书。请启动应用，或采集后保存为文件。');
}).catch(error => { if (!busy && !captured) show(error.message); });
