"""
모든 invest 함수의 공통된 조건

input -> (strategy_param, df, initial_cash, fee_rate)
return -> { 'total_return_pct': ~, 'mdd_pct': ~, 'total_trades': ~, asset_history': [~, ~ ...] }

"""

import numpy as np
import pandas as pd

# 이동평균선 크로스오버 전략
def ma_crossover_strategy(params, df, initial_cash, fee_rate):
    short_ma_period = params.get('short_ma', 20)
    long_ma_period = params.get('long_ma', 60)

    # 이동평균선 계산
    df['MA_short'] = df['Close'].rolling(window=short_ma_period).mean()
    df['MA_long'] = df['Close'].rolling(window=long_ma_period).mean()
    df.dropna(inplace=True)

    cash = initial_cash
    coins = 0
    trades = 0
    asset_history = []

    for i in range(1, len(df)):
        # 골든 크로스일 때 매수
        if df['MA_short'].iloc[i-1] <= df['MA_long'].iloc[i-1] and df['MA_short'].iloc[i] > df['MA_long'].iloc[i] and cash > 0:
            buy_amount = cash / df['Close'].iloc[i]
            coins = buy_amount * (1 - fee_rate)
            cash = 0
            trades += 1
        # 데드 크로스일 떄 매도
        elif df['MA_short'].iloc[i-1] >= df['MA_long'].iloc[i-1] and df['MA_short'].iloc[i] < df['MA_long'].iloc[i] and coins > 0:
            sell_revenue = coins * df['Close'].iloc[i]
            cash = sell_revenue * (1 - fee_rate)
            coins = 0
            trades += 1
        
        current_asset = cash + coins * df['Close'].iloc[i]
        asset_history.append(current_asset)
    
    # 최종 결과 계산
    final_asset = asset_history[-1] if asset_history else initial_cash
    total_return = (final_asset / initial_cash - 1) * 100

    # MDD 계산
    asset_series = pd.Series(asset_history)
    cumulative_max = asset_series.cummax()
    drawdown = (cumulative_max - asset_series) / cumulative_max
    mdd = drawdown.max() * 100 if not drawdown.empty else 0

    return {
        'total_return_pct': total_return,
        'mdd_pct': -mdd,
        'total_trades': trades,
        'asset_history': asset_history
    }