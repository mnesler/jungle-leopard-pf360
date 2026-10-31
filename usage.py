"""Local Claude Code usage totals, read from ~/.claude/projects/**/*.jsonl.

Nothing leaves the machine and no credentials are used. Per-file results are
cached by (mtime, size) so refreshes only re-parse files that changed.
"""
import json
import threading
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path.home() / ".claude" / "projects"


def _parse(path):
    """Return {msg_id: (local_date, model, in, out, cache_read, cache_write)}.
    Streamed messages repeat an id; the last record holds the final counts."""
    out = {}
    with open(path, encoding="utf8", errors="replace") as f:
        for line in f:
            if '"usage"' not in line:
                continue
            try:
                r = json.loads(line)
                m = r["message"]
                u = m["usage"]
                ts = datetime.fromisoformat(r["timestamp"].replace("Z", "+00:00")).astimezone()
            except Exception:
                continue
            mid = m.get("id") or r.get("uuid")
            out[mid] = (
                ts.date(),
                m.get("model", "unknown"),
                u.get("input_tokens", 0),
                u.get("output_tokens", 0),
                u.get("cache_read_input_tokens", 0),
                u.get("cache_creation_input_tokens", 0),
            )
    return out


class UsageStats:
    def __init__(self, every=30):
        self.every = every
        self._cache = {}  # path -> ((mtime, size), records)
        self.days = {}  # date -> {"tokens": n, "msgs": n}
        self.models = defaultdict(int)  # model -> tokens (last 7 days)
        self.updated = None
        self.error = None
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self):
        while True:
            try:
                self.refresh()
                self.error = None
            except Exception as e:
                self.error = str(e)[:60]
            time.sleep(self.every)

    def refresh(self):
        seen = {}
        for p in ROOT.glob("*/*.jsonl"):
            st = p.stat()
            key = (st.st_mtime, st.st_size)
            if p not in self._cache or self._cache[p][0] != key:
                self._cache[p] = (key, _parse(p))
            seen.update(self._cache[p][1])  # dedupe across files by message id
        days = defaultdict(lambda: {"tokens": 0, "msgs": 0})
        models = defaultdict(int)
        week_start = datetime.now().date() - timedelta(days=6)
        for date, model, i, o, cr, cw in seen.values():
            total = i + o + cr + cw
            days[date]["tokens"] += total
            days[date]["msgs"] += 1
            if date >= week_start:
                models[model] += total
        self.days, self.models, self.updated = dict(days), dict(models), datetime.now()

    def last_days(self, n=7):
        today = datetime.now().date()
        return [(today - timedelta(days=k), self.days.get(today - timedelta(days=k), {"tokens": 0, "msgs": 0}))
                for k in range(n - 1, -1, -1)]


def fmt(n):
    for unit, div in (("B", 1e9), ("M", 1e6), ("K", 1e3)):
        if n >= div:
            return f"{n / div:.1f}{unit}"
    return str(int(n))


if __name__ == "__main__":
    u = UsageStats()
    u.refresh()
    for d, v in u.last_days():
        print(d, fmt(v["tokens"]), v["msgs"], "msgs")
    print(dict(u.models))
