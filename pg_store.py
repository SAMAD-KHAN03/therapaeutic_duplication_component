"""
pg_store.py
-----------
PostgreSQL persistence layer for the Therapeutic Duplication Checker.

Replaces ALL in-memory and disk caching with PostgreSQL-backed storage.

Tables
------
  drug_profiles       – resolved DrugProfile objects (keyed by normalised drug name)
  combination_rules   – NICE CombinationRule objects (keyed by drug-pair + indication hash)
  analysis_results    – full PrescriptionAnalysisReport per request (audit trail)

Environment variables (loaded from .env via python-dotenv)
----------------------------------------------------------
  DB_HOST      (default: localhost)
  DB_PORT      (default: 5432)
  DB_NAME      (required)
  DB_USER      (required)
  DB_PASSWORD  (required)
  DB_POOL_MIN  (default: 2)
  DB_POOL_MAX  (default: 10)
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from contextlib import contextmanager
from typing import Any, Dict, Generator, List, Optional, Tuple

import psycopg2
import psycopg2.extras
from psycopg2 import pool as pgpool
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# Connection pool (module-level singleton)
# ──────────────────────────────────────────────────────────────────────────────

_pool: Optional[pgpool.ThreadedConnectionPool] = None


def _get_pool() -> pgpool.ThreadedConnectionPool:
    global _pool
    if _pool is None:
        _pool = pgpool.ThreadedConnectionPool(
            minconn=int(os.getenv("DB_POOL_MIN", 2)),
            maxconn=int(os.getenv("DB_POOL_MAX", 10)),
            host=os.getenv("DB_HOST", "localhost"),
            port=int(os.getenv("DB_PORT", 5432)),
            dbname=os.getenv("DB_NAME"),
            user=os.getenv("DB_USER"),
            password=os.getenv("DB_PASSWORD"),
            cursor_factory=psycopg2.extras.RealDictCursor,
        )
        logger.info("PostgreSQL connection pool created (min=%s, max=%s)",
                    os.getenv("DB_POOL_MIN", 2), os.getenv("DB_POOL_MAX", 10))
    return _pool


@contextmanager
def _conn() -> Generator:
    """Yield a pooled connection, returning it on exit."""
    p = _get_pool()
    conn = p.getconn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        p.putconn(conn)


# ──────────────────────────────────────────────────────────────────────────────
# Schema bootstrap
# ──────────────────────────────────────────────────────────────────────────────

_DDL = """
CREATE TABLE IF NOT EXISTS drug_profiles (
    drug_key        TEXT PRIMARY KEY,          -- md5 of normalised drug name
    drug_name       TEXT NOT NULL,
    profile_json    JSONB NOT NULL,
    source          TEXT NOT NULL DEFAULT 'fda',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS combination_rules (
    rule_key        TEXT PRIMARY KEY,          -- md5 of (class_a, class_b, name_a, name_b, sorted_indications)
    drug_a_class    TEXT NOT NULL,
    drug_b_class    TEXT NOT NULL,
    drug_a_name     TEXT NOT NULL,
    drug_b_name     TEXT NOT NULL,
    indications     TEXT[] NOT NULL DEFAULT '{}',
    rules_json      JSONB NOT NULL,            -- List[{code, rule}]
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS analysis_results (
    id              BIGSERIAL PRIMARY KEY,
    case_name       TEXT NOT NULL DEFAULT 'unnamed',
    prescription    TEXT[] NOT NULL,
    report_json     JSONB NOT NULL,
    total_pairs     INT NOT NULL DEFAULT 0,
    duplicates      INT NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_drug_profiles_name   ON drug_profiles  (drug_name);
CREATE INDEX IF NOT EXISTS idx_combination_ab       ON combination_rules (drug_a_class, drug_b_class);
CREATE INDEX IF NOT EXISTS idx_analysis_created     ON analysis_results (created_at DESC);
"""


def init_db() -> None:
    """Create tables if they do not exist. Safe to call at startup."""
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(_DDL)
    logger.info("Database schema verified / initialised.")


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _md5(data: str) -> str:
    return hashlib.md5(data.encode()).hexdigest()


def _drug_key(drug_name: str) -> str:
    return _md5(drug_name.strip().lower())


def _rule_key(
    drug_a_class: str,
    drug_b_class: str,
    drug_a_name: str,
    drug_b_name: str,
    indications: List[str],
) -> str:
    payload = json.dumps(
        {
            "a": drug_a_class,
            "b": drug_b_class,
            "an": drug_a_name,
            "bn": drug_b_name,
            "ind": sorted(indications),
        },
        sort_keys=True,
    )
    return _md5(payload)


# ──────────────────────────────────────────────────────────────────────────────
# Drug profile store
# ──────────────────────────────────────────────────────────────────────────────

def load_drug_profile(drug_name: str) -> Optional[Dict]:
    """
    Return the stored profile dict for *drug_name*, or None if not found.
    The caller is responsible for deserialising into a DrugProfile object.
    """
    key = _drug_key(drug_name)
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT profile_json FROM drug_profiles WHERE drug_key = %s",
                (key,),
            )
            row = cur.fetchone()
            if row:
                return dict(row["profile_json"])
    return None


def save_drug_profile(drug_name: str, profile_dict: Dict) -> None:
    """Upsert a drug profile into PostgreSQL."""
    key = _drug_key(drug_name)
    source = profile_dict.get("source", "fda")
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO drug_profiles (drug_key, drug_name, profile_json, source, updated_at)
                VALUES (%s, %s, %s::jsonb, %s, NOW())
                ON CONFLICT (drug_key) DO UPDATE
                    SET profile_json = EXCLUDED.profile_json,
                        source       = EXCLUDED.source,
                        updated_at   = NOW()
                """,
                (key, drug_name.strip().lower(), json.dumps(profile_dict, default=list), source),
            )
    logger.debug("Saved drug profile: %s (source=%s)", drug_name, source)


# ──────────────────────────────────────────────────────────────────────────────
# Combination rules store
# ──────────────────────────────────────────────────────────────────────────────

def load_combination_rules(
    drug_a_class: str,
    drug_b_class: str,
    drug_a_name: str,
    drug_b_name: str,
    indications: List[str],
) -> Optional[List[Dict]]:
    """
    Return a list of {code, rule} dicts, or None if no cached entry exists.
    An empty list [] is a valid cached result (no rules found).
    """
    key = _rule_key(drug_a_class, drug_b_class, drug_a_name, drug_b_name, indications)
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT rules_json FROM combination_rules WHERE rule_key = %s",
                (key,),
            )
            row = cur.fetchone()
            if row is not None:
                return list(row["rules_json"])
    return None


def save_combination_rules(
    drug_a_class: str,
    drug_b_class: str,
    drug_a_name: str,
    drug_b_name: str,
    indications: List[str],
    rules: List[Dict],
) -> None:
    """Upsert NICE combination rules."""
    key = _rule_key(drug_a_class, drug_b_class, drug_a_name, drug_b_name, indications)
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO combination_rules
                    (rule_key, drug_a_class, drug_b_class, drug_a_name, drug_b_name,
                     indications, rules_json, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, NOW())
                ON CONFLICT (rule_key) DO UPDATE
                    SET rules_json = EXCLUDED.rules_json,
                        updated_at = NOW()
                """,
                (
                    key,
                    drug_a_class, drug_b_class,
                    drug_a_name,  drug_b_name,
                    indications,
                    json.dumps(rules, default=list),
                ),
            )
    logger.debug(
        "Saved %d combination rule(s) for %s+%s", len(rules), drug_a_name, drug_b_name
    )


# ──────────────────────────────────────────────────────────────────────────────
# Analysis results store (audit trail)
# ──────────────────────────────────────────────────────────────────────────────

def save_analysis_result(
    case_name: str,
    prescription: List[str],
    report_dict: Dict,
) -> int:
    """Persist a full analysis report and return the generated row id."""
    summary = report_dict.get("summary", {})
    total   = summary.get("total_pairs", 0)
    dupes   = summary.get("overlaps_detected", 0)

    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO analysis_results
                    (case_name, prescription, report_json, total_pairs, duplicates)
                VALUES (%s, %s, %s::jsonb, %s, %s)
                RETURNING id
                """,
                (
                    case_name,
                    prescription,
                    json.dumps(report_dict, default=list),
                    total,
                    dupes,
                ),
            )
            row = cur.fetchone()
            row_id = row["id"] if row else -1

    logger.debug("Saved analysis result id=%d for case='%s'", row_id, case_name)
    return row_id


