/*!
 * DeepSuck — live-config.js：公开"实时服务"（大模型对话代理 + 语音演示，见 deploy/ 与 docs/DEPLOY.md）的地址。
 *  - api 为空：纯静态，沙盒只用规则引擎（默认，零成本）。
 *  - api 设为 'https://live.deepsuck.si'：沙盒探测 <api>/api/health，可用且当日额度未用完时自动切到大模型；
 *    任何失败（离线 / 限流 / 额度用完）都会回退到规则引擎。导航栏显示"语音演示"入口（<api>/）。
 * Apache-2.0 · 非官方项目，与 DeepSeek 无关
 */
(function (root) {
  root.DEEPSUCK_LIVE = root.DEEPSUCK_LIVE || { api: '' };
})(typeof self !== 'undefined' ? self : this);
