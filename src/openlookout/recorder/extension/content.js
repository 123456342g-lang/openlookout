// 只记录"哪个字段被填了、是打字还是粘贴"，不记录填了什么。
(() => {
  const SKIP = new Set(["password", "hidden"]);
  const lastSent = new WeakMap();
  function labelOf(el) {
    if (el.labels && el.labels.length) return el.labels[0].innerText.trim();
    const a = el.getAttribute("aria-label") || el.getAttribute("placeholder") || el.getAttribute("title");
    if (a) return a.trim();
    const lb = el.getAttribute("aria-labelledby");
    if (lb) { const n = document.getElementById(lb); if (n) return n.innerText.trim(); }
    const prev = el.closest("td, div, li, p");
    if (prev && prev.previousElementSibling) return prev.previousElementSibling.innerText.trim().slice(0, 40);
    return el.name || el.id || el.tagName.toLowerCase();
  }
  function isField(el) {
    if (!el || !el.tagName) return false;
    if (el.tagName === "TEXTAREA" || el.tagName === "SELECT" || el.isContentEditable) return true;
    return el.tagName === "INPUT" && !SKIP.has((el.type || "").toLowerCase());
  }
  function send(el, via) {
    const now = Date.now(), prev = lastSent.get(el);
    if (prev && prev.via === via && now - prev.t < 3000) return; // 同一字段连续打字只记一次
    lastSent.set(el, {via, t: now});
    chrome.runtime.sendMessage({kind: "form_edit", field_label: labelOf(el).slice(0, 60), via, url: location.href});
  }
  const reportUrl = () => { if (window === window.top && document.visibilityState === "visible") chrome.runtime.sendMessage({kind: "url", url: location.href, title: document.title}); };
  reportUrl();
  document.addEventListener("visibilitychange", reportUrl);
  document.addEventListener("paste", e => { if (isField(e.target)) send(e.target, "paste"); }, true);
  document.addEventListener("input", e => {
    if (!isField(e.target) || !e.isTrusted) return;
    if (e.inputType && e.inputType.startsWith("insertFromPaste")) return; // 已由 paste 处理
    send(e.target, "type");
  }, true);
  document.addEventListener("change", e => { if (e.target && e.target.tagName === "SELECT") send(e.target, "select"); }, true);
})();
