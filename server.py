"""
server.py
---------
Flask REST API for the Therapeutic Duplication Checker.

Endpoints
---------
POST /api/v1/check            – analyse one or more prescription cases
GET  /api/v1/health           – liveness / readiness probe (includes DB status)
GET  /api/v1/guidelines       – list NICE guideline codes in static library
GET  /api/v1/database/stats   – PostgreSQL row counts + last-activity timestamp
GET  /api/v1/database/recent  – recent analysis metadata (?limit=50, max 200)

Usage
-----
    python server.py                  # default: http://0.0.0.0:8000
    python server.py --port 5000
    python server.py --host 127.0.0.1 --port 8080
    python server.py --debug          # auto-reload, verbose errors
"""

from __future__ import annotations

import argparse
import atexit
import logging
import os
import sys
import time
from typing import Any, Dict, List, Optional

from flask import Flask, Response, jsonify, request

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import pg_store
from therapeutic_duplication_checker import TherapeuticDuplicationChecker, PairOutcome

# ──────────────────────────────────────────────────────────────────────────────
# Logging
# ──────────────────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger("td_server")

# ──────────────────────────────────────────────────────────────────────────────
# Startup: init DB schema then checker
# ──────────────────────────────────────────────────────────────────────────────

logger.info("Initialising PostgreSQL schema...")
pg_store.init_db()
logger.info("Database schema ready.")

logger.info("Initialising TherapeuticDuplicationChecker...")
checker = TherapeuticDuplicationChecker()
logger.info("Checker ready.")

atexit.register(pg_store.close_pool)

# ──────────────────────────────────────────────────────────────────────────────
# Flask app
# ──────────────────────────────────────────────────────────────────────────────

app = Flask(__name__)
app.config["JSON_SORT_KEYS"] = False


def _error(message: str, status: int = 400) -> Response:
    return jsonify({"error": message}), status


def _serialise_pair_result(result) -> Dict[str, Any]:
    nice_detail: Optional[Dict] = None
    if result.nice_rules_found:
        code, rule = result.nice_rules_found[0]
        nice_detail = {
            "guideline_code":      code,
            "section_ref":         rule.section_ref,
            "recommendation":      rule.recommendation,
            "recommendation_text": rule.recommendation_text,
            "rationale":           rule.rationale,
            "conditions":          list(rule.conditions),
            "url":                 rule.url,
        }
    return {
        "drug_a":             result.drug_a,
        "drug_b":             result.drug_b,
        "outcome":            result.outcome.value,
        "outcome_code":       result.outcome.name,
        "is_duplicate":       result.is_duplicate,
        "overlap_reasons":    [r.value for r in result.duplicate_reasons],
        "shared_classes":     result.shared_classes,
        "shared_moas":        result.shared_moas,
        "shared_indications": sorted(result.shared_indications),
        "nice_detail":        nice_detail,
    }


def _serialise_report(case_name: str, report) -> Dict[str, Any]:
    medications = []
    for med in report.medications:
        profile = report.resolved_profiles.get(med)
        if profile:
            medications.append({
                "name":                med,
                "resolved":            True,
                "drug_class":          profile.drug_class,
                "mechanism_of_action": profile.mechanism_of_action,
                "source":              getattr(profile, "source", "fda"),
                "brand_names":         getattr(profile, "brand_names", []),
                "indications":         sorted(profile.indications),
            })
        else:
            medications.append({"name": med, "resolved": False})

    return {
        "case_name":    case_name,
        "prescription": report.medications,
        "summary": {
            "total_pairs":            len(report.pair_results),
            "unique_pairs":           len(report.unique_pairs),
            "overlaps_detected":      len(report.duplicate_pairs),
            "overlap_with_rationale": len(report.supported_combinations),
            "redundant_or_contra":    len(report.unsupported_duplicates),
        },
        "medications":      medications,
        "unresolved_drugs": report.unresolved_drugs,
        "pair_results":     [_serialise_pair_result(r) for r in report.pair_results],
        "formatted_report": checker.format_report(report),
    }


