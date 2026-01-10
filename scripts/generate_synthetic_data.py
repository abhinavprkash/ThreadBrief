#!/usr/bin/env python3
"""
Generate synthetic Slack conversation data for testing ThreadBrief.

This script generates realistic multi-day Slack conversations with:
- Multiple personas with distinct communication styles
- Conversation patterns (standups, bug reports, blockers, casual)
- Thread replies and emoji reactions
- Cross-team dependencies and blockers spanning multiple days
- Story arcs that evolve day by day (blockers → discussions → resolutions)

Usage:
    poetry run python scripts/generate_synthetic_data.py [--days N] [--channels N] [--output PATH]

Requirements:
    - GOOGLE_API_KEY and CHAT_MODEL in .env
"""

import json
import os
import random
import argparse
import time
from datetime import datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv
from google import genai

load_dotenv()

# Rate limiting configuration
REQUEST_DELAY = 5.0  # Seconds between requests
MAX_RETRIES = 3
RETRY_DELAY = 15.0  # Seconds to wait on rate limit

# =============================================================================
# PERSONAS - 12 personas across 3 teams matching existing fixture users
# =============================================================================

PERSONAS = {
    # Mechanical Team (4)
    "U_ALEX": {
        "id": "U_ALEX",
        "name": "Alex Thompson",
        "team": "mechanical",
        "role": "Senior Mechanical Engineer",
        "style": "Technical, focuses on FEA/CAD, precise with tolerances and specifications",
        "concerns": ["motor mounts", "chassis design", "stress analysis", "prototypes"],
        "typical_phrases": ["running FEA simulation", "tolerances within spec", "need to check stress requirements"]
    },
    "U_MARIA": {
        "id": "U_MARIA",
        "name": "Maria Rodriguez",
        "team": "mechanical",
        "role": "Mechanical Lead",
        "style": "Decision maker, risk-aware, delegates clearly, summarizes at EOD",
        "concerns": ["timeline", "risk flags", "resource allocation", "cross-team dependencies"],
        "typical_phrases": ["Decision:", "Risk flag:", "End of day summary:", "Let's wait until"]
    },
    "U_JAMES": {
        "id": "U_JAMES",
        "name": "James Wilson",
        "team": "mechanical",
        "role": "Manufacturing Engineer",
        "style": "Practical, focuses on inventory, CNC operations, and supplier relations",
        "concerns": ["stock levels", "lead times", "CNC machine status", "external fabrication"],
        "typical_phrases": ["running low on", "lead time is", "maintenance says", "I'll follow up with"]
    },
    "U_SARAH": {
        "id": "U_SARAH",
        "name": "Sarah Chen",
        "team": "mechanical",
        "role": "Mechanical Engineer",
        "style": "Cross-team coordinator, good with external communications",
        "concerns": ["supplier meetings", "scheduling", "BOM updates", "cross-team specs"],
        "typical_phrases": ["Just got back from", "FYI:", "please update the BOM", "electrical team needs"]
    },
    
    # Electrical Team (4)
    "U_KEVIN": {
        "id": "U_KEVIN",
        "name": "Kevin Park",
        "team": "electrical",
        "role": "Electrical Lead",
        "style": "PCB design focused, structured decision maker, coordinates with mechanical",
        "concerns": ["PCB revisions", "component placement", "layout decisions", "demo prep"],
        "typical_phrases": ["PCB Rev", "Decision:", "Option A:", "Option B:", "let's finalize"]
    },
    "U_LISA": {
        "id": "U_LISA",
        "name": "Lisa Zhang",
        "team": "electrical",
        "role": "Power Systems Engineer",
        "style": "Testing focused, firmware integration, identifies thermal issues",
        "concerns": ["power supply", "thermal shutdown", "firmware", "stress tests"],
        "typical_phrases": ["I'll run the full stress test", "thermal shutting down", "blocked on firmware"]
    },
    "U_TOM": {
        "id": "U_TOM",
        "name": "Tom Baker",
        "team": "electrical",
        "role": "Hardware Engineer",
        "style": "Runs simulations, handles thermal analysis, practical solutions",
        "concerns": ["thermal simulations", "heatsinks", "via count", "layout work"],
        "typical_phrases": ["I ran thermal simulations", "heatsink test complete", "I'll start the layout"]
    },
    "U_PRIYA": {
        "id": "U_PRIYA",
        "name": "Priya Patel",
        "team": "electrical",
        "role": "QA Engineer",
        "style": "Detail-oriented, finds edge cases, thorough validation",
        "concerns": ["test coverage", "edge cases", "regression", "validation"],
        "typical_phrases": ["found an issue", "edge case:", "tested on", "steps to reproduce"]
    },
    
    # Software Team (4)
    "U_RYAN": {
        "id": "U_RYAN",
        "name": "Ryan O'Brien",
        "team": "software",
        "role": "Software Lead",
        "style": "Deployments, architecture decisions, sets priorities",
        "concerns": ["deployments", "releases", "staging", "production", "priorities"],
        "typical_phrases": ["Deployed to staging", "Priority order:", "Everyone aligned?", "go for production"]
    },
    "U_AMANDA": {
        "id": "U_AMANDA",
        "name": "Amanda Foster",
        "team": "software",
        "role": "Senior Developer",
        "style": "Code review, monitoring, catches issues early",
        "concerns": ["memory usage", "code review", "monitoring", "race conditions"],
        "typical_phrases": ["Reviewing now", "Good catch", "Found a potential", "Memory looks stable"]
    },
    "U_CHEN": {
        "id": "U_CHEN",
        "name": "Chen Wei",
        "team": "software",
        "role": "Backend Developer",
        "style": "PRs, bug fixes, quick turnaround on issues",
        "concerns": ["PRs", "cache", "bug fixes", "cross-team integration"],
        "typical_phrases": ["PR is up:", "Found the issue", "Fix looks good", "I can pick that up"]
    },
    "U_DAVID": {
        "id": "U_DAVID",
        "name": "David Kim",
        "team": "software",
        "role": "Mobile Developer",
        "style": "API integration, latency concerns, mobile app focus",
        "concerns": ["API latency", "mobile app", "response times", "metrics"],
        "typical_phrases": ["mobile app team", "P99 latencies", "Question:", "LGTM"]
    },
}

