import pandas as pd
import mplfinance as mpf


def original_graph(start_date='2025-01-01', end_date='2025-06-30', type='D'):
    file_name = 'data.csv'

    try:
        df = pd.read_csv(file_name, parse_dates=['Open time'])

        df.set_index('Open time', inplace=True)

        print(f"{file_name} 파일 로딩 성공!")

    except FileNotFoundError:
        print(f"파일을 찾을 수 없습니다.")
        exit()

    df_period = df[start_date:end_date]

    # 데이터 리샘플링(1분봉 -> 1일봉)
    df_resampled = df_period.resample(type).agg({
        'Open': 'first',
        'High': 'max',
        'Low': 'min',
        'Close': 'last',
        'Volume': 'sum'
    }).dropna()

    print(f"{start_date}부터 {end_date}까지의 일봉 차트를 생성합니다...")

    mc = mpf.make_marketcolors(
        up='r',
        down='b',
        volume={'up': 'r', 'down': 'b'}
    )

    my_style = mpf.make_mpf_style(marketcolors=mc, gridstyle='--')

    mpf.plot(df_resampled,
            type='candle',
            style=my_style,
            title=f'BTC/USDT Daily Chart ({start_date} to {end_date})',
            ylabel='price ($)',
            volume=True,
            mav=(5, 20)
    )




# 직접 실행했을 떄만 실행할 부분
if __name__ == "__main__":
    print("visualization.py이 직접 실행됩니다...")
    original_graph()