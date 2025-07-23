# indicators.py - 기술적 지표 계산 모듈
import pandas as pd
import numpy as np
import logging
from typing import Dict, Any, Optional

class TechnicalIndicators:
    """기술적 지표 계산 클래스"""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
    
    @staticmethod
    def moving_average(data: pd.Series, period: int, ma_type: str = "simple") -> pd.Series:
        """이동평균 계산
        
        Args:
            data: 가격 데이터 (close price)
            period: 기간
            ma_type: "simple", "exponential", "weighted"
        """
        try:
            if ma_type == "simple":
                return data.rolling(window=period).mean()
            elif ma_type == "exponential":
                return data.ewm(span=period).mean()
            elif ma_type == "weighted":
                weights = np.arange(1, period + 1)
                return data.rolling(window=period).apply(
                    lambda x: np.dot(x, weights) / weights.sum(), raw=True
                )
            else:
                raise ValueError(f"지원하지 않는 이동평균 타입: {ma_type}")
                
        except Exception as e:
            logging.error(f"이동평균 계산 오류: {e}")
            return pd.Series(index=data.index, dtype=float)
    
    @staticmethod
    def rsi(data: pd.Series, period: int = 14) -> pd.Series:
        """RSI (Relative Strength Index) 계산"""
        try:
            delta = data.diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
            
            rs = gain / loss
            rsi = 100 - (100 / (1 + rs))
            
            return rsi
            
        except Exception as e:
            logging.error(f"RSI 계산 오류: {e}")
            return pd.Series(index=data.index, dtype=float)
    
    @staticmethod
    def bollinger_bands(data: pd.Series, period: int = 20, std_dev: float = 2.0) -> Dict[str, pd.Series]:
        """볼린저 밴드 계산"""
        try:
            sma = data.rolling(window=period).mean()
            std = data.rolling(window=period).std()
            
            upper_band = sma + (std * std_dev)
            lower_band = sma - (std * std_dev)
            
            return {
                'upper': upper_band,
                'middle': sma,
                'lower': lower_band,
                'width': upper_band - lower_band,
                'percent_b': (data - lower_band) / (upper_band - lower_band)
            }
            
        except Exception as e:
            logging.error(f"볼린저 밴드 계산 오류: {e}")
            return {}
    
    @staticmethod
    def volume_analysis(volume: pd.Series, price: pd.Series, period: int = 20) -> Dict[str, Any]:
        """거래량 분석"""
        try:
            volume_ma = volume.rolling(window=period).mean()
            current_volume = volume.iloc[-1]
            avg_volume = volume_ma.iloc[-1]
            
            volume_ratio = current_volume / avg_volume if avg_volume > 0 else 1.0
            
            # 가격 변화와 거래량 관계
            price_change = price.pct_change()
            volume_weighted_price = (price * volume).rolling(window=period).sum() / volume.rolling(window=period).sum()
            
            return {
                'volume_ratio': volume_ratio,
                'avg_volume': avg_volume,
                'current_volume': current_volume,
                'volume_ma': volume_ma,
                'volume_weighted_price': volume_weighted_price.iloc[-1] if len(volume_weighted_price) > 0 else price.iloc[-1],
                'volume_trend': 'increasing' if volume_ratio > 1.2 else 'decreasing' if volume_ratio < 0.8 else 'stable'
            }
            
        except Exception as e:
            logging.error(f"거래량 분석 오류: {e}")
            return {}
    
    @classmethod
    def calculate_all_indicators(cls, df: pd.DataFrame, config: Dict[str, Any] = None) -> Dict[str, Any]:
        """모든 지표를 한 번에 계산"""
        try:
            indicators = {}
            
            # 기본 설정값
            if config is None:
                config = {
                    'short_ma_period': 5,
                    'long_ma_period': 20,
                    'rsi_period': 14,
                    'bb_period': 20,
                    'bb_std': 2.0,
                    'volume_period': 20
                }
            
            required_columns = ['open', 'high', 'low', 'close', 'volume']
            if not all(col in df.columns for col in required_columns):
                raise ValueError(f"필수 컬럼 누락: {required_columns}")
            
            close = df['close']
            high = df['high']
            low = df['low']
            volume = df['volume']
            
            # 이동평균들
            indicators['short_ma'] = cls.moving_average(close, config['short_ma_period'])
            indicators['long_ma'] = cls.moving_average(close, config['long_ma_period'])
            
            # RSI
            indicators['rsi'] = cls.rsi(close, config['rsi_period'])
            
            # 거래량 분석
            volume_info = cls.volume_analysis(volume, close, config['volume_period'])
            indicators.update({f'volume_{k}': v for k, v in volume_info.items() if isinstance(v, (pd.Series, float, int))})
            
            # 추가 계산된 지표들
            if len(indicators['short_ma']) > 0 and len(indicators['long_ma']) > 0:
                # MA 교차 상태
                indicators['ma_cross'] = indicators['short_ma'] > indicators['long_ma']
                
                # MA 간격 (백분율)
                indicators['ma_diff_pct'] = ((indicators['short_ma'] - indicators['long_ma']) / indicators['long_ma']) * 100
            
            logging.info(f"기술적 지표 계산 완료: {len(indicators)}개 지표")
            return indicators
            
        except Exception as e:
            logging.error(f"전체 지표 계산 오류: {e}")
            return {}
    
    @staticmethod
    def get_latest_values(indicators: Dict[str, Any]) -> Dict[str, float]:
        """각 지표의 최신값만 추출"""
        try:
            latest_values = {}
            
            for key, value in indicators.items():
                if isinstance(value, pd.Series) and len(value) > 0:
                    latest_values[key] = value.iloc[-1]
                elif isinstance(value, (int, float)):
                    latest_values[key] = value
                elif isinstance(value, list) and len(value) > 0:
                    latest_values[key] = value[-1] if isinstance(value[-1], (int, float)) else str(value)
                else:
                    latest_values[key] = str(value)
            
            return latest_values
            
        except Exception as e:
            logging.error(f"최신값 추출 오류: {e}")
            return {}
