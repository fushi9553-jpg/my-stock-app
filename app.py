import streamlit as st
from streamlit_gsheets import GSheetsConnection
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from datetime import datetime

# 1. ページ設定
st.set_page_config(page_title="My Portfolio App", layout="wide", initial_sidebar_state="collapsed")

# セッション状態の初期化
if 'page' not in st.session_state: st.session_state.page = "assets"
if 'target_ticker' not in st.session_state: st.session_state.target_ticker = None

# デザイン設定
st.markdown("""
    <style>
    .main { background-color: #0e1117; color: white; }
    .stMetric { background-color: #262730; padding: 10px; border-radius: 8px; border-left: 5px solid #2ecc71; }
    /* ボタンのスタイル調整 */
    div.stButton > button {
        width: 100%;
        border-radius: 8px;
        height: auto;
        padding: 10px;
        border: 1px solid #3b3d48;
        background-color: #262730;
        text-align: left;
    }
    div.stButton > button:hover {
        border-color: #2ecc71;
        color: #2ecc71;
    }
    </style>
    """, unsafe_allow_html=True)

# --- 2. データ読み込み（エラー対策：キャッシュ化） ---
@st.cache_data(ttl=600) # 10分間データを記憶してAPI制限を防ぐ
def load_data():
    conn = st.connection("gsheets", type=GSheetsConnection)
    try:
        # tradesシート読み込み
        df_t = conn.read(worksheet="trades", ttl=0)
        # balanceシート読み込み（なければ空を作成）
        try:
            df_b = conn.read(worksheet="balance", ttl=0)
        except:
            df_b = pd.DataFrame(columns=['date', 'type', 'amount', 'memo'])
        return df_t, df_b
    except Exception as e:
        st.error(f"スプレッドシートの読み込みに失敗しました。URLやシート名を確認してください。\nエラー内容: {e}")
        return pd.DataFrame(), pd.DataFrame()

df_trades, df_balance = load_data()

# --- 3. ロジック類 ---

def calculate_assets(balance_data):
    if balance_data.empty: return 0, 0
    balance_data['amount'] = pd.to_numeric(balance_data['amount'], errors='coerce').fillna(0)
    deposits = balance_data[balance_data['type'] == 'DEPOSIT']['amount'].sum()
    withdrawals = balance_data[balance_data['type'] == 'WITHDRAW']['amount'].sum()
    cash = deposits - withdrawals
    trusts = balance_data[balance_data['type'] == 'TRUST']['amount'].sum()
    return cash, trusts

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
        current = hist['Close'].iloc[-1]
        prev_close = hist['Close'].iloc[0] if len(hist) > 1 else current
        diff = current - prev_close
        pct = (diff / prev_close) * 100
        return current, diff, pct
    except: return None, 0, 0

# --- 4. サイドバー ---
conn = st.connection("gsheets", type=GSheetsConnection) # 更新用コネクション

