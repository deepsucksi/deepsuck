"""全局 loguru 配置（#253）：关掉 diagnose，logger.exception 的堆栈里不带局部变量的值（可能是转写原文）。

loguru 默认 handler（id 0，stderr）是 diagnose=True；这里把它换成 diagnose=False 的同一路 stderr。
backtrace 也关掉（只打本层堆栈，不展开上层帧的变量）。重复调用是幂等的。"""
from __future__ import annotations

import sys

from loguru import logger

_ID = None


def sink_options() -> dict:
    return {"level": "DEBUG", "diagnose": False, "backtrace": False}


def configure(sink=None):
    """返回 handler id。sink 默认 sys.stderr；测试可以传别的 sink。"""
    global _ID
    if sink is None:
        try:
            logger.remove(0)  # loguru 自带的 diagnose=True stderr handler
        except ValueError:
            pass
        if _ID is not None:
            return _ID
        _ID = logger.add(sys.stderr, **sink_options())
        return _ID
    return logger.add(sink, **sink_options())


configure()
