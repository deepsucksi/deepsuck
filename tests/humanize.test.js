'use strict';
// 真人化（humanize.js）：与 Python personas/humanize 逐字一致（tests/fixtures/humanize.json 由本实现生成、pytest 比对），
// 这里测 JS 端自身的不变量：数字串前后不动、错字密度档位、会话级错字映射、标点风格、配合句不接跑题、禁用词。
const test = require('node:test');
const assert = require('node:assert/strict');
const HZ = require('../site/assets/js/humanize.js');
const C = require('../site/assets/core/personas.json');

const T = (t) => (typeof t === 'string' ? t : t.t);
function pool(pid) {
  const p = C.personas.find((x) => x.id === pid);
  const out = [];
  Object.values(p.templates).forEach((l) => l.forEach((t) => out.push(T(t).split('{call}').join('小伙子').split('{intel}').join('卡号尾号3445').split('{ask}').join(''))));
  return out;
}
const EMOJI = /\[[^\]]{1,3}\]|[\u{1F300}-\u{1FAFF}]/gu;
function rate(pid, hw, extra) {
  const lines = pool(pid);
  let typ = 0, n = 0;
  for (let s = 0; s < 30; s++) {
    const h = new HZ.Humanizer(Object.assign({ profile: pid, seed: s, handwriting: hw }, extra || {}));
    for (let i = 0; i < 40; i++) {
      const r = h.apply(lines[(s * 13 + i * 7) % lines.length]);
      r.ops.forEach((o) => { if (o.indexOf('typo:') === 0) typ += Number(o.split(':')[1]); });
      n += HZ.hanCount(r.text.replace(EMOJI, ''));
    }
  }
  return 100 * typ / n;
}

test('王阿姨默认档每百字 2–4 个错字；每百字 10+ 只在 handwriting 打开时', () => {
  const d = rate('wang', false), hw = rate('wang', true);
  assert.ok(d >= 2 && d <= 4, String(d));
  assert.ok(hw >= 10, String(hw));
  assert.equal(new HZ.Humanizer({ profile: 'wang' }).handwriting, false);
  const lin = rate('lin', false);
  assert.ok(lin < d && lin >= 0.6, String(lin));
});

test('会话级错字映射：同一个词一场里只错成一种写法，被指出后照错', () => {
  const h = new HZ.Humanizer({ profile: 'wang', seed: 3, ops: ['typo'], typoPer100: 30 });
  const line = '我已经知道了，手机上的短信我看了，到底是哪个银行？';
  h.apply(line, '快点');
  const snap = Object.assign({}, h.typoMap);
  for (let i = 0; i < 20; i++) h.apply(line, '你打错字了');
  Object.keys(snap).forEach((k) => assert.equal(h.typoMap[k], snap[k]));
});

test('标点风格每个人设固定：王阿姨一逗到底，李大爷 / 小林全不打（数字串旁、“户名”等人名提示词后的原标点不动）', () => {
  for (const [pid, style] of [['wang', 'comma'], ['li', 'none'], ['lin', 'none']]) {
    const h = new HZ.Humanizer({ profile: pid, seed: 2 });
    pool(pid).slice(0, 80).forEach((x) => {
      const out = Array.from(h.apply(x).text), core = HZ.protectedMask(out, C.humanize.confusion.nameCues), fz = HZ.cueFrozen(out);
      out.forEach((ch, i) => {
        if (core[i] || core[i - 1] || core[i + 1] || fz[i] || '，,。！？!?；;：:、…~～'.indexOf(ch) < 0) return;
        if (style === 'comma') assert.ok(ch === '，' || ('？?'.indexOf(ch) >= 0 && (i === out.length - 1 || out[i + 1] === '\n')), out.join(''));
        else assert.fail(pid + ' ' + out.join(''));
      });
    });
  }
});

test('配合类意图不接跑题句；小林没有“打游戏”跑题句', () => {
  for (let s = 0; s < 100; s++) {
    const h = new HZ.Humanizer({ profile: 'wang', seed: s, weights: { digress: 50 } });
    HZ.COOP_INTENTS.forEach((it) => assert.ok(h.apply('好，我照你说的点了', null, it).ops.indexOf('digress') < 0));
  }
  assert.ok(!HZ.resolve('lin').digressions.some((d) => d.indexOf('打游戏') >= 0));
});

test('人设台词、真人化短语池与输出都没有年轻网络用语和美篇体', () => {
  const banned = C.humanize.confusion.bannedStyle.youthSlang.concat(C.humanize.confusion.bannedStyle.essayStyle).map((w) => w.toLowerCase());
  const H = C.humanize;
  const texts = [];
  C.personas.forEach((p) => { texts.push(...pool(p.id)); texts.push(...Object.values(p.asks)); });
  Object.keys(H.profiles).filter((k) => k !== 'comment').concat(['wang', 'li', 'lin']).forEach((k) => {
    const pr = HZ.resolve(k);
    ['digressions', 'ageLines', 'apologies', 'closings', 'emojis', 'selfRef'].forEach((f) => texts.push(...(pr[f] || [])));
  });
  texts.forEach((t) => banned.forEach((w) => assert.ok(t.toLowerCase().indexOf(w) < 0, w + ' in ' + t)));
  ['wang', 'li', 'lin'].forEach((pid) => {
    const h = new HZ.Humanizer({ profile: pid, seed: 9, handwriting: true });
    pool(pid).slice(0, 100).forEach((x) => { const o = h.apply(x, '验证码发我').text.toLowerCase(); banned.forEach((w) => assert.ok(o.indexOf(w) < 0, o)); });
  });
});

