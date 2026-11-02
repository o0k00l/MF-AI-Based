with open("app.py", "r", encoding="utf-8") as f:
    text = f.read()

target = """# Load Verified Ground Truth Facts
@st.cache_data(ttl=300)
def load_portfolio_facts():
    cas, metrics, config, aliases, outputs = get_default_paths()
    facts = aggregate_fiduciary_facts(cas, metrics, config, aliases)
    return facts

try:
    facts = load_portfolio_facts()
except Exception as e:
    st.error(f"Error loading portfolio data: {e}")
    st.stop()

client_name = facts.client_name
f1 = facts.fee_bleed
tot_val = facts.total_portfolio_value_inr
tot_inv = facts.total_invested_value_inr
tot_gain = facts.total_unrealized_gain_inr

# Page Configuration
st.set_page_config(
    page_title=f"Wealth Copilot | {client_name}",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="collapsed"
)"""

replacement = """# Page Configuration must be first Streamlit command
st.set_page_config(
    page_title="Wealth Copilot | Fiduciary Portfolio Engine",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded"
)

from advisor import discover_client_portfolios

# Discover Available Portfolios
available_ports = discover_client_portfolios(ROOT)
if not available_ports:
    available_ports = {"lalit_portfolio": ROOT / "data" / "lalit_portfolio"}

with st.sidebar:
    st.markdown("### 💼 Portfolio Selection")
    client_list = list(available_ports.keys())
    default_idx = client_list.index("lalit_portfolio") if "lalit_portfolio" in client_list else 0
    selected_client_key = st.selectbox(
        "Select Client Account:",
        options=client_list,
        index=default_idx
    )

# Load Verified Ground Truth Facts
@st.cache_data(ttl=300)
def load_portfolio_facts(client_target: str = "lalit_portfolio"):
    cas, metrics, config, aliases, outputs = get_default_paths(client_target)
    facts = aggregate_fiduciary_facts(cas, metrics, config, aliases)
    return facts

try:
    facts = load_portfolio_facts(selected_client_key)
except Exception as e:
    st.error(f"Error loading portfolio data for '{selected_client_key}': {e}")
    st.stop()

client_name = facts.client_name
f1 = facts.fee_bleed
tot_val = facts.total_portfolio_value_inr
tot_inv = facts.total_invested_value_inr
tot_gain = facts.total_unrealized_gain_inr"""

assert target in text, "Target not found in app.py"
text = text.replace(target, replacement, 1)

with open("app.py", "w", encoding="utf-8") as f:
    f.write(text)

with open("ui/app.py", "w", encoding="utf-8") as f:
    f.write(text)

print("Successfully updated app.py and ui/app.py with Multi-Client selector")

