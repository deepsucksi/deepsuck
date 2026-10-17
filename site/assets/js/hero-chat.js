/*! DeepSuck — hero-chat.js：首页循环播放的示例对话（纯展示，台词与数据均为虚构）。Apache-2.0 · 非官方项目，与 DeepSeek 无关 */
(function () {
  'use strict';
  var box = document.getElementById('heroChat');
  if (!box) return;
  var body = document.getElementById('hcBody'), title = document.getElementById('hcTitle');
  var timer = document.getElementById('hcTimer'), intel = document.getElementById('hcIntel');
  var reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  // r = 骗子，s = 机器人人设；t = 话术标签；i = 提取到的情报（已打码）；w = 这一轮"拖住"的估算秒数
  var SCRIPTS = [
    { title: '🚨 冒充公检法 · 👵 王阿姨', lines: [
      { r: '我是市公安局张警官，你名下银行卡涉嫌洗钱，马上配合调查！', t: '冒充公检法 · 制造紧迫感' },
      { s: '👵 哎呀吓死我了，你等我吃个速效救心丸……好了，警察同志你说吧。', w: 60 },
      { r: '案件保密，不要告诉家人。把钱转到安全账户 6222 **** **** 3445，户名王**', t: '要求保密 · 安全账户', i: '银行卡 6222 **** **** 3445 · 户名 王**' },
      { s: '👵 我抄在挂历背面了，你看我写的对不对？你再留个电话，我怕一会儿找不到你。', w: 45 },
      { r: '打 139****2233，快点！', i: '电话 139****2233' },
      { s: '👵 好好好，我先去找存折，好像放在米缸下面了……', w: 180 }
    ] },
    { title: '🧾 刷单返利 · 🧑‍🎓 小林', lines: [
      { r: '点赞员日结 200-500 元，先做新手任务，返 5 元马上到账～', t: '刷单返佣 · 制造紧迫感' },
      { s: '🧑‍🎓 5 块到了！我先提现到余额宝，稳一手再做下一单～', w: 100 },
      { r: '下一单是福利单，先垫付 2800 元，下载"星辰任务"APP：xi***mo.top', t: '诱导垫付 · 下载APP', i: 'APP 星辰任务 · 网址 xi***mo.top' },
      { s: '🧑‍🎓 垫付我好像在反诈课 PPT 第三页见过……开玩笑开玩笑，收款账户发我一下？', w: 90 },
      { r: '转到 6230 **** **** 3445，户名赵**', i: '银行卡 6230 **** **** 3445' },
      { s: '🧑‍🎓 我卡里只有 23 块，等下个月 1 号生活费到账再转可以吗？', w: 240 }
    ] },
    { title: '👔 冒充领导 · 👴 李大爷', lines: [
      { r: '我是你王总，换新号了，在开会不方便接电话。', t: '冒充熟人/领导' },
      { s: '👴 领导？我们车间主任老刘前年就走了啊……你说说，车间那台老车床是哪年报废的？', w: 120 },
      { r: '别问了，先帮我给合作方垫 4.8 万，转 6214 **** **** 9887', t: '要求转账 · 阻止核实', i: '银行卡 6214 **** **** 9887' },
      { s: '👴 你等等，我腿脚不方便，起来拿个本子得五分钟……', w: 180 }
    ] }
  ];

  function esc(s) { return String(s).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; }); }
  function fmt(sec) { return '⏱ ' + String(Math.floor(sec / 60)).padStart(2, '0') + ':' + String(sec % 60).padStart(2, '0'); }
  function wait(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }

  function bubble(line) {
    var row = document.createElement('div');
    row.className = 'row hc-in';
    var cls = line.r ? 'r' : 's';
    row.innerHTML = '<div class="b ' + cls + '">' + esc(line.r || line.s) + '</div>';
    body.appendChild(row);
    if (line.t) {
      var tag = document.createElement('div');
      tag.className = 'tag hc-in'; tag.style.textAlign = 'right';
      tag.textContent = '⚑ ' + line.t;
      body.appendChild(tag);
    }
    while (body.scrollHeight > body.clientHeight && body.children.length > 2) body.removeChild(body.firstChild);
  }

  function typing() {
    var row = document.createElement('div');
    row.className = 'row hc-in';
    row.innerHTML = '<div class="b s"><span class="dots"><span></span><span></span><span></span></span></div>';
    body.appendChild(row);
    return row;
  }

  var visible = true;
  if ('IntersectionObserver' in window) new IntersectionObserver(function (es) { visible = es[0].isIntersecting; }).observe(box);
  function whenVisible() { return visible && !document.hidden ? Promise.resolve() : wait(600).then(whenVisible); }

  async function play() {
    var idx = 0;
    for (;;) {
      var sc = SCRIPTS[idx % SCRIPTS.length];
      var sec = 0, found = [];
      title.textContent = sc.title; body.innerHTML = ''; timer.textContent = fmt(0);
      intel.textContent = '等待骗子露出马脚……'; intel.classList.remove('got');
      for (var i = 0; i < sc.lines.length; i++) {
        await whenVisible();
        var l = sc.lines[i];
        if (l.s) { var t = typing(); await wait(1100 + l.s.length * 22); t.remove(); }
        else await wait(700);
        bubble(l);
        if (l.w) { sec += l.w; timer.textContent = fmt(sec); }
        if (l.i) { found.push(l.i); intel.textContent = '✓ 已提取：' + found.join(' · '); intel.classList.add('got'); }
        await wait(l.r ? 900 : 1500);
      }
      await wait(3200);
      idx++;
    }
  }

  if (reduce) return; // 尊重"减少动态效果"：保留静态示例
  play();
})();
/* GitHub 星标数（公开 API，失败则静默隐藏） */
(function () {
  var el = document.getElementById('ghStars');
  if (!el || !window.fetch) return;
  fetch('https://api.github.com/repos/deepsucksi/deepsuck', { headers: { Accept: 'application/vnd.github+json' } })
    .then(function (r) { return r.ok ? r.json() : null; })
    .then(function (j) { if (j && j.stargazers_count > 0) { el.textContent = j.stargazers_count; el.hidden = false; } })
    .catch(function () {});
})();
