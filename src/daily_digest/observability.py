"""Observability and metrics for the digest pipeline."""

import logging
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Optional
from uuid import uuid4

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("daily_digest")


@dataclass
class PipelineMetrics:
    """Metrics collected during a pipeline run."""
    
    run_id: str = field(default_factory=lambda: str(uuid4())[:8])
    run_timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    
    # Channel metrics
    channels_processed: int = 0
    messages_per_channel: dict[str, int] = field(default_factory=dict)
    
    # Token usage (estimated)
    token_usage: dict[str, int] = field(default_factory=dict)
    total_tokens: int = 0
    
    # Timing
    agent_durations_ms: dict[str, int] = field(default_factory=dict)
    total_duration_ms: int = 0
    
    # Errors
    failures: list[str] = field(default_factory=list)
    
    def to_dict(self) -> dict:
        """Convert to dictionary for logging/storage."""
        return asdict(self)


class MetricsLogger:
    """
    Collects and logs pipeline metrics.
    
    Usage:
        metrics = MetricsLogger()
        metrics.start()
        
        with metrics.track_agent("extractor"):
            # agent processing
        
        metrics.record_channel("mechanical", message_count=15)
        metrics.finish()
        metrics.log_summary()
    """
    
    def __init__(self):
        self.metrics = PipelineMetrics()
        self._start_time: Optional[float] = None
        self._agent_start: Optional[float] = None
    
    def start(self):
        """Start pipeline timing."""
        self._start_time = time.time()
        logger.info(f"Pipeline run started: {self.metrics.run_id}")
    
    def finish(self):
        """Finish pipeline timing."""
        if self._start_time:
            self.metrics.total_duration_ms = int(
                (time.time() - self._start_time) * 1000
            )
    
    def record_channel(
        self, 
        channel_name: str, 
        message_count: int,
        tokens_used: int = 0
    ):
        """Record metrics for a processed channel."""
        self.metrics.channels_processed += 1
        self.metrics.messages_per_channel[channel_name] = message_count
        if tokens_used:
            self.metrics.token_usage[channel_name] = tokens_used
            self.metrics.total_tokens += tokens_used
    
    def record_agent_duration(self, agent_name: str, duration_ms: int):
        """Record duration for an agent."""
        self.metrics.agent_durations_ms[agent_name] = duration_ms
    
    def record_failure(self, error: str):
        """Record a failure."""
        self.metrics.failures.append(error)
        logger.error(f"Pipeline failure: {error}")
    
    def track_agent(self, agent_name: str):
        """Context manager for tracking agent duration."""
        return AgentTimer(self, agent_name)
    
    def log_summary(self):
        """Log a summary of the pipeline run."""
        m = self.metrics
        
        logger.info("=" * 50)
        logger.info(f"Pipeline Run Summary: {m.run_id}")
        logger.info("=" * 50)
        logger.info(f"Timestamp: {m.run_timestamp}")
        logger.info(f"Duration: {m.total_duration_ms}ms")
        logger.info(f"Channels processed: {m.channels_processed}")
        
        if m.messages_per_channel:
            logger.info("Messages per channel:")
            for channel, count in m.messages_per_channel.items():
                logger.info(f"  - {channel}: {count}")
        
        if m.token_usage:
            logger.info(f"Total tokens used: {m.total_tokens}")
        
        if m.agent_durations_ms:
            logger.info("Agent durations:")
            for agent, ms in m.agent_durations_ms.items():
                logger.info(f"  - {agent}: {ms}ms")
        
        if m.failures:
            logger.warning(f"Failures: {len(m.failures)}")
            for failure in m.failures:
                logger.warning(f"  - {failure}")
        else:
            logger.info("Status: SUCCESS")
        
        logger.info("=" * 50)


class AgentTimer:
    """Context manager for timing agent execution."""
    
    def __init__(self, metrics_logger: MetricsLogger, agent_name: str):
        self.metrics_logger = metrics_logger
        self.agent_name = agent_name
        self.start_time: Optional[float] = None
    
    def __enter__(self):
        self.start_time = time.time()
        logger.debug(f"Starting agent: {self.agent_name}")
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.start_time:
            duration_ms = int((time.time() - self.start_time) * 1000)
            self.metrics_logger.record_agent_duration(self.agent_name, duration_ms)
            logger.debug(f"Agent {self.agent_name} completed in {duration_ms}ms")
        
        if exc_type:
            self.metrics_logger.record_failure(
                f"{self.agent_name}: {exc_type.__name__}: {exc_val}"
            )
        
        return False  # Don't suppress exceptions
