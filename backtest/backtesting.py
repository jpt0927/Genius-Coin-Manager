import pandas as pd
import time

def backtest(strategy_function, strategy_param, resample_period='h', window_size=pd.DateOffset(months=6), step_size=pd.DateOffset(days=1), progress_callback=None, plot_callback=None, initial_cash=100, fee_rate=0.001):
    """롤링 윈도우 백테스팅 (일반)"""
    print("롤링 윈도우 백테스팅을 시작합니다.")
    try:
        df = pd.read_csv('backtest/data.csv', parse_dates=['Open time'], index_col='Open time')
        df_resampled = df.resample(resample_period).agg({
            'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last', 'Volume': 'sum'
        }).dropna()
        print(f"데이터 준비 완료 ({resample_period} 봉)")
    except FileNotFoundError:
        print("데이터 파일을 찾을 수 없습니다."); return None

    start_date, end_date = df_resampled.index[0], df_resampled.index[-1]
    current_start = start_date
    all_results, total_steps, current_step = [], 0, 0

    temp_start = start_date
    while temp_start + window_size <= end_date:
        total_steps += 1; temp_start += step_size

    while current_start + window_size <= end_date:
        current_end = current_start + window_size
        window_df = df_resampled.loc[current_start:current_end]
        if len(window_df) < 20: current_start += step_size; continue
        
        window_strategy_result = strategy_function(strategy_param, window_df.copy(), initial_cash, fee_rate, leverage=1)
        market_return = (window_df['Close'].iloc[-1] / window_df['Close'].iloc[0]) - 1

        all_results.append({
            'start_date': current_start, 'end_date': current_end,
            'strategy_return': window_strategy_result['total_return_pct'],
            'market_return': market_return * 100,
            'strategy_mdd': window_strategy_result['mdd_pct'],
            'total_trades': window_strategy_result['total_trades']
        })
        current_start += step_size; current_step += 1
        if progress_callback: progress_callback(current_step, total_steps)
        if plot_callback: plot_callback(current_start, window_strategy_result['total_return_pct'], market_return * 100)
    
    if not all_results: print("백테스팅을 실행할 기간이 충분하지 않습니다."); return None
    
    results_df = pd.DataFrame(all_results)
    avg_return = results_df['strategy_return'].mean()
    final_balance = initial_cash * (1 + avg_return / 100)
    return {
        'final_balance': final_balance, 'total_return_pct': avg_return,
        'mdd_pct': results_df['strategy_mdd'].mean(),
        'win_rate_pct': (results_df['strategy_return'] > results_df['market_return']).mean() * 100,
        'total_trades': results_df['total_trades'].sum()
    }


def leverage_backtest(strategy_function, strategy_param, leverage, resample_period='h', window_size=pd.DateOffset(months=6), step_size=pd.DateOffset(days=1), progress_callback=None, plot_callback=None, initial_cash=100, fee_rate=0.001):
    """롤링 윈도우 백테스팅 (레버리지)"""
    print(f"롤링 레버리지 백테스팅을 시작합니다. (레버리지: {leverage}x)")
    try:
        df = pd.read_csv('backtest/data.csv', parse_dates=['Open time'], index_col='Open time')
        df_resampled = df.resample(resample_period).agg({
            'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last', 'Volume': 'sum'
        }).dropna()
        print(f"데이터 준비 완료 ({resample_period} 봉)")
    except FileNotFoundError:
        print("데이터 파일을 찾을 수 없습니다."); return None
    
    start_date, end_date = df_resampled.index[0], df_resampled.index[-1]
    current_start = start_date
    all_results, total_steps, current_step = [], 0, 0
    
    temp_start = start_date
    while temp_start + window_size <= end_date:
        total_steps += 1; temp_start += step_size
    
    while current_start + window_size <= end_date:
        current_end = current_start + window_size
        window_df = df_resampled.loc[current_start:current_end]
        if len(window_df) < 20: current_start += step_size; continue
        
        window_strategy_result = strategy_function(strategy_param, window_df.copy(), initial_cash, fee_rate, leverage)
        
        # ⭐ --- 시장 수익률을 레버리지 없는 1배로 계산하도록 수정 ---
        start_price, end_price = window_df['Close'].iloc[0], window_df['Close'].iloc[-1]
        market_return_spot = ((end_price / start_price) - 1) * 100
            
        all_results.append({
            'start_date': current_start, 'end_date': current_end,
            'strategy_return': window_strategy_result['total_return_pct'],
            'market_return': market_return_spot, # 수정된 값 사용
            'strategy_mdd': window_strategy_result['mdd_pct'],
            'total_trades': window_strategy_result['total_trades'],
            'total_liquidations': window_strategy_result.get('total_liquidations', 0)
        })
        current_start += step_size; current_step += 1
        if progress_callback: progress_callback(current_step, total_steps)
        if plot_callback: plot_callback(current_start, window_strategy_result['total_return_pct'], market_return_spot) # 수정된 값 전달
    
    
    if not all_results: print("백테스팅을 실행할 기간이 충분하지 않습니다."); return None
        
    results_df = pd.DataFrame(all_results)
    avg_return = results_df['strategy_return'].mean()
    final_balance = initial_cash * (1 + avg_return / 100)
    return {
        'leverage': f"{leverage}x", 'final_balance': final_balance, 'total_return_pct': avg_return,
        'mdd_pct': results_df['strategy_mdd'].mean(),
        'win_rate_pct': (results_df['strategy_return'] > results_df['market_return']).mean() * 100,
        'total_trades': results_df['total_trades'].sum(),
        'avg_liquidations_per_window': results_df['total_liquidations'].mean()
    }


