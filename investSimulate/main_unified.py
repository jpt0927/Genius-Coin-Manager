#!/usr/bin/env python3
"""
Genius Coin Manager - 통합 실행 파일
백테스트와 실시간 시뮬레이션 트레이딩을 모두 지원합니다.
"""

import sys
import os
import argparse
import logging
import asyncio
from PyQt5.QtWidgets import QApplication, QMainWindow, QTabWidget, QVBoxLayout, QWidget, QMessageBox
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QIcon

# 현재 디렉토리를 Python 경로에 추가
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.insert(0, current_dir)
sys.path.insert(0, parent_dir)

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class UnifiedTradingApp(QMainWindow):
    """통합 트레이딩 애플리케이션"""
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Genius Coin Manager - 통합 트레이딩 플랫폼")
        self.setGeometry(100, 100, 1600, 900)
        
        # 메인 위젯과 레이아웃
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        layout = QVBoxLayout(main_widget)
        
        # 탭 위젯 생성
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)
        
        # 각 모듈 초기화
        self.init_invest_simulate()
        self.init_backtest()
        
        # 스타일 설정
        self.setStyleSheet("""
            QMainWindow {
                background-color: #1e2329;
            }
            QTabWidget::pane {
                border: 1px solid #2b3139;
                background-color: #1e2329;
            }
            QTabBar::tab {
                background-color: #2b3139;
                color: #848e9c;
                padding: 10px 20px;
                margin-right: 2px;
                font-size: 14px;
                font-weight: bold;
            }
            QTabBar::tab:selected {
                background-color: #1e2329;
                color: #f0b90b;
                border-bottom: 3px solid #f0b90b;
            }
            QTabBar::tab:hover {
                background-color: #363c45;
            }
        """)
        
    def init_invest_simulate(self):
        """실시간 시뮬레이션 트레이딩 탭 초기화"""
        try:
            # InvestSimulate GUI 임포트
            from gui_app import TradingGUI
            
            # 트레이딩 GUI 인스턴스 생성
            self.trading_gui = TradingGUI()
            
            # 탭에 추가
            self.tabs.addTab(self.trading_gui, "📈 실시간 시뮬레이션")
            
            logger.info("실시간 시뮬레이션 모듈 로드 완료")
            
        except Exception as e:
            logger.error(f"실시간 시뮬레이션 모듈 로드 실패: {e}")
            error_widget = QWidget()
            self.tabs.addTab(error_widget, "❌ 실시간 시뮬레이션 (오류)")
            
    def init_backtest(self):
        """백테스트 탭 초기화"""
        try:
            # Backtest GUI 임포트
            from backtest.main import BacktestMainWindow
            from backtest.dataset import Dataset
            from backtest.backtesting import TradingStrategy
            from backtest.invest_strategy import (
                InvestmentStrategy, MAStrategy, RSIStrategy, 
                BollingerBandsStrategy, MACDStrategy, StochasticStrategy
            )
            
            # 백테스트 위젯 생성
            backtest_widget = QWidget()
            backtest_layout = QVBoxLayout(backtest_widget)
            
            # 백테스트 메인 윈도우 생성 (임베드용으로 수정)
            self.backtest_window = BacktestMainWindow()
            
            # 백테스트 윈도우의 중앙 위젯을 가져와서 탭에 추가
            central_widget = self.backtest_window.centralWidget()
            if central_widget:
                backtest_layout.addWidget(central_widget)
            
            # 탭에 추가
            self.tabs.addTab(backtest_widget, "📊 백테스트")
            
            logger.info("백테스트 모듈 로드 완료")
            
        except Exception as e:
            logger.error(f"백테스트 모듈 로드 실패: {e}")
            error_widget = QWidget()
            self.tabs.addTab(error_widget, "❌ 백테스트 (오류)")
            
    def closeEvent(self, event):
        """애플리케이션 종료 시 정리 작업"""
        reply = QMessageBox.question(
            self, 
            '종료 확인',
            'Genius Coin Manager를 종료하시겠습니까?',
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            # 실시간 시뮬레이션 정리
            if hasattr(self, 'trading_gui'):
                try:
                    self.trading_gui.close()
                except:
                    pass
                    
            # 백테스트 정리
            if hasattr(self, 'backtest_window'):
                try:
                    self.backtest_window.close()
                except:
                    pass
                    
            event.accept()
        else:
            event.ignore()

def run_gui_mode():
    """GUI 모드 실행"""
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    
    # 애플리케이션 아이콘 설정 (있는 경우)
    icon_path = os.path.join(current_dir, 'assets', 'icon.png')
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))
    
    # 메인 윈도우 생성 및 표시
    window = UnifiedTradingApp()
    window.show()
    
    sys.exit(app.exec_())

