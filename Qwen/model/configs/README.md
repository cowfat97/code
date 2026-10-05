# configs/ 配置说明

一条流水线的全部行为由这里决定：**执行哪个环节、什么任务、模型从哪来、训练从哪起步、各阶段参数**。

## 文件

| 文件 | 作用 |
| --- | --- |
| `base.yaml` | 基础配置：任务、模型来源与参数、数据（含列映射与模板）、设备 |
| `train.yaml` | 训练阶段覆盖：`run.stage: train` + 训练起点与训练参数 |
| `evaluate.yaml` | 评估阶段覆盖：`run.stage: evaluate` + 评估参数 |
| `predict.yaml` | 推理阶段覆盖：`run.stage: predict` + 推理参数 |
| `exp_cls_bert.yaml` | 示例①：**分类小模型**，微调 BERT |
| `exp_gen_qwen.yaml` | 示例②（**主线**）：**文案生成**，以无限制基座 `warshanks/Huihui-Qwen3-14B-abliterated-v2-AWQ`（4bit，本机已缓存 9.4 GB）为服务基座 |
| `exp_gen_qwen_aligned.yaml` | 示例②-附：把基座换成官方对齐版 `Qwen/Qwen3-4B`（对照用，只覆盖 `model` 段；本机已无缓存，用它会联网下载 ≈7.5 GB） |

## 合并规则

按命令行顺序**深合并**，后面的文件覆盖前面的同名键。顺序固定为**基础 → 阶段 → 实验**：

```bash
# 从头训练自己写的模型（RNN / GRU / LSTM / CNN / MLP）
python train/train.py -c configs/base.yaml -c configs/train.yaml

# 文案生成（无限制 14B 基座，主线）
python train/train.py -c configs/base.yaml -c configs/train.yaml -c configs/exp_gen_qwen.yaml

# 换成官方对齐版 4B 基座做对照
python train/train.py -c configs/base.yaml -c configs/train.yaml -c configs/exp_gen_qwen.yaml -c configs/exp_gen_qwen_aligned.yaml

# 微调分类小模型（BERT）
python train/train.py -c configs/base.yaml -c configs/train.yaml -c configs/exp_cls_bert.yaml

# 评估 / 推理
python evaluate/evaluate.py -c configs/base.yaml -c configs/evaluate.yaml
python predict/predict.py   -c configs/base.yaml -c configs/predict.yaml
```

实验覆盖放最后，才能盖掉阶段文件里的默认参数（例如 `train.yaml` 的 `lr: 0.001` 被微调的 `lr: 0.0002` 覆盖）；`run.stage` 始终由阶段文件给出。

深合并只覆盖写出来的键。要把基础配置里的**整块**清掉，显式写 `null`——微调示例都用 `model.params: null` 清空本地结构参数。

## 文案生成：以无限制基座为主线

生成线默认用**去审查（abliterated）基座**，不再拒答；需要官方对齐版时叠加一行覆盖文件即可。

| 事项 | 说明 |
| --- | --- |
| 默认基座 | `warshanks/Huihui-Qwen3-14B-abliterated-v2-AWQ`（4bit 量化，约 9.4 GB） |
| 架构 | `qwen3`：40 层 / hidden 5120 / 40 注意力头 / 8 KV 头 / vocab 151936；`lora.target_modules` 仍是 `q_proj`、`k_proj`、`v_proj`、`o_proj` |
| 对照基座 | `Qwen/Qwen3-4B`（官方对齐版），叠加 `exp_gen_qwen_aligned.yaml` 切换；**本机缓存已删（2026-10-05）**，用它会联网下载 ≈7.5 GB |
| 权重来源 | 14B 在 WSL 的 HF 缓存，配置里 `offline: true`，不会联网；官方 4B 已无缓存，对照配置里为 `offline: false` |
| ⚠️ 训练限制 | **4bit 量化权重只能服务，不能直接训 LoRA**。要训练需换 bf16 权重 `huihui-ai/Huihui-Qwen3-14B-abliterated-v2`（约 28 GB，本机未下载）并改走 QLoRA（bitsandbytes 4bit 加载，约 10~12 GB 显存）；或退回 4B bf16（需重新下载 7.5 GB） |
| 训练建议 | **部署哪个基座就在哪个基座上训 LoRA**；换基座后建议重训，别把对齐版上训的适配器直接挂到 abliterated 版上 |
| 代价 | abliteration 通常带来轻微通用能力退化（推理、多语言、格式稳定性），文案任务一般可接受 |
| 合规 | 制作、传播淫秽内容在国内有法律责任，风险由使用者与发布平台承担 |