def get_recent_analyses(limit: int = 50) -> List[Dict]:
    """Return the most recent *limit* analysis results (metadata only, no full JSON)."""
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, case_name, prescription, total_pairs, duplicates, created_at
                FROM   analysis_results
                ORDER  BY created_at DESC
                LIMIT  %s
                """,
                (limit,),
            )
            return [dict(r) for r in cur.fetchall()]


def get_db_stats() -> Dict[str, Any]:
    """Return row counts for all tables — used by the /database/stats endpoint."""
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS n FROM drug_profiles")
            drug_count = cur.fetchone()["n"]

            cur.execute("SELECT COUNT(*) AS n FROM combination_rules")
            rule_count = cur.fetchone()["n"]

            cur.execute("SELECT COUNT(*) AS n FROM analysis_results")
            analysis_count = cur.fetchone()["n"]

            cur.execute(
                "SELECT created_at FROM analysis_results ORDER BY created_at DESC LIMIT 1"
            )
            last_row = cur.fetchone()
            last_analysis = str(last_row["created_at"]) if last_row else None

    return {
        "drug_profiles":     drug_count,
        "combination_rules": rule_count,
        "analysis_results":  analysis_count,
        "last_analysis_at":  last_analysis,
    }


def close_pool() -> None:
    """Gracefully close the connection pool (call on server shutdown)."""
    global _pool
    if _pool:
        _pool.closeall()
        _pool = None
        logger.info("PostgreSQL connection pool closed.")