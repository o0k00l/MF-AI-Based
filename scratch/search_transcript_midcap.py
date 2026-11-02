import json

with open("C:/Users/l9999/.gemini/antigravity/brain/35b1fa8d-0f59-45e7-a21f-f4d24f3e78c8/.system_generated/logs/transcript.jsonl", "r", encoding="utf-8") as f:
    for line in f:
        obj = json.loads(line)
        content = obj.get("content", "")
        if "Motilal" in content and ("HDFC Mid" in content or "mid-cap" in content.lower()):
            source = obj.get("source")
            idx = obj.get("step_index")
            print(f"Step {idx} ({source}): {content[:200]}...\n")

