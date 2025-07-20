"""
모든 invest 함수의 공통된 조건

input -> (strategy_param, df, initial_cash, fee_rate)
return -> { 'total_return_pct': ~, 'mdd_pct': ~, 'total_trades': ~, asset_history': [~, ~ ...] }

"""

import numpy as np
import pandas as pd


def calculate_rsi(data, period=14):
    """RSI 지표를 수동으로 계산합니다."""
    delta = data.diff()
    gain = delta.where(delta > 0, 0)
    loss = -delta.where(delta < 0, 0)

    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()

    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi

def calculate_bbands(data, length=20, std_dev=2):
    """볼린저 밴드를 수동으로 계산하여 DataFrame에 추가합니다."""
    middle_band = data['Close'].rolling(window=length).mean()
    std = data['Close'].rolling(window=length).std()
    
    data['BBM'] = middle_band
    data['BBU'] = middle_band + (std * std_dev)
    data['BBL'] = middle_band - (std * std_dev)
    return data

def calculate_adx(df, period=14):
    """ADX, +DI, -DI 지표를 계산하여 DataFrame에 추가합니다."""
    df['H-L'] = df['High'] - df['Low']
    df['H-C'] = np.abs(df['High'] - df['Close'].shift(1))
    df['L-C'] = np.abs(df['Low'] - df['Close'].shift(1))
    df['TR'] = df[['H-L', 'H-C', 'L-C']].max(axis=1)
    
    df['+DM'] = np.where((df['High'] - df['High'].shift(1)) > (df['Low'].shift(1) - df['Low']), df['High'] - df['High'].shift(1), 0)
    df['-DM'] = np.where((df['Low'].shift(1) - df['Low']) > (df['High'] - df['High'].shift(1)), df['Low'].shift(1) - df['Low'], 0)
    
    # EMA를 사용하여 ATR, +DI, -DI를 계산 (더 부드러운 값)
    atr = df['TR'].ewm(alpha=1/period, min_periods=period).mean()
    plus_di = 100 * (df['+DM'].ewm(alpha=1/period, min_periods=period).mean() / atr)
    minus_di = 100 * (df['-DM'].ewm(alpha=1/period, min_periods=period).mean() / atr)
    
    dx = 100 * np.abs(plus_di - minus_di) / (plus_di + minus_di)
    adx = dx.ewm(alpha=1/period, min_periods=period).mean()
    
    df['ADX'] = adx
    
    # 중간 계산 컬럼 삭제
    df.drop(['H-L', 'H-C', 'L-C', 'TR', '+DM', '-DM'], axis=1, inplace=True)
    
    return df

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

