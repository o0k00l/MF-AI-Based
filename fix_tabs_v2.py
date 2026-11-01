import pathlib

content = pathlib.Path("ui/app.py").read_text(encoding="utf-8")

old = """# 4 Essential Tabs
tab_switch, tab_fresh, tab_copilot, tab_upload = st.tabs([
    "📋 Switch to Direct (Save ₹39k)",
    "🎯 Fresh Money (SIP & Lumpsum)",
    "💬 Ask Copilot & Reports",
    "📤 Upload Statement",
])"""

new = """# 5 Essential Tabs
tab_switch, tab_fresh, tab_copilot, tab_stress, tab_upload = st.tabs([
    "📋 Switch to Direct (Save ₹39k)",
    "🎯 Fresh Money (SIP & Lumpsum)",
    "💬 Ask Copilot & Reports",
    "⚡ Stress Test",
    "📤 Upload Statement",
])"""

# The old text has slight whitespace differences - let's find the exact boundaries
idx = content.find("4 Essential Tabs")
if idx >= 0:
    # Find the closing bracket of st.tabs()
    end_idx = content.find("])", idx)
    if end_idx > idx:
        end_idx += 2  # include the ])
        content = content[:idx] + new + content[end_idx:]
        pathlib.Path("ui/app.py").write_text(content, encoding="utf-8")
        print("SUCCESS: Tab updated via slice")
    else:
        print("Could not find closing bracket")
else:
    print("OLD TEXT NOT FOUND")

pathlib.Path("fix_tabs.py").write_text("SUCCESS" if "5 Essential Tabs" in content else "FAILED")