# Additional personas for new teams
PERSONAS.update({
    # Product Team
    "U_JESSICA": {
        "id": "U_JESSICA",
        "name": "Jessica Wu",
        "team": "product",
        "role": "Product Manager",
        "style": "Customer focused, roadmap planning, coordinates across teams",
        "concerns": ["user feedback", "feature priority", "deadlines", "cross-team alignment"],
        "typical_phrases": ["customer feedback shows", "let's prioritize", "shipping this feature", "roadmap update"]
    },
    "U_MARK": {
        "id": "U_MARK",
        "name": "Mark Peterson",
        "team": "product",
        "role": "Product Designer",
        "style": "UX focused, prototypes, user research",
        "concerns": ["user experience", "design consistency", "prototypes", "accessibility"],
        "typical_phrases": ["design prototype ready", "user testing showed", "accessibility concern", "visual polish"]
    },
    # QA Team
    "U_OLIVIA": {
        "id": "U_OLIVIA",
        "name": "Olivia Chen",
        "team": "qa",
        "role": "QA Lead",
        "style": "Test strategy, automation, quality metrics",
        "concerns": ["test coverage", "regression testing", "quality metrics", "release readiness"],
        "typical_phrases": ["test coverage at", "found regression in", "automation suite", "ready for release"]
    },
    "U_PETER": {
        "id": "U_PETER",
        "name": "Peter Schmidt",
        "team": "qa",
        "role": "QA Engineer",
        "style": "Manual testing, detailed bug reports, exploratory testing",
        "concerns": ["edge cases", "bug reports", "test scenarios", "environment issues"],
        "typical_phrases": ["steps to reproduce", "found edge case", "tested on staging", "environment issue"]
    },
})

