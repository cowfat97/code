import logging
from pathlib import Path
from huggingface_hub import snapshot_download as hf_snapshot_download
from modelscope import snapshot_download as ms_snapshot_download

logging.getLogger("transformers").setLevel(logging.INFO)

BASE_DIR = "/Users/haoxinlei/Desktop/开发/学习/envs"
MODELS_DIR = f"{BASE_DIR}/models"

MODEL_IDS = [
    "BAAI/bge-m3",
    "BAAI/bge-reranker-v2-m3",
]


def _pull_from_hf(model_id: str, save_dir: str) -> bool:
    """HuggingFace 拉取，成功返回 True，失败返回 False"""
    hf_snapshot_download(model_id, local_dir=save_dir)
    return True


def _pull_from_ms(model_id: str, save_dir: str) -> bool:
    """ModelScope 拉取，成功返回 True，失败返回 False"""
    ms_snapshot_download(model_id, cache_dir=save_dir)
    return True


def pull_model(model_id: str) -> None:
    """拉取模型，优先 HuggingFace，不通则 ModelScope"""
    save_dir = f"{MODELS_DIR}/{model_id}"
    if Path(save_dir).exists() and list(Path(save_dir).iterdir()):
        print(f"已存在，跳过: {save_dir}")
        return

    print(f"尝试 HuggingFace: {model_id}")
    try:
        _pull_from_hf(model_id, save_dir)
        print(f"模型已保存(HF): {save_dir}")
        return
    except Exception as e:
        print(f"HuggingFace 失败: {e}")

    print(f"回退 ModelScope: {model_id}")
    _pull_from_ms(model_id, save_dir)
    print(f"模型已保存(MS): {save_dir}")


if __name__ == "__main__":
    for model_id in MODEL_IDS:
        pull_model(model_id)
