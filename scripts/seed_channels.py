#!/usr/bin/env python3
"""
Seed Slack channels with mock conversation data.

This script pushes the mock conversations from fixtures/slack_mock.json
to real Slack channels for testing the digest pipeline.

Usage:
    poetry run python scripts/seed_channels.py

Requirements:
    - SLACK_BOT_TOKEN in .env
    - Channel IDs configured in .env (CHANNEL_MECHANICAL, etc.)
    - Bot must be invited to all target channels
"""

import json
import os
import time
from pathlib import Path
from datetime import datetime

from dotenv import load_dotenv
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

load_dotenv()


def load_fixtures() -> dict:
    """Load mock conversation data."""
    fixture_path = Path(__file__).parent.parent / "fixtures" / "slack_mock.json"
    with open(fixture_path) as f:
        return json.load(f)


def get_channel_mapping() -> dict:
    """Map fixture channel IDs to real channel IDs from env."""
    return {
        "C_MECHANICAL": os.getenv("CHANNEL_MECHANICAL"),
        "C_ELECTRICAL": os.getenv("CHANNEL_ELECTRICAL"),
        "C_SOFTWARE": os.getenv("CHANNEL_SOFTWARE"),
    }


def seed_channel(client: WebClient, channel_id: str, messages: list, users: dict) -> int:
    """
    Post messages to a channel.
    
    Returns the number of messages posted.
    """
    posted = 0
    
    for msg in messages:
        # Get user info for this message
        user_id = msg.get("user", "")
        user_info = users.get(user_id, {})
        user_name = user_info.get("name", "Team Member")
        
        # Format message with attribution
        text = f"*[{user_name}]*: {msg['text']}"
        
        try:
            client.chat_postMessage(
                channel=channel_id,
                text=text,
                unfurl_links=False,
                unfurl_media=False,
            )
            posted += 1
            print(f"  ✓ Posted message {posted}")
            
            # Rate limiting - Slack allows ~1 msg/sec
            time.sleep(1.2)
            
        except SlackApiError as e:
            print(f"  ✗ Error posting message: {e.response['error']}")
    
    return posted


def main():
    """Main entry point."""
    print("=" * 50)
    print("Slack Channel Seeder")
    print("=" * 50)
    
    # Validate environment
    token = os.getenv("SLACK_BOT_TOKEN")
    if not token or token == "xoxb-your-bot-token":
        print("\n❌ Error: SLACK_BOT_TOKEN not configured in .env")
        print("   Please add your bot token to .env first.")
        return
    
    # Load data
    print("\n📁 Loading fixtures...")
    data = load_fixtures()
    users = data.get("users", {})
    channels = data.get("channels", {})
    
    # Get channel mapping
    channel_map = get_channel_mapping()
    
    # Validate channels
    missing = [k for k, v in channel_map.items() if not v or v.startswith("C012345")]
    if missing:
        print(f"\n⚠️  Warning: Some channels have placeholder IDs: {missing}")
        print("   Update .env with real channel IDs from your Slack workspace.")
        proceed = input("\n   Continue anyway? (y/N): ").strip().lower()
        if proceed != 'y':
            print("   Aborted.")
            return
    
    # Initialize client
    client = WebClient(token=token)
    
    # Test connection
    try:
        auth = client.auth_test()
        print(f"\n✓ Connected as: {auth['user']} in {auth['team']}")
    except SlackApiError as e:
        print(f"\n❌ Error: Could not connect to Slack: {e.response['error']}")
        return
    
    # Seed each channel
    total_posted = 0
    
    for fixture_id, real_id in channel_map.items():
        if not real_id:
            continue
            
        channel_data = channels.get(fixture_id, {})
        channel_name = channel_data.get("name", fixture_id)
        messages = channel_data.get("messages", [])
        
        print(f"\n📤 Seeding #{channel_name} ({real_id})")
        print(f"   {len(messages)} messages to post...")
        
        # Confirm before posting
        confirm = input(f"   Post {len(messages)} messages? (y/N): ").strip().lower()
        if confirm != 'y':
            print("   Skipped.")
            continue
        
        posted = seed_channel(client, real_id, messages, users)
        total_posted += posted
        print(f"   ✓ Posted {posted} messages")
    
    print("\n" + "=" * 50)
    print(f"✅ Done! Posted {total_posted} total messages.")
    print("=" * 50)


if __name__ == "__main__":
    main()