# Channel configurations
CHANNELS = {
    "C_MECHANICAL": {
        "name": "mechanical-team",
        "personas": ["U_ALEX", "U_MARIA", "U_JAMES", "U_SARAH"],
    },
    "C_ELECTRICAL": {
        "name": "electrical-team",
        "personas": ["U_KEVIN", "U_LISA", "U_TOM", "U_PRIYA"],
    },
    "C_SOFTWARE": {
        "name": "software-team",
        "personas": ["U_RYAN", "U_AMANDA", "U_CHEN", "U_DAVID"],
    },
    "C_PRODUCT": {
        "name": "product-team",
        "personas": ["U_JESSICA", "U_MARK"],
    },
    "C_QA": {
        "name": "qa-team",
        "personas": ["U_OLIVIA", "U_PETER"],
    },
}

# Common emoji reactions
EMOJI_REACTIONS = [
    "thumbsup", "eyes", "rocket", "fire", "100", "white_check_mark",
    "thinking_face", "pray", "raised_hands", "+1", "clap", "tada"
]


# =============================================================================
# STORY ARCS - Multi-day scenarios with cross-team dependencies
# =============================================================================

STORY_ARCS = [
    {
        "name": "Motor Mount Redesign",
        "description": "Mechanical discovers stress issues requiring redesign, blocks electrical PCB work",
        "duration_days": 6,
        "teams_involved": ["mechanical", "electrical"],
        "timeline": [
            {"day": 1, "team": "mechanical", "event": "FEA analysis shows stress concentration in motor mount exceeding safety margin", "blocker": False},
            {"day": 2, "team": "mechanical", "event": "Team decides redesign is needed, estimates 2-3 days", "blocker": False},
            {"day": 2, "team": "electrical", "event": "Hears about redesign, concerned about PCB layout timeline", "blocker": True, "blocked_by": "mechanical"},
            {"day": 3, "team": "mechanical", "event": "CAD license issue delays redesign work", "blocker": True, "blocked_by": "external"},
            {"day": 3, "team": "electrical", "event": "Cannot finalize PCB layout without final mount dimensions", "blocker": True, "blocked_by": "mechanical"},
            {"day": 4, "team": "mechanical", "event": "License resolved, new design complete, sharing dimensions", "blocker": False},
            {"day": 4, "team": "electrical", "event": "Reviews new dimensions, finds clearance issue with capacitors", "blocker": False},
            {"day": 5, "team": "mechanical", "event": "Adjusts design by 2mm to fix clearance, re-running simulations", "blocker": False},
            {"day": 5, "team": "electrical", "event": "Confirms 2mm shift works, updating PCB layout", "blocker": False},
            {"day": 6, "team": "mechanical", "event": "Prototype ordered, 3-day lead time", "blocker": False},
            {"day": 6, "team": "electrical", "event": "PCB layout complete and sent for review", "blocker": False},
        ]
    },
    {
        "name": "API Migration",
        "description": "Software proposes new API, requires firmware and QA updates",
        "duration_days": 8,
        "teams_involved": ["software", "electrical", "qa"],
        "timeline": [
            {"day": 1, "team": "software", "event": "Proposes new telemetry API for performance improvements", "blocker": False},
            {"day": 2, "team": "software", "event": "Draft API spec shared for review", "blocker": False},
            {"day": 2, "team": "electrical", "event": "Reviews API spec, looks good overall", "blocker": False},
            {"day": 3, "team": "software", "event": "Implements new API in backend", "blocker": False},
            {"day": 3, "team": "electrical", "event": "Starts firmware updates to match new API", "blocker": False},
            {"day": 4, "team": "software", "event": "Backend deployed to staging", "blocker": False},
            {"day": 4, "team": "electrical", "event": "Firmware update blocked - test hardware in use by mechanical", "blocker": True, "blocked_by": "mechanical"},
            {"day": 5, "team": "electrical", "event": "Still waiting for test hardware", "blocker": True, "blocked_by": "mechanical"},
            {"day": 6, "team": "electrical", "event": "Hardware available, firmware updated and testing", "blocker": False},
            {"day": 6, "team": "qa", "event": "Need to update test suite for new API", "blocker": False},
            {"day": 7, "team": "electrical", "event": "Found edge case in error handling", "blocker": False},
            {"day": 7, "team": "software", "event": "Deploying fix for edge case", "blocker": False},
            {"day": 7, "team": "qa", "event": "Test suite updated, running full regression", "blocker": False},
            {"day": 8, "team": "software", "event": "All systems stable, ready for production", "blocker": False},
            {"day": 8, "team": "electrical", "event": "Firmware validated and ready", "blocker": False},
            {"day": 8, "team": "qa", "event": "All tests passing, approved for release", "blocker": False},
        ]
    },
    {
        "name": "Thermal Issue",
        "description": "Power board overheating requires coordinated hardware and software solution",
        "duration_days": 5,
        "teams_involved": ["electrical", "mechanical", "software"],
        "timeline": [
            {"day": 1, "team": "electrical", "event": "Power board hitting 85°C during stress tests, above spec", "blocker": False},
            {"day": 2, "team": "electrical", "event": "Thermal simulations confirm problem, need both hardware and software fixes", "blocker": False},
            {"day": 2, "team": "mechanical", "event": "Can design heatsink solution, needs 1 day", "blocker": False},
            {"day": 2, "team": "software", "event": "Can implement power throttling in firmware", "blocker": False},
            {"day": 3, "team": "mechanical", "event": "Heatsink designed, ordering prototype", "blocker": False},
            {"day": 3, "team": "software", "event": "Power throttling implemented and testing", "blocker": False},
            {"day": 4, "team": "software", "event": "Throttling helps but not enough alone", "blocker": False},
            {"day": 4, "team": "mechanical", "event": "Heatsink prototype arrives tomorrow", "blocker": False},
            {"day": 5, "team": "electrical", "event": "Testing heatsink + firmware together, temps at 72°C - success!", "blocker": False},
            {"day": 5, "team": "mechanical", "event": "Ordering bulk heatsinks", "blocker": False},
        ]
    },
    {
        "name": "Feature Delay",
        "description": "Product feature delayed due to integration test failures",
        "duration_days": 10,
        "teams_involved": ["product", "software", "qa", "electrical"],
        "timeline": [
            {"day": 1, "team": "product", "event": "Demo scheduled for day 10, feature must ship", "blocker": False},
            {"day": 2, "team": "qa", "event": "Integration tests showing intermittent failures", "blocker": False},
            {"day": 3, "team": "qa", "event": "Failures seem hardware-related, escalating", "blocker": False},
            {"day": 3, "team": "software", "event": "Added detailed logging to diagnose issue", "blocker": False},
            {"day": 4, "team": "electrical", "event": "Found race condition in sensor polling", "blocker": False},
            {"day": 5, "team": "electrical", "event": "Firmware fix deployed", "blocker": False},
            {"day": 5, "team": "qa", "event": "Still seeing failures, different pattern", "blocker": False},
            {"day": 6, "team": "electrical", "event": "New issue - voltage drops during high load", "blocker": False},
            {"day": 6, "team": "mechanical", "event": "Power supply may be insufficient, ordering upgrade", "blocker": False},
            {"day": 7, "team": "product", "event": "Demo at risk, discussing backup plan", "blocker": False},
            {"day": 8, "team": "mechanical", "event": "New power supply delayed 1 day", "blocker": True, "blocked_by": "external"},
            {"day": 8, "team": "product", "event": "Communicating delay to stakeholders", "blocker": False},
            {"day": 9, "team": "mechanical", "event": "Power supply arrived and installed", "blocker": False},
            {"day": 9, "team": "qa", "event": "Running full test suite", "blocker": False},
            {"day": 10, "team": "qa", "event": "All tests passing!", "blocker": False},
            {"day": 10, "team": "product", "event": "Demo ready to proceed", "blocker": False},
        ]
    },
]