def ma_crossover_leverage_strategy(params, df, initial_cash, fee_rate, leverage):
    """
    레버리지를 사용하는 이동평균선 크로스오버 전략.
    - 골든 크로스: 롱 포지션 진입
    - 데드 크로스: 숏 포지션 진입
    - 강제 청산 로직 포함
    """
    short_ma_period = params.get('short_ma', 20)
    long_ma_period = params.get('long_ma', 60)
    leverage = max(1, leverage) # 레버리지는 최소 1배

    df['MA_short'] = df['Close'].rolling(window=short_ma_period).mean()
    df['MA_long'] = df['Close'].rolling(window=long_ma_period).mean()
    df.dropna(inplace=True)
    if df.empty:
        return {'total_return_pct': 0, 'mdd_pct': 0, 'total_trades': 0, 'total_liquidations': 0, 'asset_history': []}


    cash = initial_cash
    asset_history = [initial_cash]
    trades = 0
    liquidations = 0

    position_status = 'none' # 'none', 'long', 'short'
    entry_price = 0
    position_margin = 0 # 포지션에 진입한 증거금
    
    # 청산 가격 계산을 위한 공식 (수수료 등은 미반영한 간략식)
    # 롱 포지션 청산 가격 = 진입가 * (1 - 1/레버리지)
    # 숏 포지션 청산 가격 = 진입가 * (1 + 1/레버리지)
    liquidation_price = 0

    for i in range(1, len(df)):
        current_price = df['Close'].iloc[i]
        
        # --- 1. 강제 청산 확인 ---
        if position_status == 'long' and df['Low'].iloc[i] <= liquidation_price:
            cash = 0 # 전 재산(증거금) 손실
            position_status = 'none'
            liquidations += 1
            asset_history.append(cash)
            continue
        elif position_status == 'short' and df['High'].iloc[i] >= liquidation_price:
            cash = 0 # 전 재산(증거금) 손실
            position_status = 'none'
            liquidations += 1
            asset_history.append(cash)
            continue
        
        # 가진 현금이 없으면 거래 불가
        if cash <= 0:
            asset_history.append(cash)
            continue

        # --- 2. 매매 신호 확인 ---
        is_golden_cross = df['MA_short'].iloc[i-1] <= df['MA_long'].iloc[i-1] and df['MA_short'].iloc[i] > df['MA_long'].iloc[i]
        is_dead_cross = df['MA_short'].iloc[i-1] >= df['MA_long'].iloc[i-1] and df['MA_short'].iloc[i] < df['MA_long'].iloc[i]

        # --- 3. 포지션 진입/종료 ---
        # 골든 크로스 발생
        if is_golden_cross:
            # 기존 숏 포지션이 있었다면 종료
            if position_status == 'short':
                pnl = (entry_price - current_price) * (position_margin * leverage) / entry_price
                cash = position_margin + pnl
                cash *= (1 - fee_rate)
                position_status = 'none'
                trades += 1

            # 롱 포지션 진입
            if position_status == 'none':
                position_margin = cash
                entry_price = current_price
                position_status = 'long'
                liquidation_price = entry_price * (1 - 1/leverage)
                trades += 1

        # 데드 크로스 발생
        elif is_dead_cross:
            # 기존 롱 포지션이 있었다면 종료
            if position_status == 'long':
                pnl = (current_price - entry_price) * (position_margin * leverage) / entry_price
                cash = position_margin + pnl
                cash *= (1 - fee_rate)
                position_status = 'none'
                trades += 1

            # 숏 포지션 진입
            if position_status == 'none':
                position_margin = cash
                entry_price = current_price
                position_status = 'short'
                liquidation_price = entry_price * (1 + 1/leverage)
                trades += 1

        # --- 4. 현재 자산 평가 ---
        if position_status == 'long':
            current_pnl = (current_price - entry_price) * (position_margin * leverage) / entry_price
            current_asset = position_margin + current_pnl
        elif position_status == 'short':
            current_pnl = (entry_price - current_price) * (position_margin * leverage) / entry_price
            current_asset = position_margin + current_pnl
        else: # position_status == 'none'
            current_asset = cash
            
        asset_history.append(current_asset)

    # 최종 자산 계산
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
        'total_liquidations': liquidations, # 청산 횟수 추가
        'asset_history': asset_history
    }

def rsi_strategy(params, df, initial_cash, fee_rate):
    """RSI 지표를 이용한 매매 전략 (일반)"""
    rsi_period = params.get('rsi_period', 14)
    oversold_threshold = params.get('oversold_threshold', 30)
    overbought_threshold = params.get('overbought_threshold', 70)

    # 헬퍼 함수를 이용해 RSI 계산
    df['RSI'] = calculate_rsi(df['Close'], period=rsi_period)
    df.dropna(inplace=True)

    cash = initial_cash
    coins = 0
    trades = 0
    asset_history = []
    for i in range(1, len(df)):
        if df['RSI'].iloc[i-1] < oversold_threshold and df['RSI'].iloc[i] >= oversold_threshold and cash > 0:
            coins = (cash / df['Close'].iloc[i]) * (1 - fee_rate)
            cash = 0
            trades += 1
        elif df['RSI'].iloc[i-1] > overbought_threshold and df['RSI'].iloc[i] <= overbought_threshold and coins > 0:
            cash = (coins * df['Close'].iloc[i]) * (1 - fee_rate)
            coins = 0
            trades += 1
        current_asset = cash + coins * df['Close'].iloc[i]
        asset_history.append(current_asset)
    final_asset = asset_history[-1] if asset_history else initial_cash
    total_return = (final_asset / initial_cash - 1) * 100
    asset_series = pd.Series(asset_history)
    mdd = (1 - (asset_series / asset_series.cummax())).max() * 100
    return {'total_return_pct': total_return, 'mdd_pct': -mdd, 'total_trades': trades, 'asset_history': asset_history}


