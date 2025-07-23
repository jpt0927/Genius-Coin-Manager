# invest_strategy.py (자산 상한선 적용 최종 버전)

import numpy as np
import pandas as pd

# ==============================================================================
# 헬퍼 함수 (지표 직접 계산 및 안정성 강화)
# ==============================================================================

MAX_ASSET_VALUE = 1e15  # 자산 최대 상한선 (1000조)

def calculate_rsi(data, period=14):
    delta = data.diff()
    gain = delta.where(delta > 0, 0); loss = -delta.where(delta < 0, 0)
    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean(); avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
    if avg_loss.empty or avg_loss.iloc[-1] == 0: return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def calculate_bbands(df, length=20, std_dev=2):
    middle_band = df['Close'].rolling(window=length).mean(); std = df['Close'].rolling(window=length).std()
    df['BBM'] = middle_band; df['BBU'] = middle_band + (std * std_dev); df['BBL'] = middle_band - (std * std_dev)
    return df

def calculate_adx(df, period=14):
    df['H-L'] = df['High'] - df['Low']; df['H-PC'] = abs(df['High'] - df['Close'].shift(1)); df['L-PC'] = abs(df['Low'] - df['Close'].shift(1))
    df['TR'] = df[['H-L', 'H-PC', 'L-PC']].max(axis=1)
    df['+DM'] = np.where((df['High'] - df['High'].shift(1)) > (df['Low'].shift(1) - df['Low']), df['High'] - df['High'].shift(1), 0)
    df['-DM'] = np.where((df['Low'].shift(1) - df['Low']) > (df['High'] - df['High'].shift(1)), df['Low'].shift(1) - df['Low'], 0)
    ATR = df['TR'].ewm(alpha=1/period, min_periods=period).mean(); ADX_plus = df['+DM'].ewm(alpha=1/period, min_periods=period).mean(); ADX_minus = df['-DM'].ewm(alpha=1/period, min_periods=period).mean()
    df['+DI'] = (ADX_plus / ATR) * 100; df['-DI'] = (ADX_minus / ATR) * 100
    DX = (abs(df['+DI'] - df['-DI']) / (df['+DI'] + df['-DI'])).fillna(0) * 100
    df['ADX'] = DX.ewm(alpha=1/period, min_periods=period).mean()
    return df

def _calculate_pnl(entry_price, exit_price, position_margin, leverage, position_type):
    if entry_price <= 0 or exit_price <= 0: return 0
    if position_type == 'long': pnl = ((exit_price / entry_price) - 1) * position_margin * leverage
    elif position_type == 'short': pnl = ((entry_price / exit_price) - 1) * position_margin * leverage
    else: pnl = 0
    return 0 if not np.isfinite(pnl) else pnl

def _calculate_asset(entry_price, current_price, position_margin, leverage, position_type, cash):
    if position_type == 'none': return cash
    if entry_price <= 0 or current_price <= 0: return cash
    if position_type == 'long': asset = position_margin + (((current_price / entry_price) - 1) * position_margin * leverage)
    elif position_type == 'short': asset = position_margin + (((entry_price / current_price) - 1) * position_margin * leverage)
    else: asset = cash
    if not np.isfinite(asset): return cash
    # ⭐ 자산 상한선 적용
    return min(asset, MAX_ASSET_VALUE)

# ==============================================================================
# 전략 함수들 (공통 로직 수정)
# ==============================================================================

# (모든 레버리지 전략 함수 내부에 아래와 같은 수정이 공통적으로 적용됩니다)
# cash = (position_margin + pnl) * (1 - fee_rate)
# # ⭐ 자산 상한선 적용
# cash = min(cash, MAX_ASSET_VALUE)


def ma_crossover_strategy(params, df, initial_cash, fee_rate, leverage=1):
    short_ma_period = params.get('short_ma', 20); long_ma_period = params.get('long_ma', 60)
    df['MA_short'] = df['Close'].rolling(window=short_ma_period).mean(); df['MA_long'] = df['Close'].rolling(window=long_ma_period).mean(); df.dropna(inplace=True)
    cash, coins, trades, asset_history = initial_cash, 0, 0, []
    for i in range(1, len(df)):
        if df['MA_short'].iloc[i-1] <= df['MA_long'].iloc[i-1] and df['MA_short'].iloc[i] > df['MA_long'].iloc[i] and cash > 0:
            coins = (cash / df['Close'].iloc[i]) * (1 - fee_rate); cash = 0; trades += 1
        elif df['MA_short'].iloc[i-1] >= df['MA_long'].iloc[i-1] and df['MA_short'].iloc[i] < df['MA_long'].iloc[i] and coins > 0:
            cash = (coins * df['Close'].iloc[i]) * (1 - fee_rate); coins = 0; trades += 1
        asset_history.append(cash + coins * df['Close'].iloc[i])
    final_asset = asset_history[-1] if asset_history else initial_cash
    total_return = (final_asset / initial_cash - 1) * 100
    asset_series = pd.Series(asset_history); mdd = (1 - (asset_series / asset_series.cummax())).max() * 100
    return {'total_return_pct': total_return, 'mdd_pct': -mdd, 'total_trades': trades, 'asset_history': asset_history}

def ma_crossover_leverage_strategy(params, df, initial_cash, fee_rate, leverage):
    short_ma_period=params.get('short_ma', 20); long_ma_period=params.get('long_ma', 60)
    df['MA_short'] = df['Close'].rolling(window=short_ma_period).mean(); df['MA_long'] = df['Close'].rolling(window=long_ma_period).mean(); df.dropna(inplace=True)
    if df.empty: return {'total_return_pct': 0, 'mdd_pct': 0, 'total_trades': 0, 'total_liquidations': 0, 'asset_history': []}
    cash = initial_cash; asset_history = [initial_cash]
    trades, liquidations, position_status, entry_price, position_margin, liquidation_price = 0, 0, 'none', 0, 0, 0
    for i in range(1, len(df)):
        current_price = df['Close'].iloc[i]
        if position_status == 'long' and df['Low'].iloc[i] <= liquidation_price:
            cash, position_status, liquidations = 0, 'none', liquidations + 1; asset_history.append(cash); continue
        elif position_status == 'short' and df['High'].iloc[i] >= liquidation_price:
            cash, position_status, liquidations = 0, 'none', liquidations + 1; asset_history.append(cash); continue
        if cash <= 0: asset_history.append(cash); continue
        is_golden_cross = df['MA_short'].iloc[i-1] <= df['MA_long'].iloc[i-1] and df['MA_short'].iloc[i] > df['MA_long'].iloc[i]
        is_dead_cross = df['MA_short'].iloc[i-1] >= df['MA_long'].iloc[i-1] and df['MA_short'].iloc[i] < df['MA_long'].iloc[i]
        if is_golden_cross:
            if position_status == 'short':
                pnl = _calculate_pnl(entry_price, current_price, position_margin, leverage, 'short')
                cash = (position_margin + pnl) * (1 - fee_rate); cash = min(cash, MAX_ASSET_VALUE)
                position_status, trades = 'none', trades + 1
            if position_status == 'none':
                position_margin, entry_price, position_status, trades = cash, current_price, 'long', trades + 1; liquidation_price = entry_price * (1 - 1/leverage)
        elif is_dead_cross:
            if position_status == 'long':
                pnl = _calculate_pnl(entry_price, current_price, position_margin, leverage, 'long')
                cash = (position_margin + pnl) * (1 - fee_rate); cash = min(cash, MAX_ASSET_VALUE)
                position_status, trades = 'none', trades + 1
            if position_status == 'none':
                position_margin, entry_price, position_status, trades = cash, current_price, 'short', trades + 1; liquidation_price = entry_price * (1 + 1/leverage)
        current_asset = _calculate_asset(entry_price, current_price, position_margin, leverage, position_status, cash)
        asset_history.append(current_asset)
    final_asset = asset_history[-1] if asset_history else initial_cash; total_return = (final_asset / initial_cash - 1) * 100
    asset_series = pd.Series(asset_history); mdd = (1 - (asset_series / asset_series.cummax())).max() * 100
    return {'total_return_pct': total_return, 'mdd_pct': -mdd, 'total_trades': trades, 'total_liquidations': liquidations, 'asset_history': asset_history}

def rsi_leverage_strategy(params, df, initial_cash, fee_rate, leverage):
    rsi_period=params.get('rsi_period', 14); oversold_threshold=params.get('oversold_threshold', 30); overbought_threshold=params.get('overbought_threshold', 70)
    df['RSI'] = calculate_rsi(df['Close'], period=rsi_period); df.dropna(inplace=True)
    if df.empty: return {'total_return_pct': 0, 'mdd_pct': 0, 'total_trades': 0, 'total_liquidations': 0, 'asset_history': []}
    cash = initial_cash; asset_history = [initial_cash]
    trades, liquidations, position_status, entry_price, position_margin, liquidation_price = 0, 0, 'none', 0, 0, 0
    for i in range(1, len(df)):
        current_price = df['Close'].iloc[i]
        if position_status == 'long' and df['Low'].iloc[i] <= liquidation_price:
            cash, position_status, liquidations = 0, 'none', liquidations + 1; asset_history.append(cash); continue
        elif position_status == 'short' and df['High'].iloc[i] >= liquidation_price:
            cash, position_status, liquidations = 0, 'none', liquidations + 1; asset_history.append(cash); continue
        if cash <= 0: asset_history.append(cash); continue
        is_buy_signal = df['RSI'].iloc[i-1] < oversold_threshold and df['RSI'].iloc[i] >= oversold_threshold
        is_sell_signal = df['RSI'].iloc[i-1] > overbought_threshold and df['RSI'].iloc[i] <= overbought_threshold
        if is_buy_signal:
            if position_status == 'short':
                pnl = _calculate_pnl(entry_price, current_price, position_margin, leverage, 'short')
                cash = (position_margin + pnl) * (1 - fee_rate); cash = min(cash, MAX_ASSET_VALUE)
                position_status, trades = 'none', trades + 1
            if position_status == 'none':
                position_margin, entry_price, position_status, trades = cash, current_price, 'long', trades + 1; liquidation_price = entry_price * (1 - 1/leverage)
        elif is_sell_signal:
            if position_status == 'long':
                pnl = _calculate_pnl(entry_price, current_price, position_margin, leverage, 'long')
                cash = (position_margin + pnl) * (1 - fee_rate); cash = min(cash, MAX_ASSET_VALUE)
                position_status, trades = 'none', trades + 1
            if position_status == 'none':
                position_margin, entry_price, position_status, trades = cash, current_price, 'short', trades + 1; liquidation_price = entry_price * (1 + 1/leverage)
        current_asset = _calculate_asset(entry_price, current_price, position_margin, leverage, position_status, cash)
        asset_history.append(current_asset)
    final_asset = asset_history[-1] if asset_history else initial_cash; total_return = (final_asset / initial_cash - 1) * 100
    asset_series = pd.Series(asset_history); mdd = (1 - (asset_series / asset_series.cummax())).max() * 100
    return {'total_return_pct': total_return, 'mdd_pct': -mdd, 'total_trades': trades, 'total_liquidations': liquidations, 'asset_history': asset_history}

