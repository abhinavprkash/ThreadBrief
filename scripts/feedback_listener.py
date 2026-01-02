#!/usr/bin/env python3
"""
Feedback Listener - Slack Events API webhook server for capturing emoji reactions.

This Flask-based server listens for `reaction_added` and `reaction_removed` events
from Slack and stores them as feedback on digest items.

Setup:
1. Configure Slack app with Events API subscription
2. Subscribe to `reaction_added` and `reaction_removed` events
3. Set REQUEST_URL to this server's /slack/events endpoint
4. Set SLACK_SIGNING_SECRET environment variable

Usage:
    python scripts/feedback_listener.py [--port 3000] [--debug]
"""

import os
import sys
import hmac
import hashlib
import time
import argparse
from datetime import datetime
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from flask import Flask, request, jsonify
from dotenv import load_dotenv

from daily_digest.feedback import FeedbackStore, FeedbackMetrics
from daily_digest.feedback.feedback_store import FeedbackEvent
from daily_digest.observability import logger

load_dotenv()

app = Flask(__name__)

# Initialize stores
feedback_store = FeedbackStore()
feedback_metrics = FeedbackMetrics(feedback_store)

# Slack signing secret for request verification
SIGNING_SECRET = os.getenv("SLACK_SIGNING_SECRET", "")


def verify_slack_request(request) -> bool:
    """Verify that the request came from Slack using signing secret."""
    if not SIGNING_SECRET:
        logger.warning("SLACK_SIGNING_SECRET not set, skipping verification")
        return True
    
    timestamp = request.headers.get("X-Slack-Request-Timestamp", "")
    signature = request.headers.get("X-Slack-Signature", "")
    
    # Reject old timestamps (replay attack prevention)
    if abs(time.time() - int(timestamp)) > 60 * 5:
        return False
    
    # Compute expected signature
    sig_basestring = f"v0:{timestamp}:{request.get_data(as_text=True)}"
    expected_sig = "v0=" + hmac.new(
        SIGNING_SECRET.encode(),
        sig_basestring.encode(),
        hashlib.sha256
    ).hexdigest()
    
    return hmac.compare_digest(expected_sig, signature)


@app.route("/slack/events", methods=["POST"])
def handle_slack_event():
    """Handle incoming Slack Events API requests."""
    
    # Verify request signature
    if not verify_slack_request(request):
        logger.warning("Invalid Slack request signature")
        return jsonify({"error": "Invalid signature"}), 403
    
    data = request.json
    
    # Handle URL verification challenge
    if data.get("type") == "url_verification":
        return jsonify({"challenge": data.get("challenge")})
    
    # Handle event callbacks
    if data.get("type") == "event_callback":
        event = data.get("event", {})
        event_type = event.get("type")
        
        if event_type == "reaction_added":
            handle_reaction_added(event)
        elif event_type == "reaction_removed":
            handle_reaction_removed(event)
    
    return jsonify({"ok": True})


def handle_reaction_added(event: dict):
    """
    Handle reaction_added event.
    
    Event structure:
    {
        "type": "reaction_added",
        "user": "U123ABC456",
        "reaction": "white_check_mark",
        "item_user": "U222BBB222",
        "item": {
            "type": "message",
            "channel": "C123ABC456",
            "ts": "1234567890.123456"
        },
        "event_ts": "1234567890.123456"
    }
    """
    user_id = event.get("user", "")
    reaction = event.get("reaction", "")
    item = event.get("item", {})
    channel_id = item.get("channel", "")
    message_ts = item.get("ts", "")
    
    # Map reaction to feedback type
    feedback_type = feedback_store.emoji_to_feedback_type(reaction)
    if not feedback_type:
        logger.debug(f"Ignoring unrecognized reaction: {reaction}")
        return
    
    # Look up the digest item by message_ts
    digest_item = feedback_store.get_item_by_message_ts(message_ts, channel_id)
    if not digest_item:
        logger.debug(f"No digest item found for message ts={message_ts}")
        return
    
    # Rate limiting check
    allowed, remaining = feedback_metrics.check_rate_limit(user_id)
    if not allowed:
        logger.info(f"User {user_id} rate limited, ignoring feedback")
        return
    
    # Check for duplicate feedback
    if feedback_metrics.is_user_spamming(user_id, digest_item.digest_item_id):
        logger.debug(f"User {user_id} already gave feedback on {digest_item.digest_item_id}")
        return
    
    # Store the feedback
    feedback_event = FeedbackEvent(
        digest_item_id=digest_item.digest_item_id,
        user_id=user_id,
        team=digest_item.team,
        feedback_type=feedback_type,
        created_at=datetime.now().isoformat(),
    )
    
    event_id = feedback_store.store_feedback(feedback_event)
    logger.info(
        f"Stored feedback: {feedback_type} on item {digest_item.digest_item_id} "
        f"from user {user_id} (id={event_id})"
    )


