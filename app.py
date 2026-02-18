import streamlit as st
from streamlit_gsheets import GSheetsConnection
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from datetime import datetime

# 1. ページ設定（サイドバーをデフォルトで閉じる）
st.set_page_config(page_title="My Portfolio App", layout="wide", initial_sidebar_state="collapsed")

if 'target_ticker' not in st.session_state:
    st.session_state['target_ticker'] = None

# デザイン設定（ボタンをカード幅いっぱいに広げるなど）
st.markdown("""
    <style>
    .main { background-color: #0e1117; color: white; }
    .stMetric { background-color: #262730; padding: 15px; border-radius: 8px; border-left: 5px solid #2ecc71; }
    .stock-card { background-color: #262730; padding: 15px; border-radius: 10px; margin-bottom: 5px; border: 1px solid #3b3d48; }
    /* 分析ボタンを大きく目立たせる */
    .stButton button { width: 100%; border-radius: 5px; font-weight: bold; border: 1px solid #4e505e; }
    button[data-baseweb="tab"] { font-size: 16px; font-weight: bold; }
    </style>
    """, unsafe_allow_html=True)

# --- 2. データ読み込み ---
conn = st.connection("gsheets", type=GSheetsConnection)
df_trades = conn.read(worksheet="trades", ttl=0)
try:
    df_balance = conn.read(worksheet="balance", ttl=0)
except:
    # balanceシートがまだない場合のエラー回避
    df_balance = pd.DataFrame(columns=['date', 'type', 'amount', 'memo'])

# --- 3. ロジック類 ---

# 現金残高の計算
def calculate_cash(balance_data):
    if balance_data.empty: return 0
    balance_data['amount'] = pd.to_numeric(balance_data['amount'], errors='coerce').fillna(0)
    deposits = balance_data[balance_data['type'] == 'DEPOSIT']['amount'].sum()
    withdrawals = balance_data[balance_data['type'] == 'WITHDRAW']['amount'].sum()
    # 株の売買による現金増減も計算すべきですが、今回は簡易的に「入出金」のみ管理します
    # (本格的にやるなら売買代金もここに入れる必要がありますが、まずは資産総額の補正用として)
    return deposits - withdrawals

# データの処理
def process_data(data):
    holdings = {}
    history = []
    if data.empty: return {}, [], {"win_rate": 0, "ev": 0, "total_pl": 0, "count": 0}
    try:
        data['date'] = pd.to_datetime(data['date'].astype(str), errors='coerce')
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
current_cash = calculate_cash(df_balance)

@st.cache_data(ttl=600)
def get_stock_price(ticker):
    try:
        s = yf.Ticker(ticker)
        h = s.history(period="1d")
        return h['Close'].iloc[-1] if not h.empty else None
    except: return None

# --- 4. サイドバー (入力系) ---
with st.sidebar:
    st.header("🔧 管理メニュー")
    
    # 目標設定
    target_amount = st.number_input("目標資産額 (円)", value=1000000, step=10000)
    
    st.divider()
    
    # 1. 株トレード入力
    with st.expander("📈 株トレード入力", expanded=False):
        with st.form("add_trade", clear_on_submit=True):
            f_date = st.date_input("取引日", datetime.now())
            f_ticker = st.text_input("銘柄コード", "6269.T")
            f_name = st.text_input("銘柄名", "") 
            f_type = st.selectbox("売買", ["IN", "OUT"])
            f_price = st.number_input("単価", value=0.0)
            f_qty = st.number_input("数量", value=100)
            if st.form_submit_button("トレード保存"):
                new_data = pd.DataFrame([{"date": f_date, "ticker": f_ticker, "name": f_name, "type": f_type, "price": f_price, "qty": f_qty}])
                conn.update(worksheet="trades", data=pd.concat([df_trades, new_data], ignore_index=True))
                st.success("保存完了")
                st.rerun()

    # 2. 現金入出金
    with st.expander("💰 現金・入出金", expanded=False):
        with st.form("add_cash", clear_on_submit=True):
            c_date = st.date_input("日付", datetime.now())
            c_type = st.selectbox("種別", ["DEPOSIT", "WITHDRAW"], format_func=lambda x: "入金" if x=="DEPOSIT" else "出金")
            c_amount = st.number_input("金額", value=0)
            c_memo = st.text_input("メモ (給料など)")
            if st.form_submit_button("現金情報の保存"):
                new_balance = pd.DataFrame([{"date": c_date, "type": c_type, "amount": c_amount, "memo": c_memo}])
                conn.update(worksheet="balance", data=pd.concat([df_balance, new_balance], ignore_index=True))
                st.success("更新完了")
                st.rerun()