def bollinger_band_leverage_strategy(params, df, initial_cash, fee_rate, leverage):
    bb_length=params.get('bb_length', 20); bb_std=params.get('bb_std', 2);
    df = calculate_bbands(df, length=bb_length, std_dev=bb_std); df.dropna(inplace=True)
    if df.empty: return {'total_return_pct': 0, 'mdd_pct': 0, 'total_trades': 0, 'total_liquidations': 0, 'asset_history': []}
    cash = initial_cash; asset_history = [initial_cash]
    trades, liquidations, position_status, entry_price, position_margin, liquidation_price = 0, 0, 'none', 0, 0, 0
    for i in range(1, len(df)):
        current_price = df['Close'].iloc[i]
        if position_status == 'long' and df['Low'].iloc[i] <= liquidation_price:
            cash, position_status, liquidations = 0, 'none', liquidations + 1; asset_history.append(cash); continue
        elif position_status == 'short' and df['High'].iloc[i] >= liquidation_price:
            cash, position_status, liquidations = 0, 'none', liquidations + 1; asset_history.append(cash); continue
        if position_status == 'long' and current_price >= df['BBM'].iloc[i]:
            pnl = _calculate_pnl(entry_price, current_price, position_margin, leverage, 'long')
            cash = (position_margin + pnl) * (1 - fee_rate); cash = min(cash, MAX_ASSET_VALUE)
            position_status, trades = 'none', trades + 1
        elif position_status == 'short' and current_price <= df['BBM'].iloc[i]:
            pnl = _calculate_pnl(entry_price, current_price, position_margin, leverage, 'short')
            cash = (position_margin + pnl) * (1 - fee_rate); cash = min(cash, MAX_ASSET_VALUE)
            position_status, trades = 'none', trades + 1
        if cash <= 0 and position_status == 'none': asset_history.append(cash); continue
        if position_status == 'none':
            if current_price < df['BBL'].iloc[i]:
                position_margin, entry_price, position_status, trades = cash, current_price, 'long', trades + 1; liquidation_price = entry_price * (1 - 1/leverage)
            elif current_price > df['BBU'].iloc[i]:
                position_margin, entry_price, position_status, trades = cash, current_price, 'short', trades + 1; liquidation_price = entry_price * (1 + 1/leverage)
        current_asset = _calculate_asset(entry_price, current_price, position_margin, leverage, position_status, cash)
        asset_history.append(current_asset)
    final_asset = asset_history[-1] if asset_history else initial_cash; total_return = (final_asset / initial_cash - 1) * 100
    asset_series = pd.Series(asset_history); mdd = (1 - (asset_series / asset_series.cummax())).max() * 100
    return {'total_return_pct': total_return, 'mdd_pct': -mdd, 'total_trades': trades, 'total_liquidations': liquidations, 'asset_history': asset_history}

def adx_filtered_dual_strategy(params, df, initial_cash, fee_rate, leverage):
    adx_period=params.get('adx_period',14); adx_threshold=params.get('adx_threshold',25); rsi_period=params.get('rsi_period',14); oversold_threshold=params.get('oversold_threshold',30); overbought_threshold=params.get('overbought_threshold',70); ema_short_period=params.get('ema_short_period',12); ema_long_period=params.get('ema_long_period',26); stop_loss_pct=params.get('stop_loss_pct',-1.5); take_profit_pct=params.get('take_profit_pct',3.0)
    df = calculate_adx(df, period=adx_period); df['RSI'] = calculate_rsi(df['Close'], period=rsi_period); df['EMA_short'] = df['Close'].ewm(span=ema_short_period, adjust=False).mean(); df['EMA_long'] = df['Close'].ewm(span=ema_long_period, adjust=False).mean(); df.dropna(inplace=True)
    if df.empty: return {'total_return_pct': 0, 'mdd_pct': 0, 'total_trades': 0, 'total_liquidations': 0, 'asset_history': []}
    cash = initial_cash; asset_history = [initial_cash]
    trades, liquidations, position_status, entry_price, position_margin, stop_loss_price, take_profit_price = 0, 0, 'none', 0, 0, 0, 0
    for i in range(1, len(df)):
        current_price = df['Close'].iloc[i]
        if position_status != 'none':
            exit_price, pnl, is_liquidated = 0, 0, False
            if position_status == 'long':
                liquidation_price = entry_price * (1 - 1/leverage) if leverage > 0 else 0
                if df['Low'].iloc[i] <= liquidation_price: exit_price, liquidations, is_liquidated = liquidation_price, liquidations + 1, True
                elif stop_loss_pct != 0 and df['Low'].iloc[i] <= stop_loss_price: exit_price = stop_loss_price
                elif take_profit_pct != 0 and df['High'].iloc[i] >= take_profit_price: exit_price = take_profit_price
                if exit_price > 0: pnl = _calculate_pnl(entry_price, exit_price, position_margin, leverage, 'long')
            elif position_status == 'short':
                liquidation_price = entry_price * (1 + 1/leverage) if leverage > 0 else float('inf')
                if df['High'].iloc[i] >= liquidation_price: exit_price, liquidations, is_liquidated = liquidation_price, liquidations + 1, True
                elif stop_loss_pct != 0 and df['High'].iloc[i] >= stop_loss_price: exit_price = stop_loss_price
                elif take_profit_pct != 0 and df['Low'].iloc[i] <= take_profit_price: exit_price = take_profit_price
                if exit_price > 0: pnl = _calculate_pnl(entry_price, exit_price, position_margin, leverage, 'short')
            if exit_price > 0:
                cash = 0 if is_liquidated else (position_margin + pnl) * (1 - fee_rate); cash = min(cash, MAX_ASSET_VALUE)
                position_status = 'none'
        if position_status == 'none':
            if cash <= 0: asset_history.append(cash); continue
            is_trending_market = df['ADX'].iloc[i] > adx_threshold; signal = 'none'
            if is_trending_market:
                if df['EMA_short'].iloc[i-1]<=df['EMA_long'].iloc[i-1] and df['EMA_short'].iloc[i]>df['EMA_long'].iloc[i]: signal = 'long'
                elif df['EMA_short'].iloc[i-1]>=df['EMA_long'].iloc[i-1] and df['EMA_short'].iloc[i]<df['EMA_long'].iloc[i]: signal = 'short'
            else:
                if df['RSI'].iloc[i-1]<oversold_threshold and df['RSI'].iloc[i]>=oversold_threshold: signal = 'long'
                elif df['RSI'].iloc[i-1]>overbought_threshold and df['RSI'].iloc[i]<=overbought_threshold: signal = 'short'
            if signal != 'none':
                position_margin, entry_price, position_status, trades = cash, current_price, signal, trades + 1
                if stop_loss_pct != 0:
                    if signal == 'long': stop_loss_price = entry_price * (1 + stop_loss_pct / 100); take_profit_price = entry_price * (1 + take_profit_pct / 100)
                    else: stop_loss_price = entry_price * (1 - stop_loss_pct / 100); take_profit_price = entry_price * (1 - take_profit_pct / 100)
        current_asset = _calculate_asset(entry_price, current_price, position_margin, leverage, position_status, cash)
        asset_history.append(current_asset)
    final_asset = asset_history[-1] if asset_history else initial_cash; total_return = (final_asset / initial_cash - 1) * 100
    asset_series = pd.Series(asset_history); mdd = (1 - (asset_series / asset_series.cummax())).max() * 100
    return {'total_return_pct': total_return, 'mdd_pct': -mdd, 'total_trades': trades, 'total_liquidations': liquidations, 'asset_history': asset_history}

