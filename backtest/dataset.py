# dataset.py

import pandas as pd
from binance.client import Client
from datetime import datetime, timezone
import time
import os

def update_data(file_name='data.csv', symbol='BTCUSDT'):
    """
    지정된 심볼의 데이터를 업데이트합니다. (이어쓰기 방식으로 최적화)
    - 파일이 없으면: 2018년부터 모든 1분봉 데이터를 수집합니다.
    - 파일이 있으면: 마지막 데이터 시점 이후의 1분봉 데이터만 파일 끝에 추가합니다.
    """
    print("--- 데이터 업데이트 스크립트 실행 (최적화 모드) ---")
    client = Client("", "") # API 키와 시크릿 키를 입력하세요

    # 1. 기존 데이터 파일 확인
    if os.path.exists(file_name):
        # ================================================================
        # 파일이 있을 경우 (읽기/쓰기 최소화로 속도 개선)
        # ================================================================
        print(f"'{file_name}' 파일을 발견했습니다. 마지막 데이터 이후의 기록을 업데이트합니다.")
        
        # ※ 성능을 위해 전체 파일을 읽는 대신 마지막 줄만 읽어 날짜를 확인하는 방법도 있지만,
        #   정확성을 위해 현재는 read_csv를 유지합니다. 파일이 매우 클 경우 이 부분도 개선 가능합니다.
        existing_df = pd.read_csv(file_name, parse_dates=['Open time'])
        
        if existing_df.empty:
            # 파일은 있지만 비어있는 예외적인 경우
            last_date = pd.to_datetime('2018-01-01', utc=True)
        else:
            existing_df['Open time'] = pd.to_datetime(existing_df['Open time'], utc=True)
            last_date = existing_df['Open time'].max()

        print(f"마지막 데이터 시점: {last_date}")

        now_utc = datetime.now(timezone.utc)
        if (now_utc - last_date).total_seconds() < 120:
            print("✅ 이미 최신 데이터입니다. 업데이트를 종료합니다.")
            return

        print(f"'{last_date}' 이후의 신규 데이터를 수집합니다.")
        klines = client.get_historical_klines(
            symbol=symbol,
            interval=Client.KLINE_INTERVAL_1MINUTE,
            start_str=str(last_date)
        )
        
        if not klines:
            print("✅ 새롭게 수집된 데이터가 없습니다.")
            return

        new_df = pd.DataFrame(klines, columns=[
            'Open time', 'Open', 'High', 'Low', 'Close', 'Volume', 'Close time',
            'Quote asset volume', 'Number of trades', 'Taker buy base asset volume',
            'Taker buy quote asset volume', 'Ignore'
        ])
        
        new_df = new_df[['Open time', 'Open', 'High', 'Low', 'Close', 'Volume']]
        new_df['Open time'] = pd.to_datetime(new_df['Open time'], unit='ms', utc=True)
        for col in ['Open', 'High', 'Low', 'Close', 'Volume']:
            new_df[col] = pd.to_numeric(new_df[col])

        # API는 start_str로 지정된 시간을 포함해서 데이터를 주므로, 첫 행은 중복 데이터임
        # 따라서 중복을 막기 위해 첫 행을 제거
        if not new_df.empty and new_df['Open time'].iloc[0] == last_date:
            new_df = new_df.iloc[1:]

        if new_df.empty:
            print("✅ 중복 데이터를 제외하고 나니 추가할 새 데이터가 없습니다.")
            return
            
        # ⭐ 핵심: 새로운 데이터만 파일 끝에 이어쓰기
        # mode='a'는 append(추가) 모드를 의미
        # header=False는 기존 파일에 헤더(컬럼명)가 이미 있으므로 추가하지 않는다는 의미
        new_df.to_csv(file_name, mode='a', header=False, index=False)
        
        print(f"🎉 '{file_name}' 파일에 {len(new_df)}개의 신규 데이터를 추가했습니다.")


    else:
        # ================================================================
        # 파일이 없을 경우 (기존과 동일)
        # ================================================================
        print(f"'{file_name}' 파일이 없습니다. 2018년부터 전체 데이터를 수집합니다.")
        # ... (이하 로직은 이전과 동일하므로 생략) ...
        start_date = pd.to_datetime('2018-01-01', utc=True)
        dates = pd.date_range(start=start_date, end=datetime.now(timezone.utc), freq='MS')
        all_data_frames = []

        for month_start in dates:
            start_str = month_start.strftime('%Y-%m-%d')
            end_str = (month_start + pd.offsets.MonthEnd(1)).strftime('%Y-%m-%d')
            print(f"===== {start_str} ~ {end_str} 데이터 수집 시작 =====")
            try:
                klines = client.get_historical_klines(
                    symbol=symbol, interval=Client.KLINE_INTERVAL_1MINUTE,
                    start_str=start_str, end_str=end_str
                )
                if klines:
                    df_monthly = pd.DataFrame(klines, columns=[
                        'Open time', 'Open', 'High', 'Low', 'Close', 'Volume', 'Close time',
                        'Quote asset volume', 'Number of trades', 'Taker buy base asset volume',
                        'Taker buy quote asset volume', 'Ignore'
                    ])
                    all_data_frames.append(df_monthly)
                    print(f"✅ {start_str} 기간 데이터 수집 완료. {len(klines)}개 캔들.")
            except Exception as e:
                print(f"❌ {start_str} 기간 데이터 수집 중 에러 발생: {e}")
            time.sleep(1)

        if not all_data_frames:
            print("데이터 수집에 실패했습니다.")
            return
            
        final_df = pd.concat(all_data_frames, ignore_index=True)
        final_df = final_df[['Open time', 'Open', 'High', 'Low', 'Close', 'Volume']]
        final_df['Open time'] = pd.to_datetime(final_df['Open time'], unit='ms', utc=True)
        for col in ['Open', 'High', 'Low', 'Close', 'Volume']:
            final_df[col] = pd.to_numeric(final_df[col])

        final_df.drop_duplicates(subset=['Open time'], keep='last', inplace=True)
        final_df.sort_values(by='Open time', inplace=True)
        # 처음 생성할 때는 헤더를 포함하여 저장
        final_df.to_csv(file_name, index=False)
        print(f"🎉 '{file_name}' 파일 생성 완료! 총 {len(final_df)}개 데이터.")