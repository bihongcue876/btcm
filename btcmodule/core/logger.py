"""调用日志：JSONL 单文件落盘与分页读取。

记录内容为每次调用的摘要字段，不含完整中间日志（中间日志已随响应返回）。
- 内存保留完整镜像，分页读取 O(1)，不再全量扫描文件
- 记录数超过 MAX_RECORDS 时裁剪文件到最近 TRIM_TO 条，防止无限膨胀
- 写入走 asyncio.to_thread，不阻塞事件循环
"""

from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path

BASE_LOG_FILE = Path(__file__).resolve().parent.parent / "calls.jsonl"

MAX_LOG_LIMIT = 100
MAX_RECORDS = 5000
TRIM_TO = 4000


class CallLogger:
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path else BASE_LOG_FILE
        self._records: list[dict] = []
        # append/trim 以 to_thread 在线程池执行，用锁串行化防止文件竞写
        self._lock = threading.Lock()
        self._load()

    # ---------- 加载 ----------

    def _load(self) -> None:
        if not self.path.exists():
            return
        records: list[dict] = []
        try:
            with self.path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        records.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        except OSError:
            return
        self._records = records[-MAX_RECORDS:]

    # ---------- 写入 ----------

    async def append(self, record: dict) -> None:
        """追加一条调用记录（异步写入，不阻塞事件循环）。"""
        await asyncio.to_thread(self._append_sync, record)

    def _append_sync(self, record: dict) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            line = json.dumps(record, ensure_ascii=False)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
            self._records.append(record)
            if len(self._records) > MAX_RECORDS:
                self._trim()

    def _trim(self) -> None:
        """超出上限时重写文件，仅保留最近 TRIM_TO 条。调用方须已持锁。"""
        self._records = self._records[-TRIM_TO:]
        tmp = self.path.with_name(self.path.name + ".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            for record in self._records:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        tmp.replace(self.path)

    # ---------- 读取 ----------

    def list(self, limit: int = 20, offset: int = 0) -> tuple[int, list[dict]]:
        """返回 (总条数, 倒序分页列表)。"""
        total = len(self._records)
        start = max(total - offset - limit, 0)
        end = max(total - offset, 0)
        return total, list(reversed(self._records[start:end]))
