#!/usr/bin/env node
/*!
 * DeepSuck — 可选的本地后端（零依赖，Node.js >= 18）
 *  - 托管 site/ 静态文件
 *  - POST /api/chat：代理到 OpenAI 兼容大模型（默认阿里云百炼 DashScope / qwen-plus），API Key 只留在服务器端
 *  - GET  /api/health：返回是否已配置大模型、限流与当日预算状态（不返回 Key）
 *  - 公开部署（deploy/）时的费用护栏见 server/guard.js：每 IP/全局限流、每局最大轮数、每日预算上限、CORS 白名单
 * 用法：cp .env.example .env && 填写 DASHSCOPE_API_KEY && npm start
 * Apache-2.0
 */
'use strict';
var http = require('http');
var fs = require('fs');
var path = require('path');
var llm = require('../site/assets/js/llm.js');
var engine = require('../site/assets/js/engine.js');
var guard = require('./guard.js');

var ROOT = path.resolve(__dirname, '..');
var SITE = path.join(ROOT, 'site');

function loadEnv(file) {
  if (!fs.existsSync(file)) return;
  fs.readFileSync(file, 'utf8').split(/\r?\n/).forEach(function (line) {
    var m = line.match(/^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)\s*$/);
    if (!m || line.trim().charAt(0) === '#') return;
    var v = m[2].replace(/^(['"])(.*)\1$/, '$2');
    if (process.env[m[1]] === undefined) process.env[m[1]] = v;
  });
}
loadEnv(path.join(ROOT, '.env'));

var CFG = {
  host: process.env.HOST || '127.0.0.1',
  port: parseInt(process.env.PORT || '8787', 10),
  apiKey: process.env.LLM_API_KEY || process.env.DASHSCOPE_API_KEY || '',
  // 服务端代理的默认值（未设 LLM_BASE_URL / LLM_MODEL 时）：百炼兼容模式 + qwen-plus，与改前一致。
  // 浏览器端 llm.js 的 DEFAULTS 已留空（#108），这里单独保留，代理行为不变。配置见 docs/QUICKSTART.md。
  baseUrl: process.env.LLM_BASE_URL || 'https://dashscope.aliyuncs.com/compatible-mode/v1',
  model: process.env.LLM_MODEL || 'qwen-plus',
  temperature: process.env.LLM_TEMPERATURE ? parseFloat(process.env.LLM_TEMPERATURE) : llm.DEFAULTS.temperature,
  maxTokens: parseInt(process.env.LLM_MAX_TOKENS || '120', 10),
  // ---- 费用护栏（公开部署时务必保留默认值或调得更严） ----
  rateLimit: parseInt(process.env.RATE_LIMIT_PER_MIN || '20', 10),          // 每 IP 每分钟
  ratePerDay: parseInt(process.env.RATE_LIMIT_PER_DAY || '300', 10),        // 每 IP 每天
  globalPerMin: parseInt(process.env.GLOBAL_RATE_PER_MIN || '60', 10),      // 全站每分钟
  maxTurns: parseInt(process.env.CHAT_MAX_TURNS || '40', 10),               // 每局骗子最多发言轮数
  budgetCny: parseFloat(process.env.CHAT_DAILY_BUDGET_CNY || '0'),          // 每日预算（元），0 = 不限（仅本地）
  priceInPerM: parseFloat(process.env.PRICE_LLM_IN_PER_M || '0.8'),         // qwen-plus 输入 元/百万 token
  priceOutPerM: parseFloat(process.env.PRICE_LLM_OUT_PER_M || '2'),         // qwen-plus 输出 元/百万 token
  dataDir: process.env.DATA_DIR || '',
  origins: guard.parseOrigins(process.env.ALLOWED_ORIGINS),                // 例：https://deepsuck.si,https://www.deepsuck.si
  trustProxy: process.env.TRUST_PROXY === '1',                             // 在 Caddy 之后：取 X-Forwarded-For 最右值
  serveStatic: process.env.SERVE_STATIC !== '0'
};
var limiter = guard.createLimiter({ perIpPerMin: CFG.rateLimit, perIpPerDay: CFG.ratePerDay, globalPerMin: CFG.globalPerMin });
var budget = guard.createBudget({ capCny: CFG.budgetCny, dir: CFG.dataDir, prices: { inPerM: CFG.priceInPerM, outPerM: CFG.priceOutPerM } });

var MIME = {
  '.html': 'text/html; charset=utf-8', '.css': 'text/css; charset=utf-8', '.js': 'application/javascript; charset=utf-8',
  '.svg': 'image/svg+xml', '.png': 'image/png', '.json': 'application/json; charset=utf-8', '.ico': 'image/x-icon',
  '.txt': 'text/plain; charset=utf-8', '.md': 'text/markdown; charset=utf-8'
};

function clientIp(req) {
  if (CFG.trustProxy) {
    var xff = String(req.headers['x-forwarded-for'] || '').split(',').map(function (x) { return x.trim(); }).filter(Boolean);
    if (xff.length) return xff[xff.length - 1];
  }
  return req.socket.remoteAddress || 'unknown';
}

/** CORS：只给白名单里的 Origin 回头；返回 false 表示应拒绝 */
function cors(req, res) {
  if (!CFG.origins.length) return true;
  var o = String(req.headers.origin || '').replace(/\/+$/, '');
  res.setHeader('Vary', 'Origin');
  if (o && CFG.origins.indexOf(o) >= 0) {
    res.setHeader('Access-Control-Allow-Origin', o);
    res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
    res.setHeader('Access-Control-Allow-Headers', 'Content-Type');
    res.setHeader('Access-Control-Max-Age', '600');
    return true;
  }
  return false;
}

function send(res, code, obj, headers) {
  var body = typeof obj === 'string' ? obj : JSON.stringify(obj);
  res.writeHead(code, Object.assign({ 'Content-Type': 'application/json; charset=utf-8', 'X-Content-Type-Options': 'nosniff' }, headers || {}));
  res.end(body);
}

function readBody(req, limit) {
  return new Promise(function (resolve, reject) {
    var size = 0, chunks = [];
    req.on('data', function (c) {
      size += c.length;
      if (size > limit) { reject(new Error('请求过大')); req.destroy(); return; }
      chunks.push(c);
    });
    req.on('end', function () { resolve(Buffer.concat(chunks).toString('utf8')); });
    req.on('error', reject);
  });
}

function serveStatic(req, res) {
  var urlPath = decodeURIComponent(req.url.split('?')[0]);
  if (urlPath.endsWith('/')) urlPath += 'index.html';
  var file = path.normalize(path.join(SITE, urlPath));
  if (file !== SITE && file.indexOf(SITE + path.sep) !== 0) return send(res, 403, { error: 'forbidden' });
  fs.stat(file, function (err, st) {
    if (err || !st.isFile()) { res.writeHead(404, { 'Content-Type': 'text/plain; charset=utf-8' }); return res.end('404'); }
    res.writeHead(200, { 'Content-Type': MIME[path.extname(file)] || 'application/octet-stream', 'X-Content-Type-Options': 'nosniff' });
    // 自托管时告诉前端"同源有 /api/"：纯静态托管（GitHub Pages 等）没有这一行，前端就不会去请求 api/health
    if (urlPath === '/assets/js/live-config.js') {
      return fs.readFile(file, 'utf8', function (e, js) { res.end((js || '') + '\n;(self.DEEPSUCK_LIVE = self.DEEPSUCK_LIVE || { api: \'\' }).local = true;\n'); });
    }
    fs.createReadStream(file).pipe(res);
  });
}

function handleChat(req, res) {
  var ip = clientIp(req);
  if (!CFG.apiKey) return send(res, 503, { error: '服务器未配置大模型 API Key（.env 中的 DASHSCOPE_API_KEY），前端将回退到规则引擎。' });
  if (budget.status().exhausted) return send(res, 429, { error: '今日大模型体验额度已用完，已切换为规则引擎。', code: 'budget' });
  var why = limiter.check(ip);
  if (why) return send(res, 429, { error: why, code: 'rate' });
  readBody(req, 64 * 1024).then(function (raw) {
    var p;
    try { p = JSON.parse(raw); } catch (e) { return send(res, 400, { error: 'JSON 格式错误' }); }
    var hint = typeof p.hint === 'string' && llm.INTENT_HINTS[p.hint] ? p.hint : 'generic';
    var transcript = Array.isArray(p.transcript) ? p.transcript.filter(function (m) {
      return m && (m.role === 'scammer' || m.role === 'bot') && typeof m.text === 'string';
    }) : [];
    var turns = transcript.filter(function (m) { return m.role === 'scammer'; }).length;
    if (CFG.maxTurns > 0 && turns > CFG.maxTurns) return send(res, 429, { error: '本局已达 ' + CFG.maxTurns + ' 轮上限，请结束对话查看情报看板。', code: 'max_turns' });
    var missing = Array.isArray(p.missing) ? p.missing.filter(function (g) { return typeof g === 'string'; }).slice(0, 5) : [];
    // 系统提示词由服务端生成，不接受客户端自定义，避免被当作通用代理滥用
    var messages = llm.buildMessages({ persona: String(p.persona || ''), scenario: String(p.scenario || ''), hint: hint, missing: missing, transcript: transcript });
    var estIn = guard.estimateTokens(messages);
    var resv = budget.reserve(estIn, CFG.maxTokens);
    if (resv === null) return send(res, 429, { error: '今日大模型体验额度已用完，已切换为规则引擎。', code: 'budget' });
    var used = null;
    var cfg = Object.assign({}, CFG, { onUsage: function (u) {
      used = u ? { in: +u.prompt_tokens || 0, out: +u.completion_tokens || 0 } : null;
    } });
    return llm.chatCompletions(cfg, messages).then(function (reply) {
      budget.commit(resv, used || { in: estIn, out: guard.estimateTokens([{ content: reply }]) });
      send(res, 200, { reply: reply, model: CFG.model });
    }, function (e) {
      budget.commit(resv, used); // 失败调用通常不计费；若有 usage 仍按实际记账
      throw e;
    });
  }).catch(function (e) {
    console.error('[chat]', e.message);
    send(res, 502, { error: '大模型调用失败：' + e.message.slice(0, 160) });
  });
}

function health() {
  var b = budget.status();
  return {
    ok: true, version: engine.VERSION, llmConfigured: !!CFG.apiKey, model: CFG.apiKey ? CFG.model : null,
    provider: CFG.apiKey ? CFG.baseUrl.replace(/^https?:\/\//, '').split('/')[0] : null,
    limits: { perIpPerMin: CFG.rateLimit, perIpPerDay: CFG.ratePerDay, globalPerMin: CFG.globalPerMin, maxTurns: CFG.maxTurns },
    budget: { capCny: b.capCny, usedPct: b.capCny ? Math.min(100, Math.round(b.spentCny / b.capCny * 100)) : null, exhausted: b.exhausted }
  };
}

var server = http.createServer(function (req, res) {
  var u = req.url.split('?')[0];
  if (u.indexOf('/api/') === 0) {
    var allowed = cors(req, res);
    if (req.method === 'OPTIONS') { res.writeHead(allowed ? 204 : 403); return res.end(); }
    if (u === '/api/health') return send(res, 200, health());
    if (u === '/api/chat') {
      if (req.method !== 'POST') return send(res, 405, { error: 'POST only' });
      // 配置了白名单时，/api/chat 必须带合法 Origin（挡住跨站滥用；非浏览器客户端仍受限流与预算约束）
      if (!allowed) return send(res, 403, { error: 'origin not allowed' });
      return handleChat(req, res);
    }
    return send(res, 404, { error: 'not found' });
  }
  if (!CFG.serveStatic) return send(res, 404, { error: 'not found' });
  if (req.method !== 'GET' && req.method !== 'HEAD') return send(res, 405, { error: 'method not allowed' });
  serveStatic(req, res);
});

if (require.main === module) {
  server.listen(CFG.port, CFG.host, function () {
    console.log('DeepSuck 已启动: http://' + CFG.host + ':' + CFG.port + '/');
    console.log('护栏：每 IP ' + CFG.rateLimit + '/分钟、' + CFG.ratePerDay + '/天；全站 ' + CFG.globalPerMin + '/分钟；每局 ' + CFG.maxTurns + ' 轮；每日预算 ' + (CFG.budgetCny > 0 ? CFG.budgetCny + ' 元' : '不限') + (CFG.origins.length ? '；CORS ' + CFG.origins.join(',') : ''));
    console.log(CFG.apiKey ? '大模型引擎：已配置 ' + CFG.model + ' @ ' + CFG.baseUrl : '大模型引擎：未配置（仅规则引擎）。如需启用，请在 .env 中填写 DASHSCOPE_API_KEY');
  });
}

function shutdown() { budget.flush(); process.exit(0); }
if (require.main === module) { process.on('SIGTERM', shutdown); process.on('SIGINT', shutdown); }

module.exports = { server: server, CFG: CFG, budget: budget, limiter: limiter };