## 两个目标任务

| | 分类小模型 | 文案生成 |
| --- | --- | --- |
| `run.task` | `classification` | `text_generation` |
| 示例文件 | `exp_cls_bert.yaml` | `exp_gen_qwen.yaml`（+ `exp_gen_qwen_aligned.yaml` 可换基座） |
| 底座模型 | `bert-base-chinese`（约 110M，全参微调可行） | `warshanks/Huihui-Qwen3-14B-abliterated-v2-AWQ`（约 14B，4bit，本机已缓存 9.4 GB，**服务用**） |
| 数据模板 | `template: plain` | `template: chat` + `template_kwargs: { enable_thinking: false }` |
| `data.columns` | `text` + `label` | `prompt` + `response` |
| `evaluate.metrics` | accuracy / precision / recall / f1 | perplexity / rouge-l |
| 预测特有参数 | `predict.classify.*`（`return_probabilities`、`label_names`） | `predict.generate.*`（`max_new_tokens`、`temperature`、`top_p`、`repetition_penalty`） |

换底座模型只改 `model.name`，其余配置不变；只有 `lora.target_modules` 要跟着模型结构改（Qwen 系 `q_proj/k_proj/v_proj/o_proj`，BERT 系 `query/value`）。

## 两条训练线

| 线 | 配置 | 说明 |
| --- | --- | --- |
| 从头训练自己写的模型（RNN / GRU / LSTM / CNN / MLP） | `model.source: local` + `train.init: scratch` | `base.yaml` 的默认值；学原理用 |
| **微调现成模型**（abliterated Qwen3-14B 写文案、BERT 分类） | `model.source: remote` + `train.init: pretrained` + `train.finetune` | 见示例文件；14B 需先按上面「训练限制」换成 bf16 权重 |
| 续训 | `train.init: resume` + `train.resume_from: runs/<run_name>/…` | 中断接着跑 |

`source: remote` 配 `init: scratch` 属于配置错误——下载了权重却随机初始化，加载器应直接报错。

## 模型从哪来：`model.source` 与 `model.path`

| source | `model.name` 含义 | 权重位置 |
| --- | --- | --- |
| `local` | 仓库内自己实现的模型名，如 `rnn`、`gru`、`lstm` | 随机初始化（或 `resume`） |
| `remote` | 模型 id，如 `bert-base-chinese`、`warshanks/Huihui-Qwen3-14B-abliterated-v2-AWQ` | `model.path` 有值 → 读该目录；否则按 `model.download` 取 |

`model.download` 只在 `source: remote` 且 `path` 为空时读取：

| 键 | 含义 |
| --- | --- |
| `hub` | `huggingface` 或 `modelscope` |
| `fallback` | 主源失败时的回退源；不需要就删掉该行 |
| `revision` | 分支、标签或提交 |
| `cache_dir` | 留空 = 用该 hub 的默认缓存（HF 默认 `~/.cache/huggingface/hub`） |
| `offline` | `true` 时只用本地缓存、不联网；缓存缺失直接报错 |

下载不通时的常用办法：设 `HF_ENDPOINT=https://hf-mirror.com` 再下，或先离线下载好、用 `model.path` 指到目录。

## 训练从哪起步：`train.init`

| init | 含义 | 典型用法 |
| --- | --- | --- |
| `scratch` | 随机初始化，从零训练 | `source: local` + 自己写的 RNN / GRU / CNN |
| `pretrained` | **加载 `model` 的权重再训练（微调）** | `source: remote` + Qwen3-14B(abliterated) / BERT + `finetune` |
| `resume` | 从 `train.resume_from` 的检查点继续训练 | 中断后续训 |

