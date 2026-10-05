# Model Lab

一条流水线，从训练到推理：**train → evaluate → predict**。顶层只按流水线阶段划分，不按任务、也不按模型分目录；跑什么任务、用哪个模型、模型从哪来、怎么训练，全部由 `configs/` 决定。

当前两个目标任务：

- **文案生成（主线）** —— 无限制（abliterated）基座 `warshanks/Huihui-Qwen3-14B-abliterated-v2-AWQ`（4bit，本机已缓存 9.4 GB，供 vLLM 服务），见 [`configs/exp_gen_qwen.yaml`](configs/exp_gen_qwen.yaml)
  - 注意：4bit 量化权重**只能服务、不能直接训 LoRA**；训练需换 bf16 权重并走 QLoRA，详见 [`configs/README.md`](configs/README.md)
  - 需要官方对齐版做对照时，叠加 [`configs/exp_gen_qwen_aligned.yaml`](configs/exp_gen_qwen_aligned.yaml)（只换基座）
- **分类小模型** —— 微调 BERT，见 [`configs/exp_cls_bert.yaml`](configs/exp_cls_bert.yaml)

同时保留另一条线：在 `common/` 里自己实现 RNN / GRU / LSTM / CNN / MLP 并从零训练。

## 目录说明

| 目录 | 用途 |
| --- | --- |
| `train/` | 训练阶段入口（含微调） |
| `evaluate/` | 评估阶段入口 |
| `predict/` | 推理阶段入口 |
| `configs/` | 配置：任务、模型来源、训练起点与各阶段参数，详见 [`configs/README.md`](configs/README.md) |
| `datasets/` | 数据读取与预处理；大数据集不提交到 Git |
| `common/` | 三阶段共用：数据加载、模型定义与注册表、模型加载（本地目录 / 远端下载）、训练循环、指标、日志、随机种子 |

## 配置决定任务

`configs/` 采用**基础配置 + 阶段覆盖 + 实验覆盖**，按命令行顺序深合并，后面的覆盖前面的：

```bash
# 微调文案生成小模型（无限制基座 + LoRA，主线）
python train/train.py -c configs/base.yaml -c configs/train.yaml -c configs/exp_gen_qwen.yaml
# 换成官方对齐版基座做对照
python train/train.py -c configs/base.yaml -c configs/train.yaml -c configs/exp_gen_qwen.yaml -c configs/exp_gen_qwen_aligned.yaml
# 微调分类小模型（BERT）
python train/train.py -c configs/base.yaml -c configs/train.yaml -c configs/exp_cls_bert.yaml
# 从头训练自己写的模型（RNN / GRU / LSTM）
python train/train.py -c configs/base.yaml -c configs/train.yaml
# 推理
python predict/predict.py -c configs/base.yaml -c configs/predict.yaml
```

配置里有两条关键轴：

| 轴 | 取值 | 说明 |
| --- | --- | --- |
| `model.source` | `local` / `remote` | 执行仓库里自己写的模型，还是执行现成模型 |
| `train.init` | `scratch` / `pretrained` / `resume` | 从零训练、加载现成权重再训练（微调）、从检查点续训 |

现成模型的权重可以来自**本机目录**（`model.path`）或 **hub 下载**（`model.download`，`offline: true` 时只用本地缓存）。任务差异（分类 / 文案生成）体现在 `run.task`、`data.columns`、`data.template`、`evaluate.metrics` 与 `predict.classify.*` / `predict.generate.*` 上。字段逐项说明见 [`configs/README.md`](configs/README.md)。

推理部署走本机 WSL 里的 vLLM（由统一的 `start-local-services` Skill 管理：`~/vllm-env`、端口 8000、两个必需的环境变量），LoRA 可以 `--lora-modules` 直接挂载而不必合并；启动参数、路径换算与对应配置见 [`configs/README.md`](configs/README.md) 的「部署：本地 vLLM」一节。

## 约定

- 优先使用小数据集和小模型验证完整流程。
- `train/`、`evaluate/`、`predict/` 共用同一套数据处理与模型定义，不复制代码；共用逻辑放 `common/`。
- 新增任务不新建顶层目录：本地实现放 `common/` 并注册，现成模型用配置引用。
- 训练开始时把生效的最终配置写一份到 `runs/<run_name>/config.yaml`，评估与推理据此复现。
- 机器相关的绝对路径放 `configs/local.yaml`（已被忽略），不写进提交的配置。
- 模型权重、检查点、日志、下载缓存和大型数据文件不应直接提交到 Git（见 `.gitignore`）。
