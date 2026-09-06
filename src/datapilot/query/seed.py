"""Seed GameStream-aligned ADS demo tables into DuckDB (flat names, no schema prefix)."""

from __future__ import annotations

from datetime import date, timedelta
import random
from typing import Any

SERVER_IDS = (0, 1, 2)

_OLD_TABLES = (
    "ads_dau_daily",
    "ads_retention_daily",
    "ads_revenue_daily",
)


def seed_demo_data(conn: Any, days: int = 14, seed: int = 42) -> None:
    rng = random.Random(seed)
    today = date.today()
    start = today - timedelta(days=days)

    for t in _OLD_TABLES:
        conn.execute(f"DROP TABLE IF EXISTS {t}")

    for t in (
        "ads_dau_di",
        "ads_retention_nd",
        "ads_arpu_di",
        "ads_pay_rate_di",
        "ads_online_duration_di",
        "ads_dungeon_clear_rate_di",
        "ads_churn_di",
    ):
        conn.execute(f"DROP TABLE IF EXISTS {t}")

    conn.execute(
        """
        CREATE TABLE ads_dau_di (
            dt DATE,
            server_id INTEGER,
            dau BIGINT,
            metric_id VARCHAR
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE ads_retention_nd (
            cohort_dt DATE,
            server_id INTEGER,
            n_days INTEGER,
            cohort_size BIGINT,
            retained_cnt BIGINT,
            retention_rate DOUBLE,
            metric_id VARCHAR
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE ads_arpu_di (
            dt DATE,
            server_id INTEGER,
            dau BIGINT,
            revenue_cny DOUBLE,
            arpu_cny DOUBLE,
            metric_id VARCHAR
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE ads_pay_rate_di (
            dt DATE,
            server_id INTEGER,
            dau BIGINT,
            pay_users BIGINT,
            pay_rate DOUBLE,
            metric_id VARCHAR
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE ads_online_duration_di (
            dt DATE,
            server_id INTEGER,
            total_online_sec BIGINT,
            players BIGINT,
            avg_online_sec DOUBLE,
            metric_id VARCHAR
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE ads_dungeon_clear_rate_di (
            dt DATE,
            server_id INTEGER,
            dungeon_id INTEGER,
            enter_cnt BIGINT,
            clear_cnt BIGINT,
            clear_rate DOUBLE,
            metric_id VARCHAR
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE ads_churn_di (
            dt DATE,
            server_id INTEGER,
            active_7d_users BIGINT,
            churn_risk_users BIGINT,
            churn_risk_rate DOUBLE,
            metric_id VARCHAR
        )
        """
    )

    base_by_server = {0: 45_000, 1: 38_000, 2: 32_000}
    d = start
    while d < today:
        for sid in SERVER_IDS:
            base = base_by_server[sid]
            dau = max(1000, int(base + rng.randint(-2500, 2500)))
            conn.execute(
                "INSERT INTO ads_dau_di VALUES (?, ?, ?, ?)",
                [d, sid, dau, "ads_dau_di"],
            )

            pay_rate = round(0.035 + rng.random() * 0.025, 4)
            pay_users = max(1, int(dau * pay_rate))
            arpu = round(1.1 + rng.random() * 0.9, 4)
            revenue = round(dau * arpu * 0.12, 2)
            conn.execute(
                "INSERT INTO ads_arpu_di VALUES (?, ?, ?, ?, ?, ?)",
                [d, sid, dau, revenue, arpu, "ads_arpu_di"],
            )
            conn.execute(
                "INSERT INTO ads_pay_rate_di VALUES (?, ?, ?, ?, ?, ?)",
                [d, sid, dau, pay_users, pay_rate, "ads_pay_rate_di"],
            )

            players = dau
            avg_sec = round(1800 + rng.random() * 1200, 2)
            total_sec = int(avg_sec * players)
            conn.execute(
                "INSERT INTO ads_online_duration_di VALUES (?, ?, ?, ?, ?, ?)",
                [d, sid, total_sec, players, avg_sec, "ads_online_duration_di"],
            )

            for dungeon_id in (101, 102):
                enter_cnt = int(dau * (0.15 + rng.random() * 0.1))
                clear_rate = round(0.35 + rng.random() * 0.3, 4)
                clear_cnt = int(enter_cnt * clear_rate)
                conn.execute(
                    "INSERT INTO ads_dungeon_clear_rate_di VALUES (?, ?, ?, ?, ?, ?, ?)",
                    [d, sid, dungeon_id, enter_cnt, clear_cnt, clear_rate, "ads_dungeon_clear_rate_di"],
                )

            active_7d = int(dau * (1.4 + rng.random() * 0.3))
            churn_rate = round(0.08 + rng.random() * 0.06, 4)
            churn_users = int(active_7d * churn_rate)
            conn.execute(
                "INSERT INTO ads_churn_di VALUES (?, ?, ?, ?, ?, ?)",
                [d, sid, active_7d, churn_users, churn_rate, "ads_churn_di"],
            )

            # retention: cohort on this day, n_days in {1,3,7}
            cohort_size = max(500, int(dau * 0.08 + rng.randint(-80, 80)))
            for n_days, base_r in ((1, 0.38), (3, 0.22), (7, 0.14)):
                rate = round(base_r + rng.random() * 0.06 - 0.02, 4)
                rate = max(0.01, min(0.95, rate))
                retained = int(cohort_size * rate)
                conn.execute(
                    "INSERT INTO ads_retention_nd VALUES (?, ?, ?, ?, ?, ?, ?)",
                    [d, sid, n_days, cohort_size, retained, rate, "ads_retention_nd"],
                )

            base_by_server[sid] = base + rng.randint(-1200, 1500)

        d += timedelta(days=1)
