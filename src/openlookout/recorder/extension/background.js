const ENDPOINT = "http://127.0.0.1:8765/event";
function post(ev) {
  fetch(ENDPOINT, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(ev)}).catch(() => {});
}
async function reportTab(tabId) {
  try {
    const t = await chrome.tabs.get(tabId);
    if (t && t.url && !t.url.startsWith("chrome")) post({kind: "url", url: t.url, title: t.title || ""});
  } catch (e) {}
}
chrome.tabs.onActivated.addListener(({tabId}) => reportTab(tabId));
chrome.tabs.onUpdated.addListener((tabId, info, tab) => { if (tab.active && (info.url || info.title)) reportTab(tabId); });
chrome.windows.onFocusChanged.addListener(async () => {
  const [t] = await chrome.tabs.query({active: true, lastFocusedWindow: true});
  if (t) reportTab(t.id);
});
chrome.runtime.onMessage.addListener((msg, sender) => {
  if (msg && msg.kind === "url") post({kind: "url", url: msg.url, title: msg.title});
  if (msg && msg.kind === "form_edit") post({...msg, url: sender.tab ? sender.tab.url : msg.url});
});
