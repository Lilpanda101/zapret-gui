#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""JSONL history of orchestrator runs."""
from __future__ import annotations
import json
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict


@dataclass
class RunRecord:
    preset_id: str
    ok_count: int
    total_targets: int
    avg_latency_ms: int
    timestamp: float = field(default_factory=time.time)
    per_target: Dict[str, dict] = field(default_factory=dict)
    error: str = ''

    @classmethod
    def from_result(cls, result, timestamp=None):
        per_target = {}
        for item in getattr(result, 'per_target', ()) or ():
            per_target[item.target_key] = {
                'attempts': item.attempts,
                'successes': item.successes,
                'stable': item.stable,
                'avg_latency_ms': item.avg_latency_ms,
            }
        return cls(
            preset_id=result.preset_id,
            ok_count=result.ok_count,
            total_targets=result.total_targets,
            avg_latency_ms=result.avg_latency_ms,
            timestamp=time.time() if timestamp is None else timestamp,
            per_target=per_target,
            error=getattr(result, 'error', '') or '',
        )

    @classmethod
    def from_dict(cls, data):
        return cls(
            preset_id=str(data.get('preset_id', '')),
            ok_count=int(data.get('ok_count', 0)),
            total_targets=int(data.get('total_targets', 0)),
            avg_latency_ms=int(data.get('avg_latency_ms', 9999)),
            timestamp=float(data.get('timestamp', 0) or 0),
            per_target=dict(data.get('per_target', {}) or {}),
            error=str(data.get('error', '') or ''),
        )


class HistoryStore:
    def __init__(self, path):
        self.path = Path(path)

    def append(self, record):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(asdict(record), ensure_ascii=False, sort_keys=True)
        with open(self.path, 'a', encoding='utf-8') as fh:
            fh.write(line + '\n')
            fh.flush()
            os.fsync(fh.fileno())

    def load(self, limit=50):
        if not self.path.exists():
            return []
        records = []
        for line in self.path.read_text(encoding='utf-8', errors='ignore').splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                records.append(RunRecord.from_dict(json.loads(line)))
            except Exception:
                continue
        return records[-limit:] if limit else records

    def best_preset_ids(self, limit=3):
        ranked = sorted(self.load(limit=0), key=lambda r: (r.ok_count, -r.avg_latency_ms, r.timestamp), reverse=True)
        seen = []
        for record in ranked:
            if record.ok_count > 0 and record.preset_id not in seen:
                seen.append(record.preset_id)
            if len(seen) >= limit:
                break
        return seen
