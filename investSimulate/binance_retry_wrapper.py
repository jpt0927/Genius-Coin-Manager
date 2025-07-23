# binance_retry_wrapper.py - 바이낸스 API 재시도 래퍼
import time
import logging
from functools import wraps
from binance.exceptions import BinanceAPIException

class BinanceRetryWrapper:
    """바이낸스 API 호출을 위한 재시도 래퍼"""
    
    def __init__(self, max_retries=3, base_delay=1.0):
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.logger = logging.getLogger(__name__)
        
    def retry_on_timeout(self, func):
        """타임아웃 발생 시 재시도하는 데코레이터"""
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            
            for attempt in range(self.max_retries):
                try:
                    return func(*args, **kwargs)
                    
                except BinanceAPIException as e:
                    last_exception = e
                    error_code = e.code
                    
                    # 타임아웃 관련 오류 코드들
                    timeout_codes = [-1007, -1000, -1001, -1003]
                    
                    if error_code in timeout_codes and attempt < self.max_retries - 1:
                        delay = self.base_delay * (2 ** attempt)  # 지수적 백오프
                        self.logger.warning(
                            f"바이낸스 타임아웃 (코드: {error_code}), "
                            f"{delay:.1f}초 후 재시도... (시도 {attempt + 1}/{self.max_retries})"
                        )
                        time.sleep(delay)
                        continue
                    else:
                        # 재시도하지 않을 오류거나 최대 재시도 횟수 초과
                        raise e
                        
                except Exception as e:
                    last_exception = e
                    if attempt < self.max_retries - 1:
                        delay = self.base_delay * (2 ** attempt)
                        self.logger.warning(f"예상치 못한 오류, {delay:.1f}초 후 재시도... {e}")
                        time.sleep(delay)
                        continue
                    else:
                        raise e
            
            # 모든 재시도 실패
            raise last_exception
            
        return wrapper
        
    def create_resilient_client(self, futures_client):
        """복원력 있는 클라이언트 생성"""
        
        # 원본 메서드들을 래핑
        original_create_order = futures_client.create_futures_order
        original_get_position = futures_client.get_position_info
        original_close_position = futures_client.close_position
        
        # 재시도 로직이 적용된 메서드들로 교체
        futures_client.create_futures_order = self.retry_on_timeout(original_create_order)
        futures_client.get_position_info = self.retry_on_timeout(original_get_position)
        futures_client.close_position = self.retry_on_timeout(original_close_position)
        
        self.logger.info("바이낸스 클라이언트에 재시도 로직 적용 완료")
        return futures_client

# 전역 재시도 래퍼 인스턴스
retry_wrapper = BinanceRetryWrapper(max_retries=5, base_delay=2.0)
