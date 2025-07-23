# strategy_adapter.py
# Backtest 전략을 실시간 트레이딩봇에 연결하는 어댑터 (수정된 버전)

import pandas as pd
import numpy as np
from typing import Dict, Any, Optional, Tuple
from dataclasses import dataclass
from enum import Enum
import sys
import os

class SignalType(Enum):
    NONE = "none"
    LONG = "long"
    SHORT = "short"
    CLOSE = "close"

@dataclass
class TradingSignal:
    signal_type: SignalType
    strength: float = 0.0  # 신호 강도 (0-1)
    price: float = 0.0
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    leverage: int = 1
    reason: str = ""

def calculate_rsi(prices: pd.Series, period: int = 14) -> pd.Series:
    """RSI 계산 함수"""
    delta = prices.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return rsi

def calculate_bbands(df: pd.DataFrame, length: int = 20, std_dev: float = 2) -> pd.DataFrame:
    """볼린저 밴드 계산 함수"""
    df_copy = df.copy()
    df_copy['BBM'] = df_copy['Close'].rolling(window=length).mean()
    bb_std = df_copy['Close'].rolling(window=length).std()
    df_copy['BBU'] = df_copy['BBM'] + (bb_std * std_dev)
    df_copy['BBL'] = df_copy['BBM'] - (bb_std * std_dev)
    return df_copy