`train.finetune` 只在 `init: pretrained` 时读取：

| 键 | 含义 |
| --- | --- |
| `method` | `full`=全参微调；`lora`=低秩适配；`freeze`=冻结主干只训输出层 |
| `lora.r` / `lora.alpha` / `lora.dropout` | LoRA 秩、缩放与丢弃率，仅 `method: lora` 时读取 |
| `lora.target_modules` | 注入 LoRA 的层名：Qwen 用 `q_proj`、`k_proj`、`v_proj`、`o_proj`；BERT 用 `query`、`value`；GPT-2 用 `c_attn`、`c_proj` |
| `merge_on_save` | `true` 时额外导出一份把 LoRA 合并进基座的完整权重，便于交给 vLLM 等推理引擎 |

### LoRA 微调产出什么、怎么用

LoRA 只训练注入到线性层旁的低秩分支（`h = Wx + (α/r)·BAx`，`W` 冻结），所以产物是**独立的适配器文件**，不含基座权重：

```text
runs/gen_abl_14b_01/
├── adapter_config.json
├── adapter_model.safetensors   # 训练产物，通常几十 MB（14B 基座本体：bf16 约 28 GB / 4bit 约 9.4 GB）
├── config.yaml                 # 训练时生效的配置快照
└── merged/                     # 仅 finetune.merge_on_save: true 时导出，含完整权重
```

推理时两者都要给：**基座**来自 `model.source` + `model.name`（或 `model.path`），**适配器**来自 `predict.checkpoint`。指向适配器目录时按"基座 + LoRA"加载，指向 `merged/` 这类完整模型目录时直接加载。

## 部署：本地 vLLM

推理不必走进程内加载。本机服务由 `~/.codex/skills/start-local-services` 统一管理，不依赖 `C:\Workspace` 下的启动脚本。需要启动或检查标准服务时调用 `$start-local-services`。

vLLM 的等价直接命令如下；添加 LoRA 参数时以此为基线：

```bash
source ~/vllm-env/bin/activate
VLLM_USE_V2_MODEL_RUNNER=0 VLLM_USE_FLASHINFER_SAMPLER=0 \
vllm serve warshanks/Huihui-Qwen3-14B-abliterated-v2-AWQ \
  --served-model-name abl-14b \
  --host 127.0.0.1 --port 8000 \
  --gpu-memory-utilization 0.93 --max-model-len 5632 \
  --generation-config vllm \
  --override-generation-config '{"temperature": 0.9, "top_p": 0.95, "top_k": -1, "presence_penalty": 0.6, "frequency_penalty": 0.3, "repetition_penalty": 1.05}' \
  --reasoning-parser qwen3
```

微调产物**不合并、直接挂 LoRA** 时加两个参数（适配器路径按 Windows `C:\...` → WSL `/mnt/c/...` 换算）：

```bash
  --enable-lora --max-lora-rank 16 \
  --lora-modules gen_abl_14b_01=/mnt/c/Workspace/code/model/runs/gen_abl_14b_01
```

对应的推理配置（此时进程内不加载权重，只发 HTTP）：

```yaml
predict:
  backend: vllm
  base_url: http://127.0.0.1:8000/v1
  model: abl-14b             # 服务端 --served-model-name；挂 LoRA 时填 --lora-modules 的名字
  api_key: EMPTY
```

