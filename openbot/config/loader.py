"""Configuration loading utilities."""

import json
import os
from pathlib import Path

from openbot.config.schema import Config


def _find_project_root_from(cwd: Path) -> Path | None:
    """从给定目录向上查找项目根（包含 .openbot 的目录）。"""
    current = cwd.resolve()
    while current != current.parent:
        openbot_dir = current / ".openbot"
        if openbot_dir.exists() and openbot_dir.is_dir():
            return current
        current = current.parent
    return None


def bootstrap_project_root() -> None:
    """
    将进程工作目录切换到项目根目录（与 CLI 相同的「当前位置」）。
    
    从当前目录向上查找 .openbot 目录，若找到则 chdir 到该目录的父目录。
    这样 CLI、QQ 网关、HTTP 服务等所有入口启动后，workspace 解析都基于同一项目根。
    """
    cwd = Path.cwd().resolve()
    root = _find_project_root_from(cwd)
    if root is not None and root != cwd:
        os.chdir(root)


def get_config_path(use_global: bool = False) -> Path:
    """Get the default configuration file path.
    
    优先级：
    1. 如果 use_global=True，使用用户主目录
    2. 否则，总是优先使用当前目录的 .openbot/config.json
    
    Args:
        use_global: 如果为 True，使用全局配置（用户主目录）
    """
    if use_global:
        return Path.home() / ".openbot" / "config.json"
    
    # 总是优先使用当前目录
    return Path.cwd() / ".openbot" / "config.json"


def get_data_dir(use_global: bool = False) -> Path:
    """Get the openbot data directory.
    
    优先级同 get_config_path()。
    
    Args:
        use_global: 如果为 True，使用全局目录（用户主目录）
    """
    if use_global:
        return Path.home() / ".openbot"
    
    # 总是优先使用当前目录
    return Path.cwd() / ".openbot"


def load_config(config_path: Path | None = None, use_global: bool = False) -> Config:
    """
    Load configuration from file or create default.

    Args:
        config_path: Optional path to config file. Uses default if not provided.
        use_global: If True, load from global config (home directory). Otherwise, use local config.

    Returns:
        Loaded configuration object.
    """
    if config_path:
        path = config_path
    else:
        # 先尝试当前目录
        local_path = get_config_path(use_global=False)
        if local_path.exists():
            path = local_path
        elif use_global:
            # 如果指定了全局，且本地不存在，使用全局
            path = get_config_path(use_global=True)
        else:
            # 默认使用当前目录（即使文件不存在）
            path = local_path

    if path.exists():
        try:
            with open(path) as f:
                data = json.load(f)
            data = _migrate_config(data)
            return Config.model_validate(data)
        except (json.JSONDecodeError, ValueError) as e:
            print(f"Warning: Failed to load config from {path}: {e}")
            print("Using default configuration.")

    return Config()


def save_config(config: Config, config_path: Path | None = None, use_local: bool = True) -> None:
    """
    Save configuration to file.

    Args:
        config: Configuration to save.
        config_path: Optional path to save to. Uses default if not provided.
        use_local: If True, save to current directory. If False, save to home directory.
    """
    if config_path:
        path = config_path
    elif use_local:
        # 优先保存到当前目录
        path = Path.cwd() / ".openbot" / "config.json"
    else:
        # 保存到用户主目录
        path = Path.home() / ".openbot" / "config.json"
    
    path.parent.mkdir(parents=True, exist_ok=True)

    data = config.model_dump(by_alias=True)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _migrate_config(data: dict) -> dict:
    """Migrate old config formats to current."""
    # Placeholder for future migrations
    return data
