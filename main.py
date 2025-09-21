import re
import streamlit as st
import pandas as pd
import yfinance as yf
from companies_data import companies_list   # <-- ensure your cleaned file is named companies_data.py

st.set_page_config(page_title="EV/EBITDA Explorer", layout="wide")

# -----------------------------
# Load companies (clean universe ~7k)
# -----------------------------
companies = pd.DataFrame(companies_list)[["Company Name", "Ticker", "Sector"]].dropna()
companies["Company Name"] = companies["Company Name"].str.replace(r"\s*\([^)]+\)$", "", regex=True)
companies["lc_sector"] = companies["Sector"].str.lower()

# -----------------------------
# Damodaran industries (robust parse)
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
    out["Sector EV/EBITDA"] = pd.to_numeric(out["Sector EV/EBITDA"], errors="coerce")
    out = out[~out["Industry"].str.lower().str.contains("total market")]
    return out.dropna().reset_index(drop=True)

damo = damodaran_industries()
INDUSTRIES = damo["Industry"].tolist()

# -----------------------------
# Mapping rules: derive sectors + YF industry needles from Damodaran label
# -----------------------------
STOP = {"and","services","service","general","other","lines","line","systems","application","apps"}

def derive_rules(industry_label: str):
    """Return (allowed_sectors, yf_industry_needles) for strict filtering."""
    s = industry_label.lower()
    sectors, needles = set(), set()

    def add_sec(*xs): 
        for x in xs: sectors.add(x)
    def add_nd(*xs): 
        for x in xs: needles.add(x)

    # Communication/Media
    if "advertis" in s: add_sec("communication services"); add_nd("advertising agencies","advertising")
    if "broadcast" in s: add_sec("communication services"); add_nd("broadcasting")
    if "publishing" in s or "newspaper" in s: add_sec("communication services"); add_nd("publishing","internet content")
    if "entertainment" in s: add_sec("communication services","consumer discretionary"); add_nd("entertainment")
    if "telecom" in s and "equipment" not in s:
        add_sec("communication services"); add_nd("telecom services","telecommunications services","wireless telecommunications services")
    if ("telecom" in s and "equipment" in s) or "communication equipment" in s:
        add_sec("information technology","communication services"); add_nd("communication equipment")

    # Software/Internet/Semis/IT
    if "software" in s:
        add_sec("information technology"); add_nd("software","software—application","software—infrastructure","systems software","application software")
    if "internet" in s:
        add_sec("communication services","information technology","consumer discretionary")
        add_nd("internet content","internet content & information","internet retail","online")
    if "semiconductor" in s:
        add_sec("information technology"); add_nd("semiconductors","semiconductor equipment")
    if "computer services" in s or "it services" in s:
        add_sec("information technology"); add_nd("information technology services","it services")
    if "computer peripherals" in s or "hardware" in s:
        add_sec("information technology"); add_nd("computer hardware","technology hardware","consumer electronics")

    # Health care cluster
    if "biotech" in s:
        add_sec("health care"); add_nd("biotechnology")
    if "drug" in s or "pharma" in s:
        add_sec("health care"); add_nd("drug manufacturers","pharmaceuticals","drug manufacturers—general","drug manufacturers—specialty & generic")
    if "medical equipment" in s or "medical devices" in s or ("medical" in s and "equipment" in s):
        add_sec("health care"); add_nd("medical devices","medical instruments & supplies","diagnostic & research","healthcare equipment")
    if "support services" in s or "health care support" in s:
        add_sec("health care"); add_nd("healthcare providers & services","healthcare plans","medical care facilities","health information services","managed healthcare")

    # Financials/RE
    if "bank" in s: add_sec("financials"); add_nd("banks")
    if "insur" in s: add_sec("financials"); add_nd("insurance")
    if "reit" in s: add_sec("real estate"); add_nd("reit")
    if "real estate" in s and "reit" not in s:
        add_sec("real estate"); add_nd("real estate—development","real estate—diversified")

    # Energy/Materials/Industrials
    if "aerospace" in s or "defense" in s:
        add_sec("industrials"); add_nd("aerospace & defense")
    if "airline" in s:
        add_sec("industrials"); add_nd("airlines")
    if "railroad" in s:
        add_sec("industrials"); add_nd("railroads")
    if "trucking" in s:
        add_sec("industrials"); add_nd("trucking")
    if "marine" in s or "shipping" in s:
        add_sec("industrials"); add_nd("marine")
    if "transportation" in s:
        add_sec("industrials"); add_nd("transportation")
    if "aerospace & defense" in s: add_sec("industrials"); add_nd("aerospace & defense")
    if "oil" in s or "gas" in s or "energy" in s:
        add_sec("energy"); add_nd("oil & gas","oil & gas e&p","oil & gas integrated","oil & gas refining & marketing","oil & gas equipment & services")
    if "chemical" in s:
        add_sec("materials"); add_nd("chemicals")
    if "steel" in s:
        add_sec("materials"); add_nd("steel")
    if "mining" in s or "metals" in s:
        add_sec("materials"); add_nd("metals & mining","other industrial metals & mining","gold","silver","copper")
    if "building materials" in s or "construction materials" in s:
        add_sec("materials","industrials"); add_nd("building materials")
    if "aerospace & defense" in s:
        add_sec("industrials"); add_nd("aerospace & defense")
    if "utility" in s or "electric" in s or "water" in s:
        add_sec("utilities"); add_nd("utilities")

    # Retail/Consumer
    if "retail" in s and "online" in s:
        add_sec("consumer discretionary","communication services"); add_nd("internet retail")
    elif "retail" in s:
        add_sec("consumer discretionary","consumer staples")
        add_nd("specialty retail","department stores","apparel retail","grocery stores","drug retailers","discount stores")
    if "restaurant" in s or "dining" in s:
        add_sec("consumer discretionary"); add_nd("restaurants")
    if "auto" in s:
        add_sec("consumer discretionary"); add_nd("auto manufacturers")
    if "beverage" in s:
        add_sec("consumer staples"); add_nd("beverages—non-alcoholic","beverages—wineries & distilleries","beverages—brewers")
    if "food" in s:
        add_sec("consumer staples"); add_nd("packaged foods & meats","farm products")
    if "household" in s or "personal products" in s:
        add_sec("consumer staples"); add_nd("household & personal products")
    if "tobacco" in s: add_sec("consumer staples"); add_nd("tobacco")

    # Fallback: use tokens from label for YF industry contains-any
    if not needles:
        toks = [w for w in re.split(r"[^a-zA-Z]+", s) if len(w) > 2 and w not in STOP]
        needles.update(toks)

    return (list(sectors) or None, [n.lower() for n in needles])

