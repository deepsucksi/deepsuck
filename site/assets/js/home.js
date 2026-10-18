/*! DeepSuck — home.js：首页 R11 版式的人设轮播、提取结果表与语音演示入口（纯展示，不含业务逻辑）。
 *  台词一律读 hero-chat.js 的 SCRIPTS（正式首页示例对话）；本文件不写任何台词，
 *  唯一例外是没有首页示例的郑老板，用 personas/prompts/shop_owner.yaml 的 sample_lines 原句。Apache-2.0 */
(function () {
  'use strict';
  var SCRIPTS = (window.DeepSuckHero && window.DeepSuckHero.SCRIPTS) || [];
  var $ = function (id) { return document.getElementById(id); };
  var SCENARIO = { '冒充客服': 'refund', '冒充公检法': 'police', '杀猪盘': 'pig', '刷单返利': 'task', '虚假贷款': 'loan', '冒充领导': 'boss', '注销校园贷': 'campus' };
  // 人设 id / 名字取自 personas/prompts/*.yaml
  var CAST = [
    { id: 'retiree', name: '周伯' },
    { id: 'mom', name: '小陈妈妈' },
    { id: 'graduate', name: '小宇' },
    { id: 'shop_owner', name: '郑老板', reply: '你把账户发过来嘛 会计明天来了我让她弄' } // shop_owner.yaml sample_lines[2]
  ];
  function scriptFor(name) {
    for (var i = 0; i < SCRIPTS.length; i++) { var t = String(SCRIPTS[i].title || ''); if (t.slice(-name.length - 3) === ' · ' + name) return SCRIPTS[i]; }
    return null;
  }
  // 主要应答：第一句带情报（i）的骗子台词，以及紧接着的人设回复
  function exchange(sc) {
    var lines = sc.lines || [], k = -1;
    for (var i = 0; i < lines.length; i++) if (lines[i].r && lines[i].i) { k = i; break; }
    if (k < 0) for (i = 0; i < lines.length; i++) if (lines[i].r) { k = i; break; }
    var reply = '';
    for (i = k + 1; i < lines.length; i++) if (lines[i].s) { reply = lines[i].s; break; }
    return { scam: k >= 0 ? lines[k].r : '', reply: reply };
  }
  CAST.forEach(function (c) {
    var sc = scriptFor(c.name);
    if (sc) {
      var ex = exchange(sc);
      c.title = sc.title; c.scam = ex.scam; c.reply = ex.reply; c.source = true;
      c.scenario = SCENARIO[String(sc.title).split(' · ')[0]] || '';
    } else { c.title = c.name; c.scam = ''; c.source = false; c.scenario = ''; }
  });

  var lang = document.documentElement.lang === 'en' ? 'en' : 'zh';
  var active = 0;
  var console_ = $('heroChat');
  function renderPersona(announce) {
    var c = CAST[active];
    document.querySelector('.persona-exchange').setAttribute('aria-live', announce ? 'polite' : 'off');
    $('portraitNumber').textContent = '0' + (active + 1) + ' / 0' + CAST.length;
    $('scamPrompt').hidden = !c.scam;
    $('scamLine').textContent = c.scam ? '“' + c.scam + '”' : '';
    $('botSpeaker').textContent = c.title;
    $('personaReply').textContent = c.reply || '';
    $('personaLink').href = 'demo.html' + (c.scenario ? '?scenario=' + c.scenario : '');
    $('personaSource').hidden = !c.source;
    document.querySelectorAll('.team-member').forEach(function (b, i) { var on = i === active; b.classList.toggle('active', on); b.setAttribute('aria-pressed', String(on)); });
    document.dispatchEvent(new CustomEvent('deepsuck:personachange', { detail: { persona: c.id } }));
  }

  // 轮播：6 秒一换（计时规则见 carousel.js）。悬停在对话区、键盘焦点在轮播内、离开视口、页面后台、
  // 用户暂停、减少动态 / 站点动效已关时不自动播放；鼠标点选或触屏点选后从该张继续轮播。
  var button = $('carouselToggle');
  var reduced = matchMedia('(prefers-reduced-motion: reduce)');
  function motionOff() { return reduced.matches || document.documentElement.classList.contains('motion-paused'); }
  var rot = window.DeepSuckCarousel.createRotator({
    count: CAST.length, delay: 6000,
    onChange: function (i, manual) { active = i; renderPersona(manual); },
    onState: function (st, on) {
      var off = st.reduced, stop = st.paused || off;
      console_.classList.remove('is-rotating');
      button.disabled = off;
      button.setAttribute('aria-pressed', String(stop));
      button.setAttribute('aria-label', off ? (lang === 'en' ? 'Automatic rotation off' : '已关闭自动轮播') : stop ? (lang === 'en' ? 'Start automatic rotation' : '开始自动轮播') : (lang === 'en' ? 'Pause automatic rotation' : '暂停自动轮播'));
      button.classList.toggle('is-paused', stop);
      if (!on) return;
      void console_.offsetWidth; // 重启进度条动画
      console_.classList.add('is-rotating');
    }
  });
  function keyboardFocus(el) { try { return el.matches(':focus-visible'); } catch (_) { return true; } }
  function syncMotion() { rot.state.reduced = motionOff(); rot.state.hidden = document.hidden; rot.sync(); }
  document.querySelectorAll('.team-member').forEach(function (b, i) { b.addEventListener('click', function () { rot.go(i); }); });
  button.addEventListener('click', function () { rot.set('paused', !rot.state.paused); });
  var talk = $('personaConversation');
  talk.addEventListener('pointerenter', function (e) { if (e.pointerType === 'mouse') rot.set('hover', true); });
  talk.addEventListener('pointerleave', function () { rot.set('hover', false); });
  console_.addEventListener('focusin', function (e) { rot.set('focus', keyboardFocus(e.target)); });
  console_.addEventListener('focusout', function (e) { if (!console_.contains(e.relatedTarget)) rot.set('focus', false); });
  console_.addEventListener('keyup', function (e) { if (e.key === 'Tab' && console_.contains(document.activeElement)) rot.set('focus', keyboardFocus(document.activeElement)); });
  document.addEventListener('visibilitychange', syncMotion);
  document.addEventListener('deepsuck:motionchange', syncMotion);
  document.addEventListener('deepsuck:languagechange', function (e) { lang = e.detail && e.detail.lang === 'en' ? 'en' : 'zh'; rot.sync(); });
  if (reduced.addEventListener) reduced.addEventListener('change', syncMotion); else if (reduced.addListener) reduced.addListener(syncMotion);
  if ('IntersectionObserver' in window) new IntersectionObserver(function (es) {
    var e = es[es.length - 1];
    rot.set('visible', e.isIntersecting && (e.intersectionRatio >= .25 || e.intersectionRect.height >= innerHeight * .4));
  }, { threshold: [0, .1, .25, .5] }).observe(console_);
  else rot.state.visible = true;
  syncMotion();

  // 提取结果表：首页第一段示例的骗子原话、已打码情报与话术标签
  (function () {
    var sc = SCRIPTS[0]; if (!sc) { $('clueSheet').hidden = true; return; }
    var lines = sc.lines || [], said = '', intel = [], tags = [];
    lines.forEach(function (l) {
      if (l.r && l.i && !said) said = l.r;
      if (l.i) String(l.i).split(' · ').forEach(function (x) { intel.push(x); });
      if (l.t) String(l.t).split(' · ').forEach(function (x) { if (tags.indexOf(x) < 0) tags.push(x); });
    });
    $('clueTitle').textContent = sc.title;
    $('clueSource').textContent = sc.source || '';
    $('clueSaid').textContent = said ? '“' + said + '”' : '';
    var dd = $('clueIntel'); dd.textContent = '';
    intel.forEach(function (x) {
      var row = document.createElement('span'); row.className = 'clue-item';
      // 打码部分（*）用强调色
      String(x).split(/(\*+)/).forEach(function (part) {
        if (!part) return;
        if (/^\*+$/.test(part)) { var m = document.createElement('span'); m.className = 'mask'; m.textContent = part; row.appendChild(m); }
        else row.appendChild(document.createTextNode(part));
      });
      dd.appendChild(row);
    });
    $('clueTactics').textContent = tags.join(' · ');
  })();

  // 语音演示入口：与沙盒一致，live 服务健康时才显示
  var LIVE = String((window.DEEPSUCK_LIVE && window.DEEPSUCK_LIVE.api) || '').replace(/\/+$/, '');
  if (LIVE && window.fetch) fetch(LIVE + '/api/health', { cache: 'no-store' }).then(function (r) { return r.ok ? r.json() : null; }).then(function (j) {
    if (j) document.querySelectorAll('[data-live-voice]').forEach(function (a) { a.href = LIVE + '/'; a.hidden = false; });
  }).catch(function () {});

  document.querySelectorAll('.menu-panel a').forEach(function (a) { a.addEventListener('click', function () { var d = a.closest('details'); if (d) d.open = false; }); });
  renderPersona(false);
})();
