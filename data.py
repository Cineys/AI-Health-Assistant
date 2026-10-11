import requests

url = "https://huggingface.co/datasets/FreedomIntelligence/huatuo26M-testdatasets/resolve/main/test_datasets.jsonl"
r = requests.get(url)

with open("huatuo_sample.jsonl", "wb") as f:
    f.write(r.content)

print("下载完成 ➤ huatuo_sample.jsonl")