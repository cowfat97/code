# 设计文档：[限定目录文件读取](../../../../../文档/Qwen/Agent/限定目录文件读取/design/详细设计.md)
import os
from pathlib import Path
import stat

from agent.entities import ReadTextArguments, PluginSpec
from agent.entities import ToolSpec

ROOT = Path(__file__).resolve().parents[2]
MAX_BYTES = 64 * 1024
MAX_RESULT_CHARS = 16000
# Keep the native function identity for capability checks even when tests wrap open.
_NATIVE_OPEN = os.open


def _components(path):
    parts = path.split('/')
    if (path.startswith('/') or '\\' in path or '\0' in path
            or any(not part or part.startswith('.') for part in parts)):
        raise ValueError('文件路径必须是非隐藏的安全相对路径')
    return parts


def _read_bytes(parts):
    if (not all(hasattr(os, name) for name in ('O_NOFOLLOW', 'O_DIRECTORY', 'O_NONBLOCK'))
            or _NATIVE_OPEN not in os.supports_dir_fd):
        raise ValueError('当前平台不支持安全文件读取')
    descriptors = []
    try:
        directory_flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_DIRECTORY
        directory = os.open(ROOT, directory_flags)
        descriptors.append(directory)
        for part in parts[:-1]:
            directory = os.open(part, directory_flags, dir_fd=directory)
            descriptors.append(directory)
        fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                     dir_fd=directory)
        descriptors.append(fd)
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise ValueError('只允许读取普通文本文件')
        if info.st_size > MAX_BYTES:
            raise ValueError('文件超过64KiB限制')
        chunks = []
        remaining = MAX_BYTES + 1
        while remaining:
            chunk = os.read(fd, remaining)
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        data = b''.join(chunks)
        if len(data) > MAX_BYTES:
            raise ValueError('文件超过64KiB限制')
        return data
    except (OSError, NotImplementedError, TypeError):
        raise ValueError('无法安全读取指定文件') from None
    finally:
        for fd in reversed(descriptors):
            os.close(fd)


def read_text(arguments):
    parts = _components(arguments.path)
    data = _read_bytes(parts)
    if b'\0' in data:
        raise ValueError('文件包含NUL，不是支持的文本文件')
    try:
        text = data.decode('utf-8-sig')
    except UnicodeDecodeError:
        raise ValueError('文件必须使用UTF-8编码') from None
    lines = text.splitlines(keepends=True)
    selected = lines[arguments.start_line - 1:arguments.start_line - 1 + arguments.line_count]
    content = ''.join(selected)
    if len(content) > MAX_RESULT_CHARS:
        raise ValueError('结果超过16000字符，请缩小读取行数')
    end_line = arguments.start_line + len(selected) - 1 if selected else None
    return {'path': '/'.join(parts), 'start_line': arguments.start_line,
            'end_line': end_line, 'total_lines': len(lines), 'content': content,
            'eof': end_line is None or end_line >= len(lines)}


def create_tools(context, config):
    if set(config) - {'design_document'}:
        raise ValueError('files插件配置字段无效')
    if 'design_document' in config:
        document = config['design_document']
        if not isinstance(document, str) or not document.strip():
            raise ValueError('design_document必须为非空字符串')
    return [ToolSpec('files__read_text', '读取当前agent目录内的UTF-8普通文件，最多64KiB、200行和16000字符。',
                     ReadTextArguments, read_text, max_calls=1, require_success=False)]


PLUGIN = PluginSpec('files', 1, create_tools)