| 事项 | 说明 |
| --- | --- |
| 当前服务 | `warshanks/Huihui-Qwen3-14B-abliterated-v2-AWQ`（4bit 量化，约 9.4 GB），服务名 `abl-14b`，上下文 6144 |
| 显存实测 | 权重 9.44 GiB + 峰值激活 2.48 GiB + CUDA 图 0.67 GiB；**开机可用显存只有 14.8 GiB**，所以 `--gpu-memory-utilization` 上限是 **0.93**（0.94 会被 vLLM 直接拒绝） |
| 与 ComfyUI 冲突 | ComfyUI 跑 MiniMax H3 视频时会占满 16 GB 显存，**不能同时启动 vLLM**；先跑完视频并释放模型缓存 |
| 量化基座不能训练 | AWQ / compressed-tensors 的 4bit 权重只用于服务；要训练需 bf16 权重（14B bf16 显存不够，走 QLoRA + bitsandbytes） |
| WSL 路径换算 | Windows `C:\Workspace\code\model\runs\...` → WSL `/mnt/c/Workspace/code/model/runs/...` |
| 两个环境变量 | 本机基线必须带 `VLLM_USE_V2_MODEL_RUNNER=0`（UVA 不可用）与 `VLLM_USE_FLASHINFER_SAMPLER=0`（缺 nvcc，避开采样器 JIT） |
| 端口 | vLLM 用 **8000**，`Qwen/web/controller.py` 用 **8001**，别混 |
| 合并后部署 | 开 `finetune.merge_on_save: true` 导出完整权重后，直接 `vllm serve <merged 目录>`，不再需要 `--enable-lora` |
| 健康检查 | `curl.exe --max-time 10 -f http://127.0.0.1:8000/health`，`/v1/models` 里能看到 `abl-14b` 才算就绪 |
| 两套环境 | Windows `Qwen\.venv`（训练/客户端）与 WSL `~/vllm-env`（服务端）互相独立，不能混用 |
| 启动纪律 | 沿用该 skill 的约定：只给命令时不启动进程；要代启动时先做只读状态检查，占用端口时不擅自中断别的服务 |

## 字段

### base.yaml

| 键 | 含义 |
| --- | --- |
| `run.task` | 任务类型：`classification`、`text_generation`、`sequence_labeling`…… |
| `run.run_name` | 本次运行名称，输出写入 `runs/<run_name>/` |
| `run.seed` | 随机种子，保证可复现 |
| `run.device` | `cpu` 或 `cuda` |
| `data.path` | 数据集目录或文件 |
| `data.max_len` | 序列截断/补齐长度 |
| `data.batch_size` | 默认批大小，各阶段可覆盖 |
| `data.template` | `plain` 纯文本拼接；`chat` 套用模型对话模板（instruct 模型用） |
| `data.template_kwargs` | 传给对话模板的额外参数，如 Qwen3 的 `{ enable_thinking: false }` |
| `data.system_prompt` | 仅 `template: chat` 时使用 |
| `data.columns.*` | 列映射：`text`/`label`（分类）、`prompt`/`response`（文案生成） |
| `model.source` / `model.name` | 模型来源与标识，见上表 |
| `model.path` | 本地已有的模型目录；填了就只读本地、不联网 |
| `model.params.*` | 本地实现的结构参数；现成模型在实验覆盖里写 `null` 清空 |

### 阶段覆盖文件

| 文件 | 关键字段 |
| --- | --- |
| `train.yaml` | `run.stage: train`；`train.init`、`train.resume_from`、`train.epochs`、`train.batch_size`、`train.grad_accum`、`train.grad_checkpoint`、`train.lr`、`train.optimizer`、`train.log_every`、`train.save_best`、`train.finetune.*` |
| `evaluate.yaml` | `run.stage: evaluate`；`evaluate.batch_size`、`evaluate.metrics`、`evaluate.checkpoint` |
| `predict.yaml` | `run.stage: predict`；`predict.batch_size`、`predict.checkpoint`、`predict.input`、`predict.output`，以及任务特有的 `predict.classify.*` / `predict.generate.*` |

## 约定

- 换任务改 `run.task`、`data.columns` 与 `data.template`；换模型改 `model.source` / `model.name` / `model.path`；换训练方式改 `train.init` 与 `train.finetune`。
- 训练开始时把**生效的最终配置**写一份到 `runs/<run_name>/config.yaml`，评估与推理按它复现，不再依赖命令行参数。
- 机器相关的绝对路径（如 `model.path`）放 `configs/local.yaml`，该文件已被 `.gitignore` 忽略。
- 需要多组实验时再加一层实验覆盖：`-c configs/base.yaml -c configs/train.yaml -c configs/exp_xxx.yaml`。
- 配置里不写密钥、令牌或个人绝对路径。
- 权重、检查点、日志、预测结果与下载缓存都不提交到 Git。
