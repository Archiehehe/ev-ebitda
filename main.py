import streamlit as st
import pandas as pd
import yfinance as yf

# --- Load base company list ---
companies = pd.read_csv("companies.csv")

# --- Cache financial data to make app fast ---
@st.cache_data
def get_financials(ticker):
    try:
        stock = yf.Ticker(ticker)
        info = stock.info
        return {
            "Market Cap": info.get("marketCap", None),
            "Company EV/EBITDA": info.get("enterpriseToEbitda", None),
        }
    except:
        return {"Market Cap": None, "Company EV/EBITDA": None}

# --- Fetch sector EV/EBITDA ---
url = "https://pages.stern.nyu.edu/~adamodar/New_Home_Page/datafile/vebitda.html"
sector_table = pd.read_html(url, header=0)[0]  # use first row as header
sector_table.columns = [str(c).strip() for c in sector_table.columns]
sector_table = sector_table.rename(columns={"Industry Name": "Sector", "EV/EBITDA": "Sector EV/EBITDA"})

# --- Streamlit UI ---
st.title("📊 Company vs Sector EV/EBITDA Explorer")

sector_choice = st.sidebar.selectbox("Select Sector", ["All"] + sorted(companies["Sector"].dropna().unique().tolist()))
cap_choice = st.sidebar.radio("Market Cap Filter", [
    "Show All Companies",
    "Small Cap (<$2B)",
    "Mid Cap ($2B–$10B)",
    "Large Cap ($10B–$50B)",
    "Mega Cap ($50B–$200B)",
    "Ultra Cap (>$200B)",
])

# --- Apply sector filter first (reduces API calls) ---
if sector_choice != "All":
    filtered = companies[companies["Sector"] == sector_choice].copy()
else:
    filtered = companies.copy()

# --- Fetch financials only for filtered tickers ---
financials = pd.DataFrame([get_financials(tkr) for tkr in filtered["Ticker"]])
filtered = pd.concat([filtered.reset_index(drop=True), financials], axis=1)

# --- Filter Market Cap categories ---
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

# --- Merge with sector EV/EBITDA ---
filtered = filtered.merge(sector_table[["Sector", "Sector EV/EBITDA"]], on="Sector", how="left")

# --- Formatting helpers ---
def format_mcap(mcap):
    if pd.isna(mcap):
        return "N/A"
    if mcap >= 1_000_000_000_000:
        return f"{mcap/1_000_000_000_000:.2f}T"
    elif mcap >= 1_000_000_000:
        return f"{mcap/1_000_000_000:.2f}B"
    elif mcap >= 1_000_000:
        return f"{mcap/1_000_000:.2f}M"
    else:
        return str(mcap)

def format_multiple(val):
    if pd.isna(val):
        return "N/A"
    return f"{val:.1f}×"

filtered["Market Cap"] = filtered["Market Cap"].apply(format_mcap)
filtered["Company EV/EBITDA"] = filtered["Company EV/EBITDA"].apply(format_multiple)
filtered["Sector EV/EBITDA"] = filtered["Sector EV/EBITDA"].apply(format_multiple)

# --- Display table ---
st.data_editor(
    filtered[["Company Name", "Ticker", "Sector", "Market Cap", "Company EV/EBITDA", "Sector EV/EBITDA"]],
    use_container_width=True,
    hide_index=True,
    disabled=True
)

# --- Download button ---
st.download_button(
    "⬇️ Download CSV",
    filtered.to_csv(index=False),
    "company_multiples.csv",
    "text/csv"
)
