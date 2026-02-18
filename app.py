import streamlit as st
from streamlit_gsheets import GSheetsConnection
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime

# 1. ページ設定
st.set_page_config(page_title="Personal KaView Clone", layout="wide")

# カビュウ風ダークデザイン
st.markdown("""
    <style>
    .main { background-color: #121d2b; color: white; }
    .stMetric { background-color: #1e2e3e; padding: 15px; border-radius: 10px; border-left: 5px solid #2ecc71; }
    .stock-card { background-color: #1e2e3e; padding: 15px; border-radius: 10px; margin-bottom: 10px; border: 1px solid #34495e; }
    </style>
    """, unsafe_allow_html=True)

# --- 2. スプレッドシート接続とデータ読み込み ---
conn = st.connection("gsheets", type=GSheetsConnection)
df = conn.read(worksheet="trades", ttl=0)

# --- 3. ロジック：保有資産と確定損益の計算 ---
def process_data(data):
    holdings = {}
    history = []
    
    if data.empty:
        return {}, []
        
    data['date'] = pd.to_datetime(data['date'].astype(str), format='mixed', errors='coerce')
    
    # 万が一、変なデータがあって日付に変換できなかった行は削除して無視する（安全策）
    data = data.dropna(subset=['date'])
    
    # 日付でソート
    data = data.sort_values('date')
    
    for _, row in data.iterrows():
        t = row['ticker']
        if t not in holdings: holdings[t] = {"qty": 0, "total_cost": 0}
        
        if row['type'] == "IN":
            holdings[t]['qty'] += row['qty']
            holdings[t]['total_cost'] += row['price'] * row['qty']
        elif row['type'] == "OUT":
            if holdings[t]['qty'] > 0:
                avg_price = holdings[t]['total_cost'] / holdings[t]['qty']
                p_l = (row['price'] - avg_price) * row['qty']
                history.append({"ticker": t, "pl": p_l, "date": row['date'], "price": row['price']})
                holdings[t]['qty'] -= row['qty']
                holdings[t]['total_cost'] -= avg_price * row['qty']
            
    active_holdings = {k: v for k, v in holdings.items() if v['qty'] > 0}
    return active_holdings, history
    
    # 日付でソート
    data['date'] = pd.to_datetime(data['date'])
    data = data.sort_values('date')
    
    for _, row in data.iterrows():
        t = row['ticker']
        if t not in holdings: holdings[t] = {"qty": 0, "total_cost": 0}
        
        if row['type'] == "IN":
            holdings[t]['qty'] += row['qty']
            holdings[t]['total_cost'] += row['price'] * row['qty']
        elif row['type'] == "OUT":
            if holdings[t]['qty'] > 0:
                avg_price = holdings[t]['total_cost'] / holdings[t]['qty']
                p_l = (row['price'] - avg_price) * row['qty']
                history.append({"ticker": t, "pl": p_l, "date": row['date'], "price": row['price']})
                holdings[t]['qty'] -= row['qty']
                holdings[t]['total_cost'] -= avg_price * row['qty']
            
    active_holdings = {k: v for k, v in holdings.items() if v['qty'] > 0}
    return active_holdings, history

active_holdings, history_data = process_data(df)

# --- 4. サイドバー：売買入力フォーム ---
with st.sidebar:
    st.header("📥 トレード記録")
    with st.form("add_trade", clear_on_submit=True):
        f_ticker = st.text_input("銘柄コード (例: 6269.T)", "6269.T")
        f_date = st.date_input("取引日", datetime.now())
        f_type = st.selectbox("売買", ["IN", "OUT"])
        f_price = st.number_input("単価", value=0.0)
        f_qty = st.number_input("数量", value=100)
        
        if st.form_submit_button("スプレッドシートへ保存"):
            new_entry = pd.DataFrame([{
                "date": str(f_date), "ticker": f_ticker, 
                "type": f_type, "price": f_price, "qty": f_qty
            }])
            updated_df = pd.concat([df, new_entry], ignore_index=True)
            conn.update(worksheet="trades", data=updated_df)
            st.success("保存しました！")
            st.rerun()

# --- 5. メイン画面の表示 ---
tab1, tab2, tab3 = st.tabs(["💰 資産状況", "📊 個別分析", "📜 全履歴"])

# 【タブ1】資産状況
with tab1:
    st.title("保有銘柄・含み損益")
    if not active_holdings:
        st.info("現在保有中の銘柄はありません。サイドバーから入力を開始してください。")
    else:
        total_unrealized = 0
        for ticker, info in active_holdings.items():
            stock = yf.Ticker(ticker).history(period="1d")
            if not stock.empty:
                current_p = stock['Close'].iloc[-1]
                avg_p = info['total_cost'] / info['qty']
                u_pl = (current_p - avg_p) * info['qty']
                total_unrealized += u_pl
                st.markdown(f"""<div class="stock-card"><b>{ticker}</b> {u_pl:+,.0f}円</div>""", unsafe_allow_html=True)
        st.metric("合計含み損益", f"{total_unrealized:+,.0f}円")

# 【タブ2】個別分析（ここを修正しました）
with tab2:
    st.title("チャート分析")
    
    # 銘柄リストがあるか確認
    ticker_list = list(df['ticker'].unique()) if not df.empty else []
    
    if not ticker_list:
        st.warning("スプレッドシートに銘柄データがありません。")
    else:
        target = st.selectbox("銘柄を選択", ticker_list)
        
        if target:
            # トレード履歴抽出
            t_trades = df[df['ticker'] == target].copy()
            t_trades['date'] = pd.to_datetime(t_trades['date'])
            
            try:
                # 株価ダウンロード
                data = yf.download(target, period="3mo", interval="1d")
                
                if not data.empty:
                    data = data.reset_index()
                    if isinstance(data.columns, pd.MultiIndex): data.columns = data.columns.get_level_values(0)
                    
                    fig = go.Figure(data=[go.Candlestick(
                        x=data['Date'], open=data['Open'], high=data['High'], low=data['Low'], close=data['Close'],
                        increasing_line_color='#ff4b4b', decreasing_line_color='#00d1ff', name="株価"
                    )])
                    
                    for _, r in t_trades.iterrows():
                        fig.add_trace(go.Scatter(
                            x=[r['date']], y=[r['price']], mode="markers+text",
                            text=["買" if r['type']=="IN" else "売"], textposition="top center",
                            marker=dict(color="#ff4b4b" if r['type']=="IN" else "#00d1ff", size=12, symbol="triangle-up" if r['type']=="IN" else "triangle-down"),
                            showlegend=False
                        ))
                    fig.update_layout(template="plotly_dark", height=500, xaxis_rangeslider_visible=False)
                    st.plotly_chart(fig, use_container_width=True)
            except Exception as e:
                st.error(f"チャート取得エラー: {e}")

# 【タブ3】全履歴
with tab3:
    st.title("売買ログ（スプレッドシート同期）")

    st.dataframe(df, use_container_width=True)
