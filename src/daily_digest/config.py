"""Configuration for Daily Digest."""

import os
from dataclasses import dataclass, field
from typing import Optional
from dotenv import load_dotenv

load_dotenv()


@dataclass
class ChannelConfig:
    """Configuration for a team channel."""
    team_name: str
    channel_id: str
    

@dataclass
class DigestConfig:
    """Main configuration for the digest system."""
    
    # Team channels to monitor
    channels: dict[str, str] = field(default_factory=dict)
    
    # Distribution settings
    digest_channel: str = ""
    leadership_users: list[str] = field(default_factory=list)
    
    # Processing settings
    lookback_hours: int = 24
    max_summary_length: int = 500
    
    # Model settings
    chat_model: str = "gpt-4.1"
    temperature: float = 0.3
    
    @classmethod
    def from_env(cls) -> "DigestConfig":
        """Load configuration from environment variables."""
        channels = {
            "mechanical": os.getenv("CHANNEL_MECHANICAL", "C_MECHANICAL"),
            "electrical": os.getenv("CHANNEL_ELECTRICAL", "C_ELECTRICAL"),
            "software": os.getenv("CHANNEL_SOFTWARE", "C_SOFTWARE"),
        }
        
        leadership_str = os.getenv("LEADERSHIP_USERS", "")
        leadership_users = [u.strip() for u in leadership_str.split(",") if u.strip()]
        
        return cls(
            channels=channels,
            digest_channel=os.getenv("CHANNEL_DIGEST", "C_DIGEST"),
            leadership_users=leadership_users,
            lookback_hours=int(os.getenv("LOOKBACK_HOURS", "24")),
            max_summary_length=int(os.getenv("MAX_SUMMARY_LENGTH", "500")),
            chat_model=os.getenv("CHAT_MODEL", "gpt-4.1"),
            temperature=float(os.getenv("TEMPERATURE", "0.3")),
        )


def get_config() -> DigestConfig:
    """Get the current configuration."""
    return DigestConfig.from_env()
