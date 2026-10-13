const ENDPOINT = "http://127.0.0.1:8765/event";
function post(ev) {
  fetch(ENDPOINT, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(ev)}).catch(() => {});
}
async function reportTab(tabId) {
  try {
    const t = await chrome.tabs.get(tabId);
    if (t && t.url && !t.url.startsWith("chrome") && !t.url.startsWith("edge") && !t.url.startsWith("about:")) {
      post({kind: "url", url: t.url, title: t.title || "", tab_id: tabId});
    }
  } catch (e) {}
}
chrome.tabs.onActivated.addListener(({tabId}) => reportTab(tabId));
chrome.tabs.onUpdated.addListener((tabId, info, tab) => {
  if (tab.active && (info.url || info.title)) reportTab(tabId);
});
chrome.windows.onFocusChanged.addListener(async () => {
  const [t] = await chrome.tabs.query({active: true, lastFocusedWindow: true});
  if (t) reportTab(t.id);
});

// nav / browser_error (requires "webNavigation" permission)
if (chrome.webNavigation) {
  chrome.webNavigation.onCommitted.addListener((details) => {
    if (details.frameId !== 0) return;
    const url = details.url || "";
    if (!url || url.startsWith("chrome") || url.startsWith("edge") || url.startsWith("about:")) return;
    post({
      kind: "nav",
      url,
      tab_id: details.tabId,
      transition: details.transitionType || "",
    });
  });
  chrome.webNavigation.onErrorOccurred.addListener((details) => {
    if (details.frameId !== 0) return;
    const url = details.url || "";
    if (!url || url.startsWith("chrome-extension")) return;
    let code = details.error || "ERR_FAILED";
    if (typeof code === "string" && code.indexOf("net::") === 0) code = code.slice(5);
    post({
      kind: "browser_error",
      url,
      error: code,
      tab_id: details.tabId,
      message: details.error || "",
    });
  });
}

chrome.runtime.onMessage.addListener((msg, sender) => {
  if (msg && msg.kind === "url") post({kind: "url", url: msg.url, title: msg.title, tab_id: sender.tab && sender.tab.id});
  if (msg && msg.kind === "form_edit") post({...msg, url: sender.tab ? sender.tab.url : msg.url, tab_id: sender.tab && sender.tab.id});
  if (msg && msg.kind === "browser_error") post({
    kind: "browser_error",
    url: msg.url || (sender.tab && sender.tab.url) || "",
    error: msg.error || msg.code || "ERR_FAILED",
    title: msg.title || "",
    message: msg.message || "",
    tab_id: sender.tab && sender.tab.id,
  });
});
