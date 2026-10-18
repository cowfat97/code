# Monitoring Hooks Implementation Plan

Goal: implement the reviewed monitoring-hooks-design with core/hook_runtime.py.
Spec: ../specs/2026-10-18-monitoring-hooks-design.md
Execution: inline in the current session, as requested by the user.

Constraints: preserve PluginSpec v1, plugin configuration v1 and existing tool failure semantics;
monitoring exceptions cannot replace business exceptions; no SDK imports in core.

- [x] Add behavioral tests for nested stages, reverse cleanup, error/cancellation propagation,
  snapshot isolation, serialization fallback and concurrent independent runtimes; verify red.
- [x] Add StageEvent/StageResult/HookSpec and HookPluginSpec, implement HookRuntime.stage.
- [x] Share configuration parsing; extend optional hook_plugins with cross-list unique IDs;
  implement load_hook_runtime(config_path=None), isolation and disabled-plugin behavior.
- [x] Move SDK adapter to plugins/langfuse; test credentials, SDK scope cleanup, cached client
  and exit flush; preserve installed langfuse>=4.7,<5 for current server compatibility.
- [x] Wire CLI and Web request boundaries and workflow(runtime=None); migrate monitoring tests.
- [x] Run all tests in WSL, Windows project tests and Web/CLI smoke checks; inspect final diff.

Review focus: nullable hook tokens, cancelled nested stages, plugin mutating event objects,
malformed configuration vs optional-plugin failures, update failure before SDK scope exit.
No automatic commit or push for this implementation.

Validation: Windows project 33/33 passed; WSL project 32 passed, 1 SDK test skipped (SDK absent); WSL Agent 37/37 passed. Real SDK test passed on Windows with in-memory export. Live server ingestion was not verified.
