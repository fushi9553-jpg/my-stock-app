import streamlit as st
from streamlit_gsheets import GSheetsConnection
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from datetime import datetime

# 1. ページ設定
st.set_page_config(page_title="My Portfolio App", layout="wide", initial_sidebar_state="collapsed")

# --- セッション状態の初期化 ---
if 'page' not in st.session_state: st.session_state.page = "assets"
if 'target_ticker' not in st.session_state: st.session_state.target_ticker = None
# 目標金額は後でロードするので初期値は仮置き

# ★★★ CSSデザイン（青線削除・カード分離） ★★★
st.markdown("""
    <style>
    .main { background-color: #0e1117; color: white; }
    
    /* リンクの青線・下線を強制的に消す */
    a { text-decoration: none !important; color: inherit !important; }
    a:hover { text-decoration: none !important; color: inherit !important; }
    
    /* カードのデザイン */
    .stock-card {
        background-color: #262730;
        padding: 15px;
        border-radius: 10px;
        margin-bottom: 10px;
        border: 1px solid #3b3d48;
        transition: transform 0.1s, border-color 0.1s;
        color: white; /* 文字色を白で固定 */
        text-decoration: none; /* 下線を消す */
    }
    .stock-card:hover {
        border-color: #2ecc71;
        transform: translateY(-2px);
        cursor: pointer;
    }

    /* メトリック（上部の数字カード）のデザイン */
    .stMetric {
        background-color: #262730;
        padding: 15px;
        border-radius: 8px;
        border-left: 5px solid #2ecc71;
        box-shadow: 0 2px 4px rgba(0,0,0,0.2);
    }
    </style>
    """, unsafe_allow_html=True)

# --- 2. データ読み込み ---
conn = st.connection("gsheets", type=GSheetsConnection)

@st.cache_data(ttl=600)
def load_data():
    try:
        df_t = conn.read(worksheet="trades", ttl=0)
        try: df_b = conn.read(worksheet="balance", ttl=0)
        except: df_b = pd.DataFrame(columns=['date', 'type', 'amount', 'memo'])
        try: df_s = conn.read(worksheet="settings", ttl=0)
        except: df_s = pd.DataFrame(columns=['key', 'value'])
        return df_t, df_b, df_s
    except Exception as e:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

df_trades, df_balance, df_settings = load_data()

# 目標金額の取得（設定シートから）
try:
    saved_target = df_settings[df_settings['key'] == 'target_amount']['value'].iloc[0]
    st.session_state.target_amount = float(saved_target)
except:
    if 'target_amount' not in st.session_state:
        st.session_state.target_amount = 1000000.0

# --- 3. ロジック類 ---
def calculate_assets(balance_data):
    if balance_data.empty: return 0, 0
    balance_data['amount'] = pd.to_numeric(balance_data['amount'], errors='coerce').fillna(0)
    
    deposits = balance_data[balance_data['type'] == 'DEPOSIT']['amount'].sum()
    withdrawals = balance_data[balance_data['type'] == 'WITHDRAW']['amount'].sum()
    cash = deposits - withdrawals
    
    trust_data = balance_data[balance_data['type'] == 'TRUST'].sort_values('date')
    current_trust = trust_data.iloc[-1]['amount'] if not trust_data.empty else 0
    return cash, current_trust

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
current_cash, current_trust = calculate_assets(df_balance)

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

