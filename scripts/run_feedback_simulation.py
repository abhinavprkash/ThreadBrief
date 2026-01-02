#!/usr/bin/env python3
"""
Run feedback simulation to demonstrate learning over time.

This script runs a multi-day simulation that demonstrates how the
personalization and ranking system improves with feedback.

Usage:
    poetry run python scripts/run_feedback_simulation.py [options]

Options:
    --days N        Number of days to simulate (default: 14)
    --items N       Items per team per day (default: 5)
    --feedback N    Feedback rate 0-1 (default: 0.4)
    --output PATH   Output JSON report path
    --use-llm       Use LLM for evaluation (default: heuristic)
    --dry-run       Run for 3 days only as a test
"""

import argparse
import sys
from pathlib import Path

# Add src to path for imports
src_path = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(src_path))

from daily_digest.simulation import FeedbackSimulator


def main():
    parser = argparse.ArgumentParser(
        description="Run feedback simulation for ThreadBrief personalization"
    )
    parser.add_argument(
        "--days", 
        type=int, 
        default=14,
        help="Number of days to simulate (default: 14)"
    )
    parser.add_argument(
        "--items",
        type=int,
        default=5,
        help="Items per team per day (default: 5)"
    )
    parser.add_argument(
        "--feedback",
        type=float,
        default=0.4,
        help="Feedback rate 0-1 (default: 0.4)"
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Output JSON report path"
    )
    parser.add_argument(
        "--use-llm",
        action="store_true",
        help="Use LLM for evaluation (default: heuristic)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run for 3 days only as a test"
    )
    
    args = parser.parse_args()
    
    # Adjust for dry run
    num_days = 3 if args.dry_run else args.days
    
    print("=" * 60)
    print("🧪 ThreadBrief Feedback Simulation")
    print("=" * 60)
    print()
    print("This simulation demonstrates how the personalization and")
    print("ranking system improves with user feedback over time.")
    print()
    print("Key metrics tracked:")
    print("  • Wrong ratio: How often items are marked as incorrect")
    print("  • Cross-team surfacing: How well cross-team items are highlighted")
    print("  • Directives: Rules learned from feedback patterns")
    print()
    
    # Initialize simulator
    simulator = FeedbackSimulator(
        use_mock_evaluation=not args.use_llm
    )
    
    # Run simulation
    report = simulator.run_simulation(
        num_days=num_days,
        items_per_team=args.items,
        feedback_rate=args.feedback,
    )
    
    # Save report
    if args.output:
        output_path = Path(args.output)
    else:
        output_dir = Path(__file__).parent.parent / "data"
        output_dir.mkdir(exist_ok=True)
        output_path = output_dir / f"simulation_report_{report.simulation_id}.json"
    
    report.save(str(output_path))
    print(f"\n📄 JSON Report saved to: {output_path}")
    
    # Save human-readable markdown digest
    markdown_path = output_path.with_suffix(".md")
    report.save_digests_markdown(str(markdown_path))
    print(f"📖 Human-readable digests saved to: {markdown_path}")
    
    # Save individual daily digests
    daily_dir = output_path.parent / f"daily_digests_{report.simulation_id}"
    saved_files = report.save_daily_digests(str(daily_dir))
    print(f"📁 Individual daily digests saved to: {daily_dir}/ ({len(saved_files)} files)")
    
    # Print detailed learning curve
    print("\n📈 Learning Curve by Day:")
    print("-" * 70)
    print(f"{'Day':<5} {'Date':<12} {'Wrong%':<8} {'Irrelev%':<9} {'Accurate%':<10} {'X-Team':<8}")
    print("-" * 70)
    
    for lp in report.learning_curve:
        print(
            f"{lp.day:<5} "
            f"{lp.date:<12} "
            f"{lp.wrong_ratio:>6.1%}  "
            f"{lp.irrelevant_ratio:>6.1%}   "
            f"{lp.accuracy_ratio:>7.1%}   "
            f"{lp.cross_team_surfacing_avg:>6.2f}"
        )
    
    print("-" * 70)
    
    # Print improvement summary
    print("\n✅ Improvement Summary:")
    if report.wrong_ratio_improvement > 0:
        print(f"  • Wrong ratio decreased by {report.wrong_ratio_improvement:.1%}")
    elif report.wrong_ratio_improvement < 0:
        print(f"  • Wrong ratio increased by {-report.wrong_ratio_improvement:.1%}")
    else:
        print(f"  • Wrong ratio unchanged")
    
    if report.cross_team_improvement > 0:
        print(f"  • Cross-team surfacing improved by {report.cross_team_improvement:.2f}")
    elif report.cross_team_improvement < 0:
        print(f"  • Cross-team surfacing decreased by {-report.cross_team_improvement:.2f}")
    else:
        print(f"  • Cross-team surfacing unchanged")
    
    print()


if __name__ == "__main__":
    main()
