/*!
 * DeepSuck — server/guard.js：公开部署时的费用护栏（零依赖）
 *  - 每 IP 每分钟 / 每 IP 每天 / 全局每分钟 限流
 *  - 每日全局预算（人民币，按 DashScope 返回的 usage token 记账；无 usage 时按字数估算），超出即拒绝
 *  - 预算账本按 Asia/Shanghai 自然日持久化到 DATA_DIR，重启不清零
 *  - 逐次台账（#174）：DATA_DIR/chat-usage-YYYY-MM-DD.jsonl，每次调用一行，原样保留上游 usage；没 usage 时估算并标 estimated
 * Apache-2.0
 */
'use strict';
var fs = require('fs');
var path = require('path');

/** Asia/Shanghai 的日期 YYYY-MM-DD（不依赖系统时区） */
function cnDay(now) {
  return new Date((now || Date.now()) + 8 * 3600 * 1000).toISOString().slice(0, 10);
}

function createLimiter(opts) {
  var perMin = opts.perIpPerMin, perDay = opts.perIpPerDay, globalPerMin = opts.globalPerMin;
  var mins = {}, days = {}, global = [], day = cnDay(opts.now && opts.now());
  function now() { return opts.now ? opts.now() : Date.now(); }
  return {
    /** 返回 null 表示放行；否则返回拒绝原因 */
    check: function (ip) {
      var t = now(), d = cnDay(t);
      if (d !== day) { days = {}; day = d; }
      global = global.filter(function (x) { return t - x < 60000; });
      if (globalPerMin > 0 && global.length >= globalPerMin) return '全站请求过多，请稍后再试';
      var arr = (mins[ip] || []).filter(function (x) { return t - x < 60000; });
      mins[ip] = arr;
      if (perMin > 0 && arr.length >= perMin) return '请求过于频繁，请稍后再试';
      if (perDay > 0 && (days[ip] || 0) >= perDay) return '今日该 IP 的调用次数已用完，明天再来';
      arr.push(t); global.push(t); days[ip] = (days[ip] || 0) + 1;
      // 防止 mins 无限增长
      if (Object.keys(mins).length > 5000) Object.keys(mins).forEach(function (k) { if (!mins[k].length) delete mins[k]; });
      return null;
    }
  };
}

/**
 * 每日预算账本。prices 单位：元 / 百万 token。
 * reserve(est) 先按上限预占，commit(actual) 时按实际结算，保证并发下也不超过上限。
 */
function createBudget(opts) {
  var capCny = +opts.capCny || 0;
  var prices = opts.prices || { inPerM: 0.8, outPerM: 2 };
  var file = opts.dir ? path.join(opts.dir, 'chat-budget.json') : null;
  // 前六个字段是原有格式（voice/cost.py 读 inTokens/outTokens），#174 只在后面追加计数
  function fresh(d) { return { day: d, spentCny: 0, calls: 0, inTokens: 0, outTokens: 0, refused: 0, reasoningTokens: 0, cachedTokens: 0, estimatedCalls: 0 }; }
  var st = fresh(cnDay());
  var reserved = 0, lastSave = 0;
  if (file && fs.existsSync(file)) {
    try { var j = JSON.parse(fs.readFileSync(file, 'utf8')); if (j.day === st.day) st = Object.assign(st, j); } catch (e) {}
  }
  function roll() { var d = cnDay(); if (d !== st.day) { st = fresh(d); reserved = 0; } }
  function save(force) {
    if (!file) return;
    var t = Date.now(); if (!force && t - lastSave < 2000) return; lastSave = t;
    try { fs.mkdirSync(path.dirname(file), { recursive: true }); fs.writeFileSync(file + '.tmp', JSON.stringify(st)); fs.renameSync(file + '.tmp', file); } catch (e) { console.error('[budget] save failed', e.message); }
  }
  function cost(inTok, outTok) { return (inTok * prices.inPerM + outTok * prices.outPerM) / 1e6; }
  function appendLedger(rec) {
    if (!opts.dir) return;
    try {
      fs.mkdirSync(opts.dir, { recursive: true });
      fs.appendFileSync(path.join(opts.dir, 'chat-usage-' + rec.day + '.jsonl'), JSON.stringify(rec) + '\n', { mode: 0o600 });
    } catch (e) { console.error('[budget] ledger append failed', e.message); }
  }
  return {
    cost: cost,
    enabled: function () { return capCny > 0; },
    /** 预占一次调用的最坏花费；返回 token（数字）或 null（预算不足） */
    reserve: function (estIn, maxOut) {
      roll();
      var c = cost(estIn, maxOut);
      if (capCny > 0 && st.spentCny + reserved + c > capCny) { st.refused++; save(); return null; }
      reserved += c; return c;
    },
    commit: function (resv, usage) {
      roll();
      reserved = Math.max(0, reserved - (resv || 0));
      if (!usage) return;
      st.calls++; st.inTokens += usage.in; st.outTokens += usage.out;
      st.spentCny = +(st.spentCny + cost(usage.in, usage.out)).toFixed(6);
      save();
    },
    /**
     * #174：按上游 usage 结算并写一行逐次台账。
     * raw：上游响应的 usage 对象，原样写进台账；没有（或不含 token 数）时用 est {in, out} 估算并标 estimated: true。
     * raw 和 est 都没有（调用失败且上游没给 usage）：只释放预占，不记账，返回 null。
     * 金额 = prompt_tokens × 输入单价 + completion_tokens × 输出单价（思考 token 已含在 completion_tokens 里；
     * cached_tokens 照原价算，是上限）。返回台账记录。
     */
    record: function (resv, raw, est, meta) {
      roll();
      reserved = Math.max(0, reserved - (resv || 0));
      var u = normUsage(raw), estimated = false, usage = numericLeaves(raw);
      if (!u) {
        if (!est) return null;
        estimated = true;
        u = { in: +est.in || 0, out: +est.out || 0, reasoning: 0, cached: 0 };
        usage = { prompt_tokens: u.in, completion_tokens: u.out, total_tokens: u.in + u.out };
      }
      var c = +cost(u.in, u.out).toFixed(8);
      st.calls++; st.inTokens += u.in; st.outTokens += u.out;
      st.reasoningTokens += u.reasoning; st.cachedTokens += u.cached;
      if (estimated) st.estimatedCalls++;
      st.spentCny = +(st.spentCny + c).toFixed(6);
      // #178：台账行只写白名单字段（LEDGER_FIELDS），meta 里只取 model / failed，不写对话、IP、会话、UA
      meta = meta || {};
      var rec = { ts: new Date().toISOString(), day: st.day };
      if (typeof meta.model === 'string') rec.model = meta.model.slice(0, 64);
      rec.estimated = estimated;
      if (meta.failed === true) rec.failed = true;
      rec.usage = usage; rec.cny = c; rec.prices = { inPerM: +prices.inPerM, outPerM: +prices.outPerM };
      appendLedger(rec);
      save();
      return rec;
    },
    status: function () {
      roll();
      return { day: st.day, capCny: capCny, spentCny: +st.spentCny.toFixed(4), calls: st.calls, refused: st.refused,
        exhausted: capCny > 0 && st.spentCny >= capCny * 0.999 };
    },
    flush: function () { save(true); }
  };
}

