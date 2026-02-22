"""Base tool interface for openbot."""

from abc import ABC, abstractmethod
from typing import Any


class Tool(ABC):
    """Base class for tools (Atomic capabilities)."""
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Tool name."""
        pass
    
    @property
    @abstractmethod
    def description(self) -> str:
        """Tool description."""
        pass
    
    @property
    @abstractmethod
    def schema(self) -> dict[str, Any]:
        """Tool parameters schema (JSON Schema)."""
        pass
    
    @abstractmethod
    async def execute(self, **kwargs: Any) -> str:
        """Execute the tool."""
        pass