# -----------------------------
# Fetch (batched) from Yahoo
# -----------------------------
def fetch_batch(tickers, limit=600):
    tickers = tickers[:limit]
    if not tickers:
        return pd.DataFrame(columns=["Ticker","mcap_num","Company EV/EBITDA","yf_industry"])
    data = yf.Tickers(" ".join(tickers))
    out = []
    for t in tickers:
        try:
            ti = data.tickers[t]
            info = {}
            try:
                info = ti.info or {}
            except Exception:
                info = {}
            mcap = getattr(getattr(ti, "fast_info", None), "market_cap", None)
            if mcap is None:
                mcap = info.get("marketCap")
            out.append({
                "Ticker": t,
                "mcap_num": mcap,
                "Company EV/EBITDA": info.get("enterpriseToEbitda"),
                "yf_industry": (info.get("industry") or "").strip().lower(),
            })
        except Exception:
            continue
    return pd.DataFrame(out)

# -----------------------------
# Formatting
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
    ["Show All Companies","Small Cap (<$2B)","Mid Cap ($2B–$10B)",
     "Large Cap ($10B–$50B)","Mega Cap ($50B–$200B)","Ultra Cap (>$200B)"],
    index=0
)

industry_multiple = float(damo.loc[damo["Industry"] == industry_choice, "Sector EV/EBITDA"].iloc[0])

if st.button("Fetch Data"):
    # 1) Derive strict rules
    allowed_sectors, yf_needles = derive_rules(industry_choice)

    # 2) Prefilter by sector to keep batch small
    candidates = companies.copy()
    if allowed_sectors:
        mask = pd.Series(False, index=candidates.index)
        for s in allowed_sectors:
            mask |= candidates["lc_sector"].str.contains(s, na=False)
        candidates = candidates[mask]

    # 3) Fetch from Yahoo in one batch
    fin = fetch_batch(candidates["Ticker"].dropna().unique().tolist(), limit=600)

    if fin.empty or "Ticker" not in fin.columns:
        st.warning("No Yahoo Finance data returned for this slice.")
        st.stop()

    # 4) STRICT refine by Yahoo 'industry'
    z = fin.copy()
    z["yf_industry"] = z["yf_industry"].fillna("")
    mask_yf = pd.Series(False, index=z.index)
    for p in set(yf_needles):
        mask_yf |= z["yf_industry"].str.contains(p, na=False)
    refined = z[mask_yf]

    if refined.empty:
        st.warning("No companies matched this industry under Yahoo classification.")
        st.stop()

    # 5) Join back names/sectors and filter by market cap
    out = refined.merge(candidates, on="Ticker", how="left")

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

    # 6) Sort + format
    out = out.sort_values("mcap_num", ascending=False, na_position="last")
    out["Market Cap"] = out["mcap_num"].apply(fmt_mcap)
    out["Company EV/EBITDA"] = out["Company EV/EBITDA"].apply(fmt_mult)
    out["Sector EV/EBITDA"] = fmt_mult(industry_multiple)

    st.data_editor(
        out[["Company Name","Ticker","Sector","Market Cap","Company EV/EBITDA","Sector EV/EBITDA"]],
        use_container_width=True, hide_index=True, disabled=True
    )

    st.download_button(
        "⬇️ Download CSV",
        out[["Company Name","Ticker","Sector","Market Cap","Company EV/EBITDA","Sector EV/EBITDA"]].to_csv(index=False),
        "company_multiples.csv",
        "text/csv"
    )
else:
    st.info("Select an industry and click **Fetch Data**.")