def _validate_request(body: Any) -> Optional[str]:
    if not isinstance(body, list):
        return "Request body must be a JSON array."
    if not body:
        return "Request array must contain at least one case."
    for i, case in enumerate(body):
        if not isinstance(case, dict):
            return f"Item at index {i} must be an object."
        if "prescription" not in case:
            return f"Item at index {i} is missing required field 'prescription'."
        if not isinstance(case["prescription"], list):
            return f"Item at index {i}: 'prescription' must be an array of drug name strings."
        if not case["prescription"]:
            return f"Item at index {i}: 'prescription' must contain at least one drug."
        for j, drug in enumerate(case["prescription"]):
            if not isinstance(drug, str) or not drug.strip():
                return (
                    f"Item at index {i}, prescription[{j}]: "
                    "each drug must be a non-empty string."
                )
    return None


# ── routes ────────────────────────────────────────────────────────────────────

@app.get("/api/v1/health")
def health():
    try:
        pg_store.get_db_stats()
        db_status = "ok"
    except Exception as exc:
        db_status = f"error: {exc}"
    return jsonify({
        "status":    "ok",
        "service":   "therapeutic-duplication-checker",
        "db_status": db_status,
    })


@app.get("/api/v1/guidelines")
def list_guidelines():
    try:
        codes = checker._nice.list_available_guidelines()
        return jsonify({"guideline_codes": codes, "count": len(codes)})
    except Exception as exc:
        logger.exception("Error listing guidelines")
        return _error(str(exc), 500)


@app.get("/api/v1/database/stats")
def database_stats():
    try:
        return jsonify(pg_store.get_db_stats())
    except Exception as exc:
        logger.exception("Error fetching DB stats")
        return _error(str(exc), 500)


@app.get("/api/v1/database/recent")
def database_recent():
    try:
        limit = min(int(request.args.get("limit", 50)), 200)
        rows  = pg_store.get_recent_analyses(limit)
        for row in rows:
            if "created_at" in row and hasattr(row["created_at"], "isoformat"):
                row["created_at"] = row["created_at"].isoformat()
        return jsonify({"results": rows, "count": len(rows)})
    except Exception as exc:
        logger.exception("Error fetching recent analyses")
        return _error(str(exc), 500)


@app.post("/api/v1/check")
def check():
    if not request.is_json:
        return _error("Content-Type must be application/json.")
    try:
        body = request.get_json(force=True)
    except Exception:
        return _error("Request body is not valid JSON.")

    err = _validate_request(body)
    if err:
        return _error(err)

    t_start = time.perf_counter()
    results: List[Dict] = []

    for case in body:
        case_name    = (case.get("name") or "Unnamed case").strip() or "Unnamed case"
        prescription = [d.strip() for d in case["prescription"] if d.strip()]

        logger.info("Analysing case '%s' | drugs: %s", case_name, ", ".join(prescription))

        try:
            report      = checker.analyse(prescription)
            report_dict = _serialise_report(case_name, report)

            try:
                row_id = pg_store.save_analysis_result(case_name, prescription, report_dict)
                report_dict["db_row_id"] = row_id
            except Exception as db_exc:
                logger.warning("PG save failed for case '%s': %s", case_name, db_exc)

            results.append(report_dict)

        except Exception as exc:
            logger.exception("Error analysing case '%s'", case_name)
            results.append({
                "case_name":    case_name,
                "prescription": prescription,
                "error":        str(exc),
            })

    elapsed_ms = (time.perf_counter() - t_start) * 1000
    logger.info("Completed %d case(s) in %.1f ms", len(results), elapsed_ms)

    return jsonify({
        "results": results,
        "meta": {
            "total_cases":        len(results),
            "processing_time_ms": round(elapsed_ms, 2),
        },
    })


@app.errorhandler(404)
def not_found(e):
    return _error(
        "Endpoint not found. Available: POST /api/v1/check  GET /api/v1/health  "
        "GET /api/v1/guidelines  GET /api/v1/database/stats  GET /api/v1/database/recent",
        404,
    )


@app.errorhandler(405)
def method_not_allowed(e):
    return _error("Method not allowed.", 405)


# ──────────────────────────────────────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────────────────────────────────────

def _parse_args():
    p = argparse.ArgumentParser(description="Therapeutic Duplication Checker API Server")
    p.add_argument("--host",  default="0.0.0.0",  help="Bind host (default: 0.0.0.0)")
    p.add_argument("--port",  default=8000, type=int, help="Bind port (default: 8000)")
    p.add_argument("--debug", action="store_true",   help="Enable Flask debug / auto-reload")
    return p.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    logger.info("Starting server on %s:%d  debug=%s", args.host, args.port, args.debug)
    app.run(host=args.host, port=args.port, debug=args.debug)