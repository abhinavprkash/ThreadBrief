#!/usr/bin/env python3
"""
One-command demo script for ThreadBrief.

Runs the complete pipeline end-to-end:
1. Fetches messages (or uses mock data)
2. Analyzes teams
3. Detects dependencies
4. Generates personalized digests
5. Shows what changed due to feedback

Usage:
    # Full demo with mock data
    python scripts/demo_run.py
    
    # Demo with specific days
    python scripts/demo_run.py --days 7
    
    # Demo with real Slack (requires API key)
    python scripts/demo_run.py --real
"""

import asyncio
import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from daily_digest.config import DigestConfig, get_config
from daily_digest.slack_client import SlackClient
from daily_digest.orchestrator import DigestOrchestrator
from daily_digest.distributor import DigestDistributor
from daily_digest.feedback import FeedbackStore, FeedbackMetrics, PromptEnhancer, FeedbackProcessor


def main():
    parser = argparse.ArgumentParser(description="ThreadBrief Demo Run")
    parser.add_argument("--days", type=int, default=1, help="Days of history to process")
    parser.add_argument("--real", action="store_true", help="Use real Slack API (requires key)")
    parser.add_argument("--preview", action="store_true", help="Preview only, don't post")
    parser.add_argument("--process-feedback", action="store_true", help="Process feedback before running")
    
    args = parser.parse_args()
    
    print("\n" + "=" * 60)
    print("🧵 ThreadBrief Demo Run")
    print("=" * 60 + "\n")
    
    # Run the demo
    asyncio.run(run_demo(
        days=args.days,
        use_real=args.real,
        preview_only=args.preview,
        process_feedback=args.process_feedback,
    ))


async def run_demo(
    days: int = 1,
    use_real: bool = False,
    preview_only: bool = True,
    process_feedback: bool = True,
):
    """Run the complete ThreadBrief pipeline."""
    
    # Step 1: Process feedback (if enabled)
    if process_feedback:
        print("📊 Step 0: Processing prior feedback...")
        feedback_summary = process_prior_feedback()
        print(f"   {feedback_summary}\n")
    
    # Step 2: Initialize components
    print("🔧 Step 1: Initializing components...")
    config = get_config()
    
    # Use mock data by default
    if use_real:
        slack = SlackClient()
        print("   Using REAL Slack API\n")
    else:
        mock_path = Path(__file__).parent.parent / "data" / "mock_slack_data.json"
        if not mock_path.exists():
            # Try synthetic data
            mock_path = Path(__file__).parent.parent / "data" / "synthetic_slack_data.json"
        slack = SlackClient(mock_data_path=str(mock_path))
        print(f"   Using MOCK data: {mock_path.name}\n")
    
    orchestrator = DigestOrchestrator(config=config, mock_mode=not use_real)
    
    # Step 3: Run the pipeline
    print("🚀 Step 2: Running digest pipeline...")
    since = datetime.now() - timedelta(days=days)
    output = await orchestrator.run(slack, since=since)
    
    print(f"   ✓ Analyzed {len(output.team_analyses)} teams")
    print(f"   ✓ Found {output.global_digest.total_events} events")
    print(f"   ✓ Detected {len(output.global_digest.cross_team_highlights)} cross-team items\n")
    
    # Step 4: Show results
    print("📨 Step 3: Generating outputs...")
    
    store = FeedbackStore()
    distributor = DigestDistributor(slack, config, feedback_store=store)
    
    if preview_only:
        preview = await distributor.preview(output, output.team_analyses)
        print("\n" + "-" * 60)
        print("PREVIEW - Main Digest Header:")
        print("-" * 60)
        print(preview["header"]["text"][:500] + "..." if len(preview["header"]["text"]) > 500 else preview["header"]["text"])
        
        print("\n" + "-" * 60)
        print("PREVIEW - High Confidence Items:")
        print("-" * 60)
        for item in preview["high_confidence_items"][:5]:
            print(f"  [{item['confidence']:.0%}] {item['text'][:80]}...")
        
        print("\n" + "-" * 60)
        print("PREVIEW - Leadership DM:")
        print("-" * 60)
        print(preview["leadership_dm"][:800] + "..." if len(preview["leadership_dm"]) > 800 else preview["leadership_dm"])
    else:
        run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        result = await distributor.distribute(output, output.team_analyses, run_id=run_id)
        print(f"   ✓ Posted {len(result['item_posts'])} items to main channel")
        print(f"   ✓ Sent {len(result['dms'])} leadership DMs")
        if result["errors"]:
            print(f"   ⚠️ {len(result['errors'])} errors")
    
    # Step 5: Show feedback-based improvements
    print("\n" + "=" * 60)
    print("📈 What Changed Due to Feedback")
    print("=" * 60)
    show_feedback_impact(store)
    
    print("\n✅ Demo complete!\n")


def process_prior_feedback() -> str:
    """Process any accumulated feedback before the run."""
    try:
        store = FeedbackStore()
        processor = FeedbackProcessor(store)
        enhancer = PromptEnhancer(store)
        
        # Get recent items with feedback
        recent_items = store.get_recent_items(days=7)
        processed = 0
        
        for item in recent_items:
            feedback = store.get_feedback_for_item(item.digest_item_id)
            if feedback:
                processor.apply_item_specific_feedback(item.digest_item_id)
                processed += 1
        
        # Generate directives for each team
        teams = ["mechanical", "electrical", "software"]
        new_directives = 0
        for team in teams:
            directives = enhancer.generate_directives(team)
            if directives:
                new_directives += len(directives.split("\n"))
        
        return f"Processed {processed} items, generated {new_directives} new directives"
    except Exception as e:
        return f"Skipped (no prior feedback): {e}"


def show_feedback_impact(store: FeedbackStore):
    """Show how feedback has improved the system."""
    try:
        metrics = FeedbackMetrics(store)
        snapshot = metrics.compute_snapshot(days=7)
        
        print(f"\n📊 Last 7 Days:")
        print(f"   Items generated: {snapshot.total_digest_items}")
        print(f"   Feedback received: {snapshot.total_feedback_events}")
        print(f"   Accuracy ratio: {snapshot.accuracy_ratio:.1%}")
        
        if snapshot.wrong_ratio > 0:
            print(f"   Wrong ratio: {snapshot.wrong_ratio:.1%} (items to improve)")
        
        # Show active directives 
        try:
            enhancer = PromptEnhancer(store)
            for team in ["mechanical", "electrical", "software"]:
                instructions = enhancer.get_prompt_instructions(team=team)
                if instructions and "Based on feedback" in instructions:
                    directive_lines = [l for l in instructions.split("\n") if l.strip().startswith("-")]
                    if directive_lines:
                        print(f"\n🧠 Active Directives for {team.title()}:")
                        for line in directive_lines[:3]:
                            print(f"  {line.strip()}")
        except Exception:
            pass
    except Exception as e:
        print(f"   (No metrics available: {e})")


if __name__ == "__main__":
    main()
