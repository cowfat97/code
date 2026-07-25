from datasets import load_from_disk
from transformers import AutoModelForSequenceClassification, AutoTokenizer, Trainer, TrainingArguments, DataCollatorWithPadding
import numpy as np

MODEL = "/Users/haoxinlei/Desktop/开发/学习/envs/models/bert-base-chinese"
DATA = "/Users/haoxinlei/Desktop/开发/学习/envs/dataSet/fancyzhx/ag_news"
OUT = "/Users/haoxinlei/Desktop/开发/学习/envs/finetuned/bert-base-chinese-ag_news"

tokenizer = AutoTokenizer.from_pretrained(MODEL)
model = AutoModelForSequenceClassification.from_pretrained(MODEL, num_labels=4)

ds = load_from_disk(DATA)
train_ds = ds["train"].map(lambda x: tokenizer(x["text"], max_length=512, truncation=True), batched=True)
eval_ds = ds["test"].map(lambda x: tokenizer(x["text"], max_length=512, truncation=True), batched=True)

trainer = Trainer(
    model=model,
    args=TrainingArguments(OUT, num_train_epochs=3, per_device_train_batch_size=16, per_device_eval_batch_size=16, learning_rate=2e-5, logging_steps=200, eval_strategy="epoch", save_strategy="epoch", save_total_limit=1, load_best_model_at_end=True, metric_for_best_model="accuracy", report_to="none"),
    train_dataset=train_ds,
    eval_dataset=eval_ds,
    data_collator=DataCollatorWithPadding(tokenizer),
    compute_metrics=lambda p: {"accuracy": (np.argmax(p[0], -1) == p[1]).mean()},
)

trainer.train()
trainer.save_model(OUT)
tokenizer.save_pretrained(OUT)
