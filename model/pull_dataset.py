from pathlib import Path
from datasets import load_dataset

BASE_DIR = "/Users/haoxinlei/Desktop/开发/学习/envs"
DATASETS_DIR = f"{BASE_DIR}/dataSet"

# 需要拉取的数据集列表
DATASETS = [
    # "embedding-data/QQP",  # 示例
]


def pull_dataset(dataset_id: str, **kwargs) -> None:
    """从 HuggingFace 拉取数据集到本地"""
    save_dir = f"{DATASETS_DIR}/{dataset_id}"
    if Path(save_dir).exists() and list(Path(save_dir).iterdir()):
        print(f"已存在，跳过: {save_dir}")
        return

    dataset = load_dataset(dataset_id, **kwargs)
    dataset.save_to_disk(save_dir)
    print(f"数据集已保存: {save_dir}")


def pull_all() -> None:
    """拉取 DATASETS 中所有数据集"""
    for dataset_id in DATASETS:
        print(f"\n--- {dataset_id} ---")
        pull_dataset(dataset_id)


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        pull_all()
    else:
        pull_dataset(sys.argv[1])
