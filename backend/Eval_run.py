"""
Eval_run.py — Development only

Evaluates Whispr's text refinement quality using real transcription history.
Uses the connectonion eval plugin to judge raw → refined pairs.

Usage:
    python Eval_run.py              # evaluate last 20 transcriptions
    python Eval_run.py --limit 10   # evaluate last N transcriptions
    python Eval_run.py --save       # save results to eval_results.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

# Force UTF-8 on Windows to avoid gbk codec errors
os.environ["PYTHONUTF8"] = "1"
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

from connectonion import Agent
from connectonion.useful_plugins import eval, re_act

from app import load_history

REFINE_EXPECTED = (
    "The output should have all disfluencies, stutters, false starts, and repeated words removed. "
    "The core meaning of the original input must be fully preserved — no facts added or removed. "
    "The tone and formality should be appropriate for the active application context. "
    "The output should be grammatically correct and readable."
)


# =========================================================
# Scoring
# =========================================================

def score_evaluation(evaluation: Any) -> Tuple[bool, int, str]:
    """Parse eval plugin output into (passed, score, reason). Score is 0-100."""
    text = str(evaluation).strip().lower()

    passed = any(kw in text for kw in [
        "✓", "success", "completed successfully", "passed", "correct",
        "well done", "good", "appropriate", "preserved", "removed",
    ])
    failed = any(kw in text for kw in [
        "✗", "failed", "incorrect", "not completed", "missing", "error",
        "wrong", "meaning changed", "facts added",
    ])
    if failed:
        passed = False

    score = 50
    if passed:                                                    score += 30
    if "meaning preserved" in text or "meaning unchanged" in text: score += 10
    if "tone appropriate" in text or "appropriate tone" in text:   score += 5
    if "disfluencies removed" in text or "stutters removed" in text: score += 5
    if failed:                                                    score -= 40
    if "meaning changed" in text or "facts added" in text:       score -= 20

    return passed, max(0, min(100, score)), str(evaluation).strip()


# =========================================================
# Eval runner
# =========================================================

def run_refinement_eval(
    items: List[Dict[str, Any]], verbose: bool = True
) -> List[Dict[str, Any]]:
    results = []

    for i, item in enumerate(items):
        raw      = str(item.get("raw_text",   "")).strip()
        final    = str(item.get("final_text", "")).strip()
        app_name = str(item.get("app_name",   "")).strip()

        if not raw or not final:
            continue

        if verbose:
            print(f"\n[{i+1}/{len(items)}] App: {app_name or 'unknown'}")
            print(f"  RAW:     {raw}")
            print(f"  REFINED: {final}")

        agent = Agent(
            model="gpt-5",
            name="whispr_eval",
            plugins=[re_act, eval],
            system_prompt=(
                "You are an evaluator for Whispr's text refinement agent. "
                "Judge whether the refinement was done correctly. "
                "Be explicit about pass or fail and why."
            ),
        )
        agent.input(
            f"Active application: {app_name or 'unknown'}\n\n"
            f"Raw spoken input:\n{raw}\n\n"
            f"Refined output:\n{final}\n\n"
            f"Expected behaviour:\n{REFINE_EXPECTED}"
        )

        evaluation = (
            agent.current_session.get("evaluation", "no evaluation returned")
            if agent.current_session else "no session"
        )
        passed, score, reason = score_evaluation(evaluation)

        if verbose:
            print(f"  RESULT:  {'✓ PASS' if passed else '✗ FAIL'} — score: {score}/100")
            print(f"  REASON:  {reason[:120]}")

        results.append({
            "index":      i + 1,
            "app_name":   app_name,
            "raw_text":   raw,
            "final_text": final,
            "passed":     passed,
            "score":      score,
            "reason":     reason,
        })

    return results


def print_summary(results: List[Dict[str, Any]]) -> None:
    total = len(results)
    if not total:
        print("No results to summarise.")
        return

    passed    = sum(1 for r in results if r["passed"])
    avg_score = sum(r["score"] for r in results) / total

    print("\n" + "=" * 60)
    print(f"EVAL SUMMARY — {total} pairs evaluated")
    print("=" * 60)
    print(f"  Passed:    {passed}/{total} ({passed/total*100:.1f}%)")
    print(f"  Avg Score: {avg_score:.1f}/100")
    print("-" * 60)
    for r in results:
        status = "✓" if r["passed"] else "✗"
        print(f"  {status} [{r['index']:02d}] {(r['app_name'] or 'unknown'):<20} score: {r['score']:3d}/100")
    print("=" * 60)


def save_results(results: List[Dict[str, Any]], path: str = "eval_results.json") -> None:
    total     = len(results)
    passed    = sum(1 for r in results if r["passed"])
    avg_score = sum(r["score"] for r in results) / total if total else 0

    out = Path(path)
    out.write_text(json.dumps({
        "summary": {
            "total":        total,
            "passed":       passed,
            "failed":       total - passed,
            "pass_rate_pct": round(passed / total * 100, 1) if total else 0,
            "avg_score":    round(avg_score, 1),
        },
        "results": results,
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nResults saved to {out.resolve()}")


# =========================================================
# Entry point
# =========================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Whispr eval runner")
    parser.add_argument("--limit",  type=int, default=20, help="Recent items to evaluate")
    parser.add_argument("--save",   action="store_true",  help="Save results to eval_results.json")
    parser.add_argument("--quiet",  action="store_true",  help="Summary only")
    args = parser.parse_args()

    history = load_history()
    items   = history.get("items", [])

    if not items:
        print("No transcription history found.")
        sys.exit(0)

    valid_items = [
        item for item in items
        if str(item.get("raw_text", "")).strip() and str(item.get("final_text", "")).strip()
    ][-args.limit:]

    print(f"Running eval on {len(valid_items)} pairs ({len(items)} total in history)\n")
    results = run_refinement_eval(valid_items, verbose=not args.quiet)
    print_summary(results)

    if args.save:
        save_results(results)