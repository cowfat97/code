"""Source-module integrations; no registration or startup side effects."""

from .plugin_adapter import PluginAdapter, PluginPort

__all__ = ["PluginAdapter", "PluginPort"]
