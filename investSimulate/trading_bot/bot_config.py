# bot_config.py - 트레이딩봇 설정
import json
import os
from datetime import datetime
from dataclasses import dataclass
from typing import Dict, Any

@dataclass
class BotConfig:
    """트레이딩봇 설정 클래스"""
    
    # 봇 기본 설정
    bot_name: str = "MA Cross Bot"
    strategy_name: str = "ma_cross"
    is_active: bool = False
    
    # 거래 설정
    symbol: str = "BTCUSDT"
    base_amount: float = 200.0  # 기본 거래 금액 (USD) - 500에서 200으로 조정
    trading_mode: str = "spot"  # "spot" 또는 "cross"
    
    # 이동평균 설정
    short_ma_period: int = 3    # 단기 이동평균 (5에서 3으로 단축 - 더 민감하게)
    long_ma_period: int = 10    # 장기 이동평균 (20에서 10으로 단축 - 더 빠른 반응)
    signal_timeframe: str = "1m"  # 신호 확인 시간대 (5m에서 1m으로 단축)
    
    # 신호 강도 설정
    signal_strength_multiplier: Dict[str, float] = None
    volume_threshold: float = 1.2  # 평균 거래량 대비 배율
    
    # 리스크 관리
    max_consecutive_losses: int = 10  # 5에서 10으로 증가 (더 많은 연속 손실 허용)
    daily_loss_limit: float = 5000.0  # 일일 최대 손실 한도 (2000에서 5000으로 증가)
    max_positions: int = 10  # 최대 동시 포지션 수 (5에서 10으로 증가)
    
    # 필터 설정
    rsi_min: float = 20.0  # RSI 최소값
    rsi_max: float = 80.0  # RSI 최대값
    use_volume_filter: bool = True
    use_rsi_filter: bool = True
    
    def __post_init__(self):
        """초기화 후 기본값 설정"""
        if self.signal_strength_multiplier is None:
            self.signal_strength_multiplier = {
                "weak": 0.5,     # 약한 신호 ($100)
                "normal": 1.0,   # 보통 신호 ($200)
                "strong": 1.5    # 강한 신호 ($300)
            }
    
    def to_dict(self) -> Dict[str, Any]:
        """딕셔너리로 변환"""
        return {
            'bot_name': self.bot_name,
            'strategy_name': self.strategy_name,
            'is_active': self.is_active,
            'symbol': self.symbol,
            'base_amount': self.base_amount,
            'trading_mode': self.trading_mode,
            'short_ma_period': self.short_ma_period,
            'long_ma_period': self.long_ma_period,
            'signal_timeframe': self.signal_timeframe,
            'signal_strength_multiplier': self.signal_strength_multiplier,
            'volume_threshold': self.volume_threshold,
            'max_consecutive_losses': self.max_consecutive_losses,
            'daily_loss_limit': self.daily_loss_limit,
            'max_positions': self.max_positions,
            'rsi_min': self.rsi_min,
            'rsi_max': self.rsi_max,
            'use_volume_filter': self.use_volume_filter,
            'use_rsi_filter': self.use_rsi_filter
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'BotConfig':
        """딕셔너리에서 생성"""
        return cls(**data)
    
    def save_to_file(self, filepath: str = None):
        """설정을 파일로 저장"""
        if filepath is None:
            os.makedirs("data/bot_configs", exist_ok=True)
            filepath = f"data/bot_configs/{self.bot_name.lower().replace(' ', '_')}_config.json"
        
        config_data = self.to_dict()
        config_data['last_updated'] = datetime.now().isoformat()
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(config_data, f, indent=2, ensure_ascii=False)
    
    @classmethod
    def load_from_file(cls, filepath: str) -> 'BotConfig':
        """파일에서 설정 로드"""
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # last_updated 제거 (클래스 필드가 아니므로)
        data.pop('last_updated', None)
        
        return cls.from_dict(data)
    
    def get_signal_amount(self, strength: str) -> float:
        """신호 강도에 따른 거래 금액 계산"""
        multiplier = self.signal_strength_multiplier.get(strength, 1.0)
        return self.base_amount * multiplier
    
    def validate(self) -> tuple[bool, str]:
        """설정 검증"""
        if self.short_ma_period >= self.long_ma_period:
            return False, "단기 이동평균 기간이 장기 이동평균 기간보다 작아야 합니다"
        
        if self.base_amount <= 0:
            return False, "기본 거래 금액은 0보다 커야 합니다"
        
        if self.max_consecutive_losses <= 0:
            return False, "최대 연속 손실 횟수는 0보다 커야 합니다"
        
        if self.daily_loss_limit <= 0:
            return False, "일일 손실 한도는 0보다 커야 합니다"
        
        if not (0 <= self.rsi_min < self.rsi_max <= 100):
            return False, "RSI 범위가 올바르지 않습니다 (0 <= min < max <= 100)"
        
        return True, "설정이 올바릅니다"

class BotStatus:
    """봇 상태 관리 클래스"""
    
    STOPPED = "stopped"
    RUNNING = "running"
    PAUSED = "paused"
    ERROR = "error"
    
    def __init__(self):
        self.status = self.STOPPED
        self.start_time = None
        self.last_signal_time = None
        self.consecutive_losses = 0
        self.daily_pnl = 0.0
        self.total_trades = 0
        self.successful_trades = 0
        self.error_message = ""
    
    def start(self):
        """봇 시작"""
        self.status = self.RUNNING
        self.start_time = datetime.now()
        self.error_message = ""
    
    def stop(self):
        """봇 정지"""
        self.status = self.STOPPED
        self.start_time = None
    
    def pause(self, reason: str = ""):
        """봇 일시정지"""
        self.status = self.PAUSED
        self.error_message = reason
    
    def set_error(self, error_msg: str):
        """에러 상태 설정"""
        self.status = self.ERROR
        self.error_message = error_msg
    
    def add_trade_result(self, pnl: float):
        """거래 결과 추가"""
        self.total_trades += 1
        self.daily_pnl += pnl
        
        if pnl > 0:
            self.successful_trades += 1
            self.consecutive_losses = 0
        else:
            self.consecutive_losses += 1
    
    def get_success_rate(self) -> float:
        """성공률 계산"""
        if self.total_trades == 0:
            return 0.0
        return (self.successful_trades / self.total_trades) * 100
    
    def get_status_info(self) -> dict:
        """상태 정보 반환"""
        return {
            'status': self.status,
            'start_time': self.start_time.isoformat() if self.start_time else None,
            'last_signal_time': self.last_signal_time.isoformat() if self.last_signal_time else None,
            'consecutive_losses': self.consecutive_losses,
            'daily_pnl': self.daily_pnl,
            'total_trades': self.total_trades,
            'successful_trades': self.successful_trades,
            'success_rate': self.get_success_rate(),
            'error_message': self.error_message
        }
