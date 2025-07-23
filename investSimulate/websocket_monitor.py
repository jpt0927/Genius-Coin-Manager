# websocket_monitor.py - WebSocket 상태 모니터링
from PyQt5.QtCore import QObject, pyqtSignal, QTimer
import time
import statistics
from collections import deque

class WebSocketMonitor(QObject):
    """WebSocket 데이터 일관성 모니터링"""
    
    anomaly_detected = pyqtSignal(str, dict)  # (message, data)
    
    def __init__(self):
        super().__init__()
        
        # 각 소스별 가격 히스토리
        self.price_history = {
            'portfolio': deque(maxlen=50),  # 포트폴리오 가격
            'orderbook': deque(maxlen=50),  # 호가창 중간가
            'chart': deque(maxlen=50)       # 차트 종가
        }
        
        # 마지막 업데이트 시간
        self.last_updates = {
            'portfolio': 0,
            'orderbook': 0, 
            'chart': 0
        }
        
        # 모니터링 타이머 (10초마다)
        self.monitor_timer = QTimer()
        self.monitor_timer.timeout.connect(self.check_data_consistency)
        self.monitor_timer.start(10000)
    
    def record_portfolio_price(self, symbol, price):
        """포트폴리오 가격 기록"""
        self.price_history['portfolio'].append({
            'symbol': symbol,
            'price': price,
            'timestamp': time.time()
        })
        self.last_updates['portfolio'] = time.time()
    
    def record_orderbook_price(self, symbol, mid_price):
        """호가창 중간가 기록"""
        self.price_history['orderbook'].append({
            'symbol': symbol,
            'price': mid_price,
            'timestamp': time.time()
        })
        self.last_updates['orderbook'] = time.time()
    
    def record_chart_price(self, symbol, close_price):
        """차트 종가 기록"""
        self.price_history['chart'].append({
            'symbol': symbol,
            'price': close_price,
            'timestamp': time.time()
        })
        self.last_updates['chart'] = time.time()
    
    def check_data_consistency(self):
        """데이터 일관성 검증"""
        current_time = time.time()
        
        # 1. 데이터 신선도 검사
        stale_sources = []
        for source, last_time in self.last_updates.items():
            age = current_time - last_time
            if age > 30:  # 30초 이상 오래됨
                stale_sources.append((source, age))
        
        if stale_sources:
            message = f"⚠️ 오래된 데이터: {stale_sources}"
            self.anomaly_detected.emit(message, {'type': 'stale_data', 'sources': stale_sources})
        
        # 2. 가격 일관성 검사 (같은 심볼)
        self.check_price_consistency_by_symbol()
    
    def check_price_consistency_by_symbol(self):
        """심볼별 가격 일관성 검사"""
        symbols_to_check = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT']
        
        for symbol in symbols_to_check:
            recent_prices = self.get_recent_prices_for_symbol(symbol)
            
            if len(recent_prices) >= 2:
                prices = [item['price'] for item in recent_prices]
                max_price = max(prices)
                min_price = min(prices)
                
                if min_price > 0:
                    diff_pct = ((max_price - min_price) / min_price) * 100
                    
                    if diff_pct > 1.0:  # 1% 이상 차이
                        message = f"🚨 가격 불일치: {symbol} 차이 {diff_pct:.2f}%"
                        data = {
                            'type': 'price_inconsistency',
                            'symbol': symbol,
                            'prices': recent_prices,
                            'diff_percent': diff_pct
                        }
                        self.anomaly_detected.emit(message, data)
    
    def get_recent_prices_for_symbol(self, symbol):
        """특정 심볼의 최근 가격들 수집"""
        recent_prices = []
        current_time = time.time()
        
        for source, history in self.price_history.items():
            for item in list(history)[-5:]:  # 최근 5개
                if (item['symbol'] == symbol and 
                    current_time - item['timestamp'] < 60):  # 1분 이내
                    recent_prices.append({
                        'source': source,
                        'price': item['price'],
                        'timestamp': item['timestamp']
                    })
        
        return recent_prices
    
    def get_status_report(self):
        """상태 리포트 생성"""
        current_time = time.time()
        
        report = {
            'timestamp': current_time,
            'data_sources': {},
            'last_updates': {},
            'total_records': {}
        }
        
        for source in ['portfolio', 'orderbook', 'chart']:
            age = current_time - self.last_updates[source]
            report['last_updates'][source] = f"{age:.1f}초 전"
            report['total_records'][source] = len(self.price_history[source])
            
            if age < 10:
                status = "✅ 정상"
            elif age < 30:
                status = "⚠️ 주의"
            else:
                status = "🚨 오류"
            
            report['data_sources'][source] = status
        
        return report