def rsi_leverage_strategy(params, df, initial_cash, fee_rate, leverage):
    """RSI 지표를 이용한 매매 전략 (레버리지)"""
    rsi_period = params.get('rsi_period', 14)
    oversold_threshold = params.get('oversold_threshold', 30)
    overbought_threshold = params.get('overbought_threshold', 70)
    leverage = max(1, leverage)

    # 헬퍼 함수를 이용해 RSI 계산
    df['RSI'] = calculate_rsi(df['Close'], period=rsi_period)
    df.dropna(inplace=True)
    if df.empty: return {'total_return_pct': 0, 'mdd_pct': 0, 'total_trades': 0, 'total_liquidations': 0, 'asset_history': []}

    cash = initial_cash
    asset_history = [initial_cash]
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
                pnl = (entry_price - current_price) * (position_margin * leverage) / entry_price; cash, position_status, trades = position_margin + pnl, 'none', trades + 1; cash *= (1 - fee_rate)
            if position_status == 'none':
                position_margin, entry_price, position_status, trades = cash, current_price, 'long', trades + 1; liquidation_price = entry_price * (1 - 1/leverage)
        elif is_sell_signal:
            if position_status == 'long':
                pnl = (current_price - entry_price) * (position_margin * leverage) / entry_price; cash, position_status, trades = position_margin + pnl, 'none', trades + 1; cash *= (1 - fee_rate)
            if position_status == 'none':
                position_margin, entry_price, position_status, trades = cash, current_price, 'short', trades + 1; liquidation_price = entry_price * (1 + 1/leverage)
        if position_status == 'long': current_asset = position_margin + (current_price - entry_price) * (position_margin * leverage) / entry_price
        elif position_status == 'short': current_asset = position_margin + (entry_price - current_price) * (position_margin * leverage) / entry_price
        else: current_asset = cash
        asset_history.append(current_asset)
    final_asset = asset_history[-1] if asset_history else initial_cash
    total_return = (final_asset / initial_cash - 1) * 100
    asset_series = pd.Series(asset_history)
    mdd = (1 - (asset_series / asset_series.cummax())).max() * 100
    return {'total_return_pct': total_return, 'mdd_pct': -mdd, 'total_trades': trades, 'total_liquidations': liquidations, 'asset_history': asset_history}


# ==============================================================================
# 4. ADX 필터를 이용한 듀얼 전략
# ==============================================================================