def macd_liquidity_tracker(params, df, initial_cash, fee_rate, leverage):
    system_type = params.get('system_type', 'Normal')
    if isinstance(system_type, int): system_type = {0: 'Normal', 1: 'Fast', 2: 'Safe', 3: 'Crossover'}.get(system_type, 'Normal')
    fast_ma_len=params.get('fast_ma',12); slow_ma_len=params.get('slow_ma',26); signal_len=params.get('signal_ma',9); use_trend_filter=params.get('use_trend_filter',True); trend_ma_len=params.get('trend_ma_len',50); stop_loss_pct=params.get('stop_loss_pct',0); take_profit_pct=params.get('take_profit_pct',0)
    ema_fast = df['Close'].ewm(span=fast_ma_len, adjust=False).mean(); ema_slow = df['Close'].ewm(span=slow_ma_len, adjust=False).mean(); df['MACD'] = ema_fast - ema_slow; df['Signal'] = df['MACD'].ewm(span=signal_len, adjust=False).mean(); df['Hist'] = df['MACD'] - df['Signal']
    df['Hist_Color'] = 'none'; is_rising = df['Hist'] > df['Hist'].shift(1); is_above_zero = df['Hist'] > 0
    df.loc[(is_above_zero) & (is_rising), 'Hist_Color'] = 'Bright Blue'; df.loc[(is_above_zero) & (~is_rising), 'Hist_Color'] = 'Dark Blue'; df.loc[(~is_above_zero) & (~is_rising), 'Hist_Color'] = 'Bright Magenta'; df.loc[(~is_above_zero) & (is_rising), 'Hist_Color'] = 'Dark Magenta'
    if use_trend_filter: df['Trend_MA'] = df['Close'].ewm(span=trend_ma_len, adjust=False).mean()
    df.dropna(inplace=True)
    if df.empty: return {'total_return_pct': 0, 'mdd_pct': 0, 'total_trades': 0, 'total_liquidations': 0, 'asset_history': []}
    cash = initial_cash; asset_history = [initial_cash]
    trades, liquidations, position_status, entry_price, position_margin, stop_loss_price, take_profit_price = 0, 0, 'none', 0, 0, 0, 0
    for i in range(1, len(df)):
        current_price = df['Close'].iloc[i]
        if position_status != 'none':
            exit_price, pnl, is_liquidated = 0, 0, False
            if position_status == 'long':
                liquidation_price = entry_price * (1 - 1/leverage) if leverage > 1 else 0
                if df['Low'].iloc[i] <= liquidation_price and leverage > 1: exit_price, liquidations, is_liquidated = liquidation_price, liquidations + 1, True
                elif stop_loss_pct != 0 and df['Low'].iloc[i] <= stop_loss_price: exit_price = stop_loss_price
                elif take_profit_pct != 0 and df['High'].iloc[i] >= take_profit_price: exit_price = take_profit_price
                if exit_price > 0: pnl = _calculate_pnl(entry_price, exit_price, position_margin, leverage, 'long')
            elif position_status == 'short':
                liquidation_price = entry_price * (1 + 1/leverage) if leverage > 1 else float('inf')
                if df['High'].iloc[i] >= liquidation_price and leverage > 1: exit_price, liquidations, is_liquidated = liquidation_price, liquidations + 1, True
                elif stop_loss_pct != 0 and df['High'].iloc[i] >= stop_loss_price: exit_price = stop_loss_price
                elif take_profit_pct != 0 and df['Low'].iloc[i] <= take_profit_price: exit_price = take_profit_price
                if exit_price > 0: pnl = _calculate_pnl(entry_price, exit_price, position_margin, leverage, 'short')
            if exit_price > 0:
                cash = 0 if is_liquidated else (position_margin + pnl) * (1 - fee_rate); cash = min(cash, MAX_ASSET_VALUE); position_status = 'none'
        long_signal, short_signal = False, False
        if system_type == 'Normal': long_signal = df['MACD'].iloc[i] > df['Signal'].iloc[i]; short_signal = df['MACD'].iloc[i] < df['Signal'].iloc[i]
        elif system_type == 'Fast': long_signal = df['Hist_Color'].iloc[i] in ['Bright Blue', 'Dark Magenta']; short_signal = df['Hist_Color'].iloc[i] in ['Dark Blue', 'Bright Magenta']
        elif system_type == 'Safe': long_signal = df['Hist_Color'].iloc[i] == 'Bright Blue'; short_signal = not long_signal
        elif system_type == 'Crossover': long_signal = df['MACD'].iloc[i-1] < df['Signal'].iloc[i-1] and df['MACD'].iloc[i] > df['Signal'].iloc[i]; short_signal = df['MACD'].iloc[i-1] > df['Signal'].iloc[i-1] and df['MACD'].iloc[i] < df['Signal'].iloc[i]
        if use_trend_filter:
            is_uptrend = current_price > df['Trend_MA'].iloc[i]; is_downtrend = current_price < df['Trend_MA'].iloc[i]
            long_signal = long_signal and is_uptrend; short_signal = short_signal and is_downtrend
        if position_status == 'long' and short_signal:
            pnl = _calculate_pnl(entry_price, current_price, position_margin, leverage, 'long'); cash = (position_margin + pnl) * (1 - fee_rate); cash = min(cash, MAX_ASSET_VALUE); position_status = 'none'; trades += 1
        elif position_status == 'short' and long_signal:
            pnl = _calculate_pnl(entry_price, current_price, position_margin, leverage, 'short'); cash = (position_margin + pnl) * (1 - fee_rate); cash = min(cash, MAX_ASSET_VALUE); position_status = 'none'; trades += 1
        if position_status == 'none' and cash > 0:
            signal = 'none'
            if long_signal: signal = 'long'
            elif short_signal: signal = 'short'
            if signal != 'none':
                position_margin, entry_price, position_status, trades = cash, current_price, signal, trades + 1
                if stop_loss_pct != 0:
                    if signal == 'long': stop_loss_price = entry_price * (1 + stop_loss_pct / 100); take_profit_price = entry_price * (1 + take_profit_pct / 100)
                    else: stop_loss_price = entry_price * (1 - stop_loss_pct / 100); take_profit_price = entry_price * (1 - take_profit_pct / 100)
        current_asset = _calculate_asset(entry_price, current_price, position_margin, leverage, position_status, cash)
        asset_history.append(current_asset)
    final_asset = asset_history[-1] if asset_history else initial_cash; total_return = (final_asset / initial_cash - 1) * 100
    asset_series = pd.Series(asset_history); mdd = (1 - (asset_series / asset_series.cummax())).max() * 100
    return {'total_return_pct': total_return, 'mdd_pct': -mdd, 'total_trades': trades, 'total_liquidations': liquidations, 'asset_history': asset_history}



def macd_crossover_with_filter(params, df, initial_cash, fee_rate, leverage):
    """
    MACD Crossover 전략에 시장 국면 필터(200일 MA)를 적용한 버전.
    - 상승장 (현재가 > 200일 MA): MACD Crossover 매매 실행
    - 하락장 (현재가 < 200일 MA): 모든 포지션을 청산하고 매매 중단
    """
    # 1. 파라미터 설정
    fast_ma_len = params.get('fast_ma', 21)
    slow_ma_len = params.get('slow_ma', 55)
    signal_len = params.get('signal_ma', 8)
    stop_loss_pct = params.get('stop_loss_pct', 0)
    take_profit_pct = params.get('take_profit_pct', 0)
    
    # ⭐ 200일 이동평균선 기간 (시간봉에 맞게 설정 필요)
    regime_filter_period = params.get('regime_filter_period', 4800) # 기본값: 1시간봉 기준 200일
    leverage = max(1, leverage)

    # 2. 지표 계산
    ema_fast = df['Close'].ewm(span=fast_ma_len, adjust=False).mean()
    ema_slow = df['Close'].ewm(span=slow_ma_len, adjust=False).mean()
    df['MACD'] = ema_fast - ema_slow
    df['Signal'] = df['MACD'].ewm(span=signal_len, adjust=False).mean()
    
    # ⭐ 시장 국면 판단을 위한 장기 이동평균선 계산
    df['MA_regime'] = df['Close'].rolling(window=regime_filter_period).mean()
    
    df.dropna(inplace=True)
    if df.empty: return {'total_return_pct': 0, 'mdd_pct': 0, 'total_trades': 0, 'total_liquidations': 0, 'asset_history': []}

    # 3. 백테스팅 변수 초기화
    cash = initial_cash
    asset_history = [initial_cash]
    trades, liquidations, position_status, entry_price, position_margin, stop_loss_price, take_profit_price = 0, 0, 'none', 0, 0, 0, 0

    # 4. 백테스팅 루프
    for i in range(1, len(df)):
        current_price = df['Close'].iloc[i]
        
        # --- 4-1. 위험 관리 (손절/익절/강제청산) ---
        if position_status != 'none':
            exit_price, pnl, is_liquidated = 0, 0, False
            if position_status == 'long':
                liquidation_price = entry_price * (1 - 1/leverage) if leverage > 1 else 0
                if df['Low'].iloc[i] <= liquidation_price and leverage > 1: exit_price, liquidations, is_liquidated = liquidation_price, liquidations + 1, True
                elif stop_loss_pct != 0 and df['Low'].iloc[i] <= stop_loss_price: exit_price = stop_loss_price
                elif take_profit_pct != 0 and df['High'].iloc[i] >= take_profit_price: exit_price = take_profit_price
                if exit_price > 0: pnl = _calculate_pnl(entry_price, exit_price, position_margin, leverage, 'long')
            elif position_status == 'short':
                liquidation_price = entry_price * (1 + 1/leverage) if leverage > 1 else float('inf')
                if df['High'].iloc[i] >= liquidation_price and leverage > 1: exit_price, liquidations, is_liquidated = liquidation_price, liquidations + 1, True
                elif stop_loss_pct != 0 and df['High'].iloc[i] >= stop_loss_price: exit_price = stop_loss_price
                elif take_profit_pct != 0 and df['Low'].iloc[i] <= take_profit_price: exit_price = take_profit_price
                if exit_price > 0: pnl = _calculate_pnl(entry_price, exit_price, position_margin, leverage, 'short')
            if exit_price > 0:
                cash = 0 if is_liquidated else (position_margin + pnl) * (1 - fee_rate); cash = min(cash, MAX_ASSET_VALUE); position_status = 'none'

        # ⭐ --- 4-2. 시장 국면 필터 적용 ---
        is_bull_market = current_price > df['MA_regime'].iloc[i]

        # 하락장으로 전환되면, 모든 포지션을 즉시 청산
        if not is_bull_market and position_status != 'none':
            pnl = _calculate_pnl(entry_price, current_price, position_margin, leverage, position_status)
            cash = (position_margin + pnl) * (1 - fee_rate); cash = min(cash, MAX_ASSET_VALUE)
            position_status = 'none'; trades += 1
        
        # 상승장에서만 매매 로직을 실행
        if is_bull_market:
            long_signal = df['MACD'].iloc[i-1] < df['Signal'].iloc[i-1] and df['MACD'].iloc[i] > df['Signal'].iloc[i]
            short_signal = df['MACD'].iloc[i-1] > df['Signal'].iloc[i-1] and df['MACD'].iloc[i] < df['Signal'].iloc[i]

            if position_status == 'long' and short_signal:
                pnl = _calculate_pnl(entry_price, current_price, position_margin, leverage, 'long'); cash = (position_margin + pnl) * (1 - fee_rate); cash = min(cash, MAX_ASSET_VALUE); position_status = 'none'; trades += 1
            elif position_status == 'short' and long_signal:
                pnl = _calculate_pnl(entry_price, current_price, position_margin, leverage, 'short'); cash = (position_margin + pnl) * (1 - fee_rate); cash = min(cash, MAX_ASSET_VALUE); position_status = 'none'; trades += 1
            
            if position_status == 'none' and cash > 0:
                signal = 'none'
                if long_signal: signal = 'long'
                elif short_signal: signal = 'short'
                if signal != 'none':
                    position_margin, entry_price, position_status, trades = cash, current_price, signal, trades + 1
                    if stop_loss_pct != 0:
                        if signal == 'long': stop_loss_price = entry_price * (1 + stop_loss_pct / 100); take_profit_price = entry_price * (1 + take_profit_pct / 100)
                        else: stop_loss_price = entry_price * (1 - stop_loss_pct / 100); take_profit_price = entry_price * (1 - take_profit_pct / 100)
        
        # --- 4-3. 현재 자산 평가 ---
        current_asset = _calculate_asset(entry_price, current_price, position_margin, leverage, position_status, cash)
        asset_history.append(current_asset)

    # 5. 최종 결과 계산
    final_asset = asset_history[-1] if asset_history else initial_cash; total_return = (final_asset / initial_cash - 1) * 100
    asset_series = pd.Series(asset_history); mdd = (1 - (asset_series / asset_series.cummax())).max() * 100
    return {'total_return_pct': total_return, 'mdd_pct': -mdd, 'total_trades': trades, 'total_liquidations': liquidations, 'asset_history': asset_history}


