"""语音演示页只留用户文案（#37）：渲染出来的 HTML/JS 文案里不出现模型、厂商、技术栈名；同意说明只说一次。"""
import re
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "static"
BANNED = re.compile(r"paraformer|cosyvoice|qwen|dashscope|百炼|阿里|aliyun|smallwebrtc|pipecat|aiortc|deepseek|通义", re.I)
SENTENCE = "每通保存去掉敏感信息的文字记录 30 天用于排查问题，勾选同意时另存录音；仅供防诈研究与教育，请勿用于联系任何真实的人。"


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


EMOJI = re.compile("[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F000-\U0001F2FF\uFE0F]")


def test_trace_copy_no_emoji_and_honest_about_storage():
    """#5：通话编号、“这通有问题”、留存说明；不加 emoji；文案如实说明文字每通都存、录音要勾选。"""
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    js = (STATIC / "voice.js").read_text(encoding="utf-8")
    for name, text in (("index.html", html), ("voice.js", js)):
        assert not EMOJI.search(text), name
    assert 'id="traceId"' in html and 'id="traceCopy"' in html and ">这通有问题<" in html
    assert "什么内容都不存" not in html and "不勾选则不保存" not in html
    info = html[html.index('id="consentInfo"'):html.index('id="trace"')]
    for word in ("银行卡号", "身份证号", "姓名", "QQ", "微信", "支付宝", "录音"):
        assert word in info, word
    # voice.js 会改写 #keepNote（关闭追踪 / 不录音 / 非默认天数）：每种都保留同一句结尾
    assert js.count('$("keepNote").textContent') == 3 and "NOTE_TAIL" in js
    assert "仅供防诈研究与教育，请勿用于联系任何真实的人。" in js
    # 提交“这通有问题”带本页口令，并在原位给出结果
    assert "key: traceKey" in js and "已标记这通有问题" in js and 'aria-live="polite"' in html
