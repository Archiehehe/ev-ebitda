import re
import streamlit as st
import pandas as pd
import yfinance as yf
from companies_data_cleaned import companies_list   # <-- use the cleaned file

st.set_page_config(page_title="EV/EBITDA Explorer", layout="wide")

# -----------------------------
# Load company list
# -----------------------------
companies = pd.DataFrame(companies_list)[["Company Name", "Ticker", "Sector"]].dropna()
companies["Company Name"] = companies["Company Name"].str.replace(r"\s*\([^)]+\)$", "", regex=True)

# -----------------------------
# Damodaran industries
# -----------------------------
@st.cache_data
def damodaran_industries():
    url = "https://pages.stern.nyu.edu/~adamodar/New_Home_Page/datafile/vebitda.html"
    df = pd.read_html(url, header=0)[0]
    df.columns = [str(c).strip() for c in df.columns]
    ind_col = df.columns[0]
    ev_cols = [c for c in df.columns if "All firms" in c]
    ev_col = ev_cols[-1] if ev_cols else df.columns[-1]
    out = df[[ind_col, ev_col]].rename(columns={ind_col: "Industry", ev_col: "Sector EV/EBITDA"})
    out["Sector EV/EBITDA"] = pd.to_numeric(out["Sector EV/EBITDA"], errors="coerce")
    out = out[~out["Industry"].str.lower().str.contains("total market")]
    return out.dropna().reset_index(drop=True)

damo = damodaran_industries()
INDUSTRIES = damo["Industry"].tolist()

# -----------------------------
# Helpers
# -----------------------------
def tokens(label: str):
    txt = label.lower().replace("&", " ").replace("/", " ").replace("(", " ").replace(")", " ")
    return [w for w in txt.split() if len(w) > 2]

def fmt_mcap(x):
    if pd.isna(x): return "N/A"
    x = float(x)
    if x >= 1e12: return f"{x/1e12:.2f}T"
    if x >= 1e9: return f"{x/1e9:.2f}B"
    if x >= 1e6: return f"{x/1e6:.2f}M"
    return f"{x:.0f}"

def fmt_mult(x):
    return "N/A" if pd.isna(x) else f"{float(x):.1f}×"

# -----------------------------
# Streamlit UI
# -----------------------------
st.title("📊 Company vs Industry EV/EBITDA Explorer")

industry_choice = st.sidebar.selectbox("Select Industry", INDUSTRIES)
cap_choice = st.sidebar.radio(
    "Market Cap Filter",
    ["Show All Companies","Small Cap (<$2B)","Mid Cap ($2B–$10B)",
     "Large Cap ($10B–$50B)","Mega Cap ($50B–$200B)","Ultra Cap (>$200B)"],
    index=5
)

industry_multiple = float(damo.loc[damo["Industry"] == industry_choice, "Sector EV/EBITDA"].iloc[0])

if st.button("Fetch Data"):
    # --- Filter companies by industry tokens ---
    needles = tokens(industry_choice)
    mask = pd.Series(False, index=companies.index)
    for w in needles:
        mask |= companies["Sector"].str.lower().str.contains(w, na=False)
        mask |= companies["Company Name"].str.lower().str.contains(w, na=False)
    subset = companies[mask]

    if subset.empty:
        st.warning("No companies matched this industry.")
        st.stop()

    # --- Batch fetch Yahoo finance ---
    data = yf.Tickers(" ".join(subset["Ticker"].tolist()))
    rows = []
    for t in subset["Ticker"]:
        try:
            info = data.tickers[t].info
            rows.append({
                "Ticker": t,
                "Market Cap": info.get("marketCap"),
                "Company EV/EBITDA": info.get("enterpriseToEbitda")
            })
        except:
            continue
    fin = pd.DataFrame(rows)

    merged = subset.merge(fin, on="Ticker", how="left")

    # --- Market cap filter ---
    mc = merged["Market Cap"]
    if cap_choice == "Small Cap (<$2B)":
        merged = merged[mc < 2_000_000_000]
    elif cap_choice == "Mid Cap ($2B–$10B)":
        merged = merged[(mc >= 2_000_000_000) & (mc < 10_000_000_000)]
    elif cap_choice == "Large Cap ($10B–$50B)":
        merged = merged[(mc >= 10_000_000_000) & (mc < 50_000_000_000)]
    elif cap_choice == "Mega Cap ($50B–$200B)":
        merged = merged[(mc >= 50_000_000_000) & (mc < 200_000_000_000)]
    elif cap_choice == "Ultra Cap (>$200B)":
        merged = merged[mc >= 200_000_000_000]

    # --- Sort and format ---
    merged = merged.sort_values("Market Cap", ascending=False)
    merged["Market Cap"] = merged["Market Cap"].apply(fmt_mcap)
    merged["Company EV/EBITDA"] = merged["Company EV/EBITDA"].apply(fmt_mult)
    merged["Sector EV/EBITDA"] = fmt_mult(industry_multiple)

    st.data_editor(
        merged[["Company Name","Ticker","Sector","Market Cap","Company EV/EBITDA","Sector EV/EBITDA"]],
        use_container_width=True, hide_index=True, disabled=True
    )

    st.download_button(
        "⬇️ Download CSV",
        merged.to_csv(index=False),
        "company_multiples.csv",
        "text/csv"
    )
