"""Mock GameStream ADS schema/metrics documents."""

from __future__ import annotations

from datapilot.rag.base import RetrievedDoc

DOCS: list[dict] = [
    {
        "doc_id": "ads_dau_daily",
        "title": "ads_dau_daily — 日活 DAU",
        "content": (
            "表 ads_dau_daily(dt DATE, dau BIGINT, platform VARCHAR)。"
            "指标 DAU：每日活跃用户数，按平台(iOS/Android/All)拆分。"
            "查询昨日 DAU 可用 WHERE dt = current_date - 1。"
            "GameStream ADS 层日汇总表（mock）。"
        ),
        "keywords": ["dau", "日活", "活跃", "platform"],
    },
    {
        "doc_id": "ads_retention_daily",
        "title": "ads_retention_daily — 留存",
        "content": (
            "表 ads_retention_daily(dt DATE, retention_d1 DOUBLE, retention_d7 DOUBLE)。"
            "retention_d1 / retention_d7 为次日/7日留存率（0-1）。"
            "GameStream ADS 留存日表（mock）。"
        ),
        "keywords": ["留存", "retention", "d1", "d7"],
    },
    {
        "doc_id": "ads_revenue_daily",
        "title": "ads_revenue_daily — 营收与付费",
        "content": (
            "表 ads_revenue_daily(dt DATE, revenue DOUBLE, pay_users BIGINT, arpu DOUBLE, pay_rate DOUBLE)。"
            "revenue 营收；pay_users 付费用户；arpu = revenue/dau 近似；pay_rate 付费率。"
            "GameStream ADS 营收日表（mock）。"
        ),
        "keywords": ["arpu", "付费率", "营收", "收入", "revenue", "pay", "付费"],
    },
]


class MockGameStreamRetriever:
    """Keyword RAG over mock ADS docs. Real GameStream client reserved."""

    def retrieve(self, question: str, intent_name: str | None = None, top_k: int = 3) -> list[RetrievedDoc]:
        q = (question or "").lower()
        scored: list[tuple[float, dict]] = []
        for d in DOCS:
            score = 0.0
            for kw in d["keywords"]:
                if kw.lower() in q:
                    score += 1.0
            if intent_name and d["doc_id"].replace("ads_", "").split("_")[0] in (intent_name or ""):
                score += 0.5
            if intent_name and any(k in (intent_name or "") for k in d["keywords"]):
                score += 0.5
            # metric name in intent
            for metric in ("dau", "retention", "arpu", "pay_rate", "revenue", "pay_users"):
                if intent_name and metric in intent_name and metric in " ".join(d["keywords"]):
                    score += 1.0
            scored.append((score, d))
        scored.sort(key=lambda x: x[0], reverse=True)
        out: list[RetrievedDoc] = []
        for score, d in scored[:top_k]:
            if score <= 0 and out:
                continue
            out.append(
                RetrievedDoc(
                    doc_id=d["doc_id"],
                    title=d["title"],
                    content=d["content"],
                    score=max(score, 0.1),
                    source="mock_gamestream",
                )
            )
        if not out:
            # fallback: return all lightly
            for d in DOCS[:top_k]:
                out.append(
                    RetrievedDoc(
                        doc_id=d["doc_id"],
                        title=d["title"],
                        content=d["content"],
                        score=0.1,
                        source="mock_gamestream",
                    )
                )
        return out
