# ma_cross_strategy.py - 이동평균 교차 전략
import pandas as pd
import numpy as np
from typing import Dict, Any
from .base_strategy import BaseStrategy, TradingSignal

class MACrossStrategy(BaseStrategy):
    """이동평균 교차 전략
    
    골든크로스/데드크로스를 이용한 매매 전략:
    - 골든크로스: 단기 MA > 장기 MA → 매수 신호
    - 데드크로스: 단기 MA < 장기 MA → 매도 신호
    
    추가 필터:
    - 거래량 확인: 평균 거래량 대비 일정 배율 이상
    - RSI 필터: 극단적 과매수/과매도 구간 제외
    - 신호 강도: MA 간격과 거래량으로 강도 결정
    """
    
    def __init__(self, config):
        super().__init__(config)
        self.logger.info(f"이동평균 교차 전략 초기화: 단기 MA({config.short_ma_period}) vs 장기 MA({config.long_ma_period})")
        
        # 전략별 상태 변수
        self.previous_ma_cross = None  # 이전 교차 상태
        self.cross_confirmed = False   # 교차 확인 상태
        
    def calculate_indicators(self, df: pd.DataFrame) -> Dict[str, Any]:
        """기술적 지표 계산"""
        indicators = {}
        
        try:
            # 이동평균 계산
            indicators['short_ma'] = df['close'].rolling(window=self.config.short_ma_period).mean()
            indicators['long_ma'] = df['close'].rolling(window=self.config.long_ma_period).mean()
            
            # 현재 MA 값들
            current_short_ma = indicators['short_ma'].iloc[-1]
            current_long_ma = indicators['long_ma'].iloc[-1]
            
            indicators['current_short_ma'] = current_short_ma
            indicators['current_long_ma'] = current_long_ma
            
            # MA 간격 (백분율)
            ma_diff_pct = ((current_short_ma - current_long_ma) / current_long_ma) * 100
            indicators['ma_diff_pct'] = ma_diff_pct
            
            # 교차 상태 확인
            ma_cross = "golden" if current_short_ma > current_long_ma else "dead"
            indicators['ma_cross'] = ma_cross
            
            # 교차 발생 여부 (이전 상태와 비교)
            if len(indicators['short_ma']) >= 2 and len(indicators['long_ma']) >= 2:
                prev_short = indicators['short_ma'].iloc[-2]
                prev_long = indicators['long_ma'].iloc[-2]
                prev_cross = "golden" if prev_short > prev_long else "dead"
                
                indicators['cross_occurred'] = ma_cross != prev_cross
                indicators['cross_direction'] = ma_cross if indicators['cross_occurred'] else None
            else:
                indicators['cross_occurred'] = False
                indicators['cross_direction'] = None
            
            # 거래량 분석
            if len(df) >= 20:
                volume_ma = df['volume'].rolling(window=20).mean()
                current_volume = df['volume'].iloc[-1]
                volume_ratio = current_volume / volume_ma.iloc[-1] if volume_ma.iloc[-1] > 0 else 1.0
                indicators['volume_ratio'] = volume_ratio
                indicators['avg_volume'] = volume_ma.iloc[-1]
            else:
                indicators['volume_ratio'] = 1.0
                indicators['avg_volume'] = df['volume'].mean()
            
            # RSI 계산 (14일)
            if len(df) >= 14:
                delta = df['close'].diff()
                gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
                loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
                rs = gain / loss
                rsi = 100 - (100 / (1 + rs))
                indicators['rsi'] = rsi.iloc[-1]
            else:
                indicators['rsi'] = 50.0  # 중립값
            
            # 현재 가격
            indicators['current_price'] = df['close'].iloc[-1]
            
            self.logger.debug(f"지표 계산 완료: 단기MA={current_short_ma:.4f}, 장기MA={current_long_ma:.4f}, 교차={ma_cross}")
            
            return indicators
            
        except Exception as e:
            self.logger.error(f"지표 계산 오류: {e}")
            return {}
    
    def generate_signal(self, df: pd.DataFrame) -> TradingSignal:
        """이동평균 교차 신호 생성 - 더 자주 거래하도록 완화"""
        try:
            current_price = self.indicators['current_price']
            current_short_ma = self.indicators['current_short_ma']
            current_long_ma = self.indicators['current_long_ma']
            ma_diff_pct = self.indicators['ma_diff_pct']
            volume_ratio = self.indicators.get('volume_ratio', 1.0)
            rsi = self.indicators.get('rsi', 50)
            
            # 🚀 더 자주 거래하도록 조건 대폭 완화
            if abs(ma_diff_pct) < 0.005:  # MA 차이가 0.005% 미만이면 중립 (기존 0.01%에서 완화)
                return TradingSignal(
                    TradingSignal.HOLD,
                    "normal",
                    current_price,
                    f"중립 구간 - MA 차이: {ma_diff_pct:+.3f}%"
                )
            
            # 🎯 매우 민감한 신호 조건 (거의 모든 움직임에 반응)
            if current_short_ma > current_long_ma:
                # 매수 신호 조건 극도로 완화
                if ma_diff_pct > 0.01:  # 0.01% 이상 차이면 매수 (기존 0.05%에서 완화)
                    action = TradingSignal.BUY
                    reason = f"단기MA 우위 - 차이: {ma_diff_pct:+.3f}% (매수 신호)"
                else:
                    action = TradingSignal.HOLD
                    reason = f"단기MA 약간 우위 - 차이: {ma_diff_pct:+.3f}% (대기)"
            else:
                # 매도 신호 조건 극도로 완화
                if ma_diff_pct < -0.01:  # -0.01% 이하 차이면 매도 (기존 -0.05%에서 완화)
                    action = TradingSignal.SELL
                    reason = f"장기MA 우위 - 차이: {ma_diff_pct:+.3f}% (매도 신호)"
                else:
                    action = TradingSignal.HOLD
                    reason = f"장기MA 약간 우위 - 차이: {ma_diff_pct:+.3f}% (대기)"
            
            # 🔥 RSI 필터 완전 제거 (모든 구간에서 거래 허용)
            
            # 🎯 거래량 필터도 완화 (거래량이 낮아도 거래 허용)
            
            # 신호 강도 계산 (더 관대한 기준)
            if abs(ma_diff_pct) > 0.3:
                strength = "strong"
            elif abs(ma_diff_pct) > 0.1:
                strength = "normal"  
            else:
                strength = "weak"
            
            # 신호 생성
            signal = TradingSignal(
                action=action,
                strength=strength,
                price=current_price,
                reason=reason,
                data={
                    'short_ma': current_short_ma,
                    'long_ma': current_long_ma,
                    'ma_diff_pct': ma_diff_pct,
                    'volume_ratio': volume_ratio,
                    'rsi': rsi
                }
            )
            
            # 🚀 더 자주 거래: 모든 신호 로깅
            if action != TradingSignal.HOLD:
                self.logger.info(f"📊 적극적 거래 신호: {signal}")
            
            return signal
            
        except Exception as e:
            self.logger.error(f"신호 생성 오류: {e}")
            return TradingSignal(
                TradingSignal.HOLD,
                "normal",
                self.indicators.get('current_price', 0),
                f"신호 생성 실패: {str(e)}"
            )
    
    def calculate_signal_strength(self, ma_diff_pct: float, volume_ratio: float) -> str:
        """이동평균 교차 전용 신호 강도 계산"""
        try:
            # MA 간격이 클수록 강한 신호
            ma_strength_score = 0
            if ma_diff_pct > 3.0:
                ma_strength_score = 3
            elif ma_diff_pct > 1.5:
                ma_strength_score = 2
            elif ma_diff_pct > 0.5:
                ma_strength_score = 1
            
            # 거래량이 많을수록 강한 신호
            volume_strength_score = 0
            if volume_ratio > 2.0:
                volume_strength_score = 3
            elif volume_ratio > 1.5:
                volume_strength_score = 2
            elif volume_ratio > 1.2:
                volume_strength_score = 1
            
            # 종합 점수
            total_score = ma_strength_score + volume_strength_score
            
            if total_score >= 4:
                return "strong"
            elif total_score >= 2:
                return "normal"
            else:
                return "weak"
                
        except Exception as e:
            self.logger.error(f"신호 강도 계산 오류: {e}")
            return "normal"
    
    def get_current_trend(self) -> str:
        """현재 트렌드 반환"""
        if not self.indicators:
            return "unknown"
        
        ma_diff_pct = self.indicators.get('ma_diff_pct', 0)
        
        if ma_diff_pct > 1.0:
            return "strong_uptrend"
        elif ma_diff_pct > 0.3:
            return "uptrend"
        elif ma_diff_pct < -1.0:
            return "strong_downtrend"
        elif ma_diff_pct < -0.3:
            return "downtrend"
        else:
            return "sideways"
    
    def get_strategy_status(self) -> Dict[str, Any]:
        """전략 상태 정보"""
        status = self.get_strategy_info()
        
        if self.indicators:
            status.update({
                'current_trend': self.get_current_trend(),
                'ma_cross_state': self.indicators.get('ma_cross', 'unknown'),
                'ma_diff_pct': self.indicators.get('ma_diff_pct', 0),
                'volume_ratio': self.indicators.get('volume_ratio', 1.0),
                'rsi': self.indicators.get('rsi', 50),
                'ready_for_signal': len(self.price_data) >= max(self.config.short_ma_period, self.config.long_ma_period)
            })
        
        return status
