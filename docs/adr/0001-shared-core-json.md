# 0001 共享 core JSON 作为 JS 与 Python 的单一事实来源

状态：已采纳

## 背景

浏览器沙盒需要零后端运行（JS），语音端、模拟器、情报 intake 需要 Python。提取规则、话术关键词、人设台词、场景若两边各写一份，必然漂移。

## 决策

- 规则与台词只写在 `site/assets/core/*.json`。JS 通过 `npm run build:core` 生成的 `core-data.js` 读取，Python 通过 `deepsuck.core` 读取（`DEEPSUCK_CORE_DIR` 可覆盖路径）。
- 正则只用 JS 与 Python `re` 共同支持的语法；`\d`/`\w` 在 Python 端收窄为 ASCII。
- 逻辑代码两边各一份，用 `tests/fixtures/*.json`（JS 生成）做金标准，Python 逐项比对。

## 后果

- 改规则只改一处；测试会检查 `core-data.js` 与夹具是否同步。
- 逻辑仍是双实现，一致性靠夹具覆盖率（#10）。
- 语音端、评测按相对路径读 `site/assets/core`，调整 `site/` 目录结构会影响它们（#14）。
