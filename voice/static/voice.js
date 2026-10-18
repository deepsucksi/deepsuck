// DeepSuck 语音演示前端：原生 WebRTC 连 Pipecat SmallWebRTC（/api/offer），数据通道收看板消息。
(() => {
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  let pc = null, dc = null, pcId = null, mic = null, interimEl = null, iceServers = [], traceId = null, traceOn = true;

  function setStatus(cls, text) { $("dot").className = "dot " + cls; $("st").textContent = text; }
  function err(t) { $("err").textContent = t || ""; }

  async function loadConfig() {
    try {
      const c = await (await fetch("/api/config", { cache: "no-store" })).json();
      iceServers = c.iceServers || [];
      traceOn = !c.trace || c.trace.enabled !== false;
      if (!traceOn) { $("consentRow").hidden = true; $("keepNote").hidden = true; }
      if (c.limits) $("limits").textContent = `公开体验限制：每局最长 ${c.limits.maxMinutes} 分钟 / ${c.limits.maxTurns} 轮，同时最多 ${c.limits.maxSessions} 路通话` +
        (c.budget && c.budget.capCny ? `；今日额度已用 ${c.budget.usedPct}%` : "") + "。";
      if (c.budget && c.budget.exhausted) { setStatus("bad", "今日语音体验额度已用完"); $("call").disabled = true; return; }
      $("persona").innerHTML = c.personas.map((p) => `<option value="${p.id}">${esc(p.name)}（${esc(p.voice || "")}）</option>`).join("");
      $("scenario").innerHTML = c.scenarios.map((s) => `<option value="${s.id}">${esc(s.title)}</option>`).join("");
      if (c.keyConfigured) setStatus("ok", `就绪 · ${c.engine === "rule" ? "规则引擎" : c.models.llm} · ${c.models.asr} · ${c.models.tts}`);
      else { setStatus("bad", "未配置 DASHSCOPE_API_KEY"); $("call").disabled = true; err("服务端没有 DASHSCOPE_API_KEY：复制 voice/.env.example 为 voice/.env 并填入后重启。"); }
    } catch (e) { setStatus("bad", "无法连接服务"); }
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
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || `HTTP ${r.status}`);
    const ans = await r.json();
    pcId = ans.pc_id;
    if (ans.trace_id) showTrace(ans.trace_id);
    await pc.setRemoteDescription({ sdp: ans.sdp, type: ans.type });
  }

  async function start() {
    err(""); $("call").disabled = true;
    try {
      mic = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true } });
      pc = new RTCPeerConnection({ iceServers });
      pc.addTransceiver(mic.getAudioTracks()[0], { direction: "sendrecv" });
      pc.addTransceiver("video", { direction: "sendrecv" }); // SmallWebRTC 期望有视频收发器；不发送画面
      pc.ontrack = (e) => { if (e.track.kind === "audio") $("audio").srcObject = new MediaStream([e.track]); };
      pc.onconnectionstatechange = () => {
        if (pc && pc.connectionState === "connected") setStatus("live", "通话中");
        if (pc && ["failed", "closed", "disconnected"].includes(pc.connectionState)) stop();
      };
      dc = pc.createDataChannel("chat", { ordered: true });
      dc.onmessage = (e) => {
        let m; try { m = JSON.parse(e.data); } catch { return; }
        if (m.type === "deepsuck") onData(m.data);
        else if (m.type === "signalling" && m.message && m.message.type === "renegotiate") negotiate({}).catch(() => {});
      };
      $("log").innerHTML = "";
      hideTrace();
      await negotiate({ persona: $("persona").value, scenario: $("scenario").value, consent: consentOn() });
      $("hang").hidden = false;
    } catch (e) {
      err("无法开始通话：" + e.message); stop();
    }
  }

  function stop() {
    if (dc) try { dc.close(); } catch {}
    if (pc) try { pc.close(); } catch {}
    if (mic) mic.getTracks().forEach((t) => t.stop());
    pc = dc = mic = null; pcId = null;
    $("hang").hidden = true; $("call").disabled = false;
    if ($("dot").classList.contains("live")) setStatus("ok", "已挂断");
  }

  // ---- 通话追踪：同意、编号、反馈 ----
  function consentOn() { return traceOn && $("consent").checked; }
  function showTrace(id) {
    traceId = id; $("traceId").textContent = id; $("trace").hidden = false;
    $("fb").hidden = true; $("fbDone").hidden = true; $("fbOpen").hidden = false;
  }
  function hideTrace() { traceId = null; $("trace").hidden = true; $("fb").hidden = true; $("fbDone").hidden = true; }
  $("consent").onchange = () => { if (!$("consent").checked && !pc) hideTrace(); };
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
  $("fb").onsubmit = async (e) => {
    e.preventDefault();
    if (!traceId) return;
    const turn = $("fbTurn").value.trim();
    try {
      const r = await fetch(`/api/feedback/${encodeURIComponent(traceId)}`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ note: $("fbNote").value.trim(), turn: turn === "" ? null : Number(turn) }),
      });
      $("fbDone").textContent = r.ok ? `已记录，谢谢。通话编号 ${traceId}` : "提交失败，请稍后再试。";
    } catch { $("fbDone").textContent = "提交失败，请稍后再试。"; }
    $("fb").hidden = true; $("fbDone").hidden = false; $("fbNote").value = ""; $("fbTurn").value = "";
  };

  $("call").onclick = start;
  $("hang").onclick = stop;
  window.__deepsuckVoice = { onData }; // 便于本地截图/调试
  loadConfig();
})();
