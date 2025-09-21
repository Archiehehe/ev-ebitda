import streamlit as st
import pandas as pd
import yfinance as yf
from companies_data import companies_list  # your ~7k US + ADRs

st.set_page_config(page_title="EV/EBITDA Explorer", layout="wide")

# -----------------------------
# Load companies from embedded list
# -----------------------------
companies = pd.DataFrame(companies_list)[["Company Name", "Ticker", "Sector"]].dropna()
companies["Company Name"] = companies["Company Name"].str.replace(r"\s*\([^)]+\)$", "", regex=True)
companies["lc_name"] = companies["Company Name"].str.lower()
companies["lc_sector"] = companies["Sector"].str.lower()

# -----------------------------
# YF helpers (cached, robust)
# -----------------------------
@st.cache_data(show_spinner=False)
def fetch_financials(ticker: str):
    """Best-effort Market Cap + EV/EBITDA + Industry using multiple fallbacks."""
    try:
        t = yf.Ticker(ticker)
        # fast_info is quicker & often reliable for cap
        cap = getattr(t, "fast_info", None)
        mcap = getattr(cap, "market_cap", None) if cap else None
        info = {}
        try:
            info = t.info or {}
        except Exception:
            info = {}
        if mcap is None:
            mcap = info.get("marketCap")
        ev_ebitda = info.get("enterpriseToEbitda")
        industry = (info.get("industry") or "").strip() or None
        longname = (info.get("longName") or "").strip() or None
        return {"Ticker": ticker, "mcap_num": mcap, "Company EV/EBITDA": ev_ebitda, "yf_industry": industry, "Long Name": longname}
    except Exception:
        return {"Ticker": ticker, "mcap_num": None, "Company EV/EBITDA": None, "yf_industry": None, "Long Name": None}

# -----------------------------
# Damodaran industries & multiples
# -----------------------------
@st.cache_data(show_spinner=False)
def damodaran_industries():
    url = "https://pages.stern.nyu.edu/~adamodar/New_Home_Page/datafile/vebitda.html"
    df = pd.read_html(url, header=0)[0]
    df.columns = [str(c).strip().replace("\xa0", " ") for c in df.columns]
    ind_col = df.columns[0]
    ev_cols = [c for c in df.columns if "All firms" in c]
    ev_col = ev_cols[-1] if ev_cols else df.columns[-1]
    out = df[[ind_col, ev_col]].rename(columns={ind_col: "Industry", ev_col: "Sector EV/EBITDA"})
    out["Industry_lc"] = out["Industry"].str.lower()
    out["Sector EV/EBITDA"] = pd.to_numeric(out["Sector EV/EBITDA"], errors="coerce")
    out = out.dropna(subset=["Sector EV/EBITDA"]).reset_index(drop=True)
    return out

damodaran_df = damodaran_industries()
industry_options = damodaran_df["Industry"].tolist()

# -----------------------------
# Matching logic
# -----------------------------
def gen_tokens(label: str):
    txt = label.lower().replace("&", " and ").replace("(", " ").replace(")", " ").replace("/", " ")
    toks = [w for w in txt.split() if len(w) > 2]
    return toks

# explicit yfinance-industry refiners for key Damodaran industries
REFINE_MAP = {
    "drugs": ["drug", "pharm", "pharmaceutical"],
    "biotechnology": ["biotech"],
    "medical equipment": ["medical devices", "medical instruments", "diagnostic", "healthcare equipment"],
    "health care support services": ["healthcare providers", "healthcare plans", "medical care facilities",
                                     "health information services", "managed healthcare"],
    "semiconductor": ["semiconductors", "semiconductor equipment"],
    "software": ["software—application", "software—infrastructure", "software", "systems software", "application software"],
    "software (internet)": ["internet content", "internet services", "internet retail", "online"],
    "telecom": ["telecom services", "telecommunications services"],
    "telecom. services": ["telecom services", "telecommunications services"],
    "telecom equipment": ["communication equipment"],
    "retail": ["specialty retail", "department stores", "apparel retail", "internet retail", "discount stores"],
    "banks": ["banks"],
    "insurance": ["insurance"],
    "reit": ["reit"],
    "utilities": ["utilities"],
    "aerospace": ["aerospace", "defense"],
    "oil": ["oil", "gas", "energy"],
    "chemicals": ["chemicals"],
    "transportation": ["airlines", "railroads", "trucking", "marine", "transportation"],
    "metals": ["steel", "aluminum", "other industrial metals", "gold", "silver", "copper", "metals", "mining"],
    "auto": ["auto manufacturers"],
}

# Big-cap priority seed so headline names are fetched first (helps Ultra Cap):
PRIORITY_TICKERS = [
    # Health care megacaps & ADRs
    "LLY","NVO","JNJ","UNH","MRK","PFE","AZN","BMY","SNY","GSK","RHHBY",
    # Tech megacaps etc (helps other industries)
    "AAPL","MSFT","NVDA","GOOGL","GOOG","AMZN","META","TSLA","TSM","AVGO",
]

