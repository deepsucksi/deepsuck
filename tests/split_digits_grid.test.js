'use strict';
// #163 三审：拆字报姓（含 ASR 同音写法）紧接金额 / 数字 / 卡号 / 手机号，web 出口（llm.js sanitizeReply）不露姓。
// 与 voice/tests/test_split_digits_grid.py 同一网格（refs、语音、CallRedactor 在那边跑）
const test = require('node:test');
const assert = require('node:assert');
const LLM = require('../site/assets/js/llm.js');

const SP = { 弓长张: '张', 木子李: '李', 耳东陈: '陈', 口天吴: '吴', 立早章: '章', 龚厂长: '张', 工长张: '张', 尔东陈: '陈' };
const EXACT = ['弓长张', '木子李', '耳东陈', '口天吴', '立早章'];
const LEADS = ['', '转给', '收款人', '收款人是', '户名', '打给', '汇给'];
const TAILS = ['五百块', '三五百块', '一千元', '两万', '500', '1000元', '6222021234567890123', '，卡号6222021234567890123',
  '13812345678', '，手机13812345678', '，500块'];

test('#163 拆字报姓 + 数字 / 金额网格：web 出口不露姓', () => {
  let n = 0;
  for (const l of LEADS) for (const sp of Object.keys(SP)) for (const t of TAILS) {
    for (const g of (EXACT.includes(sp) ? ['', '三', '伟明'] : [''])) {
      const text = l + sp + g + t;
      const out = LLM.sanitizeReply(text).replace(/那个名字/g, '');
      assert.ok(!out.includes(SP[sp]) && !out.includes(sp.slice(0, 2)), text + ' -> ' + out);
      n++;
    }
  }
  assert.ok(n >= 1000);
});
