# futures_simulator.py - 선물거래 시뮬레이터 (API 권한 없을 때 사용)
import logging
from datetime import datetime
import json
import os

class FuturesSimulator:
    """선물거래 시뮬레이터 - API 권한 없을 때 사용"""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.positions = {}  # 심볼별 포지션 저장
        self.balance = 10000.0  # 시작 잔고 (USDT)
        self.data_file = 'data/futures_positions.json'
        self.load_positions()
        
    def load_positions(self):
        """저장된 포지션 불러오기"""
        try:
            if os.path.exists(self.data_file):
                with open(self.data_file, 'r') as f:
                    data = json.load(f)
                    self.positions = data.get('positions', {})
                    self.balance = data.get('balance', 10000.0)
        except Exception as e:
            self.logger.error(f"포지션 로드 오류: {e}")
            
    def save_positions(self):
        """포지션 저장"""
        try:
            os.makedirs(os.path.dirname(self.data_file), exist_ok=True)
            data = {
                'positions': self.positions,
                'balance': self.balance,
                'last_updated': datetime.now().isoformat()
            }
            with open(self.data_file, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            self.logger.error(f"포지션 저장 오류: {e}")
            
    def get_futures_balance(self):
        """시뮬레이션 잔고 조회"""
        return {
            'balance': self.balance,
            'available': self.balance,
            'crossWalletBalance': self.balance
        }
        
    def set_leverage(self, symbol, leverage):
        """레버리지 설정 (시뮬레이션)"""
        self.logger.info(f"시뮬레이션: {symbol} 레버리지 {leverage}x 설정")
        return True, f"{symbol} 레버리지 {leverage}x 설정 완료 (시뮬레이션)"
        
    def get_position_info(self, symbol):
        """포지션 정보 조회 (시뮬레이션)"""
        if symbol not in self.positions:
            return {
                'symbol': symbol,
                'size': 0,
                'entry_price': 0,
                'mark_price': 0,
                'unrealized_pnl': 0,
                'percentage': 0,
                'side': 'NONE'
            }
            
        pos = self.positions[symbol]
        return {
            'symbol': symbol,
            'size': pos['size'],
            'entry_price': pos['entry_price'],
            'mark_price': pos.get('mark_price', pos['entry_price']),
            'unrealized_pnl': pos.get('unrealized_pnl', 0),
            'percentage': pos.get('percentage', 0),
            'side': 'LONG' if pos['size'] > 0 else 'SHORT' if pos['size'] < 0 else 'NONE'
        }
        
    def create_futures_order(self, symbol, side, quantity, order_type='MARKET', price=None, leverage=None):
        """선물 주문 실행 (시뮬레이션)"""
        try:
            # 현재 포지션 확인
            current_pos = self.get_position_info(symbol)
            
            # 새로운 포지션 계산
            if side == 'BUY':
                new_size = current_pos['size'] + quantity
            else:  # SELL
                new_size = current_pos['size'] - quantity
                
            # 포지션 업데이트
            if symbol not in self.positions:
                self.positions[symbol] = {}
                
            self.positions[symbol] = {
                'size': new_size,
                'entry_price': price if price else 50000,  # 임시 가격
                'leverage': leverage if leverage else 1,
                'timestamp': datetime.now().isoformat()
            }
            
            # 저장
            self.save_positions()
            
            result = {
                'symbol': symbol,
                'side': side,
                'type': order_type,
                'quantity': quantity,
                'status': 'FILLED (시뮬레이션)'
            }
            
            self.logger.info(f"시뮬레이션 선물 주문: {symbol} {side} {quantity}")
            return True, result
            
        except Exception as e:
            error_msg = f"시뮬레이션 주문 실패: {e}"
            self.logger.error(error_msg)
            return False, error_msg
            
    def close_position(self, symbol):
        """포지션 청산 (시뮬레이션)"""
        try:
            if symbol in self.positions:
                del self.positions[symbol]
                self.save_positions()
                return True, f"{symbol} 포지션 청산 완료 (시뮬레이션)"
            else:
                return False, "청산할 포지션이 없습니다"
                
        except Exception as e:
            error_msg = f"포지션 청산 중 오류: {e}"
            self.logger.error(error_msg)
            return False, error_msg
            
    def update_position_pnl(self, symbol, current_price):
        """포지션 PnL 업데이트"""
        if symbol in self.positions:
            pos = self.positions[symbol]
            entry_price = pos['entry_price']
            size = pos['size']
            
            if size != 0:
                # PnL 계산
                if size > 0:  # LONG
                    pnl = (current_price - entry_price) * abs(size)
                else:  # SHORT
                    pnl = (entry_price - current_price) * abs(size)
                    
                percentage = (pnl / (entry_price * abs(size))) * 100
                
                self.positions[symbol]['mark_price'] = current_price
                self.positions[symbol]['unrealized_pnl'] = pnl
                self.positions[symbol]['percentage'] = percentage
                
                self.save_positions()