def macd_crossover_dual_filter(params, df, initial_cash, fee_rate, leverage):
    """
    MACD Crossover 전략에 장기 국면 필터와 단기 추세 필터를 모두 적용.
    1. 장기 국면 필터 (regime_filter): 하락장에서는 모든 매매 중단.
    2. 단기 추세 필터 (trend_filter): 상승장 내에서, 단기 추세와 맞는 방향의 거래만 실행.
    """
    # 1. 파라미터 설정
    fast_ma_len = params.get('fast_ma', 21)
    slow_ma_len = params.get('slow_ma', 55)
    signal_len = params.get('signal_ma', 8)
    
    # 두 종류의 필터 파라미터
    trend_ma_len = params.get('trend_ma_len', 50) # 단기 추세 필터
    regime_filter_period = params.get('regime_filter_period', 4800) # 장기 국면 필터
    
    stop_loss_pct = params.get('stop_loss_pct', 0)
    take_profit_pct = params.get('take_profit_pct', 0)
    leverage = max(1, leverage)

    # 2. 지표 계산
    ema_fast = df['Close'].ewm(span=fast_ma_len, adjust=False).mean()
    ema_slow = df['Close'].ewm(span=slow_ma_len, adjust=False).mean()
    df['MACD'] = ema_fast - ema_slow
    df['Signal'] = df['MACD'].ewm(span=signal_len, adjust=False).mean()
    
    df['Trend_MA'] = df['Close'].ewm(span=trend_ma_len, adjust=False).mean()
    df['MA_regime'] = df['Close'].rolling(window=regime_filter_period).mean()
    
    df.dropna(inplace=True)
    if df.empty: return {'total_return_pct': 0, 'mdd_pct': 0, 'total_trades': 0, 'total_liquidations': 0, 'asset_history': []}

    # 3. 백테스팅 변수 초기화
    cash = initial_cash
    asset_history = [initial_cash]
    trades, liquidations, position_status, entry_price, position_margin, stop_loss_price, take_profit_price = 0, 0, 'none', 0, 0, 0, 0

    # 4. 백테스팅 루프
    for i in range(1, len(df)):
        current_price = df['Close'].iloc[i]
        
        # --- 4-1. 위험 관리 (손절/익절/강제청산) ---
        if position_status != 'none':
            exit_price, pnl, is_liquidated = 0, 0, False
            if position_status == 'long':
                liquidation_price = entry_price * (1 - 1/leverage) if leverage > 1 else 0
                if df['Low'].iloc[i] <= liquidation_price and leverage > 1: exit_price, liquidations, is_liquidated = liquidation_price, liquidations + 1, True
                elif stop_loss_pct != 0 and df['Low'].iloc[i] <= stop_loss_price: exit_price = stop_loss_price
                elif take_profit_pct != 0 and df['High'].iloc[i] >= take_profit_price: exit_price = take_profit_price
                if exit_price > 0: pnl = _calculate_pnl(entry_price, exit_price, position_margin, leverage, 'long')
            elif position_status == 'short':
                liquidation_price = entry_price * (1 + 1/leverage) if leverage > 1 else float('inf')
                if df['High'].iloc[i] >= liquidation_price and leverage > 1: exit_price, liquidations, is_liquidated = liquidation_price, liquidations + 1, True
                elif stop_loss_pct != 0 and df['High'].iloc[i] >= stop_loss_price: exit_price = stop_loss_price
                elif take_profit_pct != 0 and df['Low'].iloc[i] <= take_profit_price: exit_price = take_profit_price
                if exit_price > 0: pnl = _calculate_pnl(entry_price, exit_price, position_margin, leverage, 'short')
            if exit_price > 0:
                cash = 0 if is_liquidated else (position_margin + pnl) * (1 - fee_rate); cash = min(cash, MAX_ASSET_VALUE); position_status = 'none'

        # ⭐ --- 4-2. 시장 국면 필터 (마스터 스위치) ---
        is_bull_market = current_price > df['MA_regime'].iloc[i]

        if not is_bull_market:
            # 하락장이면, 보유 포지션 즉시 청산 후 이번 턴 종료
            if position_status != 'none':
                pnl = _calculate_pnl(entry_price, current_price, position_margin, leverage, position_status)
                cash = (position_margin + pnl) * (1 - fee_rate); cash = min(cash, MAX_ASSET_VALUE)
                position_status = 'none'; trades += 1
        else:
            # ⭐ --- 4-3. 상승장일 때만 매매 로직 실행 ---
            long_signal = df['MACD'].iloc[i-1] < df['Signal'].iloc[i-1] and df['MACD'].iloc[i] > df['Signal'].iloc[i]
            short_signal = df['MACD'].iloc[i-1] > df['Signal'].iloc[i-1] and df['MACD'].iloc[i] < df['Signal'].iloc[i]
            
            # 단기 추세 필터 적용
            is_uptrend = current_price > df['Trend_MA'].iloc[i]
            is_downtrend = current_price < df['Trend_MA'].iloc[i]
            
            final_long_signal = long_signal and is_uptrend
            final_short_signal = short_signal and is_downtrend

            # 포지션 청산 (반대 신호)
            if position_status == 'long' and final_short_signal:
                pnl = _calculate_pnl(entry_price, current_price, position_margin, leverage, 'long'); cash = (position_margin + pnl) * (1 - fee_rate); cash = min(cash, MAX_ASSET_VALUE); position_status = 'none'; trades += 1
            elif position_status == 'short' and final_long_signal:
                pnl = _calculate_pnl(entry_price, current_price, position_margin, leverage, 'short'); cash = (position_margin + pnl) * (1 - fee_rate); cash = min(cash, MAX_ASSET_VALUE); position_status = 'none'; trades += 1
            
            # 신규 포지션 진입
            if position_status == 'none' and cash > 0:
                signal = 'none'
                if final_long_signal: signal = 'long'
                elif final_short_signal: signal = 'short'
                if signal != 'none':
                    position_margin, entry_price, position_status, trades = cash, current_price, signal, trades + 1
                    if stop_loss_pct != 0:
                        if signal == 'long': stop_loss_price = entry_price * (1 + stop_loss_pct / 100); take_profit_price = entry_price * (1 + take_profit_pct / 100)
                        else: stop_loss_price = entry_price * (1 - stop_loss_pct / 100); take_profit_price = entry_price * (1 - take_profit_pct / 100)
        
        # --- 4-4. 현재 자산 평가 ---
        current_asset = _calculate_asset(entry_price, current_price, position_margin, leverage, position_status, cash)
        asset_history.append(current_asset)

    # 5. 최종 결과 계산
    final_asset = asset_history[-1] if asset_history else initial_cash; total_return = (final_asset / initial_cash - 1) * 100
    asset_series = pd.Series(asset_history); mdd = (1 - (asset_series / asset_series.cummax())).max() * 100
    return {'total_return_pct': total_return, 'mdd_pct': -mdd, 'total_trades': trades, 'total_liquidations': liquidations, 'asset_history': asset_history}

