# risk_manager.py - 리스크 관리 시스템
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Tuple
from dataclasses import dataclass

@dataclass
class TradeResult:
    """거래 결과 클래스"""
    timestamp: datetime
    symbol: str
    action: str  # BUY, SELL
    amount: float
    price: float
    pnl: float
    success: bool
    strategy: str

class RiskManager:
    """리스크 관리 시스템"""
    
    def __init__(self, config):
        self.config = config
        self.logger = logging.getLogger(__name__)
        
        # 거래 결과 기록
        self.trade_history: List[TradeResult] = []
        
        # 일일 통계
        self.daily_pnl = 0.0
        self.daily_trades = 0
        self.consecutive_losses = 0
        self.last_reset_date = datetime.now().date()
        
        # 포지션 관리
        self.current_positions = 0
        self.position_symbols = set()
        
        self.logger.info("리스크 관리자 초기화 완료")
    
    def check_trading_allowed(self, symbol: str, action: str, amount: float) -> Tuple[bool, str]:
        """거래 허용 여부 확인"""
        try:
            # 일일 리셋 확인
            self._check_daily_reset()
            
            # 1. 일일 손실 한도 확인
            if self.daily_pnl <= -self.config.daily_loss_limit:
                return False, f"일일 손실 한도 초과 (${abs(self.daily_pnl):.2f} / ${self.config.daily_loss_limit:.2f})"
            
            # 2. 연속 손실 확인
            if self.consecutive_losses >= self.config.max_consecutive_losses:
                return False, f"연속 손실 한도 초과 ({self.consecutive_losses} / {self.config.max_consecutive_losses}회)"
            
            # 3. 최대 포지션 수 확인
            if action == "BUY" and self.current_positions >= self.config.max_positions:
                return False, f"최대 포지션 수 초과 ({self.current_positions} / {self.config.max_positions}개)"
            
            # 4. 동일 심볼 중복 확인 - 완화된 조건
            if action == "BUY":
                current_quantity = 0
                try:
                    # 현재 보유량 확인
                    if hasattr(self.config, 'trading_engine'):
                        current_quantity = self.config.trading_engine.portfolio.get_holding_quantity(symbol)
                    elif hasattr(self.config, '_trading_engine'):
                        current_quantity = self.config._trading_engine.portfolio.get_holding_quantity(symbol)
                except:
                    pass
                
                # 보유량이 너무 많으면 추가 매수 제한
                max_position_value = 200000  # $200,000 한도 (50,000에서 증가)
                current_value = current_quantity * 200  # 대략적인 현재 가치 (SOL $200 가정)
                
                if current_value > max_position_value:
                    return False, f"{symbol} 최대 포지션 한도 초과 (현재: ${current_value:.0f} / 한도: ${max_position_value})"
                
                # 기존 중복 체크 제거 - 추가 매수 허용
                self.logger.info(f"💰 {symbol} 추가 매수 허용: 현재 보유량 {current_quantity:.6f}")
            
            # 5. 매도할 포지션 확인 - 실제 보유량 우선 확인
            if action == "SELL":
                # 실제 보유량으로 먼저 확인 (더 정확함)
                has_position = symbol in self.position_symbols
                actual_quantity = 0
                
                try:
                    # config 객체를 통해 trading_engine 접근 시도
                    if hasattr(self.config, 'trading_engine'):
                        actual_quantity = self.config.trading_engine.portfolio.get_holding_quantity(symbol)
                    elif hasattr(self.config, '_trading_engine'):
                        actual_quantity = self.config._trading_engine.portfolio.get_holding_quantity(symbol)
                except:
                    pass
                
                # 실제 보유량이 있으면 포지션 추가 (동기화)
                if actual_quantity > 0:
                    self.position_symbols.add(symbol)
                    self.current_positions = len(self.position_symbols)
                    self.logger.info(f"🔄 {symbol} 포지션 동기화: 실제 보유량 {actual_quantity:.6f}")
                elif not has_position and actual_quantity <= 0:
                    return False, f"{symbol} 매도할 포지션이 없습니다 (보유량: {actual_quantity})"
            
            # 6. 거래 금액 검증
            if amount <= 0:
                return False, f"유효하지 않은 거래 금액: ${amount:.2f}"
            
            # 7. 최소/최대 거래 금액 확인
            min_amount = 10.0  # 최소 $10
            max_amount = 2000.0  # 고정된 최대 거래 금액 $2000 (하드코딩된 제한)
            
            if amount < min_amount:
                return False, f"최소 거래 금액 미달 (${amount:.2f} < ${min_amount:.2f})"
            
            if amount > max_amount:
                return False, f"최대 거래 금액 초과 (${amount:.2f} > ${max_amount:.2f})"
            
            return True, "거래 허용"
            
        except Exception as e:
            self.logger.error(f"리스크 확인 오류: {e}")
            return False, f"리스크 확인 실패: {str(e)}"
    
    def calculate_position_size(self, signal_strength: str, base_amount: float) -> float:
        """신호 강도에 따른 포지션 크기 계산"""
        try:
            multiplier = self.config.signal_strength_multiplier.get(signal_strength, 1.0)
            calculated_amount = base_amount * multiplier
            
            # 연속 손실이 있으면 포지션 크기 감소
            if self.consecutive_losses > 0:
                reduction_factor = 0.8 ** self.consecutive_losses  # 20%씩 감소
                calculated_amount *= reduction_factor
                self.logger.info(f"연속 손실로 인한 포지션 크기 감소: {multiplier:.1f}x → {reduction_factor:.2f}x")
            
            # 일일 손실이 있으면 보수적으로 조정
            if self.daily_pnl < 0:
                loss_ratio = abs(self.daily_pnl) / self.config.daily_loss_limit
                if loss_ratio > 0.5:  # 50% 이상 손실시
                    calculated_amount *= 0.7  # 30% 감소
                    self.logger.info(f"일일 손실로 인한 포지션 크기 감소: 70%로 조정")
            
            return round(calculated_amount, 2)
            
        except Exception as e:
            self.logger.error(f"포지션 크기 계산 오류: {e}")
            return base_amount
    
    def record_trade(self, symbol: str, action: str, amount: float, price: float, 
                    pnl: float = 0.0, strategy: str = "unknown") -> None:
        """거래 결과 기록"""
        try:
            success = pnl >= 0
            
            trade_result = TradeResult(
                timestamp=datetime.now(),
                symbol=symbol,
                action=action,
                amount=amount,
                price=price,
                pnl=pnl,
                success=success,
                strategy=strategy
            )
            
            self.trade_history.append(trade_result)
            
            # 일일 통계 업데이트
            self.daily_pnl += pnl
            self.daily_trades += 1
            
            # 포지션 관리
            if action == "BUY":
                self.current_positions += 1
                self.position_symbols.add(symbol)
            elif action == "SELL":
                self.current_positions = max(0, self.current_positions - 1)
                self.position_symbols.discard(symbol)
            
            # 연속 손실 카운트
            if success:
                self.consecutive_losses = 0
            else:
                self.consecutive_losses += 1
            
            # 거래 내역 제한 (최근 1000개만 유지)
            if len(self.trade_history) > 1000:
                self.trade_history = self.trade_history[-1000:]
            
            self.logger.info(f"거래 기록: {action} {symbol} ${amount:.2f} @${price:.4f} PnL:${pnl:+.2f}")
            
        except Exception as e:
            self.logger.error(f"거래 기록 오류: {e}")
    
    def _check_daily_reset(self):
        """일일 통계 리셋 확인"""
        today = datetime.now().date()
        if today > self.last_reset_date:
            self.logger.info(f"일일 통계 리셋: {self.last_reset_date} → {today}")
            self.daily_pnl = 0.0
            self.daily_trades = 0
            self.last_reset_date = today
    
    def get_risk_metrics(self) -> Dict[str, Any]:
        """리스크 지표 반환"""
        try:
            self._check_daily_reset()
            
            # 최근 거래 분석 (지난 24시간)
            recent_trades = [
                trade for trade in self.trade_history
                if trade.timestamp > datetime.now() - timedelta(hours=24)
            ]
            
            # 성공률 계산
            if recent_trades:
                successful_trades = sum(1 for trade in recent_trades if trade.success)
                success_rate = (successful_trades / len(recent_trades)) * 100
            else:
                success_rate = 0.0
            
            # 평균 수익/손실
            if recent_trades:
                total_pnl = sum(trade.pnl for trade in recent_trades)
                avg_pnl = total_pnl / len(recent_trades)
            else:
                total_pnl = 0.0
                avg_pnl = 0.0
            
            # 최대 연속 손실 계산
            max_consecutive_losses = 0
            current_consecutive = 0
            for trade in reversed(self.trade_history[-50:]):  # 최근 50개 거래
                if not trade.success:
                    current_consecutive += 1
                    max_consecutive_losses = max(max_consecutive_losses, current_consecutive)
                else:
                    current_consecutive = 0
            
            return {
                'daily_pnl': self.daily_pnl,
                'daily_trades': self.daily_trades,
                'consecutive_losses': self.consecutive_losses,
                'current_positions': self.current_positions,
                'position_symbols': list(self.position_symbols),
                'success_rate_24h': success_rate,
                'avg_pnl_24h': avg_pnl,
                'total_pnl_24h': total_pnl,
                'max_consecutive_losses': max_consecutive_losses,
                'daily_loss_limit': self.config.daily_loss_limit,
                'daily_loss_ratio': abs(self.daily_pnl) / self.config.daily_loss_limit if self.daily_pnl < 0 else 0,
                'risk_level': self._calculate_risk_level()
            }
            
        except Exception as e:
            self.logger.error(f"리스크 지표 계산 오류: {e}")
            return {}
    
    def _calculate_risk_level(self) -> str:
        """현재 리스크 레벨 계산"""
        try:
            risk_score = 0
            
            # 일일 손실 비율
            if self.daily_pnl < 0:
                loss_ratio = abs(self.daily_pnl) / self.config.daily_loss_limit
                if loss_ratio > 0.8:
                    risk_score += 3
                elif loss_ratio > 0.5:
                    risk_score += 2
                elif loss_ratio > 0.3:
                    risk_score += 1
            
            # 연속 손실
            if self.consecutive_losses >= self.config.max_consecutive_losses - 1:
                risk_score += 3
            elif self.consecutive_losses >= self.config.max_consecutive_losses // 2:
                risk_score += 2
            elif self.consecutive_losses > 0:
                risk_score += 1
            
            # 포지션 수
            if self.current_positions >= self.config.max_positions:
                risk_score += 2
            elif self.current_positions >= self.config.max_positions // 2:
                risk_score += 1
            
            # 리스크 레벨 결정
            if risk_score >= 6:
                return "HIGH"
            elif risk_score >= 3:
                return "MEDIUM"
            elif risk_score >= 1:
                return "LOW"
            else:
                return "SAFE"
                
        except Exception as e:
            self.logger.error(f"리스크 레벨 계산 오류: {e}")
            return "UNKNOWN"
    
    def should_pause_trading(self) -> Tuple[bool, str]:
        """거래 일시정지 여부 확인"""
        try:
            risk_level = self._calculate_risk_level()
            
            if risk_level == "HIGH":
                return True, "리스크 레벨이 높음 - 거래 일시정지"
            
            if self.consecutive_losses >= self.config.max_consecutive_losses:
                return True, f"연속 손실 한도 초과 ({self.consecutive_losses}회)"
            
            if self.daily_pnl <= -self.config.daily_loss_limit:
                return True, f"일일 손실 한도 초과 (${abs(self.daily_pnl):.2f})"
            
            return False, "정상 거래 가능"
            
        except Exception as e:
            self.logger.error(f"거래 일시정지 확인 오류: {e}")
            return True, f"확인 실패: {str(e)}"
    
    def reset_daily_stats(self):
        """일일 통계 수동 리셋"""
        self.daily_pnl = 0.0
        self.daily_trades = 0
        self.last_reset_date = datetime.now().date()
        self.logger.info("일일 통계가 수동으로 리셋되었습니다")
    
    def reset_consecutive_losses(self):
        """연속 손실 카운트 리셋"""
        old_count = self.consecutive_losses
        self.consecutive_losses = 0
        self.logger.info(f"연속 손실 카운트 리셋: {old_count} → 0")
    
    def get_trade_history(self, limit: int = 50) -> List[Dict[str, Any]]:
        """거래 내역 반환"""
        try:
            recent_trades = self.trade_history[-limit:] if len(self.trade_history) > limit else self.trade_history
            
            return [
                {
                    'timestamp': trade.timestamp.isoformat(),
                    'symbol': trade.symbol,
                    'action': trade.action,
                    'amount': trade.amount,
                    'price': trade.price,
                    'pnl': trade.pnl,
                    'success': trade.success,
                    'strategy': trade.strategy
                }
                for trade in reversed(recent_trades)  # 최신순
            ]
            
        except Exception as e:
            self.logger.error(f"거래 내역 조회 오류: {e}")
            return []
