import streamlit as st
import pandas as pd
import yfinance as yf
from companies_data import companies_list   # preprocessed ~7k US + ADRs

# ---------- Load company dataset ----------
companies = pd.DataFrame(companies_list)
companies = companies[["Company Name", "Ticker", "Sector"]]
companies["Company Name"] = companies["Company Name"].str.replace(r"\s*\([^)]+\)$", "", regex=True)

# ---------- Yahoo Finance (cached) ----------
@st.cache_data(show_spinner=False)
def get_financials(ticker: str):
    try:
        info = yf.Ticker(ticker).info
        return {
            "Ticker": ticker,
            "Market Cap": info.get("marketCap"),
            "Company EV/EBITDA": info.get("enterpriseToEbitda"),
        }
    except Exception:
        return {"Ticker": ticker, "Market Cap": None, "Company EV/EBITDA": None}

# ---------- Damodaran industries ----------
@st.cache_data(show_spinner=False)
def load_damodaran_industries():
    url = "https://pages.stern.nyu.edu/~adamodar/New_Home_Page/datafile/vebitda.html"
    df = pd.read_html(url, header=0)[0]
    df.columns = [str(c).strip() for c in df.columns]
    industry_col = df.columns[0]
    ev_cols = [c for c in df.columns if "All firms" in c]
    ev_col = ev_cols[-1] if ev_cols else df.columns[-1]
    out = df[[industry_col, ev_col]].rename(
        columns={industry_col: "Industry", ev_col: "Sector EV/EBITDA"}
    )
    out["Sector EV/EBITDA"] = pd.to_numeric(out["Sector EV/EBITDA"], errors="coerce")
    return out.dropna()

damodaran_df = load_damodaran_industries()

# ---------- Pre-generate industry → companies lookup ----------
def generate_keywords(industry: str):
    """Split industry string into useful lowercase keyword fragments."""
    text = industry.lower()
    text = text.replace("(", " ").replace(")", " ").replace("&", "and")
    return [w for w in text.split() if len(w) > 2]

industry_keywords = {
    row["Industry"]: generate_keywords(row["Industry"])
    for _, row in damodaran_df.iterrows()
}

industry_company_map = {}
for industry, keywords in industry_keywords.items():
    mask = pd.Series(False, index=companies.index)
    for k in keywords:
        mask |= companies["Sector"].str.lower().str.contains(k, na=False)
        mask |= companies["Company Name"].str.lower().str.contains(k, na=False)
    industry_company_map[industry] = companies[mask]

# ---------- UI ----------
st.set_page_config(page_title="EV/EBITDA Explorer", layout="wide")
st.title("📊 Company vs Industry EV/EBITDA Explorer")

industry_choice = st.sidebar.selectbox("Select Industry", damodaran_df["Industry"].tolist())
cap_choice = st.sidebar.radio(
    "Market Cap Filter",
    ["Show All Companies", "Small Cap (<$2B)", "Mid Cap ($2B–$10B)",
     "Large Cap ($10B–$50B)", "Mega Cap ($50B–$200B)", "Ultra Cap (>$200B)"],
    index=3,
)

# Damodaran multiple
industry_multiple = damodaran_df.loc[
    damodaran_df["Industry"] == industry_choice, "Sector EV/EBITDA"
].iloc[0]

# Pre-matched companies for this industry
filtered = industry_company_map.get(industry_choice, pd.DataFrame())

# ---------- Fetch company data ----------
if st.button("Fetch Data"):
    # Limit for performance
    tickers = filtered["Ticker"].dropna().unique().tolist()[:800]
    rows = [get_financials(tkr) for tkr in tickers]
    fin = pd.DataFrame(rows)
    merged = filtered.merge(fin, on="Ticker", how="left")

    # Market cap filter
    if cap_choice == "Small Cap (<$2B)":
        merged = merged[merged["Market Cap"] < 2_000_000_000]
    elif cap_choice == "Mid Cap ($2B–$10B)":
        merged = merged[(merged["Market Cap"] >= 2_000_000_000) & (merged["Market Cap"] < 10_000_000_000)]
    elif cap_choice == "Large Cap ($10B–$50B)":
        merged = merged[(merged["Market Cap"] >= 10_000_000_000) & (merged["Market Cap"] < 50_000_000_000)]
    elif cap_choice == "Mega Cap ($50B–$200B)":
        merged = merged[(merged["Market Cap"] >= 50_000_000_000) & (merged["Market Cap"] < 200_000_000_000)]
    elif cap_choice == "Ultra Cap (>$200B)":
        merged = merged[merged["Market Cap"] >= 200_000_000_000]

    # ---------- Formatting ----------
    def fmt_mcap(x):
        if pd.isna(x): return "N/A"
        if x >= 1e12: return f"{x/1e12:.2f}T"
        if x >= 1e9:  return f"{x/1e9:.2f}B"
        if x >= 1e6:  return f"{x/1e6:.2f}M"
        return f"{x:.0f}"

    def fmt_mult(x):
        return "N/A" if pd.isna(x) else f"{float(x):.1f}×"

    merged["Market Cap"] = merged["Market Cap"].apply(fmt_mcap)
    merged["Company EV/EBITDA"] = merged["Company EV/EBITDA"].apply(fmt_mult)
    merged["Sector EV/EBITDA"] = fmt_mult(industry_multiple)

    # Sort by Market Cap (descending)
    def mcap_sort_key(val):
        try:
            if isinstance(val, str) and val.endswith("T"): return float(val[:-1]) * 1e12
            if isinstance(val, str) and val.endswith("B"): return float(val[:-1]) * 1e9
            if isinstance(val, str) and val.endswith("M"): return float(val[:-1]) * 1e6
            return float(val)
        except: return -1.0

    merged = merged.sort_values(by="Market Cap", key=lambda s: s.map(mcap_sort_key), ascending=False)

    # ---------- Show Table ----------
    st.data_editor(
        merged[["Company Name", "Ticker", "Sector", "Market Cap", "Company EV/EBITDA", "Sector EV/EBITDA"]],
        use_container_width=True, hide_index=True, disabled=True
    )

    # ---------- Download ----------
    st.download_button(
        "⬇️ Download CSV",
        merged.to_csv(index=False),
        "company_multiples.csv",
        "text/csv",
    )
else:
    st.info("👆 Select an industry and click 'Fetch Data' to load results.")