def run_cli_mode(args):
    """CLI 모드 실행"""
    logger.info("CLI 모드 시작")
    
    if args.mode == 'simulate':
        # 실시간 시뮬레이션 CLI 모드
        from main import main as simulate_main
        
        # CLI 인자 설정
        cli_args = ['--amount', str(args.amount)]
        if args.strategy:
            cli_args.extend(['--strategy', args.strategy])
        if args.leverage:
            cli_args.extend(['--leverage', str(args.leverage)])
            
        # 기존 main.py의 main 함수 호출
        sys.argv = ['main.py'] + cli_args
        simulate_main()
        
    elif args.mode == 'backtest':
        # 백테스트 CLI 모드
        from backtest.backtesting import run_backtest_cli
        from backtest.dataset import Dataset
        
        # 데이터셋 로드
        dataset = Dataset()
        dataset.load_data()
        
        # 백테스트 실행
        results = run_backtest_cli(
            dataset=dataset,
            strategy=args.strategy,
            initial_balance=args.amount,
            start_date=args.start_date,
            end_date=args.end_date
        )
        
        # 결과 출력
        print("\n=== 백테스트 결과 ===")
        print(f"최종 잔고: ${results['final_balance']:,.2f}")
        print(f"총 수익률: {results['total_return']:.2f}%")
        print(f"최대 낙폭: {results['max_drawdown']:.2f}%")
        print(f"승률: {results['win_rate']:.2f}%")
        
    else:
        logger.error(f"알 수 없는 모드: {args.mode}")
        sys.exit(1)

def main():
    """메인 진입점"""
    parser = argparse.ArgumentParser(
        description='Genius Coin Manager - 통합 트레이딩 플랫폼',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
사용 예시:
  # GUI 모드 실행 (기본)
  python main_unified.py
  
  # CLI 시뮬레이션 모드
  python main_unified.py --cli --mode simulate --amount 1000 --strategy trend_following
  
  # CLI 백테스트 모드
  python main_unified.py --cli --mode backtest --amount 10000 --strategy ma_crossover
        """
    )
    
    parser.add_argument('--cli', action='store_true', 
                       help='CLI 모드로 실행 (GUI 대신)')
    parser.add_argument('--mode', choices=['simulate', 'backtest'],
                       help='실행 모드 선택')
    parser.add_argument('--amount', type=float, default=1000.0,
                       help='초기 투자금액 (기본: 1000 USDT)')
    parser.add_argument('--strategy', type=str, default='trend_following',
                       help='사용할 전략 이름')
    parser.add_argument('--leverage', type=int, default=1,
                       help='레버리지 배율 (시뮬레이션 모드용)')
    parser.add_argument('--start-date', type=str,
                       help='백테스트 시작 날짜 (YYYY-MM-DD)')
    parser.add_argument('--end-date', type=str,
                       help='백테스트 종료 날짜 (YYYY-MM-DD)')
    
    args = parser.parse_args()
    
    # 환경 변수 로드
    try:
        from dotenv import load_dotenv
        env_path = os.path.join(current_dir, '.env')
        if os.path.exists(env_path):
            load_dotenv(env_path)
            logger.info(".env 파일 로드 완료")
    except ImportError:
        logger.warning("python-dotenv가 설치되지 않음. 환경 변수를 직접 설정하세요.")
    
    # 실행 모드 결정
    if args.cli:
        if not args.mode:
            parser.error("CLI 모드에서는 --mode 옵션이 필요합니다.")
        run_cli_mode(args)
    else:
        run_gui_mode()

if __name__ == "__main__":
    # Windows에서 멀티프로세싱 문제 방지
    if sys.platform.startswith('win'):
        import multiprocessing
        multiprocessing.freeze_support()
    
    # asyncio 이벤트 루프 정책 설정 (Windows)
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    
    main()