def macd_crossover_advanced_filter(params, df, initial_cash, fee_rate, leverage):
    """
    MACD Crossover에 ADX 횡보장 필터와 장기 추세에 따른 순/역추세 전환 로직을 적용 (수정 버전).
    """
    # 1. 파라미터 설정
    fast_ma_len = params.get('fast_ma', 21)
    slow_ma_len = params.get('slow_ma', 55)
    signal_len = params.get('signal_ma', 8)
    
    adx_period = params.get('adx_period', 14)
    adx_threshold = params.get('adx_threshold', 20)
    
    regime_filter_period = params.get('regime_filter_period', 4800)
    
    stop_loss_pct = params.get('stop_loss_pct', 0)
    take_profit_pct = params.get('take_profit_pct', 0)
    leverage = max(1, leverage)

    # 2. 지표 계산
    ema_fast = df['Close'].ewm(span=fast_ma_len, adjust=False).mean()
    ema_slow = df['Close'].ewm(span=slow_ma_len, adjust=False).mean()
    df['MACD'] = ema_fast - ema_slow
    df['Signal'] = df['MACD'].ewm(span=signal_len, adjust=False).mean()
    
    df = calculate_adx(df, period=adx_period)
    df['MA_regime'] = df['Close'].rolling(window=regime_filter_period).mean()
    
    df.dropna(inplace=True)
    if df.empty: return {'total_return_pct': 0, 'mdd_pct': 0, 'total_trades': 0, 'total_liquidations': 0, 'asset_history': []}

    # 3. 백테스팅 변수 초기화
    cash = initial_cash
    asset_history = [initial_cash]
    trades, liquidations, position_status, entry_price, position_margin, stop_loss_price, take_profit_price = 0, 0, 'none', 0, 0, 0, 0

    # 4. 백테스팅 루프
    for i in range(1, len(df)):
        current_price = df['Close'].iloc[i]
        
        # --- 4-1. 위험 관리 (손절/익절/강제청산) ---
        if position_status != 'none':
            exit_price, pnl, is_liquidated = 0, 0, False
            if position_status == 'long':
                liquidation_price = entry_price * (1 - 1/leverage) if leverage > 1 else 0
                if df['Low'].iloc[i] <= liquidation_price and leverage > 1: exit_price, liquidations, is_liquidated = liquidation_price, liquidations + 1, True
                elif stop_loss_pct != 0 and df['Low'].iloc[i] <= stop_loss_price: exit_price = stop_loss_price
                elif take_profit_pct != 0 and df['High'].iloc[i] >= take_profit_price: exit_price = take_profit_price
                if exit_price > 0: pnl = _calculate_pnl(entry_price, exit_price, position_margin, leverage, 'long')
            elif position_status == 'short':
                liquidation_price = entry_price * (1 + 1/leverage) if leverage > 1 else float('inf')
                if df['High'].iloc[i] >= liquidation_price and leverage > 1: exit_price, liquidations, is_liquidated = liquidation_price, liquidations + 1, True
                elif stop_loss_pct != 0 and df['High'].iloc[i] >= stop_loss_price: exit_price = stop_loss_price
                elif take_profit_pct != 0 and df['Low'].iloc[i] <= take_profit_price: exit_price = take_profit_price
                if exit_price > 0: pnl = _calculate_pnl(entry_price, exit_price, position_margin, leverage, 'short')
            if exit_price > 0:
                cash = 0 if is_liquidated else (position_margin + pnl) * (1 - fee_rate); cash = min(cash, MAX_ASSET_VALUE); position_status = 'none'

        # --- 4-2. 시장 국면 필터 ---
        is_trending = df['ADX'].iloc[i] > adx_threshold
        is_bull_market = current_price > df['MA_regime'].iloc[i]

        if not is_trending:
            if position_status != 'none':
                pnl = _calculate_pnl(entry_price, current_price, position_margin, leverage, position_status)
                cash = (position_margin + pnl) * (1 - fee_rate); cash = min(cash, MAX_ASSET_VALUE)
                position_status = 'none'; trades += 1
        else: # 추세장일 때만 매매 로직 실행
            gc = df['MACD'].iloc[i-1] < df['Signal'].iloc[i-1] and df['MACD'].iloc[i] > df['Signal'].iloc[i]
            dc = df['MACD'].iloc[i-1] > df['Signal'].iloc[i-1] and df['MACD'].iloc[i] < df['Signal'].iloc[i]
            
            long_signal, short_signal = False, False

            # ⭐ 로직 수정: 단기 추세 필터 제거하여 신호 발생 가능하게 함
            if is_bull_market: # 상승장: 순추세 매매
                long_signal = gc
                short_signal = dc
            else: # 하락장: 역추세 매매
                long_signal = dc
                short_signal = gc

            # 포지션 청산 (반대 신호)
            if position_status == 'long' and short_signal:
                pnl = _calculate_pnl(entry_price, current_price, position_margin, leverage, 'long'); cash = (position_margin + pnl) * (1 - fee_rate); cash = min(cash, MAX_ASSET_VALUE); position_status = 'none'; trades += 1
            elif position_status == 'short' and long_signal:
                pnl = _calculate_pnl(entry_price, current_price, position_margin, leverage, 'short'); cash = (position_margin + pnl) * (1 - fee_rate); cash = min(cash, MAX_ASSET_VALUE); position_status = 'none'; trades += 1
            
            # 신규 포지션 진입
            if position_status == 'none' and cash > 0:
                signal = 'none'
                if long_signal: signal = 'long'
                elif short_signal: signal = 'short'
                if signal != 'none':
                    position_margin, entry_price, position_status, trades = cash, current_price, signal, trades + 1
                    if stop_loss_pct != 0:
                        if signal == 'long': stop_loss_price = entry_price * (1 + stop_loss_pct / 100); take_profit_price = entry_price * (1 + take_profit_pct / 100)
                        else: stop_loss_price = entry_price * (1 - stop_loss_pct / 100); take_profit_price = entry_price * (1 - take_profit_pct / 100)
        
        # --- 4-4. 현재 자산 평가 ---
        current_asset = _calculate_asset(entry_price, current_price, position_margin, leverage, position_status, cash)
        asset_history.append(current_asset)

    # 5. 최종 결과 계산
    final_asset = asset_history[-1] if asset_history else initial_cash; total_return = (final_asset / initial_cash - 1) * 100
    asset_series = pd.Series(asset_history); mdd = (1 - (asset_series / asset_series.cummax())).max() * 100
    return {'total_return_pct': total_return, 'mdd_pct': -mdd, 'total_trades': trades, 'total_liquidations': liquidations, 'asset_history': asset_history}


def macd_liquidity_tracker_revised_crossover(params, df, initial_cash, fee_rate, leverage):
    # params에서 값을 가져옴
    fast_ma_len=params.get('fast_ma',12)
    slow_ma_len=params.get('slow_ma',26)
    signal_len=params.get('signal_ma',9)
    use_trend_filter=params.get('use_trend_filter',True)
    trend_ma_len=params.get('trend_ma_len',50)
    stop_loss_pct=params.get('stop_loss_pct',0)
    take_profit_pct=params.get('take_profit_pct',0)
    long_trend_len=params.get('long_trend_len',0)
    ema_fast = df['Close'].ewm(span=fast_ma_len, adjust=False).mean(); ema_slow = df['Close'].ewm(span=slow_ma_len, adjust=False).mean(); df['MACD'] = ema_fast - ema_slow; df['Signal'] = df['MACD'].ewm(span=signal_len, adjust=False).mean(); df['Hist'] = df['MACD'] - df['Signal']
    
    # MACD 관련 지표(MACD선, 신호선, 히스토그램)와 단기 추세 필터용 이동평균선(Trend_MA)를 계산
    df['Hist_Color'] = 'none'; is_rising = df['Hist'] > df['Hist'].shift(1); is_above_zero = df['Hist'] > 0
    df.loc[(is_above_zero) & (is_rising), 'Hist_Color'] = 'Bright Blue'; df.loc[(is_above_zero) & (~is_rising), 'Hist_Color'] = 'Dark Blue'; df.loc[(~is_above_zero) & (~is_rising), 'Hist_Color'] = 'Bright Magenta'; df.loc[(~is_above_zero) & (is_rising), 'Hist_Color'] = 'Dark Magenta'
    if use_trend_filter: df['Trend_MA'] = df['Close'].ewm(span=trend_ma_len, adjust=False).mean()
    df['long_trend_len'] = df['Close'].ewm(span=long_trend_len, adjust=False).mean()
    df.dropna(inplace=True)

    # 값이 없는 행 제거, 데이터가 없으면 즉시 함수 종료
    if df.empty: return {'total_return_pct': 0, 'mdd_pct': 0, 'total_trades': 0, 'total_liquidations': 0, 'asset_history': []}

    # 백테스팅 준비(초기값 초기화)
    cash = initial_cash; asset_history = [initial_cash]
    trades, liquidations, position_status, entry_price, position_margin, stop_loss_price, take_profit_price = 0, 0, 'none', 0, 0, 0, 0

    # 핵심 거래 로직
    for i in range(1, len(df)):
        current_price = df['Close'].iloc[i]

        # 현재 포지션에 진입해 있을 경우
        if position_status != 'none':
            exit_price, pnl, is_liquidated = 0, 0, False
            # 롱일 경우 -> 청산/손절/익절 여부 판단
            if position_status == 'long':
                liquidation_price = entry_price * (1 - 1/leverage) if leverage > 1 else 0
                if df['Low'].iloc[i] <= liquidation_price and leverage > 1: exit_price, liquidations, is_liquidated = liquidation_price, liquidations + 1, True
                elif stop_loss_pct != 0 and df['Low'].iloc[i] <= stop_loss_price: exit_price = stop_loss_price
                elif take_profit_pct != 0 and df['High'].iloc[i] >= take_profit_price: exit_price = take_profit_price
                if exit_price > 0: pnl = _calculate_pnl(entry_price, exit_price, position_margin, leverage, 'long')
            # 숏일 경우 -> 청산/손절/익절 여부 판단
            elif position_status == 'short':
                liquidation_price = entry_price * (1 + 1/leverage) if leverage > 1 else float('inf')
                if df['High'].iloc[i] >= liquidation_price and leverage > 1: exit_price, liquidations, is_liquidated = liquidation_price, liquidations + 1, True
                elif stop_loss_pct != 0 and df['High'].iloc[i] >= stop_loss_price: exit_price = stop_loss_price
                elif take_profit_pct != 0 and df['Low'].iloc[i] <= take_profit_price: exit_price = take_profit_price
                if exit_price > 0: pnl = _calculate_pnl(entry_price, exit_price, position_margin, leverage, 'short')
            # 조건에 해당할 경우 포지션 청산
            if exit_price > 0:
                cash = 0 if is_liquidated else (position_margin + pnl) * (1 - fee_rate); cash = min(cash, MAX_ASSET_VALUE); position_status = 'none'
        
        # 롱인지 숏인지 판단
        long_signal, short_signal = False, False

        # 상승장인 경우
        if current_price <= df['long_trend_len'].iloc[i]:
            # 골든크로스(롱) vs 데드크로스(숏)
            long_signal = df['MACD'].iloc[i-1] < df['Signal'].iloc[i-1] and df['MACD'].iloc[i] > df['Signal'].iloc[i]; short_signal = df['MACD'].iloc[i-1] > df['Signal'].iloc[i-1] and df['MACD'].iloc[i] < df['Signal'].iloc[i]
            # 단기 추세선을 사용하여 롱/숏 신호를 한 번 거름.
            if use_trend_filter:
                is_uptrend = current_price > df['Trend_MA'].iloc[i]; is_downtrend = current_price < df['Trend_MA'].iloc[i]
                long_signal = long_signal and is_uptrend; short_signal = short_signal and is_downtrend
            if position_status == 'long' and short_signal:
                pnl = _calculate_pnl(entry_price, current_price, position_margin, leverage, 'long'); cash = (position_margin + pnl) * (1 - fee_rate); cash = min(cash, MAX_ASSET_VALUE); position_status = 'none'; trades += 1
            elif position_status == 'short' and long_signal:
                pnl = _calculate_pnl(entry_price, current_price, position_margin, leverage, 'short'); cash = (position_margin + pnl) * (1 - fee_rate); cash = min(cash, MAX_ASSET_VALUE); position_status = 'none'; trades += 1

        # 포지션 진입
        if position_status == 'none' and cash > 0:
            signal = 'none'
            if long_signal: signal = 'long'
            elif short_signal: signal = 'short'
            if signal != 'none':
                position_margin, entry_price, position_status, trades = cash, current_price, signal, trades + 1
                if stop_loss_pct != 0:
                    if signal == 'long': stop_loss_price = entry_price * (1 + stop_loss_pct / 100); take_profit_price = entry_price * (1 + take_profit_pct / 100)
                    else: stop_loss_price = entry_price * (1 - stop_loss_pct / 100); take_profit_price = entry_price * (1 - take_profit_pct / 100)
        
        # 자산 기록
        current_asset = _calculate_asset(entry_price, current_price, position_margin, leverage, position_status, cash)
        asset_history.append(current_asset)
    
    # 최종 결과 반환
    final_asset = asset_history[-1] if asset_history else initial_cash; total_return = (final_asset / initial_cash - 1) * 100
    asset_series = pd.Series(asset_history); mdd = (1 - (asset_series / asset_series.cummax())).max() * 100
    return {'total_return_pct': total_return, 'mdd_pct': -mdd, 'total_trades': trades, 'total_liquidations': liquidations, 'asset_history': asset_history}

