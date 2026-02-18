import streamlit as st
from streamlit_gsheets import GSheetsConnection
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from datetime import datetime

# 1. ページ設定
st.set_page_config(page_title="My Portfolio App", layout="wide")

# セッション状態の初期化（タブ間のデータ受け渡し用）
if 'target_ticker' not in st.session_state:
    st.session_state['target_ticker'] = None

# デザイン設定
st.markdown("""
    <style>
    .main { background-color: #121d2b; color: white; }
    .stMetric { background-color: #1e2e3e; padding: 10px; border-radius: 5px; border-left: 5px solid #2ecc71; }
    .stock-card { background-color: #1e2e3e; padding: 15px; border-radius: 10px; margin-bottom: 10px; border: 1px solid #34495e; }
    button[data-baseweb="tab"] { font-size: 18px; font-weight: bold; }
    /* ボタンのデザイン調整 */
    .stButton button { width: 100%; border-radius: 5px; font-weight: bold; }
    </style>
    """, unsafe_allow_html=True)

# --- 2. データ読み込み ---
conn = st.connection("gsheets", type=GSheetsConnection)
df = conn.read(worksheet="trades", ttl=0)

# --- 3. 計算ロジック ---
def process_data(data):
    holdings = {}
    history = []
    
    if data.empty:
        return {}, [], {"win_rate": 0, "ev": 0, "total_pl": 0, "count": 0}
    
    try:
        data['date'] = pd.to_datetime(data['date'].astype(str), errors='coerce')
    except Exception:
        return {}, [], {"win_rate": 0, "ev": 0, "total_pl": 0, "count": 0}

    data = data.dropna(subset=['date'])
    # 日付順、同じ日ならIN→OUTの順
    data = data.sort_values(by=['date', 'type'], ascending=[True, True])
    
    for _, row in data.iterrows():
        t = str(row['ticker']).strip()
        n = row['name'] if 'name' in row and pd.notna(row['name']) else t
        
        if t not in holdings: 
            holdings[t] = {"qty": 0, "total_cost": 0, "name": n}
        
        if 'name' in row and pd.notna(row['name']):
            holdings[t]["name"] = row['name']
        
        type_str = str(row['type']).strip().upper()
        
        if type_str == "IN":
            holdings[t]['qty'] += row['qty']
            holdings[t]['total_cost'] += row['price'] * row['qty']
            
        elif type_str == "OUT":
            if holdings[t]['qty'] > 0:
                current_avg = holdings[t]['total_cost'] / holdings[t]['qty']
                p_l = (row['price'] - current_avg) * row['qty']
                
                history.append({
                    "ticker": t, "name": holdings[t]["name"],
                    "pl": p_l, "date": row['date'], 
                    "price": row['price'], "type": "OUT"
                })
                
                holdings[t]['qty'] -= row['qty']
                holdings[t]['total_cost'] -= current_avg * row['qty']

    active_holdings = {k: v for k, v in holdings.items() if v['qty'] > 0.001}
    
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

# 株価取得関数
@st.cache_data(ttl=600)
def get_stock_price(ticker):
    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(period="1d")
        if not hist.empty:
            return hist['Close'].iloc[-1]
        data = yf.download(ticker, period="1d", progress=False)
        if not data.empty:
            return data['Close'].iloc[-1]
        return None
    except:
        return None

# --- 4. サイドバー ---
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

# --- 5. メイン画面 ---
tab1, tab2, tab3, tab4 = st.tabs(["💰 資産状況", "📈 全体成績", "📊 個別分析", "📜 売買ログ"])

