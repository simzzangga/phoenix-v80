import streamlit as st
import FinanceDataReader as fdr
import yfinance as yf
import pandas as pd
import numpy as np
import datetime
import json
import os
import plotly.graph_objects as go
import time

# --- [1. 시스템 설정] ---
SCAN_RESULT_FILE = "last_scan_results.json"
ANALYSIS_LOG_FILE, BACKUP_KRX_FILE = "analysis_log_v5.json", "backup_krx.json"

if "scan_storage" not in st.session_state:
    st.session_state.scan_storage = []
if "auto_code" not in st.session_state: st.session_state.auto_code = ""
if "server_status" not in st.session_state: st.session_state.server_status = "🛰️ 엔진 예열 중..."

@st.cache_data(ttl=3600, show_spinner=False)
def get_krx_list_ultimate():
    if os.path.exists(BACKUP_KRX_FILE):
        try:
            df_l = pd.read_json(BACKUP_KRX_FILE)
            if not df_l.empty:
                st.session_state.server_status = "🔥 출격 준비 완료 (LOCAL FAST)"
                return df_l
        except: pass
    try:
        df = fdr.StockListing('KRX')[['Code', 'Name']]
        df['Code'] = df['Code'].astype(str).str.zfill(6)
        df.to_json(BACKUP_KRX_FILE)
        st.session_state.server_status = "🔥 출격 준비 완료 (CONNECTED)"
        return df
    except:
        return pd.DataFrame([{"Code": "005930", "Name": "삼성전자"}])

# --- [2. 신뢰도 강화 엔진: v5.9.80] ---
def analyze_v5_80_engine(ticker, target_date):
    df = None
    ticker_str = str(ticker).zfill(6)
    # 데이터 로드 기간 확대 (MFI 연산용)
    start_date = target_date - datetime.timedelta(days=300) 
    try:
        df = fdr.DataReader(ticker_str, start_date, target_date)
        if df is not None and not df.empty:
            df.columns = [c.upper() for c in df.columns]
            # 한국 데이터 한글 컬럼 대응
            df = df.rename(columns={'시가':'OPEN','고가':'HIGH','저가':'LOW','종가':'CLOSE','거래량':'VOLUME','거래대금':'AMOUNT'})
    except: pass

    if df is None or len(df) < 30: return None, None
    
    # [A. 기준봉 품질 체크]
    # 최근 20일 내 '강력한 기준봉' 탐색
    lookback = df.iloc[-25:]
    # 조건: 거래대금 500억 이상(한국시장 기준) AND 시가갭 2.5% 미만 AND 장대양봉(5% 이상)
    base_candle = lookback[(lookback['AMOUNT'] >= 50_000_000_000) & 
                          ((lookback['OPEN'] / lookback['CLOSE'].shift(1)) < 1.025) &
                          ((lookback['CLOSE'] / lookback['OPEN']) >= 1.05)]
    
    trust_bonus = 30 if not base_candle.empty else 0
    
    # [B. MFI (Money Flow Index) 연산 - 눌림목 신뢰도]
    typical_price = (df['HIGH'] + df['LOW'] + df['CLOSE']) / 3
    money_flow = typical_price * df['VOLUME']
    positive_flow = []
    negative_flow = []
    for i in range(1, len(typical_price)):
        if typical_price.iloc[i] > typical_price.iloc[i-1]:
            positive_flow.append(money_flow.iloc[i])
            negative_flow.append(0)
        else:
            positive_flow.append(0)
            negative_flow.append(money_flow.iloc[i])
    
    # 14일 MFI 계산
    mfi_period = 14
    pos_sum = pd.Series(positive_flow).rolling(window=mfi_period).sum()
    neg_sum = pd.Series(negative_flow).rolling(window=mfi_period).sum()
    mfi = 100 - (100 / (1 + pos_sum / (neg_sum + 1e-10)))
    curr_mfi = mfi.iloc[-1]
    
    # [C. 기존 변수 연산]
    body_ratio_val = (df['CLOSE'] - df['OPEN']).abs() / (df['HIGH'] - df['LOW'] + 0.001)
    vol_ratio = df['VOLUME'].iloc[-1] / (df['VOLUME'].iloc[-21:-1].mean() + 1)
    pre_20 = df.iloc[-21:-1]
    cv_val = (pre_20['CLOSE'].std() / pre_20['CLOSE'].mean()) * 100
    
    # [D. 적합도 산출 (신뢰도 중심)]
    similarity = ((max(0, 100 - (abs(cv_val - 1.8) * 20))) * 0.3) + ((min(100, (vol_ratio / 5.0) * 100)) * 0.7)
    
    fit_score = trust_bonus
    if 82.5 <= similarity <= 88.0: fit_score += 25
    if 2.8 <= vol_ratio <= 4.2: fit_score += 20
    if 1.5 <= cv_val <= 2.2: fit_score += 15
    if 20 <= curr_mfi <= 45: fit_score += 10 # 눌림목 수급 과매도 구간 가점
    
    # [E. 전략 도출]
    phase = "🟡 관망"
    if fit_score >= 90: phase = "🔥 3차: 강력매수"
    elif fit_score >= 80: phase = "🚀 2차: 추가매수"
    elif fit_score >= 70: phase = "⚔️ 1차: 신규진입"
    
    return {
        "종목코드": ticker_str, "현재가": int(df['CLOSE'].iloc[-1]),
        "적합도": fit_score, "상태": phase,
        "MFI": round(curr_mfi, 1), "CV": round(cv_val, 2), "거래대금": f"{int(df['AMOUNT'].iloc[-1]/100000000):,}억",
        "목표가": int(df['CLOSE'].iloc[-1] * 1.08), # 8% 목표
        "손절가": int(df['CLOSE'].iloc[-1] * 0.95), # -5% 손절
        "유지기간": "최대 10거래일 (강제종료)",
        "is_valid": True if fit_score >= 70 else False,
        "스캔날짜": target_date.strftime('%Y-%m-%d')
    }, df

