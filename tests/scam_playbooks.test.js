'use strict';
// 骗子参考话术（scam_playbooks.json）：格式、阶段标签、出处类型、占位符；site 与 voice/static 两份一致。
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const ROOT = path.join(__dirname, '..');
const SITE = path.join(ROOT, 'site/assets/core/scam_playbooks.json');
const VOICE = path.join(ROOT, 'voice/static/scam_playbooks.json');
const PB = JSON.parse(fs.readFileSync(SITE, 'utf8'));
const SS = JSON.parse(fs.readFileSync(path.join(ROOT, 'site/assets/core/scam_scripts.json'), 'utf8'));
const SC = JSON.parse(fs.readFileSync(path.join(ROOT, 'site/assets/core/scenarios.json'), 'utf8'));
const SOURCES = ['反诈中心通报改写', '裁判文书改写', 'TeleAntiFraud 数据集改写'];

// 场景 id → scam_scripts.json 的类型：按 types[].simScenarios
function typeFor(key) {
  return SS.types.find((t) => (t.simScenarios || []).includes(key));
}

test('scam_playbooks：site/assets/core 与 voice/static 两份内容完全相同', () => {
  assert.equal(fs.readFileSync(VOICE, 'utf8'), fs.readFileSync(SITE, 'utf8'));
});

test('scam_playbooks：覆盖语音页下拉里的全部场景，键名合法', () => {
  assert.equal(PB.version, 1);
  const ids = SC.scenarios.map((s) => s.id);
  assert.deepEqual(Object.keys(PB.scenarios).sort(), ids.slice().sort(), '场景键名 = 语音页下拉 id');
});

test('scam_playbooks：每场景 3–5 步，每步 goal / 2–3 句 lines / 出处类型，stage 在 scam_scripts.json 中存在', () => {
  const allStages = new Set(SS.types.flatMap((t) => t.stages.map((s) => s.id)));
  for (const [key, sc] of Object.entries(PB.scenarios)) {
    if (sc.title !== undefined) assert.ok(typeof sc.title === 'string' && sc.title, key);
    assert.ok(Array.isArray(sc.steps) && sc.steps.length >= 3 && sc.steps.length <= 5, key + ' 步数');
    const type = typeFor(key);
    assert.ok(type, key + ' 找不到 scam_scripts 类型');
    const own = new Set(type.stages.map((s) => s.id));
    for (const st of sc.steps) {
      assert.deepEqual(Object.keys(st).filter((k) => !['stage', 'goal', 'lines', 'source'].includes(k)), [], key);
      if (st.stage !== undefined) {
        assert.ok(allStages.has(st.stage), `${key}: stage ${st.stage} 不在 scam_scripts.json`);
        assert.ok(own.has(st.stage), `${key}: stage ${st.stage} 不属于 ${type.id}`);
      }
      assert.ok(typeof st.goal === 'string' && st.goal.trim(), key);
      assert.ok(Array.isArray(st.lines) && st.lines.length >= 2 && st.lines.length <= 3, key + ' lines');
      assert.ok(SOURCES.includes(st.source), key + ' source ' + st.source);
    }
  }
});

test('scam_playbooks：不含真实号码、网址、账户；只用 scam_scripts.json 已有的占位符', () => {
  const ph = new Set(Object.keys(SS.placeholders));
  const raw = fs.readFileSync(SITE, 'utf8');
  assert.ok(!/\d{4,}/.test(raw), '不含长数字');
  assert.ok(!/https?:|www\.|\.(com|cn|top|vip|net)\b/i.test(raw), '不含网址');
  assert.ok(!/@[a-z0-9]/i.test(raw), '不含邮箱');
  assert.ok(!/deepseek/i.test(raw));
  assert.ok(!/[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}]/u.test(raw), '不含 emoji');
  for (const sc of Object.values(PB.scenarios)) for (const st of sc.steps) for (const l of st.lines) {
    for (const m of l.matchAll(/\{([^}]+)\}/g)) assert.ok(ph.has(m[1]), '未知占位符 ' + m[1]);
  }
});

test('scam_playbooks：stageNames.<场景>.<stage> 与 scam_scripts.json 对应类型的 stages[].name 一致', () => {
  const MAP = { refund: 'impersonate_cs', police: 'impersonate_police', boss: 'impersonate_boss', pig: 'pig_butchering',
    task: 'task_rebate', loan: 'loan_credit', campus: 'loan_credit' };
  assert.deepEqual(Object.keys(PB.stageNames).sort(), Object.keys(PB.scenarios).sort());
  for (const [key, typeId] of Object.entries(MAP)) {
    const type = SS.types.find((t) => t.id === typeId);
    assert.ok(type, typeId);
    assert.equal(typeFor(key).id, typeId, key + ' 对应类型');
    const want = Object.fromEntries(type.stages.map((s) => [s.id, s.name]));
    assert.deepEqual(PB.stageNames[key], want, key);
    for (const st of PB.scenarios[key].steps) if (st.stage) assert.ok(PB.stageNames[key][st.stage], key + ' ' + st.stage);
  }
});
