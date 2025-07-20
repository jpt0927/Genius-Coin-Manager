# config.py
import os
from dotenv import load_dotenv

# .env 파일 로드
load_dotenv()

class Config:
    # 바이낸스 현물 API 키
    BINANCE_API_KEY = os.getenv('BINANCE_API_KEY', '')
    BINANCE_API_SECRET = os.getenv('BINANCE_API_SECRET', '')
    
    # 바이낸스 선물 API 키 (새로 추가)
    BINANCE_FUTURES_API_KEY = os.getenv('BINANCE_FUTURES_API_KEY', '')
    BINANCE_FUTURES_API_SECRET = os.getenv('BINANCE_FUTURES_API_SECRET', '')

    # 테스트넷 사용 여부
    USE_TESTNET = True

    # 초기 자금 (USD)
    INITIAL_BALANCE = 1000000.0

    # 수수료율 (0.1%)
    COMMISSION_RATE = 0.001

    # 지원하는 거래쌍 (3개 메이저 코인)
    SUPPORTED_PAIRS = [
        'BTCUSDT',   # 비트코인
        'ETHUSDT',   # 이더리움  
        'SOLUSDT'    # 솔라나
    ]

    # 데이터 저장 경로
    DATA_DIR = 'data'

    # 로그 설정
    LOG_LEVEL = 'INFO'
    LOG_FILE = 'trading_log.txt'