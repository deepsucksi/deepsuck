"""情报数据的许可与署名（与根目录 DATA_LICENSE、site/data/intel.json 顶层字段一致）。

代码按 Apache-2.0 发布；情报数据（site/data/intel.json、intel.csv、intel.rss、intel.stix.json 及其生成物）
按 CC BY 4.0 发布，署名「DeepSuck (deepsuck.si)」。导出器（deepsuck.stix / deepsuck.feeds）从这里取值。
"""
from __future__ import annotations

LICENSE_ID = "CC-BY-4.0"  # SPDX 标识
LICENSE_NAME = "CC BY 4.0"
LICENSE_URL = "https://creativecommons.org/licenses/by/4.0/legalcode"
ATTRIBUTION = "DeepSuck (deepsuck.si)"
LICENSE_FILE_URL = "https://github.com/deepsucksi/deepsuck/blob/main/DATA_LICENSE"
NOTICE_ZH = f"数据以 {LICENSE_NAME} 许可发布，署名：{ATTRIBUTION}。许可全文：{LICENSE_URL}"
NOTICE_EN = f"Data licensed under {LICENSE_NAME} ({LICENSE_URL}). Attribution: {ATTRIBUTION}."
