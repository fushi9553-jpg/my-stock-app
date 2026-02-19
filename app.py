import streamlit as st
from supabase import create_client, Client
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from datetime import datetime
import requests
from bs4 import BeautifulSoup
import re

# --- 投資信託の基準価額をスクレイピングする汎用関数 ---
@st.cache_data(ttl=3600)  # 1時間に1回だけ取得（サイトへの負荷軽減）
def get_trust_price(fund_code):
    """
    みんかぶの投資信託ページから最新の基準価額を取得する
    例: fund_code = '0331418A' (オルカン)
    """
    url = f"https://itf.minkabu.jp/fund/{fund_code}"
    # Pythonからの機械的なアクセスだと弾かれることがあるため、ブラウザを装う
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    
    try:
        res = requests.get(url, headers=headers, timeout=5)
        soup = BeautifulSoup(res.text, 'html.parser')
        
        # みんかぶのHTML構造から基準価額の部分を探す（※クラス名はサイトの仕様変更で変わる可能性あり）
        # <div class="stock_price">12,345円</div> のような部分を狙い撃ち
        price_elem = soup.select_one('.stock_price')
        
        if price_elem:
            # 「28,540円」のような文字列から、数字だけを抽出して数値(float)に変換する
            price_str = re.sub(r'[^\d]', '', price_elem.text)
            return float(price_str)
        else:
            return None
            
    except Exception as e:
        # 通信エラーなどの場合はNoneを返す
        st.error(f"投資信託データの取得に失敗しました: {e}")
        return None
# 1. ページ設定
st.set_page_config(page_title="My Portfolio App", layout="wide", initial_sidebar_state="collapsed")

if 'page' not in st.session_state: st.session_state.page = "assets"
if 'target_ticker' not in st.session_state: st.session_state.target_ticker = None

# ★★★ CSSデザイン ★★★
st.markdown("""
    <style>
    .main { background-color: #0e1117; color: white; }
    a { text-decoration: none !important; color: inherit !important; }
    a:hover { text-decoration: none !important; color: inherit !important; }
    .stock-card { background-color: #262730; padding: 15px; border-radius: 10px; margin-bottom: 10px; border: 1px solid #3b3d48; transition: transform 0.1s, border-color 0.1s; color: white; text-decoration: none; }
    .stock-card:hover { border-color: #2ecc71; transform: translateY(-2px); cursor: pointer; }
    .stMetric { background-color: #262730; padding: 15px; border-radius: 8px; border-left: 5px solid #2ecc71; box-shadow: 0 2px 4px rgba(0,0,0,0.2); }
    </style>
    """, unsafe_allow_html=True)

# --- 2. データベース接続 (Supabase) ---
@st.cache_resource
def init_connection():
    url = st.secrets["supabase"]["url"]
    key = st.secrets["supabase"]["key"]
    return create_client(url, key)

supabase: Client = init_connection()

@st.cache_data(ttl=60)
def load_data():
    try:
        t_res = supabase.table("trades").select("*").execute()
        df_t = pd.DataFrame(t_res.data) if t_res.data else pd.DataFrame(columns=['id', 'date', 'ticker', 'name', 'type', 'price', 'qty'])
        
        b_res = supabase.table("balance").select("*").execute()
        df_b = pd.DataFrame(b_res.data) if b_res.data else pd.DataFrame(columns=['id', 'date', 'type', 'amount', 'memo'])
        
        s_res = supabase.table("settings").select("*").execute()
        df_s = pd.DataFrame(s_res.data) if s_res.data else pd.DataFrame(columns=['key', 'value'])
        
        return df_t, df_b, df_s
    except Exception as e:
        st.error(f"DBエラー: {e}")
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

df_trades, df_balance, df_settings = load_data()

# 目標金額の取得
try:
    saved_target = df_settings[df_settings['key'] == 'target_amount']['value'].iloc[0]
    st.session_state.target_amount = float(saved_target)
except:
    if 'target_amount' not in st.session_state:
        st.session_state.target_amount = 1000000.0

import requests
from bs4 import BeautifulSoup
import re

# --- 3. ロジック類 ---
def calculate_assets(balance_data):
    if balance_data.empty: return 0
    balance_data['amount'] = pd.to_numeric(balance_data['amount'], errors='coerce').fillna(0)
    deposits = balance_data[balance_data['type'] == 'DEPOSIT']['amount'].sum()
    withdrawals = balance_data[balance_data['type'] == 'WITHDRAW']['amount'].sum()
    return deposits - withdrawals

