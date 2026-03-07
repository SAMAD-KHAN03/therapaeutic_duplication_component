"""
local_test_server.py
--------------------
A lightweight version of the server for local development and testing.
- Uses an In-Memory 'database' instead of PostgreSQL.
- Disables persistence by default.
- Optimized for rapid request/response debugging.
"""

import time
import uuid
from flask import Flask, jsonify, request, Response
from typing import List, Dict, Any

# Import your core logic
from therapeutic_duplication_checker import TherapeuticDuplicationChecker

app = Flask(__name__)

# --- Mock In-Memory Store ---
# This replaces pg_store for local testing
MOCK_DB: List[Dict[str, Any]] = []

def save_to_mock_db(case_name: str, prescription: List[str], report: Dict):
    entry = {
        "id": str(uuid.uuid4()),
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "case_name": case_name,
        "prescription": prescription,
        "overlaps": report["summary"]["overlaps_detected"]
    }
    MOCK_DB.append(entry)
    return entry["id"]

# --- Initialize Checker ---
# It will use the non-cached versions of FDA/NICE if you updated those files
checker = TherapeuticDuplicationChecker()

# --- Helper: Serialize (Same logic as your main server) ---
def _serialise_report(case_name: str, report) -> Dict[str, Any]:
    # ... [Keep your existing serialization logic here] ...
    # Simplified version for the example:
    return {
        "case_name": case_name,
        "prescription": report.medications,
        "summary": {
            "overlaps_detected": len(report.duplicate_pairs),
        },
        "pair_results": [
            {
                "drug_a": r.drug_a,
                "drug_b": r.drug_b,
                "outcome": r.outcome.name
            } for r in report.pair_results
        ]
    }

# --- Routes ---

@app.route("/api/v1/health", methods=["GET"])
def health():
    return jsonify({
        "status": "online",
        "mode": "local-testing",
        "storage": "in-memory"
    })

@app.route("/api/v1/check", methods=["POST"])
def check():
    data = request.get_json()
    if not data or not isinstance(data, list):
        return jsonify({"error": "Expected a list of cases"}), 400

    results = []
    t_start = time.perf_counter()

    for case in data:
        name = case.get("name", "Test Case")
        drugs = case.get("prescription", [])
        
        # Run the analysis
        report = checker.analyse(drugs)
        report_dict = _serialise_report(name, report)
        
        # Save to our fake local DB
        row_id = save_to_mock_db(name, drugs, report_dict)
        report_dict["local_id"] = row_id
        
        results.append(report_dict)

    elapsed = (time.perf_counter() - t_start) * 1000
    return jsonify({
        "results": results,
        "processing_ms": round(elapsed, 2)
    })

@app.route("/api/v1/database/recent", methods=["GET"])
def recent():
    # View what has been "saved" during this session
    return jsonify(MOCK_DB[::-1])

if __name__ == "__main__":
    print("🚀 Starting Local Test Server (No PostgreSQL Required)")
    app.run(host="127.0.0.1", port=8000, debug=True)