with st.sidebar:
    st.header("MENU")
    
    pages = ["assets", "performance", "analysis", "history"]
    labels = ["💰 資産状況", "📈 全体成績", "📊 個別分析", "📜 売買ログ"]
    
    try: current_index = pages.index(st.session_state.page)
    except: current_index = 0
    selected_label = st.radio("Go to", labels, index=current_index)
    
    new_page = pages[labels.index(selected_label)]
    if st.session_state.page != new_page:
        st.session_state.page = new_page
        st.rerun()

    st.divider()
    
    # 目標設定（DB保存機能付き）
    current_target = st.session_state.target_amount
    new_target = st.number_input("目標資産額 (円)", value=current_target, step=10000.0)
    
    # 値が変わっていたらスプレッドシートを更新
    if new_target != current_target:
        st.session_state.target_amount = new_target
        # settingsシートを更新
        new_settings = pd.DataFrame([{'key': 'target_amount', 'value': new_target}])
        conn.update(worksheet="settings", data=new_settings)
        st.toast("目標金額を保存しました！", icon="💾")
    
    # データ入力
    with st.expander("📝 データ入力", expanded=False):
        tab1, tab2, tab3 = st.tabs(["株", "現金", "投信"])
        with tab1:
            with st.form("trade_form", clear_on_submit=True):
                f_d = st.date_input("日付")
                f_t = st.text_input("コード", "6269.T")
                f_n = st.text_input("銘柄名") 
                f_k = st.selectbox("売買", ["IN", "OUT"])
                f_p = st.number_input("単価", 0.0)
                f_q = st.number_input("数量", 100)
                if st.form_submit_button("株 保存"):
                    nd = pd.DataFrame([{"date": f_d, "ticker": f_t, "name": f_n, "type": f_k, "price": f_p, "qty": f_q}])
                    conn.update(worksheet="trades", data=pd.concat([df_trades, nd], ignore_index=True))
                    st.cache_data.clear()
                    st.success("完了")
                    st.rerun()
        with tab2:
            st.caption("入出金を記録")
            with st.form("cash_form", clear_on_submit=True):
                c_d = st.date_input("日付")
                c_k = st.selectbox("種別", ["DEPOSIT", "WITHDRAW"], format_func=lambda x: "入金" if x=="DEPOSIT" else "出金")
                c_a = st.number_input("金額", 0)
                c_m = st.text_input("メモ")
                if st.form_submit_button("現金 保存"):
                    nb = pd.DataFrame([{"date": c_d, "type": c_k, "amount": c_a, "memo": c_m}])
                    conn.update(worksheet="balance", data=pd.concat([df_balance, nb], ignore_index=True))
                    st.cache_data.clear()
                    st.success("完了")
                    st.rerun()
        with tab3:
            st.caption("現在の評価額を入力")
            with st.form("trust_form", clear_on_submit=True):
                t_d = st.date_input("日付")
                t_a = st.number_input("現在の評価額合計", 0)
                if st.form_submit_button("投信 更新"):
                    nb = pd.DataFrame([{"date": t_d, "type": "TRUST", "amount": t_a, "memo": "残高更新"}])
                    conn.update(worksheet="balance", data=pd.concat([df_balance, nb], ignore_index=True))
                    st.cache_data.clear()
                    st.success("完了")
                    st.rerun()

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
    
    st.write(f"**目標達成率: {(total_assets/target_val)*100:.1f}%** (目標: {target_val:,.0f}円)")
    st.markdown(f"""
    <div style="display: flex; height: 25px; width: 100%; background-color: #3b3d48; border-radius: 12px; overflow: hidden; margin-bottom: 5px;">
        <div style="width: {p_stock}%; background-color: #ff4b4b;" title="株"></div>
        <div style="width: {p_trust}%; background-color: #2ecc71;" title="投信"></div>
        <div style="width: {p_cash}%; background-color: #00d1ff;" title="現金"></div>
    </div>
    <div style="display:flex; justify-content:space-between; font-size:12px; color:#bdc3c7; margin-bottom:20px;">
        <div style="display:flex; gap:10px;">
            <span style="color:#ff4b4b;">■ 株: {total_stock_value:,.0f}</span>
            <span style="color:#2ecc71;">■ 投信: {current_trust:,.0f}</span>
            <span style="color:#00d1ff;">■ 現金: {current_cash:,.0f}</span>
        </div>
        <span>あと: {target_val - total_assets:,.0f}円</span>
    </div>""", unsafe_allow_html=True)

    # ★★★ ここでカードを4つに分割 ★★★
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("総資産", f"{total_assets:,.0f}円")
    c2.metric("国内株", f"{total_stock_value:,.0f}円")
    c3.metric("投資信託", f"{current_trust:,.0f}円")
    c4.metric("現金余力", f"{current_cash:,.0f}円")

    st.subheader("保有銘柄")
    if not stock_details: st.info("保有なし")
    
    for s in stock_details:
        u_color = "#ff4b4b" if s['u_pl'] > 0 else "#00d1ff"
        u_sign = "+" if s['u_pl'] > 0 else ""
        d_color = "#ff4b4b" if s['diff'] > 0 else "#00d1ff"
        d_sign = "+" if s['diff'] > 0 else ""

        link_url = f"?ticker={s['ticker']}"

        # CSSで a { text-decoration: none } を指定したので、青線は消えます
        card_html = f"""
        <a href="{link_url}" target="_self">
            <div class="stock-card">
                <div style="display:flex; justify-content:space-between; align-items:center;">
                    <div>
                        <span style="font-size:18px; font-weight:bold; color:white;">{s['name']}</span>
                        <span style="font-size:14px; color:#ccc; margin-left:5px;">{s['ticker']}</span>
                    </div>
                    <div style="display:flex; justify-content:space-between; margin-top:5px;">
                        <span style="color:#ddd;">現在: {s['curr']:,.0f}円 <span style="color:{d_color};">({d_sign}{s['diff']:,.0f} / {d_sign}{s['pct']:.1f}%)</span></span>
                    </div>
                </div>
                <div style="display:flex; justify-content:space-between; align-items:center; margin-top:5px;">
                    <div style="font-size:12px; color:#888;">
                        評価額: {s['val']:,.0f}円 | 取得: {s['avg']:,.0f}円 | {s['qty']:,}株
                    </div>
                    <div>
                        <span style="color:{u_color}; font-weight:bold; font-size:20px;">{u_sign}{s['u_pl']:,.0f}円</span>
                    </div>
                </div>
            </div>
        </a>
        """
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
        fig_a.update_traces(line=dict(color='#2ecc71', width=2), fillcolor='rgba(46, 204, 113, 0.1)')
        fig_a.update_layout(template="plotly_dark", height=300, hovermode="x unified", xaxis=dict(showgrid=False), yaxis=dict(tickformat=",", title="損益"), margin=dict(l=0, r=0, t=30, b=0))
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
                fig = go.Figure(data=[go.Candlestick(x=data['Date'], open=data['Open'], high=data['High'], low=data['Low'], close=data['Close'], increasing_line_color='#ff4b4b', decreasing_line_color='#00d1ff', name="Price")])
                t_d = df_trades[df_trades['ticker'] == tk]
                for _, r in t_d.iterrows():
                    color = "#ff4b4b" if r['type']=="IN" else "#00d1ff"
                    marker = "triangle-up" if r['type']=="IN" else "triangle-down"
                    fig.add_trace(go.Scatter(x=[r['date']], y=[r['price']], mode="markers", marker=dict(color=color, size=14, symbol=marker, line=dict(color='white', width=1)), name=r['type'], hovertext=f"{r['type']}<br>{r['date']}<br>{r['price']}円"))
                fig.update_layout(template="plotly_dark", height=500, hovermode="x unified", dragmode="pan", xaxis=dict(rangeslider=dict(visible=True), type='date', rangebreaks=[dict(bounds=["sat", "mon"])], tickformat="%Y/%m/%d", spikethickness=1, showspikes=True), yaxis=dict(fixedrange=False, tickformat=",", side="right", showspikes=True, spikethickness=1), margin=dict(l=10, r=50, t=10, b=10), modebar=dict(remove=['zoom', 'select', 'lasso', 'autoScale']))
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





