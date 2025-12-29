"""Test configuration and shared fixtures."""

import pytest
from pathlib import Path


@pytest.fixture
def fixtures_path():
    """Path to fixture files."""
    return Path(__file__).parent.parent / "fixtures"


@pytest.fixture
def mock_fixture_path(fixtures_path):
    """Path to mock Slack data."""
    return str(fixtures_path / "slack_mock.json")


@pytest.fixture
def sample_messages():
    """Sample messages for testing."""
    return [
        {
            "ts": "1703462400.000001",
            "user": "U_TEST1",
            "text": "Completed the feature implementation. Ready for review.",
            "author": "Test User 1",
            "timestamp": "2024-12-24T10:00:00",
        },
        {
            "ts": "1703463000.000002", 
            "user": "U_TEST2",
            "text": "Found a bug in the login flow. Need to fix before release.",
            "author": "Test User 2",
            "timestamp": "2024-12-24T10:10:00",
        },
        {
            "ts": "1703463600.000003",
            "user": "U_TEST1",
            "text": "Decision: We'll go with option A for the database migration.",
            "author": "Test User 1", 
            "timestamp": "2024-12-24T10:20:00",
        },
    ]


@pytest.fixture
def sample_messages_text(sample_messages):
    """Formatted messages text for LLM."""
    lines = []
    for msg in sample_messages:
        author = msg.get("author", "Unknown")
        text = msg.get("text", "")
        ts = msg.get("timestamp", "")[:16]
        lines.append(f"[{ts}] {author}: {text}")
    return "\n".join(lines)