def process_data(data):
    holdings = {}
    history = []
    if data.empty: return {}, [], {"win_rate": 0, "ev": 0, "total_pl": 0, "count": 0}
    try: data['date'] = pd.to_datetime(data['date'].astype(str), errors='coerce')
    except: return {}, [], {"win_rate": 0, "ev": 0, "total_pl": 0, "count": 0}
    
    data = data.dropna(subset=['date']).sort_values(by=['date', 'type'], ascending=[True, True])
    
    for _, row in data.iterrows():
        t = str(row['ticker']).strip()
        n = row['name'] if 'name' in row and pd.notna(row['name']) else t
        if t not in holdings: holdings[t] = {"qty": 0, "total_cost": 0, "name": n}
        if 'name' in row and pd.notna(row['name']): holdings[t]["name"] = row['name']
        type_str = str(row['type']).strip().upper()
        
        if type_str == "IN":
            holdings[t]['qty'] += row['qty']
            holdings[t]['total_cost'] += row['price'] * row['qty']
        elif type_str == "OUT":
            if holdings[t]['qty'] > 0:
                avg = holdings[t]['total_cost'] / holdings[t]['qty']
                p_l = (row['price'] - avg) * row['qty']
                history.append({"ticker": t, "name": holdings[t]["name"], "pl": p_l, "date": row['date'], "price": row['price']})
                holdings[t]['qty'] -= row['qty']
                holdings[t]['total_cost'] -= avg * row['qty']
                
    active_holdings = {k: v for k, v in holdings.items() if v['qty'] > 0.001}
    total_pl = sum([h['pl'] for h in history])
    trade_count = len(history)
    wins = len([h for h in history if h['pl'] > 0])
    stats = {"win_rate": (wins/trade_count*100) if trade_count>0 else 0, "ev": (total_pl/trade_count) if trade_count>0 else 0, "total_pl": total_pl, "count": trade_count}
    return active_holdings, history, stats

active_holdings, history_data, global_stats = process_data(df_trades)
base_cash = calculate_assets(df_balance)

if not df_trades.empty:
    df_trades['price'] = pd.to_numeric(df_trades['price'], errors='coerce').fillna(0)
    df_trades['qty'] = pd.to_numeric(df_trades['qty'], errors='coerce').fillna(0)
    spent = df_trades[df_trades['type'] == 'IN'].apply(lambda r: r['price'] * r['qty'], axis=1).sum()
    gained = df_trades[df_trades['type'] == 'OUT'].apply(lambda r: r['price'] * r['qty'], axis=1).sum()
    current_cash = base_cash - spent + gained
else:
    current_cash = base_cash

@st.cache_data(ttl=600)
def get_asset_info(ticker):
    """株と投資信託を自動判別して価格を取得する関数"""
    ticker_str = str(ticker).strip()
    
    # 8桁の英数字（ドットなし）なら投資信託と判定してスクレイピング
    if len(ticker_str) == 8 and '.' not in ticker_str:
        url = f"https://itf.minkabu.jp/fund/{ticker_str}"
        headers = {'User-Agent': 'Mozilla/5.0'}
        try:
            res = requests.get(url, headers=headers, timeout=5)
            soup = BeautifulSoup(res.text, 'html.parser')
            price_elem = soup.select_one('.stock_price')
            if price_elem:
                price_str = re.sub(r'[^\d]', '', price_elem.text)
                return float(price_str), 0, 0.0 # 投信は前日比を一旦0とする
            return None, 0, 0
        except:
            return None, 0, 0
    else:
        # それ以外は個別株と判定してyfinanceを使用
        try:
            s = yf.Ticker(ticker_str)
            hist = s.history(period="2d")
            if hist.empty: return None, 0, 0
            curr = hist['Close'].iloc[-1]
            prev = hist['Close'].iloc[0] if len(hist)>1 else curr
            return curr, curr-prev, ((curr-prev)/prev)*100
        except: return None, 0, 0
else:
    current_cash = base_cash

@st.cache_data(ttl=600)
def get_stock_info(ticker):
    try:
        s = yf.Ticker(ticker)
        hist = s.history(period="2d")
        if hist.empty: return None, 0, 0
        curr = hist['Close'].iloc[-1]
        prev = hist['Close'].iloc[0] if len(hist)>1 else curr
        return curr, curr-prev, ((curr-prev)/prev)*100
    except: return None, 0, 0

