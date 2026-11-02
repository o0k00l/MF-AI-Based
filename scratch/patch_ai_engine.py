with open("core/ai_engine.py", "r", encoding="utf-8") as f:
    text = f.read()

# Replace Requesty temperature
text = text.replace(
    'temperature=0.2,\n                    max_tokens=4000,',
    'temperature=0.0,\n                    seed=42,\n                    max_tokens=4000,'
)

# Replace OpenRouter temperature
text = text.replace(
    'temperature=0.2,\n                max_tokens=4000,',
    'temperature=0.0,\n                seed=42,\n                max_tokens=4000,'
)

# Replace Gemini temperature
text = text.replace(
    'cfg = {"temperature": 0.2, "max_output_tokens": 8192}',
    'cfg = {"temperature": 0.0, "seed": 42, "max_output_tokens": 8192}'
)

with open("core/ai_engine.py", "w", encoding="utf-8") as f:
    f.write(text)

print("Successfully locked temperature=0.0 and seed=42 across all LLM providers in core/ai_engine.py")