def get_llm():
    """Initialize Gemini client."""
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise ValueError("GOOGLE_API_KEY not found in environment")
    
    print(f"\n🤖 Initializing Gemini client...")
    return genai.Client(api_key=api_key)


def generate_conversation_with_ai(
    llm,
    channel_name: str,
    date: datetime,
    day_number: int,
    num_messages: int,
    personas_involved: list[str],
    context: str = "",
    story_events: list[dict] = None
) -> list[dict]:
    """Use LLM to generate realistic Slack conversation with story arc awareness."""
    
    persona_descriptions = "\n".join([
        f"- {pid}: {PERSONAS[pid]['name']} ({PERSONAS[pid]['role']}) - {PERSONAS[pid]['style']}. "
        f"Typical phrases: {', '.join(PERSONAS[pid]['typical_phrases'][:3])}"
        for pid in personas_involved
    ])
    
    # Build story context
    story_context = ""
    if story_events:
        story_context = "\n\nIMPORTANT STORY EVENTS HAPPENING TODAY:\n"
        for event in story_events:
            blocker_text = " [BLOCKER - mention dependency on other team]" if event.get("blocker") else ""
            blocked_by = f" (blocked by {event.get('blocked_by')})" if event.get("blocked_by") else ""
            story_context += f"- {event['event']}{blocker_text}{blocked_by}\n"
        story_context += "\nMake sure conversations naturally discuss these events."
    
    prompt = f"""Generate a realistic Slack conversation for #{channel_name} channel on Day {day_number} ({date.strftime('%Y-%m-%d')}).

Personas involved:
{persona_descriptions}

Requirements:
- Generate exactly {num_messages} messages
- Include realistic timestamps throughout the work day (9am-6pm)
- Mix message types: standup updates (30%), questions/discussions (25%), blockers (20%), bug reports (15%), casual chat (10%)
- About 30% of messages should be thread replies (indicated by non-null "thread_ts")
- About 20% of messages should have emoji reactions
- Make conversations feel authentic with natural back-and-forth
- Include occasional typos or informal language
- {context}{story_context}

Return ONLY a valid JSON array where each message has:
{{
  "user": "U_USERID",
  "text": "message content",
  "timestamp": "HH:MM",
  "thread_ts": "parent_timestamp if this is a reply, else null",
  "reactions": ["emoji1", "emoji2"]
}}

Example patterns to include:
- Morning standup updates with yesterday/today/blockers format
- Bug reports with steps to reproduce
- Questions that spark multi-message discussions
- Blockers mentioning cross-team dependencies (e.g., "@Kevin we're blocked on the motor mount dimensions from mechanical")
- Code/design review requests
- End-of-day summaries from leads
- Brief casual exchanges (lunch, coffee, weekend plans)

Generate realistic, varied content - avoid generic placeholder text."""

    # Retry logic for rate limits
    for attempt in range(MAX_RETRIES):
        try:
            response = llm.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt
            )
            content = response.text
            
            # Extract JSON from response
            start = content.find('[')
            end = content.rfind(']') + 1
            
            if start != -1 and end > start:
                json_str = content[start:end]
                messages = json.loads(json_str)
            
            # Process and add full timestamps
            base_ts = int(date.replace(hour=9, minute=0, second=0).timestamp())
            processed_messages = []
            ts_map = {}  # Map HH:MM to actual timestamp for thread references
            
            for i, msg in enumerate(messages):
                # Parse time
                try:
                    time_parts = msg['timestamp'].split(':')
                    hour = int(time_parts[0])
                    minute = int(time_parts[1]) if len(time_parts) > 1 else 0
                except (ValueError, IndexError):
                    hour = 9 + (i * 10 // 60)
                    minute = (i * 10) % 60
                
                # Create unique timestamp
                msg_ts = base_ts + (hour - 9) * 3600 + minute * 60 + i
                ts_str = f"{msg_ts}.{i:06d}"
                ts_map[msg['timestamp']] = ts_str
                
                # Handle thread_ts
                thread_ts = None
                if msg.get('thread_ts') and msg['thread_ts'] in ts_map:
                    thread_ts = ts_map[msg['thread_ts']]
                
                # Filter valid reactions
                reactions = [r for r in msg.get('reactions', []) if isinstance(r, str)]
                
                processed_messages.append({
                    "ts": ts_str,
                    "user": msg['user'],
                    "text": msg['text'],
                    "thread_ts": thread_ts,
                    "reactions": reactions[:3]  # Limit to 3 reactions
                })
            
            # Add delay between requests to avoid rate limits
            time.sleep(REQUEST_DELAY)
            return processed_messages
            
        except Exception as e:
            if "429" in str(e) or "TooManyRequests" in str(e) or "Resource has been exhausted" in str(e):
                if attempt < MAX_RETRIES - 1:
                    wait_time = RETRY_DELAY * (attempt + 1)
                    print(f"  ⚠️  Rate limit hit, waiting {wait_time}s before retry {attempt + 2}/{MAX_RETRIES}...")
                    time.sleep(wait_time)
                    continue
                else:
                    print(f"  ❌ Rate limit exceeded after {MAX_RETRIES} attempts")
                    return []
            else:
                print(f"  ⚠️  Error generating conversation: {e}")
                return []
    
    return []


def add_cross_channel_blockers(dataset: dict, dates: list[str]) -> dict:
    """Add realistic cross-team dependencies and blockers."""
    
    blocker_scenarios = [
        {
            "day_index": 1,
            "source_channel": "C_MECHANICAL",
            "source_user": "U_SARAH",
            "message": "FYI: The electrical team mentioned they need the motor mount dimensions by Friday for PCB layout. <@U_KEVIN> - can we sync on this?",
            "hour": 14, "minute": 30
        },
        {
            "day_index": 2,
            "source_channel": "C_ELECTRICAL",
            "source_user": "U_LISA",
            "message": "I'm blocked on the firmware update. <@U_RYAN> in software was supposed to send the new motor control algorithm yesterday but I haven't received it yet.",
            "hour": 11, "minute": 15
        },
        {
            "day_index": 2,
            "source_channel": "C_SOFTWARE",
            "source_user": "U_CHEN",
            "message": "BTW Lisa from electrical is waiting on the motor control algorithm. I sent it yesterday but she says she didn't receive it. Resending now.",
            "hour": 11, "minute": 45
        },
        {
            "day_index": 3,
            "source_channel": "C_SOFTWARE",
            "source_user": "U_DAVID",
            "message": "Heads up: Found a dependency issue - the API changes we're making might affect the firmware interface. <@U_LISA> can you validate the new endpoints work with your integration tests?",
            "hour": 15, "minute": 0
        },
    ]
    
    for scenario in blocker_scenarios:
        if scenario['day_index'] < len(dates):
            date_key = dates[scenario['day_index']]
            channel = scenario['source_channel']
            
            if date_key in dataset and channel in dataset[date_key]:
                # Create timestamp
                base_date = datetime.strptime(date_key, '%Y-%m-%d')
                msg_ts = base_date.replace(
                    hour=scenario['hour'],
                    minute=scenario['minute']
                ).timestamp()
                
                blocker_msg = {
                    "ts": f"{int(msg_ts)}.999999",
                    "user": scenario['source_user'],
                    "text": scenario['message'],
                    "thread_ts": None,
                    "reactions": random.sample(EMOJI_REACTIONS, k=random.randint(0, 2))
                }
                
                dataset[date_key][channel].append(blocker_msg)
                # Sort by timestamp
                dataset[date_key][channel].sort(key=lambda x: x['ts'])
    
    return dataset


def generate_multi_day_dataset(days: int = 10, num_channels: int = 5) -> dict:
    """Generate a multi-day conversation dataset with story arcs."""
    
    print(f"\n🤖 Initializing LLM (model: {os.getenv('CHAT_MODEL', 'models/gemini-1.0-pro')})...")
    llm = get_llm()
    
    # Calculate dates (going back from today)
    start_date = datetime.now() - timedelta(days=days - 1)
    dates = [(start_date + timedelta(days=i)).strftime('%Y-%m-%d') for i in range(days)]
    
    # Select channels based on num_channels
    all_channels = list(CHANNELS.items())
    selected_channels = dict(all_channels[:num_channels])
    
    dataset = {"channels": {}, "users": {}, "metadata": {}}
    
    # Add metadata
    dataset["metadata"] = {
        "generated_at": datetime.now().isoformat(),
        "start_date": dates[0],
        "end_date": dates[-1],
        "num_days": days,
        "story_arcs": [arc["name"] for arc in STORY_ARCS]
    }
    
    # Add users from personas
    for pid, persona in PERSONAS.items():
        dataset["users"][pid] = {
            "name": persona["name"],
            "team": persona["team"]
        }
    
    # Initialize channels
    for channel_id, channel_info in selected_channels.items():
        dataset["channels"][channel_id] = {
            "name": channel_info["name"],
            "messages": []
        }
    
    # Determine which story arcs are active on which days
    print(f"\n📖 Story Arcs (spanning {days} days):")
    for arc in STORY_ARCS:
        print(f"   • {arc['name']}: {arc['description']}")
        print(f"     Teams: {', '.join(arc['teams_involved'])}, Duration: {arc['duration_days']} days")
    
    # Generate conversations for each day
    all_messages_by_channel = {cid: [] for cid in selected_channels}
    
    for day_idx, date_str in enumerate(dates):
        current_date = datetime.strptime(date_str, '%Y-%m-%d')
        day_number = day_idx + 1
        
        print(f"\n📅 Day {day_number}/{days} ({date_str})")
        
        # Find active story events for this day
        story_events_by_team = {}
        for arc in STORY_ARCS:
            if day_number <= arc["duration_days"]:
                for event in arc["timeline"]:
                    if event["day"] == day_number:
                        team = event["team"]
                        if team not in story_events_by_team:
                            story_events_by_team[team] = []
                        story_events_by_team[team].append({
                            "arc_name": arc["name"],
                            "event": event["event"],
                            "blocker": event.get("blocker", False),
                            "blocked_by": event.get("blocked_by", "")
                        })
        
        # Show which teams have active stories today
        if story_events_by_team:
            print(f"   Active stories: {', '.join([f'{t} ({len(e)} events)' for t, e in story_events_by_team.items()])}")
        
        # Context varies by day
        if day_idx == 0:
            context = "Beginning of sprint. Include planning, task assignments, and goal setting."
        elif day_idx == days - 1:
            context = "End of sprint. Include deadline pressure, demo prep, retrospective mentions."
        elif day_idx < 3:
            context = "Early sprint. Ramping up on tasks, clarifying questions, early progress."
        elif day_idx > days - 4:
            context = "Late sprint. Focus on finishing tasks, handling blockers, preparing for demo."
        else:
            context = "Mid-sprint. Mix of ongoing tasks, code reviews, regular progress updates."
        
        for channel_id, channel_info in selected_channels.items():
            team = channel_info["name"].replace("-team", "")
            
            # Get story events for this team
            team_events = story_events_by_team.get(team, [])
            
            # Vary message count based on activity
            if team_events:
                # More messages when story events are happening
                num_messages = 18 + random.randint(0, 8)
                print(f"   📝 #{channel_info['name']}: {num_messages} messages ({len(team_events)} story events)")
            else:
                # Background chatter
                num_messages = 8 + random.randint(0, 6)
                print(f"   📝 #{channel_info['name']}: {num_messages} messages (background)")
            
            messages = generate_conversation_with_ai(
                llm=llm,
                channel_name=channel_info["name"],
                date=current_date,
                day_number=day_number,
                num_messages=num_messages,
                personas_involved=channel_info["personas"],
                context=context,
                story_events=team_events if team_events else None
            )
            
            # Fail-fast check to avoid empty datasets
            if not messages:
                raise RuntimeError(f"LLM generation failed for {channel_info['name']} on day {day_number} — no messages produced")
            
            all_messages_by_channel[channel_id].extend(messages)
    
    # Store all messages in channels
    for channel_id, messages in all_messages_by_channel.items():
        sorted_messages = sorted(messages, key=lambda x: x['ts'])
        dataset["channels"][channel_id]["messages"] = sorted_messages
        print(f"\n✓ #{CHANNELS[channel_id]['name']}: {len(sorted_messages)} total messages")
    
    return dataset


def parse_args(args_list=None):
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="Generate synthetic Slack conversation data with multi-day story arcs")
    parser.add_argument("--days", type=int, default=10, help="Number of days to generate (default: 10)")
    parser.add_argument("--channels", type=int, default=5, help="Number of channels to use (default: 5, max: 5)")
    parser.add_argument("--output", type=str, default=None, help="Output file path")
    return parser.parse_args(args_list)


