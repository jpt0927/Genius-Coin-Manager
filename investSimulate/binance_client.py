# binance_client.py
from binance.client import Client
from binance.exceptions import BinanceAPIException
import logging
from .config import Config

class BinanceClient:
    def __init__(self):
        self.client = Client(
            Config.BINANCE_API_KEY,
            Config.BINANCE_API_SECRET,
            testnet=Config.USE_TESTNET
        )
        self.logger = logging.getLogger(__name__)

    def get_symbol_price(self, symbol):
        """특정 심볼의 현재 가격 조회"""
        try:
            ticker = self.client.get_symbol_ticker(symbol=symbol)
            return float(ticker['price'])
        except BinanceAPIException as e:
            self.logger.error(f"가격 조회 오류 ({symbol}): {e}")
            return None

    def get_all_prices(self):
        """모든 심볼의 현재 가격 조회"""
        try:
            prices = self.client.get_all_tickers()
            return {price['symbol']: float(price['price']) for price in prices}
        except BinanceAPIException as e:
            self.logger.error(f"전체 가격 조회 오류: {e}")
            return {}

    def get_klines(self, symbol, interval='1h', limit=100):
        """캔들스틱 데이터 조회"""
        try:
            klines = self.client.get_klines(
                symbol=symbol,
                interval=interval,
                limit=limit
            )
            return klines
        except BinanceAPIException as e:
            self.logger.error(f"캔들스틱 데이터 조회 오류 ({symbol}): {e}")
            return []

    def get_orderbook(self, symbol, limit=10):
        """호가창 정보 조회"""
        try:
            orderbook = self.client.get_order_book(symbol=symbol, limit=limit)
            return orderbook
        except BinanceAPIException as e:
            self.logger.error(f"호가창 조회 오류 ({symbol}): {e}")
            return None

    def get_24hr_ticker(self, symbol):
        """24시간 통계 정보 조회"""
        try:
            ticker = self.client.get_ticker(symbol=symbol)
            return ticker
        except BinanceAPIException as e:
            self.logger.error(f"24시간 통계 조회 오류 ({symbol}): {e}")
            return None

    def is_valid_symbol(self, symbol):
        """심볼 유효성 검사"""
        try:
            self.client.get_symbol_ticker(symbol=symbol)
            return True
        except BinanceAPIException:
            return False