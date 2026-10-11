from datasets import load_dataset
import pandas as pd

ds = load_dataset("FreedomIntelligence/huatuo_encyclopedia_qa", split="train")

def is_valid_text_answer(example):
    if not example["answers"]:
        return False
    
    first = str(example["answers"][0]).strip().lower()
    
    # 过滤URL
    if first.startswith("http://") or first.startswith("https://"):
        return False
    
    # 过滤太短或空内容
    if len(first) < 2:
        return False
    
    return True

filtered_ds = ds.filter(is_valid_text_answer)

print("原始数据量：", len(ds))
print("过滤后数据量：", len(filtered_ds))

# 随机抽 500 条
subset = filtered_ds.shuffle(seed=42).select(range(min(500, len(filtered_ds))))

# 保存
df = pd.DataFrame(subset)
df.to_json("huatuo_text_test_subset.jsonl", orient="records", force_ascii=False, lines=True)

print("已保存为 huatuo_text_test_subset.jsonl")
print(df.head())