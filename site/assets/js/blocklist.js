/*!
 * DeepSuck — blocklist.js
 * 公开黑名单比对：
 *   - 域名：destroylist、Phishing.Database（MIT），构建时由 scripts/fetch-blocklists.js 按 FNV-1a(域名) % 256 分片到 data/blocklist/d/xx.txt，
 *     浏览器只按需拉取 1–3 个分片（每片几十 KB），查询的域名不会发给第三方。
 *   - 钱包：ScamSniffer（GPL-3.0）、OFAC SDN 地址列表，运行时从 GitHub 拉取整表后本地比对（不打包进本仓库）。
 * 命中仅供参考：域名可能被回收、地址可能被冒用，不能作为认定依据。
 * Apache-2.0 · 非官方项目，与 DeepSeek 无关
 */
(function (root, factory) {
  var isNode = typeof module === 'object' && module.exports;
  var C = isNode ? require('../core/blocklists.json') : (root.DeepSuck.coreData || {}).blocklists;
  var mod = factory(C);
  if (isNode) module.exports = mod;
  else { root.DeepSuck = root.DeepSuck || {}; root.DeepSuck.blocklist = mod; }
})(typeof self !== 'undefined' ? self : this, function (C) {
  'use strict';

  var SHARDS = C.domainShards;
  var DOMAIN_SOURCES = C.sources.filter(function (s) { return s.kind === 'domain'; });
  var WALLET_SOURCES = C.sources.filter(function (s) { return s.kind === 'wallet'; });

  /** FNV-1a 32 位（按 UTF-8 字节；域名均为 ASCII/punycode） */
  function fnv1a(str) {
    var h = 0x811c9dc5;
    for (var i = 0; i < str.length; i++) {
      h ^= str.charCodeAt(i) & 0xff;
      h = Math.imul(h, 0x01000193) >>> 0;
    }
    return h >>> 0;
  }
  function shardOf(domain) {
    var n = fnv1a(domain) % SHARDS;
    return ('0' + n.toString(16)).slice(-2);
  }

  /** 从 URL / 裸域名中取出小写主机名（去掉 www. 与端口）；不是域名则返回 null */
  function hostOf(v) {
    var s = String(v || '').trim().toLowerCase();
    s = s.replace(/^[a-z][a-z0-9+.-]*:\/\//, '').replace(/^\/\//, '');
    s = s.split(/[\/?#]/)[0].replace(/:\d+$/, '').replace(/\.+$/, '');
    if (s.indexOf('@') >= 0) s = s.slice(s.lastIndexOf('@') + 1);
    if (!/^[a-z0-9.-]+\.[a-z0-9-]{2,}$/.test(s) || /^\d+(\.\d+){3}$/.test(s)) return null;
    return s;
  }

  /** 待查域名：自身 + 各级父域（至少 domainParentMinLabels 段），如 a.b.evil.top → a.b.evil.top, b.evil.top, evil.top */
  function candidates(host) {
    var parts = host.split('.');
    var out = [];
    for (var i = 0; i <= parts.length - C.domainParentMinLabels; i++) out.push(parts.slice(i).join('.'));
    return out;
  }

  /** 解析分片：每行 "domain<TAB>bits"，bits 的第 i 位对应 meta.sources[i] */
  function parseShard(text) {
    var map = {};
    String(text || '').split('\n').forEach(function (line) {
      if (!line) return;
      var t = line.indexOf('\t');
      if (t < 0) map[line] = 1; else map[line.slice(0, t)] = parseInt(line.slice(t + 1), 10) || 1;
    });
    return map;
  }

  /** 钱包地址规范化：EVM 不区分大小写；TRON/BTC base58 区分大小写；bech32 统一小写 */
  function walletKey(addr) {
    var s = String(addr || '').trim();
    if (/^0x[0-9a-f]{40}$/i.test(s) || /^bc1/i.test(s)) return s.toLowerCase();
    return s;
  }

  function parseWalletList(text, format) {
    var list = [];
    if (format === 'json-array') {
      try { list = JSON.parse(text); } catch (e) { list = []; }
    } else {
      list = String(text || '').split(/\r?\n/);
    }
    var set = {};
    list.forEach(function (a) { a = String(a || '').trim(); if (a && a.charAt(0) !== '#') set[walletKey(a)] = 1; });
    return set;
  }

  /**
   * createClient({ base, fetchText }) —— base 为分片目录（含 meta.json），fetchText(url) 返回 Promise<string>（失败时 reject）。
   */
  function createClient(opts) {
    opts = opts || {};
    var base = (opts.base || 'data/blocklist/').replace(/\/?$/, '/');
    var fetchText = opts.fetchText || function (url) {
      return fetch(url).then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.text(); });
    };
    var metaP = null, shardP = {}, walletP = {};

    function meta() {
      if (!metaP) metaP = fetchText(base + 'meta.json').then(JSON.parse).catch(function () { return null; });
      return metaP;
    }
    function shard(id) {
      if (!shardP[id]) shardP[id] = fetchText(base + 'd/' + id + '.txt').then(parseShard);
      return shardP[id];
    }

    /** checkDomain(urlOrHost) -> Promise<{ status: 'hit'|'clean'|'unavailable'|'skip', how?, sources?, listed? }> */
    function checkDomain(v) {
      var host = hostOf(v);
      if (!host) return Promise.resolve({ status: 'skip' });
      return meta().then(function (m) {
        if (!m) return { status: 'unavailable' };
        var cands = candidates(host);
        return Promise.all(cands.map(function (d) { return shard(shardOf(d)).then(function (map) { return map[d] || 0; }); }))
          .then(function (bits) {
            for (var i = 0; i < cands.length; i++) {
              if (bits[i]) {
                var srcs = m.sources.filter(function (s, k) { return bits[i] & (1 << k); }).map(function (s) { return s.name; });
                return { status: 'hit', how: i === 0 ? 'exact' : 'parent', sources: srcs, listed: cands[i], updated: m.generatedAt };
              }
            }
            return { status: 'clean', updated: m.generatedAt, total: m.total };
          });
      }).catch(function () { return { status: 'unavailable' }; });
    }

    function walletSet(src) {
      if (!walletP[src.id]) {
        walletP[src.id] = fetchText(src.url).then(function (t) { return parseWalletList(t, src.format); })
          .catch(function () { delete walletP[src.id]; return null; });
      }
      return walletP[src.id];
    }

    /** checkWallet(addr, extractorType) -> Promise<{ status, sources? }> */
    function checkWallet(addr, type) {
      var srcs = WALLET_SOURCES.filter(function (s) { return !type || s.chains.indexOf(type) >= 0; });
      if (!srcs.length) return Promise.resolve({ status: 'skip' });
      var key = walletKey(addr);
      return Promise.all(srcs.map(walletSet)).then(function (sets) {
        var ok = sets.filter(Boolean).length;
        if (!ok) return { status: 'unavailable' };
        var hits = srcs.filter(function (s, i) { return sets[i] && sets[i][key]; }).map(function (s) { return s.name; });
        return hits.length ? { status: 'hit', how: 'exact', sources: hits } : { status: 'clean', checked: ok };
      });
    }

    /** check(type, raw)：按情报类型分派；非域名/钱包类型返回 skip */
    function check(type, raw) {
      if (type === 'url' || type === 'email') return checkDomain(type === 'email' ? String(raw).split('@').pop() : raw);
      if (/^crypto_/.test(type)) return checkWallet(raw, type);
      return Promise.resolve({ status: 'skip' });
    }

    return { meta: meta, checkDomain: checkDomain, checkWallet: checkWallet, check: check };
  }

  return {
    SOURCES: C.sources, DOMAIN_SOURCES: DOMAIN_SOURCES, WALLET_SOURCES: WALLET_SOURCES, SHARDS: SHARDS,
    fnv1a: fnv1a, shardOf: shardOf, hostOf: hostOf, candidates: candidates, parseShard: parseShard,
    walletKey: walletKey, parseWalletList: parseWalletList, createClient: createClient
  };
});
