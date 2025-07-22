# trading_bot package
"""
자동 트레이딩 봇 패키지

주요 구성요소:
- bot_engine: 봇 메인 엔진
- strategies: 트레이딩 전략들
- indicators: 기술적 지표 계산
- risk_manager: 리스크 관리
- bot_config: 봇 설정
"""

from .bot_engine import TradingBot
from .bot_config import BotConfig
from .risk_manager import RiskManager

__version__ = "1.0.0"
__author__ = "Genius Trading Team"

__all__ = [
    'TradingBot',
    'BotConfig', 
    'RiskManager'
]
