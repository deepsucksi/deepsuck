/*! DeepSuck — hero-chat.js：首页循环播放的示例对话（纯展示；台词据公开反诈宣传改写，由 corpus/examples/hero_rewrite.json 的 after 段生成，号码与户名均为虚构打码值）。Apache-2.0 */
(function () {
  'use strict';
  var box = document.getElementById('heroChat');
  if (!box) return;
  var body = document.getElementById('hcBody'), title = document.getElementById('hcTitle');
  var timer = document.getElementById('hcTimer'), intel = document.getElementById('hcIntel');
  var reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  // 更新方式：改 corpus 后把 hero_rewrite.json 的 after 段整段替换到这里，不要手改单句。
  // r = 骗子，s = 机器人人设；t = 话术标签；i = 提取到的情报（已打码）；w = 这一轮"拖住"的估算秒数
  var SCRIPTS = [
    { title: "冒充公检法 · 周伯", source: "据公开反诈宣传改写", lines: [
      {"r": "我是市公安局经侦支队张警官，你名下银行卡涉嫌洗钱，请配合调查。", "t": "冒充公检法 · 制造紧迫感"},
      {"s": "啊？警察同志你慢点说，我耳朵背。洗钱？我就一张退休金的卡啊。", "w": 60},
      {"r": "案件保密，别告诉家人！钱转到安全账户 622202*********3445", "t": "要求保密 · 安全账户", "i": "银行卡 622202*********3445"},
      {"s": "等会儿，我找老花镜抄本子上。户名写谁？在留个电话，我手机老断。", "w": 90},
      {"r": "户名王**，电话 139****2233，两小时内必须办完！", "i": "户名 王** · 电话 139****2233"},
      {"s": "好好好 我先去找存折然后好像压在柜子底下了 就是说你别挂啊", "w": 180}
    ] },
    { title: "刷单返利 · 小陈妈妈", source: "据公开反诈宣传改写", lines: [
      {"r": "宝妈再家也能赚钱！点赞员日结 200-500 元，新手任务返 5 元。", "t": "刷单返佣 · 制造紧迫感"},
      {"s": "真的假的？娃刚睡着正好有空，我先做一个试试", "w": 60},
      {"r": "福利单先垫 2800 元返本加佣，下载\"星辰任务\"APP：xi***mo.top", "t": "诱导垫付 · 下载APP", "i": "APP 星辰任务 · 网址 xi***mo.top"},
      {"s": "先付多少来着？付完多久能返呀？稍等，娃又醒了。", "w": 120},
      {"r": "十分钟内返，转到 622848*********3445，户名赵**", "i": "银行卡 622848*********3445 · 户名 赵**"},
      {"s": "账户发我截图存着，钱在我老公哪，等他下班回来转。", "w": 240}
    ] },
    { title: "冒充领导 · 小宇", source: "据公开反诈宣传改写", lines: [
      {"r": "小宇，我是王总，这是新微信，在开会不方便接电话。", "t": "冒充熟人/领导"},
      {"s": "王总好！您有什么吩咐？我能打电话跟您确认一下吗？", "w": 60},
      {"r": "别打！先帮我给合作方垫 4.8 万，转 621483******9887", "t": "要求转账 · 阻止核实", "i": "银行卡 621483******9887"},
      {"s": "啊这，工资还没发余额不够。户名是公司还是个人的？我得核对一下。", "w": 150},
      {"r": "户名孙**，合作方老板的个人账户，赶紧的。", "i": "户名 孙**"},
      {"s": "好嘞，我找室友借点，在上班呢，等摸鱼的时候弄。等下我室友喊我拿外卖~", "w": 180}
    ] }
  ];

  function esc(s) { return String(s).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; }); }
  function fmt(sec) { return String(Math.floor(sec / 60)).padStart(2, '0') + ':' + String(sec % 60).padStart(2, '0'); }
  function wait(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }

  function bubble(line, still) {
    var row = document.createElement('div');
    row.className = still ? 'row' : 'row hc-in';
    var cls = line.r ? 'r' : 's';
    row.innerHTML = '<div class="b ' + cls + '">' + esc(line.r || line.s) + '</div>';
    body.appendChild(row);
    if (line.t) {
      var tag = document.createElement('div');
      tag.className = still ? 'tag' : 'tag hc-in'; tag.style.textAlign = 'right';
      tag.textContent = line.t;
      body.appendChild(tag);
    }
    trim();
  }

  // 只保留能完整放下的气泡：最上面一条的顶边必须在可视区内（留 GAP 给渐隐），
  // 这样任何时刻都不会出现被裁掉半截的气泡；连带移除孤立的话术标签。
  var GAP = 12;
  function trim() {
    var top = body.getBoundingClientRect().top + GAP;
    while (body.children.length > 2 && body.firstElementChild.getBoundingClientRect().top < top) {
      body.removeChild(body.firstElementChild);
      while (body.children.length > 2 && body.firstElementChild.classList.contains('tag')) body.removeChild(body.firstElementChild);
    }
  }

  function typing() {
    var row = document.createElement('div');
    row.className = 'row hc-in';
    row.innerHTML = '<div class="b s"><span class="dots"><span></span><span></span><span></span></span></div>';
    body.appendChild(row);
    trim();
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
      var start = 0;
      if (idx === 0) {
        // 首帧不留白：第一段对话的前 3 句直接铺好，再从第 4 句开始播放
        for (; start < 3; start++) {
          var p0 = sc.lines[start];
          bubble(p0, true);
          if (p0.w) sec += p0.w;
          if (p0.i) found.push(p0.i);
        }
        timer.textContent = fmt(sec);
        if (found.length) { intel.textContent = '已提取　' + found.join(' · '); intel.classList.add('got'); }
        await wait(1200);
      }
      for (var i = start; i < sc.lines.length; i++) {
        await whenVisible();
        var l = sc.lines[i];
        if (l.s) { var t = typing(); await wait(1100 + l.s.length * 22); t.remove(); }
        else await wait(700);
        bubble(l);
        if (l.w) { sec += l.w; timer.textContent = fmt(sec); }
        if (l.i) { found.push(l.i); intel.textContent = '已提取　' + found.join(' · '); intel.classList.add('got'); }
        await wait(l.r ? 900 : 1500);
      }
      await wait(3200);
      idx++;
    }
  }

  if (reduce) return; // 尊重"减少动态效果"：保留静态示例
  play();
})();