def simple_ma_strategy(params, df, initial_cash, fee_rate, leverage=1):
    """
    단순 이동평균선 돌파 전략 (현물)
    - 가격이 지정된 기간의 이동평균선을 상향 돌파하면 매수
    - 가격이 지정된 기간의 이동평균선을 하향 돌파하면 매도
    """
    # 1. 파라미터 설정
    ma_period = params.get('ma_period', 50)

    # 2. 지표 계산
    df['MA'] = df['Close'].rolling(window=ma_period).mean()
    df.dropna(inplace=True)

    if df.empty:
        return {'total_return_pct': 0, 'mdd_pct': 0, 'total_trades': 0, 'asset_history': []}

    # 3. 백테스팅 준비
    cash = initial_cash
    coins = 0
    trades = 0
    asset_history = [initial_cash]

    # 4. 핵심 거래 로직
    for i in range(1, len(df)):
        current_price = df['Close'].iloc[i]
        
        # 매수 신호: 가격이 이동평균선을 상향 돌파 (골든 크로스)
        is_buy_signal = df['Close'].iloc[i-1] <= df['MA'].iloc[i-1] and df['Close'].iloc[i] > df['MA'].iloc[i]
        
        # 매도 신호: 가격이 이동평균선을 하향 돌파 (데드 크로스)
        is_sell_signal = df['Close'].iloc[i-1] >= df['MA'].iloc[i-1] and df['Close'].iloc[i] < df['MA'].iloc[i]

        if is_buy_signal and cash > 0:
            # 보유 현금으로 모두 매수
            coins = (cash / current_price) * (1 - fee_rate)
            cash = 0
            trades += 1
        elif is_sell_signal and coins > 0:
            # 보유 코인을 모두 매도
            cash = (coins * current_price) * (1 - fee_rate)
            coins = 0
            trades += 1
        
        # 현재 자산 기록
        current_asset = cash + coins * current_price
        asset_history.append(current_asset)

    # 5. 최종 결과 계산 및 반환
    final_asset = asset_history[-1]
    total_return = (final_asset / initial_cash - 1) * 100
    asset_series = pd.Series(asset_history)
    mdd = (1 - (asset_series / asset_series.cummax())).max() * 100
    
    return {
        'total_return_pct': total_return,
        'mdd_pct': -mdd,
        'total_trades': trades,
        'asset_history': asset_history
    }


def macd_final_strategy(params, df, initial_cash, fee_rate, leverage):
    """
    고정된 파라미터와 장기 추세 필터를 사용하는 최종 MACD Crossover 전략
    """
    # 1. 파라미터 설정 (대부분 고정값 사용)
    fast_ma_len = 12
    slow_ma_len = 26
    signal_len = 9
    trend_ma_len = 100
    stop_loss_pct = -2
    take_profit_pct = 10
    
    # 장기 추세 필터만 파라미터로 받음 (시간봉에 따라 조절해야 하므로)
    regime_filter_period = params.get('regime_filter_period', 4800) # 1h 기준 200일
    leverage = max(1, leverage)

    # 2. 지표 계산
    ema_fast = df['Close'].ewm(span=fast_ma_len, adjust=False).mean()
    ema_slow = df['Close'].ewm(span=slow_ma_len, adjust=False).mean()
    df['MACD'] = ema_fast - ema_slow
    df['Signal'] = df['MACD'].ewm(span=signal_len, adjust=False).mean()
    
    df['Trend_MA'] = df['Close'].ewm(span=trend_ma_len, adjust=False).mean()
    df['MA_regime'] = df['Close'].rolling(window=regime_filter_period).mean()
    
    df.dropna(inplace=True)
    if df.empty: return {'total_return_pct': 0, 'mdd_pct': 0, 'total_trades': 0, 'total_liquidations': 0, 'asset_history': []}

    # 3. 백테스팅 변수 초기화
    cash = initial_cash
    asset_history = [initial_cash]
    trades, liquidations, position_status, entry_price, position_margin, stop_loss_price, take_profit_price = 0, 0, 'none', 0, 0, 0, 0

    # 4. 백테스팅 루프
    for i in range(1, len(df)):
        current_price = df['Close'].iloc[i]
        
        # --- 4-1. 위험 관리 (손절/익절/강제청산) ---
        if position_status != 'none':
            exit_price, pnl, is_liquidated = 0, 0, False
            if position_status == 'long':
                liquidation_price = entry_price * (1 - 1/leverage) if leverage > 1 else 0
                if leverage > 1 and df['Low'].iloc[i] <= liquidation_price: exit_price, liquidations, is_liquidated = liquidation_price, liquidations + 1, True
                elif stop_loss_pct != 0 and df['Low'].iloc[i] <= stop_loss_price: exit_price = stop_loss_price
                elif take_profit_pct != 0 and df['High'].iloc[i] >= take_profit_price: exit_price = take_profit_price
                if exit_price > 0: pnl = _calculate_pnl(entry_price, exit_price, position_margin, leverage, 'long')
            elif position_status == 'short':
                liquidation_price = entry_price * (1 + 1/leverage) if leverage > 1 else float('inf')
                if leverage > 1 and df['High'].iloc[i] >= liquidation_price: exit_price, liquidations, is_liquidated = liquidation_price, liquidations + 1, True
                elif stop_loss_pct != 0 and df['High'].iloc[i] >= stop_loss_price: exit_price = stop_loss_price
                elif take_profit_pct != 0 and df['Low'].iloc[i] <= take_profit_price: exit_price = take_profit_price
                if exit_price > 0: pnl = _calculate_pnl(entry_price, exit_price, position_margin, leverage, 'short')
            if exit_price > 0:
                cash = 0 if is_liquidated else (position_margin + pnl) * (1 - fee_rate); cash = min(cash, MAX_ASSET_VALUE); position_status = 'none'

        # --- 4-2. 시장 국면 필터 (마스터 스위치) ---
        is_bull_market = current_price > df['MA_regime'].iloc[i]

        # --- 4-3. 상승장일 때만 매매 로직 실행 ---
        long_signal = df['MACD'].iloc[i-1] < df['Signal'].iloc[i-1] and df['MACD'].iloc[i] > df['Signal'].iloc[i]
        short_signal = df['MACD'].iloc[i-1] > df['Signal'].iloc[i-1] and df['MACD'].iloc[i] < df['Signal'].iloc[i]

        if not is_bull_market:
            temp = long_signal
            long_signal = short_signal
            short_signal = temp
        
        is_uptrend = current_price > df['Trend_MA'].iloc[i]
        long_signal = long_signal and is_uptrend
        # 숏 포지션은 진입하지 않으므로 short_signal은 청산 용도로만 사용
        
        if position_status == 'long' and short_signal:
            pnl = _calculate_pnl(entry_price, current_price, position_margin, leverage, 'long'); cash = (position_margin + pnl) * (1 - fee_rate); cash = min(cash, MAX_ASSET_VALUE); position_status = 'none'; trades += 1
        
        if position_status == 'none' and cash > 0 and long_signal:
            signal = 'long'
            position_margin, entry_price, position_status, trades = cash, current_price, signal, trades + 1
            if stop_loss_pct != 0:
                stop_loss_price = entry_price * (1 + stop_loss_pct / 100)
                take_profit_price = entry_price * (1 + take_profit_pct / 100)

        
        # --- 4-4. 현재 자산 평가 ---
        current_asset = _calculate_asset(entry_price, current_price, position_margin, leverage, position_status, cash)
        asset_history.append(current_asset)

    # 5. 최종 결과 계산
    final_asset = asset_history[-1] if asset_history else initial_cash; total_return = (final_asset / initial_cash - 1) * 100
    asset_series = pd.Series(asset_history); mdd = (1 - (asset_series / asset_series.cummax())).max() * 100
    return {'total_return_pct': total_return, 'mdd_pct': -mdd, 'total_trades': trades, 'total_liquidations': liquidations, 'asset_history': asset_history}

