"""#249：同音 / ASR 拆字写法 + 名 + 数字按姓名打码，普通词走 nameRules.split.numWhitelist；与 tests/homophone_split_249.test.js 共用夹具。"""
import pytest

from deepsuck import extract_sensitive, redact_text
from deepsuck.redact import say_names

from conftest import fixture

CASES = fixture("homophone_split_249")["cases"]


@pytest.mark.parametrize("c", CASES, ids=[c["text"] for c in CASES])
def test_fixture(c):
    out = redact_text(c["text"], extract_sensitive(c["text"]))
    assert out == c["redacted"]
    assert (out != c["text"]) == (c["expect"] == "mask")


def test_say_names():
    assert say_names("尔东陈伟明500", extract_sensitive("尔东陈伟明500")) == "那个名字500"
    assert say_names("我在尔东陈列馆2楼等你", extract_sensitive("我在尔东陈列馆2楼等你")) == "我在尔东陈列馆2楼等你"
