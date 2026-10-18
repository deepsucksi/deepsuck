/*! DeepSuck — blog.js：博客页的语言链接记住所选语言，回到首页时沿用（与 i18n.js 共用 localStorage 键）。Apache-2.0 */
(function () {
  'use strict';
  document.querySelectorAll('[data-lang-switch]').forEach(function (a) {
    a.addEventListener('click', function () {
      try { localStorage.setItem('deepsuck.lang', a.getAttribute('data-lang-switch')); } catch (e) {}
    });
  });
  try { localStorage.setItem('deepsuck.lang', document.documentElement.lang === 'en' ? 'en' : 'zh'); } catch (e) {}
})();
