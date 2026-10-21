/*!
 * DeepSuck — stats.js：隐私友好的访问统计（自托管 GoatCounter，见 deploy/docker-compose.yml 的 stats 服务）。
 *  - endpoint：live 站 /stats/ 路径下的 GoatCounter 计数端点（deploy/caddy/Caddyfile 的 @stats）。置空则什么都不发。
 *  - 统计服务没部署或出错时（404 / 502 / 断网）静默失败：只发一次，不重试、不抛错、不打日志。
 *  - 不设 cookie、不用 localStorage、不加载第三方脚本；只发一个 GET 计数请求（页面路径、标题、来源站）。
 *  - 浏览器开了「请勿追踪」（DNT）或 GPC 时完全不发；本地预览（localhost / file:）也不发。
 *  - 不发送查询串、页面内容、聊天内容或任何输入框里的文字；事件只有固定名字（例如 demo-session）。
 *  - 服务端（GoatCounter）不保存 IP：只用 IP+UA 加每日轮换的盐算一个当天去重用的哈希。
 * Apache-2.0
 */
(function (root) {
  'use strict';
  var cfg = root.DEEPSUCK_STATS = root.DEEPSUCK_STATS || { endpoint: 'https://live.deepsuck.si/stats/count' };

  function enabled() {
    if (!cfg.endpoint || typeof document === 'undefined') return false;
    var n = root.navigator || {};
    var dnt = n.doNotTrack || root.doNotTrack || n.msDoNotTrack;
    if (dnt === '1' || dnt === 'yes' || n.globalPrivacyControl === true) return false;
    var loc = root.location || {};
    if (loc.protocol === 'file:' || /^(localhost|127\.|0\.0\.0\.0|\[::1\])/.test(loc.hostname || '')) return false;
    return true;
  }

  function referrer() {
    // 只报来源站点（协议+域名），不带路径和查询串；站内跳转不报
    try {
      var r = new URL(document.referrer);
      return r.host === root.location.host ? '' : r.protocol + '//' + r.host;
    } catch (e) { return ''; }
  }

  function hit(path, title, isEvent) {
    if (!enabled()) return;
    var q = 'p=' + encodeURIComponent(path) + '&t=' + encodeURIComponent(title || '') +
      '&r=' + encodeURIComponent(isEvent ? '' : referrer()) + (isEvent ? '&e=true' : '') + '&rnd=' + Math.random().toString(36).slice(2);
    var url = cfg.endpoint + '?' + q;
    try {
      if (root.navigator && root.navigator.sendBeacon && root.navigator.sendBeacon(url)) return;
    } catch (e) { /* 回退到图片请求 */ }
    try {
      var img = new Image();
      img.onerror = img.onload = function () { img.onerror = img.onload = null; };
      img.referrerPolicy = 'no-referrer';
      img.src = url;
    } catch (e) { /* 静默失败，不重试 */ }
  }

  root.DeepsuckStats = {
    // 固定名字的事件，例如 'demo-session'；不要传任何用户输入
    event: function (name) { if (/^[a-z0-9-]{1,40}$/.test(name)) hit(name, name, true); }
  };

  function pageview() { hit(root.location.pathname || '/', document.title, false); }
  if (typeof document !== 'undefined') {
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', pageview);
    else pageview();
  }
})(typeof self !== 'undefined' ? self : this);