# --- 4. サイドバー ---
# URLパラメータ検知（クリック遷移）
if "ticker" in st.query_params:
    st.session_state.target_ticker = st.query_params["ticker"]
    st.session_state.page = "analysis"
    st.query_params.clear()

# --- 4. サイドバー ---
if "ticker" in st.query_params:
    st.session_state.target_ticker = st.query_params["ticker"]
    st.session_state.page = "analysis"
    st.query_params.clear()

with st.sidebar:
    st.header("MENU")
    pages = ["assets", "performance", "analysis", "history", "manage"]
    labels = ["💰 資産状況", "📈 全体成績", "📊 個別分析", "📜 売買ログ", "🔧 データ修正"]
    try: current_index = pages.index(st.session_state.page)
    except: current_index = 0
    selected_label = st.radio("Go to", labels, index=current_index)
    new_page = pages[labels.index(selected_label)]
    if st.session_state.page != new_page:
        st.session_state.page = new_page
        st.rerun()

    st.divider()
    
    # 目標設定の保存
    current_target = st.session_state.target_amount
    new_target = st.number_input("目標資産額 (円)", value=current_target, step=10000.0)
    if new_target != current_target:
        st.session_state.target_amount = new_target
        supabase.table("settings").upsert({"key": "target_amount", "value": str(new_target)}).execute()
        st.toast("目標金額を保存しました！", icon="💾")
    
# データ入力
    with st.expander("📝 データ入力", expanded=False):
        tab1, tab2 = st.tabs(["個別株・投信", "現金"])
        with tab1:
            st.caption("個別株も投資信託もここで入力します")
            with st.form("trade_form", clear_on_submit=True):
                f_d = st.date_input("日付")
                asset_type = st.radio("資産の種類", ["個別株", "投資信託"], horizontal=True)
                
                # Streamlitの仕様上、form内での動的表示切り替えはできないため汎用入力枠にする
                st.info("💡 個別株なら「4005.T」、投信なら協会コード「0331418A」等を入力")
                f_t = st.text_input("コード", "4005.T")
                f_n = st.text_input("銘柄名・ファンド名") 
                f_k = st.selectbox("売買", ["IN", "OUT"])
                f_p = st.number_input("単価・基準価額(円)", 0.0)
                
                st.caption("※個別株なら「株数」、投信なら「買付金額 ÷ 基準価額」の数値を入力")
                f_q = st.number_input("数量 (投信の例: 5万円買付で基準価額2.5万円なら「2」)", 1.0)
                
                if st.form_submit_button("保存"):
                    supabase.table("trades").insert({"date": str(f_d), "ticker": f_t, "name": f_n, "type": f_k, "price": f_p, "qty": f_q}).execute()
                    st.cache_data.clear()
                    st.success("完了")
                    st.rerun()
        with tab2:
            st.caption("証券口座への入出金を記録")
            with st.form("cash_form", clear_on_submit=True):
                c_d = st.date_input("日付")
                c_k = st.selectbox("種別", ["DEPOSIT", "WITHDRAW"], format_func=lambda x: "入金" if x=="DEPOSIT" else "出金")
                c_a = st.number_input("金額", 0)
                c_m = st.text_input("メモ")
                if st.form_submit_button("現金 保存"):
                    supabase.table("balance").insert({"date": str(c_d), "type": c_k, "amount": c_a, "memo": c_m}).execute()
                    st.cache_data.clear()
                    st.success("完了")
                    st.rerun()

# --- 5. メイン画面 ---
page = st.session_state.page

