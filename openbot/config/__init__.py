"""Configuration module for openbot."""

from openbot.config.loader import bootstrap_project_root, get_config_path, load_config, save_config
from openbot.config.schema import Config

__all__ = ["Config", "bootstrap_project_root", "get_config_path", "load_config", "save_config"]
