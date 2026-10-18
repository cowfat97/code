# 设计文档：[插件机制](../../../../文档/Qwen/Agent/插件机制/design/详细设计.md)
import copy
import json
import re
from importlib import import_module
from pathlib import Path
import os
from .base import PluginLoadError
from agent.entities import PluginSpec, ToolSpec

DEFAULT_CONFIG_PATH = Path(__file__).with_name('plugins.json')
QWEN_ROOT = Path(__file__).resolve().parents[2]


ID_PATTERN = re.compile(r'[a-z][a-z0-9_]{0,31}', re.ASCII)
MODULE_PATTERN = re.compile(r'[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*', re.ASCII)


def _error(stage, path, plugin, reason):
    return PluginLoadError(f'插件加载失败 [stage={stage}] [path={path}] [plugin={plugin}] {reason}')


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('重复JSON键：' + key)
        result[key] = value
    return result


def _reject_constant(value):
    raise ValueError('非有限JSON数值')


def _read_config(path):
    data = json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=_object,
                      parse_constant=_reject_constant)
    json.dumps(data, allow_nan=False)
    if not isinstance(data, dict) or not {'schema_version', 'plugins'} <= data.keys() or data.keys() - {'schema_version', 'plugins', 'metadata', 'hook_plugins'}:
        raise ValueError('顶层字段无效')
    if type(data['schema_version']) is not int or data['schema_version'] != 1:
        raise ValueError('schema_version必须为整数1')
    if 'metadata' in data:
        metadata = data['metadata']
        if not isinstance(metadata, dict) or set(metadata) != {'design_document'} or not isinstance(metadata['design_document'], str) or not metadata['design_document'].strip():
            raise ValueError('metadata.design_document必须为非空字符串')
    if not isinstance(data['plugins'], list):
        raise ValueError('plugins必须为数组')
    hooks = data.get('hook_plugins', [])
    if not isinstance(hooks, list):
        raise ValueError('hook_plugins必须为数组')
    ids = set()
    for index, entry in enumerate(data['plugins'] + hooks):
        label = f'plugins[{index}]'
        if not isinstance(entry, dict) or set(entry) != {'id', 'module', 'enabled', 'config'}:
            raise ValueError(label + '字段无效')
        if not isinstance(entry['id'], str) or not ID_PATTERN.fullmatch(entry['id']):
            raise ValueError(label + '.id无效')
        if entry['id'] in ids:
            raise ValueError(label + '.id重复')
        ids.add(entry['id'])
        if not isinstance(entry['module'], str) or not MODULE_PATTERN.fullmatch(entry['module']):
            raise ValueError(label + '.module无效')
        if type(entry['enabled']) is not bool or not isinstance(entry['config'], dict):
            raise ValueError(label + '.enabled/config类型无效')
    data.setdefault('hook_plugins', [])
    return data


def read_plugin_config(*, config_path=None):
    selected = config_path if config_path is not None else os.environ.get('QWEN_PLUGINS_CONFIG')
    path = DEFAULT_CONFIG_PATH
    try:
        if selected is not None:
            if not str(selected).strip():
                raise ValueError('配置路径不能为空')
            path = Path(selected).expanduser()
        if not path.is_absolute():
            path = QWEN_ROOT / path
        try:
            entries = _read_config(path)
        except FileNotFoundError:
            if selected is None:
                return path, {'plugins': [], 'hook_plugins': []}
            raise
    except Exception as exc:
        raise _error('配置', path, '-', str(exc)) from exc
    return path, entries


def load_plugins(context, *, config_path=None, reserved_names=()):
    path, config = read_plugin_config(config_path=config_path)
    entries = config['plugins']
    tools = {}
    reserved = {'answer', *reserved_names}
    for entry in entries:
        if not entry['enabled']:
            continue
        plugin_id = entry['id']
        try:
            module = import_module(entry['module'])
        except Exception as exc:
            raise _error('导入', path, plugin_id, '模块导入失败') from exc
        try:
            plugin = getattr(module, 'PLUGIN', None)
            if not isinstance(plugin, PluginSpec) or plugin.id != plugin_id:
                raise ValueError('PLUGIN类型或ID无效')
            if type(plugin.api_version) is not int or plugin.api_version != 1:
                raise ValueError('api_version必须为整数1')
            if not callable(plugin.create_tools):
                raise ValueError('create_tools不可调用')
        except Exception as exc:
            raise _error('声明', path, plugin_id, str(exc)) from exc
        try:
            created = plugin.create_tools(context, copy.deepcopy(entry['config']))
        except Exception as exc:
            raise _error('工厂', path, plugin_id, 'create_tools执行失败') from exc
        try:
            if not isinstance(created, (list, tuple)) or not created:
                raise ValueError('工厂必须返回非空list或tuple')
            for spec in created:
                _validate_tool(spec, plugin_id, reserved | tools.keys())
                tools[spec.name] = spec
        except Exception as exc:
            raise _error('工具校验', path, plugin_id, str(exc)) from exc
    return tools


def _validate_tool(spec, plugin_id, reserved):
    if not isinstance(spec, ToolSpec):
        raise ValueError('工具必须为ToolSpec')
    prefix = plugin_id + '__'
    if not isinstance(spec.name, str) or not spec.name.startswith(prefix) or not ID_PATTERN.fullmatch(spec.name[len(prefix):]) or len(spec.name) > 64 or spec.name in reserved:
        raise ValueError('工具名称无效或冲突')
    if not isinstance(spec.description, str) or not spec.description.strip():
        raise ValueError('工具说明必须为非空字符串')
    if not callable(spec.handler) or type(spec.max_calls) is not int or spec.max_calls < 1:
        raise ValueError('handler或max_calls无效')
    if type(spec.require_success) is not bool or (spec.result_footer is not None and not callable(spec.result_footer)):
        raise ValueError('require_success或result_footer无效')
    schema = spec.parameters()
    if not isinstance(schema, dict):
        raise ValueError('参数Schema必须为字典')
    json.dumps(schema, allow_nan=False)