/** 逐次台账一行允许的字段（#178） */
var LEDGER_FIELDS = ['ts', 'day', 'model', 'estimated', 'failed', 'usage', 'cny', 'prices'];

/** usage 只留数字叶子（#178）：上游若在 usage 里塞字符串、数组、布尔等一律丢掉，空的子对象也丢掉；最多 3 层 */
function numericLeaves(o, depth) {
  depth = depth || 0;
  if (!o || typeof o !== 'object' || Array.isArray(o) || depth > 2) return {};
  var out = {};
  Object.keys(o).forEach(function (k) {
    var v = o[k];
    if (typeof v === 'number' && isFinite(v)) out[k] = v;
    else if (v && typeof v === 'object' && !Array.isArray(v)) {
      var sub = numericLeaves(v, depth + 1);
      if (Object.keys(sub).length) out[k] = sub;
    }
  });
  return out;
}

/** 上游 usage → {in, out, reasoning, cached}；不是对象或没有 token 数时返回 null */
function normUsage(u) {
  if (!u || typeof u !== 'object') return null;
  var n = function (x) { x = +x; return isFinite(x) && x > 0 ? Math.round(x) : 0; };
  if (!isFinite(+u.prompt_tokens) && !isFinite(+u.completion_tokens)) return null;
  if (u.prompt_tokens == null && u.completion_tokens == null) return null;
  return {
    in: n(u.prompt_tokens), out: n(u.completion_tokens),
    reasoning: n(u.completion_tokens_details && u.completion_tokens_details.reasoning_tokens),
    cached: n(u.prompt_tokens_details && u.prompt_tokens_details.cached_tokens)
  };
}

/** 粗略 token 估算：中文约 1 字 ≈ 1 token，其他约 4 字符 ≈ 1 token；偏保守 */
function estimateTokens(messages) {
  var n = 0;
  (messages || []).forEach(function (m) {
    var s = String(m.content || '');
    var cjk = (s.match(/[\u3000-\u9fff\uff00-\uffef]/g) || []).length;
    n += cjk + Math.ceil((s.length - cjk) / 3) + 4;
  });
  return n + 8;
}

/** 解析 ALLOWED_ORIGINS（逗号分隔）；空表示不发 CORS 头、不检查（本地开发） */
function parseOrigins(s) {
  return String(s || '').split(',').map(function (x) { return x.trim().replace(/\/+$/, ''); }).filter(Boolean);
}

module.exports = { cnDay: cnDay, createLimiter: createLimiter, createBudget: createBudget, estimateTokens: estimateTokens, normUsage: normUsage, numericLeaves: numericLeaves, LEDGER_FIELDS: LEDGER_FIELDS, parseOrigins: parseOrigins };
