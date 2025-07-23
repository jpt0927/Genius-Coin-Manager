# liquidation_manager.py - 자동 청산 관리자
import logging
from datetime import datetime
from config import Config

class LiquidationManager:
    """자동 청산 관리자"""
    
    def __init__(self, cross_position_manager):
        self.cross_position_manager = cross_position_manager
        self.logger = logging.getLogger(__name__)
        
        # 청산 임계값 설정
        self.liquidation_threshold = -80.0  # -80% 손실시 청산
        self.margin_call_threshold = -50.0  # -50% 손실시 마진콜 경고
        
    def check_liquidation_conditions(self, current_prices):
        """청산 조건 확인 및 실행"""
        try:
            liquidated_positions = []
            margin_calls = []
            
            for position in self.cross_position_manager.cross_data['positions']:
                symbol = position['symbol']
                current_price = current_prices.get(symbol, 0)
                
                if current_price <= 0:
                    continue
                    
                # 현재 손익률 계산
                unrealized_pnl = self.cross_position_manager.calculate_unrealized_pnl(position, current_price)
                margin_used = position['margin_used']
                pnl_percentage = (unrealized_pnl / margin_used) * 100 if margin_used > 0 else 0
                
                # 청산 조건 확인
                if pnl_percentage <= self.liquidation_threshold:
                    # 자동 청산 실행
                    success = self._execute_liquidation(position, current_price, pnl_percentage)
                    if success:
                        liquidated_positions.append({
                            'symbol': symbol,
                            'side': position['side'],
                            'pnl_percentage': pnl_percentage,
                            'liquidation_price': current_price
                        })
                        
                elif pnl_percentage <= self.margin_call_threshold:
                    # 마진콜 경고
                    margin_calls.append({
                        'symbol': symbol,
                        'side': position['side'],
                        'pnl_percentage': pnl_percentage,
                        'current_price': current_price
                    })
                    
            return liquidated_positions, margin_calls
            
        except Exception as e:
            self.logger.error(f"청산 조건 확인 오류: {e}")
            return [], []
            
    def _execute_liquidation(self, position, liquidation_price, pnl_percentage):
        """청산 실행"""
        try:
            symbol = position['symbol']
            
            # 강제 청산 실행
            success, message = self.cross_position_manager.close_position(symbol, liquidation_price)
            
            if success:
                # 청산 로그 기록
                liquidation_log = {
                    'type': 'LIQUIDATION',
                    'symbol': symbol,
                    'side': position['side'],
                    'quantity': position['quantity'],
                    'entry_price': position['entry_price'],
                    'liquidation_price': liquidation_price,
                    'leverage': position['leverage'],
                    'pnl_percentage': pnl_percentage,
                    'reason': 'AUTO_LIQUIDATION',
                    'timestamp': datetime.now().isoformat()
                }
                
                self.cross_position_manager.cross_transactions.append(liquidation_log)
                self.cross_position_manager.save_cross_transactions()
                
                self.logger.warning(f"🚨 자동 청산 실행: {symbol} {position['side']} (손실률: {pnl_percentage:.1f}%)")
                return True
            else:
                self.logger.error(f"청산 실행 실패: {symbol} - {message}")
                return False
                
        except Exception as e:
            self.logger.error(f"청산 실행 오류: {e}")
            return False
            
    def calculate_liquidation_price(self, position):
        """청산가격 계산"""
        try:
            entry_price = position['entry_price']
            leverage = position['leverage']
            side = position['side']
            
            # 유지증거금률 (일반적으로 0.4% ~ 5%)
            maintenance_margin_rate = self._get_maintenance_margin_rate(position['symbol'])
            
            if side == 'LONG':
                # 롱 포지션 청산가격
                liquidation_price = entry_price * (1 - (1/leverage) + maintenance_margin_rate)
            else:  # SHORT
                # 숏 포지션 청산가격
                liquidation_price = entry_price * (1 + (1/leverage) - maintenance_margin_rate)
                
            return liquidation_price
            
        except Exception as e:
            self.logger.error(f"청산가격 계산 오류: {e}")
            return 0
            
    def _get_maintenance_margin_rate(self, symbol):
        """심볼별 유지증거금률 조회"""
        # 실제로는 바이낸스 API에서 조회해야 하지만, 
        # 여기서는 일반적인 값들을 사용
        maintenance_rates = {
            'BTCUSDT': 0.004,   # 0.4%
            'ETHUSDT': 0.005,   # 0.5%
            'SOLUSDT': 0.01,    # 1.0%
        }
        
        return maintenance_rates.get(symbol, 0.01)  # 기본값 1%
        
    def get_position_risk_summary(self, current_prices):
        """포지션 위험도 요약"""
        try:
            risk_summary = {
                'high_risk': [],     # 청산 위험 높음
                'medium_risk': [],   # 마진콜 위험
                'low_risk': [],      # 안전
                'total_at_risk': 0.0
            }
            
            for position in self.cross_position_manager.cross_data['positions']:
                symbol = position['symbol']
                current_price = current_prices.get(symbol, 0)
                
                if current_price <= 0:
                    continue
                    
                unrealized_pnl = self.cross_position_manager.calculate_unrealized_pnl(position, current_price)
                margin_used = position['margin_used']
                pnl_percentage = (unrealized_pnl / margin_used) * 100 if margin_used > 0 else 0
                
                position_info = {
                    'symbol': symbol,
                    'side': position['side'],
                    'pnl_percentage': pnl_percentage,
                    'unrealized_pnl': unrealized_pnl,
                    'margin_used': margin_used,
                    'liquidation_price': self.calculate_liquidation_price(position)
                }
                
                if pnl_percentage <= -60.0:
                    risk_summary['high_risk'].append(position_info)
                    risk_summary['total_at_risk'] += abs(unrealized_pnl)
                elif pnl_percentage <= -30.0:
                    risk_summary['medium_risk'].append(position_info)
                else:
                    risk_summary['low_risk'].append(position_info)
                    
            return risk_summary
            
        except Exception as e:
            self.logger.error(f"위험도 요약 계산 오류: {e}")
            return None
