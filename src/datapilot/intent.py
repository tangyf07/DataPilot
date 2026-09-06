"""Intent recognition — rules offline, optional LLM later."""

from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass
class Intent:
    name: str
    metric: str | None
    time_hint: str | None
    server_id: int | None
    raw: str
    confidence: float
    # kept for backward-compat in traces; always None (platform dim removed)
    platform: str | None = None


_METRIC_PATTERNS: list[tuple[str, str]] = [
    (r"dau|日活|活跃", "dau"),
    (r"留存|retention|d1|d7|次留", "retention"),
    (r"arpu", "arpu"),
    (r"付费率|付费.?率|pay.?rate", "pay_rate"),
    (r"营收|收入|revenue", "revenue"),
    (r"付费用户|pay.?user", "pay_users"),
    (r"在线时长|online.?duration", "online_duration"),
    (r"副本|通关|dungeon", "dungeon_clear"),
    (r"流失|churn", "churn"),
]


def recognize_intent(question: str) -> Intent:
    q = question.strip()
    ql = q.lower()
    metric = None
    for pat, name in _METRIC_PATTERNS:
        if re.search(pat, ql, re.I):
            metric = name
            break

    time_hint = None
    if re.search(r"昨天|昨日|yesterday", ql, re.I):
        time_hint = "yesterday"
    elif re.search(r"今天|今日|today", ql, re.I):
        time_hint = "today"
    elif re.search(r"近\s*7|最近7|过去7|last\s*7|7\s*天", ql, re.I):
        time_hint = "last_7_days"
    elif re.search(r"近\s*14|最近14|过去14|last\s*14|14\s*天", ql, re.I):
        time_hint = "last_14_days"
    else:
        time_hint = "latest"

    server_id = None
    m = re.search(r"(?:server[_ ]?id|区服|服务器)\s*[=:：]?\s*(\d+)", ql, re.I)
    if m:
        server_id = int(m.group(1))
    else:
        m2 = re.search(r"(\d+)\s*服", ql)
        if m2:
            server_id = int(m2.group(1))

    if metric is None:
        name = "unknown"
        conf = 0.3
    else:
        name = f"query_{metric}"
        conf = 0.9 if time_hint else 0.7

    return Intent(
        name=name,
        metric=metric,
        time_hint=time_hint,
        server_id=server_id,
        raw=q,
        confidence=conf,
        platform=None,
    )
