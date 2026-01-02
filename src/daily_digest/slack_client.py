"""Slack client wrapper supporting both real and mock clients."""

import json
import os
from datetime import datetime, timedelta
from typing import Optional, Protocol
from pathlib import Path

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError


class SlackClientProtocol(Protocol):
    """Protocol for Slack client operations."""
    
    async def get_channel_history(
        self, 
        channel_id: str, 
        since_ts: Optional[str] = None
    ) -> list[dict]:
        """Fetch channel message history."""
        ...
    
    async def post_message(
        self, 
        channel: str, 
        text: str, 
        blocks: Optional[list] = None
    ) -> dict:
        """Post a message to a channel."""
        ...
    
    async def post_thread(
        self, 
        channel: str, 
        thread_ts: str, 
        text: str
    ) -> dict:
        """Post a reply in a thread."""
        ...
    
    async def send_dm(
        self, 
        user_id: str, 
        text: str, 
        blocks: Optional[list] = None
    ) -> dict:
        """Send a direct message to a user."""
        ...
    
    def get_user_name(self, user_id: str) -> str:
        """Get display name for a user ID."""
        ...


class MockSlackClient:
    """Mock Slack client that uses fixture data for testing."""
    
    def __init__(self, fixture_path: str):
        self.fixture_path = Path(fixture_path)
        self._data = None
        self._load_fixtures()
        self.posted_messages: list[dict] = []
        self.posted_threads: list[dict] = []
        self.sent_dms: list[dict] = []
    
    def _load_fixtures(self):
        """Load mock data from fixture file."""
        if self.fixture_path.exists():
            with open(self.fixture_path, "r") as f:
                self._data = json.load(f)
        else:
            self._data = {"channels": {}, "users": {}}
    
    async def get_channel_history(
        self, 
        channel_id: str, 
        since_ts: Optional[str] = None
    ) -> list[dict]:
        """Return mock messages for a channel."""
        channel_data = self._data.get("channels", {}).get(channel_id, {})
        messages = channel_data.get("messages", [])
        
        if since_ts:
            messages = [m for m in messages if float(m["ts"]) > float(since_ts)]
        
        return messages
    
    async def post_message(
        self, 
        channel: str, 
        text: str, 
        blocks: Optional[list] = None
    ) -> dict:
        """Record posted message."""
        result = {
            "ok": True,
            "channel": channel,
            "ts": str(datetime.now().timestamp()),
            "text": text,
            "blocks": blocks,
        }
        self.posted_messages.append(result)
        return result
    
    async def post_thread(
        self, 
        channel: str, 
        thread_ts: str, 
        text: str
    ) -> dict:
        """Record thread reply."""
        result = {
            "ok": True,
            "channel": channel,
            "thread_ts": thread_ts,
            "ts": str(datetime.now().timestamp()),
            "text": text,
        }
        self.posted_threads.append(result)
        return result
    
    async def send_dm(
        self, 
        user_id: str, 
        text: str, 
        blocks: Optional[list] = None
    ) -> dict:
        """Record DM."""
        result = {
            "ok": True,
            "user": user_id,
            "ts": str(datetime.now().timestamp()),
            "text": text,
            "blocks": blocks,
        }
        self.sent_dms.append(result)
        return result
    
    def get_user_name(self, user_id: str) -> str:
        """Get user name from fixtures."""
        user = self._data.get("users", {}).get(user_id, {})
        return user.get("name", user_id)
    
    def get_channel_name(self, channel_id: str) -> str:
        """Get channel name from fixtures."""
        channel = self._data.get("channels", {}).get(channel_id, {})
        return channel.get("name", channel_id)
    
    def get_reactions(
        self,
        channel: str,
        timestamp: str,
    ) -> list[dict]:
        """Get reactions for a message (mock returns empty for fixtures)."""
        # In mock mode, we don't have real reactions - return empty
        return []


