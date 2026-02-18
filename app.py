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

# --- 3. 計算ロジック（統計・保有・履歴） ---
def process_data(data):
    holdings = {}
    history = []
    
    if data.empty:
        return {}, [], {"win_rate": 0, "ev": 0, "total_pl": 0, "count": 0}
    
    # 日付変換と整理
    data['date'] = pd.to_datetime(data['date'].astype(str), format='mixed', errors='coerce')
    data = data.dropna(subset=['date'])
    data = data.sort_values('date')
    
    for _, row in data.iterrows():
        t = row['ticker']
        # 銘柄名：シートにあればそれを使う、なければコード
        n = row['name'] if 'name' in row and pd.notna(row['name']) else t
        
        if t not in holdings: 
            holdings[t] = {"qty": 0, "total_cost": 0, "name": n}
        
        # 名前情報の更新
        if row['name'] and pd.notna(row['name']):
            holdings[t]["name"] = row['name']
        
        if row['type'] == "IN":
            holdings[t]['qty'] += row['qty']
            holdings[t]['total_cost'] += row['price'] * row['qty']
        elif row['type'] == "OUT":
            if holdings[t]['qty'] > 0:
                avg_price = holdings[t]['total_cost'] / holdings[t]['qty']
                p_l = (row['price'] - avg_price) * row['qty']
                
                history.append({
                    "ticker": t, "name": holdings[t]["name"],
                    "pl": p_l, "date": row['date'], 
                    "price": row['price'], "type": "OUT"
                })
                
                holdings[t]['qty'] -= row['qty']
                holdings[t]['total_cost'] -= avg_price * row['qty']
            
    # 保有中のみ抽出
    active_holdings = {k: v for k, v in holdings.items() if v['qty'] > 0}
    
    # 全体統計の計算
    total_pl = sum([h['pl'] for h in history])
    trade_count = len(history)
    wins = len([h for h in history if h['pl'] > 0])
    
    stats = {
        "win_rate": (wins / trade_count * 100) if trade_count > 0 else 0,
        "ev": (total_pl / trade_count) if trade_count > 0 else 0,
        "total_pl": total_pl,
        "count": trade_count
    }
    
    return active_holdings, history, stats

active_holdings, history_data, global_stats = process_data(df)

# --- 4. サイドバー（入力 ＆ 全体統計） ---
with st.sidebar:
    # --- 全体統計 ---
    st.header("📊 全体成績")
    col_s1, col_s2 = st.columns(2)
    col_s1.metric("勝率", f"{global_stats['win_rate']:.1f}%")
    col_s2.metric("期待値", f"{global_stats['ev']:+,.0f}円")
    st.metric("累計確定損益", f"{global_stats['total_pl']:+,.0f}円")
    st.markdown("---")

    # --- 入力フォーム ---
    st.header("📥 トレード入力")
    with st.form("add_trade", clear_on_submit=True):
        f_date = st.date_input("取引日", datetime.now())
        f_ticker = st.text_input("銘柄コード (例: 6269.T)", "6269.T")
        f_name = st.text_input("銘柄名 (例: 三井海洋開発)", "") 
        f_type = st.selectbox("売買", ["IN", "OUT"])
        f_price = st.number_input("単価", value=0.0)
        f_qty = st.number_input("数量", value=100)
        
        if st.form_submit_button("保存"):
            new_data = pd.DataFrame([{
                "date": f_date, 
                "ticker": f_ticker,
                "name": f_name,
                "type": f_type,
                "price": f_price,
                "qty": f_qty
            }])
            updated_df = pd.concat([df, new_data], ignore_index=True)
            conn.update(worksheet="trades", data=updated_df)
            st.success("保存しました！")
            st.rerun()

# --- 5. メイン画面 ---
tab1, tab2, tab3 = st.tabs(["💰 資産状況", "📊 チャート分析", "📜 売買ログ"])

# 【タブ1】資産状況（詳細表示化）
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
                
                # 表示用データの整理
                disp_name = info['name'] if info['name'] else ticker
                p_color = '#ff4b4b' if u_pl > 0 else '#00d1ff'
                
                # HTMLでリッチなカードを作成
                st.markdown(f"""
                <div class="stock-card">
                    <div style="display: flex; justify-content: space-between; align-items: center;">
                        <div>
                            <div style="font-size: 22px; font-weight: bold; color: white;">{disp_name}</div>
                            <div style="font-size: 14px; color: #bdc3c7;">{ticker}</div>
                        </div>
                        <div style="text-align: right;">
                            <div style="color: {p_color}; font-size: 24px; font-weight: bold;">
                                {u_pl:+,.0f}円
                            </div>
                            <div style="font-size: 14px; color: #bdc3c7;">
                                前日比: {((current_p/avg_p)-1)*100:+.2f}%
                            </div>
                        </div>
                    </div>
                    <hr style="margin: 10px 0; border-color: #34495e;">
                    <div style="display: flex; justify-content: space-between; font-size: 15px; color: #ecf0f1;">
                        <div style="text-align: center;">
                            <div style="color:#bdc3c7; font-size:12px;">保有数量</div>
                            <div>{info['qty']:,} 株</div>
                        </div>
                        <div style="text-align: center;">
                            <div style="color:#bdc3c7; font-size:12px;">平均取得単価</div>
                            <div>{avg_p:,.0f} 円</div>
                        </div>
                        <div style="text-align: center;">
                            <div style="color:#bdc3c7; font-size:12px;">現在値</div>
                            <div>{current_p:,.0f} 円</div>
                        </div>
                    </div>
                </div>
                """, unsafe_allow_html=True)
        
        st.metric("合計含み損益", f"{total_unrealized:+,.0f}円")

