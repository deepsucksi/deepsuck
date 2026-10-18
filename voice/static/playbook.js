// DeepSuck 语音演示「参考话术」面板：给扮演骗子的测试者当提词用。
// 独立于 voice.js：只读取 #scenario 的值并监听它的 change；下拉由 voice.js 异步填充，选项晚到时用 MutationObserver 补渲染。
// 数据：主来源是同源 /static/scam_playbooks.json（语料负责人放在 voice/static/），失败才跨域取主站
// https://deepsuck.si/assets/core/scam_playbooks.json 作备用；都拿不到就显示一行说明，不影响通话。只读这一份文件。
// 结构：{"version":1,"stageNames?":{"<场景 id>":{"<stage id>":"中文名"}},"scenarios":{"<场景 id>":{"title","steps":[{"stage?","goal","lines":[],"source"}]}}}
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

  // stageNames 按场景分组：{"<场景 id>":{"<stage id>":"中文名"}}；任何一层缺失、不是对象，或值不是非空字符串时忽略
  const isObj = (o) => !!o && typeof o === "object" && !Array.isArray(o);
  const own = (o, k) => Object.prototype.hasOwnProperty.call(o, k);
  function stageName(scenarioId, stage) {
    const all = data && data.stageNames;
    if (!isObj(all) || !own(all, scenarioId) || !isObj(all[scenarioId]) || !own(all[scenarioId], stage)) return "";
    const v = all[scenarioId][stage];
    return typeof v === "string" ? v.trim() : "";
  }

  // 话术里的 {机构}、{工号} 等占位槽：拆成等宽小字，提示测试者自己填
  const SLOT = /\{[^{}\n]{1,16}\}/g;
  function lineEl(text) {
    const li = el("li");
    let last = 0;
    for (const m of text.matchAll(SLOT)) {
      if (m.index > last) li.append(document.createTextNode(text.slice(last, m.index)));
      li.append(el("span", "pb-slot", m[0].slice(1, -1)));
      last = m.index + m[0].length;
    }
    if (last < text.length) li.append(document.createTextNode(text.slice(last)));
    return li;
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
    steps.scrollTop = 0;
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
      // stage 是分类器阶段 id（如 refund 的 hook/problem/tool/harvest/cashout）。顶层 stageNames 有中文名时显示中文名，
      // id 用等宽小字附在旁边便于和看板对照；没有中文名就只显示 id
      if (typeof s.stage === "string" && s.stage) {
        const name = stageName(id, s.stage);
        if (name) {
          const tag = el("span", "pb-stage", name);
          tag.append(el("span", "pb-sid", s.stage));
          head.append(tag);
        } else head.append(el("span", "pb-stage pb-sid-only", s.stage));
      }
      li.append(head);
      const goal = el("h3", "pb-goal");
      goal.append(el("span", "pb-k", "目标"), document.createTextNode(String(s.goal || "—")));
      li.append(goal);
      const lines = Array.isArray(s.lines) ? s.lines.filter((x) => typeof x === "string" && x.trim()) : [];
      if (lines.length) {
        const ul = el("ul", "pb-lines");
        lines.forEach((x) => ul.append(lineEl(x)));
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
