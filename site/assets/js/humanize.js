/*!
 * DeepSuck — humanize.js
 * 真人化后处理（与 Python personas/humanize/core.py 逐字一致：同一 seed、同样的调用序列得到同样的输出）。
 * 数据（混淆表、预设）来自 site/assets/core/personas.json 的 humanize 段与各人设的 humanize 字段。
 * 数字串（号码、卡号、金额、钱包地址、网址、打码值）与占位符内部及紧挨的前后一个字符不插入错字、表情、标点，也不在那里拆条。
 * Apache-2.0
 */
(function (root, factory) {
  var isNode = typeof module === 'object' && module.exports;
  var C = isNode ? require('../core/personas.json') : root.DeepSuck.coreData.personas;
  var mod = factory(C);
  if (isNode) module.exports = mod;
  else { root.DeepSuck = root.DeepSuck || {}; root.DeepSuck.humanize = mod; }
})(typeof self !== 'undefined' ? self : this, function (C) {
  'use strict';
  var H = C.humanize, CF = H.confusion;
  var OPS = ['dialect', 'selfref', 'repeat', 'digress', 'extras', 'typo', 'asr', 'punct', 'emoji', 'split'];
  var MODES = ['chat', 'voice'];
  var PUNCT_STYLES = ['comma', 'none'];
  var BASE_RATES = { typo: 10.0, punct: 0.9, asr: 1.0, repeat: 0.4, digress: 0.25, dialect: 1.0 };
  var STICKY = 0.6, DEBT_MAX = 2.0, AGE_MAX = 2;
  // 配合类意图：回复本身是在“照做 / 确认 / 找东西”，后面不接跑题句
  var COOP_INTENTS = ['coop_step', 'fake_progress', 'confirm_intel', 're_ask'];
  var DIGITS = '0123456789０１２３４５６７８９*＊', CN_NUM = '零〇一二两三四五六七八九十百千万亿', CN_UNIT = '块元';
  var ASCII_TAIL = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.:/@-';
  var SENT_END = '。！？!?', PUNCT = '，,。！？!?；;：:、…~～', CLAUSE_SEP = '，,。！？!?；;…~～', ECHO_SEP = '，,。！？!?；;：:…~～ \t\n';
  var ECHO_BAD = '0123456789０１２３４５６７８９*＊ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz';
  var has = function (o, k) { return Object.prototype.hasOwnProperty.call(o, k); };
  var chars = function (s) { return Array.from(String(s)); };
  var clen = function (s) { return chars(s).length; };
  var inSet = function (set, ch) { return ch !== '' && ch !== undefined && set.indexOf(ch) >= 0; };
  var rstripWs = function (s) { return s.replace(/\s+$/, ''); };
  var endsQ = function (s) { return /[？?]$/.test(rstripWs(s)); };
  function pyRound(x) { var f = Math.floor(x), d = x - f; if (d > 0.5) return f + 1; if (d < 0.5) return f; return f % 2 === 0 ? f : f + 1; }

  function mulberry32(seed) {
    var a = seed >>> 0;
    return function () {
      a = (a + 0x6D2B79F5) >>> 0;
      var t = a;
      t = Math.imul(t ^ (t >>> 15), t | 1);
      t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }
  function Rand(seed, rng) {
    this.r = rng || mulberry32(seed === undefined || seed === null ? Math.floor(Math.random() * 4294967296) : seed);
  }
  Rand.prototype.random = function () { return this.r(); };
  Rand.prototype.below = function (n) { return Math.floor(this.r() * n); };
  Rand.prototype.choice = function (seq) { return seq[this.below(seq.length)]; };

  var isHan = function (c) { return c >= '\u4e00' && c <= '\u9fff'; };
  function hanCount(text) { return chars(text).filter(isHan).length; }
  // 在字符数组 a 里找 word（字符数组）的全部不重叠出现位置
  function findAll(a, word) {
    var w = chars(word), out = [];
    if (!w.length) return out;
    var i = 0;
    while (i + w.length <= a.length) {
      var ok = true;
      for (var k = 0; k < w.length; k++) if (a[i + k] !== w[k]) { ok = false; break; }
      if (ok) { out.push(i); i += w.length; } else i++;
    }
    return out;
  }
  var isLetter = function (c) { return (c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z'); };
  function protectedMask(text, keep) {
    var a = Array.isArray(text) ? text : chars(text), n = a.length, m = new Array(n).fill(false), i = 0, x;
    while (i < n) {
      var c = a[i], j = i, k;
      if (c === '{') {
        k = i + 1;
        while (k < n && a[k] !== '{' && a[k] !== '}') k++;
        if (k < n && a[k] === '}') j = k + 1;
      } else if (inSet(DIGITS, c)) {
        while (j < n && inSet(DIGITS, a[j])) j++;
      } else if (isLetter(c)) {
        while (j < n && inSet(ASCII_TAIL, a[j])) j++;
      } else if (inSet(CN_NUM, c)) {
        k = i;
        while (k < n && inSet(CN_NUM, a[k])) k++;
        if (k < n && inSet(CN_UNIT, a[k])) j = k + 1;
        else if (k - i >= 3) j = k;
      }
      if (j > i) { for (x = i; x < j; x++) m[x] = true; i = j; } else i++;
    }
    (keep || []).forEach(function (w) {
      if (!w) return;
      var L = clen(w);
      findAll(a, w).forEach(function (s) { for (var y = s; y < s + L; y++) m[y] = true; });
    });
    return m;
  }
  function halo(m) { return m.map(function (v, i) { return v || (i > 0 && m[i - 1]) || (i + 1 < m.length && m[i + 1]); }); }
  // 紧跟在 nameCues（户名、收款人……）后面的那个字符：不改标点、不在那里断句 / 拆条 / 放表情
  function cueFrozen(a) {
    var m = new Array(a.length).fill(false);
    CF.nameCues.forEach(function (w) {
      var L = clen(w);
      findAll(a, w).forEach(function (s) { if (s + L < a.length) m[s + L] = true; });
    });
    return m;
  }
  function digitSafePositions(text, keep) { return halo(protectedMask(text, keep)).map(function (v) { return !v; }); }
  var any = function (arr, s, e) { for (var i = s; i < e; i++) if (arr[i]) return true; return false; };

  function resolve(name) {
    if (has(H.profiles, name) && name !== 'comment') return Object.assign({}, H.profiles[name]);
    for (var i = 0; i < C.personas.length; i++) {
      var p = C.personas[i];
      if (p.id === name && p.humanize && p.humanize.profile) {
        var o = Object.assign({}, p.humanize); var base = o.profile; delete o.profile;
        return Object.assign({}, H.profiles[base], o, { base: base });
      }
    }
    throw new Error('unknown profile: ' + name);
  }
  var PROFILES = {};
  Object.keys(H.profiles).forEach(function (k) { if (k !== 'comment') PROFILES[k] = H.profiles[k]; });

  /**
   * new Humanizer({ profile: 'wang', seed: 1 })：一个实例 = 一整场对话。
   * 选项与 Python 同名参数一一对应：intensity, seed, mode, dialect, ops, weights, digressions, keep, profile, maxTypos,
   * rng, handwriting, typoPer100, shapeTypos, punctStyle。
   */
  function Humanizer(opts) {
    opts = opts || {};
    var prof = opts.profile ? resolve(opts.profile) : {};
    var g = function (k, d) { return prof[k] === undefined || prof[k] === null ? d : prof[k]; };
    this.profile = opts.profile || null;
    this.intensity = Number(opts.intensity === undefined || opts.intensity === null ? g('intensity', 0.3) : opts.intensity);
    if (!(this.intensity >= 0 && this.intensity <= 1)) throw new Error('intensity must be within [0, 1]');
    this.mode = opts.mode || g('mode', 'chat');
    if (MODES.indexOf(this.mode) < 0) throw new Error('mode must be one of chat, voice');
    this.dialect = opts.dialect !== undefined && opts.dialect !== null ? opts.dialect : g('dialect', null);
    if (this.dialect !== null && !has(CF.dialect, this.dialect)) throw new Error('unknown dialect: ' + this.dialect);
    this.punctStyle = opts.punctStyle !== undefined && opts.punctStyle !== null ? opts.punctStyle : g('punctStyle', null);
    if (this.punctStyle !== null && PUNCT_STYLES.indexOf(this.punctStyle) < 0) throw new Error('bad punctStyle');
    var ops = opts.ops || prof.ops;
    if (!ops) {
      var drop = this.mode === 'chat' ? ['asr'] : (this.punctStyle ? [] : ['punct']);
      ops = OPS.filter(function (o) { return drop.indexOf(o) < 0; });
    }
    this.ops = {};
    var self = this;
    ops.forEach(function (o) { if (OPS.indexOf(o) < 0) throw new Error('unknown op: ' + o); self.ops[o] = true; });
    this.weights = Object.assign({}, g('weights', {}), opts.weights || {});
    this.digressions = (opts.digressions && opts.digressions.length ? opts.digressions : (g('digressions', null) && g('digressions', []).length ? g('digressions', []) : CF.digressions)).slice();
    this.keep = (opts.keep || []).concat(g('keep', []), CF.nameCues); // 人名提示词本身不写错
    this.handwriting = !!(opts.handwriting === undefined || opts.handwriting === null ? g('handwriting', false) : opts.handwriting);
    var shape = opts.shapeTypos === undefined || opts.shapeTypos === null ? g('shapeTypos', this.mode === 'chat') : opts.shapeTypos;
    this.shapeTypos = !!shape || this.handwriting;
    var tp = opts.typoPer100;
    if (tp === undefined || tp === null) {
      tp = g(this.handwriting ? 'handwritingTypoPer100' : 'typoPer100', null);
      if (tp === null && this.handwriting) tp = g('typoPer100', null);
      if (tp === null) tp = BASE_RATES.typo * this.intensity * (this.handwriting ? 3.0 : 1.0);
    }
    this.typoPer100 = Math.max(0, Number(tp) * (has(this.weights, 'typo') ? this.weights.typo : 1.0));
    this.maxTypos = opts.maxTypos !== undefined && opts.maxTypos !== null ? opts.maxTypos
      : Math.max(1 + pyRound(3 * this.intensity), Math.floor(this.typoPer100 * 0.4) + 1);
    this.selfRef = g('selfRef', []).slice();
    this.selfRefRate = Number(g('selfRefRate', 0));
    this.age = g('age', null);
    this.ageLines = this.age ? g('ageLines', []).slice() : [];
    this.ageRate = Number(g('ageRate', 0.08));
    this.apologies = g('apologies', []).slice();
    this.apologyRate = Number(g('apologyRate', 0));
    this.closings = g('closings', []).slice();
    this.closingRate = Number(g('closingRate', 0));
    this.emojis = g('emojis', []).slice();
    this.emojiRate = Number(g('emojiComma', 0));
    this.splitRate = Number(g('split', 0));
    this.rng = new Rand(opts.seed, opts.rng);
    this.typoMap = {};
    this._debt = 0; this._turn = 0; this._ageUsed = 0; this._lastExtra = '';
    this._usedDigressions = []; this._usedApologies = [];
    var words = [];
    [[CF.placeWords, 4.0], [CF.commonWords, 3.0], [CF.homophoneWords, 2.0]].forEach(function (tw) {
      Object.keys(tw[0]).forEach(function (k) { words.push([k, tw[0][k], tw[1]]); });
    });
    this._words = words.sort(function (a, b) { return clen(b[0]) - clen(a[0]); });
  }
  var P = Humanizer.prototype;

  P._p = function (op, scale) {
    var w = has(this.weights, op) ? this.weights[op] : 1.0;
    return Math.max(0, Math.min(1, BASE_RATES[op] * w * this.intensity * (scale === undefined ? 1 : scale)));
  };
  P._hit = function (p) { return p > 0 && this.rng.random() < p; };
  P._core = function (text) { return protectedMask(text, this.keep); };
  P._prepend = function (piece, text, joint) {
    var core = this._core(text);
    if (text && core[0]) return null;
    return piece + joint + text;
  };
  P._append = function (text, piece, joint) {
    if (joint === undefined) joint = '。';
    var a = chars(text), core = this._core(a), i = a.length;
    while (i > 0 && inSet(PUNCT, a[i - 1])) i--;
    if (i < a.length) {
      if (i > 0 && core[i - 1]) return text + piece;
      return a.slice(0, i).join('') + joint + piece;
    }
    if (i > 0 && core[i - 1]) return null;
    return text + joint + piece;
  };
  P._attach = function (text, piece, prefix, preJoint, postJoint) {
    var a = prefix ? this._prepend(piece, text, preJoint) : this._append(text, piece, postJoint);
    if (a === null) a = prefix ? this._append(text, piece, postJoint) : this._prepend(piece, text, preJoint);
    return a;
  };
  P._take = function (pool, used) {
    var left = pool.filter(function (x) { return used.indexOf(x) < 0; });
    if (!left.length) left = pool.slice();
    if (left.length === pool.length) used.length = 0;
    var x = this.rng.choice(left);
    used.push(x);
    return x;
  };

  P._dialect = function (text) {
    if (!this.dialect) return [text, false];
    var p = this.intensity > 0 ? Math.min(1, 0.5 + 0.5 * this._p('dialect')) : 0, changed = false, self = this;
    var pairs = CF.dialect[this.dialect].slice().sort(function (x, y) { return clen(y[0]) - clen(x[0]); });
    pairs.forEach(function (pr) {
      var src = pr[0], alts = pr[1], a = chars(text), h = halo(self._core(a)), out = [], i = 0, L = clen(src);
      findAll(a, src).forEach(function (s) {
        var e = s + L;
        if (any(h, s, e) || !self._hit(p)) return;
        out.push(a.slice(i, s).join(''));
        out.push(self.rng.choice(alts));
        i = e; changed = true;
      });
      out.push(a.slice(i).join(''));
      text = out.join('');
    });
    return [text, changed];
  };

  P._selfref = function (text) {
    if (!this.selfRef.length || this.selfRefRate <= 0) return [text, false];
    var a = chars(text), h = halo(this._core(a)), out = [], n = 0;
    for (var i = 0; i < a.length; i++) {
      var nxt = i + 1 < a.length ? a[i + 1] : '', prv = i > 0 ? a[i - 1] : '';
      if (a[i] === '我' && nxt !== '们' && nxt !== '我' && prv !== '自' && prv !== '我' && !h[i] && n < 2 && this._hit(this.selfRefRate)) {
        out.push(this.rng.choice(this.selfRef)); n++;
      } else out.push(a[i]);
    }
    return [out.join(''), n > 0];
  };

  P._echo = function (context) {
    var ctx = chars(context || ''), keys = [], taken = new Array(ctx.length).fill(false);
    CF.echoKeywords.slice().sort(function (x, y) { return clen(y) - clen(x); }).forEach(function (k) {
      var L = clen(k);
      findAll(ctx, k).forEach(function (s) {
        if (!any(taken, s, s + L)) { keys.push([s, k]); for (var i = s; i < s + L; i++) taken[i] = true; }
      });
    });
    keys.sort(function (x, y) { return x[0] - y[0]; });
    var uniq = [];
    keys.forEach(function (k) { if (uniq.indexOf(k[1]) < 0) uniq.push(k[1]); });
    if (uniq.length) return this.rng.choice(uniq);
    var parts = [], cur = '';
    ctx.concat([' ']).forEach(function (ch) {
      if (inSet(ECHO_SEP, ch)) { if (cur) parts.push(cur); cur = ''; } else cur += ch;
    });
    parts = parts.filter(function (x) {
      var L = clen(x);
      return L >= 2 && L <= 8 && !chars(x).some(function (c) { return inSet(ECHO_BAD, c); }) &&
        !CF.echoAvoid.some(function (w) { return x.indexOf(w) >= 0; });
    });
    if (!parts.length) return null;
    return this.rng.choice(parts);
  };

  P._repeat = function (text, context) {
    if (!this._hit(this._p('repeat'))) return [text, false];
    var echo = context ? this._echo(context) : null, out, line;
    if (echo) {
      line = this.rng.choice(CF.confirmTemplates).split('{echo}').join(echo);
      var lc = chars(line), joint = inSet(PUNCT, lc[lc.length - 1]) ? '' : '，';
      out = this._attach(text, line, this.rng.random() < 0.6, joint, '。');
    } else {
      line = this.rng.choice(CF.confirmGeneric);
      out = this._append(text, line, '，');
    }
    return out !== null ? [out, true] : [text, false];
  };

  P._digress = function (text, intent) {
    if (!this.digressions.length || COOP_INTENTS.indexOf(intent) >= 0 || !this._hit(this._p('digress'))) return [text, false];
    var d = this._take(this.digressions, this._usedDigressions);
    var out = this._attach(text, d, this.rng.random() < 0.5, '……', '。');
    return out !== null ? [out, true] : [text, false];
  };

  P._extras = function (text) {
    var done = [], me = this.selfRef.length ? this.selfRef[0] : '我', out, line;
    if (this.ageLines.length && this._ageUsed < AGE_MAX && this._turn >= 2 && this._lastExtra !== 'age' && this._hit(this.ageRate)) {
      line = this.rng.choice(this.ageLines).split('{self}').join(me).split('{age}').join(String(this.age));
      out = this._append(text, line, '，');
      if (out !== null) { text = out; this._ageUsed++; done.push('age'); }
    }
    if (this.apologies.length && this._lastExtra !== 'apology' && !done.length && this._hit(this.apologyRate)) {
      line = this._take(this.apologies, this._usedApologies);
      out = this._prepend(line, text, '，');
      if (out !== null) { text = out; done.push('apology'); }
    }
    if (this.closings.length && this._lastExtra !== 'closing' && !done.length && !endsQ(text) && this._hit(this.closingRate)) {
      out = this._append(text, this.rng.choice(this.closings), '，');
      if (out !== null) { text = out; done.push('closing'); }
    }
    this._lastExtra = done.length ? done[0] : '';
    return [text, done];
  };

  P._typo = function (text) {
    var rate = this.typoPer100, self = this;
    if (rate <= 0 || this.maxTypos <= 0) return [text, 0];
    var a = chars(text);
    var lam = hanCount(text) * rate / 100.0;
    this._debt = Math.min(this._debt + lam, lam + DEBT_MAX);
    var cap = Math.min(this.maxTypos, Math.max(1, Math.floor(this._debt + 1.0)));
    var h = halo(this._core(a)), taken = new Array(a.length).fill(false), sites = [];
    CF.nameCues.forEach(function (w) { // 人名提示词后面 3 个字不写错（错字可能被提取器读成人名）
      var L = clen(w);
      findAll(a, w).forEach(function (st) { for (var x = st + L; x < Math.min(a.length, st + L + 3); x++) h[x] = true; });
    });
    this._words.forEach(function (wd) {
      var L = clen(wd[0]);
      findAll(a, wd[0]).forEach(function (s) {
        var e = s + L;
        if (!any(h, s, e) && !any(taken, s, e)) {
          sites.push([s, e, wd[0], wd[1], wd[2]]);
          for (var k = s; k < e; k++) taken[k] = true;
        }
      });
    });
    for (var i = 0; i < a.length; i++) {
      if (h[i] || taken[i]) continue;
      var ch = a[i], alts = has(CF.homophoneChars, ch) ? CF.homophoneChars[ch].slice() : [], w = 1.0;
      if (this.shapeTypos && has(CF.shapeChars, ch)) alts = alts.concat(CF.shapeChars[ch]);
      if (this.handwriting && has(CF.handwritingChars, ch)) { alts = alts.concat(CF.handwritingChars[ch]); w = 2.0; }
      if (alts.length) sites.push([i, i + 1, ch, alts, w]);
    }
    var forced = [], rest = [];
    sites.forEach(function (st) {
      if (has(self.typoMap, st[2])) {
        if (forced.length < cap && self.rng.random() < STICKY) forced.push(st);
        else rest.push([st[0], st[1], st[2], st[3], st[4] * 8.0]);
      } else rest.push(st);
    });
    var k = Math.floor(this._debt - forced.length + this.rng.random());
    k = Math.max(0, Math.min(k, this.maxTypos - forced.length, rest.length));
    var chosen = forced.slice();
    for (var t = 0; t < k; t++) {
      var total = 0.0, j;
      for (j = 0; j < rest.length; j++) total += rest[j][4];
      var r = this.rng.random() * total, idx = rest.length - 1;
      for (j = 0; j < rest.length; j++) { r -= rest[j][4]; if (r < 0) { idx = j; break; } }
      chosen.push(rest.splice(idx, 1)[0]);
    }
    this._debt = Math.max(this._debt - chosen.length, -DEBT_MAX);
    var reps = chosen.map(function (c) {
      var rep = has(self.typoMap, c[2]) ? self.typoMap[c[2]] : null;
      if (rep === null) { rep = self.rng.choice(c[3]); self.typoMap[c[2]] = rep; }
      return [c[0], c[1], rep];
    });
    reps.slice().sort(function (x, y) { return y[0] - x[0]; }).forEach(function (rp) {
      a = a.slice(0, rp[0]).concat(chars(rp[2]), a.slice(rp[1]));
    });
    return [a.join(''), reps.length];
  };

  P._asr = function (text) {
    if (!this._hit(this._p('asr'))) return [text, false];
    var segs = [], cur = '', sep = '', self = this;
    chars(text).forEach(function (ch) {
      if (inSet(CLAUSE_SEP, ch)) sep += ch;
      else { if (sep) { segs.push([cur, sep]); cur = ''; sep = ''; } cur += ch; }
    });
    segs.push([cur, sep]);
    var clean = [], lead = '';
    segs.forEach(function (cs) {
      if (cs[0].trim()) clean.push([cs[0].trim(), cs[1]]);
      else if (clean.length) clean[clean.length - 1][1] += cs[0] + cs[1];
      else lead += cs[0] + cs[1];
    });
    if (!clean.length) return [text, false];
    var pFill = 0.45 * this.intensity, out = [];
    clean.forEach(function (cs, i) {
      var c = cs[0];
      if (i > 0 && !self._core(c)[0] && self._hit(pFill)) c = self.rng.choice(CF.asrFillers) + c;
      out.push(c);
    });
    if (this._hit(0.35 * this.intensity)) {
      var j = this.rng.below(out.length);
      for (var q = 0; q < CF.stutterWords.length; q++) {
        var w = CF.stutterWords[q];
        if (out[j].indexOf(w) === 0) { out[j] = w + out[j]; break; }
      }
    }
    var seps = this.punctStyle === 'comma' ? ['，', '，', ''] : this.punctStyle === 'none' ? [' ', ' ', ''] : [' ', '，', ''], s = out[0];
    for (var i = 1; i < out.length; i++) {
      var pick = this.rng.choice(seps);
      var pc = this._core(out[i - 1]);
      var endsCue = CF.nameCues.some(function (w) { return out[i - 1].slice(-w.length) === w; });
      if (pc[pc.length - 1] || this._core(out[i])[0] || endsCue) pick = clean[i - 1][1];
      s += pick + out[i];
    }
    var sc = this._core(s);
    if (endsQ(text) && this.rng.random() < 0.5 && !sc[sc.length - 1]) s += '？';
    return [s, true];
  };

  P._restyle = function (text, fn) {
    var a = chars(text), core = this._core(a), fz = cueFrozen(a), n = a.length;
    return a.map(function (ch, i) {
      var adj = core[i] || (i > 0 && core[i - 1]) || (i + 1 < n && core[i + 1]) || fz[i];
      return adj ? ch : fn(ch);
    }).join('');
  };
  P._stripEdges = function (text, set) {
    var a = chars(text), core = this._core(a), lo = 0, hi = a.length;
    while (lo < hi && inSet(set, a[lo]) && !(lo + 1 < a.length && core[lo + 1])) lo++;
    while (hi > lo && inSet(set, a[hi - 1]) && !(hi - 2 >= 0 && core[hi - 2])) hi--;
    return a.slice(lo, hi).join('');
  };
  function collapse(text, sep) {
    var out = [];
    chars(text).forEach(function (ch) { if (!(ch === sep && out.length && out[out.length - 1] === sep)) out.push(ch); });
    return out.join('');
  }
  P._punct = function (text) {
    var newT, a, core, b;
    if (this.punctStyle) {
      var q = endsQ(text);
      if (this.punctStyle === 'comma') {
        newT = this._restyle(text, function (c) { return inSet(PUNCT, c) || c === ' ' ? '，' : c; });
        newT = this._stripEdges(collapse(newT, '，'), '，');
        var na = chars(newT), nc = this._core(na);
        if (q && na.length && !inSet('？?', na[na.length - 1]) && !nc[nc.length - 1]) newT += '？';
      } else {
        newT = this._restyle(text, function (c) { return inSet(PUNCT, c) ? ' ' : c; });
        newT = this._stripEdges(collapse(newT, ' '), ' ');
      }
      return [newT, this.punctStyle];
    }
    if (!this._hit(this._p('punct'))) return [text, null];
    var styles = ['drop_final', 'comma_space', 'all_comma', 'double', 'halfwidth', 'tilde'];
    if (this.intensity >= 0.6) styles.push('strip_all');
    var style = this.rng.choice(styles);
    a = chars(text); core = this._core(a);
    if (style === 'drop_final') {
      b = a.length;
      while (b > 0 && inSet(SENT_END, a[b - 1]) && !(b - 2 >= 0 && core[b - 2])) b--;
      newT = a.slice(0, b).join('');
    } else if (style === 'comma_space') {
      newT = this._restyle(text, function (c) { return inSet('，,', c) ? ' ' : c; });
    } else if (style === 'all_comma') {
      newT = this._restyle(text, function (c) { return inSet('。！!；;', c) ? '，' : c; });
      if (/，$/.test(newT)) newT = this._stripEdges(newT, '，');
    } else if (style === 'double') {
      newT = this._restyle(text, function (c) { return inSet('？?！!', c) ? c + c : c; });
      if (newT === text) {
        for (var i = 0; i < a.length; i++) {
          if (a[i] === '。' && !(core[i] || (i > 0 && core[i - 1]) || (i + 1 < a.length && core[i + 1]))) {
            newT = a.slice(0, i).join('') + '。。。' + a.slice(i + 1).join(''); break;
          }
        }
      }
    } else if (style === 'halfwidth') {
      var tr = { '，': ',', '。': '.', '！': '!', '？': '?', '：': ':', '；': ';' };
      newT = this._restyle(text, function (c) { return has(tr, c) ? tr[c] : c; });
    } else if (style === 'tilde') {
      if (a.length && inSet('。！!', a[a.length - 1])) newT = a.length >= 2 && core[a.length - 2] ? text : a.slice(0, -1).join('') + '~';
      else newT = a.length && core[a.length - 1] ? text : text + '~';
    } else {
      newT = this._restyle(text, function (c) { return inSet(PUNCT, c) ? ' ' : c; });
      newT = this._stripEdges(collapse(newT, ' '), ' ');
    }
    return [newT, style];
  };

  P._safeSeps = function (a, set) {
    var core = this._core(a), fz = cueFrozen(a), out = [];
    for (var i = 1; i < a.length - 1; i++) if (inSet(set, a[i]) && !(core[i - 1] || core[i] || core[i + 1] || fz[i])) out.push(i);
    return out;
  };
  P._emoji = function (text) {
    if (!this.emojis.length || !this._hit(this.emojiRate)) return [text, false];
    var a = chars(text), pos = this._safeSeps(a, '，, ');
    if (!pos.length) return [text, false];
    var i = this.rng.choice(pos);
    return [a.slice(0, i).join('') + this.rng.choice(this.emojis) + a.slice(i + 1).join(''), true];
  };
  P._split = function (text) {
    if (!this._hit(this.splitRate)) return [text];
    var a = chars(text), cands = this._safeSeps(a, '，,。！？!?；; '), cuts = [];
    var want = this.rng.random() < 0.35 ? 2 : 1;
    var slice = function (s, e) { return a.slice(s, e).join(''); };
    for (var t = 0; t < want; t++) {
      var ok = cands.filter(function (p) {
        if (cuts.indexOf(p) >= 0) return false;
        var bounds = cuts.concat([p]).sort(function (x, y) { return x - y; }), prev = 0, pieces = [];
        bounds.forEach(function (b) { pieces.push(slice(prev, b)); prev = b + 1; });
        pieces.push(slice(prev, a.length));
        return pieces.every(function (x) { return hanCount(x) >= 2; });
      });
      if (!ok.length) break;
      cuts.push(this.rng.choice(ok));
    }
    if (!cuts.length) return [text];
    var parts = [], prev = 0;
    cuts.slice().sort(function (x, y) { return x - y; }).forEach(function (b) {
      parts.push(slice(prev, b) + (inSet('？?', a[b]) ? a[b] : ''));
      prev = b + 1;
    });
    parts.push(slice(prev, a.length));
    return parts.map(function (x) { return x.trim(); });
  };

  /** 对一条回复做真人化；context 是对方上一条消息；intent 是规则引擎意图（可选，配合类不接跑题句）。返回 { text, ops, parts }。 */
  P.apply = function (text, context, intent) {
    text = String(text === undefined || text === null ? '' : text);
    if (this.intensity <= 0 || !text.trim()) return { text: text, ops: [], parts: [text] };
    this._turn++;
    var applied = [], r;
    if (this.ops.dialect) { r = this._dialect(text); text = r[0]; if (r[1]) applied.push('dialect'); }
    if (this.ops.selfref) { r = this._selfref(text); text = r[0]; if (r[1]) applied.push('selfref'); }
    if (this.ops.repeat) { r = this._repeat(text, context); text = r[0]; if (r[1]) applied.push('repeat'); }
    if (this.ops.digress) { r = this._digress(text, intent); text = r[0]; if (r[1]) applied.push('digress'); }
    if (this.ops.extras) { r = this._extras(text); text = r[0]; applied = applied.concat(r[1]); }
    if (this.ops.typo) { r = this._typo(text); text = r[0]; if (r[1]) applied.push('typo:' + r[1]); }
    if (this.ops.asr) { r = this._asr(text); text = r[0]; if (r[1]) applied.push('asr'); }
    if (this.ops.punct) { r = this._punct(text); text = r[0]; if (r[1]) applied.push('punct:' + r[1]); }
    if (this.ops.emoji) { r = this._emoji(text); text = r[0]; if (r[1]) applied.push('emoji'); }
    var parts = this.ops.split ? this._split(text) : [text];
    if (parts.length > 1) applied.push('split:' + parts.length);
    return { text: parts.join('\n'), ops: applied, parts: parts };
  };

  function humanize(text, opts) {
    opts = opts || {};
    return new Humanizer(opts).apply(text, opts.context, opts.intent).text;
  }

  return { Humanizer: Humanizer, humanize: humanize, resolve: resolve, PROFILES: PROFILES, OPS: OPS, BASE_RATES: BASE_RATES,
    protectedMask: protectedMask, cueFrozen: cueFrozen, digitSafePositions: digitSafePositions, hanCount: hanCount, mulberry32: mulberry32, COOP_INTENTS: COOP_INTENTS };
});
