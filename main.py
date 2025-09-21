import streamlit as st
import pandas as pd
import yfinance as yf
from companies_data import companies_list   # <-- import the embedded dataset

# --- Load company list from embedded Python file ---
companies = pd.DataFrame(companies_list)

# --- Cache Yahoo Finance lookups ---
@st.cache_data
def get_financials(ticker):
    try:
        stock = yf.Ticker(ticker)
        info = stock.info
        return {
            "Market Cap": info.get("marketCap"),
            "Company EV/EBITDA": info.get("enterpriseToEbitda"),
        }
    except:
        return {"Market Cap": None, "Company EV/EBITDA": None}

# --- Fetch Damodaran sector EV/EBITDA ---
url = "https://pages.stern.nyu.edu/~adamodar/New_Home_Page/datafile/vebitda.html"
sector_table = pd.read_html(url, header=0)[0]

# Normalize columns
sector_table.columns = [str(c).strip() for c in sector_table.columns]

# Take first column = Sector, last column = EV/EBITDA (All Firms)
sector_table = sector_table.iloc[:, [0, -1]].rename(
    columns={sector_table.columns[0]: "Sector", sector_table.columns[-1]: "Sector EV/EBITDA"}
)

# --- Streamlit UI ---
st.title("📊 Company vs Sector EV/EBITDA Explorer")

sector_choice = st.sidebar.selectbox("Select Sector", ["All"] + sorted(companies["Sector"].dropna().unique()))
cap_choice = st.sidebar.radio("Market Cap Filter", [
    "Show All Companies",
    "Small Cap (<$2B)",
    "Mid Cap ($2B–$10B)",
    "Large Cap ($10B–$50B)",
    "Mega Cap ($50B–$200B)",
    "Ultra Cap (>$200B)",
], index=3)

# Prevent loading full dataset
if sector_choice == "All" and cap_choice == "Show All Companies":
    st.warning("⚠️ Please select a sector or market cap filter. Loading all 7,000+ companies is too large.")
    st.stop()

# Apply filters
filtered = companies.copy()
if sector_choice != "All":
    filtered = filtered[filtered["Sector"] == sector_choice]

# Limit for performance
if len(filtered) > 200:
    st.warning(f"⚠️ Too many companies selected ({len(filtered)}). Showing first 200.")
    filtered = filtered.head(200)

# --- Fetch data only when button is pressed ---
if st.button("Fetch Data"):
    financials = pd.DataFrame([get_financials(tkr) for tkr in filtered["Ticker"]])
    filtered = pd.concat([filtered.reset_index(drop=True), financials], axis=1)

    # Apply Market Cap filter
    if cap_choice == "Small Cap (<$2B)":
        filtered = filtered[filtered["Market Cap"] < 2_000_000_000]
    elif cap_choice == "Mid Cap ($2B–$10B)":
        filtered = filtered[(filtered["Market Cap"] >= 2_000_000_000) & (filtered["Market Cap"] < 10_000_000_000)]
    elif cap_choice == "Large Cap ($10B–$50B)":
        filtered = filtered[(filtered["Market Cap"] >= 10_000_000_000) & (filtered["Market Cap"] < 50_000_000_000)]
    elif cap_choice == "Mega Cap ($50B–$200B)":
        filtered = filtered[(filtered["Market Cap"] >= 50_000_000_000) & (filtered["Market Cap"] < 200_000_000_000)]
    elif cap_choice == "Ultra Cap (>$200B)":
        filtered = filtered[filtered["Market Cap"] >= 200_000_000_000]

    # Merge with sector multiples
    filtered = filtered.merge(sector_table, on="Sector", how="left")

    # Formatting helpers
    def fmt_mcap(mcap):
        if pd.isna(mcap): return "N/A"
        if mcap >= 1e12: return f"{mcap/1e12:.2f}T"
        if mcap >= 1e9: return f"{mcap/1e9:.2f}B"
        if mcap >= 1e6: return f"{mcap/1e6:.2f}M"
        return str(mcap)

    def fmt_mult(x):
        return "N/A" if pd.isna(x) else f"{x:.1f}×"

    filtered["Market Cap"] = filtered["Market Cap"].apply(fmt_mcap)
    filtered["Company EV/EBITDA"] = filtered["Company EV/EBITDA"].apply(fmt_mult)
    filtered["Sector EV/EBITDA"] = filtered["Sector EV/EBITDA"].apply(fmt_mult)

    # Display table
    st.data_editor(
        filtered[["Company Name", "Ticker", "Sector", "Market Cap", "Company EV/EBITDA", "Sector EV/EBITDA"]],
        use_container_width=True, hide_index=True, disabled=True
    )

    # Download option
    st.download_button("⬇️ Download CSV", filtered.to_csv(index=False), "company_multiples.csv", "text/csv")
else:
    st.info("👆 Select filters and click 'Fetch Data' to load results.")
