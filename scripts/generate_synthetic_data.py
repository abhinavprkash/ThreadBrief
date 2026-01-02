#!/usr/bin/env python3
"""
Generate synthetic Slack conversation data for testing ThreadBrief.

This script generates realistic multi-day Slack conversations with:
- Multiple personas with distinct communication styles
- Conversation patterns (standups, bug reports, blockers, casual)
- Thread replies and emoji reactions
- Cross-team dependencies and blockers

Usage:
    poetry run python scripts/generate_synthetic_data.py [--days N] [--output PATH]

Requirements:
    - OPENAI_API_KEY and CHAT_MODEL in .env
"""

import json
import os
import random
import argparse
from datetime import datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain.schema import HumanMessage

load_dotenv()

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
}

# Common emoji reactions
EMOJI_REACTIONS = [
    "thumbsup", "eyes", "rocket", "fire", "100", "white_check_mark",
    "thinking_face", "pray", "raised_hands", "+1", "clap", "tada"
]


def get_llm():
    """Initialize LLM using CHAT_MODEL from .env."""
    model = os.getenv("CHAT_MODEL", "gpt-4")
    temperature = float(os.getenv("TEMPERATURE", "0.7"))
    
    return ChatOpenAI(
        model=model,
        temperature=temperature,
    )


def generate_conversation_with_ai(
    llm,
    channel_name: str,
    date: datetime,
    num_messages: int,
    personas_involved: list[str],
    context: str = ""
) -> list[dict]:
    """Use LLM to generate realistic Slack conversation."""
    
    persona_descriptions = "\n".join([
        f"- {pid}: {PERSONAS[pid]['name']} ({PERSONAS[pid]['role']}) - {PERSONAS[pid]['style']}. "
        f"Typical phrases: {', '.join(PERSONAS[pid]['typical_phrases'][:3])}"
        for pid in personas_involved
    ])
    
    prompt = f"""Generate a realistic Slack conversation for #{channel_name} channel on {date.strftime('%Y-%m-%d')}.

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
- {context}

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
- Blockers mentioning cross-team dependencies
- Code/design review requests
- End-of-day summaries from leads
- Brief casual exchanges (lunch, coffee, weekend plans)

Generate realistic, varied content - avoid generic placeholder text."""

    try:
        response = llm.invoke([HumanMessage(content=prompt)])
        content = response.content
        
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
            
            return processed_messages
    except Exception as e:
        print(f"  ⚠️  Error generating conversation: {e}")
    
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


def generate_multi_day_dataset(days: int = 5) -> dict:
    """Generate a multi-day conversation dataset."""
    
    print(f"\n🤖 Initializing LLM (model: {os.getenv('CHAT_MODEL', 'gpt-4')})...")
    llm = get_llm()
    
    # Calculate dates (going back from today)
    start_date = datetime.now() - timedelta(days=days - 1)
    dates = [(start_date + timedelta(days=i)).strftime('%Y-%m-%d') for i in range(days)]
    
    dataset = {"channels": {}, "users": {}}
    
    # Add users from personas
    for pid, persona in PERSONAS.items():
        dataset["users"][pid] = {
            "name": persona["name"],
            "team": persona["team"]
        }
    
    # Initialize channels
    for channel_id, channel_info in CHANNELS.items():
        dataset["channels"][channel_id] = {
            "name": channel_info["name"],
            "messages": []
        }
    
    # Generate conversations for each day
    all_messages_by_channel = {cid: [] for cid in CHANNELS}
    
    for day_idx, date_str in enumerate(dates):
        current_date = datetime.strptime(date_str, '%Y-%m-%d')
        
        # Context varies by day in sprint
        if day_idx == 0:
            context = "Beginning of a new sprint. Include sprint planning, task assignments, and goal setting."
        elif day_idx == days - 1:
            context = "End of sprint. Include deadline pressure, blocker escalation, demo prep, and retrospective mentions."
        elif day_idx == 1:
            context = "Day 2 of sprint. People are ramping up on tasks, some clarifying questions, early progress updates."
        else:
            context = "Mid-sprint work day. Mix of ongoing tasks, some blockers emerging, code reviews, and regular progress."
        
        for channel_id, channel_info in CHANNELS.items():
            # Vary message count by day and add some randomness
            base_count = 20
            if day_idx == 0 or day_idx == days - 1:
                base_count = 25  # More activity at sprint boundaries
            num_messages = base_count + random.randint(-5, 10)
            
            print(f"📝 Generating {num_messages} messages for #{channel_info['name']} on {date_str}...")
            
            messages = generate_conversation_with_ai(
                llm=llm,
                channel_name=channel_info["name"],
                date=current_date,
                num_messages=num_messages,
                personas_involved=channel_info["personas"],
                context=context
            )
            
            all_messages_by_channel[channel_id].extend(messages)
            print(f"   ✓ Generated {len(messages)} messages")
    
    # Store all messages in channels
    for channel_id, messages in all_messages_by_channel.items():
        dataset["channels"][channel_id]["messages"] = sorted(messages, key=lambda x: x['ts'])
    
    # Create dated structure for cross-channel blockers
    dated_dataset = {}
    for date_str in dates:
        dated_dataset[date_str] = {}
        for channel_id in CHANNELS:
            dated_dataset[date_str][channel_id] = [
                m for m in all_messages_by_channel[channel_id]
                if date_str in datetime.fromtimestamp(float(m['ts'].split('.')[0])).strftime('%Y-%m-%d')
            ]
    
    # Add cross-channel blockers
    dated_dataset = add_cross_channel_blockers(dated_dataset, dates)
    
    # Merge back
    for channel_id in CHANNELS:
        all_msgs = []
        for date_str in dates:
            all_msgs.extend(dated_dataset[date_str][channel_id])
        dataset["channels"][channel_id]["messages"] = sorted(all_msgs, key=lambda x: x['ts'])
    
    return dataset


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Generate synthetic Slack conversation data")
    parser.add_argument("--days", type=int, default=5, help="Number of days to generate (default: 5)")
    parser.add_argument("--output", type=str, default=None, help="Output file path")
    args = parser.parse_args()
    
    print("=" * 60)
    print("🔧 Synthetic Slack Data Generator for ThreadBrief")
    print("=" * 60)
    
    # Generate dataset
    dataset = generate_multi_day_dataset(days=args.days)
    
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
    
    print("\n" + "=" * 60)
    print(f"✅ Generated synthetic data saved to {output_path}")
    print(f"   Channels: {len(dataset['channels'])}")
    print(f"   Users: {len(dataset['users'])}")
    print(f"   Total messages: {total_messages}")
    print("=" * 60)
    
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
