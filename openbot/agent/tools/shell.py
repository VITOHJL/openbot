"""Shell command execution tools for openbot."""

from __future__ import annotations

import asyncio
import subprocess
from typing import Any

from openbot.agent.tools.base import Tool


class ExecuteShellTool(Tool):
    """Execute a shell command and return the output."""
    
    @property
    def name(self) -> str:
        return "execute_shell"
    
    @property
    def description(self) -> str:
        return "Execute a shell command and return the output. Use with caution - only execute safe commands."
    
    @property
    def schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "Shell command to execute"
                },
                "timeout": {
                    "type": "integer",
                    "description": "Timeout in seconds (default: 30)",
                    "default": 30
                },
                "cwd": {
                    "type": "string",
                    "description": "Working directory for the command (optional, defaults to workspace)"
                }
            },
            "required": ["command"]
        }
    
    async def execute(self, **kwargs: Any) -> str:
        command = kwargs.get("command", "")
        timeout = kwargs.get("timeout", 30)
        cwd = kwargs.get("cwd")
        
        if not command:
            return "Error: command is required"
        
        try:
            # 确定工作目录
            if cwd:
                work_dir = cwd
            else:
                from openbot.config import load_config
                config = load_config()
                work_dir = str(config.workspace_path)
            
            # 执行命令
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=work_dir,
            )
            
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=timeout
                )
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                return f"Error: Command timed out after {timeout} seconds"
            
            stdout_text = stdout.decode("utf-8", errors="replace")
            stderr_text = stderr.decode("utf-8", errors="replace")
            return_code = process.returncode
            
            result_parts = []
            if stdout_text:
                result_parts.append(f"STDOUT:\n{stdout_text}")
            if stderr_text:
                result_parts.append(f"STDERR:\n{stderr_text}")
            if return_code != 0:
                result_parts.append(f"Exit code: {return_code}")
            
            return "\n".join(result_parts) if result_parts else "Command executed (no output)"
            
        except Exception as e:
            return f"Error executing command: {str(e)}"
