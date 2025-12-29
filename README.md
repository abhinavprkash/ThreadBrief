# Daily Digest PoC

A proof-of-concept for generating daily team digests from Slack channels using LangChain agents.

## Features

- **Multi-team aggregation**: Fetches messages from mechanical, electrical, and software team channels
- **AI-powered analysis**: Uses 4 specialized LangChain agents:
  - **Extractor**: Identifies key updates and progress
  - **BlockerDetector**: Finds blockers and issues
  - **DecisionTracker**: Captures decisions made
  - **Summarizer**: Creates concise team summaries
- **Smart distribution**: Posts to digest channel, threads details, and DMs leadership
- **Mock testing**: In-process mock Slack client for development

## Quick Start

```bash
# Install dependencies
poetry install

# Copy environment template
cp .env.example .env
# Edit .env with your Slack and OpenAI credentials

# Run with mock data (for testing)
python -m daily_digest.main --mock

# Run with real Slack
python -m daily_digest.main
```

## Project Structure

```
src/daily_digest/
├── config.py           # Channel and distribution configuration
├── slack_client.py     # Real + Mock Slack client wrapper
├── message_aggregator.py  # Fetch and filter messages
├── agents/             # LangChain agents
│   ├── base.py
│   ├── extractor.py
│   ├── blocker_detector.py
│   ├── decision_tracker.py
│   └── summarizer.py
├── digest_generator.py # Orchestrates agents
├── formatter.py        # Formats Slack output
├── distributor.py      # Posts to Slack
├── state.py           # Last-run tracking
├── observability.py   # Metrics logging
└── main.py            # CLI entry point
```

## Testing

```bash
# Run all tests
pytest tests/ -v

# Run with coverage
pytest tests/ --cov=daily_digest
```

## Architecture

```
Slack Channels → Aggregator → Agents → Generator → Formatter → Distributor → Slack
      ↓              ↓           ↓          ↓           ↓            ↓
 mechanical     filter noise   extract   combine    format      #daily-digest
 electrical                   blockers   insights   blocks      leadership DMs
 software                    decisions              threads
```