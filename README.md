# ThreadPilot - Daily Digest PoC

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
- **Synthetic data generation**: Creates realistic multi-day conversations for testing

## Quick Start

```bash
# Install dependencies
poetry install

# Copy environment template
cp .env.example .env
# Edit .env with your Slack and Google API credentials

# Generate synthetic conversation data (for testing)
./generate_data.sh --days 5 --channels 5

# Run digest with mock data
python -m daily_digest.main --mock

# Run with real Slack
python -m daily_digest.main
```

## Command Reference

### Generate Synthetic Data

Creates realistic multi-day Slack conversations for testing the digest pipeline.

**Simple command (works from anywhere):**
```bash
/path/to/ThreadPilot/generate_data.sh --days 5 --channels 5
```

**From project directory:**
```bash
cd ThreadPilot
poetry run generate-data --days 5 --channels 5 --output data/my_conversations.json
```

**Options:**
- `--days N`: Number of days to generate (default: 5)
- `--channels N`: Number of channels to generate (default: 5, max: 5)
- `--output PATH`: Output file path (default: data/synthetic_conversations.json)

**Generated data includes:**
- 16 personas across 5 teams (mechanical, electrical, software, product, QA)
- Story arcs spanning multiple days with dependencies and blockers
- Realistic conversation patterns (standups, bug reports, decisions)
- Thread replies and emoji reactions
- Cross-team dependencies

### Run Digest Pipeline

**With mock/synthetic data:**
```bash
python -m daily_digest.main --mock
```

**With real Slack (production):**
```bash
python -m daily_digest.main
```

**Preview mode (generate but don't post):**
```bash
python -m daily_digest.main --preview
```

**Debug mode:**
```bash
python -m daily_digest.main --debug
```

### Run Tests

```bash
# Run all tests
pytest tests/ -v

# Run with coverage
pytest tests/ --cov=daily_digest
```

## Project Structure

```
src/daily_digest/
├── config.py              # Channel and distribution configuration
├── slack_client.py        # Real + Mock Slack client wrapper
├── message_aggregator.py  # Fetch and filter messages
├── agents/                # LangChain agents
│   ├── base.py
│   ├── extractor.py
│   ├── blocker_detector.py
│   ├── decision_tracker.py
│   └── summarizer.py
├── digest_generator.py    # Orchestrates agents
├── formatter.py           # Formats Slack output
├── distributor.py         # Posts to Slack
├── state.py              # Last-run tracking
├── observability.py      # Metrics logging
└── main.py               # CLI entry point

scripts/
└── generate_synthetic_data.py  # Synthetic conversation generator

data/
├── synthetic_conversations.json  # Generated test data
├── memory/                       # Persistent memory stores
│   ├── blockers.json
│   └── decisions.json
└── last_run.json                # State tracking
```

## Common Workflows

### Test Full Pipeline with Synthetic Data

```bash
# Step 1: Generate test conversations
cd ThreadPilot
./generate_data.sh --days 3 --channels 3

# Step 2: Run digest with mock data
python -m daily_digest.main --mock
```

### Preview Digest without Posting

```bash
python -m daily_digest.main --preview
```

## Important Notes

- **API Key required**: Set `GOOGLE_API_KEY` in `.env` for data generation
- **Rate limits**: Free Gemini API has rate limits (5s delay between requests)
- **Project directory**: Poetry commands must be run from the directory containing `pyproject.toml`
- Use `./generate_data.sh` script to run from any directory

## Architecture

```
Slack Channels → Aggregator → Agents → Generator → Formatter → Distributor → Slack
      ↓              ↓           ↓          ↓           ↓            ↓
 mechanical     filter noise   extract   combine    format      #daily-digest
 electrical                   blockers   insights   blocks      leadership DMs
 software                    decisions              threads
```