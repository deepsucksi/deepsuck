/*!
 * DeepSuck — llm.js
 * 可选的大模型引擎（默认关闭）。兼容标准聊天接口（Chat Completions 协议）。
 * 不内置任何服务商的地址和模型名：直连模式由用户在沙盒里填写，服务端代理由 server/index.js 读 .env，
 * 具体怎么配见 docs/QUICKSTART.md。
 * 两种接入方式：
 *   1) proxy  —— 推荐。浏览器调用本项目自带的 server（/api/chat），API Key 只保存在服务器 .env 中；
 *   2) direct —— 浏览器直连（Key 存在本机浏览器，仅适合本地自用；部分服务商不支持跨域）。
 * 隐私：发送给大模型的对话记录在本地已脱敏；模型输出也会再经过安全过滤与脱敏。
 * 任何失败都会自动回退到规则引擎。
 * Apache-2.0
 */
(function (root, factory) {
  var isNode = typeof module === 'object' && module.exports;
  var deps = isNode ? {
    redact: require('./redact.js'), extractors: require('./extractors.js'),
    personas: require('./personas.js'), scenarios: require('./scenarios.js'),
    llmQuirks: require('./llm-quirks.js'), engine: require('./engine.js')
  } : root.DeepSuck;
  var mod = factory(deps);
  if (isNode) module.exports = mod;
  else { root.DeepSuck = root.DeepSuck || {}; root.DeepSuck.llm = mod; }
})(typeof self !== 'undefined' ? self : this, function (D) {
  'use strict';

  // baseUrl / model 留空：直连模式要用户自己填（见 docs/QUICKSTART.md），服务端代理有自己的默认值
  var DEFAULTS = {
    baseUrl: '',
    model: '',
    temperature: 0.9,
    maxTokens: 200
  };

    // 每个拖延意图给大模型的提示（与 Python voice 端共用，见 core/personas.json 的 intentHints）
  var INTENT_HINTS = D.personas.INTENT_HINTS;

  // #4 不抢话：人设只接对方已经说过的话。场景名、描述、后台选的场景都不进提示词；称呼只按对方原话里认出的场景挑，
  // “想要的情报”只列对方已经提到过的话题（词表见 core/scenarios.json 的 heardCues，与 voice/persona.py 共用）。
  var CUES = (D.scenarios && D.scenarios.HEARD_CUES) || { scenes: {}, topics: {} };
  var GOAL_TOPIC = { bank: 'bank', name: 'bank', url: 'url', wallet: 'wallet', phone: 'phone' };
  // 套情报类意图的前提话题（与 voice/persona.py 的 NEEDS_TOPIC 一致）：对方还没提到就退回 generic
  var NEEDS_TOPIC = { elicit_url: 'url', elicit_account: 'bank', elicit_wallet: 'wallet', elicit_contact: 'phone', fake_progress: 'bank' };
  var GOAL_LABEL = { bank: '收款账户', name: '户名', url: '网址或 APP', wallet: '钱包地址', phone: '电话或微信' };
  function cueHits(map, text) {
    var t = String(text || ''), out = [];
    Object.keys(map).forEach(function (k) {
      var m = new RegExp(map[k]).exec(t);
      if (m) out.push({ k: k, at: m.index });
    });
    return out;
  }
  /** 对方原话里认出的场景（按第一次出现的先后） */
  function heardScenes(texts) {
    var out = [];
    (texts || []).forEach(function (t) {
      cueHits(CUES.scenes, t).sort(function (a, b) { return a.at - b.at; }).forEach(function (h) {
        [h.k].concat((CUES.implies || {})[h.k] || []).forEach(function (x) { if (out.indexOf(x) < 0) out.push(x); });
      });
    });
    return out;
  }
  function heardTopics(texts) {
    var out = {};
    (texts || []).forEach(function (t) { cueHits(CUES.topics, t).forEach(function (h) { out[h.k] = 1; }); });
    return out;
  }

  /** heard：对方（骗子）说过的话（字符串数组，已脱敏）。scenario 只用于兼容旧调用，不进提示词。
   * #173：对方没报过的号码、户名一律不提。代称条款（〔〕是什么、怎么说）只在对方的话里真有〔〕代称时才加，举的说法只举出现过的那几种；
   * 对方没报过号码 / 户名时，提示词里不出现“那个号”“那个名字”（规则里举的这类说法整段去掉，见 dropUnheard）。 */
  function systemPrompt(persona, scenario, hint, missing, heard) {
    var scenes = heardScenes(heard), topics = heardTopics(heard), refs = heardRefs(heard);
    var call = '';
    scenes.some(function (x) {
      var c = (persona.call && persona.call[x]) || '';
      // 称呼本身会带出对方还没说的场景（例如“客服”）就不用
      call = c && heardScenes([c]).every(function (y) { return scenes.indexOf(y) >= 0; }) ? c : '';
      return !!call;
    });
    if (NEEDS_TOPIC[hint] && !topics[NEEDS_TOPIC[hint]]) hint = 'generic';
    if (hint === 'confirm_intel' && !Object.keys(refs).length) hint = 'generic'; // #173：对方什么都没报过，没有可复述的
    var want = (missing || []).filter(function (g) { return GOAL_TOPIC[g] && topics[GOAL_TOPIC[g]]; })
      .map(function (g) { return GOAL_LABEL[g] || g; });
    var kinds = REF_ORDER.filter(function (k) { return refs[k]; });
    return [
      '你在一个反诈骗研究沙盒中扮演"潜在受害人"角色，与扮演骗子的人对话。目标：尽可能拖延对方时间；对方自己报出来的东西，再顺着让对方说清楚。',
      '角色：' + persona.name + '，' + persona.tagline + '。' + (call ? '称呼对方为"' + call + '"。' : '先不用称呼对方。'),
      '你不知道对方来找你干什么，只接对方已经说过的话；对方没提到的事一概不先提，也不要猜对方的目的。',
      // #173：原来写“对方已经提到、但还没说清楚的：户名”，模型读成对方报过户名
      '本轮建议策略：' + dropUnheard(INTENT_HINTS[hint] || INTENT_HINTS.generic, refs) + '。' + (want.length ? '对方还没报过的：' + want.join('、') + '，要问就直接问对方要。' : ''),
      '硬性规则：',
      '1. 只用简体中文口语，一次回复 1–2 句，像随手打字那样短，一般十来个字，最多 30 字；人设平时的口头禅、“…”和打字习惯照常留着，不用把话说全；保持人设，不要出戏，不要说自己是 AI。',
      '2. 绝不提供任何真实或看似真实的验证码、卡号、密码、身份证号、地址；需要时就说找不到、没弄好、要再确认一下。',
      '3. ' + D.personas.TRANSFER_CLAIM.rule, // #187：与语音硬性规则 4 同一句；不举“转完了”“我先转”这类原话，免得模型照着说
      '4. ' + UNSAID_RULE + (kinds.length ? '对话里〔〕括起来的是对方发过的信息的代称（原文已隐去），这次有：' +
        kinds.map(function (k) { return '〔' + UR.phrase[k] + '〕'; }).join('') + '。提到时用自然说法“' +
        kinds.map(function (k) { return UR.phrase[k]; }).join('”“') + '”，不要照抄〔〕，不要写星号，名字、号码里没看到的部分不要补也不要照念，也不要自己编号码。' : ''),
      '6. 嘴上不说任何数字串：对方报过的验证码、卡号、电话也不重复，开头几位、尾号、汉字写的数字都算；最多含糊地说“好像是…开头的”“后面几位没听清”，顶多带一个单独的数字。',
      '5. 复述对方的话只说两三个字的关键短语，不要整句或半句引用对方原话。',
      '7. ' + dropUnheard(D.personas.NAME_RULE, refs),
      '8. 每条回复的第一句不要拿对方的词加问号反问（不要“报纸？”“会员？”“哪个？”这种开头）：先接对方一个词，词后面用逗号或“…”接几个字；要问的放到第二句。对方提到转账、卡号、户名、验证码这类要求时，先犹豫或起疑（像“啊？要卡号干啥”），同一句里不要马上反问卡号或户名；整条回复也不要只有一句短问话（不要“哪家？”“同学…哪个班的？”这种），先说几个字自己的话，再问。前面说过的意思（没听懂、要再看看、在弄了）不要每条都重复。'
    ].join('\n');
  }

  /* ---------- 打码值 → 自然说法 ----------
   * 发给模型的对话是脱敏后的（打码值带 * 或 ...）。模型照抄打码值，骗子看到星号就知道对面是机器人。
   * 发送前把打码值换成〔你发的那个网址〕之类的代称；模型输出里若仍有打码值（或模型自己说了号码被脱敏），
   * 也换成自然说法。姓名一律说“那个名字”（#130），号码一律说“你发的那个号”（#121：不带出尾号），不碰原文，不改脱敏规则。 */
  // 打码值：含 * 的连续非空白串（可夹在数字间的空格，如 6222 **** **** 7890），或 TQ7x...BcDe 这种中间省略的钱包地址
  var MASKED_RE = /(?:[A-Za-z0-9]+…)?(?:[0-9]{2,6}[ \u00a0](?=[*＊]))*[A-Za-z0-9_.:\/@+#?=&%~\-]*[*＊][A-Za-z0-9_.:\/@+#?=&%~\-*＊]*(?:[ \u00a0][0-9*＊]+)*|[A-Za-z0-9]{2,}\.\.\.[A-Za-z0-9]{2,}/g;
  // 打码姓名（#130，与 engine.vagueDigits、语音端 #137 同一规则）：张**、王*明（中间打码整段吃掉）、欧阳**，前面的“姓”一并换掉；
  // 统一说“那个名字”（原来是“姓X的那个人”，“王*明”会剩下“〔姓王的那个人〕明”）
  var NDE = D.personas.DIGIT_ECHO;
  // #157：拆字报姓的说法（耳东陈***）一起换掉；拆字说法读 extractors.json 的 nameRules.split（与 engine.vagueDigits 同一份）
  var SPL = D.personas.SPLIT_NAME;
  var SPLIT_PRE = '(?:(?:' + SPL.spellings.slice().sort(function (a, b) { return b.length - a.length; })
    .map(function (x) { return x.slice(0, -1).replace(/[.*+?^${}()|[\]\\]/g, '\\$&'); }).join('|') + ')' + SPL.link + ')';
  var SPLIT_BEFORE_NAME = new RegExp(SPLIT_PRE + '(?=〔?' + NDE.name + ')', 'g');
  // #222 后续（同 #228）：星号后面紧跟数字（阿拉伯或中文）/ 金额词时不当残名（「转给李*五百块」「汇给张*三万块」不吞「五」「三」），与 refs._NUM_TAIL_GUARD 一致
  var NUM_TAIL_GUARD = '(?![0-9０-９]|[零一二两三四五六七八九十几][零一二两三四五六七八九十百千万亿块元]|[百千万亿块元])';
  // #222 后续（同 #228）：打码姓名后面紧跟 1–5 位阿拉伯数字的金额（「转给李*500」「李**500块」）仍算姓名，不当号码。与 refs._AMOUNT_AFTER 一致
  var AMOUNT_AFTER = '(?=[0-9０-９]{1,5}(?:\.[0-9]{1,2})?(?:块钱|块|元|万|千|百)?(?![0-9０-９A-Za-z*＊]))';
  var NAME_MASK_RE = new RegExp(SPLIT_PRE + '?(姓)?(' + NDE.compoundSurnames.join('|') + '|[\u4e00-\u9fff])' +
    '(?:[*＊](?:' + NUM_TAIL_GUARD + '(?![' + NDE.nameTailStop + '])[\u4e00-\u9fff](?![*＊]))?(?:(?![0-9A-Za-z*＊])|' + AMOUNT_AFTER + ')|[*＊]{2,4}(?:(?![0-9A-Za-z*＊])|' + AMOUNT_AFTER + ')' +
    '(' + NUM_TAIL_GUARD + NDE.maskedNameTail + '(?![*＊0-9A-Za-z]))?)', 'g');
  // #216 P0：姓和星号之间夹空格 / 分隔符（「张 * *」「张·*·*」「李 - * 」）先收拢成「张**」；号码里的分隔（「138 **** 1234」）不动。与 refs.collapse_spaced_stars 一致
  var SEP = NDE.spacedStarsSep;
  var SPACED_STARS_RE = new RegExp('(?<![0-9A-Za-z０-９])([\u4e00-\u9fff])((?:' + SEP + '*[*＊]){1,4})(?=' + SEP + '*(?:[^0-9A-Za-z０-９*＊' + SEP.slice(1, -1) + ']|$))', 'g');
  var SEP_RE = new RegExp(SEP);
  // #220：金额前的带空格星号（「剩余 * * 块」）先收拢成连续星号，再走金额规则。与 refs._SPACED_AMOUNT 一致
  var SPACED_AMOUNT_RE = new RegExp('(?<![0-9A-Za-z０-９*＊])[*＊](?:' + SEP + '*[*＊]){0,3}' + SEP + '*(?=块钱|块|元)', 'g');
  function collapseSpacedStars(text) {
    return String(text || '').replace(SPACED_AMOUNT_RE, function (m) { return m.replace(/[^*＊]/g, ''); }).replace(SPACED_STARS_RE, function (m, lead, stars) { return SEP_RE.test(stars) && NDE.notSurname.indexOf(lead) < 0 ? lead + stars.replace(/[^*＊]/g, '') : m; }); // 星号前那个字基本不当姓（「我在 *上班」「密码 * * *」）时不收拢
  }
  // #216 P0：星号后紧跟的残名（「是**明吗」「，**明？」）整段算名字；星号前不是汉字时（逗号、句首）也是名字。与 refs.py 一致
  var STARS_NAME_TAIL_RE = new RegExp('(?<![0-9A-Za-z０-９*＊\u4e00-\u9fff])[*＊]{1,4}' + NUM_TAIL_GUARD + NDE.maskedNameTail + '(?![*＊0-9A-Za-z０-９])', 'g');
  // #216：已经是「那个名字」、后面紧跟的星号（「那个名字***是吧」）一并去掉，不把「字」当姓
  var STARS_AFTER_NAME_RE = new RegExp('(〔?' + NDE.name + '〕?)\\s*[*＊]+(?:' + NUM_TAIL_GUARD + NDE.maskedNameTail + ')?(?![*＊0-9A-Za-z０-９])', 'g');
  // #158：逐字解释（「晓是知晓的晓」）整段打成 *，紧跟在打码姓名后面时算这个名字的一部分（与 engine.vagueDigits 的 MERGE_N 一致），不当成号码
  var NAME_TAIL_RE = new RegExp('(〔?' + NDE.name + '〕?)(?:[ \u3000…,，、.．·~～\\-—]{1,2}[*＊]+(?![0-9A-Za-z*＊]))+', 'g');
  // #172：逐字解释整段打成纯星号、前面没有打码姓名时（「弓长张，****」「伟是****」「****，****」）也是名字，念“那个名字”，不当号码。
  // 规则见 personas.json 的 unsaidRefsComment；python/deepsuck/refs.py 同一套正则（tests/fixtures/redact.json charExplain 两端都跑）。
  var UR = D.personas.UNSAID_REFS, EXP = D.personas.CHAR_EXPLAIN;
  var reEsc = function (x) { return x.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'); };
  var HAN = '[\u4e00-\u9fff]';
  var NOT_NEAR = '0-9A-Za-z_.:\\/@+#?=&%~\\-*＊';
  // 纯星号串（可用逐字解释的 sep 连成一串）：两边不贴数字、字母、星号，也不隔一个空格贴数字（6222 **** **** 7890 是卡号）
  var STAR_CHAIN = '(?<![' + NOT_NEAR + '])(?<![0-9A-Za-z]\\s)[*＊]+(?:' + EXP.sep + '(?:就是)?[*＊]+)*(?![' + NOT_NEAR + '])(?!\\s[0-9A-Za-z])';
  var SPLIT_FULL = '(?:' + SPL.spellings.slice().sort(function (a, b) { return b.length - a.length; })
    .map(function (x) { return reEsc(x.slice(0, -1)) + SPL.link + reEsc(x.slice(-1)); }).join('|') + ')';
  var SEEN_EXPLAIN = '(?:(?:就是|是)?' + HAN + '{1,4}' + EXP.link + HAN + EXP.tail + ')'; // 「立早章，文章的章，****」里没打码的那段
  var LEAD_CHAR = '(?<![^\\s，,、。！？!?；;…:：])(?![' + NDE.notSurname + UR.notLead + '])' + HAN + '字?(?:就是|是)';
  var EXPLAIN_NAME_RE = new RegExp('(?:' + SPLIT_FULL + '(?:' + EXP.sep + SEEN_EXPLAIN + ')?' + EXP.sep + '(?:就是|是)?|' + LEAD_CHAR + ')' + STAR_CHAIN, 'g');
  var BARE_STARS_RE = new RegExp(STAR_CHAIN, 'g');
  var CLAUSE_SEP = '，,。；;！？!?\n';
  var NUMBER_CUE = new RegExp('[0-9０-９]|' + UR.numberCue);
  var NAME_DUP_RE = new RegExp('(〔?' + NDE.name + '〕?)(?:' + EXP.sep + '(?:就是|是)?〔?' + NDE.name + '〕?)+', 'g');
  // 打码金额（「****块钱」「**元」）：1-4 个星号后接 块/块钱/元，念量词说法，heardRefs 记 number（不当姓名）。
  // 说法是台词，待审批；与 refs.py AMOUNT_PHRASE / _AMOUNT_STARS 一致
  var AMOUNT_PHRASE = '那么点';
  var AMOUNT_STARS_RE = /(?<![0-9A-Za-z*＊])[*＊]{1,4}(?:块钱|块|元)/g;
  var AMOUNT_NAME_LEAD = /(?:叫|姓)\s*[:：]?\s*$/;
  // 单字姓前面是句首 / 标点 / 空白，或姓名语境词，才算姓名（「剩余**块」「这包**块」的 余/包 不是姓）。与 refs._AMOUNT_SURNAME_LEAD 一致
  var AMOUNT_SURNAME_LEAD = /(?:^|[\s\p{P}\p{S}]|(?:叫|姓|户名|收款人|付款人|联系人|对方|名字|姓名|转给|打给|汇给|给)\s*[:：]?\s*)$/u;
  // #220 复审：号码语境（numberBefore）、姓名语境（nameBefore / nameAfter、「叫 / 姓」、星号前是常见姓或复姓）优先，不按金额算。与 refs._amount_skip 一致
  // #220 负责人定：字段词（收款人 / 户名 / 姓名 / 账户名 / 开户名 / 收款户名 / 开户户名）一个字都不吃，后面「（姓）+ 星号 + 尾字」整段换成「那个名字」，不留尾巴：
  // 「户名*元」「收款人马**元」「户名**明」→「字段词那个名字」；后面是数字 / 金额（「姓名*五百块」「户名李*500」）原样保留；「元宝」这类词也原样保留（「收款人那个名字元宝」）。与 refs._LABEL_STARS_YUAN 一致
  var LABEL_END = '(?:(?![\\u4e00-\\u9fff])|(?=[了吧吗呢啊呀的]))';
  var LABEL_STARS_YUAN_RE = new RegExp('(收款户名|开户户名|账户名|开户名|收款人|户名|姓名)(\\s*[:：]?\\s*)(?:' + NDE.compoundSurnames.join('|') + '|[' + D.extractors.SURNAMES + '])?[*＊]{1,4}' +
    '(?:(?:块钱|块|元)' + LABEL_END + '|' + NUM_TAIL_GUARD + '(?:' + NDE.maskedNameTail + ')' + LABEL_END + ')?', 'g');  function amountSkip(str, pos) {
    var pre = str.slice(0, pos), X = D.extractors;
    if (X.starsName(str, pos) || X.starsNotName(str, pos) || AMOUNT_NAME_LEAD.test(pre)) return true;
    return !!pre && ((X.SURNAMES.indexOf(pre.slice(-1)) >= 0 && AMOUNT_SURNAME_LEAD.test(pre.slice(0, -1))) || NDE.compoundSurnames.some(function (c) { return pre.slice(-c.length) === c; }));
  }
  function maskedPhrase(tok) {
    var t = String(tok);
    if (/[A-Za-z0-9]\.\.\.[A-Za-z0-9]/.test(t) && !/[*＊]/.test(t)) return '你发的那个钱包地址';
    if (/@/.test(t) && !/:\/\//.test(t)) return '你发的那个邮箱';
    if (/:\/\/|^www\.|\.[A-Za-z*＊]{2,}(?:[\/?#]|$)/i.test(t) && !/^[0-9*＊ .\-]+$/.test(t)) return '你发的那个网址';
    return '你发的那个号';
  }
  /** 只换打码姓名（#130 / #157）：要在再跑一遍 redactText 之前做，否则“耳东陈***”会被再打成“耳*****”、当成号码 */
  function maskNames(text, bracket) {
    var w = bracket ? '〔' + NDE.name + '〕' : NDE.name;
    var amount = bracket ? '〔' + UR.phrase.number + '〕' : AMOUNT_PHRASE;
    // #201：星号前的字是不是姓先查共用字表 core/name_stopchars.json（「有****」不是姓，「和*」「姓*」照样当姓名），不在表里的再看 notSurname
    // #163 复审：拆字报姓、逐字解释、偏旁说法连同前面的姓名整体换成「那个名字」（与语音出口 drop_name_explain 对齐）
    if (D.redact.sayNames) text = D.redact.sayNames(text, D.extractors.extractSensitive(String(text || '')), w);
    var s = collapseSpacedStars(text) // 1) 先合并带空格的星号
      .replace(LABEL_STARS_YUAN_RE, function (m, lab, sp) { return lab + sp + w; })
      .replace(AMOUNT_STARS_RE, function (m, off, str) { return amountSkip(str, off) ? m : amount; }) // 2) 打码金额先换，免得「剩*块」被当成姓名
      .replace(STARS_AFTER_NAME_RE, '$1') // 3) #221 姓名规则
      .replace(NAME_MASK_RE, function (m, xing, sur, tail, off, str) {
        // #216：残名（tail）不算「星号后跟着字」，只拿姓 + 星号这一段判断
        return D.extractors.maskedLeadNotSurname(tail ? m.slice(0, m.length - tail.length) : m, sur, off, str, NDE.notSurname) ? m : w;
      })
      .replace(STARS_NAME_TAIL_RE, function (m, off, str) { return D.extractors.starsNotName(str, off) ? m : w; })
      .replace(SPLIT_BEFORE_NAME, '')
      .replace(NAME_TAIL_RE, '$1')
      .replace(EXPLAIN_NAME_RE, w); // #172
    // #172：没有数字和号码字样时，单独的纯星号串也是逐字解释的名字。#214：按逗号、句号等分段看号码字样（「卡号是***，户名***」后一段是姓名）；
    // #206 第六条探针：号码语境（「转到***」）和「我在***上班」除外，「转到**名下」「打到**的卡上」一律是姓名。与 refs.mask_names 一致
    s = s.replace(BARE_STARS_RE, function (m, off, str) {
      if (D.extractors.starsNotName(str, off)) return m;
      if (D.extractors.starsName(str, off)) return w;
      var a = 0, b = str.length, i;
      for (i = off - 1; i >= 0; i--) if (CLAUSE_SEP.indexOf(str[i]) >= 0) { a = i + 1; break; }
      for (i = off + m.length; i < str.length; i++) if (CLAUSE_SEP.indexOf(str[i]) >= 0) { b = i; break; }
      return NUMBER_CUE.test(str.slice(a, b)) ? m : w;
    });
    return s.replace(NAME_TAIL_RE, '$1').replace(NAME_DUP_RE, '$1');
  }
  /** 把文本里的打码值换成自然说法；bracket=true 时加〔〕（给模型看的代称） */
  function speakMasked(text, bracket) {
    var wrap = function (p) { return bracket ? '〔' + p + '〕' : p; };
    var s = maskNames(text, bracket);
    s = s.replace(MASKED_RE, function (m) {
      var lead = m.match(/^[\s]*/)[0];
      return lead + wrap(maskedPhrase(m.trim()));
    });
    if (!bracket) {
      s = s.replace(/[〔〕]/g, '');
      // 打码值被引号括着时，换成自然说法后去掉这对引号（“你发的那个网址”不需要引号）
      s = s.replace(/["“「『]\s*(你发的那个(?:网址|号|钱包地址|邮箱)|那个名字)\s*["”」』]/g, '$1');
    }
    return s.replace(/[*＊]+/g, '');
  }

  /* ---------- #173：对方报过哪几种（代称），没报过的说法不进提示词 ---------- */
  var UNSAID_RULE = UR.rule; // 语音 voice/persona.py 的 UNSAID_RULE 同一句
  var REF_ORDER = ['name', 'number', 'url', 'wallet', 'email'];
  var REF_KIND = {};
  REF_ORDER.forEach(function (k) { REF_KIND[UR.phrase[k]] = k; });
  /** 对方的话（已脱敏）里出现过的代称种类：{ name: 1, number: 1, ... }。和 buildMessages 一样先换打码姓名、再脱敏、再换代称。 */
  function heardRefs(heard) {
    var out = {};
    (heard || []).forEach(function (t) {
      var s = maskNames(String(t || ''), true);
      s = D.redact.redactText(s, D.extractors.extractSensitive(s));
      (speakMasked(s, true).match(/〔[^〔〕]+〕/g) || []).forEach(function (m) {
        var k = REF_KIND[m.slice(1, -1)];
        if (k) out[k] = 1;
      });
    });
    return out;
  }
  var QUOTED_RE = /“[^“”]*”/g;
  /** 规则、建议策略里举的说法（引号括起来的），含对方没报过的那种代称（unsaidRefs.kinds）的整段去掉，再把剩下的标点理顺。
   * 与 python/deepsuck/refs.py 的 drop_unheard 逐字一致。 */
  function dropUnheard(text, refs) {
    var gone = [];
    Object.keys(UR.kinds).forEach(function (k) { if (!refs[k]) gone = gone.concat(UR.kinds[k]); });
    var s = String(text || '').replace(QUOTED_RE, function (q) {
      return gone.some(function (w) { return q.indexOf(w) >= 0; }) ? '\u0001' : q;
    });
    UNHEARD_TIDY.forEach(function (x) { s = s.replace(x[0], x[1]); });
    return s;
  }
  // 去掉的说法先换成 \u0001，只理顺它旁边的标点：“只说‘那个名字’或‘户名没记全’”→“只说‘户名没记全’”，
  // “要提就说‘你说的那个号’‘那张卡’，最多…”→“最多…”，“说‘那个名字’‘那个号’；”→“；”
  var UNHEARD_TIDY = [
    [/\u0001(?:[、或]?\u0001)*/g, '\u0001'],
    [/[、或]\u0001/g, ''],
    [/\u0001[、或]/g, ''],
    [/[，,](?:要提就说|就说|只说|比如|说)\u0001(?=[；;。，,）)]|$)/g, ''],
    [/(?:要提就说|就说|只说|比如|说)\u0001(?:[，,]|(?=[；;。）)]|$))/g, ''],
    [/[（(]像\u0001[）)]/g, ''],
    [/\u0001/g, '']
  ];

  // 引号对：开 → 合；ASCII 双引号按出现顺序两两配对
  var QUOTE_PAIRS = { '“': '”', '「': '」', '『': '』', '‘': '’' };
  var QUOTE_CLOSE = { '”': '“', '」': '「', '』': '『', '’': '‘' };
  var QUOTE_MAX = 8; // 引号里只留关键短语（≤8 字）；更长的半句引用去掉引号
  /** 引号配对：去掉单边引号；引号里超过 8 个字、为空或含省略号的引用去掉引号只留文字 */
  function fixQuotes(text) {
    var a = Array.from(String(text || ''));
    var drop = {}, stack = [], dq = -1;
    for (var i = 0; i < a.length; i++) {
      var c = a[i];
      if (QUOTE_PAIRS[c]) stack.push(i);
      else if (QUOTE_CLOSE[c]) {
        var k = stack.length ? stack[stack.length - 1] : -1;
        if (k >= 0 && a[k] === QUOTE_CLOSE[c]) { stack.pop(); judge(k, i); } else drop[i] = 1;
      } else if (c === '"') {
        if (dq < 0) dq = i; else { judge(dq, i); dq = -1; }
      }
    }
    stack.forEach(function (k) { drop[k] = 1; });
    if (dq >= 0) drop[dq] = 1;
    function judge(o, e) {
      var inner = a.slice(o + 1, e).join('');
      if (!inner.trim() || e - o - 1 > QUOTE_MAX || /…|\.\.\./.test(inner)) { drop[o] = 1; drop[e] = 1; }
    }
    return a.filter(function (_, j) { return !drop[j]; }).join('');
  }

  /** 将会话转为 OpenAI messages（transcript 中的 text 必须已脱敏） */
  function buildMessages(opts) {
    var persona = D.personas.BY_ID[opts.persona] || D.personas.PERSONAS[0];
    var scenario = D.scenarios.BY_ID[opts.scenario] || D.scenarios.SCENARIOS[0];
    var heard = (opts.transcript || []).filter(function (m) { return m.role !== 'bot'; })
      .map(function (m) { return String(m.text || '').slice(0, 600); });
    var msgs = [{ role: 'system', content: systemPrompt(persona, scenario, opts.hint, opts.missing, heard) }];
    (opts.transcript || []).slice(-16).forEach(function (m) {
      var text = String(m.text || '').slice(0, 600);
      text = maskNames(text, true); // #157：已打码的姓名先换掉，免得双保险再打一遍变成号码
      text = D.redact.redactText(text, D.extractors.extractSensitive(text)); // 双保险
      text = speakMasked(text, true); // 打码值换成〔代称〕，模型不会照抄星号
      msgs.push({ role: m.role === 'bot' ? 'assistant' : 'user', content: text });
    });
    return msgs;
  }

  /** 模型输出安全过滤：去掉长数字串（防止"编造验证码/卡号"）、脱敏、截断 */
  /* ---------- 口语化（#132、#134，配置在 personas.json 的 replyPolish；与 Python deepsuck.engine.polish_reply 逐字一致）----------
   * 书面词换成口语说法；第一句是快速反问（去标点不超过 quickQuestionMax 个字）且后面还有话时，问号换成逗号。 */
  var RP = D.personas.REPLY_POLISH;
  var RP_FIRST = /^(\s*)([^。？?！!；;\n]*?)([？?]+)/;
  var RP_PUNCT = /[…。？?！!，,、；;.\s~～]/g;
  function polishReply(text) {
    var s = String(text || '');
    RP.formal.forEach(function (p) { s = s.split(p[0]).join(p[1]); });
    for (var i = 0; i < 3; i++) { // “啊？衣服？我好像没收到”：换掉一个，第一句可能还是快速反问
      var m = s.match(RP_FIRST);
      if (!m) break;
      var core = m[2].replace(RP_PUNCT, ''), rest = s.slice(m[0].length);
      var n = Array.from(core).length;
      if (!(n > 0 && n <= RP.quickQuestionMax && rest.replace(RP_PUNCT, ''))) break;
      s = m[1] + m[2].replace(/…+$/, '') + '，' + rest.replace(/^[…，,]+/, '').replace(/^\s+/, '');
    }
    return thinEllipsis(s);
  }
  // FNV-1a 32 位（按 UTF-16 码元，与 Python _fnv 一致）
  function fnv(t) {
    var h = 0x811c9dc5;
    for (var i = 0; i < t.length; i++) { h ^= t.charCodeAt(i); h = Math.imul(h, 0x01000193) >>> 0; }
    return h >>> 0;
  }
  // #131：带“…”的句子按 ellipsisKeepPct 确定性地留一部分，其余句子的“…”换成逗号（句首去掉、句尾换句号），结巴不动
  var RP_SENT = /[^。？！?!；;\n]+[。？！?!；;]*|\n+/g;
  function thinEllipsis(s) {
    return (s.match(RP_SENT) || []).map(function (sent) {
      if (!/…+|\.{3,}/.test(sent) || fnv(sent) % 100 < RP.ellipsisKeepPct) return sent;
      return sent.replace(/…+|\.{3,}/g, function (g, a) {
        var b = a + g.length, prev = a ? sent[a - 1] : '', nxt = b < sent.length ? sent[b] : '';
        if (prev && prev === nxt) return g;
        if (!prev.trim() || '，,、'.indexOf(prev) >= 0) return '';
        if (!nxt) return '。';
        if ('。？！?!；;，,、'.indexOf(nxt) >= 0) return '';
        return '，';
      });
    }).join('');
  }

  function sanitizeReply(text) {
    var s = String(text || '').replace(/<think>[\s\S]*?<\/think>/g, '').trim();
    // 整句被一对引号包住时才去掉这对引号（原来无条件去掉开头的“，句首是引用时会留下单边的”）
    var w = s.match(/^\s*(["“「])([\s\S]*)(["”」])\s*$/);
    if (w && (w[1] === '"' ? w[3] === '"' : QUOTE_PAIRS[w[1]] === w[3]) && !/["“”「」]/.test(w[2])) s = w[2];
    if (D.engine && D.engine.holdTransfer) s = D.engine.holdTransfer(s); // #187：说成已经转了 / 答应去转的分句换成“还在弄，没弄好”（在姓名替换、数字过滤之前）
    s = maskNames(s, false); // #157：模型照抄的打码姓名先换掉，再脱敏
    s = D.redact.redactText(s, D.extractors.extractSensitive(s));
    s = speakMasked(s, false); // 打码值（模型照抄的或刚脱敏的）换成自然说法，回复里不出现星号
    s = s.replace(/(?<![\d*])\d{5,}(?![\d*])/g, '……');
    if (Array.from(s).length > 160) s = Array.from(s).slice(0, 160).join('') + '……';
    s = fixQuotes(s);
    s = polishReply(s); // #132、#134
    return s.trim();
  }

  function withTimeout(ms) {
    if (typeof AbortController === 'undefined') return {};
    var c = new AbortController();
    var h = setTimeout(function () { c.abort(); }, ms);
    if (h && typeof h.unref === 'function') h.unref(); // Node：超时计时器不拖住进程退出
    return { signal: c.signal };
  }

  /**
   * 聊天接口请求体（#166）。思考开关 enable_thinking：
   *  - cfg.enableThinking 是布尔值（服务端代理固定传，默认 false）时原样带上；
   *  - 否则（浏览器直连）只在 llm-quirks.js 认出的服务商（默认开思考的那家）时带 false，其他接口不带，免得被拒绝。
   */
  function requestBody(cfg, messages, base) {
    var model = cfg.model || DEFAULTS.model;
    var body = {
      model: model,
      messages: messages,
      temperature: cfg.temperature != null ? cfg.temperature : DEFAULTS.temperature,
      max_tokens: cfg.maxTokens || DEFAULTS.maxTokens
    };
    var q = D && D.llmQuirks;
    if (typeof cfg.enableThinking === 'boolean') body.enable_thinking = cfg.enableThinking;
    else if (q && q.thinkingOff(model, base)) body.enable_thinking = false;
    return body;
  }

  /** 调用兼容标准聊天接口的大模型（浏览器 direct 模式与 Node 服务端共用） */
  function chatCompletions(cfg, messages) {
    var missing = missingDirectConfig(cfg, { apiKey: false });
    if (missing.length) return Promise.reject(new Error('未配置 ' + missing.join('、') + '（见 docs/QUICKSTART.md）'));
    var base = String(cfg.baseUrl || DEFAULTS.baseUrl).trim().replace(/\/+$/, '');
    var opt = withTimeout(cfg.timeoutMs || 20000);
    return fetch(base + '/chat/completions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + cfg.apiKey },
      body: JSON.stringify(requestBody(cfg, messages, base)),
      signal: opt.signal
    }).then(function (r) {
      if (!r.ok) return r.text().then(function (t) { throw new Error('LLM HTTP ' + r.status + ': ' + t.slice(0, 200)); });
      return r.json();
    }).then(function (j) {
      if (typeof cfg.onUsage === 'function') cfg.onUsage((j && j.usage) || null, messages); // 服务端预算记账
      var c = j && j.choices && j.choices[0] && j.choices[0].message && j.choices[0].message.content;
      if (!c) throw new Error('LLM 返回为空');
      return sanitizeReply(c);
    });
  }

  /** 直连配置缺了哪几项（baseUrl / model / apiKey）；opts.apiKey === false 时不查 Key */
  function missingDirectConfig(cfg, opts) {
    cfg = cfg || {};
    var out = [];
    if (!String(cfg.baseUrl || DEFAULTS.baseUrl || '').trim()) out.push('Base URL');
    if (!String(cfg.model || DEFAULTS.model || '').trim()) out.push('model');
    if (!(opts && opts.apiKey === false) && !String(cfg.apiKey || '').trim()) out.push('API Key');
    return out;
  }

  /**
   * 读取浏览器里已保存的直连配置（localStorage 'deepsuck.llm' 的 JSON 文本或已解析对象）。
   * 已保存的值原样保留（包括以前版本存下的地址和模型名），不清除、不用默认值覆盖；
   * 只在没保存过的字段上用 DEFAULTS。坏 JSON 当作没保存过。
   */
  function restoreDirectConfig(saved) {
    var obj = saved;
    if (typeof saved === 'string') { try { obj = JSON.parse(saved); } catch (e) { obj = null; } }
    var direct = { baseUrl: DEFAULTS.baseUrl, model: DEFAULTS.model, apiKey: '' };
    var engine = 'rule';
    if (obj && typeof obj === 'object') {
      ['baseUrl', 'model', 'apiKey'].forEach(function (k) { if (typeof obj[k] === 'string') direct[k] = obj[k]; });
      if (obj.engine === 'rule' || obj.engine === 'proxy' || obj.engine === 'direct') engine = obj.engine;
    }
    return { engine: engine, direct: direct };
  }

  /** 浏览器端：通过本项目 server 代理 */
  function viaProxy(payload, endpoint) {
    var opt = withTimeout(25000);
    return fetch(endpoint || 'api/chat', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload), signal: opt.signal
    }).then(function (r) {
      return r.json().then(function (j) {
        if (!r.ok || !j.reply) throw new Error(j.error || ('proxy HTTP ' + r.status));
        return sanitizeReply(j.reply);
      });
    });
  }

  return {
    DEFAULTS: DEFAULTS, INTENT_HINTS: INTENT_HINTS,
    missingDirectConfig: missingDirectConfig, restoreDirectConfig: restoreDirectConfig,
    systemPrompt: systemPrompt, heardScenes: heardScenes, heardRefs: heardRefs, dropUnheard: dropUnheard, buildMessages: buildMessages, sanitizeReply: sanitizeReply, polishReply: polishReply,
    speakMasked: speakMasked, collapseSpacedStars: collapseSpacedStars, fixQuotes: fixQuotes,
    chatCompletions: chatCompletions, requestBody: requestBody, viaProxy: viaProxy
  };
});
