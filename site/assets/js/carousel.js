/*! DeepSuck — carousel.js：首页人设轮播的计时状态机（不碰 DOM，便于测试；home.js 负责渲染与事件）。Apache-2.0
 *  规则：可见且未暂停时每 delay 毫秒前进一张；鼠标悬停在对话区、键盘焦点在轮播内、离开视口、页面在后台、
 *  用户点了暂停、系统要求减少动态（或站点动效已关）时都不计时；条件恢复后重新计满一个 delay。
 *  手动选择某一张后继续自动轮播（从该张重新计时）。 */
(function (root) {
  'use strict';
  function createRotator(opts) {
    var n = opts.count, delay = opts.delay || 6000;
    var T = opts.setTimeout || function (f, ms) { return setTimeout(f, ms); };
    var C = opts.clearTimeout || function (id) { clearTimeout(id); };
    var st = { active: 0, visible: false, hover: false, focus: false, paused: false, reduced: false, hidden: false };
    var timer = 0, api;
    function running() { return n > 1 && !st.paused && !st.reduced && st.visible && !st.hover && !st.focus && !st.hidden; }
    function sync() {
      if (timer) C(timer);
      timer = 0;
      var on = running();
      if (opts.onState) opts.onState(st, on);
      if (!on) return;
      timer = T(function () {
        timer = 0;
        st.active = (st.active + 1) % n;
        opts.onChange(st.active, false);
        sync();
      }, delay);
    }
    api = {
      state: st,
      delay: delay,
      running: running,
      set: function (key, value) { if (st[key] === value) return; st[key] = value; sync(); },
      go: function (i) { st.active = ((i % n) + n) % n; opts.onChange(st.active, true); sync(); },
      sync: sync
    };
    return api;
  }
  var lib = { createRotator: createRotator };
  if (typeof module === 'object' && module.exports) module.exports = lib;
  else root.DeepSuckCarousel = lib;
})(typeof window !== 'undefined' ? window : this);
