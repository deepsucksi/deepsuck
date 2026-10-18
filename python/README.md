# deepsuck（Python core）

> Apache-2.0

DeepSuck 浏览器端规则引擎的 Python 等价实现，**直接读取** `site/assets/core/*.json`（同一份正则、台词与场景），供语音端 `voice/`、评测脚本与后端复用：

| 模块 | 对应 JS | 功能 |
|---|---|---|
| `deepsuck.normalize` | `normalize.js` | 中文去武装写法规范化（带原文位置映射） |
| `deepsuck.extractors` | `extractors.js` | 银行卡/电话/钱包/网址/QQ/微信/支付宝等提取 |
| `deepsuck.redact` | `redact.js` | 脱敏 |
| `deepsuck.tactics` | `tactics.js` | 话术分类 + 风险分 |
| `deepsuck.engine` | `engine.js` | 规则人设引擎 `Session`（拖延意图 + 台词） |

```bash
cd python
python -m pytest -q                       # 与 JS 共用 tests/fixtures/*.json（测试即规格）
python -c "import deepsuck as d; print(d.extract_sensitive('加 微 信 kefu_tb2026'))"
```

零依赖（标准库）。Python ≥ 3.9。JS 正则中的 `\d`/`\w` 会被自动改写为 ASCII 字符类，以保证两端行为一致（见 `deepsuck/core.py`）。
