#!/usr/bin/env python3
"""
Persona CLI - Set user preferences for personalized digest ranking.

This CLI allows users to configure their role, team, and custom topics
which are then used by DigestRanker to personalize their daily digest.

Usage:
    # Set a user's persona
    python scripts/set_persona.py --user U123ABC --role lead --team mechanical
    
    # Set with custom topics
    python scripts/set_persona.py --user U123ABC --topics "power,firmware,testing"
    
    # View a user's current persona
    python scripts/set_persona.py --user U123ABC --view
    
    # List all configured personas
    python scripts/set_persona.py --list
"""

import argparse
import sys
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from daily_digest.feedback import FeedbackStore
from daily_digest.personalization import PersonaManager, get_role_persona, get_team_persona


def main():
    parser = argparse.ArgumentParser(
        description="Set user preferences for personalized digest ranking"
    )
    parser.add_argument("--user", type=str, help="Slack user ID (e.g., U123ABC)")
    parser.add_argument(
        "--role", 
        type=str, 
        choices=["lead", "ic"],
        help="User role: 'lead' for managers/leads, 'ic' for individual contributors"
    )
    parser.add_argument(
        "--team", 
        type=str,
        choices=["mechanical", "electrical", "software", "general"],
        help="Primary team for topic relevance"
    )
    parser.add_argument(
        "--topics", 
        type=str,
        help="Comma-separated custom topics (e.g., 'power,firmware,testing')"
    )
    parser.add_argument(
        "--boosts",
        type=str,
        help="Comma-separated boosts as key=value (e.g., 'blocker=0.3,cross_team=0.2')"
    )
    parser.add_argument("--view", action="store_true", help="View current persona for user")
    parser.add_argument("--list", action="store_true", help="List all configured personas")
    
    args = parser.parse_args()
    
    # Initialize stores
    store = FeedbackStore()
    persona_mgr = PersonaManager(store)
    
    # Handle --list
    if args.list:
        list_all_personas(store)
        return
    
    # Require --user for other operations
    if not args.user:
        parser.error("--user is required (except with --list)")
    
    # Handle --view
    if args.view:
        view_persona(store, persona_mgr, args.user)
        return
    
    # Handle set operations
    if not any([args.role, args.team, args.topics, args.boosts]):
        parser.error("At least one of --role, --team, --topics, or --boosts is required")
    
    set_persona(store, args.user, args.role, args.team, args.topics, args.boosts)


def view_persona(store: FeedbackStore, persona_mgr: PersonaManager, user_id: str):
    """Display the current persona configuration for a user."""
    print(f"\n=== Persona for {user_id} ===\n")
    
    # Get raw config
    config = store.get_user_persona(user_id)
    if not config:
        print("No persona configured for this user.")
        print("\nUsing defaults:")
        print("  Role: ic (individual contributor)")
        print("  Team: general")
        print("  Topics: (none)")
        print("\nSet a persona with:")
        print(f"  python scripts/set_persona.py --user {user_id} --role lead --team mechanical")
        return
    
    print(f"Role: {config.get('role', 'ic')}")
    print(f"Team: {config.get('team', 'general')}")
    
    topics = config.get("custom_topics", [])
    if topics:
        print(f"Custom Topics: {', '.join(topics)}")
    
    boosts = config.get("custom_boosts", {})
    if boosts:
        print("Custom Boosts:")
        for k, v in boosts.items():
            print(f"  {k}: +{v}")
    
    # Show combined persona
    combined = persona_mgr.get_combined_persona(user_id)
    if combined:
        print(f"\nEffective Priorities: {', '.join(combined.priorities[:5])}")
        print(f"Effective Interests: {', '.join(combined.interests[:5])}")


def set_persona(
    store: FeedbackStore, 
    user_id: str, 
    role: str = None,
    team: str = None,
    topics_str: str = None,
    boosts_str: str = None,
):
    """Set or update a user's persona configuration."""
    # Get existing config
    existing = store.get_user_persona(user_id) or {}
    
    # Update with new values
    if role:
        existing["role"] = role
    if team:
        existing["team"] = team
    if topics_str:
        existing["custom_topics"] = [t.strip() for t in topics_str.split(",")]
    if boosts_str:
        boosts = {}
        for item in boosts_str.split(","):
            if "=" in item:
                key, val = item.split("=", 1)
                try:
                    boosts[key.strip()] = float(val.strip())
                except ValueError:
                    print(f"Warning: Invalid boost value '{val}' for '{key}'")
        if boosts:
            existing["custom_boosts"] = boosts
    
    # Save
    store.set_user_persona(user_id, existing)
    
    print(f"\n✅ Persona updated for {user_id}")
    print(f"   Role: {existing.get('role', 'ic')}")
    print(f"   Team: {existing.get('team', 'general')}")
    if existing.get("custom_topics"):
        print(f"   Topics: {', '.join(existing['custom_topics'])}")
    if existing.get("custom_boosts"):
        print(f"   Boosts: {existing['custom_boosts']}")
    
    # Show what this means
    role_p = get_role_persona(existing.get("role", "ic"))
    team_p = get_team_persona(existing.get("team", "general"))
    print(f"\nThis user will now see:")
    print(f"  - {role_p.name} priorities: {', '.join(role_p.priorities[:3])}")
    print(f"  - {team_p.name} topics: {', '.join(team_p.interests[:3])}")


def list_all_personas(store: FeedbackStore):
    """List all users with configured personas."""
    print("\n=== Configured Personas ===\n")
    
    # Query the database directly
    try:
        import sqlite3
        conn = sqlite3.connect(store.db_path)
        cursor = conn.execute("SELECT user_id, config FROM user_personas")
        rows = cursor.fetchall()
        conn.close()
        
        if not rows:
            print("No personas configured yet.")
            print("\nSet a persona with:")
            print("  python scripts/set_persona.py --user U123ABC --role lead --team mechanical")
            return
        
        print(f"{'User ID':<15} {'Role':<8} {'Team':<12} {'Topics'}")
        print("-" * 60)
        
        import json
        for user_id, config_json in rows:
            config = json.loads(config_json) if config_json else {}
            role = config.get("role", "ic")
            team = config.get("team", "general")
            topics = config.get("custom_topics", [])
            topics_str = ", ".join(topics[:3]) if topics else "-"
            print(f"{user_id:<15} {role:<8} {team:<12} {topics_str}")
        
        print(f"\nTotal: {len(rows)} configured persona(s)")
        
    except Exception as e:
        print(f"Error reading personas: {e}")


if __name__ == "__main__":
    main()
