with open("core/prompt_advisor.py", "r", encoding="utf-8") as f:
    text = f.read()

text = text.replace("h.folio_no", "h.folio")

with open("core/prompt_advisor.py", "w", encoding="utf-8") as f:
    f.write(text)

print("SUCCESS: Fixed h.folio_no in core/prompt_advisor.py")

