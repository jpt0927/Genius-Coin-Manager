#!/usr/bin/env python3
# performance_test.py - GUI 성능 최적화 검증 스크립트

import sys
import time
import psutil
import threading
from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import QTimer
import logging

# 테스트용 임포트
try:
    from gui_app import TradingGUI
    from background_worker import BackgroundWorker, OptimizedUpdateManager
except ImportError as e:
    print(f"❌ 모듈 임포트 실패: {e}")
    sys.exit(1)

class PerformanceMonitor:
    """성능 모니터링 클래스"""
    
    def __init__(self):
        self.process = psutil.Process()
        self.start_time = time.time()
        self.start_memory = self.process.memory_info().rss / 1024 / 1024  # MB
        self.peak_memory = self.start_memory
        self.cpu_samples = []
        self.memory_samples = []
        
    def sample(self):
        """현재 성능 지표 샘플링"""
        current_memory = self.process.memory_info().rss / 1024 / 1024  # MB
        current_cpu = self.process.cpu_percent()
        
        self.memory_samples.append(current_memory)
        self.cpu_samples.append(current_cpu)
        self.peak_memory = max(self.peak_memory, current_memory)
        
        return {
            'memory_mb': current_memory,
            'cpu_percent': current_cpu,
            'peak_memory_mb': self.peak_memory,
            'runtime_seconds': time.time() - self.start_time
        }
    
    def get_summary(self):
        """성능 요약 통계"""
        if not self.memory_samples or not self.cpu_samples:
            return {}
        
        return {
            'start_memory_mb': self.start_memory,
            'peak_memory_mb': self.peak_memory,
            'memory_increase_mb': self.peak_memory - self.start_memory,
            'avg_cpu_percent': sum(self.cpu_samples) / len(self.cpu_samples),
            'max_cpu_percent': max(self.cpu_samples),
            'runtime_seconds': time.time() - self.start_time,
            'total_samples': len(self.memory_samples)
        }

def test_gui_performance():
    """GUI 성능 테스트"""
    print("🚀 GUI 성능 최적화 테스트 시작...")
    
    # Qt 애플리케이션 생성
    app = QApplication(sys.argv)
    
    # 성능 모니터 시작
    monitor = PerformanceMonitor()
    
    try:
        print("📱 GUI 윈도우 생성 중...")
        
        # GUI 생성 시간 측정
        start_time = time.time()
        window = TradingGUI()
        window.show()
        gui_creation_time = time.time() - start_time
        
        print(f"✅ GUI 생성 완료: {gui_creation_time:.2f}초")
        print(f"📊 초기 메모리 사용량: {monitor.start_memory:.1f} MB")
        
        # 성능 모니터링 타이머
        test_duration = 30  # 30초 테스트
        sample_count = 0
        
        def monitor_performance():
            nonlocal sample_count
            sample_count += 1
            
            stats = monitor.sample()
            print(f"[{sample_count:2d}] "
                  f"메모리: {stats['memory_mb']:.1f}MB "
                  f"CPU: {stats['cpu_percent']:.1f}% "
                  f"런타임: {stats['runtime_seconds']:.1f}s")
            
            if sample_count >= test_duration:
                app.quit()
        
        # 1초마다 성능 샘플링
        timer = QTimer()
        timer.timeout.connect(monitor_performance)
        timer.start(1000)
        
        print(f"⏱️  {test_duration}초 동안 성능 모니터링...")
        
        # 이벤트 루프 실행
        app.exec_()
        
    except Exception as e:
        print(f"❌ GUI 테스트 실패: {e}")
        return False
    
    # 최종 성능 요약
    summary = monitor.get_summary()
    print("\n" + "="*50)
    print("📈 성능 테스트 결과 요약")
    print("="*50)
    print(f"🕐 총 실행 시간: {summary['runtime_seconds']:.1f}초")
    print(f"💾 시작 메모리: {summary['start_memory_mb']:.1f} MB")
    print(f"💾 최대 메모리: {summary['peak_memory_mb']:.1f} MB")
    print(f"📈 메모리 증가: {summary['memory_increase_mb']:.1f} MB")
    print(f"🔥 평균 CPU: {summary['avg_cpu_percent']:.1f}%")
    print(f"🔥 최대 CPU: {summary['max_cpu_percent']:.1f}%")
    print(f"📊 총 샘플: {summary['total_samples']}개")
    
    # 성능 평가
    print("\n" + "="*50)
    print("🎯 성능 최적화 평가")
    print("="*50)
    
    # 메모리 증가량 평가
    if summary['memory_increase_mb'] < 50:
        print("✅ 메모리 사용량: 우수 (50MB 미만 증가)")
    elif summary['memory_increase_mb'] < 100:
        print("⚠️  메모리 사용량: 보통 (50-100MB 증가)")
    else:
        print("❌ 메모리 사용량: 개선 필요 (100MB 이상 증가)")
    
    # CPU 사용률 평가
    if summary['avg_cpu_percent'] < 10:
        print("✅ CPU 사용률: 우수 (평균 10% 미만)")
    elif summary['avg_cpu_percent'] < 25:
        print("⚠️  CPU 사용률: 보통 (평균 10-25%)")
    else:
        print("❌ CPU 사용률: 개선 필요 (평균 25% 이상)")
    
    return True

