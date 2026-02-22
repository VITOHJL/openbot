"""Tool registry for automatic tool discovery and registration."""

from __future__ import annotations

import importlib
import inspect
from pathlib import Path
from typing import Any

from openbot.agent.tools.base import Tool
from openbot.infra.capability_registry import Capability, CapabilityRegistry


class ToolRegistry:
    """工具注册表，自动发现并注册工具。"""

    def __init__(self, capability_registry: CapabilityRegistry) -> None:
        self._cap_reg = capability_registry
        self._tools: dict[str, Tool] = {}

    def register_tool(self, tool: Tool) -> None:
        """注册单个工具。"""
        self._tools[tool.name] = tool
        
        # 同时注册到 CapabilityRegistry
        capability = Capability(
            name=tool.name,
            description=tool.description,
            level="atomic",
            schema=tool.schema,
        )
        self._cap_reg.register(capability)

    def register_tool_class(self, tool_class: type[Tool]) -> None:
        """注册工具类（会自动实例化）。"""
        tool = tool_class()
        self.register_tool(tool)

    def get_tool(self, name: str) -> Tool | None:
        """获取工具实例。"""
        return self._tools.get(name)

    def auto_discover(self, tools_dir: Path | None = None) -> None:
        """自动发现并注册工具。
        
        Args:
            tools_dir: 工具目录路径，如果为 None，使用默认的 tools/ 目录
        """
        if tools_dir is None:
            # 使用当前包的目录
            tools_dir = Path(__file__).parent
        
        # 预定义的工具模块列表（避免动态导入问题）
        tool_modules = [
            "openbot.agent.tools.echo",
            "openbot.agent.tools.filesystem",
            "openbot.agent.tools.shell",
        ]
        
        # 导入预定义的工具模块
        for module_name in tool_modules:
            try:
                module = importlib.import_module(module_name)
                
                # 查找所有 Tool 子类
                for name, obj in inspect.getmembers(module, inspect.isclass):
                    if (issubclass(obj, Tool) and 
                        obj is not Tool and 
                        obj.__module__ == module_name):
                        self.register_tool_class(obj)
            except Exception as e:
                import logging
                logging.warning(f"Failed to load tool from {module_name}: {e}")
        
        # 也尝试动态发现其他工具模块
        for py_file in tools_dir.glob("*.py"):
            if py_file.name in ("__init__.py", "base.py", "registry.py", "echo.py", "filesystem.py", "shell.py"):
                continue
            
            module_name = f"openbot.agent.tools.{py_file.stem}"
            try:
                module = importlib.import_module(module_name)
                
                # 查找所有 Tool 子类
                for name, obj in inspect.getmembers(module, inspect.isclass):
                    if (issubclass(obj, Tool) and 
                        obj is not Tool and 
                        obj.__module__ == module_name):
                        self.register_tool_class(obj)
            except Exception as e:
                import logging
                logging.warning(f"Failed to load tool from {module_name}: {e}")

    def list_tools(self) -> list[str]:
        """列出所有已注册的工具名称。"""
        return list(self._tools.keys())
