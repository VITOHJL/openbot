"""Echo tool for testing."""

from openbot.agent.tools.base import Tool


class EchoTool(Tool):
    """Echo tool - echoes back the input (for testing)."""
    
    @property
    def name(self) -> str:
        return "echo"
    
    @property
    def description(self) -> str:
        return "Echo back the input text (test capability)"
    
    @property
    def schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "Text to echo back"
                }
            },
            "required": ["text"]
        }
    
    async def execute(self, **kwargs) -> str:
        text = kwargs.get("text", "")
        return f"Echo: {text}"
