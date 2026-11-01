with open("ui/app.py", "r", encoding="utf-8") as f:
    content = f.read()

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

if "4 Essential Tabs" in content and "tab_switch, tab_fresh, tab_copilot, tab_upload = st.tabs" in content:
    # Replace the old text with new text
    content = content.replace(
        """# 4 Essential Tabs
tab_switch, tab_fresh, tab_copilot, tab_upload = st.tabs([
    "📋 Switch to Direct (Save ₹39k)",
    "🎯 Fresh Money (SIP & Lumpsum)",
    "💬 Ask Copilot & Reports",
    "📤 Upload Statement",
])""",
        """# 5 Essential Tabs
tab_switch, tab_fresh, tab_copilot, tab_stress, tab_upload = st.tabs([
    "📋 Switch to Direct (Save ₹39k)",
    "🎯 Fresh Money (SIP & Lumpsum)",
    "💬 Ask Copilot & Reports",
    "⚡ Stress Test",
    "📤 Upload Statement",
])"""
    )
    with open("ui/app.py", "w", encoding="utf-8") as f:
        f.write(content)
    print("SUCCESS: Tab updated")
else:
    print("OLD TEXT NOT FOUND")