import streamlit as st
from streamlit_gsheets import GSheetsConnection
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime

# 1. ページ設定
st.set_page_config(page_title="My Portfolio App", layout="wide")

# デザイン設定
st.markdown("""
    <style>
    .main { background-color: #121d2b; color: white; }
    .stMetric { background-color: #1e2e3e; padding: 10px; border-radius: 5px; border-left: 5px solid #2ecc71; }
    .stock-card { background-color: #1e2e3e; padding: 15px; border-radius: 10px; margin-bottom: 10px; border: 1px solid #34495e; }
    </style>
    """, unsafe_allow_html=True)

# --- 2. データ読み込み ---
conn = st.connection("gsheets", type=GSheetsConnection)
df = conn.read(worksheet="trades", ttl=0)

# --- 3. ロジック：計算処理 ---
def process_data(data):
    holdings = {}
    history = []
    
    if data.empty:
        return {}, []
    
    # 日付変換（どんな形式でもOKにする）
    data['date'] = pd.to_datetime(data['date'].astype(str), format='mixed', errors='coerce')
    data = data.dropna(subset=['date'])
    data = data.sort_values('date')
    
    for _, row in data.iterrows():
        t = row['ticker']
        # 銘柄名を取得（シートに 'name' 列がない場合はコードを使う）
        n = row['name'] if 'name' in row else t
        
        if t not in holdings: 
            holdings[t] = {"qty": 0, "total_cost": 0, "name": n}
        
        # 常に最新の名前に更新（入力揺れ防止）
        holdings[t]["name"] = n
        
        if row['type'] == "IN":
            holdings[t]['qty'] += row['qty']
            holdings[t]['total_cost'] += row['price'] * row['qty']
        elif row['type'] == "OUT":
            if holdings[t]['qty'] > 0:
                avg_price = holdings[t]['total_cost'] / holdings[t]['qty']
                p_l = (row['price'] - avg_price) * row['qty']
                
                # 履歴リストに追加
                history.append({
                    "ticker": t, 
                    "name": n,
                    "pl": p_l, 
                    "date": row['date'], 
                    "price": row['price'],
                    "type": "OUT"
                })
                
                holdings[t]['qty'] -= row['qty']
                holdings[t]['total_cost'] -= avg_price * row['qty']
            
    active_holdings = {k: v for k, v in holdings.items() if v['qty'] > 0}
    return active_holdings, history

active_holdings, history_data = process_data(df)

# --- 4. サイドバー入力 ---
with st.sidebar:
    st.header("📥 トレード入力")
    with st.form("add_trade", clear_on_submit=True):
        f_date = st.date_input("取引日", datetime.now())
        f_ticker = st.text_input("銘柄コード (例: 6269.T)", "6269.T")
        f_name = st.text_input("銘柄名 (例: 三井海洋開発)", "") # ここで名前を入力
        f_type = st.selectbox("売買", ["IN", "OUT"])
        f_price = st.number_input("単価", value=0.0)
        f_qty = st.number_input("数量", value=100)
        
        if st.form_submit_button("保存"):
            new_data = pd.DataFrame([{
                "date": f_date, # 保存時は自動でYYYY-MM-DDになる
                "ticker": f_ticker,
                "name": f_name,
                "type": f_type,
                "price": f_price,
                "qty": f_qty
            }])
            # 既存データと結合（name列がなくても自動で作られます）
            updated_df = pd.concat([df, new_data], ignore_index=True)
            conn.update(worksheet="trades", data=updated_df)
            st.success("保存しました！")
            st.rerun()

# --- 5. メイン画面 ---
tab1, tab2, tab3 = st.tabs(["💰 資産状況", "📊 チャート分析", "📜 売買ログ"])