# 【タブ2】チャート分析（勝率・期待値・名前選択）
with tab2:
    st.title("銘柄別分析")
    
    # 選択肢を「コード: 名前」の形式にする
    # データフレームからユニークなペアを作成
    if not df.empty:
        df['disp_label'] = df['ticker'] + " : " + df['name'].fillna('')
        unique_options = df[['ticker', 'disp_label']].drop_duplicates().set_index('ticker')['disp_label'].to_dict()
        
        # セレクトボックス（表示は名前付き、戻り値はコード）
        selected_label = st.selectbox("分析する銘柄", list(unique_options.values()))
        # 選択されたラベルからコードを逆引き
        target_ticker = [k for k, v in unique_options.items() if v == selected_label][0]
    else:
        target_ticker = None

    if target_ticker:
        # --- A. 統計データの計算 ---
        # この銘柄の確定損益履歴
        this_stock_history = [h for h in history_data if h['ticker'] == target_ticker]
        this_wins = len([h for h in this_stock_history if h['pl'] > 0])
        this_count = len(this_stock_history)
        this_win_rate = (this_wins / this_count * 100) if this_count > 0 else 0
        this_total_pl = sum([h['pl'] for h in this_stock_history])
        this_ev = (this_total_pl / this_count) if this_count > 0 else 0

        # --- B. 表示レイアウト ---
        col1, col2, col3 = st.columns([1, 1, 2])
        
        with col1:
            # 勝率円グラフ
            fig_pie = go.Figure(data=[go.Pie(
                labels=['勝', '負'], values=[this_wins, this_count - this_wins],
                hole=.6, marker_colors=['#ff4b4b', '#00d1ff'], textinfo='none'
            )])
            fig_pie.update_layout(
                showlegend=False, height=150, margin=dict(t=0, b=0, l=0, r=0),
                paper_bgcolor='rgba(0,0,0,0)',
                annotations=[dict(text=f'{this_win_rate:.0f}%', x=0.5, y=0.5, font_size=20, showarrow=False, font_color='white')]
            )
            st.markdown("##### 勝率")
            st.plotly_chart(fig_pie, use_container_width=True)

        with col2:
            st.markdown("##### 期待値 / 損益")
            st.metric("期待値 (1回あたり)", f"{this_ev:+,.0f}円")
            st.metric("累計確定損益", f"{this_total_pl:+,.0f}円")
            st.metric("取引回数", f"{this_count}回")

        with col3:
            # チャート表示
            t_trades = df[df['ticker'] == target_ticker].copy()
            t_trades['date'] = pd.to_datetime(t_trades['date'], errors='coerce')
            
            try:
                data = yf.download(target_ticker, period="6mo", interval="1d")
                if not data.empty:
                    data = data.reset_index()
                    if isinstance(data.columns, pd.MultiIndex): data.columns = data.columns.get_level_values(0)
                    
                    fig = go.Figure(data=[go.Candlestick(
                        x=data['Date'], open=data['Open'], high=data['High'], low=data['Low'], close=data['Close'],
                        increasing_line_color='#ff4b4b', decreasing_line_color='#00d1ff', name="株価"
                    )])
                    
                    # 売買ポイント
                    for _, r in t_trades.iterrows():
                        if pd.notna(r['date']):
                            fig.add_trace(go.Scatter(
                                x=[r['date']], y=[r['price']], mode="markers",
                                marker=dict(color="yellow", size=10, symbol="triangle-up" if r['type']=="IN" else "triangle-down"),
                                name=r['type'], showlegend=False
                            ))
                    
                    fig.update_layout(template="plotly_dark", height=350, xaxis_rangeslider_visible=False, margin=dict(l=0, r=0, t=10, b=0))
                    st.plotly_chart(fig, use_container_width=True)
            except Exception as e:
                st.error(f"チャート取得エラー: {e}")

# 【タブ3】売買ログ（保有中をハイライト）
with tab3:
    st.title("全取引履歴")
    st.caption("⚠️ 黄色い行の銘柄は、アプリ上で『まだ持っている（OUTされていない）』と判定されています。")
    
    if not df.empty:
        show_df = df.copy()
        show_df['date'] = pd.to_datetime(show_df['date'], errors='coerce').dt.strftime('%Y-%m-%d')
        cols = [c for c in ['date', 'ticker', 'name', 'type', 'price', 'qty'] if c in show_df.columns]
        show_df = show_df[cols]

        # ハイライト関数の定義
        def highlight_active(row):
            # もしこの行のtickerが、現在保有リスト(active_holdings)に含まれていたら黄色くする
            if row['ticker'] in active_holdings:
                return ['background-color: #333300'] * len(row) # 暗い黄色
            return [''] * len(row)

        st.dataframe(show_df.style.apply(highlight_active, axis=1), use_container_width=True)
    else:
        st.write("データがありません")