class RealSlackClient:
    """Real Slack client using slack-sdk."""
    
    def __init__(self, token: Optional[str] = None):
        self.client = WebClient(token=token or os.getenv("SLACK_BOT_TOKEN"))
        self._user_cache: dict[str, str] = {}
    
    async def get_channel_history(
        self, 
        channel_id: str, 
        since_ts: Optional[str] = None
    ) -> list[dict]:
        """Fetch real channel history."""
        try:
            kwargs = {"channel": channel_id, "limit": 1000}
            if since_ts:
                kwargs["oldest"] = since_ts
            
            response = self.client.conversations_history(**kwargs)
            return response.get("messages", [])
        except SlackApiError as e:
            print(f"Error fetching history for {channel_id}: {e.response['error']}")
            return []
    
    async def post_message(
        self, 
        channel: str, 
        text: str, 
        blocks: Optional[list] = None
    ) -> dict:
        """Post message to channel."""
        try:
            kwargs = {"channel": channel, "text": text}
            if blocks:
                kwargs["blocks"] = blocks
            return self.client.chat_postMessage(**kwargs)
        except SlackApiError as e:
            print(f"Error posting message: {e.response['error']}")
            return {"ok": False, "error": e.response["error"]}
    
    async def post_thread(
        self, 
        channel: str, 
        thread_ts: str, 
        text: str
    ) -> dict:
        """Post reply in thread."""
        try:
            return self.client.chat_postMessage(
                channel=channel,
                thread_ts=thread_ts,
                text=text,
            )
        except SlackApiError as e:
            print(f"Error posting thread: {e.response['error']}")
            return {"ok": False, "error": e.response["error"]}
    
    async def send_dm(
        self, 
        user_id: str, 
        text: str, 
        blocks: Optional[list] = None
    ) -> dict:
        """Send DM to user."""
        try:
            # Open DM conversation
            dm_response = self.client.conversations_open(users=user_id)
            dm_channel = dm_response["channel"]["id"]
            
            kwargs = {"channel": dm_channel, "text": text}
            if blocks:
                kwargs["blocks"] = blocks
            return self.client.chat_postMessage(**kwargs)
        except SlackApiError as e:
            print(f"Error sending DM: {e.response['error']}")
            return {"ok": False, "error": e.response["error"]}
    
    def get_user_name(self, user_id: str) -> str:
        """Get user display name."""
        if user_id in self._user_cache:
            return self._user_cache[user_id]
        
        try:
            response = self.client.users_info(user=user_id)
            name = response["user"].get("real_name", response["user"]["name"])
            self._user_cache[user_id] = name
            return name
        except SlackApiError:
            return user_id
    
    def get_reactions(
        self,
        channel: str,
        timestamp: str,
    ) -> list[dict]:
        """
        Get reactions for a specific message.
        
        Returns list of reactions, each with 'name' and 'users' keys.
        """
        try:
            response = self.client.reactions_get(
                channel=channel,
                timestamp=timestamp,
            )
            message = response.get("message", {})
            return message.get("reactions", [])
        except SlackApiError as e:
            print(f"Error getting reactions: {e.response['error']}")
            return []


class SlackClient:
    """
    Unified Slack client interface.
    
    Abstracts real vs mock client selection:
    - Pass mock_data_path for testing with fixtures
    - Otherwise uses real Slack API
    """
    
    def __init__(
        self, 
        mock_data_path: Optional[str] = None,
        token: Optional[str] = None
    ):
        if mock_data_path:
            self._client = MockSlackClient(mock_data_path)
        else:
            self._client = RealSlackClient(token)
    
    @property
    def is_mock(self) -> bool:
        """Check if using mock client."""
        return isinstance(self._client, MockSlackClient)
    
    async def get_channel_history(
        self, 
        channel_id: str, 
        since_ts: Optional[str] = None
    ) -> list[dict]:
        """Get channel message history."""
        return await self._client.get_channel_history(channel_id, since_ts)
    
    async def post_message(
        self, 
        channel: str, 
        text: str, 
        blocks: Optional[list] = None
    ) -> dict:
        """Post a message to a channel."""
        return await self._client.post_message(channel, text, blocks)
    
    async def post_thread(
        self, 
        channel: str, 
        thread_ts: str, 
        text: str
    ) -> dict:
        """Post a reply in a thread."""
        return await self._client.post_thread(channel, thread_ts, text)
    
    async def send_dm(
        self, 
        user_id: str, 
        text: str, 
        blocks: Optional[list] = None
    ) -> dict:
        """Send a direct message."""
        return await self._client.send_dm(user_id, text, blocks)
    
    def get_user_name(self, user_id: str) -> str:
        """Get display name for user ID."""
        return self._client.get_user_name(user_id)
    
    # Mock-specific accessors for testing
    @property
    def posted_messages(self) -> list[dict]:
        """Get posted messages (mock only)."""
        if hasattr(self._client, "posted_messages"):
            return self._client.posted_messages
        return []
    
    @property
    def sent_dms(self) -> list[dict]:
        """Get sent DMs (mock only)."""
        if hasattr(self._client, "sent_dms"):
            return self._client.sent_dms
        return []
    
    def get_reactions(
        self,
        channel: str,
        timestamp: str,
    ) -> list[dict]:
        """Get reactions for a specific message."""
        return self._client.get_reactions(channel, timestamp)