def main(args=None):
    """Main entry point."""
    if args is None:
        args = parse_args()
    
    print("=" * 70)
    print("🔧 Multi-Day Synthetic Slack Data Generator for ThreadBrief")
    print("=" * 70)
    print(f"Configuration:")
    print(f"  • Days: {args.days}")
    print(f"  • Channels: {min(args.channels, len(CHANNELS))}")
    print(f"  • Model: gemini-2.5-flash")
    
    # Generate dataset
    dataset = generate_multi_day_dataset(days=args.days, num_channels=min(args.channels, len(CHANNELS)))
    
    # Determine output path
    if args.output:
        output_path = Path(args.output)
    else:
        output_path = Path(__file__).parent.parent / "data" / "synthetic_slack_data.json"
    
    # Ensure directory exists
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Save to file
    with open(output_path, 'w') as f:
        json.dump(dataset, f, indent=2)
    
    # Print summary
    total_messages = sum(len(c["messages"]) for c in dataset["channels"].values())
    
    print("\n" + "=" * 70)
    print(f"✅ Generated synthetic data saved to {output_path}")
    print(f"   📁 Channels: {len(dataset['channels'])}")
    print(f"   👥 Users: {len(dataset['users'])}")
    print(f"   💬 Total messages: {total_messages}")
    print(f"   📅 Date range: {dataset['metadata']['start_date']} to {dataset['metadata']['end_date']}")
    print(f"   📖 Story arcs: {len(dataset['metadata']['story_arcs'])}")
    print("=" * 70)
    
    # Print sample
    sample_channel_id = list(dataset["channels"].keys())[0]
    sample_channel = dataset["channels"][sample_channel_id]
    print(f"\n📋 Sample from #{sample_channel['name']}:")
    for msg in sample_channel["messages"][:3]:
        user_name = dataset["users"].get(msg["user"], {}).get("name", msg["user"])
        text_preview = msg["text"][:80] + "..." if len(msg["text"]) > 80 else msg["text"]
        reactions_str = f" [{', '.join(msg.get('reactions', []))}]" if msg.get('reactions') else ""
        thread_str = " (reply)" if msg.get('thread_ts') else ""
        print(f"   {user_name}: {text_preview}{reactions_str}{thread_str}")


if __name__ == "__main__":
    main()
