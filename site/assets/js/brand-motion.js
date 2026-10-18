/*! DeepSuck — brand-motion.js：首页呈现层动效（本地 GSAP 3.15.0，许可见 assets/vendor/gsap/NOTICE.md）。
 *  渐进增强：GSAP 缺失、减少动态或用户暂停时显示静态版式，不影响任何内容。移植自 R11 视觉包。Apache-2.0 */
(function () {
  'use strict';
  var g = window.gsap;
  var reduce = matchMedia('(prefers-reduced-motion: reduce)');
  var fine = matchMedia('(hover: hover) and (pointer: fine)');
  var toggle = document.getElementById('motionToggle');
  var stopped = false, context, splits = [], observer, loops = [], inView = new Map(), pointerCleanup = null;
  try { stopped = localStorage.getItem('deepsuck.motion') === 'paused'; } catch (_) {}
  function enabled() { return !stopped && !reduce.matches; }
  function label() {
    var en = document.documentElement.lang === 'en';
    toggle.querySelector('span').textContent = reduce.matches ? (en ? 'Reduced motion' : '已减少动态效果') : enabled() ? (en ? 'Pause motion' : '暂停动效') : (en ? 'Enable motion' : '开启动效');
    toggle.setAttribute('aria-pressed', String(!enabled()));
    toggle.querySelector('use').setAttribute('href', enabled() ? '#ds-pause' : '#ds-play');
    toggle.disabled = reduce.matches;
    document.documentElement.classList.toggle('motion-paused', !enabled());
    document.dispatchEvent(new CustomEvent('deepsuck:motionchange'));
  }
  function synchronize() {
    loops.forEach(function (item) {
      if (enabled() && !document.hidden && inView.get(item.section)) item.tween.play(); else item.tween.pause();
    });
  }
  function cleanup() {
    if (pointerCleanup) pointerCleanup(); pointerCleanup = null;
    if (observer) observer.disconnect();
    if (context) context.revert();
    splits.forEach(function (split) { split.revert(); }); splits = []; loops = []; inView.clear();
    document.querySelectorAll('[data-split-label]').forEach(function (h) { h.removeAttribute('aria-label'); h.removeAttribute('data-split-label'); });
    document.querySelector('.call-stage').classList.remove('scene-linked');
    document.querySelector('.topbar').classList.remove('in-call');
  }
  function build() {
    label();
    if (!g || !window.ScrollTrigger || !window.SplitText || !window.CustomEase || !enabled()) return;
    g.registerPlugin(ScrollTrigger, SplitText, CustomEase);
    CustomEase.create('unfurl', '0.22,1,0.36,1');
    observer = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) { inView.set(entry.target, entry.isIntersecting); }); synchronize();
    }, { threshold: 0 });
    document.querySelector('.call-stage').classList.add('scene-linked');
    context = g.context(function () {
      function loop(section, target, vars) {
        var node = document.querySelector(section);
        var tween = g.to(target, Object.assign({ paused: true, repeat: -1 }, vars));
        loops.push({ section: node, tween: tween }); observer.observe(node);
      }
      // 标题逐字展开；读屏仍读整句（aria-label）
      document.querySelectorAll('#home-title, main h2').forEach(function (heading) {
        var phrase = heading.innerText.replace(/\s+/g, ' ').trim();
        // 英文先按词包一层，避免单词被拆到两行（中文没有空格分词，仍只按字拆）
        var en = document.documentElement.lang === 'en';
        var split = SplitText.create(heading, en ? { type: 'words,chars', wordsClass: 'unfurl-word', charsClass: 'unfurl-char', aria: 'auto' } : { type: 'chars', charsClass: 'unfurl-char', aria: 'auto' }); splits.push(split);
        heading.setAttribute('aria-label', phrase); heading.setAttribute('data-split-label', '');
        g.from(split.chars, { yPercent: 24, rotationX: -12, opacity: 0, filter: 'blur(2px)', duration: .95, stagger: .022, ease: 'unfurl', scrollTrigger: { trigger: heading, start: 'top 94%', once: true } });
      });
      g.from('.project-label, .poster-description, .poster-actions', { y: 12, opacity: 0, stagger: .1, duration: .85, ease: 'unfurl', delay: .08 });
      g.from('.receiver-rig', { y: 28, scale: .96, opacity: 0, duration: 1.45, ease: 'unfurl', delay: .12 });
      loop('.home-poster', '.receiver-float', { y: -5, rotation: .45, duration: 7, yoyo: true, ease: 'sine.inOut' });
      loop('.home-poster', '.receiver-light', { backgroundPosition: '0% 0%', duration: 11, ease: 'sine.inOut', repeatDelay: 3 });
      loop('.home-poster', '.stage-shadow', { scaleX: .9, opacity: .65, duration: 6, yoyo: true, ease: 'sine.inOut' });
      // 白到黑的连续过渡：只有一条滚动时间线，不钉住页面
      var scene = g.timeline({ scrollTrigger: { trigger: '.poster-art', start: 'top 32%', endTrigger: '#experience', end: 'top 72%', scrub: .65, invalidateOnRefresh: true } });
      scene.to('.call-stage', { '--scene-bg': '#111313', '--scene-floor': '#392b25', '--scene-light': 0, '--caption-ink': '#b3bbb5', duration: 1, ease: 'none' }, 0);
      scene.to('.poster-title', { opacity: 0, y: -22, duration: .48, ease: 'none' }, 0);
      scene.to('.poster-caption', { y: 45, duration: 1, ease: 'none' }, 0);
      scene.to('.receiver-scroll', { y: function () { return innerWidth < 700 ? 40 : 75; }, scale: .94, rotation: 1.5, duration: 1, ease: 'none' }, 0);
      ScrollTrigger.create({ trigger: '.poster-art', start: 'top 12%', endTrigger: '.clues-section', end: 'bottom 84px', toggleClass: { targets: '.topbar', className: 'in-call' } });
      g.utils.toArray('.clue-sheet, .steps .step, .cards-sc .card').forEach(function (node) {
        g.from(node, { y: 26, opacity: 0, duration: 1.05, ease: 'unfurl', scrollTrigger: { trigger: node, start: 'top 94%', once: true } });
      });
      g.from('.team-console', { y: 18, opacity: 0, duration: 1, ease: 'unfurl', scrollTrigger: { trigger: '.team-console', start: 'top 92%', once: true } });
      g.utils.toArray('.brand-art img').forEach(function (img) {
        g.fromTo(img, { yPercent: 4, scale: 1.035 }, { yPercent: -3, scale: 1, duration: 1, ease: 'none', scrollTrigger: { trigger: img.closest('.brand-art'), start: 'top bottom', end: 'bottom top', scrub: 1.2 } });
      });
      if (fine.matches) {
        var rig = document.querySelector('.receiver-rig');
        var x = g.quickTo(rig, 'rotationY', { duration: 1.4, ease: 'power3.out' });
        var y = g.quickTo(rig, 'rotationX', { duration: 1.4, ease: 'power3.out' });
        var art = document.querySelector('.poster-art');
        var move = function (e) { var r = art.getBoundingClientRect(); x((e.clientX - r.left - r.width / 2) / r.width * 5); y(-(e.clientY - r.top - r.height / 2) / r.height * 3); };
        var leave = function () { x(0); y(0); };
        art.addEventListener('pointermove', move); art.addEventListener('pointerleave', leave);
        pointerCleanup = function () { art.removeEventListener('pointermove', move); art.removeEventListener('pointerleave', leave); };
      }
    });
    ScrollTrigger.refresh();
  }
  function reset() { cleanup(); }
  toggle.addEventListener('click', function () {
    if (reduce.matches) return;
    stopped = !stopped;
    try { localStorage.setItem('deepsuck.motion', stopped ? 'paused' : 'enabled'); } catch (_) {}
    reset(); build();
  });
  if (reduce.addEventListener) reduce.addEventListener('change', function () { reset(); build(); });
  document.addEventListener('visibilitychange', synchronize);
  document.addEventListener('deepsuck:beforelanguagechange', reset);
  document.addEventListener('deepsuck:languagechange', build);
  document.addEventListener('deepsuck:personachange', function () {
    if (g && enabled()) g.fromTo('.persona-exchange', { opacity: 0, y: 8 }, { opacity: 1, y: 0, duration: .6, ease: 'power3.out', clearProps: 'opacity,transform', overwrite: true });
  });
  try { build(); } catch (error) { reset(); label(); console.warn('Brand motion unavailable; showing static design.', error); }
})();
