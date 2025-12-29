"""Base agent class for all digest agents."""

import json
import os
from abc import ABC, abstractmethod
from typing import Any, Optional

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser

from ..observability import logger


class BaseAgent(ABC):
    """
    Base class for all digest agents.
    
    Each agent:
    - Takes a list of formatted messages as input
    - Uses a specific prompt to extract information
    - Returns structured JSON output
    
    Supports mock mode for testing without API keys.
    """
    
    def __init__(
        self,
        model_name: Optional[str] = None,
        temperature: Optional[float] = None,
        mock_mode: bool = False,
    ):
        self.model_name = model_name or os.getenv("CHAT_MODEL", "gpt-4.1")
        self.temperature = temperature or float(os.getenv("TEMPERATURE", "0.3"))
        self.mock_mode = mock_mode or os.getenv("MOCK_LLM", "").lower() == "true"
        
        self.llm = None
        self.parser = JsonOutputParser()
        
        # Only initialize LLM if not in mock mode
        if not self.mock_mode:
            try:
                from langchain_openai import ChatOpenAI
                self.llm = ChatOpenAI(
                    model=self.model_name,
                    temperature=self.temperature,
                )
            except Exception as e:
                logger.warning(f"Failed to initialize LLM, falling back to mock mode: {e}")
                self.mock_mode = True
    
    @property
    @abstractmethod
    def prompt_template(self) -> str:
        """The prompt template for this agent."""
        pass
    
    @property
    @abstractmethod
    def agent_name(self) -> str:
        """Name of this agent for logging."""
        pass
    
    def _get_feedback_instructions(self, team_name: str = "") -> str:
        """Get feedback-based instructions to enhance the prompt."""
        try:
            from ..feedback import PromptEnhancer
            enhancer = PromptEnhancer()
            
            # Get item type from agent name (e.g., "BlockerDetector" -> "blocker")
            item_type = ""
            if "Blocker" in self.agent_name:
                item_type = "blocker"
            elif "Decision" in self.agent_name:
                item_type = "decision"
            elif "Extractor" in self.agent_name or "Update" in self.agent_name:
                item_type = "update"
            
            return enhancer.get_prompt_instructions(team=team_name, item_type=item_type)
        except Exception:
            return ""
    
    def _build_chain(self, team_name: str = ""):
        """Build the LangChain chain with feedback-enhanced prompt."""
        if self.llm is None:
            return None
        
        # Get feedback-based instructions
        feedback_instructions = self._get_feedback_instructions(team_name)
        
        # Enhance system prompt with feedback
        system_prompt = "You are an expert at analyzing Slack messages and extracting structured information. Always respond with valid JSON."
        if feedback_instructions:
            system_prompt += feedback_instructions
            
        prompt = ChatPromptTemplate.from_messages([
            ("system", system_prompt),
            ("human", self.prompt_template),
        ])
        return prompt | self.llm | self.parser
    
    def process(self, messages_text: str, team_name: str = "") -> dict:
        """
        Process messages and extract information.
        
        Args:
            messages_text: Formatted message text for LLM
            team_name: Name of the team for context
            
        Returns:
            Structured dictionary with extracted information
        """
        if not messages_text.strip():
            logger.warning(f"{self.agent_name}: No messages to process")
            return self._empty_result()
        
        # Use mock responses if in mock mode
        if self.mock_mode:
            logger.info(f"{self.agent_name}: Using mock response (no API key)")
            return self._mock_result(messages_text, team_name)
        
        chain = self._build_chain(team_name)
        
        try:
            result = chain.invoke({
                "messages": messages_text,
                "team_name": team_name,
            })
            logger.debug(f"{self.agent_name} result: {result}")
            return result
        except Exception as e:
            logger.error(f"{self.agent_name} error: {e}")
            return self._empty_result()
    
    @abstractmethod
    def _empty_result(self) -> dict:
        """Return empty result structure for this agent."""
        pass
    
    def _mock_result(self, messages_text: str, team_name: str) -> dict:
        """
        Generate a mock result for testing.
        
        Override in subclasses for more realistic mocks.
        """
        return self._empty_result()
    
    def estimate_tokens(self, text: str) -> int:
        """Rough estimate of token count."""
        # Approximation: 1 token ≈ 4 characters
        return len(text) // 4