# 【タブ1】資産状況
with tab1:
    st.title("現在のポートフォリオ")
    if not active_holdings:
        st.info("現在保有中の銘柄はありません。")
    else:
        total_unrealized = 0
        for ticker, info in active_holdings.items():
            stock = yf.Ticker(ticker).history(period="1d")
            if not stock.empty:
                current_p = stock['Close'].iloc[-1]
                avg_p = info['total_cost'] / info['qty']
                u_pl = (current_p - avg_p) * info['qty']
                total_unrealized += u_pl
                
                # 名前を表示に含める
                disp_name = info['name'] if info['name'] else ticker
                
                st.markdown(f"""
                <div class="stock-card">
                    <div style="display: flex; justify-content: space-between; align-items: center;">
                        <div>
                            <div style="font-size: 20px; font-weight: bold;">{disp_name}</div>
                            <div style="font-size: 14px; color: #bdc3c7;">{ticker}</div>
                        </div>
                        <div style="text-align: right;">
                            <div style="color: {'#ff4b4b' if u_pl > 0 else '#00d1ff'}; font-size: 22px; font-weight: bold;">
                                {u_pl:+,.0f}円
                            </div>
                            <div style="font-size: 14px; color: #bdc3c7;">
                                {((current_p/avg_p)-1)*100:+.2f}%
                            </div>
                        </div>
                    </div>
                    <hr style="margin: 10px 0; border-color: #34495e;">
                    <div style="display: flex; justify-content: space-between; font-size: 14px; color: #ecf0f1;">
                        <span>保有: {info['qty']}株</span>
                        <span>平均: {avg_p:,.0f}円</span>
                        <span>現在: {current_p:,.0f}円</span>
                    </div>
                </div>
                """, unsafe_allow_html=True)
        
        st.metric("合計含み損益", f"{total_unrealized:+,.0f}円")

# 【タブ2】チャート分析（修正点：個別損益の表示）
with tab2:
    st.title("銘柄別分析")
    
    # 銘柄リスト作成（コードと名前を結合して表示）
    # uniqueな銘柄コードを取得
    tickers = list(df['ticker'].unique()) if not df.empty else []
    
    if not tickers:
        st.warning("データがありません。")
    else:
        # セレクトボックスで選択
        target_ticker = st.selectbox("分析する銘柄", tickers)
        
        if target_ticker:
            # A. その銘柄のデータを抽出
            t_trades = df[df['ticker'] == target_ticker].copy()
            t_trades['date'] = pd.to_datetime(t_trades['date'], errors='coerce') # エラー回避
            
            # B. その銘柄だけの確定損益を計算（ここが要望の機能）
            # history_dataの中から、この銘柄のPLだけを合計する
            this_stock_pl = sum([h['pl'] for h in history_data if h['ticker'] == target_ticker])
            
            # C. 銘柄名を取得（最新の行から取る）
            stock_name = t_trades.iloc[-1]['name'] if 'name' in t_trades.columns else target_ticker

            # 画面表示
            col1, col2 = st.columns(2)
            col1.metric(f"{stock_name} の累計確定損益", f"{this_stock_pl:+,.0f}円")
            
            # チャート表示
            try:
                data = yf.download(target_ticker, period="3mo", interval="1d")
                if not data.empty:
                    data = data.reset_index()
                    if isinstance(data.columns, pd.MultiIndex): data.columns = data.columns.get_level_values(0)
                    
                    fig = go.Figure(data=[go.Candlestick(
                        x=data['Date'], open=data['Open'], high=data['High'], low=data['Low'], close=data['Close'],
                        increasing_line_color='#ff4b4b', decreasing_line_color='#00d1ff', name="株価"
                    )])
                    
                    # IN/OUTプロット
                    for _, r in t_trades.iterrows():
                        if pd.notna(r['date']): # 日付があるものだけ
                            fig.add_trace(go.Scatter(
                                x=[r['date']], y=[r['price']], mode="markers+text",
                                text=["買" if r['type']=="IN" else "売"], textposition="top center",
                                marker=dict(color="#ff4b4b" if r['type']=="IN" else "#00d1ff", size=12, symbol="triangle-up" if r['type']=="IN" else "triangle-down"),
                                showlegend=False
                            ))
                    fig.update_layout(template="plotly_dark", height=500, xaxis_rangeslider_visible=False, margin=dict(l=0, r=0, t=30, b=0))
                    st.plotly_chart(fig, use_container_width=True)
            except Exception as e:
                st.error(f"チャート取得エラー: {e}")

# 【タブ3】売買ログ（修正点：時間を消す）
with tab3:
    st.title("全取引履歴")
    if not df.empty:
        # 表示用のコピーを作成
        show_df = df.copy()
        
        # 日付を「YYYY-MM-DD」の文字列に変換して時間を消す
        show_df['date'] = pd.to_datetime(show_df['date'], errors='coerce').dt.strftime('%Y-%m-%d')
        
        # 列の順番を整える
        cols = ['date', 'name', 'ticker', 'type', 'price', 'qty'] 
        # もしname列がまだシートになければエラー回避
        cols = [c for c in cols if c in show_df.columns]
        
        st.dataframe(show_df[cols], use_container_width=True)
    else:
        st.write("データがありません")

