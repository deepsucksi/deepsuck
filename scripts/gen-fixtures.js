#!/usr/bin/env node
/*!
 * 生成 tests/fixtures/*.json：以 JS 实现的输出为"金标准"，供 node:test 与 pytest（python/tests）共用。
 * 用法：npm run fixtures   —— 修改 core/*.json 或提取/脱敏逻辑后运行，并检查 diff 是否符合预期。
 * npm test 会检查夹具是否最新；pytest 会检查 Python 实现与夹具逐项一致（测试即规格）。
 * Apache-2.0 · 非官方项目，与 DeepSeek 无关
 */
'use strict';
const fs = require('fs');
const path = require('path');
const R = require('../site/assets/js/redact.js');
const N = require('../site/assets/js/normalize.js');
const X = require('../site/assets/js/extractors.js');
const T = require('../site/assets/js/tactics.js');
const E = require('../site/assets/js/engine.js');
const S = require('../site/assets/js/scenarios.js');
const P = require('../site/assets/js/personas.js');
const { mulberry32 } = require('./lib/rng.js');
const BL = require('../site/assets/js/blocklist.js');

const DIR = path.join(__dirname, '..', 'tests', 'fixtures');
const HEADER = '由 scripts/gen-fixtures.js 从 JS 实现生成（金标准），node 与 pytest 共用；请勿手改，改规则后运行 npm run fixtures。示例数据均为虚构。';

// ---- 输入用例（全部为虚构测试数据）----
const TEXTS = [
  '把钱转到 6217 0012 3456 7890 123，户名李强，建设银行',
  '打我 139-0011-2233 或 400-820-1234 或 021-61234567',
  '卡号6222020200112233445',
  '我的 QQ 是 2876543210', '加我微信 kefu_tb2026', '支付宝账号：abc.def@163.com', '支付宝 13912345678', '单纯的数字 2876543210',
  'ERC20：0x12ab34cd56ef7890abcdef1234567890abcd9f3e', 'TRC20 地址：TQ7xM6hYpCzD8vNp1qJ3kR5sW9uL2aBcDe',
  'BTC 1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa', 'bc1qar0srrr7xfkvy5l643lydnw9re59gtzzwf5mdq',
  '网址 https://refund-tb-kefu.top/dl ，下载', '平台 www.goldwin-vip.top 注册', '登录 kefu-jd.vip 查看', '邮箱 abc@163.com',
  '身份证号110101199001011234', '户名：王建国，工商银行', '下载“安心退”APP，先交 2000 元保证金，用支付宝或 USDT',
  '转到 6222020200112233445 户名王建国，电话 13900112233', '+86 138-1234-5678 是我的号', '充值 1.5 万 USDT 到 TQ7xM6hYpCzD8vNp1qJ3kR5sW9uL2aBcDe',
  '版本 1.5 更新了', '三三两两地走过来', '我点了一下就好了', '今天下午三点开会', 'App点开没反应', '普通的一句话', '访问 abc.com。然后',
  '加我 微 信 kefu_tb2026 详聊', 'V信：abc12345', '薇信号 scam_demo01', '绿泡泡 hello_world88', '扣扣 2876543210', '企鹅号码：1000012345',
  'Q Q：1000012345', '网址 refund-tb 点 com 下载', '打开 goldwin-vip。top 注册', 'refund-tb[.]top/dl', 'w w w . goldwin-vip . top',
  '打 幺三九 零零幺幺 二二三三', '电话一三九零零一一二二三三', '１３９００１１２２３３', '1 3 9 0 0 1 1 2 2 3 3 联系',
  '卡号 六二二二 零二零二 零零一一 二二三三 四四五', '支付寶 13900112233', '卡号 六二二二 零二零二 零零一一 二二三三 四四五，户名王建国',
  '把钱转到 六二二二 零二零二 零零一一 二二三三 四四五，有问题打 幺三九 零零幺幺 二二三三',
  '收款人是张伟，开户行招商银行 6225 8812 3456 7891', 'http://192.168.1.10:8080/admin 登录', '访问 HTTPS://Example-Refund.CN/a?b=1。',
  '客服电话 800 123 4567，邮箱 kefu.vip@example.com', '户名写钱伟就行', '户名写张3就行', '收款人李4，工商银行 6222020200112233445', '收款人是吴刚吧', '我记一下：网址/域名 re***fu.top，钱包 0x12ab...9f3e，对吗', '“金盾理财”平台 日赚 500 元，下载金盾理财APP'
];
for (const sc of S.SCENARIOS) for (const line of sc.samples) TEXTS.push(line);

const REDACT = [
  ['bank_card', '6222021234561234'], ['bank_card', '6222 0212 3456 7890 128'], ['bank_card', '1234'],
  ['phone', '13812345678'], ['phone', '+86 138-1234-5678'], ['phone', '400-820-1234'], ['phone', '021-61234567'], ['phone', '123'],
  ['crypto_eth', '0x12ab34cd56ef7890abcdef1234567890abcd9f3e'], ['crypto_tron', 'TQ7xM6hYpCzD8vNp1qJ3kR5sW9uL2aBcDe'],
  ['crypto_btc', 'bc1qar0srrr7xfkvy5l643lydnw9re59gtzzwf5mdq'], ['crypto_btc', 'short'],
  ['url', 'https://refund-taobao-kefu.top/app/download?id=9'], ['url', 'www.goldwin-vip.top'], ['url', 'http://gaj-sh-gov.cc/case/8872'],
  ['url', 'abc.cn'], ['url', 'http://192.168.1.10:8080/admin'], ['url', 'https://www.a.b.example/'],
  ['qq', '2876543210'], ['wechat', 'kefu_tb2026'], ['wechat', 'abc'], ['alipay', 'abc.def@163.com'], ['alipay', '13912345678'], ['alipay', 'zhangsan_pay'],
  ['email', 'abc.def@163.com'], ['email', 'a@b.cn'], ['id_card', '110101199001011234'], ['id_card', '11010119900101123x'],
  ['name', '王建国'], ['name', '欧阳娜娜'], ['name', ''], ['unknown_type', 'whatever123']
];

