"""语音演示页只留用户文案（#37）：渲染出来的 HTML/JS 文案里不出现模型、厂商、技术栈名；同意说明只说一次。"""
import re
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "static"
BANNED = re.compile(r"paraformer|cosyvoice|qwen|dashscope|百炼|阿里|aliyun|smallwebrtc|pipecat|aiortc|deepseek|通义", re.I)
SENTENCE = "勾选同意时保存录音和脱敏文字 30 天用于改进，不勾选则不保存；仅供防诈研究与教育，请勿用于联系任何真实的人。"


def test_no_vendor_or_stack_names_on_page():
    for name in ("index.html", "voice.js", "playbook.js", "scam_playbooks.json"):
        hits = BANNED.findall((STATIC / name).read_text(encoding="utf-8"))
        assert not hits, f"{name}: {hits}"


def test_single_user_sentence():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert html.count(SENTENCE) == 1 and "语音链路" not in html
    intro = html[html.index('<section class="intro">'):html.index("</section>")]
    assert "30 天" not in intro  # 同意说明不在开头重复
    js = (STATIC / "voice.js").read_text(encoding="utf-8")
    assert "c.models" not in js and "p.voice" not in js  # 状态栏、人设下拉不显示模型和音色
