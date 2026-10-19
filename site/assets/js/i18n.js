/*! DeepSuck — i18n.js：全站中英切换（首页、沙盒、情报库、404；中文为默认与权威版本）。Apache-2.0 */
(function () {
  'use strict';
  var EN = {
    'nav.how': 'How', 'nav.menu': 'Menu', 'hero.sample': 'From anti-scam PSAs<span class="hc-x"> · fictional numbers</span>', 'nav.gh': 'Star on GitHub', 'nav.sc': 'Scenarios', 'nav.ethics': 'Ethics', 'nav.oss': 'Open source', 'nav.demo': 'Try the sandbox', 'nav.intel': 'Intel library', 'nav.blog': 'Blog',
    'hero.kicker': 'Open source · defensive research · Chinese scenarios first',
    'hero.title': 'Let scammers waste their time<br><em>on an AI instead</em>',
    'hero.lead': 'DeepSuck is an open-source anti-scam "time-waster" bot. Playing ordinary-sounding personas, it replies slowly, double-checks and sometimes mishears — while extracting the bank accounts, wallet addresses, phone numbers and URLs scammers reveal, masked, for prevention and early warning.',
    'chip1': 'Fully static · no API key', 'chip2': 'In-browser rule engine', 'chip3': 'Optional Qwen (Alibaba Bailian)', 'chip4': 'Intel masked by default',
    'cta.demo': 'Play the scammer', 'cta.oss': 'Contribute', 'cta.intel': 'Scam intel library', 'cta.gh': 'Star on GitHub',
    'how.title': 'How it works', 'how.sub': 'Five stages, all in your browser (rule engine). With an LLM, text is masked locally before it is sent.',
    's1.t': 'Lure', 's1.d': 'Appears as a "potential victim". Deployers can attach it to decoy numbers or report-forwarding channels. It never contacts real people first.',
    's2.t': 'Stall', 's2.d': 'Reply slowly, double-check, sometimes mishear. Every turn costs the scammer time.',
    's3.t': 'Extract', 's3.d': 'Detects bank cards, phones, QQ/WeChat/Alipay, BTC/ETH/TRON addresses, URLs, and tactics like "safe account" or OTP requests.',
    's4.t': 'Redact', 's4.d': 'In the sandbox, all intel is masked before display and export, e.g. 622202*********1234 (bank cards keep only the first 6 and last 4 digits, per PCI DSS), 138****5678, 0x12ab...9f3e. Submissions to the library follow the <a href="intel.html#policy">publishing policy</a>.',
    's5.t': 'Warn', 's5.d': 'Produces a structured JSON intel report that can be submitted (per the publishing policy) to the <a href="intel.html">public scam intel library</a> for anyone to search.',
    'sc.title': 'Seven common Chinese scam scenarios', 'sc.sub': 'In the sandbox you play the scammer and the bot plays the "victim". Each scenario ships with one-click sample lines and tactic tags.',
    'c1.t': 'Fake customer service · refunds', 'c1.d': '"Double compensation for a defective item", "membership auto-charge" — pushes app downloads, screen sharing, OTP codes.',
    'c2.t': 'Fake police · "safe account"', 'c2.d': '"You are suspected of money laundering", "keep it secret", "move funds to a safe account for checks".',
    'c3.t': 'Pig-butchering · romance/investment', 'c3.d': 'Romance first, then an "insider platform" with a "mentor", pushing USDT deposits.',
    'c4.t': 'Task scam (fake order-brushing rebates)', 'c4.d': '"Like videos, paid daily", a ¥5 starter bonus, then "advance payment tasks", "complete 3 combo orders to withdraw", "unfreeze fees".',
    'c5.t': 'Fake loans · credit repair', 'c5.d': '"Instant unsecured loan", then "card number typo froze your funds", "show repayment ability by transferring", "credit repair fee".',
    'c6.t': 'Fake boss / acquaintance', 'c6.d': '"It\'s your boss, new number", "in a meeting, don\'t call", "advance a deposit to our partner for me". Auntie asks who killed the office orchid.',
    'c7.t': '"Cancel your campus loan"', 'c7.d': '"You opened a student loan, cancel it or ruin your credit" — then borrow from loan apps and move it to a "verification account".',
    'c8.t': 'Public scam intel library', 'c8.d': 'Scam phones, wallets, URLs/apps and scripts published in full; bank cards and names partially masked. Search, download JSON/CSV, contribute.',
    'eng.title': 'Zero cost, works out of the box', 'eng.sub': 'The default rule/template persona engine runs entirely in the browser: no API key, no server. Host it on GitHub Pages, Cloudflare Pages or Aliyun OSS.',
    'eng.llm': 'Want more natural dialogue? Optionally plug in Alibaba Bailian (Qwen qwen-plus) or any model that speaks a standard chat API through the bundled zero-dependency Node proxy — your API key stays in your own server\'s .env. Off by default.',
    'eth.title': 'Ethics & usage', 'eth.sub': 'DeepSuck is for defense, research and education only. These rules live in the code and the contribution guide.',
    'e1': '<b>Never initiates:</b> the bot never contacts real people; it only responds to scammers who come to it. In the demo, you play the scammer.',
    'e2': '<b>Masked by default:</b> accounts, phones and addresses are masked by the redaction module for display and export; raw text lives only in page memory.',
    'e3': '<b>No real data:</b> personas never give real OTPs, card numbers, passwords or IDs; LLM output is safety-filtered.',
    'e4': '<b>No vigilantism:</b> no harassment, doxxing, revenge, "reverse scamming" or attacking any system.',
    'e5': '<b>Leave it to professionals:</b> report fraud to 110 or the national anti-fraud hotline 96110 (China). Intel is only a lead.',
    'e6': '<b>Compliance first:</b> before connecting real channels (phone, IM), assess PIPL, the Anti-Telecom-Fraud Law and obtain authorization.',
    'cb.qs': 'Quick start',
    'cb.qs1': '# 1) Static only, no key needed',
    'cb.qs2': '# 2) Optional: plug in Qwen (Bailian)',
    'cb.qs3': '# edit .env and add DASHSCOPE_API_KEY',
    'cb.tree': 'Project layout',
    'cb.t1': '# Website: home, sandbox, intel (static)',
    'cb.t2': '# Rule engine, extraction, masking (in-browser)',
    'cb.t3': '# Scenarios, personas, tactic rules (shared JS / Python)',
    'cb.t4': '# Python core: extraction, masking, STIX export',
    'cb.t5': '# Voice demo: WebRTC / SIP, live ASR and TTS',
    'cb.t6': '# Optional Node proxy; key stays server-side',
    'cb.t7': '# Persona prompts and humanizer',
    'cb.t8': '# Scam script corpus (masked rewrites)',
    'cb.t9': '# Docker Compose + Caddy deployment',
    'cb.t10': '# node --test, cases shared with Python',
    'oss.title': 'Build it together', 'oss.sub': 'Apache-2.0. Plain HTML/CSS/JS with clear modules.',
    'o1': 'Add scenarios and (masked) real-world script samples', 'o2': 'Design more exhausting personas and stalling tactics',
    'o3': 'Improve extractor regexes and tactic rules, add tests', 'o4': 'Roadmap: LLM personas, voice calls (ASR/TTS), intel-sharing API',
    'disc': '<b>Disclaimer:</b> DeepSuck is an independent open-source community project. Provided "as is" for anti-fraud research and education; all accounts, phones, addresses and URLs in the demo are fictitious test data. Users must comply with local laws.',
    'foot.soon': '(not live yet)', 'foot.110': 'Scam? Call 110 / 96110', 'nav.skip': 'Skip to content',
    'nav.home.back': 'Back to home',
    'nav.home': 'Home',
    'role.retiree': 'Retiree',
    'role.mom': 'Stay-at-home mom',
    'role.graduate': 'Recent graduate',
    'role.owner': 'Small business owner',
    'role.scammer': 'Scammer',
    'clue.intel': 'Extracted intel (masked)',
    'clue.tactics': 'Scam tactics detected',
    'nav.voice.arrow': 'Voice demo ↗',
    'pl.title': 'Four personas',
    'pl.wang': '01 Auntie Wang · retiree',
    'pl.chen': '02 Xiao Chen\'s Mom · young mother',
    'pl.lin': '03 Xiao Lin · new graduate',
    'pl.zheng': '04 Boss Zheng · small shop owner',
    'tag.冒充客服': 'Fake customer service',
    'tag.诱导下载APP': 'Pushes app downloads',
    'tag.索要验证码': 'Asks for OTP codes',
    'tag.冒充公检法': 'Fake police/prosecutors',
    'tag.要求保密': 'Demands secrecy',
    'tag.安全账户': '"Safe account"',
    'tag.情感操控': 'Emotional manipulation',
    'tag.高收益承诺': 'Promises high returns',
    'tag.涉加密货币': 'Involves crypto',
    'tag.刷单返利': 'Task scam',
    'tag.刷单返利.full': 'Task scam (fake order-brushing rebates)',
    'tag.连单卡单': 'Combo orders, stuck orders',
    'tag.诱导垫付': 'Pushes advance payments',
    'tag.冒充金融机构': 'Fake financial institution',
    'tag.解冻费': 'Unfreezing fee',
    'tag.征信恐吓': 'Credit-score threats',
    'tag.冒充熟人': 'Poses as an acquaintance',
    'tag.阻止电话核实': 'Blocks phone verification',
    'tag.紧急借钱': 'Urgent loan request',
    'tag.冒充网贷客服': 'Fake loan-app support',
    'tag.诱导借贷': 'Pushes borrowing',
    'tag.共享屏幕': 'Screen sharing',
    'tag.完整公开': 'Published in full',
    'tag.部分打码': 'Partially masked',
    'tag.可申诉下架': 'Removal on appeal',
    'meta.home.title': 'DeepSuck · Open-source AI anti-scam "time-waster" bot',
    'meta.demo.title': 'Sandbox demo · DeepSuck',
    'nav.voice': 'Voice demo',
    'd.settings': 'Engine settings',
    'd.h1': 'DeepSuck sandbox demo: you play the scammer, the AI plays the "potential victim"',
    'd.setup': 'Scenario &amp; persona',
    'd.lblsc': 'Scam scenario',
    'd.lblpe': 'Bot persona',
    'd.input': 'Type a message as the scammer',
    'd.send': 'Send',
    'd.foot': '<b>You play the scammer</b>; the bot plays the "potential victim". Do not enter real personal information; all accounts, phone numbers and addresses in the samples are fictitious. Intel is processed only in this page\'s memory and shown masked.',
    'd.status': 'Stalling progress',
    'd.st.wall': 'Time stalled (live)',
    'd.st.est': 'Estimated scammer time',
    'd.st.msgs': 'Messages',
    'd.st.intel': 'Intel items',
    'd.risk': 'Risk score',
    'd.maskonly': 'Masked values only',
    'd.wait': 'Waiting for the scammer to slip up…',
    'd.blnote': 'URLs and wallet addresses are automatically checked against public blocklists: <a href="https://github.com/phishdestroy/destroylist" target="_blank" rel="noopener">destroylist</a> · <a href="https://github.com/Phishing-Database/Phishing.Database" target="_blank" rel="noopener">Phishing.Database</a> · <a href="https://github.com/scamsniffer/scam-database" target="_blank" rel="noopener">ScamSniffer</a> · OFAC SDN. Checks run locally and are for reference only.',
    'd.none': 'None yet',
    'd.end': 'End chat · build intel dashboard',
    'd.export': 'Export masked JSON',
    'd.reset': 'Start over',
    'd.dash': 'Intel dashboard',
    'd.submit': 'Submit to intel library',
    'd.new': 'New session',
    'd.close': 'Close',
    'd.submit.h': 'Submit to the public intel library',
    'd.submit.note': 'Generated per the <a href="intel.html#policy" target="_blank">publishing policy</a>: phones / wallet addresses / URLs / apps in full; bank cards / names / personal accounts masked. <b>Only submit scams you actually encountered</b> — do not submit the fictitious sample lines from the sandbox.',
    'd.copy': 'Copy',
    'd.submit.open': 'Open the intel submission template on GitHub',
    'd.submit.gh': 'Requires a GitHub account; the content is prefilled into the issue form and can be edited before submitting.',
    'd.cards': 'Intel cards (masked)',
    'd.ctx': 'Context clues',
    'd.profile': 'Tactic profile',
    'd.transcript': 'Full transcript (masked)',
    'd.dash.note': 'This dashboard was generated by the sandbox demo, for anti-fraud research and education only. If you encounter a real scam, call 110 or 96110.',
    'd.eng.rule': '<b>Rule engine (default, recommended)</b> — runs entirely in the browser, no key, zero cost',
    'd.eng.proxy': '<b>Server proxy · LLM</b> — the official site uses the online service live.deepsuck.si (daily trial quota; falls back to the rule engine once used up); self-hosted setups use this project\'s bundled server (npm start). The key lives only in the server\'s .env',
    'd.checking': 'Checking…',
    'd.eng.direct': '<b>Direct from browser · LLM (advanced, optional)</b> — only for personal use on your own machine',
    'd.base': 'Base URL (standard chat API)',
    'd.model': 'Model',
    'd.remember': 'Remember in this browser\'s localStorage (do not tick on a shared computer)',
    'd.warn': 'In direct mode the key sits in the browser, where anyone or any extension with access to this page may read it; some providers do not allow cross-origin calls. The "server proxy" is recommended. Conversations sent to the model are masked locally first.',
    'd.fallback': 'If an LLM call fails, it falls back to the rule engine automatically. Intel extraction and masking always happen locally, regardless of the engine selected.',
    'd.save': 'Save',
    'd.footer': 'DeepSuck · Apache-2.0 · For anti-fraud research and education only',
    'meta.intel.title': 'Public scam intel library · DeepSuck',
    'i.policy': 'Publishing policy',
    'i.report': 'How to report',
    'i.contribute': 'Submit intel',
    'i.lead': 'DeepSuck publishes the scam intel it collects: <b>scam phone numbers, crypto wallet addresses, scam URLs / app names and scripts</b> are published in full so anyone can search, block and warn; <b>bank card numbers, names and personal accounts</b> are only partially published — many receiving cards belong to ordinary people whose identities were misused or exploited.',
    'i.notice': 'Everything in the library is currently <b>sample data</b> (fictitious numbers, invalid addresses and the RFC 2606 reserved domain .example), shown to demonstrate the format and features; it <b>does not correspond to any real person or website</b>. Real intel is added only after review.',
    'i.alltypes': 'All types',
    'i.allsc': 'All scenarios',
    'i.loading': 'Loading…',
    'i.more': 'Show more',
    'i.data': 'Full data: <a href="data/intel.json">data/intel.json</a> · STIX 2.1: <a href="data/intel.stix.json">data/intel.stix.json</a> (no names/accounts/ID numbers; bank cards masked) · Subscribe: <a href="data/intel.rss">RSS</a> · <a href="data/intel.csv">CSV</a> (published entries only) · Schema: <a href="data/intel.schema.json">data/intel.schema.json</a> (<code>deepsuck.intel-library/v1</code>) · The download buttons export the current filtered results.',
    'i.license': 'Data released under <a href="https://creativecommons.org/licenses/by/4.0/legalcode" target="_blank" rel="noopener license">CC BY 4.0</a>, attribution: DeepSuck (deepsuck.si) · See <a href="https://github.com/deepsucksi/deepsuck/blob/main/DATA_LICENSE" target="_blank" rel="noopener">DATA_LICENSE</a> (code remains Apache-2.0)',
    'i.full1': 'Scam phone numbers (including 400/800, landlines and spoofed caller IDs)',
    'i.full2': 'Crypto wallet addresses (TRON / ETH / BTC, etc.)',
    'i.full3': 'Scam URLs and domains, scam app / platform names',
    'i.full4': 'Script and method patterns (no victim information)',
    'i.full.note': 'This is the scammers\' "infrastructure": the faster and more completely it is published, the more people can recognize it before answering the call or opening the link.',
    'i.mask1': 'Bank card numbers: per PCI DSS, only the first 6 (BIN) and last 4 digits are kept, e.g. <code>622202*********1234</code>, labeled with the account bank and the issuer and card type inferred from the BIN',
    'i.mask2': 'Receiving account names / names: surname only, e.g. <code>Wang**</code>',
    'i.mask3': 'ID card numbers: <code>110101********1234</code>',
    'i.mask4': 'Alipay / WeChat / QQ / email and other personal accounts: first and last 2 characters kept',
    'i.mask.note': 'Many "money-mule cards" and "receiving cards" belong to ordinary people whose identities were misused or who were tricked into renting out or lending their accounts (many are students and older people). Partial masking still helps matching without exposing innocent people to online harassment.',
    'i.r1': '<b>Only what scammers reveal themselves:</b> no victim information, no doxxing, no harassing or "striking back" at any number.',
    'i.r2': '<b>Every entry is traceable:</b> first/last seen, scenario, tactic tags, report count and source (sandbox, community submission, own decoy numbers).',
    'i.r3': '<b>Samples kept apart from real data:</b> sample entries are always marked <code>example: true</code> and "Sample data".',
    'i.r4': '<b>Intel is for reference only:</b> numbers may be recycled, changed or spoofed and cannot serve as evidence of guilt; the police\'s determination prevails.',
    'i.appeal': 'Removal and appeals',
    'i.ap0': 'If you believe an entry <b>wrongly lists your number, account or website</b> (e.g. the number was recycled and reassigned, your bank card was misused by someone else, or the domain changed hands), please file a removal appeal:',
    'i.ap1': 'Open the <a href="https://github.com/deepsucksi/deepsuck/issues/new?template=intel-appeal.yml" target="_blank" rel="noopener">GitHub removal appeal template</a>; <b>you only need to fill in the entry ID</b> (e.g. <code>EX-0001</code>), without disclosing any personal information;',
    'i.ap2': 'Maintainers handle appeals with priority: the entry is first marked <code>disputed</code> (its value is hidden on the page), then removed (<code>removed</code>) or restored after verification;',
    'i.ap3': 'If privacy makes it hard to explain publicly, say so in the appeal and a maintainer will offer a private channel.',
    'i.ap4': 'If your bank card was misused to receive scam payments, also contact the issuing bank and report it to the police as soon as possible.',
    'i.rep.h': 'Scammed? Call the police first, then report',
    'i.rep1': 'If you have already paid or are being scammed right now: <b>call 110 immediately</b> to report it to the police, and contact your bank to try to stop the payment. <b>96110</b> is China\'s national anti-fraud warning hotline; if 96110 calls you, be sure to answer.',
    'i.rep2.h': 'National Anti-Fraud Center app',
    'i.rep2': 'Search for "<span lang="zh-CN" data-i18n-keep="search-term">国家反诈中心</span>" (National Anti-Fraud Center) in an official app store and install it. "<span lang="zh-CN" data-i18n-keep="search-term">我要举报</span>" (Report) on its home screen accepts leads such as scam calls, text messages, URLs, apps and receiving accounts, and it can also enable call/SMS warnings.',
    'i.rep3.h': 'Other channels',
    'i.rep3': 'Spam texts, nuisance calls and harmful websites can be reported to <b>12321</b> (the reporting center for harmful and spam information online); leads on cybercrime can be submitted through the Ministry of Public Security\'s cybercrime reporting website.',
    'i.rep.note': 'DeepSuck\'s intel library is a public-interest supplement and no substitute for calling the police. Please report through the official channels above first.',
    'i.s1.t': 'Collect',
    'i.s1': 'Open the <a href="demo.html">sandbox</a>, pick the closest scenario and <b>paste the scammer\'s exact messages one by one</b> (or retell them in the "scammer" seat). Extraction and masking happen entirely in your browser.',
    'i.s2.t': 'Generate',
    'i.s2': 'Click "End chat · build intel dashboard", then <b>"Submit to intel library"</b>: a submission is generated per the publishing policy (phones/addresses/URLs in full, bank cards/names masked) and copied to the clipboard.',
    'i.s3.t': 'Submit',
    'i.s3': 'Paste it into the <a href="https://github.com/deepsucksi/deepsuck/issues/new?template=intel-submission.yml" target="_blank" rel="noopener">GitHub intel submission template</a> that opens, add the time and channel, and maintainers will add it after review. <b>Do not submit victim information or the fictitious samples from the sandbox.</b>',
    'i.footer': 'DeepSuck · Code Apache-2.0 · Data <a href="https://github.com/deepsucksi/deepsuck/blob/main/DATA_LICENSE" target="_blank" rel="noopener">CC BY 4.0</a> · For anti-fraud research and education only',
    'meta.404.title': 'Page not found · DeepSuck',
    'nf.h1': 'This page does not exist',
    'nf.lead': 'The link may be broken or mistyped. Just like an "official URL" sent by a scammer — look carefully before you click.',
    'aria.pagenav': 'Page navigation',
    'aria.mainnav': 'Main navigation',
    'aria.personas': 'Personas',
    'meta.home.desc': 'DeepSuck: an open-source AI anti-scam bot that uses chatty "victim" personas to stall scammers and extract scam intel (masked) for prevention and early warning.',
    'meta.home.og': 'DeepSuck · Let scammers waste their time on an AI instead',
    'meta.home.ogdesc': 'Open-source AI anti-scam "time-waster" bot: ordinary-sounding victim personas keep scammers busy, extract masked intel, and feed a public scam intel library.',
    'meta.home.twdesc': 'Open-source AI anti-scam "time-waster" bot + public scam intel library.',
    'meta.demo.desc': 'Play the scammer in your browser and watch the AI personas Auntie Wang, Xiao Chen\'s Mom, Xiao Lin and Boss Zheng stall you while extracting masked intel. 7 common Chinese scam scenarios, no API key, runs locally.',
    'meta.demo.og': 'DeepSuck sandbox: play the scammer and see who you can fool',
    'meta.demo.ogdesc': '7 Chinese scam scenarios × 4 "victim" personas, running locally in your browser, with intel masked automatically.',
    'd.samples.title': 'Send a sample scammer line with one click',
    'd.input.ph': 'Type a message as the scammer…',
    'd.key.ph': 'sk-… (stored only in this browser)',
    'meta.intel.desc': 'DeepSuck public scam intel library: scam phone numbers, wallet addresses, URLs/apps and scripts published in full; bank cards and names partially masked. Search, filter and download as JSON/CSV.',
    'meta.intel.og': 'DeepSuck public scam intel library',
    'meta.intel.ogdesc': 'Scam phone numbers, wallet addresses, URLs/apps and scripts published in full; bank cards and names partially masked. Searchable and downloadable.',
    'i.q.ph': 'Search numbers, addresses, domains, apps, script keywords… (e.g. 10000000001, TRON, safe account)',
    'i.q.aria': 'Search',
    'i.ftype': 'Filter by type',
    'i.fsc': 'Filter by scenario',
    'meta.locale': 'en_US'
  };
  // 由 JS 渲染的数据文案（场景、人设、话术标签、情报类型等；原文在 assets/core/*.json 与各页 JS 中，不改动）：中文原文 → 英文
  var DATA = {
    '冒充客服 · 退款理赔': 'Fake customer service · refunds', '冒充公检法 · 安全账户': 'Fake police · "safe account"',
    '杀猪盘 · 投资/感情': 'Pig-butchering · romance/investment', '刷单返利 · 做任务赚佣金': 'Task scam · paid tasks for commission',
    '虚假贷款 · 征信修复': 'Fake loans · credit repair', '冒充领导/熟人 · 借钱转账': 'Fake boss / acquaintance · borrowing and transfers',
    '注销校园贷 · 清空网贷额度': '"Cancel your campus loan" · draining loan-app credit', '其他': 'Other',
    '王阿姨': 'Auntie Wang', '小林': 'Xiao Lin', '小陈妈妈': 'Xiao Chen\'s Mom', '小宇': 'Xiaoyu', '郑老板': 'Boss Zheng',
    '王': 'W', '林': 'L', '陈': 'C', '郑': 'Z', '骗': 'S',
    '退休老人': 'Retiree', '宝妈': 'Young mother', '刚毕业学生': 'New graduate', '个体小老板': 'Small shop owner',
    '宝妈，在家带娃，精打细算，常被孩子打断': 'Stay-at-home mom; careful with money, often interrupted by the kids',
    '刚毕业，试用期上班，爱较真，什么都想问个明白': 'Just graduated, on probation at a new job; a stickler who wants everything explained',
    '开五金店的个体小老板，说话直，爱讲价，一边忙生意一边应付': 'Runs a small hardware shop; blunt, loves to haggle, half-busy with customers',
    '退休会计，热心，爱确认，爱唠家常': 'Retired accountant; warm-hearted, always double-checks, loves small talk',
    '大二学生，好奇心爆棚，什么都想问个明白': 'Second-year college student, bursting with curiosity, wants to understand everything',
    '冒充公检法': 'Fake police', '刷单返利': 'Task scam', '冒充领导': 'Fake boss', '冒充供应商': 'Fake supplier',
    '要求保密': 'Demands secrecy', '安全账户': '"Safe account"', '刷单返佣': 'Order-brushing commission', '诱导垫付': 'Pushes advance payments',
    '下载APP': 'App download', '要求转账': 'Demands a transfer', '阻止核实': 'Blocks verification', '冒充熟人': 'Poses as an acquaintance', '更换收款账户': 'Switches receiving account',
    '银行卡': 'Bank card', '户名': 'Account name', '电话': 'Phone', 'APP': 'App', '网址': 'URL',
    '据公开反诈宣传改写': 'Adapted from public anti-scam PSAs', '据法院公开典型案例改写': 'Adapted from published court cases',
    '据公开典型案例改写': 'Adapted from published typical cases', '据公安机关公开通报改写': 'Adapted from public police bulletins',
    '制造紧迫感': 'Creates urgency', '冒充公检法/权威': 'Impersonates police/authority', '冒充客服/平台': 'Impersonates customer service/platform',
    '谎称账户/订单/包裹异常': 'Claims an account/order/parcel problem', '索要验证码': 'Asks for OTP codes', '要求转账至安全账户': 'Demands transfer to a "safe account"',
    '要求转账/付款': 'Demands transfer/payment', '诱导下载APP/屏幕共享': 'Pushes app download/screen sharing', '屏幕共享/远程控制': 'Screen sharing/remote control',
    '高收益承诺': 'Promises high returns', '要求保密/隔离受害人': 'Demands secrecy/isolates the victim', '威胁恐吓': 'Threats and intimidation',
    '情感操控': 'Emotional manipulation', '套取个人信息': 'Harvests personal information', '涉加密货币': 'Involves crypto',
    '引流至私聊/其他平台': 'Moves to private chat/another platform', '中奖/补贴诱饵': 'Prize/subsidy bait', '刷单/做任务返佣': 'Order-brushing/task commissions',
    '虚假贷款/征信修复': 'Fake loans/credit repair', '冒充熟人/领导': 'Poses as acquaintance/boss', '虚假绑架/家人出事': 'Fake kidnapping/family emergency',
    '注销校园贷/清空额度': '"Cancel campus loan"/drain credit',
    '银行卡号': 'Bank card number', '电话号码': 'Phone number', 'BTC 地址': 'BTC address', 'ETH/ERC20 地址': 'ETH/ERC20 address', 'TRON/TRC20 地址': 'TRON/TRC20 address',
    '网址/域名': 'URL/domain', '邮箱': 'Email', 'QQ 号': 'QQ number', '微信号': 'WeChat ID', '支付宝账号': 'Alipay account', '身份证号': 'ID card number',
    '收款户名': 'Receiving account name', '开户银行': 'Account bank', '涉及金额': 'Amount involved', '支付/联络渠道': 'Payment/contact channel', 'APP/平台名称': 'App/platform name',
    '诈骗电话': 'Scam phone number', '加密钱包地址': 'Crypto wallet address', '诈骗网址/域名': 'Scam URL/domain', '话术/手法': 'Script/method',
    '收款银行卡': 'Receiving bank card', '支付宝/微信/QQ 等账号': 'Alipay/WeChat/QQ and other accounts', '收款户名/姓名': 'Receiving account name/name',
    '借记卡': 'Debit card', '信用卡': 'Credit card', '准贷记卡': 'Semi-credit card', '预付费卡': 'Prepaid card',
    '大模型': 'LLM', '规则回退': 'Rule fallback'
  };
  // data-i18n：替换 innerHTML；data-i18n-attr="attr:key;attr:key"：替换属性（aria-label、title、placeholder、meta content 等）
  var nodes = document.querySelectorAll('[data-i18n]');
  var ZH = [];
  nodes.forEach(function (n, i) { ZH[i] = n.innerHTML; });
  // 指向分语言页面的链接（如博客）：data-href-en 给出英文版地址，切换语言时一并改 href
  var links = document.querySelectorAll('[data-href-en]');
  links.forEach(function (a) { a.setAttribute('data-href-zh', a.getAttribute('href')); });
  var attrNodes = [];
  document.querySelectorAll('[data-i18n-attr]').forEach(function (n) {
    n.getAttribute('data-i18n-attr').split(';').forEach(function (spec) {
      var p = spec.split(':'), name = p[0], key = p.slice(1).join(':');
      if (name && key) attrNodes.push({ n: n, name: name, key: key, zh: n.getAttribute(name) });
    });
  });
  var cur = 'zh';
  function has(o, k) { return Object.prototype.hasOwnProperty.call(o, k); }
  function apply(lang) {
    cur = lang === 'en' ? 'en' : 'zh';
    // 首页动效（brand-motion.js）在切换前还原逐字拆分，切换后重建
    document.dispatchEvent(new CustomEvent('deepsuck:beforelanguagechange'));
    nodes.forEach(function (n, i) {
      var k = n.getAttribute('data-i18n');
      n.innerHTML = lang === 'en' && EN[k] ? EN[k] : ZH[i];
    });
    attrNodes.forEach(function (a) {
      var v = lang === 'en' && EN[a.key] ? EN[a.key] : a.zh;
      if (v == null) a.n.removeAttribute(a.name); else a.n.setAttribute(a.name, v); // 中文里没有的属性（如只给英文短标签加的 title）切回中文时去掉
    });
    document.documentElement.lang = lang === 'en' ? 'en' : 'zh-CN';
    links.forEach(function (a) { a.setAttribute('href', a.getAttribute(lang === 'en' ? 'data-href-en' : 'data-href-zh')); });
    document.querySelectorAll('.lang-toggle').forEach(function (b) {
      b.textContent = lang === 'en' ? '中文' : 'EN';
      b.setAttribute('lang', lang === 'en' ? 'zh-CN' : 'en');
    });
    try { localStorage.setItem('deepsuck.lang', lang); } catch (e) {}
    document.dispatchEvent(new CustomEvent('deepsuck:languagechange', { detail: { lang: lang } }));
  }
  // 供各页 JS 渲染动态文案：L(中文, 英文) 按当前语言取值；tr(中文数据) 查 DATA，查不到原样返回；trParts 按“ · ”逐段查
  window.DeepSuckI18n = {
    lang: function () { return cur; },
    isEn: function () { return cur === 'en'; },
    L: function (zh, en) { return cur === 'en' ? en : zh; },
    tr: function (s) { return cur === 'en' && has(DATA, s) ? DATA[s] : s; },
    trParts: function (s, sep) {
      sep = sep || ' · ';
      return cur === 'en' ? String(s).split(sep).map(function (x) { return has(DATA, x) ? DATA[x] : x; }).join(sep) : s;
    }
  };
  var saved = 'zh';
  try { saved = localStorage.getItem('deepsuck.lang') || 'zh'; } catch (e) {}
  if (/[?&]lang=en/.test(location.search)) saved = 'en';
  else if (/[?&]lang=zh/.test(location.search)) saved = 'zh';
  if (saved === 'en') apply('en');
  document.querySelectorAll('.lang-toggle').forEach(function (btn) {
    btn.addEventListener('click', function () { apply(cur === 'en' ? 'zh' : 'en'); });
  });
})();