def adx_filtered_dual_strategy(params, df, initial_cash, fee_rate, leverage):
    # 1. 파라미터 설정
    adx_period = params.get('adx_period', 14)
    adx_threshold = params.get('adx_threshold', 25)
    rsi_period = params.get('rsi_period', 14)
    oversold_threshold = params.get('oversold_threshold', 30)
    overbought_threshold = params.get('overbought_threshold', 70)
    ema_short_period = params.get('ema_short_period', 12)
    ema_long_period = params.get('ema_long_period', 26)
    stop_loss_pct = params.get('stop_loss_pct', -1.5)
    take_profit_pct = params.get('take_profit_pct', 3.0)
    leverage = max(1, leverage)

    # 2. 데이터 전처리 및 지표 계산
    # 경고: 이 전략은 1시간봉보다 짧은 봉(예: 5분봉)에서 더 잘 작동할 수 있습니다.
    # backtesting.py에서 시간봉('h') 대신 '5T' 등으로 리샘플링해야 의미가 있습니다.
    df = calculate_adx(df, period=adx_period)
    df['RSI'] = calculate_rsi(df['Close'], period=rsi_period)
    df['EMA_short'] = df['Close'].ewm(span=ema_short_period, adjust=False).mean()
    df['EMA_long'] = df['Close'].ewm(span=ema_long_period, adjust=False).mean()
    df.dropna(inplace=True)
    if df.empty: return {'total_return_pct': 0, 'mdd_pct': 0, 'total_trades': 0, 'total_liquidations': 0, 'asset_history': []}

    # 3. 백테스팅 변수 초기화
    cash = initial_cash
    asset_history = [initial_cash]
    trades, liquidations = 0, 0
    position_status = 'none'
    entry_price, position_margin, stop_loss_price, take_profit_price = 0, 0, 0, 0

    # 4. 백테스팅 루프
    for i in range(1, len(df)):
        current_price = df['Close'].iloc[i]
        
        # --- 4-1. 위험 관리 (포지션 종료) ---
        if position_status != 'none':
            exit_price = 0
            pnl = 0
            if position_status == 'long':
                liquidation_price = entry_price * (1 - 1/leverage)
                if df['Low'].iloc[i] <= liquidation_price:
                    exit_price, liquidations = liquidation_price, liquidations + 1
                elif df['Low'].iloc[i] <= stop_loss_price: exit_price = stop_loss_price
                elif df['High'].iloc[i] >= take_profit_price: exit_price = take_profit_price
                if exit_price > 0: pnl = (exit_price - entry_price) * (position_margin * leverage) / entry_price
            elif position_status == 'short':
                liquidation_price = entry_price * (1 + 1/leverage)
                if df['High'].iloc[i] >= liquidation_price:
                    exit_price, liquidations = liquidation_price, liquidations + 1
                elif df['High'].iloc[i] >= stop_loss_price: exit_price = stop_loss_price
                elif df['Low'].iloc[i] <= take_profit_price: exit_price = take_profit_price
                if exit_price > 0: pnl = (entry_price - exit_price) * (position_margin * leverage) / entry_price
            
            if exit_price > 0:
                cash = position_margin + pnl
                if exit_price == liquidation_price: cash = 0
                position_status = 'none'

        # --- 4-2. 신규 포지션 진입 ---
        if position_status == 'none':
            if cash <= 0: asset_history.append(cash); continue
            
            is_trending_market = df['ADX'].iloc[i] > adx_threshold
            signal = 'none'

            if is_trending_market:
                if df['EMA_short'].iloc[i-1]<=df['EMA_long'].iloc[i-1] and df['EMA_short'].iloc[i]>df['EMA_long'].iloc[i]: signal = 'long'
                elif df['EMA_short'].iloc[i-1]>=df['EMA_long'].iloc[i-1] and df['EMA_short'].iloc[i]<df['EMA_long'].iloc[i]: signal = 'short'
            else:
                if df['RSI'].iloc[i-1]<oversold_threshold and df['RSI'].iloc[i]>=oversold_threshold: signal = 'long'
                elif df['RSI'].iloc[i-1]>overbought_threshold and df['RSI'].iloc[i]<=overbought_threshold: signal = 'short'

            if signal != 'none':
                position_margin, entry_price, position_status, trades = cash, current_price, signal, trades + 1
                if signal == 'long':
                    stop_loss_price = entry_price * (1 + stop_loss_pct / 100)
                    take_profit_price = entry_price * (1 + take_profit_pct / 100)
                else: # short
                    stop_loss_price = entry_price * (1 - stop_loss_pct / 100)
                    take_profit_price = entry_price * (1 - take_profit_pct / 100)
        
        # --- 4-3. 현재 자산 평가 ---
        if position_status == 'long': current_asset = position_margin + (current_price - entry_price) * (position_margin * leverage) / entry_price
        elif position_status == 'short': current_asset = position_margin + (entry_price - current_price) * (position_margin * leverage) / entry_price
        else: current_asset = cash
        asset_history.append(current_asset)

    # 5. 최종 결과 계산
    final_asset = asset_history[-1] if asset_history else initial_cash
    total_return = (final_asset / initial_cash - 1) * 100
    asset_series = pd.Series(asset_history)
    mdd = (1 - (asset_series / asset_series.cummax())).max() * 100
    return {'total_return_pct': total_return, 'mdd_pct': -mdd, 'total_trades': trades, 'total_liquidations': liquidations, 'asset_history': asset_history}


# ==============================================================================
# 3. 볼린저 밴드 전략 (직접 계산 방식으로 수정)
# ==============================================================================

