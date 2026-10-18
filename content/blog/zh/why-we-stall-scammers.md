---
title: 为什么用 AI 拖住骗子
description: DeepSuck 想做的事很简单：让骗子把时间花在一个不会上当的对象身上，同时留下可以用来预警的线索。这篇文章讲清楚我们为什么这样做，以及哪些事我们坚决不做。
date: 2026-10-19
tags: [项目, 伦理]
---

电信网络诈骗是一门讲效率的生意。一个话术团队一天能拨出的电话、能聊下去的对象是有限的，每一通电话、每一轮对话都在消耗他们的时间。DeepSuck 的出发点就在这里：**如果骗子面对的是一个永远愿意聊、永远差一步就要转账、却从不真的转账的对象，那么他们花在真人身上的时间就会少一些。**

## 我们做的事

DeepSuck 是一个开源的“拖住”机器人。它扮演一位普通的潜在受害人，回得慢一点，常常要对方再说一遍，按步骤操作时总会遇到点小状况。对话进行时，它会把骗子主动暴露的收款账户、钱包地址、电话和网址识别出来，脱敏后整理成结构化的情报。

现在有四位人设：王阿姨、小陈妈妈、小林和郑老板。他们的身份和背景都是虚构的，说话习惯各不相同，守的规矩是一样的。

这件事有三个用途：

- **防御**：每一分钟被拖住的时间，都是骗子没有拿去骗真人的时间。
- **研究**：话术如何开场、如何施压、在哪一步要钱，这些模式可以被记录、分类和比较。仓库里的话术语料、评测脚本和结果都公开，方便别人复现和改进。
- **教育**：网站上的沙盒让任何人都能扮演一次骗子，从另一侧看清这套流程。看过一遍完整套路的人，再接到类似电话时更容易认出来。

## 底线

这些规则写在 [伦理与使用规范](https://github.com/deepsucksi/deepsuck/blob/main/docs/ETHICS.md) 里，也落实在代码和贡献指南中。

**不主动联系任何真实的人。** 不外呼、不群发、不主动私信、不加好友。机器人只回应找上门来的骗子；网站沙盒里，扮演骗子的是访客自己。电话接入层同样是“只接不拨”。

**不提供真实信息。** 人设不会说出真实的验证码、卡号、密码或身份证号，也不会真的转账。语音输出前有一道守卫，会抹掉五位以上的数字串，防止模型编造看起来像真的号码。

**数据默认脱敏。** 展示、导出和发送给大模型之前，文本都先经过脱敏模块：银行卡只留前 6 位和后 4 位，手机号只留前 3 位和后 4 位，姓名只留姓。原始值只在本次处理的内存里用于比对，不写盘、不上报。

**不报复、不曝光。** 不人肉，不公开个人信息，不“以骗制骗”，不攻击任何系统。很多收款卡属于被冒用、被诱骗出租账户的普通人，所以公开情报库里的银行卡和姓名一律部分打码，任何人都可以凭条目编号申诉下架。

**线索交给专业的人。** 提取结果只是线索，不能据此认定任何人。遇到诈骗请拨打 110 或全国反诈专线 96110；情报优先提交给官方渠道。

## 为什么开源

反诈工具最需要的是信任。代码公开，别人才能检查我们说的“只接不拨”“先脱敏再落盘”是否真的成立；规则和语料公开，研究者才能在同一套数据上比较方法；评测公开，我们说的效果才有据可查。

项目采用 Apache-2.0 许可，情报数据以 CC BY 4.0 发布。如果你想参与，可以补充脱敏后的话术样本、设计更耐聊的人设、改进提取规则，或者只是在沙盒里试一试，告诉我们哪里不像真人。

## 接下来

这个博客会记录项目的进展：语音链路是怎么搭起来的，情报是怎么提取和脱敏的，常见的诈骗话术有哪些识别信号。所有数字都会注明出处，能在仓库里找到对应的文档或结果文件。

## 致谢

DeepSuck 用到了下面这些开源项目，感谢它们的作者和维护者。名单以仓库里的依赖和部署配置为准（`voice/requirements.txt`、`deploy/`、`scripts/`、`site/assets/core/blocklists.json`）。

语音链路：

- [Pipecat](https://github.com/pipecat-ai/pipecat)：实时语音管线框架
- [Silero VAD](https://github.com/snakers4/silero-vad)：语音活动检测
- [Smart Turn](https://github.com/pipecat-ai/smart-turn)：回合判定模型
- [aiortc](https://github.com/aiortc/aiortc)：Python 的 WebRTC 实现
- [FastAPI](https://github.com/fastapi/fastapi)、[Uvicorn](https://github.com/encode/uvicorn)、[websockets](https://github.com/python-websockets/websockets)：服务端与 WebSocket

部署与电话：

- [coturn](https://github.com/coturn/coturn)：TURN 中继
- [Asterisk](https://github.com/asterisk/asterisk)：电话交换机
- [Caddy](https://github.com/caddyserver/caddy) 与 [caddy-l4](https://github.com/mholt/caddy-l4)：HTTPS 与 443 端口分流
- [fail2ban](https://github.com/fail2ban/fail2ban)：拦截暴力注册

网站与数据：

- [marked](https://github.com/markedjs/marked)：本博客的 Markdown 转换
- [destroylist](https://github.com/phishdestroy/destroylist)、[Phishing.Database](https://github.com/Phishing-Database/Phishing.Database)：公开的钓鱼域名黑名单
