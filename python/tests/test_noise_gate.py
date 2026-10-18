"""噪声评测 E 部分（人设默认档 / 手写档）的回归门槛，CI 每次跑。

门槛：两档带噪提取率（A）≥ 99%、跨回合拆数字（C 正例均值）≥ 95%、负例误拼 = 0。
跨回合 ≥ 95% 原先标 xfail，等 humanize 保护「幺」与逐字中文数字；712d617 落地后两档均为 99.4%，已改为硬门槛。
另保留一条 88% 的下限，便于区分是提取器回退还是 humanize 回退。"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def noise(tmp_path_factory):
    out = tmp_path_factory.mktemp("noise") / "noise.json"
    subprocess.run([sys.executable, str(ROOT / "eval" / "noise_eval.py"), "--json", str(out), "--taf", str(out.parent / "none")],
                   check=True, cwd=ROOT, stdout=subprocess.DEVNULL)
    return json.loads(out.read_text(encoding="utf-8"))


@pytest.mark.parametrize("tier", ["default", "handwriting"])
def test_no_mis_stitch(noise, tier):
    sm = noise["tiers"][tier]["summary"]
    assert sm["negCases"] >= 600
    assert sm["falseItems"] == 0


def test_no_mis_stitch_legacy(noise):
    assert noise["summary"]["falseItems"] == 0


@pytest.mark.parametrize("tier", ["default", "handwriting"])
def test_noisy_extraction(noise, tier):
    assert noise["tiers"][tier]["summary"]["humanizeRate"] >= 0.99


@pytest.mark.parametrize("tier", ["default", "handwriting"])
def test_digit_obfuscation(noise, tier):
    assert noise["tiers"][tier]["summary"]["digitsAll100"]


def test_cross_turn_legacy(noise):
    assert noise["summary"]["stitchMean"] >= 0.95


@pytest.mark.parametrize("tier", ["default", "handwriting"])
def test_cross_turn_floor(noise, tier):
    """硬下限：不低于提取器修复后的水平（默认档 88.8% / 手写档 88.4%）。"""
    assert noise["tiers"][tier]["summary"]["stitchMean"] >= 0.88


@pytest.mark.parametrize("tier", ["default", "handwriting"])
def test_cross_turn(noise, tier):
    assert noise["tiers"][tier]["summary"]["stitchMean"] >= 0.95
