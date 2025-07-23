# base_strategy.py - 기본 전략 추상 클래스
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, Tuple
import pandas as pd
import logging
from datetime import datetime

class TradingSignal:
    """트레이딩 신호 클래스"""
    
    BUY = "BUY"
    SELL = "SELL" 
    HOLD = "HOLD"
    
    def __init__(self, action: str, strength: str, price: float, reason: str, data: Dict[str, Any] = None):
        self.action = action  # BUY, SELL, HOLD
        self.strength = strength  # weak, normal, strong
        self.price = price
        self.reason = reason  # 신호 발생 이유
        self.timestamp = datetime.now()
        self.data = data or {}  # 추가 데이터 (지표값 등)
    
    def to_dict(self) -> Dict[str, Any]:
        """딕셔너리로 변환"""
        return {
            'action': self.action,
            'strength': self.strength,
            'price': self.price,
            'reason': self.reason,
            'timestamp': self.timestamp.isoformat(),
            'data': self.data
        }
    
    def __str__(self):
        return f"{self.action} signal at ${self.price:.4f} ({self.strength}) - {self.reason}"

class BaseStrategy(ABC):
    """기본 전략 추상 클래스"""
    
    def __init__(self, config):
        self.config = config
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        
        # 전략 상태
        self.last_signal = None
        self.last_action = TradingSignal.HOLD
        self.signal_history = []
        
        # 지표 계산용 데이터 저장
        self.price_data = pd.DataFrame()
        self.indicators = {}
        
    @abstractmethod
    def calculate_indicators(self, df: pd.DataFrame) -> Dict[str, Any]:
        """기술적 지표 계산 (추상 메서드)"""
        pass
    
    @abstractmethod
    def generate_signal(self, df: pd.DataFrame) -> TradingSignal:
        """트레이딩 신호 생성 (추상 메서드)"""
        pass
    
    def update_data(self, df: pd.DataFrame):
        """가격 데이터 업데이트"""
        try:
            # 데이터 검증
            if df is None or len(df) == 0:
                self.logger.warning("빈 데이터프레임이 전달되었습니다")
                return
            
            required_columns = ['open', 'high', 'low', 'close', 'volume']
            if not all(col in df.columns for col in required_columns):
                self.logger.error(f"필수 컬럼이 없습니다: {required_columns}")
                return
            
            # 가격 데이터 저장 (최근 200개만 유지)
            self.price_data = df.tail(200).copy()
            
            # 지표 계산
            self.indicators = self.calculate_indicators(self.price_data)
            
            self.logger.debug(f"데이터 업데이트 완료: {len(self.price_data)}개 캔들")
            
        except Exception as e:
            self.logger.error(f"데이터 업데이트 오류: {e}")
    
    def get_signal(self, df: pd.DataFrame = None) -> TradingSignal:
        """트레이딩 신호 가져오기"""
        try:
            # 새로운 데이터가 있으면 업데이트
            if df is not None:
                self.update_data(df)
            
            # 충분한 데이터가 있는지 확인
            min_data_length = max(self.config.short_ma_period, self.config.long_ma_period) + 5
            if len(self.price_data) < min_data_length:
                return TradingSignal(
                    TradingSignal.HOLD, 
                    "normal", 
                    self.price_data['close'].iloc[-1] if len(self.price_data) > 0 else 0,
                    f"데이터 부족 (필요: {min_data_length}, 현재: {len(self.price_data)})"
                )
            
            # 신호 생성
            signal = self.generate_signal(self.price_data)
            
            # 신호 기록
            self.last_signal = signal
            self.signal_history.append(signal)
            
            # 최근 50개 신호만 유지
            if len(self.signal_history) > 50:
                self.signal_history = self.signal_history[-50:]
            
            self.logger.info(f"신호 생성: {signal}")
            return signal
            
        except Exception as e:
            self.logger.error(f"신호 생성 오류: {e}")
            return TradingSignal(
                TradingSignal.HOLD,
                "normal",
                self.price_data['close'].iloc[-1] if len(self.price_data) > 0 else 0,
                f"신호 생성 오류: {str(e)}"
            )
    
    def calculate_signal_strength(self, ma_diff_pct: float, volume_ratio: float) -> str:
        """신호 강도 계산"""
        try:
            # MA 간격 기준 (백분율)
            ma_strength = abs(ma_diff_pct)
            
            # 거래량 기준
            volume_strength = volume_ratio
            
            # 복합 점수 계산
            if ma_strength > 2.0 and volume_strength > 1.5:
                return "strong"
            elif ma_strength > 1.0 and volume_strength > 1.2:
                return "normal"
            else:
                return "weak"
                
        except Exception as e:
            self.logger.error(f"신호 강도 계산 오류: {e}")
            return "normal"
    
    def should_filter_signal(self, signal: TradingSignal) -> Tuple[bool, str]:
        """신호 필터링 검사 - 테스트용 완화"""
        try:
            # 🚀 테스트용: RSI 필터 완전 제거
            # 원래는 RSI 극값에서 신호 차단했지만 테스트용으로 제거
            
            # 🚀 테스트용: 거래량 필터 완화 (거의 모든 거래량 허용)
            if hasattr(self.config, 'use_volume_filter') and self.config.use_volume_filter:
                volume_ratio = self.indicators.get('volume_ratio', 1.0)
                if volume_ratio < 0.1:  # 극도로 낮은 거래량만 차단
                    return True, f"극도로 낮은 거래량: {volume_ratio:.2f}x"
            
            # 🚀 테스트용: 연속 신호 필터 완화 (5초 이상 간격이면 허용)
            if (self.last_signal and 
                signal.action != TradingSignal.HOLD and 
                signal.action == self.last_signal.action):
                
                # 최근 신호와의 시간 간격 확인
                time_diff = (signal.timestamp - self.last_signal.timestamp).total_seconds()
                if time_diff < 10:  # 10초 이내 연속 신호만 차단
                    return True, f"연속 {signal.action} 신호 방지 (간격: {time_diff:.1f}초)"
            
            return False, "필터 통과 (완화된 조건)"
            
        except Exception as e:
            self.logger.error(f"신고 필터링 오류: {e}")
            return False, f"필터링 오류로 인한 통과: {str(e)}"  # 오류 시 통과
    
    def get_strategy_info(self) -> Dict[str, Any]:
        """전략 정보 반환"""
        return {
            'name': self.__class__.__name__,
            'config': self.config.to_dict(),
            'last_signal': self.last_signal.to_dict() if self.last_signal else None,
            'indicators': self.indicators,
            'data_length': len(self.price_data),
            'signal_count': len(self.signal_history)
        }
    
    def reset(self):
        """전략 상태 초기화"""
        self.last_signal = None
        self.last_action = TradingSignal.HOLD
        self.signal_history = []
        self.price_data = pd.DataFrame()
        self.indicators = {}
        self.logger.info("전략 상태가 초기화되었습니다")