if page == "assets":
    st.title("Asset Overview")
    
    total_stock_value = 0
    total_trust_value = 0
    stock_details = []
    
    for ticker, info in active_holdings.items():
        curr, diff, pct = get_asset_info(ticker)
        if curr is None: curr = info['total_cost']/info['qty']
        val = curr * info['qty']
        avg = info['total_cost']/info['qty']
        u_pl = val - info['total_cost']
        
        is_trust = len(str(ticker)) == 8 and '.' not in str(ticker)
        if is_trust:
            total_trust_value += val
        else:
            total_stock_value += val
            
        stock_details.append({"ticker": ticker, "name": info['name'], "qty": info['qty'], "avg": avg, "curr": curr, "u_pl": u_pl, "val": val, "diff": diff, "pct": pct})

    target_val = st.session_state.target_amount
    total_assets = current_cash + total_trust_value + total_stock_value
    
    p_stock = max(0, min(total_stock_value / target_val, 1.0)) * 100
    p_trust = max(0, min(total_trust_value / target_val, 1.0)) * 100
    p_cash = max(0, min(current_cash / target_val, 1.0)) * 100
    p_total = max(0, min(total_assets / target_val, 1.0)) * 100
    
    st.write(f"**目標達成率: {p_total:.1f}%** (目標: {target_val:,.0f}円)")
    
    st.markdown(f"""
    <div style="position: relative; height: 32px; width: 100%; background-color: #3b3d48; border-radius: 16px; overflow: hidden; margin-bottom: 10px;">
        <div style="display: flex; height: 100%; width: 100%;">
            <div style="width: {p_stock}%; background-color: #ff4b4b;" title="株"></div>
            <div style="width: {p_trust}%; background-color: #2ecc71;" title="投信"></div>
            <div style="width: {p_cash}%; background-color: #00d1ff;" title="現金"></div>
        </div>
        <div style="position: absolute; top: 0; left: 0; width: 100%; height: 100%; display: flex; align-items: center; justify-content: center; color: white; font-weight: bold; font-size: 15px; text-shadow: 1px 1px 3px rgba(0,0,0,0.9); pointer-events: none;">
            現在: {total_assets:,.0f} 円
        </div>
    </div>
    
    <details style="font-size:14px; color:#bdc3c7; margin-bottom:20px; background-color: #262730; padding: 12px; border-radius: 10px; border: 1px solid #3b3d48;">
        <summary style="cursor: pointer; outline: none; font-weight: bold; display: flex; justify-content: space-between; align-items: center;">
            <span>📊 資産の内訳を見る</span>
            <span style="font-size: 12px; color: #e74c3c;">目標まであと: {target_val - total_assets:,.0f}円</span>
        </summary>
        <div style="display:flex; flex-direction: column; gap:8px; margin-top:12px; padding-top: 12px; border-top: 1px solid #3b3d48;">
            <div style="display:flex; justify-content:space-between;">
                <span style="color:#ff4b4b;">■ 国内株</span>
                <span style="color:white; font-weight:bold;">{total_stock_value:,.0f} 円</span>
            </div>
            <div style="display:flex; justify-content:space-between;">
                <span style="color:#2ecc71;">■ 投資信託</span>
                <span style="color:white; font-weight:bold;">{total_trust_value:,.0f} 円</span>
            </div>
            <div style="display:flex; justify-content:space-between;">
                <span style="color:#00d1ff;">■ 現金余力</span>
                <span style="color:white; font-weight:bold;">{current_cash:,.0f} 円</span>
            </div>
        </div>
    </details>
    """, unsafe_allow_html=True)
# --- 5. メイン画面 ---
page = st.session_state.page

