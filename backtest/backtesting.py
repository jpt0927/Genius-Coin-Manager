import pandas as pd
import matplotlib.pyplot as plt

def backtest(strategy_function, strategy_param, progress_callback=None, plot_callback=None, initial_cash=100, window_size=pd.DateOffset(months=6),
             step_size=pd.DateOffset(days=1), fee_rate=0.001):
    print("백테스팅을 시작합니다.")

    try:
        df = pd.read_csv('data.csv', parse_dates=['Open time'], index_col='Open time')
        df_daily = df.resample('h').agg({
            'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last', 'Volume': 'sum'
        }).dropna()
        print("데이터 준비 완료")
    except FileNotFoundError:
        print("데이터 파일을 찾을 수 없습니다.")
        return None
    
    start_date = df_daily.index[0]
    end_date = df_daily.index[-1]
    current_start = start_date

    total_steps = 0
    temp_start = start_date
    while temp_start + window_size <= end_date:
        total_steps += 1
        temp_start += step_size
    current_step = 0

    all_results = []

    while current_start + window_size <= end_date:
        current_end = current_start + window_size
        window_df = df_daily.loc[current_start:current_end]

        if len(window_df) < 20:
            current_start += step_size
            continue

        window_strategy_result = strategy_function(
            strategy_param,
            df=window_df.copy(),
            initial_cash=initial_cash,
            fee_rate=fee_rate
        )

        market_return = (window_df['Close'].iloc[-1] / window_df['Close'].iloc[0]) - 1

        all_results.append({
            'start_date': current_start,
            'end_date': current_end,
            'strategy_return': window_strategy_result['total_return_pct'],
            'market_return': market_return * 100,
            'strategy_mdd': window_strategy_result['mdd_pct'],
            'total_trades': window_strategy_result['total_trades']
        })

        print(f"{current_start}~ 기간 테스트 완료...")

        current_start += step_size

        current_step += 1

        if progress_callback:
            progress_callback(current_step, total_steps)
        
        if plot_callback:
            plot_callback(current_start, window_strategy_result['total_return_pct'], market_return * 100)
    
    if not all_results:
        print("백테스팅을 실행할 기간이 충분하지 않습니다.")
        return None
    
    results_df = pd.DataFrame(all_results)

    avg_return = results_df['strategy_return'].mean()
    avg_mdd = results_df['strategy_mdd'].mean()
    win_rate = (results_df['strategy_return'] > results_df['market_return']).mean() * 100
    total_trades = results_df['total_trades'].sum()
    final_balance = initial_cash * (1 + avg_return / 100)


    results = {
        'final_balance': final_balance,     # 최종 잔고
        'total_return_pct': avg_return,  # 총 수익률(%)
        'mdd_pct': avg_mdd,           # 최대 낙폭(%)
        'win_rate_pct': win_rate,      # 거래의 승률(%)
        'total_trades': total_trades,      # 총 거래 횟수
    }


    return results


def reverage_backtest(strategy_function, strategy_param, initial_cash=100, window_size=pd.DateOffset(months=6),
             step_size=pd.DateOffset(days=1), fee_rate=0.001):
    print("롤링 레버리지 백테스팅을 시작합니다.")