// DeepSuck 语音演示前端：原生 WebRTC 连语音服务（/api/offer），数据通道收看板消息。
(() => {
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  let pc = null, dc = null, pcId = null, mic = null, interimEl = null, iceServers = [], traceId = null, traceKey = "", traceOn = true;
  // 连接状态（GitHub #3）：connecting → connected / failed。超时没接通就给出原因和建议，并上报（同意时写进同一编号）
  const CONNECT_TIMEOUT_MS = 20000;
  let turnOn = false, relayOffered = false, connTimer = null, connState = "idle", tStart = 0, reported = false;

  function setStatus(cls, text) { $("dot").className = "dot " + cls; $("st").textContent = text; }
  function err(t) { $("err").textContent = t || ""; }

  async function loadConfig() {
    try {
      const c = await (await fetch("/api/config", { cache: "no-store" })).json();
      iceServers = c.iceServers || [];
      turnOn = !!c.turn;
      traceOn = !c.trace || c.trace.enabled !== false;
      applyTraceCopy(c.trace);
      if (c.limits) $("limits").textContent = `公开体验限制：每局最长 ${c.limits.maxMinutes} 分钟 / ${c.limits.maxTurns} 轮，同时最多 ${c.limits.maxSessions} 路通话` +
        (c.budget && c.budget.capCny ? `；今日额度已用 ${c.budget.usedPct}%` : "") + "。";
      if (c.budget && c.budget.exhausted) { setStatus("bad", "今日语音体验额度已用完"); $("call").disabled = true; return; }
      renderCast(c.personas, c.aliases || {});
      $("scenario").innerHTML = c.scenarios.map((s) => `<option value="${s.id}">${esc(s.title)}</option>`).join("");
      // 页面不显示模型、厂商、技术栈名；服务端配置问题见 voice/README.md「需要什么」
      if (c.keyConfigured) setStatus("ok", "就绪");
      else { setStatus("bad", "语音服务暂不可用"); $("call").disabled = true; err("语音服务暂时无法通话，请稍后再来。"); }
    } catch (e) { setStatus("bad", "无法连接服务"); }
  }

  // 人设：与首页同样的序号、身份和头像（/api/config 的 no / role / photo）；?persona=<id> 直接选中对应人设
  let persona = "";
  function pickPersona(id) {
    persona = id;
    document.querySelectorAll(".cast-member").forEach((b) => {
      const on = b.dataset.persona === id;
      b.setAttribute("aria-checked", String(on));
      b.tabIndex = on ? 0 : -1;
    });
  }
  function renderCast(list, retired) {
    const box = $("persona");
    box.querySelectorAll(".cast-member").forEach((b) => b.remove());
    list.forEach((p) => {
      const b = document.createElement("button");
      b.type = "button"; b.className = "cast-member"; b.dataset.persona = p.id;
      b.setAttribute("role", "radio"); b.setAttribute("aria-checked", "false");
      b.setAttribute("aria-label", `${p.no} ${p.role} ${p.name}`);
      b.innerHTML = `<span class="cast-photo"><img src="${esc(p.photo)}" alt="" width="400" height="500" loading="lazy" decoding="async"></span>` +
        `<span class="cast-label"><span class="cast-num">${esc(p.no)}</span><b>${esc(p.role)}</b></span><span class="cast-name">${esc(p.name)}</span>`;
      b.addEventListener("click", () => pickPersona(p.id));
      box.appendChild(b);
    });
    box.onkeydown = (e) => {
      const i = list.findIndex((p) => p.id === persona), d = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }[e.key];
      if (!d || i < 0) return;
      e.preventDefault();
      const next = list[(i + d + list.length) % list.length].id;
      pickPersona(next);
      box.querySelector(`[data-persona="${next}"]`).focus();
    };
    let want = new URLSearchParams(location.search).get("persona") || "";
    if (Object.prototype.hasOwnProperty.call(retired, want)) want = retired[want];
    pickPersona(list.some((p) => p.id === want) ? want : (list[0] && list[0].id) || "");
  }

  function addMsg(role, text, extra) {
    const log = $("log");
    if (log.querySelector(".empty")) log.innerHTML = "";
    const el = document.createElement("div");
    el.className = "msg " + role;
    el.innerHTML = esc(text) + (extra || "");
    if (role !== "interim" && interimEl) { interimEl.remove(); interimEl = null; }
    log.appendChild(el);
    log.scrollTop = log.scrollHeight;
    return el;
  }

  function renderState(s) {
    $("sTurns").textContent = s.stats.scammerMessages;
    $("sMin").textContent = (s.stats.estimatedScammerSeconds / 60).toFixed(1);
    $("sIntel").textContent = s.stats.intelCount;
    $("sRisk").textContent = s.stats.riskScore;
    $("intel").innerHTML = s.intel.length ? s.intel.map((i) => {
      const b = i.blocklist, hit = b && b.status === "hit";
      const bl = b ? `<span class="bl ${hit ? "hit" : ""}">${hit ? "黑名单命中：" + esc((b.sources || []).join("、")) : b.status === "clean" ? "黑名单未命中" : "黑名单不可用"}</span>` : "";
      return `<div class="item ${hit ? "hit" : ""}"><span>${esc(i.label)} <code>${esc(i.masked)}</code></span>${bl}</div>`;
    }).join("") : '<div class="empty">尚未抽取到情报</div>';
    $("tactics").innerHTML = s.tactics.length ? s.tactics.map((t) => `<span class="chip">${esc(t.label)} ×${t.count}</span>`).join("") : "—";
    $("intent").innerHTML = `<span class="chip intent">${esc(s.intent)}</span>`;
  }

  function onData(m) {
    if (m.type === "interim") {
      if (!interimEl) interimEl = addMsg("interim", m.text);
      else interimEl.textContent = m.text;
    } else if (m.type === "scammer") {
      const chips = (m.tactics || []).map((t) => `<span class="chip">${esc(t.label)}</span>`).join("") +
        (m.newIntel || []).map((i) => `<span class="chip">新情报：${esc(i.label)} ${esc(i.masked)}</span>`).join("");
      addMsg("scammer", m.text, chips ? `<div class="meta">${chips}</div>` : "");
    } else if (m.type === "bot") {
      addMsg("bot", m.text, `<div class="meta"><span class="chip intent">${esc(m.intent)}</span></div>`);
    } else if (m.type === "state") renderState(m);
    else if (m.type === "limit") { addMsg("interim", m.text + "，通话即将结束"); setStatus("ok", m.text); }
  }

  async function negotiate(extra) {
    const offer = await pc.createOffer();
    await pc.setLocalDescription(offer);
    // 不做 trickle：等 ICE 收集完（本机/局域网很快）
    await new Promise((res) => {
      if (pc.iceGatheringState === "complete") return res();
      const t = setTimeout(res, 2500);
      pc.addEventListener("icegatheringstatechange", () => { if (pc.iceGatheringState === "complete") { clearTimeout(t); res(); } });
    });
    const r = await fetch("/api/offer", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sdp: pc.localDescription.sdp, type: pc.localDescription.type, pc_id: pcId, ...extra }),
    });
    if (r.status === 503) throw new Error("语音服务暂不可用，请稍后再试"); // 503 的服务端说明面向部署者，不上页面
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || `HTTP ${r.status}`);
    const ans = await r.json();
    pcId = ans.pc_id;
    if (ans.trace_id) showTrace(ans.trace_id, ans.feedback_key);
    await pc.setRemoteDescription({ sdp: ans.sdp, type: ans.type });
  }

  // 开始通话前现取 ICE 服务器（含临时 TURN 凭据）；取不到就用页面配置里的（只有 STUN 或为空）
  async function freshIce() {
    if (!turnOn) return iceServers;
    try {
      const r = await fetch("/api/ice", { method: "POST", cache: "no-store", headers: { "Content-Type": "application/json" }, body: "{}" });
      if (r.ok) { const j = await r.json(); if (Array.isArray(j.iceServers)) return j.iceServers; }
    } catch {}
    return iceServers;
  }

  // 只取候选类型/协议的计数和最终选中的路径，不取 IP、端口
  async function iceSummary() {
    const out = { ice: pc ? pc.iceConnectionState : "", conn: pc ? pc.connectionState : "", gather: pc ? pc.iceGatheringState : "",
      relayOffered, elapsedMs: Date.now() - tStart, online: navigator.onLine, browser: browserName() };
    if (!pc) return out;
    try {
      const st = await pc.getStats(), local = {}, remote = {}, byId = {};
      let selected = null;
      st.forEach((r) => {
        byId[r.id] = r;
        if (r.type === "local-candidate" || r.type === "remote-candidate") {
          const k = `${r.candidateType}/${r.relayProtocol || r.protocol}`, m = r.type === "local-candidate" ? local : remote;
          m[k] = (m[k] || 0) + 1;
        }
        if (r.type === "transport" && r.selectedCandidatePairId) selected = r.selectedCandidatePairId;
      });
      if (!selected) st.forEach((r) => { if (r.type === "candidate-pair" && r.nominated && r.state === "succeeded") selected = r.id; });
      const fmt = (m) => Object.entries(m).map(([k, v]) => `${k}:${v}`).join(" ");
      out.local = fmt(local); out.remote = fmt(remote);
      const pair = selected && byId[selected], lc = pair && byId[pair.localCandidateId];
      if (lc) out.path = `${lc.candidateType}/${lc.relayProtocol || lc.protocol}`;
    } catch {}
    return out;
  }
  function browserName() {
    const u = navigator.userAgent;
    const m = u.match(/(Edg|OPR|Firefox|Chrome|Version)\/(\d+)/);
    const os = /Windows/.test(u) ? "Windows" : /Android/.test(u) ? "Android" : /iPhone|iPad/.test(u) ? "iOS" : /Mac/.test(u) ? "macOS" : /Linux/.test(u) ? "Linux" : "";
    return m ? `${m[1] === "Version" ? "Safari" : m[1]} ${m[2]} ${os}`.trim() : os;
  }
  async function report(stage, reason) {
    if (reported && stage !== "connected") return;
    if (stage !== "connected") reported = true;
    const detail = await iceSummary();
    try {
      await fetch("/api/client-report", { method: "POST", keepalive: true, headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ trace_id: traceId, stage, reason: reason || "", detail }) });
    } catch {}
  }

  function setConn(state) {
    connState = state;
    if (state === "connecting") setStatus("wait", "正在连接…");
    else if (state === "connected") setStatus("live", "已接通 · 通话中");
    else if (state === "failed") setStatus("bad", "连接失败");
  }
  function showNetHelp(why) {
    $("netWhy").textContent = why;
    $("netId").hidden = !traceId; $("netIdCode").textContent = traceId || "";
    $("netHelp").hidden = false;
  }
  async function fail(stage, why) {
    if (connState === "failed" || connState === "idle") return;
    clearTimeout(connTimer); connTimer = null;
    setConn("failed");
    showNetHelp(why);
    await report(stage, why); // 先取连接统计再关连接
    stop(true);
  }
  async function onConnected() {
    if (connState === "connected") return;
    clearTimeout(connTimer); connTimer = null;
    setConn("connected");
    report("connected");
  }

  async function start() {
    err(""); $("call").disabled = true; $("netHelp").hidden = true;
    reported = false; tStart = Date.now();
    try {
      mic = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true } });
    } catch (e) {
      err("拿不到麦克风：请在浏览器地址栏允许麦克风后再试。"); $("call").disabled = false; return;
    }
    try {
      setConn("connecting");
      const servers = await freshIce();
      relayOffered = servers.some((s) => [].concat(s.urls || []).some((u) => /^turns?:/.test(u)));
      pc = new RTCPeerConnection({ iceServers: servers });
      pc.addTransceiver(mic.getAudioTracks()[0], { direction: "sendrecv" });
      pc.addTransceiver("video", { direction: "sendrecv" }); // 服务端期望有视频收发器；不发送画面
      pc.ontrack = (e) => { if (e.track.kind === "audio") $("audio").srcObject = new MediaStream([e.track]); };
      pc.onconnectionstatechange = () => {
        if (!pc) return;
        const s = pc.connectionState;
        if (s === "connected") onConnected();
        else if (s === "failed" && connState === "connecting") fail("ice_failed", failWhy());
        else if (["failed", "closed", "disconnected"].includes(s)) stop();
      };
      dc = pc.createDataChannel("chat", { ordered: true });
      dc.onmessage = (e) => {
        let m; try { m = JSON.parse(e.data); } catch { return; }
        if (m.type === "deepsuck") onData(m.data);
        else if (m.type === "signalling" && m.message && m.message.type === "renegotiate") negotiate({}).catch(() => {});
      };
      $("log").innerHTML = "";
      hideTrace();
      try {
        await negotiate({ persona, scenario: $("scenario").value, consent: consentOn() });
      } catch (e) {
        err("无法开始通话：" + e.message); report("offer_failed", String(e.message || "").slice(0, 120)); setConn("failed"); stop(true); return;
      }
      $("hang").hidden = false;
      if (pc && pc.connectionState === "connected") onConnected();
      else connTimer = setTimeout(() => fail("ice_timeout", failWhy()), CONNECT_TIMEOUT_MS);
    } catch (e) {
      err("无法开始通话：" + e.message); setConn("failed"); stop(true);
    }
  }
  function failWhy() {
    return relayOffered ? "多半是当前网络或代理拦截了实时音频（UDP），经 443 端口的中继也没接通"
      : "多半是当前网络或代理拦截了实时音频（UDP）";
  }

  function stop(keepStatus) {
    clearTimeout(connTimer); connTimer = null;
    if (dc) try { dc.close(); } catch {}
    if (pc) try { pc.close(); } catch {}
    if (mic) mic.getTracks().forEach((t) => t.stop());
    pc = dc = mic = null; pcId = null;
    $("hang").hidden = true; $("call").disabled = false;
    if (keepStatus !== true && (connState === "connected" || connState === "connecting")) setStatus("ok", "已挂断");
    if (connState !== "failed") connState = "idle";
  }

  // ---- 通话追踪：同意、编号、反馈 ----
  // 勾选才存录音和脱敏文字，不勾选只记用量（#96）；保留天数取服务端配置（页面里写的是默认 30 天）
  const NOTE_TAIL = "仅供防诈研究与教育，请勿用于联系任何真实的人。";
  function applyTraceCopy(t) {
    if (!traceOn) {
      $("consentRow").hidden = true;
      $("keepNote").textContent = "本演示不保存通话内容；" + NOTE_TAIL;
      return;
    }
    const days = (t && t.days) || 30, audioDays = (t && t.audioDays) || days, audioOn = !t || t.audio !== false;
    if (!audioOn) {
      $("consentRow").hidden = true;
      $("consentText").textContent = `允许用本次对话改进 DeepSuck（保存脱敏文字，${days} 天后删除）`;
      $("keepNote").textContent = `勾选同意时保存脱敏文字 ${days} 天用于改进，不保存录音，不勾选只记用量、不存内容；` + NOTE_TAIL;
      return;
    }
    if (days === 30 && audioDays === 30) return; // 与页面默认文案一致
    $("consentText").textContent = days === audioDays ? `允许用本次对话改进 DeepSuck（保存录音和脱敏文字，${days} 天后删除）`
      : `允许用本次对话改进 DeepSuck（保存录音 ${audioDays} 天、脱敏文字 ${days} 天）`;
    $("infoDays").textContent = days === audioDays ? `保存多久：${days} 天后自动删除。`
      : `保存多久：文字记录 ${days} 天、录音 ${audioDays} 天后自动删除。`;
    $("keepNote").textContent = `勾选同意时保存录音和脱敏文字 ${days} 天用于改进，不勾选只记用量、不存内容；` + NOTE_TAIL;
  }
  function consentOn() { return traceOn && $("consent").checked; }
  function showTrace(id, key) {
    traceId = id; traceKey = key || ""; $("traceId").textContent = id; $("trace").hidden = false;
    $("fb").hidden = true; $("fbDone").hidden = true; $("fbOpen").hidden = !traceKey; $("fbOpen").textContent = "这通有问题";
  }
  function hideTrace() { traceId = null; traceKey = ""; $("trace").hidden = true; $("fb").hidden = true; $("fbDone").hidden = true; }
  $("consentMore").onclick = () => {
    const box = $("consentInfo"), open = box.hidden;
    box.hidden = !open; $("consentMore").setAttribute("aria-expanded", String(open));
  };
  $("traceCopy").onclick = async () => {
    if (!traceId) return;
    try { await navigator.clipboard.writeText(traceId); $("traceCopy").textContent = "已复制"; }
    catch { const r = document.createRange(); r.selectNodeContents($("traceId")); const sel = getSelection(); sel.removeAllRanges(); sel.addRange(r); }
    setTimeout(() => { $("traceCopy").textContent = "复制"; }, 1500);
  };
  $("fbOpen").onclick = () => { $("fb").hidden = false; $("fbDone").hidden = true; $("fbNote").focus(); };
  $("fbCancel").onclick = () => { $("fb").hidden = true; };
  // “这通有问题”：只认本页拿到的这通（带 feedback_key）；服务端限频，提交后在原位给出结果
  const FB_MSG = { 429: "提交太频繁，请稍后再试。", 403: "只能标记本页刚打的这通电话。",
    404: "只能标记本页刚打的这通电话。", 410: "这通电话结束太久，已不能标记。" };
  $("fb").onsubmit = async (e) => {
    e.preventDefault();
    if (!traceId || !traceKey) return;
    const turn = $("fbTurn").value.trim(), btn = $("fb").querySelector("button[type=submit]");
    btn.disabled = true;
    let ok = false;
    try {
      const r = await fetch(`/api/feedback/${encodeURIComponent(traceId)}`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ key: traceKey, note: $("fbNote").value.trim(), turn: turn === "" ? null : Number(turn) }),
      });
      ok = r.ok;
      $("fbDone").textContent = r.ok ? `已标记这通有问题，谢谢。排查时会按通话编号 ${traceId} 查看。`
        : (FB_MSG[r.status] || "提交失败，请稍后再试。");
    } catch { $("fbDone").textContent = "提交失败，请稍后再试。"; }
    btn.disabled = false;
    $("fb").hidden = true; $("fbDone").hidden = false;
    if (ok) { $("fbNote").value = ""; $("fbTurn").value = ""; $("fbOpen").textContent = "补充说明"; }
  };

  $("call").onclick = start;
  $("hang").onclick = () => stop();
  window.__deepsuckVoice = { onData, showNetHelp, setConn, showTrace }; // 便于本地截图/调试
  loadConfig();
})();
