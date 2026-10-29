"""Extraction step of the WEC RAG (ADR-001): PDF -> clean JSON, then QA gate.

Exits with an error if the QA reports a blocking issue: do not index then.

Usage: python run_pipeline.py [pdf] [output_dir]
"""

import subprocess
import sys
from pathlib import Path

pdf = sys.argv[1] if len(sys.argv) > 1 else "docs/pdf/2026_WEC.pdf"
out = Path(sys.argv[2] if len(sys.argv) > 2 else "output")
rules = out / "2026_WEC_rules_en.v2.json"
report = out / "qa_report.md"
here = Path(__file__).resolve().parent


def run(step, args):
    print(f"\n=== {step} ===")
    return subprocess.run([sys.executable, str(here / args[0]), *map(str, args[1:])]).returncode


if run("1/2 Extraction", ["extract_rules_v2.py", pdf, rules, here / "figures.json"]) != 0:
    sys.exit("Extraction failed.")
if run("2/2 Quality checks", ["qa_rules.py", pdf, rules, report]) != 0:
    sys.exit(f"QA FAILED: see {report}. Do not index {rules}.")
print(f"\nDone. Clean extraction: {rules}\nReview the items needing a human decision in: {report}")
