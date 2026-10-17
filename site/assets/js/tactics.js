/*!
 * DeepSuck — tactics.js
 * 诈骗话术分类器：基于关键词/正则的可解释规则，输出命中的话术标签与风险分。
 * 规则刻意保持简单透明，方便社区审阅与补充（见 CONTRIBUTING.md）。
 * Apache-2.0 · 非官方项目，与 DeepSeek 无关
 */
(function (root, factory) {
  var mod = factory();
  if (typeof module === 'object' && module.exports) module.exports = mod;
  else { root.DeepSuck = root.DeepSuck || {}; root.DeepSuck.tactics = mod; }
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  var TACTICS = [
    { id: 'urgency', label: '制造紧迫感', weight: 2,
      re: /马上|立即|立刻|赶紧|尽快|抓紧|今天之内|今天内|\d+\s*(?:分钟|小时)内|否则|逾期|过期|最后(?:一次)?机会|来不及|限时|名额有限|错过/ },
    { id: 'authority', label: '冒充公检法/权威', weight: 3,
      re: /公安局?|警官|民警|检察院|检察官|法院|专案组|通缉|逮捕令|拘捕|刑警|网警|银保监|金融监管|央行|中国人民银行|反诈中心|警号/ },
    { id: 'cs_impersonation', label: '冒充客服/平台', weight: 2,
      re: /客服|淘宝|天猫|京东|拼多多|快递|物流|理赔|退款|售后|会员|百万保障|商家|订单(?:异常|出错)|质量问题/ },
    { id: 'otp', label: '索要验证码', weight: 4,
      re: /验证码|校验码|动态码|短信码|动态密码|安全码|CVV|cvv/ },
    { id: 'safe_account', label: '要求转账至安全账户', weight: 5,
      re: /安全账户|资金清查|清查账户|核查账户|监管账户|资金核查|保护账户|专用账户|指定账户/ },
    { id: 'transfer', label: '要求转账/付款', weight: 3,
      re: /转账|转到|转给|转完|汇款|打款|充值|付款|转入|转过来|垫付|保证金|手续费|解冻费|激活费|刷流水|流水|入金|充币|打到/ },
    { id: 'app_download', label: '诱导下载APP/屏幕共享', weight: 4,
      re: /下载|安装|APP|App|app|屏幕共享|共享屏幕|腾讯会议|Zoom|zoom|会议号|扫码|二维码|点击链接|点链接|打开链接/ },
    { id: 'high_return', label: '高收益承诺', weight: 3,
      re: /稳赚|高收益|高回报|收益率|翻倍|翻番|内幕|带单|导师|老师带|稳赚不赔|日赚|月入|躺赚|保本|零风险|无风险|稳定盈利|漏洞|内部消息/ },
    { id: 'secrecy', label: '要求保密/隔离受害人', weight: 4,
      re: /保密|不要告诉|不能告诉|别告诉|不要跟.{0,6}说|别跟.{0,6}说|不要声张|秘密|单独|找个没人|挂断.{0,4}电话|不要挂|不要联系/ },
    { id: 'threat', label: '威胁恐吓', weight: 3,
      re: /冻结|逮捕|坐牢|拘留|判刑|征信|违法|涉嫌|洗钱|后果自负|起诉|黑名单|影响子女|追究|犯罪/ },
    { id: 'romance', label: '情感操控', weight: 2,
      re: /亲爱的|宝贝|宝宝|想你|爱你|缘分|老婆|老公|我们的未来|一起努力|结婚|见面|心动|喜欢你/ },
    { id: 'info_harvest', label: '套取个人信息', weight: 3,
      re: /身份证|银行卡号|卡号|密码|真实姓名|住址|余额|卡里有多少|存款|几张卡|名下|开户行/ },
    { id: 'crypto', label: '涉加密货币', weight: 2,
      re: /USDT|usdt|泰达币|比特币|BTC|ETH|以太坊|钱包地址|虚拟币|数字货币|交易所|币安|欧易|TRC20|ERC20|充币|提币/ },
    { id: 'off_platform', label: '引流至私聊/其他平台', weight: 2,
      re: /加我微信|加微信|加我QQ|加QQ|加V|私聊|Telegram|telegram|TG|飞机号|加群|进群|WhatsApp/ },
    { id: 'reward_bait', label: '中奖/补贴诱饵', weight: 2,
      re: /中奖|补贴|返现|红包|奖金|福利|免费领|退税|赔付金|赔偿金/ },
    { id: 'task_rebate', label: '刷单/做任务返佣', weight: 4,
      re: /刷单|点赞员|做任务|任务平台|新手任务|福利单|连单|卡单|返佣|佣金|日结|垫付.{0,6}返|返本金|提现/ },
    { id: 'loan_fraud', label: '虚假贷款/征信修复', weight: 4,
      re: /无抵押|低息|秒批|放款|贷款额度|解冻金|征信修复|修复征信|刷.{0,2}流水|还款能力|会员费|服务费/ },
    { id: 'acquaintance', label: '冒充熟人/领导', weight: 4,
      re: /我是你.{0,4}(?:领导|老板|总|经理|主任|叔|舅|姨|同学|表哥|表姐)|新的?微信号?|换(?:了)?(?:个)?号|备注一下|不方便接电话|别打我电话|在开会|帮我(?:先)?垫|明天.{0,6}报销|助理电话/ },
    { id: 'campus_loan', label: '注销校园贷/清空额度', weight: 4,
      re: /校园贷|学生贷|注销.{0,6}(?:账户|账号|业务|贷)|清空.{0,4}额度|借呗|微粒贷|网贷|失信名单|银保监/ }
  ];

  var BY_ID = {};
  TACTICS.forEach(function (t) { BY_ID[t.id] = t; });

  /**
   * classify(text) -> [{ id, label, weight, match }]
   */
  function classify(text) {
    var s = String(text || '');
    var hits = [];
    TACTICS.forEach(function (t) {
      var m = s.match(t.re);
      if (m) hits.push({ id: t.id, label: t.label, weight: t.weight, match: m[0] });
    });
    return hits;
  }

  /** 根据累计命中次数计算 0–100 风险分 */
  function riskScore(counts) {
    var raw = 0;
    Object.keys(counts || {}).forEach(function (id) {
      var t = BY_ID[id];
      if (t) raw += t.weight * Math.min(3, counts[id]);
    });
    return Math.min(100, Math.round(100 * (1 - Math.exp(-raw / 18))));
  }

  return { TACTICS: TACTICS, BY_ID: BY_ID, classify: classify, riskScore: riskScore };
});
