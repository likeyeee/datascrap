const $ = id => document.getElementById(id);
const KEYS = {server: 'http://localhost:8000', token: '', autoReport: true, autoExtract: true, annotate: true};

chrome.storage.sync.get(KEYS).then(c => {
  $('server').value = c.server || self.SCOUT_PRESET?.server || '';
  $('token').value = c.token || self.SCOUT_PRESET?.token || '';
  for (const k of ['autoReport', 'autoExtract', 'annotate']) $(k).checked = c[k];
});

$('save').onclick = async () => {
  await chrome.storage.sync.set({
    server: $('server').value.trim().replace(/\/$/, ''),
    token: $('token').value.trim(),
    autoReport: $('autoReport').checked,
    autoExtract: $('autoExtract').checked,
    annotate: $('annotate').checked,
  });
  const r = await chrome.runtime.sendMessage({type: 'ping'});
  const msg = $('msg');
  msg.className = r.error ? 'err' : 'ok';
  msg.textContent = r.error ? '连接失败：' + r.error : `连接成功，当前账号：${r.display_name || r.username}`;
  if (!r.error) chrome.storage.sync.set({user: r.display_name || r.username});
};
