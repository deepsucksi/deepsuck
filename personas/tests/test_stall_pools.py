import re

import pytest

yaml = pytest.importorskip("yaml")

from personas import prompt as P  # noqa: E402

EMOJI = re.compile("[\U0001F300-\U0001FAFF\u2600-\u27BF]")


@pytest.mark.parametrize("pid", P.PERSONA_IDS)
def test_stall_pools(pid):
    pools = P.load(pid)["stall_pools"]
    for k in ("secrecy", "loan_stall"):
        lines = pools[k]
        assert len(set(lines)) == len(lines) >= 12, (pid, k)
        for x in lines:
            assert isinstance(x, str) and x.strip()
            assert not re.search(r"\d{6,}", x) and not EMOJI.search(x)
            assert "诈骗" not in x and "骗子" not in x
