import streamlit as st
import pandas as pd
import yfinance as yf
from companies_data import companies_list  # (Company Name, Ticker, Sector) ~7k US + ADRs

st.set_page_config(page_title="EV/EBITDA Explorer", layout="wide")

# -----------------------------
# Load company universe
# -----------------------------
companies = pd.DataFrame(companies_list)[["Company Name", "Ticker", "Sector"]].dropna()
# Clean trailing exchange decorations if present
companies["Company Name"] = companies["Company Name"].str.replace(r"\s*\([^)]+\)$", "", regex=True)
companies["lc_name"]   = companies["Company Name"].str.lower()
companies["lc_sector"] = companies["Sector"].str.lower()

# -----------------------------
# Robust Yahoo Finance fetch (cached)
# -----------------------------
@st.cache_data(show_spinner=False)
def fetch_financials(ticker: str):
    """
    Best-effort pull of Market Cap (numeric), EV/EBITDA, and Yahoo 'industry'.
    Uses fast_info first, falls back to info.
    """
    try:
        t = yf.Ticker(ticker)
        mcap = None
        try:
            fi = getattr(t, "fast_info", None)
            if fi is not None:
                mcap = getattr(fi, "market_cap", None)
        except Exception:
            pass
        info = {}
        try:
            info = t.info or {}
        except Exception:
            info = {}
        if mcap is None:
            mcap = info.get("marketCap")
        return {
            "Ticker": ticker,
            "mcap_num": mcap,
            "Company EV/EBITDA": info.get("enterpriseToEbitda"),
            "yf_industry": (info.get("industry") or "").strip() or None,
            "Long Name": (info.get("longName") or "").strip() or None,
        }
    except Exception:
        return {
            "Ticker": ticker,
            "mcap_num": None,
            "Company EV/EBITDA": None,
            "yf_industry": None,
            "Long Name": None,
        }

# -----------------------------
# Damodaran industries & multiples (robust parse)
# -----------------------------
@st.cache_data(show_spinner=False)
def damodaran_industries():
    url = "https://pages.stern.nyu.edu/~adamodar/New_Home_Page/datafile/vebitda.html"
    df = pd.read_html(url, header=0)[0]
    df.columns = [str(c).strip().replace("\xa0", " ") for c in df.columns]
    ind_col = df.columns[0]
    # Prefer the “All firms” EV/EBITDA column when present
    ev_cols = [c for c in df.columns if "All firms" in c]
    ev_col = ev_cols[-1] if ev_cols else df.columns[-1]
    out = df[[ind_col, ev_col]].rename(columns={ind_col: "Industry", ev_col: "Sector EV/EBITDA"})
    out["Industry"] = out["Industry"].astype(str)
    out["Sector EV/EBITDA"] = pd.to_numeric(out["Sector EV/EBITDA"], errors="coerce")
    # drop totals / blanks
    mask_total = out["Industry"].str.lower().str.contains("total market")
    out = out[~mask_total].dropna(subset=["Sector EV/EBITDA"]).reset_index(drop=True)
    return out

damo = damodaran_industries()
INDUSTRIES = damo["Industry"].tolist()

# -----------------------------
# Helpers for matching
# -----------------------------
STOP = {"and","services","service","general","other","lines","line","systems","application","apps"}
SYN = {
    "drugs":"drug", "pharmaceuticals":"pharmaceutical", "pharma":"pharmaceutical",
    "telecom.":"telecom", "telecommunication":"telecom",
    "semiconductors":"semiconductor", "internet":"internet",
    "equipment":"equipment", "utilities":"utility", "banks":"bank",
    "minerals":"mining", "metals":"metal", "materials":"material",
    "restaurants":"restaurant", "distributors":"distributor", "wholesale":"wholesale",
    "retailers":"retail", "beverages":"beverage",
}

