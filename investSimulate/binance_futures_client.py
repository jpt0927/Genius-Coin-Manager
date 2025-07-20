# binance_futures_client.py - 바이낸스 선물거래 (레버리지) 클라이언트
from binance.client import Client
from binance.exceptions import BinanceAPIException
import logging
from config import Config

class BinanceFuturesClient:
    """바이낸스 선물거래 (레버리지) 클라이언트"""
    
    def __init__(self):
        self.client = Client(
            Config.BINANCE_FUTURES_API_KEY,
            Config.BINANCE_FUTURES_API_SECRET,
            testnet=Config.USE_TESTNET
        )
        self.logger = logging.getLogger(__name__)
        
        # 기본 설정 초기화
        self._initialize_futures_settings()
        
    def _initialize_futures_settings(self):
        """선물거래 초기 설정"""
        try:
            # 포지션 모드 설정 (단방향 모드)
            self.client.futures_change_position_mode(dualSidePosition=False)
            self.logger.info("선물거래 포지션 모드: 단방향")
        except Exception as e:
            self.logger.warning(f"포지션 모드 설정 실패: {e}")
            
    def get_futures_account(self):
        """선물 계정 정보 조회"""
        try:
            account = self.client.futures_account()
            return account
        except BinanceAPIException as e:
            self.logger.error(f"선물 계정 조회 오류: {e}")
            return None
            
    def get_futures_balance(self):
        """선물 계정 잔고 조회"""
        try:
            balance = self.client.futures_account_balance()
            usdt_balance = next((item for item in balance if item["asset"] == "USDT"), None)
            if usdt_balance:
                return {
                    'balance': float(usdt_balance['balance']),
                    'available': float(usdt_balance['availableBalance']),
                    'crossWalletBalance': float(usdt_balance['crossWalletBalance'])
                }
            return {'balance': 0, 'available': 0, 'crossWalletBalance': 0}
        except BinanceAPIException as e:
            self.logger.error(f"선물 잔고 조회 오류: {e}")
            return {'balance': 0, 'available': 0, 'crossWalletBalance': 0}
            
    def set_leverage(self, symbol, leverage):
        """레버리지 설정"""
        try:
            result = self.client.futures_change_leverage(
                symbol=symbol,
                leverage=leverage
            )
            self.logger.info(f"레버리지 설정 완료: {symbol} - {leverage}x")
            return True, f"{symbol} 레버리지 {leverage}x 설정 완료"
        except BinanceAPIException as e:
            error_msg = f"레버리지 설정 실패: {e}"
            self.logger.error(error_msg)
            return False, error_msg
            
    def get_position_info(self, symbol=None):
        """포지션 정보 조회"""
        try:
            positions = self.client.futures_position_information(symbol=symbol)
            if symbol:
                # 특정 심볼의 포지션 정보
                position = next((p for p in positions if p['symbol'] == symbol), None)
                if position:
                    # percentage 계산 (entry_price가 0이 아닌 경우에만)
                    entry_price = float(position['entryPrice']) if position['entryPrice'] != '0.0' else 0
                    unrealized_pnl = float(position['unRealizedProfit'])
                    percentage = 0
                    
                    if entry_price > 0 and float(position['positionAmt']) != 0:
                        # percentage = (unrealized_pnl / (entry_price * abs(position_size))) * 100
                        position_value = entry_price * abs(float(position['positionAmt']))
                        percentage = (unrealized_pnl / position_value) * 100 if position_value > 0 else 0
                    
                    return {
                        'symbol': position['symbol'],
                        'size': float(position['positionAmt']),
                        'entry_price': entry_price,
                        'mark_price': float(position['markPrice']),
                        'unrealized_pnl': unrealized_pnl,
                        'percentage': percentage,
                        'side': 'LONG' if float(position['positionAmt']) > 0 else 'SHORT' if float(position['positionAmt']) < 0 else 'NONE'
                    }
            return positions
        except BinanceAPIException as e:
            self.logger.error(f"포지션 정보 조회 오류: {e}")
            return None
            
    def create_futures_order(self, symbol, side, quantity, order_type='MARKET', price=None, leverage=None):
        """선물 주문 실행"""
        try:
            # 레버리지 설정 (필요한 경우)
            if leverage:
                self.set_leverage(symbol, leverage)
            
            # 수량을 심볼에 맞는 정밀도로 조정
            formatted_quantity = self.format_quantity(symbol, quantity)
            self.logger.info(f"수량 조정: {quantity} → {formatted_quantity} ({symbol})")
                
            order_params = {
                'symbol': symbol,
                'side': side,
                'type': order_type,
                'quantity': formatted_quantity,  # 조정된 수량 사용
            }
            
            # 지정가 주문인 경우 가격 추가
            if order_type == 'LIMIT':
                order_params['price'] = price
                order_params['timeInForce'] = 'GTC'  # Good Till Cancelled
                
            result = self.client.futures_create_order(**order_params)
            
            self.logger.info(f"선물 주문 성공: {symbol} {side} {formatted_quantity}")
            return True, result
            
        except BinanceAPIException as e:
            error_msg = f"선물 주문 실패: {e}"
            self.logger.error(error_msg)
            return False, error_msg
            
    def close_position(self, symbol):
        """포지션 전량 청산"""
        try:
            position = self.get_position_info(symbol)
            if not position or position['size'] == 0:
                return False, "청산할 포지션이 없습니다"
                
            # 포지션과 반대 방향으로 주문
            side = 'SELL' if position['size'] > 0 else 'BUY'
            quantity = abs(position['size'])
            
            success, result = self.create_futures_order(symbol, side, quantity)
            
            if success:
                return True, f"{symbol} 포지션 청산 완료"
            else:
                return False, f"포지션 청산 실패: {result}"
                
        except Exception as e:
            error_msg = f"포지션 청산 중 오류: {e}"
            self.logger.error(error_msg)
            return False, error_msg
            
    def get_max_leverage(self, symbol):
        """심볼별 최대 레버리지 조회"""
        try:
            # 심볼 정보에서 최대 레버리지 확인
            exchange_info = self.client.futures_exchange_info()
            symbol_info = next((s for s in exchange_info['symbols'] if s['symbol'] == symbol), None)
            
            if symbol_info:
                # filters에서 PERCENT_PRICE 필터 찾기
                for filter_info in symbol_info['filters']:
                    if filter_info['filterType'] == 'PERCENT_PRICE':
                        # 일반적으로 BTCUSDT는 125x, 알트코인은 20-50x
                        if symbol == 'BTCUSDT':
                            return 125
                        else:
                            return 50
                            
            return 20  # 기본값
            
        except Exception as e:
            self.logger.error(f"최대 레버리지 조회 오류: {e}")
            return 20
            
    def get_symbol_precision(self, symbol):
        """심볼별 수량 정밀도 조회"""
        try:
            info = self.client.futures_exchange_info()
            for s in info['symbols']:
                if s['symbol'] == symbol:
                    # quantityPrecision 사용
                    return int(s['quantityPrecision'])
            return 3  # 기본값
        except Exception as e:
            self.logger.error(f"정밀도 조회 오류: {e}")
            return 3  # 기본값
            
    def get_min_quantity(self, symbol):
        """심볼별 최소 주문 수량 조회"""
        try:
            info = self.client.futures_exchange_info()
            for s in info['symbols']:
                if s['symbol'] == symbol:
                    for f in s['filters']:
                        if f['filterType'] == 'LOT_SIZE':
                            return float(f['minQty'])
            return 0.001  # 기본값
        except Exception as e:
            self.logger.error(f"최소 수량 조회 오류: {e}")
            return 0.001  # 기본값
            
    def format_quantity(self, symbol, quantity):
        """심볼에 맞는 수량 형식으로 변환"""
        try:
            precision = self.get_symbol_precision(symbol)
            min_qty = self.get_min_quantity(symbol)
            
            # 정밀도에 맞춰 반올림
            formatted_qty = round(quantity, precision)
            
            # 최소 수량 확인
            if formatted_qty < min_qty:
                self.logger.warning(f"수량이 최소값보다 작습니다: {formatted_qty} < {min_qty}")
                return min_qty
                
            return formatted_qty
            
        except Exception as e:
            self.logger.error(f"수량 형식 변환 오류: {e}")
            return round(quantity, 3)  # 기본값
            
    def calculate_liquidation_price(self, symbol, side, entry_price, leverage, quantity):
        """청산가격 계산 (근사치)"""
        try:
            # 간단한 청산가격 계산 (실제로는 더 복잡함)
            maintenance_margin_rate = 0.004  # 0.4% (심볼별로 다름)
            
            if side == 'LONG':
                liquidation_price = entry_price * (1 - (1/leverage) + maintenance_margin_rate)
            else:  # SHORT
                liquidation_price = entry_price * (1 + (1/leverage) - maintenance_margin_rate)
                
            return liquidation_price
            
        except Exception as e:
            self.logger.error(f"청산가격 계산 오류: {e}")
            return 0
