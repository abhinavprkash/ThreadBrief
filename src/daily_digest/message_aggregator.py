"""Message aggregator for fetching and filtering Slack messages."""

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

from .slack_client import SlackClient
from .config import DigestConfig


@dataclass
class ChannelMessages:
    """Container for messages from a single channel."""
    team_name: str
    channel_id: str
    channel_name: str
    messages: list[dict] = field(default_factory=list)
    message_count: int = 0
    fetch_timestamp: str = ""
    
    def __post_init__(self):
        self.message_count = len(self.messages)
        if not self.fetch_timestamp:
            self.fetch_timestamp = datetime.now().isoformat()


class MessageAggregator:
    """
    Fetches and aggregates messages from all configured channels.
    
    Responsibilities:
    - Fetch messages for each team channel
    - Filter out noise (bots, joins/leaves, reactions-only)
    - Resolve user mentions to names
    - Return structured message containers
    """
    
    # Patterns for noise filtering
    BOT_SUBTYPE_PATTERNS = {"bot_message", "bot_add", "bot_remove"}
    SYSTEM_SUBTYPES = {
        "channel_join", "channel_leave", "channel_topic", 
        "channel_purpose", "channel_name", "group_join",
        "group_leave", "group_topic", "group_purpose"
    }
    
    def __init__(self, slack_client: SlackClient, config: DigestConfig):
        self.client = slack_client
        self.config = config
    
    async def fetch_all_channels(
        self, 
        since: Optional[datetime] = None
    ) -> list[ChannelMessages]:
        """
        Fetch messages from all configured channels.
        
        Args:
            since: Only fetch messages after this timestamp.
                   Defaults to lookback_hours from config.
        
        Returns:
            List of ChannelMessages, one per team channel.
        """
        if since is None:
            since = datetime.now() - timedelta(hours=self.config.lookback_hours)
        
        since_ts = str(since.timestamp())
        results = []
        
        for team_name, channel_id in self.config.channels.items():
            channel_messages = await self._fetch_channel(
                team_name, 
                channel_id, 
                since_ts
            )
            results.append(channel_messages)
        
        return results
    
    async def _fetch_channel(
        self, 
        team_name: str, 
        channel_id: str, 
        since_ts: str
    ) -> ChannelMessages:
        """Fetch and process messages from a single channel."""
        raw_messages = await self.client.get_channel_history(channel_id, since_ts)
        
        # Filter noise
        filtered = self.filter_noise(raw_messages)
        
        # Enrich messages with user names
        enriched = self._enrich_messages(filtered)
        
        # Get channel name if available
        channel_name = team_name
        if hasattr(self.client._client, "get_channel_name"):
            channel_name = self.client._client.get_channel_name(channel_id)
        
        return ChannelMessages(
            team_name=team_name,
            channel_id=channel_id,
            channel_name=channel_name,
            messages=enriched,
        )
    
    def filter_noise(self, messages: list[dict]) -> list[dict]:
        """
        Filter out noise from messages.
        
        Removes:
        - Bot messages (if FILTER_BOTS is enabled)
        - System messages (joins, leaves, topic changes)
        - Messages with only reactions/attachments (no text)
        - Empty messages
        """
        import os
        filter_bots = os.getenv("FILTER_BOTS", "true").lower() == "true"
        
        filtered = []
        
        for msg in messages:
            # Skip bot messages (controlled by FILTER_BOTS env var)
            if filter_bots:
                if msg.get("subtype") in self.BOT_SUBTYPE_PATTERNS:
                    continue
                if msg.get("bot_id"):
                    continue
            
            # Skip system messages
            if msg.get("subtype") in self.SYSTEM_SUBTYPES:
                continue
            
            # Skip empty or reactions-only messages
            text = msg.get("text", "").strip()
            if not text:
                continue
            
            # Skip messages that are just emoji reactions
            if self._is_reaction_only(text):
                continue
            
            filtered.append(msg)
        
        return filtered
    
    def _is_reaction_only(self, text: str) -> bool:
        """Check if message is just emoji reactions."""
        # Remove all emoji patterns
        cleaned = re.sub(r":[a-zA-Z0-9_+-]+:", "", text)
        cleaned = re.sub(r"[\U0001F600-\U0001F64F]", "", cleaned)  # emoticons
        cleaned = re.sub(r"[\U0001F300-\U0001F5FF]", "", cleaned)  # symbols
        cleaned = re.sub(r"[\U0001F680-\U0001F6FF]", "", cleaned)  # transport
        cleaned = re.sub(r"[\U0001F1E0-\U0001F1FF]", "", cleaned)  # flags
        return not cleaned.strip()
    
    def _enrich_messages(self, messages: list[dict]) -> list[dict]:
        """Add author names and clean up user mentions."""
        enriched = []
        
        for msg in messages:
            enriched_msg = msg.copy()
            
            # Add author name
            user_id = msg.get("user", "Unknown")
            enriched_msg["author"] = self.client.get_user_name(user_id)
            
            # Replace user mentions with names
            text = msg.get("text", "")
            enriched_msg["text"] = self._resolve_mentions(text)
            
            # Parse timestamp
            ts = msg.get("ts", "0")
            enriched_msg["timestamp"] = datetime.fromtimestamp(
                float(ts)
            ).isoformat()
            
            enriched.append(enriched_msg)
        
        return enriched
    
    def _resolve_mentions(self, text: str) -> str:
        """Replace <@Uxxxx> mentions with user names."""
        def replace_mention(match):
            user_id = match.group(1)
            return f"@{self.client.get_user_name(user_id)}"
        
        return re.sub(r"<@(U[A-Z0-9_]+)>", replace_mention, text)
    
    def format_messages_for_llm(self, messages: list[dict]) -> str:
        """
        Format messages for LLM consumption.
        
        Returns a string with one message per line in format:
        [timestamp] Author: Message text
        """
        lines = []
        for msg in messages:
            author = msg.get("author", "Unknown")
            text = msg.get("text", "")
            ts = msg.get("timestamp", "")[:16]  # Trim to minute precision
            lines.append(f"[{ts}] {author}: {text}")
        
        return "\n".join(lines)
