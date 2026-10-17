/*!
 * DeepSuck — scenarios.js
 * 沙盒场景定义：访客扮演骗子，机器人扮演"潜在受害人"。
 * goals = 机器人在周旋中希望诱导对方暴露的情报类型（按优先级）。
 * Apache-2.0 · 非官方项目，与 DeepSeek 无关
 */
(function (root, factory) {
  var mod = factory();
  if (typeof module === 'object' && module.exports) module.exports = mod;
  else { root.DeepSuck = root.DeepSuck || {}; root.DeepSuck.scenarios = mod; }
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';
  // 样例台词中的账号、电话、地址、域名均为虚构/测试数据，仅用于演示提取与脱敏。
  var SCENARIOS = [
    {
      id: 'refund',
      title: '冒充客服 · 退款理赔',
      icon: '📦',
      desc: '自称电商/快递客服，以"商品质量问题双倍理赔""会员自动扣费"为由，诱导下载APP、共享屏幕、索要验证码并转账。',
      goals: ['url', 'bank', 'phone', 'name'],
      samples: [
        '您好，我是淘宝官方客服，您上周购买的商品检测出质量问题，我们这边要给您双倍理赔 380 元。',
        '理赔需要您下载我们的"安心退"APP，网址是 https://refund-tb-kefu.top/dl ，下载后加入会议号 886 221 共享屏幕。',
        '您的支付宝有借呗额度吗？理赔款需要先走一下流水验证，系统会给您发个验证码，您报给我就行。',
        '系统显示您的账户异常，需要您先转 2000 元保证金到我们的理赔专用账户 6217 0012 3456 7890 123，户名李强，建设银行。',
        '阿姨您抓紧时间，今天 18 点前不处理，您的征信会受影响的。',
        '有问题您可以直接打我工号专线 400-820-1234，或者加我微信 kefu_tb2026。'
      ]
    },
    {
      id: 'police',
      title: '冒充公检法 · 安全账户',
      icon: '🚨',
      desc: '自称公安/检察院，称受害人"涉嫌洗钱"，以资金清查为名要求保密、转账至所谓"安全账户"。',
      goals: ['bank', 'phone', 'name', 'url'],
      samples: [
        '你好，这里是上海市公安局经侦支队，我是张警官，警号 029381。你名下一张银行卡涉嫌一起洗钱案件。',
        '现在案件处于保密阶段，你不要告诉任何人，包括你的家人，否则后果自负。',
        '为了证明你的清白，你需要配合我们做资金清查，把卡里的钱全部转到国家安全账户 6222 0202 0011 2233 445，户名王建国，工商银行。',
        '你登录这个网址查看你的通缉令：http://gaj-sh-gov.cc/case/8872 ，输入你的身份证号。',
        '我现在把电话转给检察院的刘检察官，你记一下他的手机 139-0011-2233，马上联系他。',
        '你还有几张卡？卡里余额有多少？必须在 2 小时内完成清查，不然我们就要对你发逮捕令了。'
      ]
    },
    {
      id: 'pig',
      title: '杀猪盘 · 投资/感情',
      icon: '💔',
      desc: '先培养感情（"缘分""我们的未来"），再推荐"内部渠道""导师带单"的高收益投资平台，诱导充值 USDT。',
      goals: ['url', 'wallet', 'phone', 'bank'],
      samples: [
        '亲爱的，早安～认识你真的是缘分，我想和你一起规划我们的未来。',
        '我舅舅在投资公司做数据分析，发现了一个平台的漏洞，稳赚不赔，我上周刚赚了 8 万。',
        '平台网址是 www.goldwin-vip.top ，你先注册，我带你操作，收益率每天 15%。',
        '充值要用 USDT，你先充 5000U 试试，打到这个 TRC20 地址：TQ7xM6hYpCzD8vNp1qJ3kR5sW9uL2aBcDe',
        '要是 TRC20 不方便，用 ERC20 也行：0x12ab34cd56ef7890abcdef1234567890abcd9f3e',
        '这个是内部机会，名额有限，宝贝你不要跟别人说哦，我们加 Telegram 私聊，我的 QQ 是 2876543210。'
      ]
    }
  ];

  var BY_ID = {};
  SCENARIOS.forEach(function (s) { BY_ID[s.id] = s; });
  return { SCENARIOS: SCENARIOS, BY_ID: BY_ID };
});
