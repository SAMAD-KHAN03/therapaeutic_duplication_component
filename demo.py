"""
demo.py
-------
Runs all 10 TD test cases from the validated case scenario spreadsheet.

Expected outcomes per case:
  TD_1  (ACEi + CCB + Thiazide)          → Overlap w/ rationale     [NG136]
  TD_2  (Statin + Ezetimibe)             → Overlap w/ rationale     [NG238]
  TD_3  (HFrEF quad: ACEi+BB+MRA+SGLT2) → Overlap w/ rationale     [NG106]
  TD_4  (T2DM: Metformin+SGLT2i+SU)     → Overlap w/ rationale     [NG28]
  TD_5  (RA: MTX + SSZ + Folic Acid)     → Overlap w/ rationale     [NG100]
  TD_6  (TB: HRZE quad)                  → Overlap w/ rationale     [NG33]
  TD_7  (Ibuprofen + Naproxen)           → Redundant [NG226]
  TA_8  (Ramipril + Lisinopril)          → Redundant [NG136]
  TA_9  (Sertraline + Fluoxetine)        → Redundant [NG222]
  TA_10 (Insulin glargine + detemir)     → Redundant [NG28]
"""

import logging
import sys
import os

logging.basicConfig(
    level=logging.WARNING,       # suppress INFO noise; change to INFO for debugging
    format="%(levelname)s | %(name)s | %(message)s",
    stream=sys.stdout,
)

# Ensure our module dir is on the path
sys.path.insert(0, os.path.dirname(__file__))

from therapeutic_duplication_checker import TherapeuticDuplicationChecker

TEST_CASES = [
    {
        "name": "TD_1 – Dual Antihypertensive Therapy (ACEi + CCB + Thiazide)",
        "prescription": ["lisinopril", "amlodipine", "indapamide"],
        "expected": "Overlap w/ rationale – NG136",
    },
    {
        "name": "TD_2 – Statin + Ezetimibe (Secondary CVD Prevention)",
        "prescription": ["atorvastatin", "ezetimibe"],
        "expected": "Overlap w/ rationale – NG238",
    },
    {
        "name": "TD_3 – HFrEF Quadruple Therapy (ACEi + BB + MRA + SGLT2i)",
        "prescription": ["ramipril", "bisoprolol", "spironolactone", "empagliflozin"],
        "expected": "Overlap w/ rationale – NG106",
    },
    {
        "name": "TD_4 – T2DM Triple Therapy (Metformin + SGLT2i + SU)",
        "prescription": ["metformin", "empagliflozin", "gliclazide"],
        "expected": "Overlap w/ rationale – NG28",
    },
    {
        "name": "TD_5 – RA csDMARD Combination (MTX + SSZ + Folic Acid)",
        "prescription": ["methotrexate", "sulfasalazine", "folic acid"],
        "expected": "Overlap w/ rationale – NG100",
    },
    {
        "name": "TD_6 – TB Initial Phase (HRZE Quad Therapy)",
        "prescription": ["isoniazid", "rifampicin", "pyrazinamide", "ethambutol"],
        "expected": "Overlap w/ rationale – NG33",
    },
    {
        "name": "TA_7 – Dual NSAID (Ibuprofen + Naproxen)",
        "prescription": ["ibuprofen", "naproxen"],
        "expected": "Redundant [not supported by guideline] – NG226",
    },
    {
        "name": "TA_8 – Dual ACE Inhibitor (Ramipril + Lisinopril)",
        "prescription": ["ramipril", "lisinopril"],
        "expected": "Redundant [not supported by guideline] – NG136",
    },
    {
        "name": "TA_9 – Dual SSRI (Sertraline + Fluoxetine)",
        "prescription": ["sertraline", "fluoxetine"],
        "expected": "Redundant [not supported by guideline] – NG222",
    },
    {
        "name": "TA_10 – Dual Basal Insulin (Insulin glargine + Insulin detemir)",
        "prescription": ["insulin glargine", "insulin detemir"],
        "expected": "Redundant [not supported by guideline] – NG28",
    },
]


if __name__ == "__main__":
    checker = TherapeuticDuplicationChecker(cache_dir="./cache")

    for case in TEST_CASES:
        print(f"\n{'#' * 90}")
        print(f"# {case['name']}")
        print(f"# Expected: {case['expected']}")
        print(f"{'#' * 90}")
        report = checker.analyse(case["prescription"])
        print(checker.format_report(report))
        print()

        request=[{
            "name":"<disease name>",
            "prescription":["<list of medicines>"]
        }]