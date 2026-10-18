"""人设对应的真人化预设（与 personas/prompts/*.yaml 的 humanize_profile 一一对应）。"""
from __future__ import annotations

PROFILES = {
    # 退休老人：用语音输入，句子断得碎，口头语多，经常重复确认、跑题
    "retiree": {
        "intensity": 0.55,
        "mode": "voice",
        "dialect": "北方",
        "weights": {"repeat": 1.5, "digress": 1.4, "typo": 0.8},
        "digressions": [
            "哎呀水开了我去关一下",
            "哎我老花镜放哪了",
            "等会儿啊我先把药吃了",
            "楼下广场舞的音乐太吵了",
            "你们单位离我家远不远啊",
        ],
    },
    # 宝妈：打字快、一心二用，标点随意，常被孩子打断
    "mom": {
        "intensity": 0.4,
        "mode": "chat",
        "dialect": None,
        "weights": {"digress": 1.5, "punct": 1.2},
        "digressions": [
            "等下娃在哭",
            "我先给孩子冲个奶粉",
            "宝宝把我手机抢走了刚才",
            "幼儿园群里又在接龙",
        ],
    },
    # 刚毕业的学生：打字熟练，错字少，标点省略、口语化多
    "graduate": {
        "intensity": 0.3,
        "mode": "chat",
        "dialect": None,
        "weights": {"typo": 0.5, "punct": 1.4, "repeat": 0.8},
        "digressions": [
            "等下我室友喊我拿外卖",
            "我这边在面试间隙",
            "刚刚在打游戏没看到",
        ],
    },
    # 个体小老板：边看店边语音回复，偶尔夹方言，说话直接
    "shop_owner": {
        "intensity": 0.45,
        "mode": "voice",
        "dialect": "西南",
        "weights": {"digress": 1.2, "repeat": 1.0},
        "digressions": [
            "等一哈有客人来买东西",
            "我这边在盘货",
            "刚才送货的来了",
            "店里网不太好",
        ],
    },
}
