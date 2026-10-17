'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const BL = require('../site/assets/js/blocklist.js');
const E = require('../site/assets/js/engine.js');
const { build } = require('../scripts/fetch-blocklists.js');

const FX = JSON.parse(fs.readFileSync(path.join(__dirname, 'fixtures', 'blocklist.json'), 'utf8'));

test('FNV 分片 / 主机名 / 父域候选 / 钱包规范化 与夹具一致', () => {
  for (const c of FX.fnv) { assert.equal(BL.fnv1a(c.input), c.hash); assert.equal(BL.shardOf(c.input), c.shard); }
  for (const c of FX.hosts) {
    const h = BL.hostOf(c.input);
    assert.equal(h, c.host, c.input);
    if (h) assert.deepEqual(BL.candidates(h), c.candidates);
  }
  for (const c of FX.wallets) assert.equal(BL.walletKey(c.input), c.key);
});

// 用虚构 .example 域名构造迷你分片，模拟 data/blocklist/ 目录
function fakeFiles() {
  const { all, counts, shards } = build(['evil-demo.example\nrefund-tb-kefu.example\n# comment\nBAD DOMAIN\n', 'refund-tb-kefu.example\nonly-pdb.example\n']);
  const files = { 'x/meta.json': JSON.stringify({ generatedAt: '2026-10-18T00:00:00Z', total: all.size, sources: [{ name: 'destroylist' }, { name: 'Phishing.Database' }] }) };
  for (const id of Object.keys(shards)) files['x/d/' + id + '.txt'] = shards[id].join('\n');
  return { files, counts };
}

test('build()：清洗、去重、按来源打位标记', () => {
  const { counts } = fakeFiles();
  assert.deepEqual(counts, [2, 2]);
});

test('checkDomain：精确命中 / 父域命中 / 未命中 / 不可用', async () => {
  const { files } = fakeFiles();
  const fetchText = (u) => (u in files ? Promise.resolve(files[u]) : u.startsWith('x/d/') ? Promise.resolve('') : Promise.reject(new Error('404')));
  const c = BL.createClient({ base: 'x', fetchText });
  let r = await c.checkDomain('https://refund-tb-kefu.example/dl');
  assert.equal(r.status, 'hit'); assert.equal(r.how, 'exact'); assert.deepEqual(r.sources, ['destroylist', 'Phishing.Database']);
  r = await c.checkDomain('http://login.www.evil-demo.example:8080/a');
  assert.equal(r.status, 'hit'); assert.equal(r.how, 'parent'); assert.deepEqual(r.sources, ['destroylist']);
  assert.equal((await c.checkDomain('good-site.example')).status, 'clean');
  assert.equal((await c.checkDomain('not a domain')).status, 'skip');
  const none = BL.createClient({ base: 'y', fetchText: () => Promise.reject(new Error('404')) });
  assert.equal((await none.checkDomain('evil-demo.example')).status, 'unavailable');
});

test('checkWallet：运行时列表（json / lines），EVM 不区分大小写', async () => {
  const lists = {};
  for (const s of BL.WALLET_SOURCES) lists[s.url] = s.format === 'json-array' ? JSON.stringify(['0xabcdef0123456789abcdef0123456789abcdef01']) : '# demo\nTQ7xM6hYpCzD8vNp1qJ3kR5sW9uL2aBcDe\n';
  const c = BL.createClient({ base: 'x', fetchText: (u) => (u in lists ? Promise.resolve(lists[u]) : Promise.reject(new Error('404'))) });
  let r = await c.check('crypto_eth', '0xABCDEF0123456789ABCDEF0123456789ABCDEF01');
  assert.equal(r.status, 'hit'); assert.ok(r.sources.includes('ScamSniffer scam-database'));
  r = await c.check('crypto_tron', 'TQ7xM6hYpCzD8vNp1qJ3kR5sW9uL2aBcDe');
  assert.equal(r.status, 'hit');
  assert.equal((await c.check('crypto_tron', 'TQ7xM6hYpCzD8vNp1qJ3kR5sW9uL2aBcDf')).status, 'clean');
  assert.equal((await c.check('bank_card', '6222020200112233445')).status, 'skip');
});

test('会话：黑名单结果进入报告，但不泄露原值', async () => {
  const s = new E.Session({ scenario: 'refund', persona: 'wang' });
  s.ingest('下载链接 https://refund-tb-kefu.example/dl ，USDT 打到 TQ7xM6hYpCzD8vNp1qJ3kR5sW9uL2aBcDe');
  const pend = s.pendingBlocklist();
  assert.deepEqual(pend.map((p) => p.type).sort(), ['crypto_tron', 'url']);
  for (const p of pend) s.annotate(p.key, p.type === 'url' ? { status: 'hit', how: 'exact', sources: ['destroylist'], listed: 'x' } : { status: 'clean' });
  assert.equal(s.pendingBlocklist().length, 0);
  const json = JSON.stringify(s.report());
  assert.ok(json.includes('"status":"hit"'));
  assert.ok(!json.includes('refund-tb-kefu.example') && !json.includes('TQ7xM6hYpCzD8vNp1qJ3kR5sW9uL2aBcDe'), json);
});