def handle_reaction_removed(event: dict):
    """
    Handle reaction_removed event.
    
    For now, we log but don't remove feedback - users changing their mind
    doesn't necessarily mean the original feedback was wrong.
    """
    user_id = event.get("user", "")
    reaction = event.get("reaction", "")
    
    feedback_type = feedback_store.emoji_to_feedback_type(reaction)
    if feedback_type:
        logger.info(f"User {user_id} removed reaction {reaction} (feedback remains)")


@app.route("/health", methods=["GET"])
def health_check():
    """Health check endpoint."""
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
    })


@app.route("/metrics", methods=["GET"])
def get_metrics():
    """Get current feedback metrics."""
    days = request.args.get("days", 7, type=int)
    team = request.args.get("team")
    
    snapshot = feedback_metrics.compute_snapshot(days=days, team=team)
    return jsonify(snapshot.to_dict())


def main():
    parser = argparse.ArgumentParser(description="Slack Events API Feedback Listener")
    parser.add_argument("--port", type=int, default=3000, help="Port to listen on")
    parser.add_argument("--debug", action="store_true", help="Enable debug mode")
    parser.add_argument("--test", action="store_true", help="Run in test mode with mock data")
    parser.add_argument("--poll", action="store_true", help="Run in polling mode (no server)")
    parser.add_argument("--poll-interval", type=int, default=300, help="Polling interval in seconds")
    parser.add_argument("--process-feedback", action="store_true", help="Process feedback and update prompts")
    
    args = parser.parse_args()
    
    if args.test:
        run_test_mode()
    elif args.poll:
        run_polling_mode(args.poll_interval)
    elif args.process_feedback:
        run_feedback_processing()
    else:
        logger.info(f"Starting feedback listener on port {args.port}")
        app.run(host="0.0.0.0", port=args.port, debug=args.debug)


def run_test_mode():
    """Run a quick test to verify the listener setup."""
    print("\n=== Feedback Listener Test Mode ===\n")
    
    # Test database connection
    print("1. Testing database connection...")
    try:
        store = FeedbackStore()
        print(f"   ✓ Database at: {store.db_path}")
    except Exception as e:
        print(f"   ✗ Database error: {e}")
        return
    
    # Test emoji mapping
    print("\n2. Testing emoji mapping...")
    test_emojis = ["white_check_mark", "x", "jigsaw", "no_bell", "random"]
    for emoji in test_emojis:
        result = store.emoji_to_feedback_type(emoji)
        print(f"   {emoji} -> {result or '(ignored)'}")
    
    # Test metrics
    print("\n3. Testing metrics...")
    metrics = FeedbackMetrics(store)
    snapshot = metrics.compute_snapshot(days=7)
    print(f"   Total items: {snapshot.total_digest_items}")
    print(f"   Total feedback: {snapshot.total_feedback_events}")
    print(f"   Accuracy ratio: {snapshot.accuracy_ratio:.1%}")
    
    print("\n=== Test Complete ===\n")
    print("To start the server, run without --test flag:")
    print("  python scripts/feedback_listener.py --port 3000")


def run_polling_mode(interval_seconds: int = 300):
    """
    Run in polling mode - periodically fetch reactions from Slack API.
    
    This is an alternative to the Events API for when a webhook server
    cannot be exposed. It polls for reactions on recent digest messages.
    
    Args:
        interval_seconds: How often to poll (default 5 minutes)
    """
    from daily_digest.slack_client import SlackClient
    
    print(f"\n=== Feedback Polling Mode ===")
    print(f"Polling interval: {interval_seconds}s")
    print(f"Press Ctrl+C to stop\n")
    
    slack = SlackClient()
    store = FeedbackStore()
    
    while True:
        try:
            poll_reactions(slack, store)
        except Exception as e:
            logger.error(f"Polling error: {e}")
        
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Sleeping for {interval_seconds}s...")
        time.sleep(interval_seconds)


