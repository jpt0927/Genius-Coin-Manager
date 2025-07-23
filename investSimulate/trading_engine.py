# trading_engine.py
import logging
from .binance_client import BinanceClient
# 순환 import 해결을 위해 lazy import 사용
from .config import Config

class TradingEngine:
    def __init__(self):
        self.client = BinanceClient()
        # Lazy import로 순환 import 해결
        from .portfolio_manager import PortfolioManager
        self.portfolio = PortfolioManager()
        self.logger = logging.getLogger(__name__)

        # 현재 가격 캐시
        self.current_prices = {}

    def update_prices(self):
        """모든 지원 심볼의 현재 가격 업데이트"""
        try:
            all_prices = self.client.get_all_prices()

            # 지원하는 거래쌍만 필터링
            self.current_prices = {
                symbol: price for symbol, price in all_prices.items()
                if symbol in Config.SUPPORTED_PAIRS
            }

            self.logger.info(f"가격 업데이트 완료: {len(self.current_prices)}개 심볼")
            return True
        except Exception as e:
            self.logger.error(f"가격 업데이트 실패: {e}")
            return False

    def get_current_price(self, symbol):
        """특정 심볼의 현재 가격 조회"""
        if symbol in self.current_prices:
            return self.current_prices[symbol]

        # 캐시에 없으면 직접 조회
        price = self.client.get_symbol_price(symbol)
        if price:
            self.current_prices[symbol] = price
        return price

    def place_buy_order(self, symbol, amount_usd=None, quantity=None):
        """매수 주문 실행"""
        try:
            if symbol not in Config.SUPPORTED_PAIRS:
                return False, f"지원하지 않는 거래쌍: {symbol}"

            # 현재 가격 조회
            current_price = self.get_current_price(symbol)
            if not current_price:
                return False, f"가격 조회 실패: {symbol}"

            # 매수 수량 계산
            if amount_usd:
                # USD 금액으로 매수
                quantity = amount_usd / current_price
            elif quantity:
                # 수량으로 매수
                amount_usd = quantity * current_price
            else:
                return False, "매수 금액 또는 수량을 지정해야 합니다"

            # 소수점 정리 (바이낸스 규칙에 따라)
            quantity = round(quantity, 8)

            if quantity <= 0:
                return False, "매수 수량이 0보다 커야 합니다"

            # 포트폴리오 매니저를 통해 매수 실행
            success, message = self.portfolio.buy_coin(symbol, quantity, current_price)

            if success:
                self.logger.info(f"매수 주문 실행: {symbol} {quantity} @ ${current_price}")
            else:
                self.logger.warning(f"매수 주문 실패: {message}")

            return success, message

        except Exception as e:
            error_msg = f"매수 주문 처리 중 오류: {e}"
            self.logger.error(error_msg)
            return False, error_msg

    def place_sell_order(self, symbol, quantity=None, sell_all=False):
        """매도 주문 실행"""
        try:
            if symbol not in Config.SUPPORTED_PAIRS:
                return False, f"지원하지 않는 거래쌍: {symbol}"

            # 현재 가격 조회
            current_price = self.get_current_price(symbol)
            if not current_price:
                return False, f"가격 조회 실패: {symbol}"

            # 매도 수량 결정
            if sell_all:
                quantity = self.portfolio.get_holding_quantity(symbol)
            elif not quantity:
                return False, "매도 수량을 지정해야 합니다"

            if quantity <= 0:
                return False, "매도할 수량이 없습니다"

            # 소수점 정리
            quantity = round(quantity, 8)

            # 포트폴리오 매니저를 통해 매도 실행
            success, message = self.portfolio.sell_coin(symbol, quantity, current_price)

            if success:
                self.logger.info(f"매도 주문 실행: {symbol} {quantity} @ ${current_price}")
            else:
                self.logger.warning(f"매도 주문 실패: {message}")

            return success, message

        except Exception as e:
            error_msg = f"매도 주문 처리 중 오류: {e}"
            self.logger.error(error_msg)
            return False, error_msg

    def get_market_data(self, symbol):
        """시장 데이터 조회"""
        try:
            if symbol not in Config.SUPPORTED_PAIRS:
                return None, f"지원하지 않는 거래쌍: {symbol}"

            # 현재 가격
            current_price = self.get_current_price(symbol)

            # 24시간 통계
            ticker_24hr = self.client.get_24hr_ticker(symbol)

            # 호가창 정보
            orderbook = self.client.get_orderbook(symbol, limit=5)

            market_data = {
                'symbol': symbol,
                'current_price': current_price,
                'price_change_24h': float(ticker_24hr['priceChange']) if ticker_24hr else 0,
                'price_change_percent_24h': float(ticker_24hr['priceChangePercent']) if ticker_24hr else 0,
                'high_24h': float(ticker_24hr['highPrice']) if ticker_24hr else 0,
                'low_24h': float(ticker_24hr['lowPrice']) if ticker_24hr else 0,
                'volume_24h': float(ticker_24hr['volume']) if ticker_24hr else 0,
                'bid_price': float(orderbook['bids'][0][0]) if orderbook and orderbook['bids'] else 0,
                'ask_price': float(orderbook['asks'][0][0]) if orderbook and orderbook['asks'] else 0,
            }

            return market_data, "시장 데이터 조회 성공"

        except Exception as e:
            error_msg = f"시장 데이터 조회 중 오류: {e}"
            self.logger.error(error_msg)
            return None, error_msg

    def get_portfolio_status(self):
        """포트폴리오 상태 조회"""
        try:
            # 가격 업데이트
            self.update_prices()

            # 포트폴리오 요약 정보
            summary = self.portfolio.get_portfolio_summary(self.current_prices)

            return summary, "포트폴리오 상태 조회 성공"

        except Exception as e:
            error_msg = f"포트폴리오 상태 조회 중 오류: {e}"
            self.logger.error(error_msg)
            return None, error_msg

    def get_transaction_history(self, limit=10):
        """거래 내역 조회"""
        try:
            transactions = self.portfolio.transactions

            # 최근 거래 순으로 정렬
            sorted_transactions = sorted(
                transactions,
                key=lambda x: x['timestamp'],
                reverse=True
            )

            # 제한된 개수만 반환
            return sorted_transactions[:limit], "거래 내역 조회 성공"

        except Exception as e:
            error_msg = f"거래 내역 조회 중 오류: {e}"
            self.logger.error(error_msg)
            return [], error_msg

    def reset_portfolio(self):
        """포트폴리오 초기화"""
        try:
            from datetime import datetime

            # 포트폴리오 초기화
            self.portfolio.portfolio = {
                'balance': Config.INITIAL_BALANCE,
                'holdings': {},
                'total_invested': 0.0,
                'total_profit_loss': 0.0,
                'last_updated': datetime.now().isoformat()
            }

            # 거래 내역 초기화
            self.portfolio.transactions = []

            # 저장
            self.portfolio.save_portfolio()
            self.portfolio.save_transactions()

            self.logger.info("포트폴리오 초기화 완료")
            return True, "포트폴리오가 초기화되었습니다"

        except Exception as e:
            error_msg = f"포트폴리오 초기화 중 오류: {e}"
            self.logger.error(error_msg)
            return False, error_msg