# --- [3. UI 레이아웃] ---
st.set_page_config(page_title="Phoenix v5.9.80 Trust+", layout="wide")
st.markdown("<style>div.stApp {background: white !important;} * {color: black !important;}</style>", unsafe_allow_html=True)

st.title("Phoenix Hybrid v5.9.80 [Trust+]")
krx_df = get_krx_list_ultimate()
krx_df['Display'] = krx_df['Code'] + " | " + krx_df['Name']

st.info(f"SYSTEM STATUS: {st.session_state.server_status}")

with st.form("analysis_form"):
    c1, c2 = st.columns([5, 2])
    search_input = c1.selectbox("종목 선택", krx_df['Display'].tolist())
    d_input = c2.date_input("기준 날짜", value=datetime.date.today())
    submit = st.form_submit_button("🔍 정밀 분석 시작")

if submit:
    res, df = analyze_v5_80_engine(search_input.split(" | ")[0], d_input)
    if res:
        st.subheader(f"🎯 [{search_input.split(' | ')[1]}] 전략 리포트")
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("신뢰 적합도", f"{res['적합도']}%")
        m2.metric("MFI 수급", res['MFI'])
        m3.metric("목표가(8%)", f"{res['목표가']:,}원")
        m4.metric("강제사출일", "D+10")
        
        fig = go.Figure(data=[go.Candlestick(x=df.index, open=df['OPEN'], high=df['HIGH'], low=df['LOW'], close=df['CLOSE'])])
        fig.update_layout(template="plotly_white", height=400)
        st.plotly_chart(fig, use_container_width=True)

st.divider()

if st.button("🚀 1,000개 종목 고신뢰 스캔", width='stretch'):
    st.session_state.scan_storage = []
    codes = krx_df.head(1000)
    prog = st.progress(0)
    for i, (idx, row) in enumerate(codes.iterrows()):
        r, _ = analyze_v5_80_engine(row['Code'], datetime.date.today())
        if r and r['적합도'] >= 90: # 90점 이상만 저장
            r['종목명'] = row['Name']
            st.session_state.scan_storage.append(r)
        prog.progress((i + 1) / 1000)
    st.rerun()

if st.session_state.scan_storage:
    st.subheader("📋 [Gold Set] 적합도 90% 이상 리스트")
    scan_df = pd.DataFrame(st.session_state.scan_storage)
    cols = ['종목명', '종목코드', '적합도', '현재가', '목표가', '손절가', 'MFI', '거래대금', '유지기간']
    st.dataframe(scan_df[cols].sort_values(by='적합도', ascending=False), use_container_width=True, hide_index=True)

with st.expander("💡 지휘관 매수 후 행동 강령", expanded=True):
    st.write("1. **종가 매수**: 적합도 90% 이상 종목만 오후 3:20분 이후 진입.")
    st.write("2. **즉시 설정**: 매수 직후 -5% 자동 손절 감시 주문 설정.")
    st.write("3. **10일 원칙**: 매수일 포함 10거래일째 되는 날 종가에 무조건 전량 매도 (수익/손실 불문).")
    st.write("4. **기회비용**: 10일간 안 움직이는 종목은 에너지가 죽은 것임. 현금화 후 새 기체 탑승.")