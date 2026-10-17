"""工具定义及参数实体；具体工具实现位于 agent.tools 和插件目录。"""

from .files import ReadTextArguments
from .spec import ToolSpec

__all__ = ["ReadTextArguments", "ToolSpec"]
