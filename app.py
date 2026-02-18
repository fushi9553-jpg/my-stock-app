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
    /* タブの文字を大きく */
    button[data-baseweb="tab"] { font-size: 18px; font-weight: bold; }
    </style>
    """, unsafe_allow_html=True)

# --- 2. データ読み込み ---
conn = st.connection("gsheets", type=GSheetsConnection)
df = conn.read(worksheet="trades", ttl=0)

# ==========================================
# 🛠️ データ洗浄（亡霊退治）コーナー
# ==========================================
if not df.empty:
    # 1. 文字型に変換
    df['ticker'] = df['ticker'].astype(str)
    df['type'] = df['type'].astype(str)
    
    # 2. 全角を半角に、前後の空白を削除（例: "４００５ " -> "4005"）
    # (unicodedataを使って正規化する処理を入れるのがベストですが、簡易的に空白削除と大文字化を行います)
    df['ticker'] = df['ticker'].str.strip().str.upper() # 小文字も大文字に
    df['type'] = df['type'].str.strip().str.upper()     # "in " -> "IN"

    # 3. 日付の強力な変換
    # どんな形式でもエラーを出さず、変換できない行は削除
    try:
        df['date'] = pd.to_datetime(df['date'].astype(str), format='mixed', errors='coerce')
    except:
        df['date'] = pd.to_datetime(df['date'].astype(str), errors='coerce')
    
    df = df.dropna(subset=['date'])

    # 4. 【超重要】並び替えのルール変更
    # 日付順 -> その中で「IN」が「OUT」より先に来るようにする
    # (アルファベット順だと 'I'N は 'O'UT より先なので、typeでもソートすれば解決！)
    df = df.sort_values(by=['date', 'type'], ascending=[True, True])

# ==========================================

# --- 3. 計算ロジック ---
def process_data(data):
    holdings = {}
    history = []
    
    if data.empty:
        return {}, [], {"win_rate": 0, "ev": 0, "total_pl": 0, "count": 0}
    
    for _, row in data.iterrows():
        t = row['ticker']
        n = row['name'] if 'name' in row and pd.notna(row['name']) else t
        
        if t not in holdings: 
            holdings[t] = {"qty": 0, "total_cost": 0, "name": n}
        
        # 名前更新
        if 'name' in row and pd.notna(row['name']):
            holdings[t]["name"] = row['name']
        
        if row['type'] == "IN":
            holdings[t]['qty'] += row['qty']
            holdings[t]['total_cost'] += row['price'] * row['qty']
            
        elif row['type'] == "OUT":
            # 【変更】在庫がなくても強制的に引き算してみる（エラー発見用）
            # もしこれで保有数がマイナスになったら、OUTが多すぎるかINの日付間違い
            
            # 平均単価の計算（在庫がある時のみ）
            current_avg = 0
            if holdings[t]['qty'] > 0:
                current_avg = holdings[t]['total_cost'] / holdings[t]['qty']
            
            p_l = (row['price'] - current_avg) * row['qty']
            
            history.append({
                "ticker": t, "name": holdings[t]["name"],
                "pl": p_l, "date": row['date'], 
                "price": row['price'], "type": "OUT"
            })
            
            holdings[t]['qty'] -= row['qty']
            if holdings[t]['qty'] > 0:
                holdings[t]['total_cost'] -= current_avg * row['qty']
            else:
                holdings[t]['total_cost'] = 0 # 売り切ったらコストリセット
            
    # 保有中のみ抽出（数量が0.01以上のものだけ。マイナスも表示しない）
    active_holdings = {k: v for k, v in holdings.items() if v['qty'] > 0.001}
    
    # 全体統計
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

# --- 4. サイドバー（入力フォームのみ） ---
with st.sidebar:
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

# --- 5. メイン画面（タブ構成を変更） ---
# タブを4つに増やしました
tab1, tab2, tab3, tab4 = st.tabs(["💰 資産状況", "📈 全体成績", "📊 個別分析", "📜 売買ログ"])

# 【タブ1】資産状況
with tab1:
    st.title("現在のポートフォリオ")
    if not active_holdings:
        st.info("現在保有中の銘柄はありません。")
    else:
        total_unrealized = 0
        for ticker, info in active_holdings.items():
            try:
                stock = yf.Ticker(ticker).history(period="1d")
                if not stock.empty:
                    current_p = stock['Close'].iloc[-1]
                else:
                    current_p = info['total_cost'] / info['qty'] # 取得失敗時は買値で仮置き
            except:
                current_p = info['total_cost'] / info['qty']

            avg_p = info['total_cost'] / info['qty']
            u_pl = (current_p - avg_p) * info['qty']
            total_unrealized += u_pl
            
            disp_name = info['name'] if info['name'] else ticker
            p_color = '#ff4b4b' if u_pl > 0 else '#00d1ff'
            
            st.markdown(f"""
            <div class="stock-card">
                <div style="display: flex; justify-content: space-between; align-items: center;">
                    <div>
                        <div style="font-size: 20px; font-weight: bold; color: white;">{disp_name}</div>
                        <div style="font-size: 14px; color: #bdc3c7;">{ticker}</div>
                    </div>
                    <div style="text-align: right;">
                        <div style="color: {p_color}; font-size: 22px; font-weight: bold;">
                            {u_pl:+,.0f}円
                        </div>
                        <div style="font-size: 14px; color: #bdc3c7;">
                            {((current_p/avg_p)-1)*100:+.2f}%
                        </div>
                    </div>
                </div>
                <hr style="margin: 8px 0; border-color: #34495e;">
                <div style="display: flex; justify-content: space-between; font-size: 14px; color: #ecf0f1;">
                    <span>保有: {info['qty']:,}</span>
                    <span>平均: {avg_p:,.0f}</span>
                    <span>現在: {current_p:,.0f}</span>
                </div>
            </div>
            """, unsafe_allow_html=True)
    
    st.metric("合計含み損益", f"{total_unrealized:+,.0f}円")

# 【タブ2】全体成績（新設）
with tab2:
    st.title("パフォーマンス分析")
    
    # 大きな指標表示
    c1, c2, c3 = st.columns(3)
    c1.metric("累計確定損益", f"{global_stats['total_pl']:+,.0f}円")
    c2.metric("勝率", f"{global_stats['win_rate']:.1f}%")
    c3.metric("総取引回数", f"{global_stats['count']}回")
    
    st.divider()
    
    c4, c5 = st.columns(2)
    c4.metric("平均利益 (期待値)", f"{global_stats['ev']:+,.0f}円 / 回")
    
    # 簡易的な損益推移グラフ（履歴がある場合のみ）
    if history_data:
        df_hist = pd.DataFrame(history_data)
        df_hist = df_hist.sort_values('date')
        df_hist['cum_pl'] = df_hist['pl'].cumsum() # 累積和
        
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=df_hist['date'], y=df_hist['cum_pl'],
            mode='lines+markers', name='資産推移',
            line=dict(color='#2ecc71', width=3)
        ))
        fig.update_layout(
            title="資産推移グラフ",
            template="plotly_dark", height=300,
            margin=dict(l=0, r=0, t=40, b=0)
        )
        st.plotly_chart(fig, use_container_width=True)

# 【タブ3】個別分析
with tab3:
    st.title("銘柄別詳細")
    
    if not df.empty:
        df['disp_label'] = df['ticker'] + " : " + df['name'].fillna('')
        # 重複削除して辞書化
        unique_options = {}
        for idx, row in df.iterrows():
            unique_options[row['ticker']] = row['disp_label']
            
        selected_label = st.selectbox("銘柄を選択", list(unique_options.values()))
        # ラベルからTickerを特定
        target_ticker = [k for k, v in unique_options.items() if v == selected_label][0]
    else:
        target_ticker = None

    if target_ticker:
        # 統計
        this_hist = [h for h in history_data if h['ticker'] == target_ticker]
        t_wins = len([h for h in this_hist if h['pl'] > 0])
        t_count = len(this_hist)
        t_win_rate = (t_wins / t_count * 100) if t_count > 0 else 0
        t_total = sum([h['pl'] for h in this_hist])
        t_ev = (t_total / t_count) if t_count > 0 else 0

        # レイアウト
        col1, col2 = st.columns([1, 2])
        
        with col1:
            # 勝率円グラフ
            fig_pie = go.Figure(data=[go.Pie(
                labels=['Win', 'Lose'], values=[t_wins, t_count - t_wins],
                hole=.6, marker_colors=['#ff4b4b', '#00d1ff'], textinfo='none'
            )])
            fig_pie.update_layout(
                showlegend=False, height=180, margin=dict(t=0, b=0, l=0, r=0),
                paper_bgcolor='rgba(0,0,0,0)',
                annotations=[dict(text=f'{t_win_rate:.0f}%', x=0.5, y=0.5, font_size=24, showarrow=False, font_color='white')]
            )
            st.write("勝率")
            st.plotly_chart(fig_pie, use_container_width=True)
            
            st.metric("期待値 (平均)", f"{t_ev:+,.0f}円")

        with col2:
            st.metric("累計確定損益", f"{t_total:+,.0f}円")
            
            # チャート
            t_trades = df[df['ticker'] == target_ticker].copy()
            # エラー対策済みの日付変換
            try:
                t_trades['date'] = pd.to_datetime(t_trades['date'].astype(str), format='mixed', errors='coerce')
            except:
                t_trades['date'] = pd.to_datetime(t_trades['date'].astype(str), errors='coerce')
                
            try:
                data = yf.download(target_ticker, period="6mo", interval="1d")
                if not data.empty:
                    data = data.reset_index()
                    if isinstance(data.columns, pd.MultiIndex): data.columns = data.columns.get_level_values(0)
                    
                    fig = go.Figure(data=[go.Candlestick(
                        x=data['Date'], open=data['Open'], high=data['High'], low=data['Low'], close=data['Close'],
                        increasing_line_color='#ff4b4b', decreasing_line_color='#00d1ff'
                    )])
                    
                    for _, r in t_trades.iterrows():
                        if pd.notna(r['date']):
                            fig.add_trace(go.Scatter(
                                x=[r['date']], y=[r['price']], mode="markers",
                                marker=dict(color="yellow", size=10, symbol="triangle-up" if r['type']=="IN" else "triangle-down"),
                                showlegend=False
                            ))
                    fig.update_layout(template="plotly_dark", height=400, xaxis_rangeslider_visible=False)
                    st.plotly_chart(fig, use_container_width=True)
            except:
                st.error("チャート取得不可")

# 【タブ4】売買ログ（未決済ハイライト）
with tab4:
    st.title("全取引履歴")
    st.caption("⚠️ 黄色い行 = アプリ上で『保有中』と認識されている銘柄")
    
    if not df.empty:
        show_df = df.copy()
        # 表示用に日付を文字列化
        try:
            show_df['date'] = pd.to_datetime(show_df['date'].astype(str), format='mixed', errors='coerce').dt.strftime('%Y-%m-%d')
        except:
            show_df['date'] = show_df['date'].astype(str)

        # 列の整理
        cols = [c for c in ['date', 'ticker', 'name', 'type', 'price', 'qty'] if c in show_df.columns]
        show_df = show_df[cols]

        # ハイライト関数
        def highlight_active(row):
            if row['ticker'] in active_holdings:
                return ['background-color: #554400'] * len(row) # 濃い黄色
            return [''] * len(row)

        st.dataframe(show_df.style.apply(highlight_active, axis=1), use_container_width=True)

