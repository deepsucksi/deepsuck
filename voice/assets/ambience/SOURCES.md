# 通话环境底噪素材

都是 24 kHz 单声道 Ogg Vorbis，首尾交叉淡化成无缝循环，统一到 -26 dBFS RMS 并软限幅，由 `voice/ambience.py` 在通话里低音量循环播放。重新生成用 `tools/build.sh`（`tools/build.sh living_room shop` 只做指定几段）。

| 文件 | 场景 | 默认人设 | 来源 | 授权 |
| --- | --- | --- | --- | --- |
| `kitchen.ogg` | 厨房（水声、碗碟） | 王阿姨 `wang` | [Ambient Kitchen Sounds.wav](https://commons.wikimedia.org/wiki/File:Ambient_Kitchen_Sounds.wav)，作者 Wilfredor，Wikimedia Commons，截取 40–102 秒 | CC0 1.0 |
| `living_room.ogg` | 客厅（窗外远处小孩玩耍、低频房间底噪） | 小陈妈妈 `chen` | [Distant suburban children playing nature sounds.wav](https://freesound.org/people/myserval/sounds/274988/)，作者 myserval，freesound 编号 274988，取官方试听版 62–124 秒；低通 900 Hz、压缩、短回声，只剩远处嬉闹的轮廓。房间底噪为自制（固定种子的棕噪声） | CC0 1.0（自制房间底噪随本仓库 Apache-2.0） |
| `street.ogg` | 街道（车流、人声） | 小林 `lin` | [Sunday in the city street noise1.ogg](https://commons.wikimedia.org/wiki/File:Sunday_in_the_city_street_noise1.ogg)，作者 cori，原载 pdsounds.org，截取 30–92 秒 | 公有领域 |
| `shop.ogg` | 店铺（冷柜、门铃、脚步、远处顾客） | 郑老板 `zheng` | [AMB_Int_ConvenienceStore_001.wav](https://freesound.org/people/conleec/sounds/149444/)，作者 conleec，freesound 编号 149444，取官方试听版 0–46 秒（之后有成段对话）；叠 [HARDWARE STORE ROOMTONE.wav](https://freesound.org/people/vmgraw/sounds/257695/)，作者 vmgraw，freesound 编号 257695（冷柜、灯管嗡声）。低通 1500 Hz、压缩 | CC0 1.0 |

小孩声和店里的人声只做远处背景：成品在原音量和 +14 dB 下各过一遍实时语音识别，均识别不出文字（2026-10-19）。

原来给李大爷用的隔壁屋电视底噪（`tv.ogg`）随人设下线已删除（#95）。
