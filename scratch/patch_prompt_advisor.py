with open("core/prompt_advisor.py", "r", encoding="utf-8") as f:
    text = f.read()

with open("scratch/new_dossier.py", "r", encoding="utf-8") as f:
    new_func = f.read()

# Locate def _build_dynamic_selection_dossier up to return dossier
start_marker = "def _build_dynamic_selection_dossier(facts: FiduciaryFactsPayload) -> str:"
end_marker = "return dossier"

assert start_marker in text, "start_marker not found"
assert end_marker in text, "end_marker not found"

start_idx = text.find(start_marker)
end_idx = text.find(end_marker) + len(end_marker)

new_text = text[:start_idx] + new_func + text[end_idx:]

with open("core/prompt_advisor.py", "w", encoding="utf-8") as f:
    f.write(new_text)

print("Successfully replaced _build_dynamic_selection_dossier in core/prompt_advisor.py")

