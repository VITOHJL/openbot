"""File system tools for openbot."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from openbot.agent.tools.base import Tool


class ReadFileTool(Tool):
    """Read a file and return its contents."""
    
    @property
    def name(self) -> str:
        return "read_file"
    
    @property
    def description(self) -> str:
        return "Read the contents of a file. Returns the file content as a string."
    
    @property
    def schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path to the file to read (relative to workspace or absolute)"
                },
                "offset": {
                    "type": "integer",
                    "description": "Line number to start reading from (1-based, optional)",
                    "default": 1
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of lines to read (optional, reads entire file if not specified)"
                }
            },
            "required": ["file_path"]
        }
    
    async def execute(self, **kwargs: Any) -> str:
        file_path = kwargs.get("file_path", "")
        offset = kwargs.get("offset", 1)
        limit = kwargs.get("limit")
        
        if not file_path:
            return "Error: file_path is required"
        
        try:
            path = Path(file_path)
            if not path.is_absolute():
                # 相对路径：尝试相对于 workspace
                from openbot.config import load_config
                config = load_config()
                workspace = config.workspace_path
                path = workspace / path
            
            if not path.exists():
                return f"Error: File not found: {file_path}"
            
            if not path.is_file():
                return f"Error: Path is not a file: {file_path}"
            
            with open(path, "r", encoding="utf-8") as f:
                lines = f.readlines()
            
            # 应用 offset 和 limit
            start_idx = max(0, offset - 1)
            if limit:
                end_idx = min(len(lines), start_idx + limit)
                lines = lines[start_idx:end_idx]
            else:
                lines = lines[start_idx:]
            
            content = "".join(lines)
            return f"File content ({len(lines)} lines):\n{content}"
            
        except Exception as e:
            return f"Error reading file: {str(e)}"


class WriteFileTool(Tool):
    """Write content to a file."""
    
    @property
    def name(self) -> str:
        return "write_file"
    
    @property
    def description(self) -> str:
        return "Write content to a file. Creates the file if it doesn't exist, overwrites if it does."
    
    @property
    def schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path to the file to write (relative to workspace or absolute)"
                },
                "content": {
                    "type": "string",
                    "description": "Content to write to the file"
                }
            },
            "required": ["file_path", "content"]
        }
    
    async def execute(self, **kwargs: Any) -> str:
        file_path = kwargs.get("file_path", "")
        content = kwargs.get("content", "")
        
        if not file_path:
            return "Error: file_path is required"
        
        try:
            path = Path(file_path)
            if not path.is_absolute():
                # 相对路径：尝试相对于 workspace
                from openbot.config import load_config
                config = load_config()
                workspace = config.workspace_path
                path = workspace / path
            
            # 创建父目录
            path.parent.mkdir(parents=True, exist_ok=True)
            
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            
            return f"Successfully wrote {len(content)} characters to {file_path}"
            
        except Exception as e:
            return f"Error writing file: {str(e)}"


class ListDirTool(Tool):
    """List directory contents."""
    
    @property
    def name(self) -> str:
        return "list_dir"
    
    @property
    def description(self) -> str:
        return "List the contents of a directory. Returns files and subdirectories."
    
    @property
    def schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "dir_path": {
                    "type": "string",
                    "description": "Path to the directory to list (relative to workspace or absolute, defaults to workspace root)"
                },
                "recursive": {
                    "type": "boolean",
                    "description": "Whether to list recursively (default: false)"
                }
            },
            "required": []
        }
    
    async def execute(self, **kwargs: Any) -> str:
        dir_path = kwargs.get("dir_path", "")
        recursive = kwargs.get("recursive", False)
        
        try:
            if dir_path:
                path = Path(dir_path)
                if not path.is_absolute():
                    from openbot.config import load_config
                    config = load_config()
                    workspace = config.workspace_path
                    path = workspace / path
            else:
                from openbot.config import load_config
                config = load_config()
                path = config.workspace_path
            
            if not path.exists():
                return f"Error: Directory not found: {path}"
            
            if not path.is_dir():
                return f"Error: Path is not a directory: {path}"
            
            items = []
            if recursive:
                for item in path.rglob("*"):
                    rel_path = item.relative_to(path)
                    item_type = "dir" if item.is_dir() else "file"
                    items.append(f"{item_type}: {rel_path}")
            else:
                for item in sorted(path.iterdir()):
                    item_type = "dir" if item.is_dir() else "file"
                    items.append(f"{item_type}: {item.name}")
            
            if not items:
                return f"Directory is empty: {path}"
            
            return f"Directory contents ({len(items)} items):\n" + "\n".join(items)
            
        except Exception as e:
            return f"Error listing directory: {str(e)}"
