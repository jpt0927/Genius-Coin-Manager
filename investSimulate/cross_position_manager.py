# cross_position_manager.py - Cross 레버리지 포지션 관리
import json
import os
import logging
from datetime import datetime
from config import Config

class CrossPositionManager:
    """Cross 레버리지 포지션 전용 관리자"""
    
    def __init__(self):
        self.positions_file = os.path.join(Config.DATA_DIR, "cross_positions.json")
        self.cross_transactions_file = os.path.join(Config.DATA_DIR, "cross_transactions.json")
        self.logger = logging.getLogger(__name__)
        
        # 데이터 디렉토리 생성
        os.makedirs(Config.DATA_DIR, exist_ok=True)
        
        # Cross 데이터 로드
        self.cross_data = self.load_cross_data()
        self.cross_transactions = self.load_cross_transactions()

    def load_cross_data(self):
        """Cross 포지션 데이터 로드"""
        try:
            if os.path.exists(self.positions_file):
                with open(self.positions_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            else:
                # 초기 Cross 데이터 생성
                initial_data = {
                    'margin_balance': Config.INITIAL_BALANCE * 0.1,  # 초기 증거금 10%
                    'positions': [],  # 현재 포지션들
                    'total_margin_used': 0.0,  # 사용된 증거금
                    'total_unrealized_pnl': 0.0,  # 총 미실현 손익
                    'last_updated': datetime.now().isoformat()
                }
                self.save_cross_data(initial_data)
                return initial_data
        except Exception as e:
            self.logger.error(f"Cross 데이터 로드 오류: {e}")
            return {
                'margin_balance': Config.INITIAL_BALANCE * 0.1,
                'positions': [],
                'total_margin_used': 0.0,
                'total_unrealized_pnl': 0.0,
                'last_updated': datetime.now().isoformat()
            }

    def load_cross_transactions(self):
        """Cross 거래 내역 로드"""
        try:
            if os.path.exists(self.cross_transactions_file):
                with open(self.cross_transactions_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            else:
                return []
        except Exception as e:
            self.logger.error(f"Cross 거래 내역 로드 오류: {e}")
            return []

    def save_cross_data(self, data=None):
        """Cross 데이터 저장"""
        try:
            data_to_save = data if data else self.cross_data
            data_to_save['last_updated'] = datetime.now().isoformat()
            with open(self.positions_file, 'w', encoding='utf-8') as f:
                json.dump(data_to_save, f, indent=2, ensure_ascii=False)
        except Exception as e:
            self.logger.error(f"Cross 데이터 저장 오류: {e}")

    def save_cross_transactions(self):
        """Cross 거래 내역 저장"""
        try:
            with open(self.cross_transactions_file, 'w', encoding='utf-8') as f:
                json.dump(self.cross_transactions, f, indent=2, ensure_ascii=False)
        except Exception as e:
            self.logger.error(f"Cross 거래 내역 저장 오류: {e}")

    def open_position(self, symbol, side, quantity, price, leverage, margin_required):
        """포지션 진입"""
        try:
            # 증거금 충분한지 확인
            available_margin = self.cross_data['margin_balance'] - self.cross_data['total_margin_used']
            if available_margin < margin_required:
                return False, f"증거금 부족 (필요: ${margin_required:.2f}, 사용가능: ${available_margin:.2f})"

            # 기존 포지션 확인 (같은 심볼)
            existing_position = self.find_position(symbol)
            
            if existing_position:
                # 기존 포지션과 같은 방향이면 추가 진입
                if existing_position['side'] == side:
                    self.add_to_position(symbol, quantity, price, margin_required)
                else:
                    # 반대 방향이면 부분 청산 또는 방향 전환
                    return self.reverse_position(symbol, side, quantity, price, leverage, margin_required)
            else:
                # 새로운 포지션 생성
                position = {
                    'symbol': symbol,
                    'side': side,  # 'LONG' or 'SHORT'
                    'quantity': quantity,
                    'entry_price': price,
                    'leverage': leverage,
                    'margin_used': margin_required,
                    'unrealized_pnl': 0.0,
                    'opened_time': datetime.now().isoformat()
                }
                
                self.cross_data['positions'].append(position)
                self.cross_data['total_margin_used'] += margin_required

            # 거래 내역 추가
            transaction = {
                'type': 'OPEN_POSITION',
                'symbol': symbol,
                'side': side,
                'quantity': quantity,
                'price': price,
                'leverage': leverage,
                'margin_used': margin_required,
                'timestamp': datetime.now().isoformat()
            }
            self.cross_transactions.append(transaction)

            # 저장
            self.save_cross_data()
            self.save_cross_transactions()

            self.logger.info(f"포지션 진입: {symbol} {side} {quantity} @{price} ({leverage}x)")
            return True, f"포지션 진입 완료: {symbol} {side} {quantity:.8f} (레버리지: {leverage}x)"

        except Exception as e:
            error_msg = f"포지션 진입 오류: {e}"
            self.logger.error(error_msg)
            return False, error_msg

    def close_position(self, symbol, close_price):
        """포지션 청산"""
        try:
            position = self.find_position(symbol)
            if not position:
                return False, f"{symbol} 포지션을 찾을 수 없습니다"

            # 실현 손익 계산
            realized_pnl = self.calculate_realized_pnl(position, close_price)
            
            # 증거금 반환 + 실현 손익
            margin_return = position['margin_used'] + realized_pnl
            self.cross_data['margin_balance'] += margin_return
            self.cross_data['total_margin_used'] -= position['margin_used']

            # 포지션 제거
            self.cross_data['positions'] = [p for p in self.cross_data['positions'] if p['symbol'] != symbol]

            # 거래 내역 추가
            transaction = {
                'type': 'CLOSE_POSITION',
                'symbol': symbol,
                'side': position['side'],
                'quantity': position['quantity'],
                'entry_price': position['entry_price'],
                'close_price': close_price,
                'leverage': position['leverage'],
                'realized_pnl': realized_pnl,
                'margin_returned': margin_return,
                'timestamp': datetime.now().isoformat()
            }
            self.cross_transactions.append(transaction)

            # 저장
            self.save_cross_data()
            self.save_cross_transactions()

            pnl_text = f"+${realized_pnl:.2f}" if realized_pnl >= 0 else f"${realized_pnl:.2f}"
            self.logger.info(f"포지션 청산: {symbol} 실현손익: {pnl_text}")
            return True, f"포지션 청산 완료: {symbol} 실현손익: {pnl_text}"

        except Exception as e:
            error_msg = f"포지션 청산 오류: {e}"
            self.logger.error(error_msg)
            return False, error_msg

    def find_position(self, symbol):
        """심볼로 포지션 찾기"""
        for position in self.cross_data['positions']:
            if position['symbol'] == symbol:
                return position
        return None

    def calculate_unrealized_pnl(self, position, current_price):
        """미실현 손익 계산 - 수정된 올바른 계산 방식 🚀"""
        try:
            entry_price = position['entry_price']
            quantity = position['quantity']
            side = position['side']
            
            # ⚠️ 중요: 수량은 이미 레버리지가 반영된 값이므로
            # PnL 계산시 레버리지를 추가로 곱하면 안됨!
            
            if side == 'LONG':
                # 롱: (현재가 - 진입가) * 수량
                pnl = (current_price - entry_price) * quantity
            else:  # SHORT
                # 숏: (진입가 - 현재가) * 수량
                pnl = (entry_price - current_price) * quantity

            return pnl

        except Exception as e:
            self.logger.error(f"미실현 손익 계산 오류: {e}")
            return 0.0

    def calculate_realized_pnl(self, position, close_price):
        """실현 손익 계산"""
        return self.calculate_unrealized_pnl(position, close_price)

    def update_positions_pnl(self, current_prices):
        """모든 포지션의 미실현 손익 업데이트 + 자동 청산 확인"""
        try:
            total_unrealized_pnl = 0.0
            liquidated_positions = []

            for position in self.cross_data['positions']:
                symbol = position['symbol']
                current_price = current_prices.get(symbol, 0)
                
                if current_price > 0:
                    unrealized_pnl = self.calculate_unrealized_pnl(position, current_price)
                    position['unrealized_pnl'] = unrealized_pnl
                    position['current_price'] = current_price
                    total_unrealized_pnl += unrealized_pnl
                    
                    # 🚨 자동 청산 조건 확인
                    margin_used = position['margin_used']
                    pnl_percentage = (unrealized_pnl / margin_used) * 100 if margin_used > 0 else 0
                    
                    # 청산가격 기반 청산 조건 추가
                    liquidation_price = self.calculate_liquidation_price(position)
                    is_liquidation_triggered = False
                    
                    if position['side'] == 'LONG' and current_price <= liquidation_price:
                        is_liquidation_triggered = True
                    elif position['side'] == 'SHORT' and current_price >= liquidation_price:
                        is_liquidation_triggered = True
                    
                    # -80% 손실시 또는 청산가격 도달시 자동 청산
                    if pnl_percentage <= -80.0 or is_liquidation_triggered:
                        self.logger.warning(f"🚨 청산 조건 감지: {symbol} {position['side']} 손실률: {pnl_percentage:.1f}%")
                        
                        # 자동 청산 실행
                        success, message = self.close_position(symbol, current_price)
                        if success:
                            liquidated_positions.append({
                                'symbol': symbol,
                                'side': position['side'],
                                'pnl_percentage': pnl_percentage,
                                'liquidation_price': current_price
                            })
                            
                            # 청산 로그 추가
                            liquidation_log = {
                                'type': 'AUTO_LIQUIDATION',
                                'symbol': symbol,
                                'side': position['side'],
                                'quantity': position['quantity'],
                                'entry_price': position['entry_price'],
                                'liquidation_price': current_price,
                                'pnl_percentage': pnl_percentage,
                                'reason': f'손실률 {pnl_percentage:.1f}% 초과',
                                'timestamp': datetime.now().isoformat()
                            }
                            self.cross_transactions.append(liquidation_log)
                            
                    # -70% 손실시 마진콜 경고
                    elif pnl_percentage <= -70.0:
                        self.logger.warning(f"⚠️ 마진콜 경고: {symbol} {position['side']} 손실률: {pnl_percentage:.1f}%")

            self.cross_data['total_unrealized_pnl'] = total_unrealized_pnl
            
            # 청산된 포지션들 제거
            if liquidated_positions:
                for liq_pos in liquidated_positions:
                    self.cross_data['positions'] = [
                        p for p in self.cross_data['positions'] 
                        if p['symbol'] != liq_pos['symbol']
                    ]
                self.logger.warning(f"🚨 {len(liquidated_positions)}개 포지션 자동 청산 완료")
            
            # 주기적으로 저장 (너무 자주 저장하지 않도록)
            import time
            if not hasattr(self, 'last_save_time'):
                self.last_save_time = 0
            
            if time.time() - self.last_save_time > 10:  # 10초마다 저장
                self.save_cross_data()
                self.last_save_time = time.time()
                
            return liquidated_positions

        except Exception as e:
            self.logger.error(f"포지션 PnL 업데이트 오류: {e}")
            return []

    def get_cross_summary(self, current_prices=None):
        """Cross 포지션 요약 정보"""
        try:
            if current_prices:
                self.update_positions_pnl(current_prices)

            summary = {
                'margin_balance': self.cross_data['margin_balance'],
                'total_margin_used': self.cross_data['total_margin_used'],
                'available_margin': self.cross_data['margin_balance'] - self.cross_data['total_margin_used'],
                'total_unrealized_pnl': self.cross_data['total_unrealized_pnl'],
                'positions': self.cross_data['positions'].copy(),
                'position_count': len(self.cross_data['positions']),
                'total_value': self.cross_data['margin_balance'] + self.cross_data['total_unrealized_pnl']
            }

            return summary

        except Exception as e:
            self.logger.error(f"Cross 요약 계산 오류: {e}")
            return None

    def get_cross_transactions(self, limit=50):
        """Cross 거래 내역 조회"""
        try:
            # 최신 거래부터 반환
            recent_transactions = self.cross_transactions[-limit:] if len(self.cross_transactions) > limit else self.cross_transactions
            recent_transactions.reverse()  # 최신 순으로 정렬
            return recent_transactions, None
        except Exception as e:
            error_msg = f"Cross 거래 내역 조회 오류: {e}"
            self.logger.error(error_msg)
            return [], error_msg

    def add_to_position(self, symbol, additional_quantity, price, additional_margin):
        """기존 포지션에 추가 진입"""
        position = self.find_position(symbol)
        if position:
            # 평균 진입가 계산
            total_quantity = position['quantity'] + additional_quantity
            total_cost = (position['quantity'] * position['entry_price']) + (additional_quantity * price)
            new_avg_price = total_cost / total_quantity
            
            # 포지션 업데이트
            position['quantity'] = total_quantity
            position['entry_price'] = new_avg_price
            position['margin_used'] += additional_margin
            
            self.cross_data['total_margin_used'] += additional_margin

    def reverse_position(self, symbol, new_side, quantity, price, leverage, margin_required):
        """반대 방향 포지션으로 전환"""
        existing_position = self.find_position(symbol)
        
        if existing_position['quantity'] == quantity:
            # 같은 수량이면 청산 후 새 포지션
            self.close_position(symbol, price)
            return self.open_position(symbol, new_side, quantity, price, leverage, margin_required)
        elif existing_position['quantity'] > quantity:
            # 부분 청산
            remaining_quantity = existing_position['quantity'] - quantity
            existing_position['quantity'] = remaining_quantity
            # 부분 청산 로직 구현 필요
            return True, f"부분 청산: {quantity} 청산, {remaining_quantity} 유지"
        else:
            # 기존 포지션보다 큰 수량으로 역전
            excess_quantity = quantity - existing_position['quantity']
            self.close_position(symbol, price)
            return self.open_position(symbol, new_side, excess_quantity, price, leverage, margin_required)

    def reset_cross_data(self):
        """Cross 데이터 초기화"""
        try:
            initial_data = {
                'margin_balance': Config.INITIAL_BALANCE * 0.1,
                'positions': [],
                'total_margin_used': 0.0,
                'total_unrealized_pnl': 0.0,
                'last_updated': datetime.now().isoformat()
            }
            
            self.cross_data = initial_data
            self.cross_transactions = []
            
            self.save_cross_data()
            self.save_cross_transactions()
            
            return True, "Cross 데이터가 초기화되었습니다"
            
        except Exception as e:
            error_msg = f"Cross 데이터 초기화 오류: {e}"
            self.logger.error(error_msg)
            return False, error_msg
            
    def calculate_liquidation_price(self, position):
        """청산가격 계산"""
        try:
            entry_price = position['entry_price']
            leverage = position['leverage']
            side = position['side']
            
            # 유지증거금률 (심볼별로 다름)
            maintenance_margin_rate = self._get_maintenance_margin_rate(position['symbol'])
            
            if side == 'LONG':
                # 롱 포지션 청산가격: entry_price * (1 - (1/leverage) + maintenance_margin_rate)
                liquidation_price = entry_price * (1 - (1/leverage) + maintenance_margin_rate)
            else:  # SHORT
                # 숏 포지션 청산가격: entry_price * (1 + (1/leverage) - maintenance_margin_rate)
                liquidation_price = entry_price * (1 + (1/leverage) - maintenance_margin_rate)
                
            return liquidation_price
            
        except Exception as e:
            self.logger.error(f"청산가격 계산 오류: {e}")
            return 0
            
    def _get_maintenance_margin_rate(self, symbol):
        """심볼별 유지증거금률 조회"""
        # 바이낸스 기준 유지증거금률
        maintenance_rates = {
            'BTCUSDT': 0.004,   # 0.4%
            'ETHUSDT': 0.005,   # 0.5%
            'SOLUSDT': 0.01,    # 1.0%
            'ADAUSDT': 0.01,    # 1.0%
            'DOTUSDT': 0.01,    # 1.0%
        }
        
        return maintenance_rates.get(symbol, 0.015)  # 기본값 1.5%
        
    def get_position_risk_info(self, current_prices):
        """포지션별 위험도 정보"""
        try:
            risk_info = []
            
            for position in self.cross_data['positions']:
                symbol = position['symbol']
                current_price = current_prices.get(symbol, 0)
                
                if current_price <= 0:
                    continue
                    
                unrealized_pnl = self.calculate_unrealized_pnl(position, current_price)
                margin_used = position['margin_used']
                pnl_percentage = (unrealized_pnl / margin_used) * 100 if margin_used > 0 else 0
                liquidation_price = self.calculate_liquidation_price(position)
                
                # 청산까지의 거리 계산
                if position['side'] == 'LONG':
                    distance_to_liquidation = ((current_price - liquidation_price) / current_price) * 100
                else:  # SHORT
                    distance_to_liquidation = ((liquidation_price - current_price) / current_price) * 100
                
                risk_level = "안전"
                if pnl_percentage <= -70:
                    risk_level = "극위험"
                elif pnl_percentage <= -50:
                    risk_level = "고위험" 
                elif pnl_percentage <= -30:
                    risk_level = "중위험"
                elif pnl_percentage <= -10:
                    risk_level = "저위험"
                
                risk_info.append({
                    'symbol': symbol,
                    'side': position['side'],
                    'entry_price': position['entry_price'],
                    'current_price': current_price,
                    'liquidation_price': liquidation_price,
                    'unrealized_pnl': unrealized_pnl,
                    'pnl_percentage': pnl_percentage,
                    'distance_to_liquidation': distance_to_liquidation,
                    'risk_level': risk_level,
                    'leverage': position['leverage'],
                    'margin_used': margin_used
                })
                
            return risk_info
            
        except Exception as e:
            self.logger.error(f"위험도 정보 계산 오류: {e}")
            return []