def tokens(label: str):
    txt = label.lower().replace("&"," and ").replace("/"," ").replace("("," ").replace(")"," ").replace(",", " ")
    toks = [SYN.get(w, w) for w in txt.split() if len(w)>2 and w not in STOP]
    # consolidate duplicates
    seen, out = set(), []
    for w in toks:
        if w not in seen:
            seen.add(w); out.append(w)
    return out

def guess_broad_sector(industry_label: str):
    """Return a list of broad sectors to prefilter on, inferred from Damodaran label."""
    t = " " + industry_label.lower() + " "
    def has(*ws): return any((" "+w.lower()+" ") in t for w in ws)
    if has("telecom"):                 return ["communication services"]
    if has("advertis", "media", "broadcast", "publishing"): return ["communication services"]
    if has("software","semiconductor","computer","internet","communication equipment","peripherals"):
        return ["information technology"]
    if has("pharma","drug","biotech","medical","health"):   return ["health care"]
    if has("retail","hotel","leisure","auto","restaurant","entertainment","homebuilding","apparel","recreation","distributor"):
        return ["consumer discretionary"]
    if has("beverage","food","grocery","household","tobacco","staple"):
        return ["consumer staples"]
    if has("bank","insurance","capital markets","broker"):   return ["financials"]
    if has("reit","real estate"):                            return ["real estate"]
    if has("oil","gas","energy","coal"):                     return ["energy"]
    if has("chem","steel","metal","mining","paper","packag","building material","construction materials"):
        return ["materials"]
    if has("aerospace","defense","industrial","transport","airline","railroad","trucking","marine","ship"):
        return ["industrials"]
    if has("utility","electric","water"):                    return ["utilities"]
    return None  # no prefilter

def industry_matcher(industry_label: str):
    """
    Build a strict matcher for Yahoo 'industry' field from Damodaran label:
    - exact / contains any of the normalized tokens
    - plus sensible synonyms for well-known categories
    """
    toks = tokens(industry_label)
    # strengthen some common industries with explicit needles
    SPECIAL = {
        "advertising": ["advertising agencies"],
        "pharmaceutical": ["drug manufacturers", "pharmaceuticals"],
        "biotechnology": ["biotechnology"],
        "semiconductor": ["semiconductors", "semiconductor equipment"],
        "telecom": ["telecom services", "telecommunications services", "wireless telecommunications services"],
        "communication": ["communication equipment"],
        "software": ["software—application","software—infrastructure","systems software","application software","software"],
        "reit": ["reit"],
        "banks": ["banks"],
        "insurance": ["insurance"],
        "utility": ["utilities"],
        "steel": ["steel"],
        "mining": ["metals & mining", "other industrial metals & mining", "gold", "silver", "copper"],
        "oil": ["oil & gas", "oil & gas e&p", "oil & gas integrated", "oil & gas refining & marketing", "oil & gas equipment & services"],
        "internet": ["internet content & information", "internet retail"],
        "retail": ["specialty retail","department stores","apparel retail","grocery stores","drug retailers","discount stores","internet retail"],
        "medical": ["medical devices","medical instruments & supplies","diagnostic & research","healthcare equipment"],
        "health": ["healthcare providers & services","healthcare plans","medical care facilities","health information services","managed healthcare"],
        "aerospace": ["aerospace & defense"],
        "transportation": ["airlines","railroads","trucking","marine","transportation"],
        "chemicals": ["chemicals"],
        "construction": ["building materials","engineering & construction"],
        "beverage": ["beverages—non-alcoholic","beverages—wineries & distilleries","beverages—brewers"],
        "food": ["packaged foods & meats","farm products"],
        "household": ["household & personal products"],
        "tobacco": ["tobacco"],
        "paper": ["paper & forest products"],
        "packag": ["packaging & containers"],
    }
    needles = set()
    for w in toks:
        if w in SPECIAL:
            needles.update([n.lower() for n in SPECIAL[w]])
        else:
            needles.add(w)
    return list(needles)