class BacktestStrategyAdapter:
    """
    Backtest 전략을 실시간 트레이딩에 적응시키는 어댑터 클래스
    """

    def __init__(self, strategy_name: str, params: Dict[str, Any], leverage: int = 1):
        self.strategy_name = strategy_name
        self.params = params
        self.leverage = leverage

        # 현재 포지션 상태 추적
        self.current_position = SignalType.NONE
        self.entry_price = 0.0
        self.position_size = 0.0

        # 과거 데이터 버퍼 (지표 계산용)
        self.data_buffer = pd.DataFrame()
        self.buffer_size = 500  # 충분한 지표 계산을 위한 버퍼 크기

    def update_data(self, new_candle: Dict[str, float]) -> None:
        """
        새로운 캔들 데이터를 버퍼에 추가
        """
        new_row = pd.DataFrame([{
            'Open': new_candle['open'],
            'High': new_candle['high'],
            'Low': new_candle['low'],
            'Close': new_candle['close'],
            'Volume': new_candle.get('volume', 0)
        }])

        self.data_buffer = pd.concat([self.data_buffer, new_row], ignore_index=True)

        # 버퍼 크기 관리
        if len(self.data_buffer) > self.buffer_size:
            self.data_buffer = self.data_buffer.tail(self.buffer_size).reset_index(drop=True)

    def get_trading_signal(self, current_price: float) -> TradingSignal:
        """
        현재 데이터를 기반으로 트레이딩 신호 생성
        """
        if len(self.data_buffer) < 50:  # 최소 데이터 요구사항
            return TradingSignal(SignalType.NONE, reason="Insufficient data")

        try:
            # 백테스팅 전략 실행 (마지막 구간만 계산)
            mini_df = self.data_buffer.tail(100).copy()  # 충분한 지표 계산을 위해

            # 내장된 전략 로직으로 신호 추출
            signal = self._extract_signal_from_strategy(mini_df, current_price)

            return signal

        except Exception as e:
            return TradingSignal(SignalType.NONE, reason=f"Strategy error: {str(e)}")

    def _extract_signal_from_strategy(self, df: pd.DataFrame, current_price: float) -> TradingSignal:
        """
        전략별 신호 추출 로직
        """
        if self.strategy_name == 'ma_crossover':
            return self._extract_ma_crossover_signal(df, current_price)
        elif 'macd' in self.strategy_name:
            return self._extract_macd_signal(df, current_price)
        elif self.strategy_name == 'rsi_leverage':
            return self._extract_rsi_signal(df, current_price)
        elif self.strategy_name == 'bollinger_band':
            return self._extract_bb_signal(df, current_price)
        elif 'momentum_spike' in self.strategy_name:
            return self._extract_momentum_signal(df, current_price)
        elif self.strategy_name == 'triple_ma':
            return self._extract_triple_ma_signal(df, current_price)
        else:
            return self._extract_generic_signal(df, current_price)

    def _extract_ma_crossover_signal(self, df: pd.DataFrame, current_price: float) -> TradingSignal:
        """MA 크로스오버 신호 추출"""
        short_ma = self.params.get('short_ma', 20)
        long_ma = self.params.get('long_ma', 60)

        df['MA_short'] = df['Close'].rolling(window=short_ma).mean()
        df['MA_long'] = df['Close'].rolling(window=long_ma).mean()

        if len(df) < 2:
            return TradingSignal(SignalType.NONE)

    def _extract_triple_ma_signal(self, df: pd.DataFrame, current_price: float) -> TradingSignal:
        """삼중 이동평균 신호 추출"""
        short_ma = self.params.get('short_ma', 10)
        medium_ma = self.params.get('medium_ma', 20)
        long_ma = self.params.get('long_ma', 50)

        df['MA_short'] = df['Close'].rolling(window=short_ma).mean()
        df['MA_medium'] = df['Close'].rolling(window=medium_ma).mean()
        df['MA_long'] = df['Close'].rolling(window=long_ma).mean()

        if len(df) < 2:
            return TradingSignal(SignalType.NONE)

        # 현재와 이전 MA 값들
        curr_short = df['MA_short'].iloc[-1]
        curr_medium = df['MA_medium'].iloc[-1]
        curr_long = df['MA_long'].iloc[-1]

        prev_short = df['MA_short'].iloc[-2]
        prev_medium = df['MA_medium'].iloc[-2]

        # 강력한 상승 신호: 단기 > 중기 > 장기 순서가 되는 순간
        if (curr_short > curr_medium > curr_long and
                prev_short <= prev_medium):
            return TradingSignal(SignalType.LONG, strength=0.9, price=current_price,
                                 reason="Triple MA bullish alignment")

        # 강력한 하락 신호: 단기 < 중기 < 장기 순서가 되는 순간
        elif (curr_short < curr_medium < curr_long and
              prev_short >= prev_medium):
            return TradingSignal(SignalType.SHORT, strength=0.9, price=current_price,
                                 reason="Triple MA bearish alignment")

        return TradingSignal(SignalType.NONE)

        # 골든크로스/데드크로스 확인
        prev_short, prev_long = df['MA_short'].iloc[-2], df['MA_long'].iloc[-2]
        curr_short, curr_long = df['MA_short'].iloc[-1], df['MA_long'].iloc[-1]

        if prev_short <= prev_long and curr_short > curr_long:
            return TradingSignal(SignalType.LONG, strength=0.8, price=current_price,
                                 reason="Golden Cross detected")
        elif prev_short >= prev_long and curr_short < curr_long:
            return TradingSignal(SignalType.SHORT, strength=0.8, price=current_price,
                                 reason="Dead Cross detected")

        return TradingSignal(SignalType.NONE)

    def _extract_macd_signal(self, df: pd.DataFrame, current_price: float) -> TradingSignal:
        """MACD 신호 추출"""
        fast_ma = self.params.get('fast_ma', 12)
        slow_ma = self.params.get('slow_ma', 26)
        signal_ma = self.params.get('signal_ma', 9)

        ema_fast = df['Close'].ewm(span=fast_ma).mean()
        ema_slow = df['Close'].ewm(span=slow_ma).mean()
        df['MACD'] = ema_fast - ema_slow
        df['Signal'] = df['MACD'].ewm(span=signal_ma).mean()

        if len(df) < 2:
            return TradingSignal(SignalType.NONE)

        # MACD 크로스오버 확인
        prev_macd, prev_signal = df['MACD'].iloc[-2], df['Signal'].iloc[-2]
        curr_macd, curr_signal = df['MACD'].iloc[-1], df['Signal'].iloc[-1]

        # 추가: 가격이 장기 이동평균 위/아래에 있는지 확인 (트렌드 필터)
        regime_period = self.params.get('regime_filter_period', 200)
        if len(df) >= regime_period:
            long_ma = df['Close'].rolling(window=regime_period).mean().iloc[-1]
            is_uptrend = current_price > long_ma
            is_downtrend = current_price < long_ma
        else:
            is_uptrend = True  # 데이터 부족시 필터 비활성화
            is_downtrend = True

        if prev_macd <= prev_signal and curr_macd > curr_signal and is_uptrend:
            return TradingSignal(SignalType.LONG, strength=0.7, price=current_price,
                                 reason="MACD Golden Cross (uptrend)")
        elif prev_macd >= prev_signal and curr_macd < curr_signal and is_downtrend:
            return TradingSignal(SignalType.SHORT, strength=0.7, price=current_price,
                                 reason="MACD Dead Cross (downtrend)")

        return TradingSignal(SignalType.NONE)

    def _extract_rsi_signal(self, df: pd.DataFrame, current_price: float) -> TradingSignal:
        """RSI 신호 추출"""
        rsi_period = self.params.get('rsi_period', 14)
        oversold = self.params.get('oversold_threshold', 30)
        overbought = self.params.get('overbought_threshold', 70)

        df['RSI'] = calculate_rsi(df['Close'], period=rsi_period)

        if len(df) < 2:
            return TradingSignal(SignalType.NONE)

        prev_rsi, curr_rsi = df['RSI'].iloc[-2], df['RSI'].iloc[-1]

        # RSI 과매도 구간에서 상승
        if prev_rsi < oversold and curr_rsi >= oversold:
            return TradingSignal(SignalType.LONG, strength=0.6, price=current_price,
                                 reason=f"RSI oversold recovery: {curr_rsi:.1f}")
        # RSI 과매수 구간에서 하락
        elif prev_rsi > overbought and curr_rsi <= overbought:
            return TradingSignal(SignalType.SHORT, strength=0.6, price=current_price,
                                 reason=f"RSI overbought decline: {curr_rsi:.1f}")

        return TradingSignal(SignalType.NONE)

    def _extract_bb_signal(self, df: pd.DataFrame, current_price: float) -> TradingSignal:
        """볼린저 밴드 신호 추출"""
        bb_length = self.params.get('bb_length', 20)
        bb_std = self.params.get('bb_std', 2)

        df = calculate_bbands(df, length=bb_length, std_dev=bb_std)

        if len(df) < 1:
            return TradingSignal(SignalType.NONE)

        current_bb_lower = df['BBL'].iloc[-1]
        current_bb_upper = df['BBU'].iloc[-1]
        current_bb_middle = df['BBM'].iloc[-1]

        # 볼린저 밴드 하단 터치 -> 롱
        if current_price <= current_bb_lower:
            return TradingSignal(SignalType.LONG, strength=0.7, price=current_price,
                                 take_profit=current_bb_middle,
                                 reason="BB Lower Band touch")
        # 볼린저 밴드 상단 터치 -> 숏
        elif current_price >= current_bb_upper:
            return TradingSignal(SignalType.SHORT, strength=0.7, price=current_price,
                                 take_profit=current_bb_middle,
                                 reason="BB Upper Band touch")

        return TradingSignal(SignalType.NONE)

    def _extract_momentum_signal(self, df: pd.DataFrame, current_price: float) -> TradingSignal:
        """모멘텀 스파이크 신호 추출"""
        spike_pct = self.params.get('spike_pct', 3.0)
        take_profit_pct = self.params.get('take_profit_pct', 1.0)
        stop_loss_pct = self.params.get('stop_loss_pct', -1.0)

        if len(df) < 2:
            return TradingSignal(SignalType.NONE)

        # 이전 캔들의 변화율 계산
        prev_open = df['Open'].iloc[-2]
        prev_close = df['Close'].iloc[-2]
        prev_change_pct = ((prev_close / prev_open) - 1) * 100

        # 급등 감지 -> 롱 진입
        if prev_change_pct >= spike_pct:
            tp_price = current_price * (1 + take_profit_pct / 100)
            sl_price = current_price * (1 + stop_loss_pct / 100)
            return TradingSignal(SignalType.LONG, strength=0.9, price=current_price,
                                 take_profit=tp_price, stop_loss=sl_price,
                                 reason=f"Momentum spike up: {prev_change_pct:.2f}%")

        # 급락 감지 -> 숏 진입
        elif prev_change_pct <= -spike_pct:
            tp_price = current_price * (1 - take_profit_pct / 100)
            sl_price = current_price * (1 - stop_loss_pct / 100)
            return TradingSignal(SignalType.SHORT, strength=0.9, price=current_price,
                                 take_profit=tp_price, stop_loss=sl_price,
                                 reason=f"Momentum spike down: {prev_change_pct:.2f}%")

        return TradingSignal(SignalType.NONE)

    def _extract_generic_signal(self, df: pd.DataFrame, current_price: float) -> TradingSignal:
        """일반적인 신호 추출 (단순 MA 기반)"""
        ma_period = self.params.get('ma_period', 50)
        df['MA'] = df['Close'].rolling(window=ma_period).mean()

        if len(df) < 2:
            return TradingSignal(SignalType.NONE)

        prev_close, prev_ma = df['Close'].iloc[-2], df['MA'].iloc[-2]
        curr_close, curr_ma = df['Close'].iloc[-1], df['MA'].iloc[-1]

        # 가격이 MA를 상향 돌파
        if prev_close <= prev_ma and curr_close > curr_ma:
            return TradingSignal(SignalType.LONG, strength=0.5, price=current_price,
                                 reason="Price break above MA")
        # 가격이 MA를 하향 돌파
        elif prev_close >= prev_ma and curr_close < curr_ma:
            return TradingSignal(SignalType.SHORT, strength=0.5, price=current_price,
                                 reason="Price break below MA")

        return TradingSignal(SignalType.NONE)