if page == "assets":
    st.title("Asset Overview")
    
    total_stock_value = 0
    stock_details = []
    
    for ticker, info in active_holdings.items():
        curr, diff, pct = get_stock_info(ticker)
        if curr is None: curr = info['total_cost']/info['qty']
        val = curr * info['qty']
        total_stock_value += val
        avg = info['total_cost']/info['qty']
        u_pl = val - info['total_cost']
        stock_details.append({"ticker": ticker, "name": info['name'], "qty": info['qty'], "avg": avg, "curr": curr, "u_pl": u_pl, "val": val, "diff": diff, "pct": pct})

    target_val = st.session_state.target_amount
    total_assets = current_cash + current_trust + total_stock_value
    
    p_stock = min(total_stock_value / target_val, 1.0) * 100
    p_trust = min(current_trust / target_val, 1.0) * 100
    p_cash = min(current_cash / target_val, 1.0) * 100
    p_total = min(total_assets / target_val, 1.0) * 100
    
    st.write(f"**目標達成率: {p_total:.1f}%** (目標: {target_val:,.0f}円)")
    
    st.markdown(f"""
    <div style="position: relative; height: 32px; width: 100%; background-color: #3b3d48; border-radius: 16px; overflow: hidden; margin-bottom: 10px;">
        <div style="display: flex; height: 100%; width: 100%;">
            <div style="width: {p_stock}%; background-color: #ff4b4b;" title="株"></div>
            <div style="width: {p_trust}%; background-color: #2ecc71;" title="投信"></div>
            <div style="width: {p_cash}%; background-color: #00d1ff;" title="現金"></div>
        </div>
        <div style="position: absolute; top: 0; left: 0; width: 100%; height: 100%; display: flex; align-items: center; justify-content: center; color: white; font-weight: bold; font-size: 15px; text-shadow: 1px 1px 3px rgba(0,0,0,0.9); pointer-events: none;">
            現在: {total_assets:,.0f} 円
        </div>
    </div>
    
    <details style="font-size:14px; color:#bdc3c7; margin-bottom:20px; background-color: #262730; padding: 12px; border-radius: 10px; border: 1px solid #3b3d48;">
        <summary style="cursor: pointer; outline: none; font-weight: bold; display: flex; justify-content: space-between; align-items: center;">
            <span>📊 資産の内訳を見る</span>
            <span style="font-size: 12px; color: #e74c3c;">目標まであと: {target_val - total_assets:,.0f}円</span>
        </summary>
        <div style="display:flex; flex-direction: column; gap:8px; margin-top:12px; padding-top: 12px; border-top: 1px solid #3b3d48;">
            <div style="display:flex; justify-content:space-between;">
                <span style="color:#ff4b4b;">■ 国内株</span>
                <span style="color:white; font-weight:bold;">{total_stock_value:,.0f} 円</span>
            </div>
            <div style="display:flex; justify-content:space-between;">
                <span style="color:#2ecc71;">■ 投資信託</span>
                <span style="color:white; font-weight:bold;">{current_trust:,.0f} 円</span>
            </div>
            <div style="display:flex; justify-content:space-between;">
                <span style="color:#00d1ff;">■ 現金余力</span>
                <span style="color:white; font-weight:bold;">{current_cash:,.0f} 円</span>
            </div>
        </div>
    </details>
    """, unsafe_allow_html=True)

c1, c2, c3, c4 = st.columns(4)
    c1.metric("総資産", f"{total_assets:,.0f}円")
    c2.metric("国内株", f"{total_stock_value:,.0f}円")
    c3.metric("投資信託", f"{total_trust_value:,.0f}円")
    c4.metric("現金余力", f"{current_cash:,.0f}円")

    st.subheader("保有銘柄")
    if not stock_details: st.info("保有なし")
    
    for s in stock_details:
        u_color = "#089981" if s['u_pl'] >= 0 else "#F23645"
        u_sign = "+" if s['u_pl'] > 0 else ""
        u_bg = "rgba(8, 153, 129, 0.15)" if s['u_pl'] >= 0 else "rgba(242, 54, 69, 0.15)"
        
        d_color = "#089981" if s['diff'] >= 0 else "#F23645"
        d_sign = "+" if s['diff'] > 0 else ""

        link_url = f"?ticker={s['ticker']}"

        card_html = f"""
        <a href="{link_url}" target="_self">
            <div class="stock-card" style="display: flex; flex-direction: column; gap: 8px;">
                <div style="display:flex; justify-content:space-between; align-items:flex-start;">
                    <div style="display:flex; flex-direction:column;">
                        <span style="font-size:18px; font-weight:bold; color:#FAFAFA; line-height:1.2;">{s['name']}</span>
                        <span style="font-size:13px; color:#8b949e;">{s['ticker']}</span>
                    </div>
                    <div style="text-align:right;">
                        <div style="font-size:18px; font-weight:bold; color:#FAFAFA; line-height:1.2;">{s['curr']:,.0f} <span style="font-size:14px; font-weight:normal; color:#8b949e;">円</span></div>
                        <div style="font-size:13px; color:{d_color}; font-weight:500;">{d_sign}{s['diff']:,.0f} ({d_sign}{s['pct']:.2f}%)</div>
                    </div>
                </div>
                <div style="display:flex; justify-content:space-between; align-items:flex-end; margin-top: 4px;">
                    <div style="font-size:12px; color:#8b949e; line-height:1.5;">
                        <div>取得単価: {s['avg']:,.0f}円 × {s['qty']:,}株</div>
                        <div>評価額: <span style="color:#FAFAFA;">{s['val']:,.0f}円</span></div>
                    </div>
                    <div style="background-color: {u_bg}; color:{u_color}; padding: 4px 12px; border-radius: 6px; font-weight:bold; font-size:16px; border: 1px solid {u_color}40;">
                        {u_sign}{s['u_pl']:,.0f} 円
                    </div>
                </div>
            </div>
        </a>
        """.replace('\n', '')

        st.markdown(card_html, unsafe_allow_html=True)

