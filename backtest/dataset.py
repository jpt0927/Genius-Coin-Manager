import pandas as pd
from binance.client import Client
from datetime import datetime
import time

print("--- 스크립트 실행 시작 ---")
client = Client("", "")
symbol = 'BTCUSDT'

# 1. 2018년부터 현재까지 매달 시작일을 리스트로 생성
# freq='MS'는 Month Start(매월 시작일)를 의미
dates = pd.date_range(start='2018-01-01', end=datetime.now(), freq='MS')

all_data_frames = [] # 월별로 받은 데이터를 데이터프레임 형태로 저장할 리스트

# 2. 월별로 반복문 실행
for start_date in dates:
    # 월의 시작과 끝을 문자열로 변환 (API 요청에 사용)
    start_str = start_date.strftime('%Y-%m-%d')
    end_str = (start_date + pd.offsets.MonthEnd(1)).strftime('%Y-%m-%d')
    
    print(f"===== {start_str} ~ {end_str} 데이터 수집 시작 =====")

    try:
        # get_historical_klines는 end_str도 받을 수 있음
        klines = client.get_historical_klines(
            symbol=symbol,
            interval=Client.KLINE_INTERVAL_1MINUTE,
            start_str=start_str,
            end_str=end_str
        )

        if not klines:
            print(f"{start_str} 기간에 데이터가 없습니다.")
            continue

        # 받아온 데이터를 데이터프레임으로 변환
        df_monthly = pd.DataFrame(klines, columns=[
            'Open time', 'Open', 'High', 'Low', 'Close', 'Volume', 'Close time',
            'Quote asset volume', 'Number of trades', 'Taker buy base asset volume',
            'Taker buy quote asset volume', 'Ignore'
        ])
        all_data_frames.append(df_monthly)
        print(f"✅ {start_str} 기간 데이터 수집 완료. {len(klines)}개 캔들.")

    except Exception as e:
        print(f"❌ {start_str} 기간 데이터 수집 중 에러 발생: {e}")
    
    time.sleep(1) # 각 월별 요청 사이에 1초 휴식

print("\n===== 모든 데이터 수집 완료! 최종 파일로 병합합니다. =====")

# 3. 모든 월별 데이터프레임을 하나로 합치기
final_df = pd.concat(all_data_frames, ignore_index=True)

# 4. 데이터 클리닝 및 타입 변환 (기존 코드와 동일)
final_df = final_df[['Open time', 'Open', 'High', 'Low', 'Close', 'Volume']]
final_df['Open time'] = pd.to_datetime(final_df['Open time'], unit='ms')
for col in ['Open', 'High', 'Low', 'Close', 'Volume']:
    final_df[col] = pd.to_numeric(final_df[col])

# 중복 데이터 제거 (월과 월 사이에 겹치는 데이터가 있을 수 있으므로)
final_df.drop_duplicates(subset=['Open time'], inplace=True)

# 5. CSV 파일로 저장
file_name = f'{symbol}_1m_from_2018_to_present.csv'
final_df.to_csv(file_name, index=False)

print(f"🎉 '{file_name}' 파일 저장 완료!")