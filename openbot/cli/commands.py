"""
CLI entrypoints for openbot.

按照 SPEC.md 实现 CLI 命令，支持单次对话和交互式模式。
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import typer
from rich.console import Console

# 在 Windows 上强制使用 UTF-8 输出，避免 Unicode 字符（如 emoji、↳）导致 gbk 编码错误
if sys.platform == "win32":
    try:
        # 切换控制台代码页为 UTF-8 (65001)
        import os
        os.system("chcp 65001 >nul 2>&1")
    except Exception:
        pass
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass

from openbot.agent.context import ContextBuilder
from openbot.agent.loop import ExecutionAgent
from openbot.config import load_config
from openbot.config.loader import bootstrap_project_root
from openbot.infra.capability_registry import CapabilityRegistry
from openbot.infra.context_manager import ContextManager
from openbot.infra.log_service import LogService
from openbot.providers.litellm_provider import LiteLLMProvider
from openbot.session.manager import SessionManager

console = Console()
app = typer.Typer(help="openbot CLI")


@app.callback()
def _main() -> None:
    """所有命令执行前，将工作目录切换到项目根（与 CLI 相同的「当前位置」）。"""
    bootstrap_project_root()


def _safe_print(text: str) -> None:
    """安全打印，避免 Windows gbk 控制台下的 UnicodeEncodeError。"""
    try:
        console.print(text)
    except (UnicodeEncodeError, UnicodeDecodeError):
        try:
            # 替换无法编码的字符后输出
            safe = text.encode("utf-8", errors="replace").decode("utf-8")
            print(safe)
        except Exception:
            print(repr(text)[:500])


def _get_workspace() -> Path:
    """获取 workspace 路径。"""
    config = load_config()
    return config.workspace_path


def _make_provider() -> LiteLLMProvider:
    """创建 LLM Provider。"""
    config = load_config()
    model = config.agents.defaults.model
    
    # Get provider config from config system
    provider_config = config.get_provider(model)
    provider_name = config.get_provider_name(model)
    
    if not provider_config or not provider_config.api_key:
        console.print("[yellow]Warning: No API key found in config. Please run 'openbot config' to set up.[/yellow]")
        console.print(f"[dim]Looking for model: {model}[/dim]")
        console.print(f"[dim]Available providers: {', '.join([p.name for p in config.providers.model_dump().keys()])}[/dim]")
    
    api_key = provider_config.api_key if provider_config else None
    api_base = config.get_api_base(model)
    extra_headers = provider_config.extra_headers if provider_config else None
    
    return LiteLLMProvider(
        api_key=api_key,
        api_base=api_base,
        default_model=model,
        extra_headers=extra_headers,
        provider_name=provider_name,
    )


def _make_agent(workspace: Path) -> ExecutionAgent:
    """创建 ExecutionAgent 实例。"""
    config = load_config()
    provider = _make_provider()
    ctx_mgr = ContextManager()
    cap_reg = CapabilityRegistry()
    log_svc = LogService()
    session_mgr = SessionManager(workspace)
    ctx_builder = ContextBuilder(workspace, session_mgr)
    
    # 创建工具注册表并自动发现工具
    from openbot.agent.tools.registry import ToolRegistry
    tool_registry = ToolRegistry(cap_reg)
    tool_registry.auto_discover()
    
    return ExecutionAgent(
        provider=provider,
        context_manager=ctx_mgr,
        capability_registry=cap_reg,
        log_service=log_svc,
        context_builder=ctx_builder,
        session_manager=session_mgr,
        tool_registry=tool_registry,
        max_iterations=config.agents.defaults.max_tool_iterations,
        model=config.agents.defaults.model,
        temperature=config.agents.defaults.temperature,
        max_tokens=config.agents.defaults.max_tokens,
    )


@app.command()
def agent(
    message: str = typer.Option(None, "--message", "-m", help="Message to send to the agent"),
    session_id: str = typer.Option("cli:direct", "--session", "-s", help="Session ID"),
) -> None:
    """Interact with the agent directly."""
    workspace = _get_workspace()
    workspace.mkdir(parents=True, exist_ok=True)
    
    agent = _make_agent(workspace)
    
    async def _cli_progress(content: str) -> None:
        try:
            console.print(f"  [dim]> {content}[/dim]")
        except (UnicodeEncodeError, UnicodeDecodeError):
            _safe_print(f"  > {content}")
    
    if message:
        # Single message mode
        async def run_once():
            session = agent._session_mgr.get_or_create(session_id)
            result = await agent.process_task(message, session=session, on_progress=_cli_progress)
            _safe_print(result)
        
        asyncio.run(run_once())
    else:
        # Interactive mode
        console.print("openbot Interactive mode (type 'exit' or Ctrl+C to quit)\n")
        
        async def run_interactive():
            session = agent._session_mgr.get_or_create(session_id)
            while True:
                try:
                    user_input = input("> ")
                    if not user_input.strip():
                        continue
                    if user_input.strip().lower() in ("exit", "quit", "q"):
                        console.print("\nGoodbye!")
                        break
                    
                    result = await agent.process_task(user_input, session=session, on_progress=_cli_progress)
                    _safe_print(f"\n{result}\n")
                except KeyboardInterrupt:
                    console.print("\n\nGoodbye!")
                    break
                except EOFError:
                    console.print("\n\nGoodbye!")
                    break
        
        asyncio.run(run_interactive())


@app.command()
def config(
    global_config: bool = typer.Option(False, "--global", "-g", help="Use global config in home directory instead of local")
) -> None:
    """初始化或查看配置。"""
    from openbot.config import get_config_path, save_config
    
    # 根据参数加载配置
    config = load_config(use_global=global_config)
    config_path = get_config_path(use_global=global_config)
    
    console.print(f"[bold]OpenBot Configuration[/bold]")
    console.print(f"Config file: {config_path}")
    if global_config:
        console.print("[dim](Using global config)[/dim]")
    else:
        console.print("[dim](Using local config in current directory)[/dim]")
    console.print()
    
    # Show current config
    console.print("[bold]Current Settings:[/bold]")
    console.print(f"  Workspace: {config.workspace_path}")
    console.print(f"  Default Model: {config.agents.defaults.model}")
    console.print(f"  Max Tokens: {config.agents.defaults.max_tokens}")
    console.print(f"  Temperature: {config.agents.defaults.temperature}")
    console.print(f"  Max Tool Iterations: {config.agents.defaults.max_tool_iterations}\n")
    
    # Show provider status
    console.print("[bold]Provider Status:[/bold]")
    model = config.agents.defaults.model
    provider_config = config.get_provider(model)
    provider_name = config.get_provider_name(model)
    
    if provider_config and provider_config.api_key:
        console.print(f"  ✓ Model '{model}' → Provider: {provider_name or 'unknown'}")
        console.print(f"    API Key: {'*' * 20}...{provider_config.api_key[-4:] if len(provider_config.api_key) > 4 else '****'}")
        if provider_config.api_base:
            console.print(f"    API Base: {provider_config.api_base}")
    else:
        console.print(f"  ✗ No API key configured for model '{model}'")
        console.print(f"    Please set API key in config file or use environment variables.\n")
        console.print("[yellow]To configure, edit the config file directly or set environment variables:[/yellow]")
        console.print("  OPENBOT__PROVIDERS__OPENROUTER__API_KEY=your_key")
        console.print("  OPENBOT__PROVIDERS__ANTHROPIC__API_KEY=your_key")
    
    # Save config if it doesn't exist
    if not config_path.exists():
        save_config(config, use_local=not global_config)
        console.print(f"\n[green]✓ Created default config at {config_path}[/green]")
        console.print("[dim]You can edit it directly or use environment variables.[/dim]")


@app.command()
def serve() -> None:
    """启动网关服务（QQ 等渠道）。工作目录与 CLI 一致，基于项目根。"""
    # bootstrap 已在 callback 中执行，此处 workspace 已正确解析
    config = load_config()
    workspace = _get_workspace()
    workspace.mkdir(parents=True, exist_ok=True)
    console.print(f"[bold]OpenBot Gateway[/bold]")
    console.print(f"  Workspace: {workspace}")
    console.print(f"  Host: {config.gateway.host}:{config.gateway.port}")
    console.print("\n[yellow]QQ 渠道尚未实现，请等待后续版本。[/yellow]")