def poll_reactions(slack, store: FeedbackStore):
    """
    Poll Slack for reactions on recent digest items.
    
    Fetches reactions for each stored digest item from the last 24 hours.
    """
    # Get recent items that were posted to Slack
    recent_items = store.get_recent_items(days=1)
    items_with_slack_ts = [
        item for item in recent_items 
        if item.slack_message_ts and item.slack_channel_id
    ]
    
    if not items_with_slack_ts:
        print(f"   No digest items with Slack message_ts found")
        return
    
    print(f"   Checking {len(items_with_slack_ts)} messages for reactions...")
    
    new_feedback_count = 0
    
    for item in items_with_slack_ts:
        try:
            # Get reactions for this message
            reactions = slack.get_reactions(
                channel=item.slack_channel_id,
                timestamp=item.slack_message_ts,
            )
            
            if not reactions:
                continue
            
            # Process each reaction
            for reaction in reactions:
                emoji = reaction.get("name", "")
                users = reaction.get("users", [])
                
                feedback_type = store.emoji_to_feedback_type(emoji)
                if not feedback_type:
                    continue
                
                # Store feedback for each user who reacted
                for user_id in users:
                    # Check if we already have this feedback
                    existing = store.get_feedback_for_item(item.digest_item_id)
                    already_exists = any(
                        fb.user_id == user_id and fb.feedback_type == feedback_type
                        for fb in existing
                    )
                    
                    if already_exists:
                        continue
                    
                    # Store new feedback
                    feedback_event = FeedbackEvent(
                        digest_item_id=item.digest_item_id,
                        user_id=user_id,
                        team=item.team,
                        feedback_type=feedback_type,
                        created_at=datetime.now().isoformat(),
                    )
                    store.store_feedback(feedback_event)
                    new_feedback_count += 1
                    logger.info(f"Stored reaction {emoji} -> {feedback_type} from {user_id}")
                    
        except Exception as e:
            logger.debug(f"Error getting reactions for {item.digest_item_id}: {e}")
    
    print(f"   ✓ Collected {new_feedback_count} new feedback events")


def run_feedback_processing():
    """
    Process collected feedback to improve future digests.
    
    This should be run periodically (e.g., daily) to:
    1. Apply confidence adjustments based on feedback
    2. Generate new prompt directives from patterns
    3. Expire old directives
    """
    from daily_digest.feedback import FeedbackProcessor, PromptEnhancer
    
    print("\n=== Feedback Processing ===\n")
    
    store = FeedbackStore()
    processor = FeedbackProcessor(store)
    enhancer = PromptEnhancer(store)
    
    # 1. Get recent feedback that hasn't been processed
    print("1. Processing feedback events...")
    recent_items = store.get_recent_items(days=7)
    items_to_process = [item for item in recent_items if item.confidence > 0]
    
    processed_count = 0
    for item in items_to_process:
        feedback = store.get_feedback_for_item(item.digest_item_id)
        if feedback:
            processor.apply_item_specific_feedback(item.digest_item_id)
            processed_count += 1
    
    print(f"   ✓ Processed {processed_count} items with feedback")
    
    # 2. Generate new directives
    print("\n2. Generating prompt directives...")
    teams = ["mechanical", "electrical", "software"]
    total_directives = 0
    
    for team in teams:
        new_directives = enhancer.generate_directives(team)
        if new_directives:
            directive_count = len(new_directives.split("\n"))
            total_directives += directive_count
            print(f"   ✓ {team}: {directive_count} new directives")
    
    if total_directives == 0:
        print("   (No new directives generated)")
    
    # 3. Expire old directives
    print("\n3. Expiring old directives...")
    expired = store.expire_old_directives(expiry_days=14)
    print(f"   ✓ Expired {expired} old directives")
    
    # 4. Print summary
    print("\n=== Summary ===")
    snapshot = feedback_metrics.compute_snapshot(days=7)
    print(f"Total feedback events: {snapshot.total_feedback_events}")
    print(f"Accuracy ratio: {snapshot.accuracy_ratio:.1%}")
    print(f"Wrong ratio: {snapshot.wrong_ratio:.1%}")
    
    print("\n✅ Feedback processing complete!")


if __name__ == "__main__":
    main()
