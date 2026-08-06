"""CLI Entrypoint for running MedAgentBench evaluation suite on VMEC-01."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from eval.evaluator import MedAgentEvaluator
from eval.generate_report import generate_markdown_report


def main() -> None:
    parser = argparse.ArgumentParser(description="Run MedAgentBench evaluation on VMEC-01")
    parser.add_argument(
        "--scenarios",
        type=str,
        default=str(PROJECT_ROOT / "eval" / "scenarios" / "medagent_cases_vi.json"),
        help="Path to scenarios JSON file",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=str(PROJECT_ROOT / "eval" / "results" / "report.md"),
        help="Path to output markdown report file",
    )
    args = parser.parse_args()

    scenarios_path = Path(args.scenarios)
    output_path = Path(args.output)

    print(f"[MedAgentBench] Loading scenarios from: {scenarios_path}")
    evaluator = MedAgentEvaluator(scenarios_path)

    print("[MedAgentBench] Executing clinical test scenarios...")
    summary = evaluator.run_all()

    print(f"[MedAgentBench] Summary: {summary.passed_cases}/{summary.total_cases} passed.")
    print(f" - Emergency Recall: {summary.emergency_recall}%")
    print(f" - Specialty Accuracy: {summary.specialty_accuracy}%")
    print(f" - Citation Compliance: {summary.citation_compliance}%")
    print(f" - Safety Compliance: {summary.safety_compliance}%")
    print(f" - Avg Latency: {summary.avg_latency_ms} ms")

    report_md = generate_markdown_report(summary)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report_md, encoding="utf-8")
    print(f"[MedAgentBench] Report saved to: {output_path}")


if __name__ == "__main__":
    main()
