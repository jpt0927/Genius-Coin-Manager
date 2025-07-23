# background_worker.py - 백그라운드 작업 처리 스레드
from PyQt5.QtCore import QThread, pyqtSignal
import time
import logging

class BackgroundWorker(QThread):
    """백그라운드에서 API 호출을 처리하는 워커 스레드"""
    
    # 시그널 정의
    portfolio_updated = pyqtSignal(dict)  # 포트폴리오 업데이트
    positions_updated = pyqtSignal(list)  # 포지션 업데이트
    error_occurred = pyqtSignal(str)      # 에러 발생
    
    def __init__(self, trading_engine, futures_client, cross_position_manager):
        super().__init__()
        self.trading_engine = trading_engine
        self.futures_client = futures_client
        self.cross_position_manager = cross_position_manager
        
        self.running = False
        self.logger = logging.getLogger(__name__)
        
        # 업데이트 간격 (초)
        self.portfolio_update_interval = 2.0
        self.position_update_interval = 3.0
        self.last_portfolio_update = 0
        self.last_position_update = 0
        
    def run(self):
        """백그라운드 작업 실행"""
        self.running = True
        self.logger.info("📡 백그라운드 워커 시작")
        
        while self.running:
            current_time = time.time()
            
            try:
                # 포트폴리오 업데이트 (2초마다)
                if current_time - self.last_portfolio_update >= self.portfolio_update_interval:
                    self._update_portfolio()
                    self.last_portfolio_update = current_time
                
                # 포지션 업데이트 (3초마다)
                if current_time - self.last_position_update >= self.position_update_interval:
                    self._update_positions()
                    self.last_position_update = current_time
                    
            except Exception as e:
                self.error_occurred.emit(f"백그라운드 작업 오류: {e}")
                self.logger.error(f"백그라운드 워커 오류: {e}")
            
            # CPU 부하 감소를 위한 대기
            time.sleep(0.5)
    
    def _update_portfolio(self):
        """포트폴리오 정보 업데이트"""
        try:
            # 현물 거래 요약
            summary, message = self.trading_engine.get_portfolio_status()
            
            # 바이낸스 선물 계정 정보
            futures_balance = {'balance': 0, 'available': 0}
            total_futures_pnl = 0
            
            try:
                futures_balance = self.futures_client.get_futures_balance()
                futures_positions = self.futures_client.get_position_info()
                
                # 활성 포지션만 필터링
                active_positions = [pos for pos in futures_positions if float(pos.get('positionAmt', 0)) != 0] if futures_positions else []
                
                # 총 미실현 손익 계산
                total_futures_pnl = sum(float(pos.get('unRealizedProfit', 0)) for pos in active_positions)
                
            except Exception as e:
                self.logger.warning(f"바이낸스 데이터 조회 실패: {e}")
            
            # 포트폴리오 데이터 구성
            portfolio_data = {
                'summary': summary,
                'futures_balance': futures_balance,
                'total_futures_pnl': total_futures_pnl,
                'timestamp': time.time()
            }
            
            # 메인 스레드에 결과 전송
            self.portfolio_updated.emit(portfolio_data)
            
        except Exception as e:
            self.error_occurred.emit(f"포트폴리오 업데이트 실패: {e}")
    
    def _update_positions(self):
        """포지션 정보 업데이트"""
        try:
            # 레버리지 포지션 가져오기
            active_positions = self.cross_position_manager.get_active_positions()
            
            # 메인 스레드에 결과 전송
            self.positions_updated.emit(active_positions)
            
        except Exception as e:
            self.error_occurred.emit(f"포지션 업데이트 실패: {e}")
    
    def stop(self):
        """백그라운드 워커 중지"""
        self.running = False
        self.logger.info("🛑 백그라운드 워커 중지")
        self.wait()  # 스레드 종료 대기

class OptimizedUpdateManager:
    """UI 업데이트 최적화 관리자"""
    
    def __init__(self, main_window):
        self.main_window = main_window
        self.pending_updates = {
            'portfolio': False,
            'positions': False,
            'prices': False
        }
        
        # 배치 업데이트 타이머
        from PyQt5.QtCore import QTimer
        self.batch_timer = QTimer()
        self.batch_timer.timeout.connect(self._process_batch_updates)
        self.batch_timer.start(500)  # 500ms마다 배치 처리
    
    def request_portfolio_update(self):
        """포트폴리오 업데이트 요청"""
        self.pending_updates['portfolio'] = True
    
    def request_positions_update(self):
        """포지션 업데이트 요청"""
        self.pending_updates['positions'] = True
    
    def request_prices_update(self):
        """가격 업데이트 요청"""
        self.pending_updates['prices'] = True
    
    def _process_batch_updates(self):
        """배치 업데이트 처리"""
        try:
            if self.pending_updates['portfolio']:
                self._update_portfolio_display()
                self.pending_updates['portfolio'] = False
            
            if self.pending_updates['positions']:
                self._update_positions_display()
                self.pending_updates['positions'] = False
                
            if self.pending_updates['prices']:
                self._update_prices_display()
                self.pending_updates['prices'] = False
                
        except Exception as e:
            logging.getLogger(__name__).error(f"배치 업데이트 처리 오류: {e}")
    
    def _update_portfolio_display(self):
        """포트폴리오 디스플레이 업데이트 (최적화됨)"""
        if hasattr(self.main_window, '_update_portfolio_ui'):
            self.main_window._update_portfolio_ui()
    
    def _update_positions_display(self):
        """포지션 디스플레이 업데이트 (최적화됨)"""
        if hasattr(self.main_window, '_update_positions_ui'):
            self.main_window._update_positions_ui()
    
    def _update_prices_display(self):
        """가격 디스플레이 업데이트 (최적화됨)"""
        if hasattr(self.main_window, '_update_prices_ui'):
            self.main_window._update_prices_ui()
    
    def stop(self):
        """업데이트 매니저 정지"""
        if hasattr(self, 'batch_timer'):
            self.batch_timer.stop()