/*! DeepSuck — i18n.js：首页中英切换（中文为默认与权威版本）。Apache-2.0 */
(function () {
  'use strict';
  var EN = {
    'nav.how': 'How', 'nav.menu': 'Menu', 'nav.gh': 'Star on GitHub', 'nav.sc': 'Scenarios', 'nav.ethics': 'Ethics', 'nav.oss': 'Open source', 'nav.demo': 'Try the sandbox', 'nav.intel': 'Intel library',
    'hero.kicker': 'Open source · defensive research · Chinese scenarios first',
    'hero.title': 'Let scammers waste their time<br><em>on an AI instead</em>',
    'hero.lead': 'DeepSuck is an open-source anti-scam "time-waster" bot. Playing personas like a muddled retired auntie, a hard-of-hearing grandpa or a curious student, it misunderstands, asks to repeat, fakes phone trouble — while extracting the bank accounts, wallet addresses, phone numbers and URLs scammers reveal, masked, for prevention and early warning.',
    'chip1': 'Fully static · no API key', 'chip2': 'In-browser rule engine', 'chip3': 'Optional Qwen (Alibaba Bailian)', 'chip4': 'Intel masked by default',
    'cta.demo': 'Play the scammer', 'cta.oss': 'Contribute', 'cta.intel': 'Scam intel library', 'cta.gh': 'Star on GitHub',
    'how.title': 'How it works', 'how.sub': 'Five stages, all in your browser (rule engine). With an LLM, text is masked locally before it is sent.',
    's1.t': 'Lure', 's1.d': 'Appears as a "potential victim". Deployers can attach it to decoy numbers or report-forwarding channels. It never contacts real people first.',
    's2.t': 'Stall', 's2.d': 'Misunderstand, ask to repeat, fake a frozen phone, go look for reading glasses… every turn costs the scammer time.',
    's3.t': 'Extract', 's3.d': 'Detects bank cards, phones, QQ/WeChat/Alipay, BTC/ETH/TRON addresses, URLs, and tactics like "safe account" or OTP requests.',
    's4.t': 'Redact', 's4.d': 'All intel is masked before display and export, e.g. 622202*********1234, 138****5678, 0x12ab...9f3e.',
    's5.t': 'Warn', 's5.d': 'Produces a structured JSON intel report that can be submitted (per the publishing policy) to the <a href="intel.html">public scam intel library</a> for anyone to search.',
    'sc.title': 'Seven common Chinese scam scenarios', 'sc.sub': 'In the sandbox you play the scammer and the bot plays the "victim". Each scenario ships with one-click sample lines and tactic tags.',
    'c1.t': 'Fake customer service · refunds', 'c1.d': '"Double compensation for a defective item", "membership auto-charge" — pushes app downloads, screen sharing, OTP codes.',
    'c2.t': 'Fake police · "safe account"', 'c2.d': '"You are suspected of money laundering", "keep it secret", "move funds to a safe account for checks".',
    'c3.t': 'Pig-butchering · romance/investment', 'c3.d': 'Romance first, then an "insider platform" with a "mentor", pushing USDT deposits.',
    'c4.t': 'Task / click-farming rebates', 'c4.d': '"Like videos, paid daily", a ¥5 starter bonus, then "advance payment tasks", "complete 3 combo orders to withdraw", "unfreeze fees".',
    'c5.t': 'Fake loans · credit repair', 'c5.d': '"Instant unsecured loan", then "card number typo froze your funds", "show repayment ability by transferring", "credit repair fee".',
    'c6.t': 'Fake boss / acquaintance', 'c6.d': '"It\'s your boss, new number", "in a meeting, don\'t call", "advance a deposit to our partner for me". Auntie asks who killed the office orchid.',
    'c7.t': '"Cancel your campus loan"', 'c7.d': '"You opened a student loan, cancel it or ruin your credit" — then borrow from loan apps and move it to a "verification account".',
    'c8.t': 'Public scam intel library', 'c8.d': 'Scam phones, wallets, URLs/apps and scripts published in full; bank cards and names partially masked. Search, download JSON/CSV, contribute.',
    'eng.title': 'Zero cost, works out of the box', 'eng.sub': 'The default rule/template persona engine runs entirely in the browser: no API key, no server. Host it on GitHub Pages, Cloudflare Pages or Aliyun OSS.',
    'eng.llm': 'Want more natural dialogue? Optionally plug in Alibaba Bailian (Qwen qwen-plus) or any OpenAI-compatible model through the bundled zero-dependency Node proxy — your API key stays in your own server\'s .env. Off by default.',
    'eth.title': 'Ethics & usage', 'eth.sub': 'DeepSuck is for defense, research and education only. These rules live in the code and the contribution guide.',
    'e1': '<b>Never initiates:</b> the bot never contacts real people; it only responds to scammers who come to it. In the demo, you play the scammer.',
    'e2': '<b>Masked by default:</b> accounts, phones and addresses are masked by the redaction module for display and export; raw text lives only in page memory.',
    'e3': '<b>No real data:</b> personas never give real OTPs, card numbers, passwords or IDs; LLM output is safety-filtered.',
    'e4': '<b>No vigilantism:</b> no harassment, doxxing, revenge, "reverse scamming" or attacking any system.',
    'e5': '<b>Leave it to professionals:</b> report fraud to 110 or the national anti-fraud hotline 96110 (China). Intel is only a lead.',
    'e6': '<b>Compliance first:</b> before connecting real channels (phone, IM), assess PIPL, the Anti-Telecom-Fraud Law and obtain authorization.',
    'oss.title': 'Build it together', 'oss.sub': 'Apache-2.0. Plain HTML/CSS/JS with clear modules.',
    'o1': 'Add scenarios and (masked) real-world script samples', 'o2': 'Design more exhausting personas and stalling tactics',
    'o3': 'Improve extractor regexes and tactic rules, add tests', 'o4': 'Roadmap: LLM personas, voice calls (ASR/TTS), intel-sharing API',
    'disc': '<b>Disclaimer:</b> DeepSuck is an independent open-source community project. Provided "as is" for anti-fraud research and education; all accounts, phones, addresses and URLs in the demo are fictitious test data. Users must comply with local laws.',
    'foot.soon': '(not live yet)', 'foot.110': 'Scam? Call 110 / 96110'
  };
  var nodes = document.querySelectorAll('[data-i18n]');
  var ZH = [];
  nodes.forEach(function (n, i) { ZH[i] = n.innerHTML; });
  function apply(lang) {
    nodes.forEach(function (n, i) {
      var k = n.getAttribute('data-i18n');
      n.innerHTML = lang === 'en' && EN[k] ? EN[k] : ZH[i];
    });
    document.documentElement.lang = lang === 'en' ? 'en' : 'zh-CN';
    document.querySelectorAll('.lang-toggle').forEach(function (b) { b.textContent = lang === 'en' ? '中文' : 'EN'; });
    try { localStorage.setItem('deepsuck.lang', lang); } catch (e) {}
  }
  var cur = 'zh';
  try { cur = localStorage.getItem('deepsuck.lang') || 'zh'; } catch (e) {}
  if (/[?&]lang=en/.test(location.search)) cur = 'en';
  if (cur === 'en') apply('en');
  document.querySelectorAll('.lang-toggle').forEach(function (btn) {
    btn.addEventListener('click', function () { cur = cur === 'en' ? 'zh' : 'en'; apply(cur); });
  });
})();
