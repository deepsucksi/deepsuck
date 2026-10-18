// DeepSuck 语音演示「参考话术」面板：给扮演骗子的测试者当提词用。
// 独立于 voice.js：只读取 #scenario 的值并监听它的 change；下拉由 voice.js 异步填充，选项晚到时用 MutationObserver 补渲染。
// 数据：主来源是同源 /static/scam_playbooks.json（语料负责人放在 voice/static/），失败才跨域取主站
// https://deepsuck.si/assets/core/scam_playbooks.json 作备用；都拿不到就显示一行说明，不影响通话。结构：{"version":1,"scenarios":{"<场景 id>":{"title","steps":[{"stage?","goal","lines":[],"source"}]}}}
// 切换场景只静默重绘，不用 aria-live，避免打断 #st 的通话状态播报。
(() => {
  const SOURCES = ["/static/scam_playbooks.json", "https://deepsuck.si/assets/core/scam_playbooks.json"];
  const TIMEOUT_MS = 6000;
  const $ = (id) => document.getElementById(id);
  const root = $("playbook"), sel = $("scenario");
  if (!root || !sel) return;
  const body = $("pbBody"), toggle = $("pbToggle"), status = $("pbStatus"), steps = $("pbSteps"), cur = $("pbCur"), scTitle = $("pbScenario");
  let data = null, failed = false, shown = null;

  const el = (tag, cls, text) => {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = String(text);
    return n;
  };

  function valid(d) {
    return d && typeof d === "object" && d.version === 1 && d.scenarios && typeof d.scenarios === "object" && !Array.isArray(d.scenarios);
  }

  async function fetchOne(url) {
    const ctl = typeof AbortController === "function" ? new AbortController() : null;
    const t = ctl ? setTimeout(() => ctl.abort(), TIMEOUT_MS) : 0;
    try {
      const r = await fetch(url, { credentials: "omit", signal: ctl ? ctl.signal : undefined });
      if (!r.ok) throw new Error("HTTP " + r.status);
      const d = await r.json();
      if (!valid(d)) throw new Error("unexpected format");
      return d;
    } finally { if (t) clearTimeout(t); }
  }

  async function load() {
    for (const url of SOURCES) {
      try { return await fetchOne(url); } catch (e) { /* 试下一个来源 */ }
    }
    return null;
  }

  function setStatus(text) {
    status.textContent = text || "";
    status.hidden = !text;
  }

  function optionTitle() {
    const o = sel.options[sel.selectedIndex];
    return o ? o.textContent : "";
  }

  function render() {
    const id = sel.value;
    const key = (data ? "d" : failed ? "f" : "l") + ":" + id;
    if (key === shown) return;
    shown = key;
    steps.replaceChildren();
    const sc = data && id && Object.prototype.hasOwnProperty.call(data.scenarios, id) ? data.scenarios[id] : null;
    const title = (sc && sc.title) || optionTitle();
    cur.textContent = title;
    scTitle.textContent = title;
    scTitle.hidden = !title;
    if (!data) { setStatus(failed ? "参考话术暂未加载，不影响通话。" : "参考话术加载中…"); return; }
    if (!id) { setStatus("场景列表加载后显示对应话术。"); return; }
    const list = sc && Array.isArray(sc.steps) ? sc.steps.filter((s) => s && typeof s === "object") : [];
    if (!list.length) { setStatus("这个场景暂时没有参考话术。"); return; }
    setStatus("");
    list.forEach((s, i) => {
      const li = el("li", "pb-step");
      const head = el("div", "pb-step-h");
      head.append(el("span", "pb-n", String(i + 1).padStart(2, "0")));
      // stage 是分类器阶段 id（如 refund 的 hook/problem/tool/harvest/cashout），原样用等宽小字显示，便于和看板对照
      if (typeof s.stage === "string" && s.stage) head.append(el("span", "pb-stage", s.stage));
      li.append(head);
      const goal = el("h3", "pb-goal");
      goal.append(el("span", "pb-k", "目标"), document.createTextNode(String(s.goal || "—")));
      li.append(goal);
      const lines = Array.isArray(s.lines) ? s.lines.filter((x) => typeof x === "string" && x.trim()) : [];
      if (lines.length) {
        const ul = el("ul", "pb-lines");
        lines.forEach((x) => ul.append(el("li", null, x)));
        li.append(ul);
      }
      if (s.source) li.append(el("p", "pb-src", "出处 · " + s.source));
      steps.append(li);
    });
  }

  // 手机端收起/展开；桌面端由 CSS 常显，按钮隐藏
  toggle.addEventListener("click", () => {
    const open = toggle.getAttribute("aria-expanded") !== "true";
    toggle.setAttribute("aria-expanded", String(open));
    root.classList.toggle("is-open", open);
  });

  sel.addEventListener("change", render);
  // voice.js 用 innerHTML 填充选项：观察子节点变化，选项晚到也能渲染
  new MutationObserver(render).observe(sel, { childList: true });
  render();
  load().then((d) => { data = d; failed = !d; shown = null; render(); });
})();