def momentum_spike_scalping_long_short(params, df, initial_cash, fee_rate, leverage):
    """
    이전 분봉의 급등/급락을 포착하여 롱 또는 숏 포지션에 진입하는 스캘핑 전략 (레버리지)
    - 롱 진입: 이전 캔들 +n% 이상 상승 시
    - 숏 진입: 이전 캔들 -n% 이상 하락 시
    - 익절/손절: 진입 후 +/- n%
    """
    # 1. 파라미터 설정 (타입 강제 변환으로 안정성 확보)
    try:
        spike_pct = float(params.get('spike_pct', 3.0))
        take_profit_pct = float(params.get('take_profit_pct', 1.0))
        stop_loss_pct = float(params.get('stop_loss_pct', -1.0))
    except (ValueError, TypeError):
        spike_pct, take_profit_pct, stop_loss_pct = 3.0, 1.0, -1.0
    
    # 숏 진입을 위한 하락률 기준
    fall_pct = -spike_pct

    # 2. 지표 계산
    df['pct_change'] = (df['Close'] / df['Open'] - 1) * 100
    df.dropna(inplace=True)

    if df.empty:
        return {'total_return_pct': 0, 'mdd_pct': 0, 'total_trades': 0, 'total_liquidations': 0, 'asset_history': []}

    # 3. 백테스팅 준비
    cash = initial_cash
    asset_history = [initial_cash]
    trades, liquidations, position_status, entry_price, position_margin = 0, 0, 'none', 0, 0
    stop_loss_price, take_profit_price, liquidation_price = 0, 0, 0

    # 4. 핵심 거래 로직
    for i in range(1, len(df)):
        current_price = df['Close'].iloc[i]

        # 4-1. 포지션이 있을 경우: 위험 관리
        if position_status != 'none':
            exit_price, is_liquidated = 0, False
            
            # 롱 포지션 청산 조건
            if position_status == 'long':
                if leverage > 1 and df['Low'].iloc[i] <= liquidation_price:
                    exit_price, liquidations, is_liquidated = liquidation_price, liquidations + 1, True
                elif df['Low'].iloc[i] <= stop_loss_price:
                    exit_price = stop_loss_price
                elif df['High'].iloc[i] >= take_profit_price:
                    exit_price = take_profit_price
            
            # 숏 포지션 청산 조건
            elif position_status == 'short':
                if leverage > 1 and df['High'].iloc[i] >= liquidation_price:
                    exit_price, liquidations, is_liquidated = liquidation_price, liquidations + 1, True
                elif df['High'].iloc[i] >= stop_loss_price: # 숏 포지션의 손절은 가격 상승
                    exit_price = stop_loss_price
                elif df['Low'].iloc[i] <= take_profit_price: # 숏 포지션의 익절은 가격 하락
                    exit_price = take_profit_price

            if exit_price > 0:
                pnl = _calculate_pnl(entry_price, exit_price, position_margin, leverage, position_status)
                cash = 0 if is_liquidated else (position_margin + pnl) * (1 - fee_rate)
                cash = min(cash, MAX_ASSET_VALUE)
                position_status = 'none'
                trades += 1

        # 4-2. 포지션이 없을 경우: 진입 신호 확인
        if position_status == 'none' and cash > 0:
            signal = 'none'
            # 롱 진입 신호 확인
            if df['pct_change'].iloc[i-1] >= spike_pct:
                signal = 'long'
            # 숏 진입 신호 확인
            elif df['pct_change'].iloc[i-1] <= fall_pct:
                signal = 'short'

            if signal != 'none':
                entry_price = df['Open'].iloc[i]
                position_margin = cash
                position_status = signal
                trades += 1
                
                if signal == 'long':
                    take_profit_price = entry_price * (1 + take_profit_pct / 100)
                    stop_loss_price = entry_price * (1 + stop_loss_pct / 100)
                    if leverage > 1: liquidation_price = entry_price * (1 - 1/leverage)
                
                elif signal == 'short':
                    take_profit_price = entry_price * (1 - take_profit_pct / 100) # 숏 익절
                    stop_loss_price = entry_price * (1 - stop_loss_pct / 100) # 숏 손절
                    if leverage > 1: liquidation_price = entry_price * (1 + 1/leverage)
        
        # 4-3. 현재 자산 평가 및 기록
        current_asset = _calculate_asset(entry_price, current_price, position_margin, leverage, position_status, cash)
        asset_history.append(current_asset)

    # 5. 최종 결과 계산 및 반환
    final_asset = asset_history[-1] if asset_history else initial_cash
    total_return = (final_asset / initial_cash - 1) * 100
    asset_series = pd.Series(asset_history)
    mdd = (1 - (asset_series / asset_series.cummax())).max() * 100 if not asset_series.empty else 0
    
    return {
        'total_return_pct': total_return,
        'mdd_pct': -mdd,
        'total_trades': trades,
        'total_liquidations': liquidations,
        'asset_history': asset_history
    }



def momentum_spike_scalping_long_short_inverse(params, df, initial_cash, fee_rate, leverage):
    """
    이전 분봉의 급등/급락을 포착하여 롱 또는 숏 포지션에 진입하는 스캘핑 전략 (레버리지)
    - 롱 진입: 이전 캔들 +n% 이상 상승 시
    - 숏 진입: 이전 캔들 -n% 이상 하락 시
    - 익절/손절: 진입 후 +/- n%
    """
    # 1. 파라미터 설정 (타입 강제 변환으로 안정성 확보)
    try:
        spike_pct = float(params.get('spike_pct', 3.0))
        take_profit_pct = float(params.get('take_profit_pct', 1.0))
        stop_loss_pct = float(params.get('stop_loss_pct', -1.0))
    except (ValueError, TypeError):
        spike_pct, take_profit_pct, stop_loss_pct = 3.0, 1.0, -1.0
    
    # 숏 진입을 위한 하락률 기준
    fall_pct = -spike_pct

    # 2. 지표 계산
    df['pct_change'] = (df['Close'] / df['Open'] - 1) * 100
    df.dropna(inplace=True)

    if df.empty:
        return {'total_return_pct': 0, 'mdd_pct': 0, 'total_trades': 0, 'total_liquidations': 0, 'asset_history': []}

    # 3. 백테스팅 준비
    cash = initial_cash
    asset_history = [initial_cash]
    trades, liquidations, position_status, entry_price, position_margin = 0, 0, 'none', 0, 0
    stop_loss_price, take_profit_price, liquidation_price = 0, 0, 0

    # 4. 핵심 거래 로직
    for i in range(1, len(df)):
        current_price = df['Close'].iloc[i]

        # 4-1. 포지션이 있을 경우: 위험 관리
        if position_status != 'none':
            exit_price, is_liquidated = 0, False
            
            # 롱 포지션 청산 조건
            if position_status == 'long':
                if leverage > 1 and df['Low'].iloc[i] <= liquidation_price:
                    exit_price, liquidations, is_liquidated = liquidation_price, liquidations + 1, True
                elif df['Low'].iloc[i] <= stop_loss_price:
                    exit_price = stop_loss_price
                elif df['High'].iloc[i] >= take_profit_price:
                    exit_price = take_profit_price
            
            # 숏 포지션 청산 조건
            elif position_status == 'short':
                if leverage > 1 and df['High'].iloc[i] >= liquidation_price:
                    exit_price, liquidations, is_liquidated = liquidation_price, liquidations + 1, True
                elif df['High'].iloc[i] >= stop_loss_price: # 숏 포지션의 손절은 가격 상승
                    exit_price = stop_loss_price
                elif df['Low'].iloc[i] <= take_profit_price: # 숏 포지션의 익절은 가격 하락
                    exit_price = take_profit_price

            if exit_price > 0:
                pnl = _calculate_pnl(entry_price, exit_price, position_margin, leverage, position_status)
                cash = 0 if is_liquidated else (position_margin + pnl) * (1 - fee_rate)
                cash = min(cash, MAX_ASSET_VALUE)
                position_status = 'none'
                trades += 1

        # 4-2. 포지션이 없을 경우: 진입 신호 확인
        if position_status == 'none' and cash > 0:
            signal = 'none'
            # 롱 진입 신호 확인
            if df['pct_change'].iloc[i-1] >= spike_pct:
                signal = 'short'
            # 숏 진입 신호 확인
            elif df['pct_change'].iloc[i-1] <= fall_pct:
                signal = 'long'

            if signal != 'none':
                entry_price = df['Open'].iloc[i]
                position_margin = cash
                position_status = signal
                trades += 1
                
                if signal == 'long':
                    take_profit_price = entry_price * (1 + take_profit_pct / 100)
                    stop_loss_price = entry_price * (1 + stop_loss_pct / 100)
                    if leverage > 1: liquidation_price = entry_price * (1 - 1/leverage)
                
                elif signal == 'short':
                    take_profit_price = entry_price * (1 - take_profit_pct / 100) # 숏 익절
                    stop_loss_price = entry_price * (1 - stop_loss_pct / 100) # 숏 손절
                    if leverage > 1: liquidation_price = entry_price * (1 + 1/leverage)
        
        # 4-3. 현재 자산 평가 및 기록
        current_asset = _calculate_asset(entry_price, current_price, position_margin, leverage, position_status, cash)
        asset_history.append(current_asset)

    # 5. 최종 결과 계산 및 반환
    final_asset = asset_history[-1] if asset_history else initial_cash
    total_return = (final_asset / initial_cash - 1) * 100
    asset_series = pd.Series(asset_history)
    mdd = (1 - (asset_series / asset_series.cummax())).max() * 100 if not asset_series.empty else 0
    
    return {
        'total_return_pct': total_return,
        'mdd_pct': -mdd,
        'total_trades': trades,
        'total_liquidations': liquidations,
        'asset_history': asset_history
    }