with st.sidebar:
    st.header("MENU")
    page_options = {"assets": "💰 資産状況", "performance": "📈 全体成績", "analysis": "📊 個別分析", "history": "📜 売買ログ"}
    selection = st.radio("Go to", list(page_options.keys()), format_func=lambda x: page_options[x], key="nav_radio")
    if st.session_state.page != selection:
        st.session_state.page = selection
        st.rerun()

    st.divider()
    target_amount = st.number_input("目標資産額 (円)", value=1000000, step=10000)
    
    with st.expander("📝 データ入力", expanded=False):
        tab_in1, tab_in2 = st.tabs(["株", "現金/投信"])
        with tab_in1:
            with st.form("add_trade", clear_on_submit=True):
                f_date = st.date_input("取引日", datetime.now())
                f_ticker = st.text_input("コード", "6269.T")
                f_name = st.text_input("銘柄名", "") 
                f_type = st.selectbox("売買", ["IN", "OUT"])
                f_price = st.number_input("単価", value=0.0)
                f_qty = st.number_input("数量", value=100)
                if st.form_submit_button("株 保存"):
                    new_data = pd.DataFrame([{"date": f_date, "ticker": f_ticker, "name": f_name, "type": f_type, "price": f_price, "qty": f_qty}])
                    conn.update(worksheet="trades", data=pd.concat([df_trades, new_data], ignore_index=True))
                    st.cache_data.clear() # 更新したらキャッシュを消す
                    st.success("完了")
                    st.rerun()
        with tab_in2:
            with st.form("add_cash", clear_on_submit=True):
                c_date = st.date_input("日付", datetime.now())
                c_type = st.selectbox("種別", ["DEPOSIT", "WITHDRAW", "TRUST"], format_func=lambda x: {"DEPOSIT":"入金","WITHDRAW":"出金","TRUST":"投資信託(評価額)"}[x])
                c_amount = st.number_input("金額", value=0)
                c_memo = st.text_input("メモ")
                if st.form_submit_button("資産 保存"):
                    new_balance = pd.DataFrame([{"date": c_date, "type": c_type, "amount": c_amount, "memo": c_memo}])
                    conn.update(worksheet="balance", data=pd.concat([df_balance, new_balance], ignore_index=True))
                    st.cache_data.clear() # 更新したらキャッシュを消す
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

    total_assets = current_cash + current_trust + total_stock_value
    p_stock = min(total_stock_value / target_amount, 1.0) * 100
    p_trust = min(current_trust / target_amount, 1.0) * 100
    p_cash = min(current_cash / target_amount, 1.0) * 100
    
    st.write(f"**目標達成率: {(total_assets/target_amount)*100:.1f}%** (目標: {target_amount:,.0f}円)")
    st.markdown(f"""
    <div style="display: flex; height: 25px; width: 100%; background-color: #3b3d48; border-radius: 12px; overflow: hidden; margin-bottom: 5px;">
        <div style="width: {p_stock}%; background-color: #ff4b4b;"></div>
        <div style="width: {p_trust}%; background-color: #2ecc71;"></div>
        <div style="width: {p_cash}%; background-color: #00d1ff;"></div>
    </div>
    <div style="display:flex; justify-content:space-between; font-size:12px; color:#bdc3c7; margin-bottom:20px;">
        <div style="display:flex; gap:15px;">
            <span style="color:#ff4b4b;">■ 株: {total_stock_value:,.0f}円</span>
            <span style="color:#2ecc71;">■ 投信: {current_trust:,.0f}円</span>
            <span style="color:#00d1ff;">■ 現金: {current_cash:,.0f}円</span>
        </div>
        <span>あと: {target_amount - total_assets:,.0f}円</span>
    </div>""", unsafe_allow_html=True)

    c1, c2, c3 = st.columns(3)
    c1.metric("総資産", f"{total_assets:,.0f}円")
    c2.metric("国内株評価額", f"{total_stock_value:,.0f}円")
    c3.metric("現金・投信", f"{current_cash + current_trust:,.0f}円")

    st.subheader("保有銘柄")
    if not stock_details: st.info("保有なし")
    for s in stock_details:
        # 含み損益の色（赤/青）
        u_color_code = "#ff4b4b" if s['u_pl'] > 0 else "#00d1ff"
        u_sign = "+" if s['u_pl'] > 0 else ""
        
        # 前日比の色（赤/青）
        d_color_code = "#ff4b4b" if s['diff'] > 0 else "#00d1ff"
        d_sign = "+" if s['diff'] > 0 else ""

        # HTML整形
        btn_label = f"""
        <div style="font-family: sans-serif;">
            <div style="display:flex; justify-content:space-between; align-items:center;">
                <span style="font-size:18px; font-weight:bold; color:white;">{s['name']}</span>
                <span style="font-size:14px; color:#ccc;">{s['ticker']}</span>
            </div>
            <div style="display:flex; justify-content:space-between; margin-top:5px;">
                <span style="color:#ddd;">現在: {s['curr']:,.0f}円 <span style="color:{d_color_code};">({d_sign}{s['diff']:,.0f} / {d_sign}{s['pct']:.1f}%)</span></span>
                <span style="color:{u_color_code}; font-weight:bold; font-size:16px;">{u_sign}{s['u_pl']:,.0f}円</span>
            </div>
            <div style="font-size:12px; color:#888; margin-top:2px;">
                評価額: {s['val']:,.0f}円 | 取得: {s['avg']:,.0f}円 | {s['qty']:,}株
            </div>
        </div>
        """
        if st.button(btn_label, key=f"card_{s['ticker']}", use_container_width=True):
            st.session_state.target_ticker = s['ticker']
            st.session_state.page = "analysis"
            st.rerun()

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