# --- 5. メイン画面 ---
tab1, tab2, tab3, tab4 = st.tabs(["💰 資産状況", "📈 全体成績", "📊 個別分析", "📜 売買ログ"])

# 【タブ1】資産状況 (目標バー追加)
with tab1:
    st.title("Asset Overview")
    
    # 資産総額の計算
    total_stock_value = 0
    stock_details = []
    
    # 最新価格取得と計算
    for ticker, info in active_holdings.items():
        curr = get_stock_price(ticker) or (info['total_cost']/info['qty'])
        val = curr * info['qty']
        total_stock_value += val
        
        avg = info['total_cost']/info['qty']
        u_pl = val - info['total_cost']
        stock_details.append({
            "ticker": ticker, "name": info['name'], "qty": info['qty'],
            "avg": avg, "curr": curr, "u_pl": u_pl, "val": val
        })

    total_assets = current_cash + total_stock_value
    
    # 目標達成度ゲージ
    progress = min(total_assets / target_amount, 1.0)
    st.write(f"**目標達成率: {progress*100:.1f}%** (目標: {target_amount:,.0f}円)")
    # 赤(半分以上)・青(半分以下)のロジック
    bar_color = "#ff4b4b" if progress >= 0.5 else "#00d1ff"
    st.markdown(f"""
    <div style="background-color: #3b3d48; border-radius: 10px; height: 20px; width: 100%;">
        <div style="background-color: {bar_color}; width: {progress*100}%; height: 100%; border-radius: 10px; opacity: 0.8;"></div>
    </div>
    <div style="display:flex; justify-content:space-between; margin-top:5px; margin-bottom:20px;">
        <span>現在: {total_assets:,.0f}円</span>
        <span>あと: {target_amount - total_assets:,.0f}円</span>
    </div>
    """, unsafe_allow_html=True)

    # 資産内訳
    col_a, col_b = st.columns(2)
    col_a.metric("総資産", f"{total_assets:,.0f}円")
    col_b.metric("現金余力", f"{current_cash:,.0f}円")

    st.subheader("保有銘柄")
    if not stock_details: st.info("保有なし")
    for s in stock_details:
        p_color = '#ff4b4b' if s['u_pl'] > 0 else '#00d1ff'
        # カードレイアウト（分析ボタンを統合）
        with st.container():
            col_info, col_act = st.columns([4, 1])
            with col_info:
                st.markdown(f"""
                <div class="stock-card">
                    <div style="display:flex; justify-content:space-between;">
                        <div><span style="font-size:18px; font-weight:bold;">{s['name']}</span> <span style="color:#888;">{s['ticker']}</span></div>
                        <div style="text-align:right;"><span style="color:{p_color}; font-weight:bold;">{s['u_pl']:+,.0f}円</span></div>
                    </div>
                    <div style="display:flex; justify-content:space-between; font-size:13px; color:#ccc; margin-top:5px;">
                        <span>評価額: {s['val']:,.0f}円</span>
                        <span>現在値: {s['curr']:,.0f}円</span>
                        <span>取得単価: {s['avg']:,.0f}円</span>
                    </div>
                </div>
                """, unsafe_allow_html=True)
            with col_act:
                # 分析ボタン（カードの横に配置して押しやすく）
                st.write("") # スペース調整
                if st.button("分析 ➡", key=f"btn_{s['ticker']}"):
                    st.session_state['target_ticker'] = s['ticker']
                    st.rerun()

# 【タブ2】全体成績
with tab2:
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
        # シンプルで見やすいチャート設定
        fig_a.update_layout(
            template="plotly_dark", height=300, 
            hovermode="x unified", # 十字線
            xaxis=dict(showgrid=False),
            yaxis=dict(tickformat=",", title="損益"),
            margin=dict(l=0, r=0, t=30, b=0)
        )
        st.plotly_chart(fig_a, use_container_width=True)