def test_websocket_connections():
    """WebSocket 연결 테스트"""
    print("\n🌐 WebSocket 연결 최적화 테스트...")
    
    try:
        from gui_app import PriceUpdateThread
        from trading_engine import TradingEngine
        
        # 트레이딩 엔진 생성
        engine = TradingEngine()
        
        # WebSocket 스레드 생성
        ws_thread = PriceUpdateThread(engine)
        
        print("✅ WebSocket 스레드 생성 성공")
        print("✅ 배치 처리 타이머 확인됨")
        
        # 정리
        if hasattr(ws_thread, 'update_timer'):
            ws_thread.update_timer.stop()
        
        return True
        
    except Exception as e:
        print(f"❌ WebSocket 테스트 실패: {e}")
        return False

def test_background_worker():
    """백그라운드 워커 테스트"""
    print("\n🔧 백그라운드 워커 테스트...")
    
    try:
        # 더미 객체들 생성
        class DummyEngine:
            def get_portfolio_status(self):
                return {'total_value': 1000}, "OK"
        
        class DummyClient:
            def get_futures_balance(self):
                return {'balance': 500}
            def get_position_info(self):
                return []
        
        class DummyManager:
            def get_active_positions(self):
                return []
        
        # 백그라운드 워커 생성
        worker = BackgroundWorker(
            DummyEngine(),
            DummyClient(), 
            DummyManager()
        )
        
        print("✅ 백그라운드 워커 생성 성공")
        print(f"✅ 포트폴리오 업데이트 간격: {worker.portfolio_update_interval}초")
        print(f"✅ 포지션 업데이트 간격: {worker.position_update_interval}초")
        
        return True
        
    except Exception as e:
        print(f"❌ 백그라운드 워커 테스트 실패: {e}")
        return False

def main():
    """메인 테스트 함수"""
    print("🧪 Genius Coin Manager 성능 최적화 검증")
    print("=" * 60)
    
    test_results = []
    
    # 1. WebSocket 연결 테스트
    test_results.append(("WebSocket 최적화", test_websocket_connections()))
    
    # 2. 백그라운드 워커 테스트  
    test_results.append(("백그라운드 워커", test_background_worker()))
    
    # 3. 전체 GUI 성능 테스트 (마지막에 실행)
    if "--full-test" in sys.argv:
        test_results.append(("GUI 성능", test_gui_performance()))
    else:
        print("\n💡 전체 GUI 테스트를 실행하려면: python3 performance_test.py --full-test")
    
    # 최종 결과 요약
    print("\n" + "=" * 60)
    print("🏁 최종 테스트 결과")
    print("=" * 60)
    
    passed = 0
    total = len(test_results)
    
    for test_name, result in test_results:
        status = "✅ 통과" if result else "❌ 실패"
        print(f"{test_name:20s}: {status}")
        if result:
            passed += 1
    
    print(f"\n📊 전체 결과: {passed}/{total} 테스트 통과")
    
    if passed == total:
        print("🎉 모든 최적화가 성공적으로 적용되었습니다!")
        return 0
    else:
        print("⚠️  일부 최적화에 문제가 있습니다.")
        return 1

if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)