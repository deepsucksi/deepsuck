/*! mulberry32 伪随机数：与 python/deepsuck/rng.py 逐位一致，用于可复现的会话、测试夹具与评测。Apache-2.0 */
'use strict';
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
module.exports = { mulberry32: mulberry32 };
