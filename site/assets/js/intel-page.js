/*! DeepSuck — intel-page.js：公开情报库页面（检索 / 筛选 / 下载）。Apache-2.0 */
(function () {
  'use strict';
  var D = window.DeepSuck, I = D.intel;
  var $ = function (id) { return document.getElementById(id); };
  // 界面文案按语言取值（i18n.js）；情报条目本身（值、备注、开户行等，来自 data/intel.json）原样保留（data-i18n-keep="intel-data"）
  var I18 = window.DeepSuckI18n || { L: function (zh) { return zh; }, tr: function (x) { return x; } };
  var L = I18.L, tr = I18.tr;
  function keep(s) { return '<span data-i18n-keep="intel-data">' + esc(s) + '</span>'; }
  var lib = null, view = [];
  var PAGE = window.matchMedia && matchMedia('(max-width: 640px)').matches ? 3 : 6, shown = PAGE; // 首屏只渲染前几条，其余点“显示更多”
  var SC = {}; D.scenarios.SCENARIOS.forEach(function (s) { SC[s.id] = s; });
  SC.other = { id: 'other', title: '其他' };

  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; }); }
  function toast(m) { var t = $('toast'); t.textContent = m; t.style.display = 'block'; clearTimeout(toast._t); toast._t = setTimeout(function () { t.style.display = 'none'; }, 2600); }
  function tacticLabel(id) { var t = D.tactics.BY_ID[id]; return t ? tr(t.label) : id; }
  function fmtValue(e) {
    if (e.type === 'phone') {
      var d = String(e.value);
      if (/^\d{11}$/.test(d)) return d.slice(0, 3) + ' ' + d.slice(3, 7) + ' ' + d.slice(7);
      if (/^(400|800)\d{7}$/.test(d)) return d.slice(0, 3) + '-' + d.slice(3, 6) + '-' + d.slice(6);
    }
    if (e.type === 'bank_card' && D.redact && D.redact.formatCardGroups) return D.redact.formatCardGroups(e.value); // 仅展示分组，存储不变
    return e.value;
  }

  function card(e) {
    var t = I.TYPES[e.type] || { label: e.type, policy: 'masked' };
    var disputed = e.status === 'disputed';
    var sc = SC[e.scenario] || SC.other;
    var meta = [];
    // meta 为已转义的 HTML 片段
    if (e.chain) meta.push(esc(L('链：', 'Chain: ') + e.chain));
    if (e.bank) meta.push(esc(L('开户行：', 'Bank: ')) + keep(e.bank));
    if (e.issuer && (!e.bank || e.issuer.indexOf(e.bank) < 0)) meta.push(esc(L('发卡行：', 'Issuer: ')) + keep(e.issuer));
    if (e.cardType) meta.push(esc(tr(e.cardType) + L('（按 BIN 推断）', ' (inferred from BIN)')));
    meta.push(esc(L('首次 ', 'First seen ') + e.firstSeen + (e.lastSeen ? L(' · 最近 ', ' · last seen ') + e.lastSeen : '')));
    if (e.reports) meta.push(esc(L('举报 ', 'Reported ') + e.reports + L(' 次', ' times')));
    return '<article class="icard2' + (e.type === 'script' ? ' wide' : '') + '">' +
      '<div class="h"><span>' + esc(tr(t.label)) + '</span><span class="badges">' +
        (e.example ? '<span class="tag ex">' + L('示例数据', 'Sample data') + '</span>' : '') +
        (disputed ? '<span class="tag">' + L('申诉处理中', 'Under appeal') + '</span>' : (t.policy === 'full' ? '<span class="tag full">' + L('完整公开', 'Published in full') + '</span>' : '<span class="tag amber">' + L('已打码', 'Masked') + '</span>')) +
      '</span></div>' +
      '<div class="val' + (e.type === 'script' ? ' script' : '') + '">' + (disputed ? L('（申诉处理中，暂不展示）', '(Under appeal, hidden for now)') : keep(fmtValue(e))) +
        (!disputed && e.type !== 'script' ? ' <button class="copy" type="button" data-copy="' + esc(e.value) + '" title="' + L('复制', 'Copy') + '">' + L('复制', 'Copy') + '</button>' : '') + '</div>' +
      '<div class="m">' + meta.join(' · ') + '</div>' +
      '<div class="tags"><span class="tag amber">' + esc(tr(sc.title)) + '</span>' +
        (e.tactics || []).map(function (id) { return '<span class="tag">' + esc(tacticLabel(id)) + '</span>'; }).join('') + '</div>' +
      (e.notes ? '<p class="notes" data-i18n-keep="intel-data">' + esc(e.notes) + '</p>' : '') +
      '<div class="id">' + esc(e.id) + L(' · 来源 ', ' · source ') + esc(e.source) + '</div>' +
      '</article>';
  }

  function current() { return { q: $('q').value, type: $('fType').value, scenario: $('fScenario').value }; }

  function render() {
    var f = current();
    view = I.filterEntries(lib.entries, f);
    $('results').innerHTML = view.length ? view.slice(0, shown).map(card).join('') : '<div class="empty">' + L('没有匹配的情报。换个关键词试试，或<a href="#contribute">提交新情报</a>。', 'No matching intel. Try another keyword, or <a href="#contribute">submit new intel</a>.') + '</div>';
    var rest = view.length - Math.min(shown, view.length);
    $('moreBtn').hidden = rest <= 0;
    $('moreBtn').textContent = L('显示更多（还有 ' + rest + ' 条）', 'Show more (' + rest + ' left)');
    var total = lib.entries.filter(function (e) { return e.status !== 'removed'; }).length;
    $('resultInfo').textContent = L('共 ' + total + ' 条，当前显示 ' + view.length + ' 条 · 更新于 ', total + ' entries, ' + view.length + ' shown · updated ') + lib.updatedAt;
    var p = new URLSearchParams();
    if (f.q) p.set('q', f.q); if (f.type) p.set('type', f.type); if (f.scenario) p.set('scenario', f.scenario);
    var qs = p.toString();
    history.replaceState(null, '', location.pathname + (qs ? '?' + qs : '') + location.hash);
  }

  function renderStats() {
    var counts = {};
    lib.entries.forEach(function (e) { if (e.status !== 'removed') counts[e.type] = (counts[e.type] || 0) + 1; });
    $('typeStats').innerHTML = Object.keys(I.TYPES).filter(function (k) { return counts[k]; }).map(function (k) {
      return '<button class="stat" type="button" data-type="' + k + '"><div class="v">' + counts[k] + '</div><div class="k">' + esc(tr(I.TYPES[k].label)) + '</div></button>';
    }).join('');
  }

  function download(name, text, mime) {
    var a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([text], { type: mime }));
    a.download = name; document.body.appendChild(a); a.click(); a.remove();
    setTimeout(function () { URL.revokeObjectURL(a.href); }, 2000);
  }

  function init(data) {
    lib = data;
    Object.keys(I.TYPES).forEach(function (k) { $('fType').insertAdjacentHTML('beforeend', '<option value="' + k + '">' + esc(tr(I.TYPES[k].label)) + '</option>'); });
    D.scenarios.SCENARIOS.forEach(function (s) { $('fScenario').insertAdjacentHTML('beforeend', '<option value="' + s.id + '" data-zh="' + esc(s.title) + '">' + esc(tr(s.title)) + '</option>'); });
    // 切换语言：重写筛选项与结果卡片（选中值不变）
    document.addEventListener('deepsuck:languagechange', function () {
      Array.prototype.forEach.call($('fType').options, function (o) { if (o.value && I.TYPES[o.value]) o.textContent = tr(I.TYPES[o.value].label); });
      Array.prototype.forEach.call($('fScenario').options, function (o) { if (o.value) o.textContent = tr(o.getAttribute('data-zh')); });
      renderStats(); render();
    });
    var p = new URLSearchParams(location.search);
    $('q').value = p.get('q') || ''; $('fType').value = p.get('type') || ''; $('fScenario').value = p.get('scenario') || '';
    if (!lib.entries.some(function (e) { return e.example; })) $('notice').style.display = 'none';
    renderStats(); render();
    function refilter() { shown = PAGE; render(); }
    $('q').addEventListener('input', refilter);
    $('fType').addEventListener('change', refilter);
    $('fScenario').addEventListener('change', refilter);
    $('moreBtn').addEventListener('click', function () {
      var first = Math.min(shown, view.length);
      shown += PAGE; render();
      var next = $('results').children[first]; if (next) { next.setAttribute('tabindex', '-1'); next.focus({ preventScroll: true }); }
    });
    $('typeStats').addEventListener('click', function (e) {
      var b = e.target.closest('[data-type]'); if (!b) return;
      $('fType').value = $('fType').value === b.dataset.type ? '' : b.dataset.type; shown = PAGE; render();
    });
    $('dlJson').addEventListener('click', function () {
      var out = Object.assign({}, lib, { entries: view, exportedAt: new Date().toISOString(), filter: current() });
      download('deepsuck-intel-' + lib.updatedAt + '.json', JSON.stringify(out, null, 2), 'application/json');
      toast(L('已导出 ' + view.length + ' 条（JSON）', 'Exported ' + view.length + ' entries (JSON)'));
    });
    $('dlCsv').addEventListener('click', function () {
      download('deepsuck-intel-' + lib.updatedAt + '.csv', I.toCSV(view), 'text/csv;charset=utf-8');
      toast(L('已导出 ' + view.length + ' 条（CSV）', 'Exported ' + view.length + ' entries (CSV)'));
    });
    $('results').addEventListener('click', function (e) {
      var b = e.target.closest('[data-copy]'); if (!b) return;
      var v = b.getAttribute('data-copy');
      (navigator.clipboard ? navigator.clipboard.writeText(v) : Promise.reject()).then(function () { toast(L('已复制：', 'Copied: ') + v); }, function () { toast(v); });
    });
  }

  fetch('data/intel.json', { cache: 'no-cache' }).then(function (r) {
    if (!r.ok) throw new Error('HTTP ' + r.status); return r.json();
  }).then(init).catch(function (err) {
    $('resultInfo').textContent = L('情报数据加载失败：', 'Failed to load intel data: ') + err.message + L('（如果你是直接双击打开 HTML，请用本地服务器访问，例如 python3 -m http.server）', ' (if you opened the HTML file directly, serve it locally instead, e.g. python3 -m http.server)');
  });
})();
