"""限定目录文本读取工具的参数协议。"""

from pydantic import BaseModel, ConfigDict, Field


class ReadTextArguments(BaseModel):
    """按行读取 UTF-8 文本；路径安全和文件大小由文件插件继续检查。"""

    # 禁止额外字段和隐式类型转换，例如不接受字符串形式的行号。
    model_config = ConfigDict(extra='forbid', strict=True)
    # 相对于文件插件 ROOT 的路径；安全检查拒绝隐藏路径、上级目录等。
    path: str = Field(min_length=1)
    # 起始行号从 1 开始，包含该行。
    start_line: int = Field(default=1, ge=1)
    # 本次最多读取的行数；默认及上限均为 200。
    line_count: int = Field(default=200, ge=1, le=200)