// 数字串保护：与 Python personas/tests/test_humanize_elderly.py 同一批用例
const DIGIT_LINES = ['好的，卡号尾号3454对吧？我记下了。', '你说转5000块到6222020200112233445是吧，我找找笔。',
  '那个网址 refund-tb.example 我打不开啊，你再发一遍？', '地址 TQ7xM6hYpCzD8vNp1qJ3kR5sW9uL2aBcDe 太长了，我抄不下来。',
  '电话139****2233是你们的吗？我已经知道了。', '我只有两千块，转一千块行不行？', '6222020200112233445，这个对吧，我已经知道了',
  '你说的是https://refund-tb.example/dl，我点不开。', '尾号3445', '我现在去银行，转5000元，你等我。好的。',
  '验证码我看不清，前两位是12吧，后面的我找找。', '那我转到13900112233这个号上？我先找找眼镜。',
  // 逐字报号的中文数字（可夹空格）、平台名 / 情报字段词（含“微 信”）同等保护
  '我念给你听，幺三九 幺幺 二二三三，你记一下', '卡号是六二二二 零二零二，后面我看不清', '房间号拐洞幺，进去以后呢', '加微 信 kefu，还是支付宝，你说哪个', '幺 三', '零 零 幺 幺'];
function spans(a) {
  const m = HZ.protectedMask(a), out = [];
  for (let i = 0; i < a.length;) { if (m[i]) { let j = i; while (j < a.length && m[j]) j++; out.push([i, j]); i = j; } else i++; }
  return out;
}
test('数字串（号码 / 卡号 / 金额 / 钱包 / 网址）内部与紧挨的前后不插错字、表情、标点，也不拆条', () => {
  for (const pid of ['wang', 'li', 'lin', 'retiree', 'mom', 'graduate', 'shop_owner']) {
    for (const hw of [false, true]) {
      for (let s = 0; s < 25; s++) {
        const h = new HZ.Humanizer({ profile: pid, seed: s, handwriting: hw, weights: { repeat: 3, digress: 3 } });
        h.emojiRate = 0.9; h.splitRate = 0.9;
        DIGIT_LINES.forEach((src) => {
          const a = Array.from(src), out = Array.from(h.apply(src, '转到安全账户 6222020200112233445').text);
          const os = spans(out);
          let k = 0;
          spans(a).forEach(([x, y]) => {
            const frag = a.slice(x, y).join('');
            while (k < os.length && out.slice(os[k][0], os[k][1]).join('') !== frag) k++;
            assert.ok(k < os.length, src + ' => ' + out.join(''));
            const [u, v] = os[k];
            assert.equal(u > 0 ? out[u - 1] : null, x > 0 ? a[x - 1] : null, src + ' => ' + out.join(''));
            assert.equal(v < out.length ? out[v] : null, y < a.length ? a[y] : null, src + ' => ' + out.join(''));
            k++;
          });
        });
      }
    }
  }
});

test('语音模式：户名 / 收款人 / 姓名字段值后面的逗号不删（“户名周杰，农业银行”）；平台名与字段词不写错', () => {
  const lines = ['户名周杰，农业银行，卡号我抄好了', '收款人王建国，开户行建设银行', '姓名张三，电话你再说一遍', '户名：李某某，我记下了'];
  const vals = ['周杰，', '王建国，', '张三，', '李某某，'];
  const words = HZ.PROTECT_WORDS;
  for (const pid of ['wang', 'li', 'retiree', 'shop_owner', 'lin', 'mom']) {
    for (const hw of [false, true]) {
      for (let s = 0; s < 60; s++) {
        const h = new HZ.Humanizer({ profile: pid, seed: s, handwriting: hw, weights: { asr: 3 } });
        h.emojiRate = 0.9; h.splitRate = 0.9;
        lines.forEach((src, i) => {
          const out = h.apply(src).text;
          assert.ok(out.indexOf(vals[i]) >= 0, pid + ' ' + src + ' => ' + out);
          words.forEach((w) => { if (src.indexOf(w) >= 0) assert.ok(out.indexOf(w) >= 0, w + ': ' + out); });
        });
        const t = h.apply('加微 信 kefu，房间号拐洞幺，会议号你再说一遍').text;
        for (const w of ['微 信', '房间号', '会议号', '拐洞幺']) assert.ok(t.indexOf(w) >= 0, w + ': ' + t);
      }
    }
  }
});

test('整条消息只有一小段逐字报的数字（跨回合拆开报号）：后面拼上别的话也原样保留，紧挨处不插东西', () => {
  for (const pid of ['wang', 'li', 'lin', 'retiree']) for (const hw of [false, true]) for (let s = 0; s < 40; s++) {
    const h = new HZ.Humanizer({ profile: pid, seed: s, handwriting: hw, weights: { repeat: 3, digress: 3 } });
    h.emojiRate = 0.9; h.splitRate = 0.9;
    for (const src of ['三三，', '九', '幺两']) {
      const out = h.apply(src, '转到安全账户').text, d = src.replace('，', '');
      assert.equal(out.indexOf(d), 0, src + ' => ' + out);
      const nx = Array.from(out)[Array.from(d).length];
      assert.ok(nx === undefined || nx === '，', src + ' => ' + out);
    }
  }
});
