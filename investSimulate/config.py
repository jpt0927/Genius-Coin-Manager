# config.py
import os
from dotenv import load_dotenv

# .env 파일 로드
load_dotenv()

class Config:
    # 바이낸스 API 키
    BINANCE_API_KEY = os.getenv('BINANCE_API_KEY', '')
    BINANCE_API_SECRET = os.getenv('BINANCE_API_SECRET', '')

    # 테스트넷 사용 여부
    USE_TESTNET = True

    # 초기 자금 (USD)
    INITIAL_BALANCE = 1000000.0

    # 수수료율 (0.1%)
    COMMISSION_RATE = 0.001

    # 지원하는 거래쌍
    SUPPORTED_PAIRS = [
        'BTCUSDT', 'ETHUSDT', 'ADAUSDT', 'DOTUSDT', 'LINKUSDT',
        'LTCUSDT', 'XRPUSDT', 'BCHUSDT', 'EOSUSDT', 'TRXUSDT'
    ]

    # 데이터 저장 경로
    DATA_DIR = 'data'
    DATA_PATH = 'data'

    # 로그 설정
    LOG_LEVEL = 'INFO'
    LOG_FILE = 'trading_log.txt'