# 사용 예시 및 테스트
if __name__ == "__main__":
    # MACD 전략 설정
    strategy_adapter = BacktestStrategyAdapter(
        strategy_name='macd_final',
        params={
            'regime_filter_period': 200  # 1시간봉 기준
        },
        leverage=3
    )

    # 가상의 캔들 데이터로 테스트
    print("Testing strategy adapter...")

    # 테스트 데이터 생성
    import random
    base_price = 50000

    for i in range(100):
        # 트렌드가 있는 가상 데이터 생성
        price_change = random.uniform(-0.02, 0.02)
        if i > 50:  # 후반부에 상승 트렌드
            price_change += 0.005

        base_price *= (1 + price_change)

        sample_candle = {
            'open': base_price * random.uniform(0.995, 1.005),
            'high': base_price * random.uniform(1.000, 1.010),
            'low': base_price * random.uniform(0.990, 1.000),
            'close': base_price,
            'volume': random.uniform(100, 1000)
        }

        strategy_adapter.update_data(sample_candle)

        # 주기적으로 신호 확인
        if i % 10 == 0 and i > 50:
            signal = strategy_adapter.get_trading_signal(base_price)
            if signal.signal_type != SignalType.NONE:
                print(f"Candle {i}: Signal: {signal.signal_type.value} "
                      f"(Strength: {signal.strength:.2f}) - {signal.reason}")

    print("Strategy adapter test completed!")