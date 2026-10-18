# 通话环境底噪素材

三段都是 24 kHz 单声道 Ogg Vorbis，首尾交叉淡化成无缝循环，统一到 -26 dBFS RMS，由 `voice/ambience.py` 在通话里低音量循环播放。重新生成用 `tools/build.sh`。

| 文件 | 场景 | 默认人设 | 来源 | 授权 |
| --- | --- | --- | --- | --- |
| `kitchen.ogg` | 厨房（水声、碗碟） | 王阿姨 `wang` | [Ambient Kitchen Sounds.wav](https://commons.wikimedia.org/wiki/File:Ambient_Kitchen_Sounds.wav)，作者 Wilfredor，Wikimedia Commons，截取 40–102 秒 | CC0 1.0 |
| `street.ogg` | 街道（车流、人声） | 小林 `lin` | [Sunday in the city street noise1.ogg](https://commons.wikimedia.org/wiki/File:Sunday_in_the_city_street_noise1.ogg)，作者 cori，原载 pdsounds.org，截取 30–92 秒 | 公有领域 |
| `tv.ogg` | 隔壁屋电视（天气预报） | 李大爷 `li` | 本项目自制：`tools/tv_voice.py` 用 CosyVoice 系统音色 longanhuan 朗读一段原创天气预报文本，再做带通、房间回声和粉噪声处理，听不清具体字句 | 随本仓库 Apache-2.0 |
