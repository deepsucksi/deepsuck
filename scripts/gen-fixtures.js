#!/usr/bin/env node
/*!
 * 生成 tests/fixtures/*.json：以 JS 实现的输出为"金标准"，供 node:test 与 pytest（python/tests）共用。
 * 用法：npm run fixtures   —— 修改 core/*.json 或提取/脱敏逻辑后运行，并检查 diff 是否符合预期。
 * npm test 会检查夹具是否最新；pytest 会检查 Python 实现与夹具逐项一致（测试即规格）。
 * Apache-2.0
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
const CB = require('../site/assets/js/cardbin.js');
const HZ = require('../site/assets/js/humanize.js');

const DIR = path.join(__dirname, '..', 'tests', 'fixtures');
const HEADER = '由 scripts/gen-fixtures.js 从 JS 实现生成（金标准），node 与 pytest 共用；请勿手改，改规则后运行 npm run fixtures。示例数据均为虚构。';

// 验证码按上下文打码（#33）：[文本, 'mask' 应打码 | 'keep' 原样（卡号 / 手机号仍由实体规则打码）]，号码均为虚构
const OTP_CASES = [
  ['您的验证码是472915，5分钟内有效，请勿告诉他人', 'mask'],
  ['472 915', 'keep'],
  ['验证码 472 915', 'mask'],
  ['验证码是 4 7 2 9 1 5', 'mask'],
  ['验证码是…4…7…2…9…1…5', 'mask'],
  ['动态码 472...915', 'mask'],
  ['校验码⋯四七二⋯九一五', 'mask'],
  ['验证码是…幺二三…四五六', 'mask'],
  ['短信码是 4 7 2，9 1 5', 'mask'],
  ['确认码：4729-1530', 'mask'],
  ['OTP: 4729', 'mask'],
  ['your otp is 47291530', 'mask'],
  ['472915是验证码吧？', 'mask'],
  ['验证码收到了。是…472915', 'mask'],
  ['动态密码收到了。你等等。我念…四七…二九…一五', 'mask'],
  ['我验证码找不到了，1234是不是', 'mask'],
  ['验证码 472915 472915', 'mask'],
  ['你的验证码是472915。另外我的工号是8823', 'mask'],
  ['验证码已发送至尾号1234的手机', 'keep'],
  ['验证码发到13800001111了', 'keep'],
  ['验证码发到 138 0000 1111 了', 'keep'],
  ['卡号6222020200112233445，验证码等会给你', 'keep'],
  ['验证码10分钟内有效', 'keep'],
  ['验证码收到了，转了5000元', 'keep'],
  ['金额是5000，验证码还没来', 'keep'],
  ['验证码？订单号A47291', 'keep'],
  ['今天买了 4729 块的东西，验证码呢', 'keep'],
  ['验证码是六位数还是四位数？', 'keep'],
  ['我家门牌号 2046，下午三点到', 'keep'],
  ['尾号1234', 'keep'],
  ['验证码是4位的，卡号后四位是8888', 'keep'],
  ['验证码是多少？我念一下：一二三', 'keep']
];

// #92：同一说话方连续的 ASR 分段（验证码被切成两三段）；mask = 跨段判断后比逐段脱敏多打了码
const OTP_SEG_CASES = [
  [['验证码是 38', '27 15'], 'mask'],
  [['验证码是 38。', '27，', '15'], 'mask'],
  [['你的校验码是三八', '二七', '一五'], 'mask'],
  [['动态码……4 7', '2、9', '1 5'], 'mask'],
  [['短信验证码我念一下啊', '3827 15'], 'mask'],
  [['验证码是三八二', '7 1 5'], 'mask'],
  [['那个验证码', '是 38', '２７１５'], 'mask'],
  [['38 27', '15 这个是验证码吧'], 'mask'],
  [['验证码 472915', '472915'], 'mask'],
  [['验证码是幺二', '三四，五六'], 'mask'],
  [['验证码是 38', '嗯', '27 15'], 'mask'],
  [['验证码收到了吧', '那你先转 3000 元'], 'keep'],
  [['验证码是 38', '明天 27 号'], 'keep'],
  [['验证码发了吗', '尾号 3827 的卡'], 'keep'],
  [['验证码等会儿再说', '金额 5000', '你先转过来'], 'keep'],
  [['我今年 65', '岁了'], 'keep'],
  [['验证码已发送', '下午 3 点', '15 分到'], 'keep'],
  [['38 27', '15'], 'keep'],
  [['验证码发到你手机了', '138 0000', '1111'], 'keep'],
  [['验证码是多少', '我数一下', '一二三'], 'keep'],
  [['验证码收到了', '订单号 A3827', '15'], 'keep'],
  [['验证码是六位的', '这个月花了 3800', '27 块'], 'keep'],
  [['验证码不能说', '我先挂了'], 'keep']
];

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
  '客服电话 800 123 4567，邮箱 kefu.vip@example.com', '户名写钱伟就行', '户名写张3就行', '收款人李4，工商银行 6222020200112233445', '收款人是吴刚吧', '我记一下：网址/域名 re***fu.top，钱包 0x12ab...9f3e，对吗', '“金盾理财”平台 日赚 500 元，下载金盾理财APP',
  '电话 ①③⑨⓪⓪①①②②③③，记好了', '手机 139.0011.2233', '加薇❤信 kefu_tb2026，或者Q扣 2876543210', 'v❤：kefu_tb2026，企鹅 287 654 321', '微信号码是 kefu_tb2026',
  '打开 refund-tb丶example 注册', '网址 refund-tb·example', '收款人姓名：王建国', '账户名字写钱伟', '卡号 ６２２２ ０２０２ ００１１ ２２３３ ４４５', '陆贰贰贰零贰零贰零零壹壹贰贰叁叁肆肆伍', '版本 1.2.3 发布，John·Smith 来了', '100 200 300 元'
];
// 噪声 / 混淆（v0.6）：中文数字夹标点、换行分段、异体字、同音错字、钱包分段
TEXTS.push('卡号 六二二二，零二零二，零零一一，二二三三，四四五', '电话 一三九-零零一一-二二三三', '打 腰三酒 零零腰腰 二二三三',
  '卡号\n6222 0202\n0011 2233 445', '卡号：6222/0202/0011/2233/445', '请把钱转入安全帐户', '帳戶異常，請轉帳到這個賬戶', '银航卡号 6222020200112233445',
  '手机号吗 13900112233', 'ERC20 0x12ab34cd 56ef7890 abcdef12 34567890 abcd9f3e', 'TRC20 TQ7xM6hY pCzD8vNp 1qJ3kR5s W9uL2aBc De',
  '2026.10.18 版本 1.2.3', '转 5000 元到 6222-0202-0011-2233-445', '先转 2000，再转 3000，一共 5000 元', '电话 139 0011 2233 卡号 6222 0202 0011 2233 445');
// 提取器修复（intel/extractor-fixes）：关键词内夹标点、量词「两」、户名边界、句中姓名、非姓名备注（表情写法 JS/Python 坐标不同，另在各自测试里断言）
TEXTS.push('电话 184-2893-2334，微，信 htb_6601', '加微、信：kefu_tb2026', '稍微，信息我晚点发', '微信，kefu_tb2026', '支付，宝 13912345678', 'QQ，2876543210',
  '电话一三九零零一一二二三三两小时后再打', '电话 一三九 零零一一 二二三三 两个小时以后', '卡号六二二二零二零二零零一一二二三三四四五两张卡', '电话一三九零零一一二二三三三小时后',
  '户名周杰农业银行', '户名郑华中国银航', '户名王建国工商银行', '收款人是我们公司财务李强，卡号6222020200112233445', '钱转到李强的账户上就行', '转到王经理的卡上',
  '【示例数据】收款户名只保留姓氏。', '收款人是我的朋友', '微信号码事 wgold_3487', '收款人叫李强找没听清', '户名周杰然后民生银航',
  '电化，幺，八\n六，幺，七，九，五，四，三，八，六', '工号 12345678 分机 139');
// #8 断续句：三点省略 + 空格、座机 / 400 停顿、钱包末段 1 个字符、开奖号码不当座机
TEXTS.push('卡号 6222... 0000... 1234... 5678... 907，户名王某某', '电话一三八...零零一三...八零零零…尾号八零零零', '座机…零二幺…两零零零…零零零零，打这个',
  '客服热线四零零…零零零…幺二三四', 'USDT地址是…TABCD…EFGHJ…KLMNP…QRSTU…VWXYZ…abcdef…ghi', '开奖号码是03、15、22、23、35、47，特别号码是09', '您尾号1234的卡涉嫌洗钱');
for (const sc of S.SCENARIOS) for (const line of sc.samples) TEXTS.push(line);

// 跨回合拼接（同一说话方相邻回合）
const STITCH = [
  ['卡号是 六二二二 零二零二 零零一一', '呃，二二三三 四四五，户名王某某'],
  ['我的电话是一三九 零零一一', '二二三三'],
  ['卡号 6222 0202', '0011 2233', '445'],
  ['转到 6222020200', '112233445 这张卡'],
  ['电话 13900112233', '6222 0202 0011 2233 445 是卡号'],
  ['转 5000', '1390011 2233'],
  ['打这个 139 0011', '不对，138 1234 5678'],
  ['账户 6222 0202 0011 2233', '445 元'],
  ['一会儿再说', '好'],
  ['卡号 6222 0202', '好的', '0011 2233 445'],
  ['验证码 1234', '5678'],
  ['卡号 6217 0012 3456', '7890 123', '电话 139 0011', '2233'],
  // #1：一段本身是 16 位（不过 Luhn）的拆分卡号
  ['卡号是 6221887154833655', '995，户名王某某'],
  ['卡号是 622', '1887154833655995，户名王某某'],
  ['卡号 6222 0202 0011 2233', '445 元'],
  // 手写错字的屏蔽词
  ['房问号 199', '0069 7308 是同事的工好'],
  // #8：断续句（停顿、逐位、跨回合；后半段像手机号；钱包地址分两回合）
  ['卡号是…6222…0000…', '嗯…1234...5678...', '…907…'],
  ['账户…6222…0000…', '然后…138…0013…8007，收款人王某某'],
  ['座机号码…零二幺…两零零零…', '嗯…零零零零'],
  ['用 ERC20 也行：0x0123，456789ab，cdef…', '嗯…0123456789，abcdef01，234567'],
  ['USDT收款地址…TABCDEFGHJKLMNPQRSTUVWX…', '然后…YZabcdefghi'],
  ['工好 151', '0859 5928']
];

const REDACT = [
  ['bank_card', '6222021234561234'], ['bank_card', '62220212345612345'], ['bank_card', '622305123456789012'], ['bank_card', '6222 0212 3456 7890 128'],
  ['bank_card', '6222-0212-3456-7890-128'], ['bank_card', '622202123456789'], ['bank_card', '622202123456'], ['bank_card', '62220212'], ['bank_card', '6222021'], ['bank_card', '1234'],
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
SESSIONS.push({ scenario: 'police', persona: 'wang', seed: 11, lines: ['把钱转到卡号 六二二二 零二零二 零零一一', '呃 二二三三 四四五，户名王某某', '有事打 一三九 零零一一', '二二三三', '记住了吗'] });
SESSIONS.push({ scenario: 'refund', persona: 'wang', seed: 21, lines: ['卡号是 6221887154833655', '995，户名王某某', '房问号 199', '0069 7308 是同事的工好'] });
SESSIONS.push({ scenario: 'refund', persona: 'lin', seed: 22, lines: ['卡号是 622', '1887154833655995，户名王某某', '电话一三九零零一一二二三三两小时后再打'] });
SESSIONS.push({ scenario: 'police', persona: 'zheng', seed: 7, lines: ['我是公安局的', '你涉嫌洗钱', '马上把验证码发我', '不要告诉任何人', '转到安全账户', '你听不懂吗？', '快点', '再不配合就逮捕你'] });

// ---- 真人化（humanize）：JS 与 Python personas/humanize 逐字一致（一个实例 = 一场对话，按顺序调用） ----
const HZ_DIGIT_LINES = ['好的，卡号尾号3454对吧？我记下了。', '你说转5000块到6222020200112233445是吧，我找找笔。', '那个网址 refund-tb.example 我打不开啊，你再发一遍？',
  '地址 TQ7xM6hYpCzD8vNp1qJ3kR5sW9uL2aBcDe 太长了，我抄不下来。', '电话139****2233是你们的吗？我已经知道了。', '我只有两千块，转一千块行不行？', '{call}，我在派出所门口，马上去银行网点。',
  '我念给你听，幺三九 幺幺 二二三三，你记一下', '卡号是六二二二 零二零二，后面我看不清', '房间号拐洞幺，进去以后呢', '加微 信 kefu，还是支付宝，你说哪个', '幺 三', '零 零 幺 幺', '户名周杰，农业银行，卡号我抄好了'];
function hzLines(pid) {
  const p = P.PERSONAS.find((x) => x.id === pid) || P.PERSONAS[0];
  const out = [];
  for (const k of ['generic', 'otp_stall', 'coop_step', 'fake_progress', 'scared', 'tech_trouble', 'slow_walk', 'info_stall']) {
    p.templates[k].slice(0, 2).forEach((t) => out.push([typeof t === 'string' ? t : t.t, k]));
  }
  return out.concat(HZ_DIGIT_LINES.map((t) => [t, null]));
}
function buildHumanize() {
  const ctxs = S.SCENARIOS.map((sc) => sc.samples).reduce((a, b) => a.concat(b), []);
  const configs = [];
  for (const prof of ['retiree', 'mom', 'graduate', 'shop_owner'].concat(P.PERSONAS.map((p) => p.id))) {
    for (const hw of [false, true]) configs.push({ profile: prof, handwriting: hw });
  }
  configs.push({ intensity: 0.5 }, { intensity: 1.0, mode: 'voice', dialect: '西南' }, { intensity: 0.8, mode: 'chat', dialect: '东北', keep: ['周伯'] },
    { intensity: 1.0, ops: ['punct'] }, { intensity: 0.6, typoPer100: 8, punctStyle: 'none' });
  const cases = [];
  configs.forEach((cfg, ci) => {
    for (const sd of [1, 2]) {
      const ids = P.PERSONAS.map((p) => p.id);
      const pid = ids.indexOf(cfg.profile) >= 0 ? cfg.profile : ids[ci % ids.length];
      const h = new HZ.Humanizer(Object.assign({}, cfg, { seed: sd * 7919 + ci }));
      const turns = hzLines(pid).map(([t, intent], i) => {
        const ctx = ctxs[(i * 5 + sd + ci) % ctxs.length];
        const r = h.apply(t, ctx, intent);
        return { input: t, context: ctx, intent: intent, text: r.text, ops: r.ops };
      });
      cases.push({ config: cfg, seed: sd * 7919 + ci, turns: turns, typoMap: h.typoMap });
    }
  });
  return { comment: HEADER, cases: cases };
}

// ---- 生成 ----
function pickEntity(e) {
  const o = { type: e.type, value: e.value, masked: e.masked, start: e.start, end: e.end, sensitive: e.sensitive, meta: e.meta };
  if ('raw' in e) o.raw = e.raw;
  if ('obfuscated' in e) o.obfuscated = e.obfuscated;
  return o;
}

function build() {
  const out = {};
  out.redact = { comment: HEADER, cases: REDACT.map(([type, input]) => ({ type, input, expected: R.mask(type, input) })),
    groups: REDACT.filter(([type]) => type === 'bank_card').map(([, input]) => R.mask('bank_card', input))
      .concat(['622202*********3445', '6222 02** ****', '', '王**', '***3445'])
      .map((input) => ({ input, expected: R.formatCardGroups(input) })),
    otp: OTP_CASES.map(([text, expect]) => {
      const spans = R.findOtpSpans(text);
      const redacted = R.redactText(text, X.extractSensitive(text));
      const masked = redacted !== R.redactText(text, X.extractSensitive(text).concat([{ start: 0, end: text.length, sensitive: false }]));
      if ((expect === 'mask') !== masked) throw new Error('OTP 用例与预期不符：' + text + ' -> ' + redacted);
      return { text, expect, spans, redacted };
    }),
    otpSegments: OTP_SEG_CASES.map(([segments, expect]) => {
      const each = segments.map((t) => R.redactText(t, X.extractSensitive(t)));
      const spans = R.findOtpSpansSegments(each);
      const redacted = R.redactOtpSegments(each);
      if ((expect === 'mask') !== (JSON.stringify(redacted) !== JSON.stringify(each))) {
        throw new Error('跨分段 OTP 用例与预期不符：' + segments.join(' | ') + ' -> ' + redacted.join(' | '));
      }
      return { segments, expect, spans, redacted };
    }) };
  out.normalize = { comment: HEADER, cases: TEXTS.map((text) => { const n = N.normalize(text); return { text, expected: n.text, changed: n.changed }; }) };
  out.extract = {
    comment: HEADER,
    cases: TEXTS.map((text) => {
      const ents = X.extract(text);
      return { text, entities: ents.map(pickEntity), redacted: R.redactText(text, ents) };
    })
  };
  const counts = [{}, { otp: 1 }, { safe_account: 2, otp: 1, urgency: 5 }, { authority: 3, threat: 3, secrecy: 1, transfer: 2 }, { romance: 1 },
    { cs_impersonation: 2, urgency: 3 }, { app_download: 1 }, { app_download: 1, screen_share: 1 }, { kidnap: 1, urgency: 1 }, { urgency: 0, otp: 0 }];
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
      return Object.assign({}, c, { turns, messages: s.messages.map((m) => m.text), intel: s.intelList(), stats: { estimatedScammerSeconds: st.estimatedScammerSeconds, intelCount: st.intelCount, riskScore: st.riskScore } });
    })
  };
  out.stitch = { comment: HEADER, cases: STITCH.map((turns) => ({ turns, expected: X.stitch(turns) })) };
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
  // 银行卡 BIN：虚构卡号（只取前缀判断发卡行），含长度不吻合、过短、未知前缀
  out.cardbin = {
    comment: HEADER,
    cases: ['6222020200112233445', '6217001234567890123', '6225881234567891', '6228480012345678901', '622305123456789012', '6223051234567890',
      '6230 5200 1234 5678 901', '1234567890123456', '62220212', '', '4033611234567890', '6222021234']
      .map((input) => ({ input, expected: CB.lookup(input) }))
  };
  out.humanize = buildHumanize();
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