# -----------------------------
# Formatting helpers
# -----------------------------
def fmt_mcap(x):
    if pd.isna(x): return "N/A"
    try: x = float(x)
    except: return "N/A"
    if x >= 1e12: return f"{x/1e12:.2f}T"
    if x >= 1e9:  return f"{x/1e9:.2f}B"
    if x >= 1e6:  return f"{x/1e6:.2f}M"
    return f"{x:.0f}"

def fmt_mult(x): return "N/A" if pd.isna(x) else f"{float(x):.1f}×"

# -----------------------------
# UI
# -----------------------------
st.title("📊 Company vs Industry EV/EBITDA Explorer")

industry_choice = st.sidebar.selectbox("Select Industry", INDUSTRIES)
cap_choice = st.sidebar.radio(
    "Market Cap Filter",
    ["Show All Companies", "Small Cap (<$2B)", "Mid Cap ($2B–$10B)",
     "Large Cap ($10B–$50B)", "Mega Cap ($50B–$200B)", "Ultra Cap (>$200B)"],
    index=5
)

industry_multiple = float(damo.loc[damo["Industry"] == industry_choice, "Sector EV/EBITDA"].iloc[0])

if st.button("Fetch Data"):
    # 1) prefilter by broad sector guess to shrink candidate set
    allowed_sectors = guess_broad_sector(industry_choice)
    cand = companies.copy()
    if allowed_sectors:
        mask_sector = pd.Series(False, index=cand.index)
        for s in allowed_sectors:
            mask_sector |= cand["lc_sector"].str.contains(s, na=False)
        cand = cand[mask_sector]

    # sensible cap and batch for Streamlit Cloud
    MAX_FETCH = 1200 if allowed_sectors else 800
    BATCH = 50

    # 2) fetch Yahoo info for candidates
    tickers = cand["Ticker"].dropna().unique().tolist()[:MAX_FETCH]
    rows = []
    for i in range(0, len(tickers), BATCH):
        for t in tickers[i:i+BATCH]:
            rows.append(fetch_financials(t))
        if len(rows) >= MAX_FETCH:
            break
    fin = pd.DataFrame(rows)
    merged = cand.merge(fin, on="Ticker", how="left")

    # 3) strict refine by yfinance industry
    needles = industry_matcher(industry_choice)  # list of lowercase substrings
    z = merged.copy()
    z["yf_industry_lc"] = z["yf_industry"].fillna("").str.lower()
    mask_yf = pd.Series(False, index=z.index)
    for p in set(needles):
        mask_yf |= z["yf_industry_lc"].str.contains(p, na=False)
    refined = z[mask_yf]

    # If nothing matched strictly, tell the user rather than show wrong companies
    if refined.empty:
        st.warning("No companies matched this industry based on Yahoo industry classification. "
                   "Try a different industry or a broader market-cap filter.")
        st.stop()

    # 4) numeric market-cap filter BEFORE formatting
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

    # 5) sort numerically (DESC) and format for display
    out = out.sort_values("mcap_num", ascending=False, na_position="last")
    out["Market Cap"] = out["mcap_num"].apply(fmt_mcap)
    out["Company EV/EBITDA"] = out["Company EV/EBITDA"].apply(fmt_mult)
    out["Sector EV/EBITDA"] = fmt_mult(industry_multiple)

    # Display & download
    view = out[["Company Name", "Ticker", "Sector", "Market Cap", "Company EV/EBITDA", "yf_industry"]]
    view = view.rename(columns={"yf_industry": "YF Industry"})
    st.data_editor(view.assign(**{"Sector EV/EBITDA": fmt_mult(industry_multiple)}),
                   use_container_width=True, hide_index=True, disabled=True)
    st.download_button("⬇️ Download CSV",
                       view.assign(**{"Sector EV/EBITDA": industry_multiple}).to_csv(index=False),
                       "company_multiples.csv","text/csv")
else:
    st.info("Select an industry and click **Fetch Data**.")