def prefilter_candidates(industry_label: str, base_df: pd.DataFrame) -> pd.DataFrame:
    """Fast, text-based prefilter to shrink candidate set before YF calls."""
    toks = gen_tokens(industry_label)
    # broaden for pharma so LLY/NVO don't get missed on name-only pass
    if "drugs" in toks or "pharmaceuticals" in toks:
        toks = toks + ["health"]  # include generic Health Care sector text

    mask = pd.Series(False, index=base_df.index)
    for t in set(toks):
        mask |= base_df["lc_sector"].str.contains(t, na=False)
        mask |= base_df["lc_name"].str.contains(t, na=False)

    # ensure headline tickers are included if present in the universe
    headliners = base_df[base_df["Ticker"].isin(PRIORITY_TICKERS)]
    candidates = pd.concat([headliners, base_df[mask]], axis=0).drop_duplicates(subset=["Ticker"])
    return candidates

def refine_by_yf_industry(industry_label: str, df: pd.DataFrame) -> pd.DataFrame:
    """After YF fetch, refine by yfinance 'industry' field using REFINE_MAP."""
    key = industry_label.lower()
    pats = []
    for k, lst in REFINE_MAP.items():
        if k in key:
            pats.extend(lst)
    if not pats:
        # generic fallback: tokens from the Damodaran label
        pats = gen_tokens(industry_label)

    if "yf_industry" not in df.columns:
        return df

    z = df.copy()
    z["yf_industry_lc"] = z["yf_industry"].fillna("").str.lower()
    mask = pd.Series(False, index=z.index)
    for p in set(pats):
        mask |= z["yf_industry_lc"].str.contains(p, na=False)
    # if we filtered everything out, fall back to original
    return z[mask] if mask.any() else df

# -----------------------------
# Display helpers
# -----------------------------
def fmt_mcap(x):
    if pd.isna(x): return "N/A"
    try:
        x = float(x)
    except Exception:
        return "N/A"
    if x >= 1e12: return f"{x/1e12:.2f}T"
    if x >= 1e9:  return f"{x/1e9:.2f}B"
    if x >= 1e6:  return f"{x/1e6:.2f}M"
    return f"{x:.0f}"

def fmt_mult(x):
    return "N/A" if pd.isna(x) else f"{float(x):.1f}×"

# -----------------------------
# UI
# -----------------------------
st.title("📊 Company vs Industry EV/EBITDA Explorer")

industry_choice = st.sidebar.selectbox("Select Industry", industry_options)
cap_choice = st.sidebar.radio(
    "Market Cap Filter",
    ["Show All Companies", "Small Cap (<$2B)", "Mid Cap ($2B–$10B)",
     "Large Cap ($10B–$50B)", "Mega Cap ($50B–$200B)", "Ultra Cap (>$200B)"],
    index=5  # default to Ultra Cap so megacaps appear quickly
)

# Selected industry multiple
ind_row = damodaran_df[damodaran_df["Industry"] == industry_choice].iloc[0]
industry_multiple = ind_row["Sector EV/EBITDA"]

# -----------------------------
# Fetch on click
# -----------------------------
if st.button("Fetch Data"):
    # 1) prefilter by label to shrink work
    cand = prefilter_candidates(industry_choice, companies)

    # 2) fetch YF data (prioritize headliners first)
    # keep a sensible cap; batches of ~50 work well on Streamlit Cloud
    MAX_FETCH = 1200
    BATCH = 50
    tickers = cand["Ticker"].tolist()[:MAX_FETCH]
    rows = []
    for i in range(0, len(tickers), BATCH):
        for t in tickers[i:i+BATCH]:
            rows.append(fetch_financials(t))
        if len(rows) >= MAX_FETCH:
            break

    fin = pd.DataFrame(rows)
    merged = cand.merge(fin, on="Ticker", how="left")

    # 3) refine using yfinance industry to keep the right sub-industry
    refined = refine_by_yf_industry(industry_choice, merged)

    # 4) apply market-cap filter on numeric column BEFORE formatting
    out = refined.copy()
    if cap_choice == "Small Cap (<$2B)":
        out = out[out["mcap_num"] < 2_000_000_000]
    elif cap_choice == "Mid Cap ($2B–$10B)":
        out = out[(out["mcap_num"] >= 2_000_000_000) & (out["mcap_num"] < 10_000_000_000)]
    elif cap_choice == "Large Cap ($10B–$50B)":
        out = out[(out["mcap_num"] >= 10_000_000_000) & (out["mcap_num"] < 50_000_000_000)]
    elif cap_choice == "Mega Cap ($50B–$200B)":
        out = out[(out["mcap_num"] >= 50_000_000_000) & (out["mcap_num"] < 200_000_000_000)]
    elif cap_choice == "Ultra Cap (>$200B)":
        out = out[out["mcap_num"] >= 200_000_000_000]

    # 5) sort by numeric cap DESC, then format for display
    out = out.sort_values("mcap_num", ascending=False, na_position="last")
    out["Market Cap"] = out["mcap_num"].apply(fmt_mcap)
    out["Company EV/EBITDA"] = out["Company EV/EBITDA"].apply(fmt_mult)
    out["Sector EV/EBITDA"] = fmt_mult(industry_multiple)

    display_cols = ["Company Name", "Ticker", "Sector", "Market Cap", "Company EV/EBITDA", "Sector EV/EBITDA"]
    st.data_editor(out[display_cols], use_container_width=True, hide_index=True, disabled=True)

    st.download_button(
        "⬇️ Download CSV",
        out[display_cols].to_csv(index=False),
        "company_multiples.csv",
        "text/csv",
    )
else:
    st.info("Select an industry and click **Fetch Data**.")
