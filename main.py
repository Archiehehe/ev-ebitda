import re
import streamlit as st
import pandas as pd
import yfinance as yf
from companies_data import companies_list

st.set_page_config(page_title="EV/EBITDA Explorer", layout="wide")

companies = pd.DataFrame(companies_list)[["Company Name","Ticker","Sector"]].dropna()
companies["Company Name"] = companies["Company Name"].str.replace(r"\s*\([^)]+\)$","",regex=True)

# -----------------------------
# Clean tickers
# -----------------------------
BAD_SUFFIX = re.compile(r"\.(F|Q|SA|BO|PA|SG|MI|BR|VX|V|BA)$", re.IGNORECASE)
def clean_tickers(df):
    tks = df["Ticker"].dropna().astype(str).str.strip().unique().tolist()
    return [t for t in tks if not BAD_SUFFIX.search(t)]

# -----------------------------
# Batch fetch (fast)
# -----------------------------
def batch_fetch(tickers, limit=400):
    tickers = tickers[:limit]
    data = yf.Tickers(" ".join(tickers))
    out=[]
    for t in tickers:
        try:
            ti = data.tickers[t]
            info = {}
            try: info = ti.info or {}
            except: pass
            mcap = getattr(getattr(ti,"fast_info",None),"market_cap",None)
            if mcap is None: mcap = info.get("marketCap")
            out.append({
                "Ticker":t,
                "Market Cap":mcap,
                "Company EV/EBITDA":info.get("enterpriseToEbitda"),
                "yf_industry":(info.get("industry") or "").lower()
            })
        except: continue
    return pd.DataFrame(out)

# -----------------------------
# Damodaran industries
# -----------------------------
@st.cache_data(show_spinner=False)
def damodaran_industries():
    url="https://pages.stern.nyu.edu/~adamodar/New_Home_Page/datafile/vebitda.html"
    df=pd.read_html(url,header=0)[0]
    df.columns=[str(c).strip().replace("\xa0"," ") for c in df.columns]
    ind_col=df.columns[0]
    ev_cols=[c for c in df.columns if "All firms" in c]
    ev_col=ev_cols[-1] if ev_cols else df.columns[-1]
    out=df[[ind_col,ev_col]].rename(columns={ind_col:"Industry",ev_col:"Sector EV/EBITDA"})
    out["Sector EV/EBITDA"]=pd.to_numeric(out["Sector EV/EBITDA"],errors="coerce")
    out=out[~out["Industry"].str.lower().str.contains("total market")]
    return out.dropna().reset_index(drop=True)

damo=damodaran_industries()
INDUSTRIES=damo["Industry"].tolist()

# -----------------------------
# Helpers
# -----------------------------
STOP={"and","services","service","general","other","lines","line","systems","application","apps"}
def tokens(label:str):
    txt=label.lower().replace("&"," ").replace("/"," ").replace("("," ").replace(")"," ")
    return [w for w in txt.split() if len(w)>2 and w not in STOP]

def fmt_mcap(x):
    if pd.isna(x): return "N/A"
    try:x=float(x)
    except: return "N/A"
    if x>=1e12: return f"{x/1e12:.2f}T"
    if x>=1e9:  return f"{x/1e9:.2f}B"
    if x>=1e6:  return f"{x/1e6:.2f}M"
    return f"{x:.0f}"

def fmt_mult(x): return "N/A" if pd.isna(x) else f"{float(x):.1f}×"

# -----------------------------
# UI
# -----------------------------
st.title("📊 Company vs Industry EV/EBITDA Explorer")

industry_choice=st.sidebar.selectbox("Select Industry",INDUSTRIES)
cap_choice=st.sidebar.radio(
    "Market Cap Filter",
    ["Show All Companies","Small Cap (<$2B)","Mid Cap ($2B–$10B)",
     "Large Cap ($10B–$50B)","Mega Cap ($50B–$200B)","Ultra Cap (>$200B)"],
    index=5
)

industry_multiple=float(damo.loc[damo["Industry"]==industry_choice,"Sector EV/EBITDA"].iloc[0])

if st.button("Fetch Data"):
    tickers=clean_tickers(companies)
    fin=batch_fetch(tickers,limit=600)

    if fin.empty: st.warning("No data fetched."); st.stop()

    # Token match against Yahoo industry OR sector text
    needles=tokens(industry_choice)
    mask=pd.Series(False,index=fin.index)
    for n in needles:
        mask |= fin["yf_industry"].str.contains(n,na=False)
    merged=fin[mask].merge(companies,on="Ticker",how="left")

    # Fallback: if empty, take top 50 by market cap
    if merged.empty:
        merged=fin.merge(companies,on="Ticker",how="left").sort_values("Market Cap",ascending=False).head(50)

    # Apply market-cap filter
    mc=merged["Market Cap"]
    if cap_choice=="Small Cap (<$2B)": merged=merged[mc<2_000_000_000]
    elif cap_choice=="Mid Cap ($2B–$10B)": merged=merged[(mc>=2_000_000_000)&(mc<10_000_000_000)]
    elif cap_choice=="Large Cap ($10B–$50B)": merged=merged[(mc>=10_000_000_000)&(mc<50_000_000_000)]
    elif cap_choice=="Mega Cap ($50B–$200B)": merged=merged[(mc>=50_000_000_000)&(mc<200_000_000_000)]
    elif cap_choice=="Ultra Cap (>$200B)": merged=merged[mc>=200_000_000_000]

    # Sort
    merged=merged.sort_values("Market Cap",ascending=False,na_position="last")

    # Format
    merged["Market Cap"]=merged["Market Cap"].apply(fmt_mcap)
    merged["Company EV/EBITDA"]=merged["Company EV/EBITDA"].apply(fmt_mult)
    merged["Sector EV/EBITDA"]=fmt_mult(industry_multiple)

    show=merged[["Company Name","Ticker","Sector","Market Cap","Company EV/EBITDA","Sector EV/EBITDA"]]

    st.data_editor(show,use_container_width=True,hide_index=True,disabled=True)
    st.download_button("⬇️ Download CSV",show.to_csv(index=False),"company_multiples.csv","text/csv")
else:
    st.info("Select an industry and click **Fetch Data**.")