def backtest_full_period(strategy_function, strategy_param, resample_period='h', start_date=None, initial_cash=100, fee_rate=0.001, leverage=1, plot_callback=None):
    """전체 데이터 기간에 대해 단일 백테스트를 실행 (지표 예열 및 자산 정규화 기능 추가)"""
    print(f"전체 기간 백테스팅을 시작합니다. (레버리지: {leverage}x)")

    try:
        df = pd.read_csv('backtest/data.csv', parse_dates=['Open time'], index_col='Open time')
        df_resampled = df.resample(resample_period).agg({
            'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last', 'Volume': 'sum'
        }).dropna()
        
        warmup_period = 0
        for key, value in strategy_param.items():
            if 'period' in key or 'len' in key:
                if isinstance(value, int) and value > warmup_period:
                    warmup_period = value
        print(f"지표 예열 기간: {warmup_period} 캔들")

        df_for_strategy = df_resampled.copy()
        if start_date:
            # ⭐ --- 예열 시작 날짜 계산 로직 수정 ---
            try:
                # pandas의 to_offset 기능을 사용하여 안정적으로 날짜 계산
                time_offset = pd.tseries.frequencies.to_offset(resample_period)
                data_start_date = start_date - (warmup_period * time_offset)
                df_for_strategy = df_resampled.loc[data_start_date:].copy()
            except Exception as e:
                print(f"예열 기간 계산 중 오류 발생: {e}. 예열 없이 진행합니다.")
                df_for_strategy = df_resampled.loc[start_date:].copy()
            # ⭐ --- 수정 끝 ---

        print(f"데이터 준비 완료 ({resample_period} 봉, 예열 포함 시작: {df_for_strategy.index[0]})")
    except FileNotFoundError:
        print("데이터 파일을 찾을 수 없습니다."); return None, None
    
    # ⭐ --- 3. 예열된 데이터로 전략 실행 ---
    strategy_results = strategy_function(strategy_param, df_for_strategy, initial_cash, fee_rate, leverage)

    raw_asset_history = pd.Series(strategy_results['asset_history'], index=df_for_strategy.index)
    
    # ⭐ --- 자산 곡선 정규화(Normalization) 로직 시작 ---
    if start_date:
        # 실제 테스트 기간의 기록만 잘라냄
        strategy_asset_history = raw_asset_history.loc[start_date:].copy()
        if not strategy_asset_history.empty:
            # 테스트 시작일의 자산 가치를 확인
            start_day_asset = strategy_asset_history.iloc[0]
            # 시작 자산을 initial_cash(100)으로 맞추기 위한 보정값 계산
            if start_day_asset != 0:
                scaling_factor = initial_cash / start_day_asset
                # 테스트 기간 전체의 자산 기록에 보정값을 곱해줌
                strategy_asset_history *= scaling_factor
    else:
        strategy_asset_history = raw_asset_history

    # --- 시장(Buy-and-Hold) 자산 기록 계산 ---
    # 시장 수익률은 사용자가 지정한 start_date부터 계산
    market_df = df_resampled.loc[start_date:].copy() if start_date else df_resampled.copy()
    market_balance_history = []
    start_price = market_df['Close'].iloc[0]
    coins_held = (initial_cash / start_price) * (1 - fee_rate)
    for i in range(len(market_df)):
        current_price = market_df['Close'].iloc[i]
        market_balance_history.append(coins_held * current_price)

    # --- 결과 데이터프레임 생성 ---
    results_df = pd.DataFrame(index=strategy_asset_history.index)
    results_df['Strategy'] = strategy_asset_history
    results_df['Market'] = market_balance_history
    
    # ⭐ --- 콜백 호출 로직 추가 시작 ---
    if plot_callback:
        last_date = None
        # 데이터프레임을 한 줄씩 반복
        for timestamp, row in results_df.iterrows():
            current_date = timestamp.date()
            # 날짜가 바뀔 때마다 콜백 함수 호출
            if last_date is None or current_date != last_date:
                plot_callback(timestamp, row['Strategy'], row['Market'])
                time.sleep(0.001) # UI가 업데이트될 시간을 줌 (시각적 효과)
                last_date = current_date
        # 마지막 데이터 포인트도 전송
        last_row = results_df.iloc[-1]
        plot_callback(results_df.index[-1], last_row['Strategy'], last_row['Market'])
    # ⭐ --- 콜백 호출 로직 추가 끝 ---
    
    market_series = pd.Series(results_df['Market'])
    market_mdd = (1 - (market_series / market_series.cummax())).max() * 100
    
    summary = {
        'initial_cash': initial_cash, 'leverage': f"{leverage}x",
        'final_strategy_balance': results_df['Strategy'].iloc[-1],
        'final_market_balance': results_df['Market'].iloc[-1],
        'total_strategy_return_pct': (results_df['Strategy'].iloc[-1] / initial_cash - 1) * 100,
        'total_market_return_pct': (results_df['Market'].iloc[-1] / initial_cash - 1) * 100,
        'strategy_mdd_pct': strategy_results['mdd_pct'],
        'market_mdd_pct': -market_mdd,
        'total_trades': strategy_results['total_trades'],
        'total_liquidations': strategy_results.get('total_liquidations', 0)
    }
    print("전체 기간 백테스팅 완료.")
    return results_df, summary