elif page == "performance":
    st.title("Performance")
    c1, c2, c3 = st.columns(3)
    c1.metric("累計確定損益", f"{global_stats['total_pl']:+,.0f}円")
    c2.metric("勝率", f"{global_stats['win_rate']:.1f}%")
    c3.metric("総取引", f"{global_stats['count']}回")
    if history_data:
        df_h = pd.DataFrame(history_data).sort_values('date')
        df_h['cum_pl'] = df_h['pl'].cumsum()
        fig_a = px.area(df_h, x='date', y='cum_pl')
        
        # TradingView風の青色設定
        fig_a.update_traces(line=dict(color='#2962FF', width=2), fillcolor='rgba(41, 98, 255, 0.1)')
        fig_a.update_layout(
            template="plotly_dark", 
            plot_bgcolor='#131722',
            paper_bgcolor='#131722',
            height=300, 
            hovermode="x unified", 
            xaxis=dict(showgrid=True, gridcolor='#2B2B43'),
            yaxis=dict(showgrid=True, gridcolor='#2B2B43', tickformat=",", title="損益"), 
            margin=dict(l=0, r=0, t=30, b=0)
        )
        st.plotly_chart(fig_a, use_container_width=True)

elif page == "analysis":
    st.title("Chart Analysis")
    if not df_trades.empty:
        df_trades['label'] = df_trades['ticker'] + " : " + df_trades['name'].fillna('')
        opts = list(df_trades['label'].unique())
        d_idx = 0
        if st.session_state.target_ticker:
            matches = [i for i, o in enumerate(opts) if st.session_state.target_ticker in o]
            if matches: d_idx = matches[0]
        sel = st.selectbox("銘柄選択", opts, index=d_idx)
        tk = sel.split(" : ")[0]
        st.session_state.target_ticker = tk
        
        time_frame = st.radio("足種", ["1d", "1wk", "1mo"], index=0, horizontal=True, format_func=lambda x: {"1d":"日足","1wk":"週足","1mo":"月足"}[x])
        try:
            data = yf.download(tk, period="2y", interval=time_frame)
            if not data.empty:
                data = data.reset_index()
                if isinstance(data.columns, pd.MultiIndex): data.columns = data.columns.get_level_values(0)
# 25日移動平均線の計算を追加
                data['25MA'] = data['Close'].rolling(window=25).mean()

                fig = go.Figure()
                
                # ローソク足（TradingViewカラー）
                fig.add_trace(go.Candlestick(
                    x=data['Date'], open=data['Open'], high=data['High'], low=data['Low'], close=data['Close'], 
                    increasing_line_color='#089981', decreasing_line_color='#F23645', name="Price"
                ))
                
                # 25日移動平均線（青色）
                fig.add_trace(go.Scatter(
                    x=data['Date'], y=data['25MA'], mode='lines', 
                    name='25日移動平均', line=dict(color='#2962FF', width=1.5), hoverinfo='skip'
                ))

                # 売買マーカーの追加（元のロジックを維持）
                t_d = df_trades[df_trades['ticker'] == tk]
                for _, r in t_d.iterrows():
                    color = "#089981" if r['type']=="IN" else "#F23645" # マーカーの色も合わせる
                    marker = "triangle-up" if r['type']=="IN" else "triangle-down"
                    fig.add_trace(go.Scatter(
                        x=[r['date']], y=[r['price']], mode="markers", 
                        marker=dict(color=color, size=14, symbol=marker, line=dict(color='white', width=1)), 
                        name=r['type'], hovertext=f"{r['type']}<br>{r['date']}<br>{r['price']}円"
                    ))
                
                # TradingView風のレイアウト設定
                fig.update_layout(
                    template="plotly_dark", 
                    plot_bgcolor='#131722',  # 背景色
                    paper_bgcolor='#131722',
                    height=500, 
                    hovermode="x unified", 
                    dragmode="pan", 
                    xaxis=dict(
                        rangeslider=dict(visible=False), # 下のスライダーを消して広く使う
                        type='date', rangebreaks=[dict(bounds=["sat", "mon"])], 
                        tickformat="%Y/%m/%d", spikethickness=1, showspikes=True,
                        showgrid=True, gridcolor='#2B2B43' # 暗めのグリッド線
                    ), 
                    yaxis=dict(
                        fixedrange=False, tickformat=",", side="right", 
                        showspikes=True, spikethickness=1,
                        showgrid=True, gridcolor='#2B2B43'
                    ), 
                    margin=dict(l=10, r=50, t=10, b=10), 
                    modebar=dict(remove=['zoom', 'select', 'lasso', 'autoScale']),
                    showlegend=False # 凡例を隠してスッキリさせる
                )
                fig.update_xaxes(fixedrange=False)
                fig.update_yaxes(fixedrange=False)
                st.plotly_chart(fig, use_container_width=True)
        except Exception as e: st.error(f"Error: {e}")