# 【タブ3】個別分析 (プロ仕様チャート)
with tab3:
    st.title("Chart Analysis")
    if not df_trades.empty:
        df_trades['label'] = df_trades['ticker'] + " : " + df_trades['name'].fillna('')
        opts = list(df_trades['label'].unique())
        # セッションから選択状態を復元
        d_idx = 0
        if st.session_state['target_ticker']:
            matches = [i for i, o in enumerate(opts) if st.session_state['target_ticker'] in o]
            if matches: d_idx = matches[0]
            
        sel = st.selectbox("銘柄選択", opts, index=d_idx)
        tk = sel.split(" : ")[0]
        
        # 時間足選択
        time_frame = st.radio("足種", ["1d", "1wk", "1mo"], index=0, horizontal=True, format_func=lambda x: {"1d":"日足","1wk":"週足","1mo":"月足"}[x])
        
        try:
            # データを長期間取得
            data = yf.download(tk, period="2y", interval=time_frame)
            if not data.empty:
                data = data.reset_index()
                if isinstance(data.columns, pd.MultiIndex): data.columns = data.columns.get_level_values(0)
                
                # ローソク足
                fig = go.Figure(data=[go.Candlestick(
                    x=data['Date'], open=data['Open'], high=data['High'], low=data['Low'], close=data['Close'],
                    increasing_line_color='#ff4b4b', decreasing_line_color='#00d1ff', name="Price"
                )])

                # 売買ポイント表示（線で結ぶのは平均取得単価ロジックだと不正確になるため、マーカーのみ強化）
                t_d = df_trades[df_trades['ticker'] == tk]
                for _, r in t_d.iterrows():
                    color = "#ff4b4b" if r['type']=="IN" else "#00d1ff"
                    marker = "triangle-up" if r['type']=="IN" else "triangle-down"
                    fig.add_trace(go.Scatter(
                        x=[r['date']], y=[r['price']], mode="markers",
                        marker=dict(color=color, size=14, symbol=marker, line=dict(color='white', width=1)),
                        name=r['type'],
                        hovertext=f"{r['type']}<br>{r['date']}<br>{r['price']}円"
                    ))

                # プロ仕様のレイアウト設定
                fig.update_layout(
                    template="plotly_dark", 
                    height=500, 
                    hovermode="x unified", # 縦のクロスヘア（十字線）
                    dragmode="pan", # チャート自体のドラッグ移動を許可（スライダーもあるが直感的）
                    xaxis=dict(
                        rangeslider=dict(visible=True), # 下のスライダー
                        type='date', 
                        rangebreaks=[dict(bounds=["sat", "mon"])], # 土日非表示
                        tickformat="%Y/%m/%d",
                        spikethickness=1, showspikes=True, # 縦線
                    ),
                    yaxis=dict(
                        fixedrange=False, # 縦軸の自動調整
                        tickformat=",", 
                        side="right", # 目盛りを右側に（プロツール風）
                        showspikes=True, spikethickness=1 # 横線
                    ),
                    margin=dict(l=10, r=50, t=10, b=10),
                    # モードバー（右上のメニュー）を整理
                    modebar=dict(remove=['zoom', 'select', 'lasso', 'autoScale']) 
                )
                # マウスホイールでのズームを有効化
                fig.update_xaxes(fixedrange=False)
                fig.update_yaxes(fixedrange=False)

                st.plotly_chart(fig, use_container_width=True)
        except Exception as e:
            st.error(f"チャート表示エラー: {e}")

# 【タブ4】売買ログ
with tab4:
    st.title("Transaction History")
    if not df_trades.empty:
        sdf = df_trades.copy()
        sdf['date'] = pd.to_datetime(sdf['date']).dt.strftime('%Y-%m-%d')
        # 保有中の銘柄をハイライト
        st.dataframe(sdf[['date', 'ticker', 'name', 'type', 'price', 'qty']].style.apply(lambda r: ['background-color: #3d3300']*6 if r['ticker'] in active_holdings else ['']*6, axis=1), use_container_width=True)
