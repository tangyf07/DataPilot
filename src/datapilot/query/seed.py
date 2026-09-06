"""Seed GameStream-like ADS demo tables into DuckDB."""

from __future__ import annotations

from datetime import date, timedelta
import random
from typing import Any


def seed_demo_data(conn: Any, days: int = 14, seed: int = 42) -> None:
    rng = random.Random(seed)
    today = date.today()
    start = today - timedelta(days=days)

    conn.execute("DROP TABLE IF EXISTS ads_dau_daily")
    conn.execute("DROP TABLE IF EXISTS ads_retention_daily")
    conn.execute("DROP TABLE IF EXISTS ads_revenue_daily")

    conn.execute(
        """
        CREATE TABLE ads_dau_daily (
            dt DATE,
            dau BIGINT,
            platform VARCHAR
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE ads_retention_daily (
            dt DATE,
            retention_d1 DOUBLE,
            retention_d7 DOUBLE
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE ads_revenue_daily (
            dt DATE,
            revenue DOUBLE,
            pay_users BIGINT,
            arpu DOUBLE,
            pay_rate DOUBLE
        )
        """
    )

    d = start
    base_dau = 120_000
    while d < today:
        ios = int(base_dau * 0.42 + rng.randint(-3000, 3000))
        android = int(base_dau * 0.55 + rng.randint(-4000, 4000))
        all_dau = ios + android
        conn.execute(
            "INSERT INTO ads_dau_daily VALUES (?, ?, ?), (?, ?, ?), (?, ?, ?)",
            [d, ios, "iOS", d, android, "Android", d, all_dau, "All"],
        )
        r1 = round(0.35 + rng.random() * 0.08, 4)
        r7 = round(0.12 + rng.random() * 0.05, 4)
        conn.execute(
            "INSERT INTO ads_retention_daily VALUES (?, ?, ?)",
            [d, r1, r7],
        )
        pay_rate = round(0.04 + rng.random() * 0.02, 4)
        pay_users = int(all_dau * pay_rate)
        arpu = round(1.2 + rng.random() * 0.8, 4)
        revenue = round(all_dau * arpu * 0.15, 2)
        conn.execute(
            "INSERT INTO ads_revenue_daily VALUES (?, ?, ?, ?, ?)",
            [d, revenue, pay_users, arpu, pay_rate],
        )
        base_dau += rng.randint(-2000, 2500)
        d += timedelta(days=1)