const SESSIONS = [];
let seed = 20261018;
for (const sc of S.SCENARIOS) for (const p of P.PERSONAS) SESSIONS.push({ scenario: sc.id, persona: p.id, seed: seed++, lines: sc.samples.slice(0, 6) });
SESSIONS.push({ scenario: 'police', persona: 'li', seed: 7, lines: ['我是公安局的', '你涉嫌洗钱', '马上把验证码发我', '不要告诉任何人', '转到安全账户', '你听不懂吗？', '快点', '再不配合就逮捕你'] });

// ---- 生成 ----
function pickEntity(e) {
  const o = { type: e.type, value: e.value, masked: e.masked, start: e.start, end: e.end, sensitive: e.sensitive, meta: e.meta };
  if ('raw' in e) o.raw = e.raw;
  if ('obfuscated' in e) o.obfuscated = e.obfuscated;
  return o;
}

function build() {
  const out = {};
  out.redact = { comment: HEADER, cases: REDACT.map(([type, input]) => ({ type, input, expected: R.mask(type, input) })) };
  out.normalize = { comment: HEADER, cases: TEXTS.map((text) => { const n = N.normalize(text); return { text, expected: n.text, changed: n.changed }; }) };
  out.extract = {
    comment: HEADER,
    cases: TEXTS.map((text) => {
      const ents = X.extract(text);
      return { text, entities: ents.map(pickEntity), redacted: R.redactText(text, ents) };
    })
  };
  const counts = [{}, { otp: 1 }, { safe_account: 2, otp: 1, urgency: 5 }, { authority: 3, threat: 3, secrecy: 1, transfer: 2 }, { romance: 1 }];
  out.tactics = {
    comment: HEADER,
    cases: TEXTS.concat(['加我 微 信 私聊', '把 验 证 码 发我', '转到 安 全 账 户', '我是你领导，在开会，不方便接电话']).map((text) => ({
      text, expected: T.classify(text).map((t) => ({ id: t.id, match: t.match }))
    })),
    risk: counts.map((c) => ({ counts: c, expected: T.riskScore(c) }))
  };
  out.sessions = {
    comment: HEADER + ' rng = mulberry32(seed)；now 固定为 1760000000000。',
    cases: SESSIONS.map((c) => {
      const s = new E.Session({ scenario: c.scenario, persona: c.persona, rng: mulberry32(c.seed), now: () => 1760000000000 });
      const turns = [{ role: 'bot', text: s.opening().text, intent: 'opening' }];
      for (const line of c.lines) {
        const a = s.ingest(line);
        const m = s.ruleReply(a);
        turns.push({ role: 'scammer', text: a.redacted, tactics: a.tactics.map((t) => t.id) });
        turns.push({ role: 'bot', text: m.text, intent: m.intent });
      }
      const st = s.stats();
      return Object.assign({}, c, { turns, intel: s.intelList(), stats: { estimatedScammerSeconds: st.estimatedScammerSeconds, intelCount: st.intelCount, riskScore: st.riskScore } });
    })
  };
  // 黑名单：FNV 分片、主机名解析、父域候选、钱包规范化（域名均为 .example / 虚构）
  const HOSTS = ['https://Login.Refund-TB-Kefu.example/dl?x=1', 'www.goldwin-vip.example', 'kefu-jd.example:8080/a', 'abc@mail.scam-demo.example',
    'http://192.168.1.10/admin', '例子.中国', 'a.b.c.d.evil-demo.example', 'evil-demo.example.', 'localhost'];
  out.blocklist = {
    comment: HEADER,
    fnv: ['', 'a', 'evil-demo.example', 'refund-tb-kefu.example', 'xn--fiqs8s.example'].map((d) => ({ input: d, hash: BL.fnv1a(d), shard: BL.shardOf(d) })),
    hosts: HOSTS.map((v) => { const h = BL.hostOf(v); return { input: v, host: h, candidates: h ? BL.candidates(h) : null }; }),
    wallets: ['0xAbCdEf0123456789aBcDeF0123456789AbCdEf01', 'TQ7xM6hYpCzD8vNp1qJ3kR5sW9uL2aBcDe', 'BC1QAR0SRRR7XFKVY5L643LYDNW9RE59GTZZWF5MDQ', '1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa']
      .map((a) => ({ input: a, key: BL.walletKey(a) }))
  };
  return out;
}

function render() {
  const out = build();
  const files = {};
  for (const k of Object.keys(out)) files[k + '.json'] = JSON.stringify(out[k], null, 1) + '\n';
  return files;
}

if (require.main === module) {
  fs.mkdirSync(DIR, { recursive: true });
  const files = render();
  for (const f of Object.keys(files)) fs.writeFileSync(path.join(DIR, f), files[f]);
  console.log('wrote', Object.keys(files).map((f) => 'tests/fixtures/' + f).join(', '));
}
module.exports = { render, DIR };