# 【タブ1】資産状況
with tab1:
    st.title("現在のポートフォリオ")
    if not active_holdings:
        st.info("現在保有中の銘柄はありません。")
    else:
        total_unrealized = 0
        for ticker, info in active_holdings.items():
            current_p = get_stock_price(ticker)
            is_error = False
            if current_p is None:
                current_p = info['total_cost'] / info['qty']
                is_error = True

            avg_p = info['total_cost'] / info['qty']
            u_pl = (current_p - avg_p) * info['qty']
            total_unrealized += u_pl
            
            disp_name = info['name'] if info['name'] else ticker
            p_color = '#ff4b4b' if u_pl > 0 else '#00d1ff'
            price_display = f"{current_p:,.0f}円"
            if is_error: price_display += " (取得失敗)"

            # カード表示
            col_card, col_btn = st.columns([5, 1])
            with col_card:
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
                        <span>現在: {price_display}</span>
                    </div>
                </div>
                """, unsafe_allow_html=True)
            
            # 分析ボタン
            with col_btn:
                st.write("") # 縦位置調整
                st.write("")
                if st.button("📊 分析", key=f"btn_{ticker}"):
                    st.session_state['target_ticker'] = ticker
                    st.success(f"{disp_name} を選択しました。「個別分析」タブを開いてください！")

        st.metric("合計含み損益", f"{total_unrealized:+,.0f}円")

# 【タブ2】全体成績（資産推移＆月別）
with tab2:
    st.title("パフォーマンス分析")
    c1, c2, c3 = st.columns(3)
    c1.metric("累計確定損益", f"{global_stats['total_pl']:+,.0f}円")
    c2.metric("勝率", f"{global_stats['win_rate']:.1f}%")
    c3.metric("総取引回数", f"{global_stats['count']}回")
    st.divider()

    # グラフ用データ作成
    if history_data:
        df_hist = pd.DataFrame(history_data)
        df_hist['date'] = pd.to_datetime(df_hist['date'])
        df_hist = df_hist.sort_values('date')
        
        # 1. 資産推移（累計利益の積み上げ）- 手入力不要！
        df_hist['cumulative_pl'] = df_hist['pl'].cumsum()
        
        st.subheader("💹 資産(累計利益)の推移")
        fig_asset = px.area(df_hist, x='date', y='cumulative_pl', 
                            labels={'cumulative_pl': '累計利益', 'date': '日付'})
        fig_asset.update_traces(line_color='#2ecc71', fill_color='rgba(46, 204, 113, 0.2)')
        fig_asset.update_layout(template="plotly_dark", height=350)
        st.plotly_chart(fig_asset, use_container_width=True)

        # 2. 月別損益バーチャート
        st.subheader("📅 月別損益")
        df_hist['month'] = df_hist['date'].dt.strftime('%Y-%m')
        monthly_pl = df_hist.groupby('month')['pl'].sum().reset_index()
        
        fig_month = px.bar(monthly_pl, x='month', y='pl',
                           color='pl',
                           color_continuous_scale=['#00d1ff', '#ff4b4b'], # マイナス青、プラス赤
                           labels={'pl': '損益', 'month': '月'})
        fig_month.update_layout(template="plotly_dark", height=350, showlegend=False)
        st.plotly_chart(fig_month, use_container_width=True)
    else:
        st.info("取引履歴がまだありません。")

# 【タブ3】個別分析（チャート強化版）
with tab3:
    st.title("銘柄別詳細")
    
    # セレクトボックス（ボタンで選択された銘柄があればそれを初期値に）
    if not df.empty:
        df['disp_label'] = df['ticker'].astype(str) + " : " + df['name'].fillna('')
        unique_options = {str(r['ticker']): r['disp_label'] for _, r in df.iterrows()}
        options_list = list(unique_options.values())
        
        # セッション状態からデフォルトインデックスを探す
        default_idx = 0
        if st.session_state['target_ticker']:
            target_label = unique_options.get(st.session_state['target_ticker'])
            if target_label in options_list:
                default_idx = options_list.index(target_label)

        selected_label = st.selectbox("銘柄を選択", options_list, index=default_idx)
        
        if selected_label:
            target_ticker = [k for k, v in unique_options.items() if v == selected_label][0]
        else:
            target_ticker = None
    else:
        target_ticker = None

    if target_ticker:
        this_hist = [h for h in history_data if h['ticker'] == target_ticker]
        t_wins = len([h for h in this_hist if h['pl'] > 0])
        t_count = len(this_hist)
        t_win_rate = (t_wins / t_count * 100) if t_count > 0 else 0
        t_total = sum([h['pl'] for h in this_hist])
        t_ev = (t_total / t_count) if t_count > 0 else 0

        col1, col2 = st.columns([1, 2])
        with col1:
            # 勝率（円グラフ）
            fig_pie = go.Figure(data=[go.Pie(
                labels=['Win', 'Lose'], values=[t_wins, t_count - t_wins],
                hole=.6, marker_colors=['#ff4b4b', '#00d1ff'], textinfo='none'
            )])
            fig_pie.update_layout(showlegend=False, height=180, margin=dict(t=0,b=0,l=0,r=0),
                paper_bgcolor='rgba(0,0,0,0)',
                annotations=[dict(text=f'{t_win_rate:.0f}%', x=0.5, y=0.5, font_size=24, showarrow=False, font_color='white')])
            st.write("勝率")
            st.plotly_chart(fig_pie, use_container_width=True)
            st.metric("期待値", f"{t_ev:+,.0f}円")

        with col2:
            st.metric("累計確定損益", f"{t_total:+,.0f}円")
            
            # --- 強化版チャート ---
            try:
                # 期間を長めに取る
                data = yf.download(target_ticker, period="1y", interval="1d")
                if not data.empty:
                    data = data.reset_index()
                    if isinstance(data.columns, pd.MultiIndex): data.columns = data.columns.get_level_values(0)
                    
                    fig = go.Figure(data=[go.Candlestick(
                        x=data['Date'], open=data['Open'], high=data['High'], low=data['Low'], close=data['Close'],
                        increasing_line_color='#ff4b4b', decreasing_line_color='#00d1ff', name="株価"
                    )])
                    
                    # 売買ポイント（矢印で表示）
                    t_trades = df[df['ticker'] == str(target_ticker)]
                    for _, r in t_trades.iterrows():
                        if r['type'] == "IN":
                            color, symbol, offset = "#ff4b4b", "triangle-up", -10
                        else:
                            color, symbol, offset = "#00d1ff", "triangle-down", 10
                            
                        fig.add_trace(go.Scatter(
                            x=[r['date']], y=[r['price']], mode="markers",
                            marker=dict(color=color, size=15, symbol=symbol), # 大きく、矢印に
                            name=r['type'], hoverinfo='text',
                            hovertext=f"{r['date']}<br>{r['type']}: {r['price']}円"
                        ))

                    # レイアウト調整（日本語、円表示、土日削除）
                    fig.update_layout(
                        template="plotly_dark", height=450,
                        xaxis_rangeslider_visible=True, # スライダー表示
                        xaxis=dict(
                            type='date',
                            rangebreaks=[dict(bounds=["sat", "mon"])], # 土日を隠す
                            tickformat="%Y-%m-%d",
                            dtick="M1" # メモリ間隔（1ヶ月ごと）
                        ),
                        yaxis=dict(
                            tickformat=",", # 10kではなく 10,000 表記に
                            title="価格 (円)"
                        ),
                        margin=dict(l=50, r=20, t=10, b=20)
                    )
                    st.plotly_chart(fig, use_container_width=True)
            except Exception as e:
                st.error(f"チャートエラー: {e}")

# 【タブ4】売買ログ
with tab4:
    st.title("全取引履歴")
    if not df.empty:
        show_df = df.copy()
        try:
            show_df['date'] = pd.to_datetime(show_df['date'], errors='coerce').dt.strftime('%Y-%m-%d')
        except:
            show_df['date'] = show_df['date'].astype(str)

        cols = [c for c in ['date', 'ticker', 'name', 'type', 'price', 'qty'] if c in show_df.columns]
        
        def highlight_active(row):
            if str(row['ticker']) in active_holdings:
                return ['background-color: #554400'] * len(row)
            return [''] * len(row)

        st.dataframe(show_df[cols].style.apply(highlight_active, axis=1), use_container_width=True)