def bollinger_band_strategy(params, df, initial_cash, fee_rate):
    """볼린저 밴드 평균 회귀 전략 (일반)"""
    bb_length = params.get('bb_length', 20)
    bb_std = params.get('bb_std', 2)

    # 헬퍼 함수를 이용해 볼린저 밴드 계산
    df = calculate_bbands(df, length=bb_length, std_dev=bb_std)
    df.dropna(inplace=True)
    
    cash = initial_cash
    coins = 0
    trades = 0
    asset_history = []
    for i in range(1, len(df)):
        if df['Close'].iloc[i] < df['BBL'].iloc[i] and cash > 0:
            coins = (cash / df['Close'].iloc[i]) * (1 - fee_rate)
            cash = 0
            trades += 1
        elif df['Close'].iloc[i] > df['BBU'].iloc[i] and coins > 0:
            cash = (coins * df['Close'].iloc[i]) * (1 - fee_rate)
            coins = 0
            trades += 1
        current_asset = cash + coins * df['Close'].iloc[i]
        asset_history.append(current_asset)
    final_asset = asset_history[-1] if asset_history else initial_cash
    total_return = (final_asset / initial_cash - 1) * 100
    asset_series = pd.Series(asset_history)
    mdd = (1 - (asset_series / asset_series.cummax())).max() * 100
    return {'total_return_pct': total_return, 'mdd_pct': -mdd, 'total_trades': trades, 'asset_history': asset_history}


def bollinger_band_leverage_strategy(params, df, initial_cash, fee_rate, leverage):
    """볼린저 밴드 평균 회귀 전략 (레버리지)"""
    bb_length = params.get('bb_length', 20)
    bb_std = params.get('bb_std', 2)
    leverage = max(1, leverage)

    # 헬퍼 함수를 이용해 볼린저 밴드 계산
    df = calculate_bbands(df, length=bb_length, std_dev=bb_std)
    df.dropna(inplace=True)
    if df.empty: return {'total_return_pct': 0, 'mdd_pct': 0, 'total_trades': 0, 'total_liquidations': 0, 'asset_history': []}

    cash = initial_cash
    asset_history = [initial_cash]
    trades, liquidations, position_status, entry_price, position_margin, liquidation_price = 0, 0, 'none', 0, 0, 0
    for i in range(1, len(df)):
        current_price = df['Close'].iloc[i]
        if position_status == 'long' and df['Low'].iloc[i] <= liquidation_price:
            cash, position_status, liquidations = 0, 'none', liquidations + 1; asset_history.append(cash); continue
        elif position_status == 'short' and df['High'].iloc[i] >= liquidation_price:
            cash, position_status, liquidations = 0, 'none', liquidations + 1; asset_history.append(cash); continue
        if position_status == 'long' and current_price >= df['BBM'].iloc[i]:
            pnl = (current_price - entry_price) * (position_margin * leverage) / entry_price; cash, position_status, trades = position_margin + pnl, 'none', trades + 1; cash *= (1 - fee_rate)
        elif position_status == 'short' and current_price <= df['BBM'].iloc[i]:
            pnl = (entry_price - current_price) * (position_margin * leverage) / entry_price; cash, position_status, trades = position_margin + pnl, 'none', trades + 1; cash *= (1 - fee_rate)
        if cash <= 0: asset_history.append(cash); continue
        if position_status == 'none':
            if current_price < df['BBL'].iloc[i]:
                position_margin, entry_price, position_status, trades = cash, current_price, 'long', trades + 1; liquidation_price = entry_price * (1 - 1/leverage)
            elif current_price > df['BBU'].iloc[i]:
                position_margin, entry_price, position_status, trades = cash, current_price, 'short', trades + 1; liquidation_price = entry_price * (1 + 1/leverage)
        if position_status == 'long': current_asset = position_margin + (current_price - entry_price) * (position_margin * leverage) / entry_price
        elif position_status == 'short': current_asset = position_margin + (entry_price - current_price) * (position_margin * leverage) / entry_price
        else: current_asset = cash
        asset_history.append(current_asset)
    final_asset = asset_history[-1] if asset_history else initial_cash
    total_return = (final_asset / initial_cash - 1) * 100
    asset_series = pd.Series(asset_history)
    mdd = (1 - (asset_series / asset_series.cummax())).max() * 100
    return {'total_return_pct': total_return, 'mdd_pct': -mdd, 'total_trades': trades, 'total_liquidations': liquidations, 'asset_history': asset_history}
