"""Mock GameStream ADS schema/metrics documents (metric_id aligned)."""

from __future__ import annotations

import os
from pathlib import Path

from datapilot.rag.base import RetrievedDoc

# Paraphrased from GameStream config/metrics.yaml
DOCS: list[dict] = [
    {
        "doc_id": "ads_dau_di",
        "metric_id": "ads_dau_di",
        "title": "ads_dau_di — 日活 DAU",
        "content": (
            "metric_id=ads_dau_di。表 ads_dau_di(dt DATE, server_id INTEGER, dau BIGINT, metric_id VARCHAR)。"
            "口径：当日出现过任意有效行为事件的 player_id 去重（login 优先补全，不强制仅 login）。"
            "粒度：day × server_id。查询昨日 DAU：WHERE dt = current_date - INTERVAL 1 DAY。"
        ),
        "keywords": ["dau", "日活", "活跃", "ads_dau_di", "server_id"],
    },
    {
        "doc_id": "ads_retention_nd",
        "metric_id": "ads_retention_nd",
        "title": "ads_retention_nd — N日留存",
        "content": (
            "metric_id=ads_retention_nd。表 ads_retention_nd(cohort_dt, server_id, n_days, "
            "cohort_size, retained_cnt, retention_rate, metric_id)。"
            "口径：cohort 日新增玩家中，在 day+N 仍有行为的玩家数 / cohort 日新增。"
            "常用 n_days ∈ {1,3,7}。粒度：cohort_day × n_days × server_id。"
        ),
        "keywords": ["留存", "retention", "d1", "d7", "n_days", "ads_retention_nd", "cohort"],
    },
    {
        "doc_id": "ads_arpu_di",
        "metric_id": "ads_arpu_di",
        "title": "ads_arpu_di — ARPU",
        "content": (
            "metric_id=ads_arpu_di。表 ads_arpu_di(dt, server_id, dau, revenue_cny, arpu_cny, metric_id)。"
            "口径：SUM(recharge.amount_fen)/100.0/DAU，单位 CNY。"
            "粒度：day × server_id。"
        ),
        "keywords": ["arpu", "营收", "收入", "revenue", "ads_arpu_di", "arpu_cny"],
    },
    {
        "doc_id": "ads_pay_rate_di",
        "metric_id": "ads_pay_rate_di",
        "title": "ads_pay_rate_di — 付费率",
        "content": (
            "metric_id=ads_pay_rate_di。表 ads_pay_rate_di(dt, server_id, dau, pay_users, pay_rate, metric_id)。"
            "口径：COUNT(DISTINCT player_id WHERE event_type='recharge') / DAU。"
            "粒度：day × server_id。"
        ),
        "keywords": ["付费率", "付费", "pay_rate", "pay_users", "ads_pay_rate_di"],
    },
    {
        "doc_id": "ads_online_duration_di",
        "metric_id": "ads_online_duration_di",
        "title": "ads_online_duration_di — 日在线时长",
        "content": (
            "metric_id=ads_online_duration_di。表含 total_online_sec / players / avg_online_sec。"
            "口径：SUM(session_duration_sec)/COUNT(DISTINCT player_id)；session 由 login→logout 配对。"
        ),
        "keywords": ["在线时长", "online", "duration", "ads_online_duration_di"],
    },
    {
        "doc_id": "ads_dungeon_clear_rate_di",
        "metric_id": "ads_dungeon_clear_rate_di",
        "title": "ads_dungeon_clear_rate_di — 副本通关率",
        "content": (
            "metric_id=ads_dungeon_clear_rate_di。口径：COUNT(clear_dungeon)/COUNT(enter_dungeon)。"
            "粒度：day × dungeon_id × server_id。"
        ),
        "keywords": ["副本", "通关", "dungeon", "clear_rate", "ads_dungeon_clear_rate_di"],
    },
    {
        "doc_id": "ads_churn_di",
        "metric_id": "ads_churn_di",
        "title": "ads_churn_di — 流失风险",
        "content": (
            "metric_id=ads_churn_di。口径：过去7日有行为且过去3日无行为的玩家数 / 过去7日有行为玩家数。"
        ),
        "keywords": ["流失", "churn", "ads_churn_di"],
    },
]


def _metrics_yaml_hint() -> str | None:
    env = os.getenv("DATAPILOT_GAMESTREAM_METRICS")
    candidates = []
    if env:
        candidates.append(Path(env))
    root = Path(__file__).resolve().parents[3]
    candidates.append(root / "data" / "gamestream" / "metrics.yaml")
    for p in candidates:
        if p.is_file():
            return str(p)
    return None


class MockGameStreamRetriever:
    """Keyword RAG over GameStream-aligned ADS docs. Real GameStream client reserved."""

    def retrieve(self, question: str, intent_name: str | None = None, top_k: int = 3) -> list[RetrievedDoc]:
        q = (question or "").lower()
        yaml_path = _metrics_yaml_hint()
        scored: list[tuple[float, dict]] = []
        for d in DOCS:
            score = 0.0
            for kw in d["keywords"]:
                if kw.lower() in q:
                    score += 1.0
            mid = d.get("metric_id", d["doc_id"])
            if intent_name:
                for metric in ("dau", "retention", "arpu", "pay_rate", "revenue", "pay_users", "churn", "dungeon", "online"):
                    if metric in intent_name and (
                        metric in " ".join(d["keywords"]) or metric in mid
                    ):
                        score += 1.0
                if mid.replace("ads_", "").split("_")[0] in intent_name:
                    score += 0.5
            scored.append((score, d))
        scored.sort(key=lambda x: x[0], reverse=True)
        out: list[RetrievedDoc] = []
        for score, d in scored[:top_k]:
            if score <= 0 and out:
                continue
            content = d["content"]
            if yaml_path:
                content += f" 口径源：GameStream metrics.yaml ({yaml_path})；metric_id={d.get('metric_id', d['doc_id'])}。"
            else:
                content += f" metric_id={d.get('metric_id', d['doc_id'])}。"
            out.append(
                RetrievedDoc(
                    doc_id=d["doc_id"],
                    title=d["title"],
                    content=content,
                    score=max(score, 0.1),
                    source="mock_gamestream",
                )
            )
        if not out:
            for d in DOCS[:top_k]:
                out.append(
                    RetrievedDoc(
                        doc_id=d["doc_id"],
                        title=d["title"],
                        content=d["content"] + f" metric_id={d.get('metric_id', d['doc_id'])}。",
                        score=0.1,
                        source="mock_gamestream",
                    )
                )
        return out
