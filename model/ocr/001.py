# 基于 paddle Ocr 识别邮件

from paddleocr import PaddleOCR
from transformers import AutoTokenizer, AutoModelForSequenceClassification
import torch

# ── 1. OCR ──
ocr = PaddleOCR(
    use_doc_orientation_classify=False,
    use_doc_unwarping=False,
    use_textline_orientation=False,
)
result = ocr.predict("/Users/haoxinlei/Desktop/开发/学习/notes/Pic/movie/1291543.jpg")
ocr_text = " ".join(result[0]["rec_texts"])

# ── 2. 拼接 ──
email_body = "用户投诉信用卡扣费异常，要求退回手续费"  # 实际场景从 .eml 提取
full_text = email_body + " [附件] " + ocr_text

# ── 3. BERT 分类 ──
model_name = "/Users/haoxinlei/Desktop/开发/学习/envs/models/bert-base-chinese"
tokenizer = AutoTokenizer.from_pretrained(model_name)
model = AutoModelForSequenceClassification.from_pretrained(model_name, num_labels=15)

inputs = tokenizer(
    full_text,
    max_length=512,
    truncation=True,
    padding="max_length",
    return_tensors="pt",
)

with torch.no_grad():
    logits = model(**inputs).logits
    probs = torch.softmax(logits, dim=-1)
    pred = probs.argmax(dim=-1).item()
    conf = probs.max().item()

print(f"\n拼接文本: {full_text}")
print(f"预测类别: {pred}, 置信度: {conf:.4f}")
