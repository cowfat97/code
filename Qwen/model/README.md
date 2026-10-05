# Model Lab

一条流水线，从训练到推理：**train → evaluate → predict**。顶层只按流水线阶段划分，不按任务、也不按模型分目录；具体跑哪个任务、用哪个模型，由 `configs/` 里的配置决定。

## 目录说明

| 目录 | 用途 |
| --- | --- |
| `train/` | 训练阶段入口 |
| `evaluate/` | 评估阶段入口 |
| `predict/` | 推理阶段入口 |
| `configs/` | 每个实验一份配置：任务、模型、数据、超参数 |
| `datasets/` | 数据读取与预处理；大数据集不提交到 Git |
| `common/` | 三个阶段共用的代码：数据加载、模型定义、训练循环、指标、日志、随机种子、注册表 |

## 配置决定任务

三个阶段是同一套代码，切换任务或模型只改配置、不改代码：

```yaml
# configs/classification_rnn.yaml
task: classification     # 任务：分类、回归、序列标注……
model: rnn               # 模型结构：mlp、cnn、rnn、lstm、gru、seq2seq、transformer
hidden_size: 128
num_layers: 2
epochs: 20
batch_size: 32
```

## 约定

- 优先使用小数据集和小模型验证完整流程。
- `train/`、`evaluate/`、`predict/` 共用同一套数据处理与模型定义，不复制代码；共用逻辑放 `common/`。
- 新增任务或模型时不新建顶层目录，共用实现放 `common/`。
- 配置中不写入密钥或个人凭证。
- 模型权重、检查点、日志和大型数据文件不应直接提交到 Git。
