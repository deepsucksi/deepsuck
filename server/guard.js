/*!
 * DeepSuck — server/guard.js：公开部署时的费用护栏（零依赖）
 *  - 每 IP 每分钟 / 每 IP 每天 / 全局每分钟 限流
 *  - 每日全局预算（人民币，按 DashScope 返回的 usage token 记账；无 usage 时按字数估算），超出即拒绝
 *  - 预算账本按 Asia/Shanghai 自然日持久化到 DATA_DIR，重启不清零
 * Apache-2.0 · 非官方项目，与 DeepSeek 无关
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
  var st = { day: cnDay(), spentCny: 0, calls: 0, inTokens: 0, outTokens: 0, refused: 0 };
  var reserved = 0, lastSave = 0;
  if (file && fs.existsSync(file)) {
    try { var j = JSON.parse(fs.readFileSync(file, 'utf8')); if (j.day === st.day) st = Object.assign(st, j); } catch (e) {}
  }
  function roll() { var d = cnDay(); if (d !== st.day) { st = { day: d, spentCny: 0, calls: 0, inTokens: 0, outTokens: 0, refused: 0 }; reserved = 0; } }
  function save(force) {
    if (!file) return;
    var t = Date.now(); if (!force && t - lastSave < 2000) return; lastSave = t;
    try { fs.mkdirSync(path.dirname(file), { recursive: true }); fs.writeFileSync(file + '.tmp', JSON.stringify(st)); fs.renameSync(file + '.tmp', file); } catch (e) { console.error('[budget] save failed', e.message); }
  }
  function cost(inTok, outTok) { return (inTok * prices.inPerM + outTok * prices.outPerM) / 1e6; }
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
    status: function () {
      roll();
      return { day: st.day, capCny: capCny, spentCny: +st.spentCny.toFixed(4), calls: st.calls, refused: st.refused,
        exhausted: capCny > 0 && st.spentCny >= capCny * 0.999 };
    },
    flush: function () { save(true); }
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

module.exports = { cnDay: cnDay, createLimiter: createLimiter, createBudget: createBudget, estimateTokens: estimateTokens, parseOrigins: parseOrigins };