def momentum_spike_scalping_long_short_half_capital(params, df, initial_cash, fee_rate, leverage):
    """
    급등/급락 스캘핑 전략에 '자산의 50%만 투자'하는 자본 관리 규칙을 추가한 버전
    """
    # 1. 파라미터 설정
    try:
        spike_pct = float(params.get('spike_pct', 3.0))
        take_profit_pct = float(params.get('take_profit_pct', 1.0))
        stop_loss_pct = float(params.get('stop_loss_pct', -1.0))
    except (ValueError, TypeError):
        spike_pct, take_profit_pct, stop_loss_pct = 3.0, 1.0, -1.0
    fall_pct = -spike_pct

    # 2. 지표 계산
    df['pct_change'] = (df['Close'] / df['Open'] - 1) * 100
    df.dropna(inplace=True)
    if df.empty: return {'total_return_pct': 0, 'mdd_pct': 0, 'total_trades': 0, 'total_liquidations': 0, 'asset_history': []}

    # 3. 백테스팅 준비
    cash = initial_cash
    asset_history = [initial_cash]
    trades, liquidations, position_status, entry_price, position_margin = 0, 0, 'none', 0, 0
    stop_loss_price, take_profit_price, liquidation_price = 0, 0, 0

    # 4. 핵심 거래 로직
    for i in range(1, len(df)):
        current_price = df['Close'].iloc[i]

        # --- 4-1. 포지션이 있을 경우: 위험 관리 ---
        if position_status != 'none':
            exit_price, is_liquidated = 0, False
            if position_status == 'long':
                if leverage > 1 and df['Low'].iloc[i] <= liquidation_price: exit_price, liquidations, is_liquidated = liquidation_price, liquidations + 1, True
                elif df['Low'].iloc[i] <= stop_loss_price: exit_price = stop_loss_price
                elif df['High'].iloc[i] >= take_profit_price: exit_price = take_profit_price
            elif position_status == 'short':
                if leverage > 1 and df['High'].iloc[i] >= liquidation_price: exit_price, liquidations, is_liquidated = liquidation_price, liquidations + 1, True
                elif df['High'].iloc[i] >= stop_loss_price: exit_price = stop_loss_price
                elif df['Low'].iloc[i] <= take_profit_price: exit_price = take_profit_price

            if exit_price > 0:
                pnl = _calculate_pnl(entry_price, exit_price, position_margin, leverage, position_status)
                # ⭐ 포지션 종료 시, 남겨둔 현금(cash)에 포지션 결과(position_margin + pnl)를 더함
                # 청산 시에는 position_margin이 0이 되므로 남은 현금만 갖게 됨
                if not is_liquidated:
                    cash += (position_margin + pnl) * (1 - fee_rate)
                
                cash = min(cash, MAX_ASSET_VALUE)
                position_status, position_margin, trades = 'none', 0, trades + 1

        # --- 4-2. 포지션이 없을 경우: 진입 신호 확인 ---
        if position_status == 'none' and cash > 0:
            signal = 'none'
            if df['pct_change'].iloc[i-1] >= spike_pct: signal = 'long'
            elif df['pct_change'].iloc[i-1] <= fall_pct: signal = 'short'

            if signal != 'none':
                # ⭐ 진입 시, 현재 현금(cash)의 50%만 포지션 증거금(position_margin)으로 사용
                position_margin = cash * 0.5
                cash -= position_margin # 남은 50%는 현금으로 보유
                
                entry_price, position_status, trades = df['Open'].iloc[i], signal, trades + 1
                
                if signal == 'long':
                    take_profit_price = entry_price * (1 + take_profit_pct / 100)
                    stop_loss_price = entry_price * (1 + stop_loss_pct / 100)
                    if leverage > 1: liquidation_price = entry_price * (1 - 1/leverage)
                elif signal == 'short':
                    take_profit_price = entry_price * (1 - take_profit_pct / 100)
                    stop_loss_price = entry_price * (1 - stop_loss_pct / 100)
                    if leverage > 1: liquidation_price = entry_price * (1 + 1/leverage)
        
        # --- 4-3. 현재 자산 평가 및 기록 ---
        current_asset = cash
        if position_status != 'none':
            # ⭐ 현재 자산 = 보유 현금 + (포지션의 현재 가치)
            current_asset += _calculate_asset(entry_price, current_price, position_margin, leverage, position_status, 0)
        
        asset_history.append(current_asset)

    # 5. 최종 결과 계산 및 반환
    final_asset = asset_history[-1] if asset_history else initial_cash
    total_return = (final_asset / initial_cash - 1) * 100
    asset_series = pd.Series(asset_history)
    mdd = (1 - (asset_series / asset_series.cummax())).max() * 100 if not asset_series.empty else 0
    
    return {
        'total_return_pct': total_return,
        'mdd_pct': -mdd,
        'total_trades': trades,
        'total_liquidations': liquidations,
        'asset_history': asset_history
    }

def momentum_spike_scalping_long_short_realistic(params, df, initial_cash, fee_rate, leverage):
    """
    급등/급락 스캘핑(50% 자본, 최소 주문량) 전략에 현실적인 레버리지 수수료를 적용한 최종 버전
    """
    # 1. 파라미터 설정
    try:
        spike_pct = float(params.get('spike_pct', 3.0))
        take_profit_pct = float(params.get('take_profit_pct', 1.0))
        stop_loss_pct = float(params.get('stop_loss_pct', -1.0))
        min_order_size_btc = float(params.get('min_order_size_btc', 0.001))
    except (ValueError, TypeError):
        spike_pct, take_profit_pct, stop_loss_pct = 3.0, 1.0, -1.0
        min_order_size_btc = 0.001
    fall_pct = -spike_pct

    # 2. 지표 계산
    df['pct_change'] = (df['Close'] / df['Open'] - 1) * 100
    df.dropna(inplace=True)
    if df.empty: return {'total_return_pct': 0, 'mdd_pct': 0, 'total_trades': 0, 'total_liquidations': 0, 'asset_history': []}

    # 3. 백테스팅 준비
    cash = initial_cash
    asset_history = [initial_cash]
    trades, liquidations, position_status, entry_price, position_margin = 0, 0, 'none', 0, 0
    stop_loss_price, take_profit_price, liquidation_price = 0, 0, 0

    # 4. 핵심 거래 로직
    for i in range(1, len(df)):
        current_price = df['Close'].iloc[i]

        # --- 4-1. 위험 관리 (포지션 종료) ---
        if position_status != 'none':
            exit_price, is_liquidated = 0, False
            if position_status == 'long':
                if leverage > 1 and df['Low'].iloc[i] <= liquidation_price: exit_price, liquidations, is_liquidated = liquidation_price, liquidations + 1, True
                elif df['Low'].iloc[i] <= stop_loss_price: exit_price = stop_loss_price
                elif df['High'].iloc[i] >= take_profit_price: exit_price = take_profit_price
            elif position_status == 'short':
                if leverage > 1 and df['High'].iloc[i] >= liquidation_price: exit_price, liquidations, is_liquidated = liquidation_price, liquidations + 1, True
                elif df['High'].iloc[i] >= stop_loss_price: exit_price = stop_loss_price
                elif df['Low'].iloc[i] <= take_profit_price: exit_price = take_profit_price
            
            if exit_price > 0:
                pnl = _calculate_pnl(entry_price, exit_price, position_margin, leverage, position_status)
                
                # ⭐ --- 현실적인 레버리지 수수료 계산 로직 ---
                position_size = position_margin * leverage
                # 진입과 청산, 두 번의 거래에 대한 수수료를 한 번에 계산
                fee = position_size * fee_rate * 2 

                if not is_liquidated:
                    # 남겨둔 현금(cash)에 포지션 결과(증거금 + 손익 - 수수료)를 더함
                    cash += (position_margin + pnl) - fee
                # 청산 시에는 증거금을 모두 잃으므로, 남겨둔 현금(cash)만 남게 됨 (아무것도 더하지 않음)
                
                cash = min(cash, MAX_ASSET_VALUE)
                position_status, position_margin, trades = 'none', 0, trades + 1

        # --- 4-2. 포지션이 없을 경우: 진입 신호 확인 ---
        if position_status == 'none' and cash > 0:
            signal, entry_price_candidate = 'none', df['Open'].iloc[i]
            if df['pct_change'].iloc[i-1] >= spike_pct: signal = 'long'
            elif df['pct_change'].iloc[i-1] <= fall_pct: signal = 'short'

            if signal != 'none' and entry_price_candidate > 0:
                potential_margin = cash * 0.5
                potential_position_size_btc = (potential_margin * leverage) / entry_price_candidate
                
                if potential_position_size_btc >= min_order_size_btc:
                    position_margin = potential_margin
                    cash -= position_margin
                    entry_price, position_status, trades = entry_price_candidate, signal, trades + 1
                    
                    if signal == 'long':
                        take_profit_price = entry_price * (1 + take_profit_pct / 100)
                        stop_loss_price = entry_price * (1 + stop_loss_pct / 100)
                        if leverage > 1: liquidation_price = entry_price * (1 - 1/leverage)
                    elif signal == 'short':
                        take_profit_price = entry_price * (1 - take_profit_pct / 100)
                        stop_loss_price = entry_price * (1 - stop_loss_pct / 100)
                        if leverage > 1: liquidation_price = entry_price * (1 + 1/leverage)
        
        # --- 4-3. 현재 자산 평가 및 기록 ---
        current_asset = cash
        if position_status != 'none':
            current_asset += _calculate_asset(entry_price, current_price, position_margin, leverage, position_status, 0)
        asset_history.append(current_asset)

    # 5. 최종 결과 계산 및 반환
    final_asset = asset_history[-1] if asset_history else initial_cash
    total_return = (final_asset / initial_cash - 1) * 100
    asset_series = pd.Series(asset_history)
    mdd = (1 - (asset_series / asset_series.cummax())).max() * 100 if not asset_series.empty else 0
    return {'total_return_pct': total_return, 'mdd_pct': -mdd, 'total_trades': trades, 'total_liquidations': liquidations, 'asset_history': asset_history}