elif page == "history":
    st.title("History")
    if not df_trades.empty:
        sdf = df_trades.copy()
        sdf['date'] = pd.to_datetime(sdf['date']).dt.strftime('%Y-%m-%d')
        st.dataframe(sdf[['date', 'ticker', 'name', 'type', 'price', 'qty']].style.apply(lambda r: ['background-color: #3d3300']*6 if r['ticker'] in active_holdings else ['']*6, axis=1), use_container_width=True)

        # ... (既存の elif page == "history": ブロックの後に続けてください)

elif page == "manage":
    st.title("🔧 Data Management")
    st.info("セルをダブルクリックして編集し、最後に「保存」ボタンを押してください。行を選択してDeleteキーで削除も可能です。")

    tab1, tab2 = st.tabs(["株取引データ (Trades)", "入出金・投信データ (Balance)"])

    # --- 株取引データの編集 ---
    with tab1:
        st.subheader("Trades Sheet")
        
        # ★★★ 修正ポイント：ここで強制的に型変換します ★★★
        if not df_trades.empty:
            # 日付を日付型に変換
            df_trades['date'] = pd.to_datetime(df_trades['date'], errors='coerce')
            # 数値を数値型に変換（念のため）
            df_trades['price'] = pd.to_numeric(df_trades['price'], errors='coerce').fillna(0)
            df_trades['qty'] = pd.to_numeric(df_trades['qty'], errors='coerce').fillna(0)

        edited_trades = st.data_editor(
            df_trades,
            num_rows="dynamic",
            use_container_width=True,
            key="editor_trades",
            column_config={
                "date": st.column_config.DateColumn("日付", format="YYYY-MM-DD"),
                "price": st.column_config.NumberColumn("単価", format="%d円"),
                "qty": st.column_config.NumberColumn("数量"),
            }
        )
        
        if st.button("株データをスプレッドシートに保存", type="primary", key="save_trades"):
            try:
                save_df = edited_trades.copy()
                # 保存時は文字列（YYYY-MM-DD）に戻す
                save_df['date'] = pd.to_datetime(save_df['date']).dt.strftime('%Y-%m-%d')
                
                conn.update(worksheet="trades", data=save_df)
                st.toast("株データを更新しました！", icon="✅")
                st.cache_data.clear()
                st.rerun()
            except Exception as e:
                st.error(f"保存エラー: {e}")

    # --- 入出金・投信データの編集 ---
    with tab2:
        st.subheader("Balance Sheet (現金・投信)")
        
        # ★★★ 修正ポイント：ここでも型変換します ★★★
        if not df_balance.empty:
            # 日付を日付型に変換
            df_balance['date'] = pd.to_datetime(df_balance['date'], errors='coerce')
            # 金額を数値型に変換
            df_balance['amount'] = pd.to_numeric(df_balance['amount'], errors='coerce').fillna(0)

        edited_balance = st.data_editor(
            df_balance,
            num_rows="dynamic",
            use_container_width=True,
            key="editor_balance",
            column_config={
                "date": st.column_config.DateColumn("日付", format="YYYY-MM-DD"),
                "amount": st.column_config.NumberColumn("金額", format="%d円"),
                "type": st.column_config.SelectboxColumn("種別", options=["DEPOSIT", "WITHDRAW", "TRUST"]),
            }
        )
        
        if st.button("残高データをスプレッドシートに保存", type="primary", key="save_balance"):
            try:
                save_df = edited_balance.copy()
                save_df['date'] = pd.to_datetime(save_df['date']).dt.strftime('%Y-%m-%d')
                
                conn.update(worksheet="balance", data=save_df)
                st.toast("残高データを更新しました！", icon="✅")
                st.cache_data.clear()
                st.rerun()
            except Exception as e:
                st.error(f"保存エラー: {e}")



























