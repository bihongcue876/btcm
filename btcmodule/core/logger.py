"""调用日志：JSONL 单文件落盘与分页读取。

记录内容为每次调用的摘要字段，不含完整中间日志（中间日志已随响应返回）。
"""

from __future__ import annotations

import json
from pathlib import Path

BASE_LOG_FILE = Path(__file__).resolve().parent.parent / "calls.jsonl"

MAX_LOG_LIMIT = 100


class CallLogger:
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path else BASE_LOG_FILE

    def append(self, record: dict) -> None:
        """追加一条调用记录。"""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(record, ensure_ascii=False)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")

    def list(self, limit: int = 20, offset: int = 0) -> tuple[int, list[dict]]:
        """返回 (总条数, 倒序分页列表)。"""
        if not self.path.exists():
            return 0, []
        with self.path.open("r", encoding="utf-8") as f:
            records = []
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        total = len(records)
        start = max(total - offset - limit, 0)
        end = max(total - offset, 0)
        return total, list(reversed(records[start:end]))
