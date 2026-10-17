#!/usr/bin/env node
/*!
 * DeepSuck — 可选的本地后端（零依赖，Node.js >= 18）
 *  - 托管 site/ 静态文件
 *  - POST /api/chat：代理到 OpenAI 兼容大模型（默认阿里云百炼 DashScope / qwen-plus），API Key 只留在服务器端
 *  - GET  /api/health：返回是否已配置大模型（不返回 Key）
 * 用法：cp .env.example .env && 填写 DASHSCOPE_API_KEY && npm start
 * Apache-2.0 · 非官方项目，与 DeepSeek 无关
 */
'use strict';
var http = require('http');
var fs = require('fs');
var path = require('path');
var llm = require('../site/assets/js/llm.js');
var engine = require('../site/assets/js/engine.js');

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
  baseUrl: process.env.LLM_BASE_URL || llm.DEFAULTS.baseUrl,
  model: process.env.LLM_MODEL || llm.DEFAULTS.model,
  temperature: process.env.LLM_TEMPERATURE ? parseFloat(process.env.LLM_TEMPERATURE) : llm.DEFAULTS.temperature,
  rateLimit: parseInt(process.env.RATE_LIMIT_PER_MIN || '20', 10)
};

var MIME = {
  '.html': 'text/html; charset=utf-8', '.css': 'text/css; charset=utf-8', '.js': 'application/javascript; charset=utf-8',
  '.svg': 'image/svg+xml', '.png': 'image/png', '.json': 'application/json; charset=utf-8', '.ico': 'image/x-icon',
  '.txt': 'text/plain; charset=utf-8', '.md': 'text/markdown; charset=utf-8'
};

var hits = {};
function rateOk(ip) {
  var now = Date.now(), win = 60000;
  var arr = (hits[ip] || []).filter(function (t) { return now - t < win; });
  if (arr.length >= CFG.rateLimit) { hits[ip] = arr; return false; }
  arr.push(now); hits[ip] = arr; return true;
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
    fs.createReadStream(file).pipe(res);
  });
}

function handleChat(req, res) {
  var ip = req.socket.remoteAddress || 'unknown';
  if (!CFG.apiKey) return send(res, 503, { error: '服务器未配置大模型 API Key（.env 中的 DASHSCOPE_API_KEY），前端将回退到规则引擎。' });
  if (!rateOk(ip)) return send(res, 429, { error: '请求过于频繁，请稍后再试。' });
  readBody(req, 64 * 1024).then(function (raw) {
    var p;
    try { p = JSON.parse(raw); } catch (e) { return send(res, 400, { error: 'JSON 格式错误' }); }
    var hint = typeof p.hint === 'string' && llm.INTENT_HINTS[p.hint] ? p.hint : 'generic';
    var transcript = Array.isArray(p.transcript) ? p.transcript.filter(function (m) {
      return m && (m.role === 'scammer' || m.role === 'bot') && typeof m.text === 'string';
    }) : [];
    var missing = Array.isArray(p.missing) ? p.missing.filter(function (g) { return typeof g === 'string'; }).slice(0, 5) : [];
    // 系统提示词由服务端生成，不接受客户端自定义，避免被当作通用代理滥用
    var messages = llm.buildMessages({ persona: String(p.persona || ''), scenario: String(p.scenario || ''), hint: hint, missing: missing, transcript: transcript });
    return llm.chatCompletions(CFG, messages).then(function (reply) {
      send(res, 200, { reply: reply, model: CFG.model });
    });
  }).catch(function (e) {
    console.error('[chat]', e.message);
    send(res, 502, { error: '大模型调用失败：' + e.message.slice(0, 160) });
  });
}

var server = http.createServer(function (req, res) {
  var u = req.url.split('?')[0];
  if (u === '/api/health') {
    return send(res, 200, { ok: true, version: engine.VERSION, llmConfigured: !!CFG.apiKey, model: CFG.apiKey ? CFG.model : null, provider: CFG.apiKey ? CFG.baseUrl.replace(/^https?:\/\//, '').split('/')[0] : null });
  }
  if (u === '/api/chat') {
    if (req.method !== 'POST') return send(res, 405, { error: 'POST only' });
    return handleChat(req, res);
  }
  if (req.method !== 'GET' && req.method !== 'HEAD') return send(res, 405, { error: 'method not allowed' });
  serveStatic(req, res);
});

if (require.main === module) {
  server.listen(CFG.port, CFG.host, function () {
    console.log('DeepSuck（非官方项目，与 DeepSeek 无关）已启动: http://' + CFG.host + ':' + CFG.port + '/');
    console.log(CFG.apiKey ? '大模型引擎：已配置 ' + CFG.model + ' @ ' + CFG.baseUrl : '大模型引擎：未配置（仅规则引擎）。如需启用，请在 .env 中填写 DASHSCOPE_API_KEY');
  });
}

module.exports = { server: server, CFG: CFG };
