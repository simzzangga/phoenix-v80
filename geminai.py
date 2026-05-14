import streamlit as st
import FinanceDataReader as fdr
import pandas as pd
import numpy as np
import datetime
import os
import time

# --- [1. 시스템 설정 및 자동 백업] ---
BACKUP_KRX_FILE = "backup_krx.json"

@st.cache_data(ttl=3600)
def get_full_krx_list():
    try:
        df = fdr.StockListing('KRX')[['Code', 'Name']]
        df['Code'] = df['Code'].astype(str).str.zfill(6)
        df.to_json(BACKUP_KRX_FILE)
        return df
    except:
        if os.path.exists(BACKUP_KRX_FILE):
            return pd.read_json(BACKUP_KRX_FILE)
        return pd.DataFrame([{"Code": "005930", "Name": "삼성전자"}])

# --- [2. v5.9.80 스캔 전용 엔진] ---
def scan_engine_v80(ticker, name):
    ticker_str = str(ticker).zfill(6)
    target_date = datetime.date.today()
    start_date = target_date - datetime.timedelta(days=200)
    
    try:
        df = fdr.DataReader(ticker_str, start_date, target_date)
        if df is None or len(df) < 40: return None
        df.columns = [c.upper() for c in df.columns]
        df = df.rename(columns={'시가':'OPEN','고가':'HIGH','저가':'LOW','종가':'CLOSE','거래량':'VOLUME','거래대금':'AMOUNT'})
        
        # [A. 기준봉 품질 체크]
        lookback = df.iloc[-25:]
        base_candle = lookback[(lookback['AMOUNT'] >= 50_000_000_000) & 
                              ((lookback['OPEN'] / lookback['CLOSE'].shift(1)) < 1.025) &
                              ((lookback['CLOSE'] / lookback['OPEN']) >= 1.05)]
        trust_bonus = 30 if not base_candle.empty else 0

        # [B. MFI 연산]
        tp = (df['HIGH'] + df['LOW'] + df['CLOSE']) / 3
        mf = tp * df['VOLUME']
        mfi_period = 14
        pos_mf = mf.where(tp > tp.shift(1), 0).rolling(window=mfi_period).sum()
        neg_mf = mf.where(tp < tp.shift(1), 0).rolling(window=mfi_period).sum()
        mfi = 100 - (100 / (1 + pos_mf / (neg_mf + 1e-10)))
        curr_mfi = mfi.iloc[-1]

        # [C. 변수 연산]
        vol_ratio = df['VOLUME'].iloc[-1] / (df['VOLUME'].iloc[-21:-1].mean() + 1)
        pre_20 = df.iloc[-21:-1]
        cv_val = (pre_20['CLOSE'].std() / pre_20['CLOSE'].mean()) * 100
        
        # [D. 적합도 산출]
        similarity = ((max(0, 100 - (abs(cv_val - 1.8) * 20))) * 0.3) + ((min(100, (vol_ratio / 5.0) * 100)) * 0.7)
        
        fit_score = trust_bonus
        if 82.5 <= similarity <= 88.0: fit_score += 25
        if 2.8 <= vol_ratio <= 4.2: fit_score += 20
        if 1.5 <= cv_val <= 2.2: fit_score += 15
        if 20 <= curr_mfi <= 45: fit_score += 10
        
        if fit_score >= 90:
            return {
                "종목명": name, "종목코드": ticker_str, "적합도": fit_score,
                "현재가": int(df['CLOSE'].iloc[-1]), "목표가": int(df['CLOSE'].iloc[-1] * 1.08),
                "MFI": round(curr_mfi, 1), "거래대금": f"{int(df['AMOUNT'].iloc[-1]/100000000):,}억"
            }
    except: pass
    return None

# --- [3. UI 레이아웃] ---
st.set_page_config(page_title="Phoenix v5.9.80 Full-Scan", layout="wide")
st.markdown("<style>div.stApp {background: white !important;} * {color: black !important;}</style>", unsafe_allow_html=True)

st.title("🛰️ Phoenix v5.9.80 [Full-Scan Edition]")

if st.button("🚀 KRX 전 종목 정밀 스캔 시작 (약 2,500개)", width='stretch'):
    krx_list = get_full_krx_list()
    results = []
    
    prog_bar = st.progress(0)
    status_text = st.empty()
    time_text = st.empty()
    
    start_time = time.time()
    total_count = len(krx_list)
    
    for i, (idx, row) in enumerate(krx_list.iterrows()):
        res = scan_engine_v80(row['Code'], row['Name'])
        if res:
            results.append(res)
        
        # [실시간 상태 브리핑 로직]
        if i % 10 == 0 or i == total_count - 1:
            elapsed_time = time.time() - start_time
            avg_time_per_stock = elapsed_time / (i + 1)
            remaining_stocks = total_count - (i + 1)
            estimated_remaining_time = avg_time_per_stock * remaining_stocks
            
            prog_bar.progress((i + 1) / total_count)
            status_text.markdown(f"**📡 스캔 중:** `[{row['Code']}] {row['Name']}` (`{i+1}`/`{total_count}`)")
            time_text.markdown(f"**⏱️ 예상 남은 시간:** `{int(estimated_remaining_time // 60)}분 {int(estimated_remaining_time % 60)}초` | **경과 시간:** `{int(elapsed_time // 60)}분 {int(elapsed_time % 60)}초` ")
            
    prog_bar.empty()
    status_text.empty()
    time_text.empty()
    
    st.divider()
    
    if results:
        st.subheader(f"🎯 포착된 정예 종목 ({len(results)}개)")
        scan_df = pd.DataFrame(results)
        st.dataframe(scan_df.sort_values(by='적합도', ascending=False), use_container_width=True, hide_index=True)
        st.success(f"✅ 스캔 완료! (총 소요 시간: {int((time.time() - start_time)//60)}분 {int((time.time() - start_time)%60)}초)")
    else:
        st.warning("⚠️ 현재 조건(적합도 90점 이상)을 충족하는 종목이 없습니다.")
