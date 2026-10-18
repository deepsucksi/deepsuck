"""语音端的人设 id 归一。

#11 把人设统一成四个：王阿姨 wang、小陈妈妈、小林 lin、郑老板。小陈妈妈和郑老板的 id 以语料分支
corpus/personas-unify 合进 site/assets/core/personas.json 的为准；定稿前语音端（音色、底噪）先按
chen / zheng 配置，几种候选写法都归一过来，personas.json 里还没有这两个人设时也不报错。
定稿后把这里收成实际 id（或删掉这层），同时改环境变量名 DEEPSUCK_VOICE_<人设>。
"""
from __future__ import annotations

ALIASES = {
    "xiaochen": "chen", "chen_mom": "chen", "mom": "chen",          # 小陈妈妈（mom 是 personas/prompts 里的旧 id）
    "zhenglaoban": "zheng", "zheng_boss": "zheng", "shop_owner": "zheng",  # 郑老板（shop_owner 同上）
}


def canonical(pid: str) -> str:
    p = (pid or "").strip().lower()
    return ALIASES.get(p, p)
