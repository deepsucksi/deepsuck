/*! DeepSuck — intel-page.js：公开情报库页面（检索 / 筛选 / 下载）。Apache-2.0 */
(function () {
  'use strict';
  var D = window.DeepSuck, I = D.intel;
  var $ = function (id) { return document.getElementById(id); };
  var lib = null, view = [];
  var SC = {}; D.scenarios.SCENARIOS.forEach(function (s) { SC[s.id] = s; });
  SC.other = { id: 'other', title: '其他' };

  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; }); }
  function toast(m) { var t = $('toast'); t.textContent = m; t.style.display = 'block'; clearTimeout(toast._t); toast._t = setTimeout(function () { t.style.display = 'none'; }, 2600); }
  function tacticLabel(id) { var t = D.tactics.BY_ID[id]; return t ? t.label : id; }
  function fmtValue(e) {
    if (e.type === 'phone') {
      var d = String(e.value);
      if (/^\d{11}$/.test(d)) return d.slice(0, 3) + ' ' + d.slice(3, 7) + ' ' + d.slice(7);
      if (/^(400|800)\d{7}$/.test(d)) return d.slice(0, 3) + '-' + d.slice(3, 6) + '-' + d.slice(6);
    }
    return e.value;
  }

  function card(e) {
    var t = I.TYPES[e.type] || { label: e.type, policy: 'masked' };
    var disputed = e.status === 'disputed';
    var sc = SC[e.scenario] || SC.other;
    var meta = [];
    if (e.chain) meta.push('链：' + e.chain);
    if (e.bank) meta.push('开户行：' + e.bank);
    meta.push('首次 ' + e.firstSeen + (e.lastSeen ? ' · 最近 ' + e.lastSeen : ''));
    if (e.reports) meta.push('举报 ' + e.reports + ' 次');
    return '<article class="icard2' + (e.type === 'script' ? ' wide' : '') + '">' +
      '<div class="h"><span>' + esc(t.label) + '</span><span class="badges">' +
        (e.example ? '<span class="tag ex">示例数据</span>' : '') +
        (disputed ? '<span class="tag">申诉处理中</span>' : (t.policy === 'full' ? '<span class="tag full">完整公开</span>' : '<span class="tag amber">已打码</span>')) +
      '</span></div>' +
      '<div class="val' + (e.type === 'script' ? ' script' : '') + '">' + (disputed ? '（申诉处理中，暂不展示）' : esc(fmtValue(e))) +
        (!disputed && e.type !== 'script' ? ' <button class="copy" type="button" data-copy="' + esc(e.value) + '" title="复制">复制</button>' : '') + '</div>' +
      '<div class="m">' + esc(meta.join(' · ')) + '</div>' +
      '<div class="tags"><span class="tag amber">' + esc(sc.title) + '</span>' +
        (e.tactics || []).map(function (id) { return '<span class="tag">' + esc(tacticLabel(id)) + '</span>'; }).join('') + '</div>' +
      (e.notes ? '<p class="notes">' + esc(e.notes) + '</p>' : '') +
      '<div class="id">' + esc(e.id) + ' · 来源 ' + esc(e.source) + '</div>' +
      '</article>';
  }

  function current() { return { q: $('q').value, type: $('fType').value, scenario: $('fScenario').value }; }

  function render() {
    var f = current();
    view = I.filterEntries(lib.entries, f);
    $('results').innerHTML = view.length ? view.map(card).join('') : '<div class="empty">没有匹配的情报。换个关键词试试，或<a href="#contribute">提交新情报</a>。</div>';
    var total = lib.entries.filter(function (e) { return e.status !== 'removed'; }).length;
    $('resultInfo').textContent = '共 ' + total + ' 条，当前显示 ' + view.length + ' 条 · 更新于 ' + lib.updatedAt;
    var p = new URLSearchParams();
    if (f.q) p.set('q', f.q); if (f.type) p.set('type', f.type); if (f.scenario) p.set('scenario', f.scenario);
    var qs = p.toString();
    history.replaceState(null, '', location.pathname + (qs ? '?' + qs : '') + location.hash);
  }

  function renderStats() {
    var counts = {};
    lib.entries.forEach(function (e) { if (e.status !== 'removed') counts[e.type] = (counts[e.type] || 0) + 1; });
    $('typeStats').innerHTML = Object.keys(I.TYPES).filter(function (k) { return counts[k]; }).map(function (k) {
      return '<button class="stat" type="button" data-type="' + k + '"><div class="v">' + counts[k] + '</div><div class="k">' + esc(I.TYPES[k].label) + '</div></button>';
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
    Object.keys(I.TYPES).forEach(function (k) { $('fType').insertAdjacentHTML('beforeend', '<option value="' + k + '">' + esc(I.TYPES[k].label) + '</option>'); });
    D.scenarios.SCENARIOS.forEach(function (s) { $('fScenario').insertAdjacentHTML('beforeend', '<option value="' + s.id + '">' + esc(s.title) + '</option>'); });
    var p = new URLSearchParams(location.search);
    $('q').value = p.get('q') || ''; $('fType').value = p.get('type') || ''; $('fScenario').value = p.get('scenario') || '';
    if (!lib.entries.some(function (e) { return e.example; })) $('notice').style.display = 'none';
    renderStats(); render();
    $('q').addEventListener('input', render);
    $('fType').addEventListener('change', render);
    $('fScenario').addEventListener('change', render);
    $('typeStats').addEventListener('click', function (e) {
      var b = e.target.closest('[data-type]'); if (!b) return;
      $('fType').value = $('fType').value === b.dataset.type ? '' : b.dataset.type; render();
    });
    $('dlJson').addEventListener('click', function () {
      var out = Object.assign({}, lib, { entries: view, exportedAt: new Date().toISOString(), filter: current() });
      download('deepsuck-intel-' + lib.updatedAt + '.json', JSON.stringify(out, null, 2), 'application/json');
      toast('已导出 ' + view.length + ' 条（JSON）');
    });
    $('dlCsv').addEventListener('click', function () {
      download('deepsuck-intel-' + lib.updatedAt + '.csv', I.toCSV(view), 'text/csv;charset=utf-8');
      toast('已导出 ' + view.length + ' 条（CSV）');
    });
    $('results').addEventListener('click', function (e) {
      var b = e.target.closest('[data-copy]'); if (!b) return;
      var v = b.getAttribute('data-copy');
      (navigator.clipboard ? navigator.clipboard.writeText(v) : Promise.reject()).then(function () { toast('已复制：' + v); }, function () { toast(v); });
    });
  }

  fetch('data/intel.json', { cache: 'no-cache' }).then(function (r) {
    if (!r.ok) throw new Error('HTTP ' + r.status); return r.json();
  }).then(init).catch(function (err) {
    $('resultInfo').textContent = '情报数据加载失败：' + err.message + '（如果你是直接双击打开 HTML，请用本地服务器访问，例如 python3 -m http.server）';
  });
})();
