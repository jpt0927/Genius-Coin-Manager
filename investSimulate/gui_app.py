import sys
import logging
from PyQt5.QtWidgets import *
from PyQt5.QtCore import *
from PyQt5.QtGui import *
from datetime import datetime

from trading_engine import TradingEngine
from config import Config
from chart_widget import CandlestickChart, ChartUpdateThread
from cross_position_manager import CrossPositionManager
from binance_futures_client import BinanceFuturesClient
from binance_retry_wrapper import retry_wrapper

try:
    from trading_bot_integration import AdvancedTradingBot, TradingBotConfig
    ADVANCED_BOT_AVAILABLE = True
except ImportError as e:
    print(f"고급 트레이딩봇 모듈을 찾을 수 없습니다: {e}")
    print("trading_bot_integration.py와 strategy_adapter.py 파일이 프로젝트 폴더에 있는지 확인하세요.")
    ADVANCED_BOT_AVAILABLE = False
    # 기본 클래스 정의
    class TradingBotConfig:
        def __init__(self, **kwargs):
            pass
    class AdvancedTradingBot:
        def __init__(self, config):
            pass

# 호가창 위젯 import
try:
    from order_book_widget import MatplotlibOrderBook
    ORDER_BOOK_AVAILABLE = True
except ImportError:
    print("호가창 위젯을 찾을 수 없습니다. order_book_widget.py가 있는지 확인하세요.")
    ORDER_BOOK_AVAILABLE = False

# 백그라운드 워커 import
from background_worker import BackgroundWorker, OptimizedUpdateManager

class PriceUpdateThread(QThread):
    """최적화된 실시간 웹소켓 가격 업데이트 스레드"""
    price_updated = pyqtSignal(dict)

    def __init__(self, trading_engine):
        super().__init__()
        self.trading_engine = trading_engine
        self.running = False
        self.ws = None
        self.current_prices = {}
        
        # 로거 초기화
        self.logger = logging.getLogger(__name__)
        
        # 배치 처리를 위한 변수들
        self.price_buffer = {}
        self.last_emit_time = 0
        self.emit_interval = 1.0  # 1초마다 배치 처리
        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self._emit_batched_prices)
        self.update_timer.start(int(self.emit_interval * 1000))

    def run(self):
        """바이낸스 웹소켓으로 실시간 가격 스트림"""
        import websocket
        import json
        import threading
        
        self.running = True
        
        # 메모리 최적화: 핵심 심볼만 선택 (최대 10개)
        core_symbols = [symbol.lower() for symbol in Config.SUPPORTED_PAIRS[:10]]
        streams = [f"{symbol}@ticker" for symbol in core_symbols]
        stream_url = f"wss://stream.binance.com:9443/ws/{'/'.join(streams)}"
        
        self.logger.info(f"🌐 핵심 심볼 {len(core_symbols)}개 구독 (메모리 최적화)")
        
        print(f"🌐 실시간 가격 웹소켓 연결 중... ({len(core_symbols)}개 심볼)")
        
        def on_message(ws, message):
            try:
                # 메시지 크기 체크 (너무 큰 메시지 무시)
                if len(message) > 10000:  # 10KB 이상 메시지 무시
                    return
                    
                data = json.loads(message)
                if 'stream' in data:
                    # 멀티 스트림 형태
                    stream_data = data['data']
                    symbol = stream_data['s']  # 심볼
                    price = float(stream_data['c'])  # 현재가
                else:
                    # 단일 스트림 형태
                    symbol = data['s']
                    price = float(data['c'])
                
                # 가격 변화량 체크 (너무 작은 변화는 무시)
                if symbol in self.current_prices:
                    try:
                        price_change = abs(price - self.current_prices[symbol]) / self.current_prices[symbol]
                        if price_change < 0.0001:  # 0.01% 미만 변화 무시
                            return
                    except (ZeroDivisionError, TypeError):
                        pass  # 계산 오류 시 무시하고 계속
                
                # 가격을 버퍼에 저장 (즉시 emit하지 않음)
                self.price_buffer[symbol] = price
                self.current_prices[symbol] = price
                
            except Exception as e:
                error_msg = f"웹소켓 메시지 처리 오류: {e}"
                if hasattr(self, 'logger'):
                    self.logger.error(error_msg)
                else:
                    print(error_msg)

        def on_error(ws, error):
            if hasattr(self, 'logger'):
                self.logger.error(f"웹소켓 에러: {error}")
            else:
                print(f"웹소켓 에러: {error}")
            # 연결 제한 - 너무 많은 에러 시 중지
            if not hasattr(self, 'error_count'):
                self.error_count = 0
            self.error_count += 1
            if self.error_count > 10:
                self.running = False

        def on_close(ws, close_status_code, close_msg):
            if hasattr(self, 'logger'):
                self.logger.info("가격 웹소켓 연결 종료")
            else:
                print("가격 웹소켓 연결 종료")
            # 메모리 정리
            if hasattr(self, 'price_buffer'):
                self.price_buffer.clear()

        def on_open(ws):
            if hasattr(self, 'logger'):
                self.logger.info("✅ 실시간 가격 웹소켓 연결 성공!")
            else:
                print("✅ 실시간 가격 웵소켓 연결 성공!")
            # 에러 카운터 리셋
            self.error_count = 0

        # 웹소콓 생성 및 실행 (메모리 최적화 옵션 적용)
        self.ws = websocket.WebSocketApp(
            stream_url,
            on_open=on_open,
            on_message=on_message,
            on_error=on_error,
            on_close=on_close
        )
        
        # 웹소켓 실행 (메모리 최적화 옵션)
        self.ws.run_forever(
            ping_interval=30,    # 30초마다 ping
            ping_timeout=10,     # 10초 타임아웃
            reconnect=3          # 최대 3번 재연결
        )

    def _emit_batched_prices(self):
        """배치 처리된 가격 업데이트 emit"""
        if self.price_buffer:
            # 복사본 생성 후 버퍼 초기화
            prices_to_emit = self.price_buffer.copy()
            self.price_buffer.clear()
            
            # GUI에 배치 처리된 가격 전송
            self.price_updated.emit(prices_to_emit)
    
    def stop(self):
        self.running = False
        if hasattr(self, 'update_timer'):
            self.update_timer.stop()
        if self.ws:
            self.ws.close()
        self.wait()

class TradingGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.trading_engine = TradingEngine()
        self.cross_position_manager = CrossPositionManager()
        base_futures_client = BinanceFuturesClient()
        self.futures_client = retry_wrapper.create_resilient_client(base_futures_client)

        # 🤖 트레이딩봇 시스템
        self.trading_bots = {}  # 여러 봇 관리
        self.active_bot = None
        self.advanced_bot = None

        self.current_prices = {}
        
        # 백그라운드 워커 초기화
        self.background_worker = None
        self.update_manager = None
        
        # 로깅 설정
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(Config.LOG_FILE),
                logging.StreamHandler()
            ]
        )

        # 로거 인스턴스 생성
        self.logger = logging.getLogger(__name__)

        self.init_ui()
        self.init_price_thread()
        self.init_background_worker()

    def init_ui(self):
        """UI 초기화 - 바이낸스 스타일 (창 크기 최적화)"""
        self.setWindowTitle("🪙 Genius Coin Manager - 실시간 차트 + 호가창 🚀")
        self.setGeometry(100, 100, 1920, 1080)  # 창 크기 증가 (Full HD 해상도)

        # 중앙 위젯 설정
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        # 메인 레이아웃 (수직)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setSpacing(0)
        main_layout.setContentsMargins(0, 0, 0, 0)

        # 차트 위젯 초기화 (가장 먼저)
        self.chart_widget = CandlestickChart(self.trading_engine)

        # 상단 바이낸스 스타일 헤더
        header = self.create_binance_header()
        main_layout.addWidget(header)
        
        # 메인 탭 위젯
        main_tabs = self.create_binance_main_tabs()
        main_layout.addWidget(main_tabs)
        
        # 상태바 숨기기
        self.statusBar().hide()

        # 차트 자동 업데이트 스레드
        self.chart_update_thread = ChartUpdateThread(self.chart_widget)
        self.chart_update_thread.update_signal.connect(self.chart_widget.update_chart)
        self.chart_update_thread.start()

        # 스타일 적용
        self.apply_binance_exchange_theme()

        # 지연 로딩 - 초기 데이터는 백그라운드에서 처리
        QTimer.singleShot(1000, self._delayed_initial_load)  # 1초 후 로드

    def closeEvent(self, event):
        """애플리케이션 종료 시 정리 작업"""
        try:
            # 백그라운드 워커 정지
            if hasattr(self, 'background_worker') and self.background_worker:
                self.background_worker.stop()
            
            # 업데이트 매니저 정지
            if hasattr(self, 'update_manager') and self.update_manager:
                self.update_manager.stop()
            
            # 가격 업데이트 스레드 정지
            if hasattr(self, 'price_thread'):
                self.price_thread.stop()

            # 차트 업데이트 스레드 정지
            if hasattr(self, 'chart_update_thread'):
                self.chart_update_thread.terminate()

            # 호가창 WebSocket 정리 🚀
            if hasattr(self, 'order_book_widget'):
                self.order_book_widget.closeEvent(event)

            # 트레이딩봇 정지
            if self.active_bot:
                self.stop_trading_bot()

            self.logger.info("🏁 Genius Coin Manager (바이낸스 테스트넷 + 트레이딩봇 + 호가창) 종료")

        except Exception as e:
            self.logger.error(f"애플리케이션 종료 중 오류: {e}")

        super().closeEvent(event)
    
    def init_background_worker(self):
        """백그라운드 워커 초기화"""
        # 백그라운드 워커 생성
        self.background_worker = BackgroundWorker(
            self.trading_engine,
            self.futures_client,
            self.cross_position_manager
        )
        
        # 시그널 연결
        self.background_worker.portfolio_updated.connect(self._handle_portfolio_update)
        self.background_worker.positions_updated.connect(self._handle_positions_update)
        self.background_worker.error_occurred.connect(self._handle_background_error)
        
        # 업데이트 매니저 생성
        self.update_manager = OptimizedUpdateManager(self)
        
        # 백그라운드 워커 시작
        self.background_worker.start()
        
        self.logger.info("📡 백그라운드 워커 초기화 완료")
    
    def _delayed_initial_load(self):
        """지연 초기 데이터 로드"""
        try:
            # 작고 가벼운 초기 데이터만 로드
            summary, _ = self.trading_engine.get_portfolio_status()
            if summary:
                self.balance_label.setText(f"잔고: ${summary['total_value']:,.2f}")
            
            self.logger.info("🚀 지연 초기 로드 완료")
        except Exception as e:
            self.logger.warning(f"초기 로드 오류: {e}")
    
    def _handle_portfolio_update(self, portfolio_data):
        """백그라운드에서 전송된 포트폴리오 데이터 처리"""
        try:
            summary = portfolio_data.get('summary')
            futures_balance = portfolio_data.get('futures_balance', {'balance': 0})
            total_futures_pnl = portfolio_data.get('total_futures_pnl', 0)
            
            if summary:
                # 현물 + 바이낸스 선물 총 자산 계산
                spot_value = summary['total_value']
                futures_value = futures_balance.get('balance', 0) + total_futures_pnl
                total_combined_value = spot_value + futures_value
                
                # UI 업데이트
                self.balance_label.setText(f"잔고: ${total_combined_value:,.2f}")
                
                # 쫌드 색상 계산
                total_invested = summary.get('total_invested', 1)
                total_pnl = total_combined_value - total_invested
                pnl_percentage = (total_pnl / total_invested) * 100 if total_invested > 0 else 0
                
                if total_pnl >= 0:
                    pnl_color = "#0ecb81"  # 초록
                else:
                    pnl_color = "#f6465d"  # 빨간
                
                # P&L 레이블 업데이트
                if hasattr(self, 'pnl_label'):
                    self.pnl_label.setText(f"P&L: ${total_pnl:,.2f} ({pnl_percentage:+.2f}%)")
                    self.pnl_label.setStyleSheet(f"font-size: 16px; color: {pnl_color}; margin-left: 10px;")
        
        except Exception as e:
            self.logger.error(f"포트폴리오 업데이트 처리 오류: {e}")
    
    def _handle_positions_update(self, positions_data):
        """백그라운드에서 전송된 포지션 데이터 처리"""
        try:
            if hasattr(self, 'leverage_history_table'):
                self._update_positions_table(positions_data)
        except Exception as e:
            self.logger.error(f"포지션 업데이트 처리 오류: {e}")
    
    def _handle_background_error(self, error_message):
        """백그라운드 오류 처리"""
        self.logger.error(f"백그라운드 오류: {error_message}")
    
    def update_prices_batch(self, prices):
        """배치 처리된 가격 업데이트 (기존 update_prices 대체)"""
        try:
            # 가격 데이터 업데이트
            self.current_prices.update(prices)
            
            # 현재 선택된 심볼의 가격만 업데이트
            if hasattr(self, 'symbol_combo'):
                current_symbol = self.symbol_combo.currentText()
                if current_symbol in prices:
                    current_price = prices[current_symbol]
                    
                    # 가격 레이블 업데이트
                    if hasattr(self, 'price_label'):
                        self.price_label.setText(f"${current_price:,.4f}")
            
            # 현물 및 레버리지 P&L 업데이트
            self.update_trading_history_pnl()
            self.update_leverage_positions_pnl()
            
            # 원래 함수에서 필수적인 부분만 유지
            if hasattr(self, 'update_manager'):
                self.update_manager.request_prices_update()
                
        except Exception as e:
            self.logger.error(f"배치 가격 업데이트 오류: {e}")

    def apply_binance_theme(self):
        """바이낸스 스타일 테마 적용"""
        self.setStyleSheet("""
            QMainWindow {
                background-color: #0b0e11;
                color: #f0f0f0;
            }
            QWidget {
                background-color: #0b0e11;
                color: #f0f0f0;
            }
            QFrame {
                background-color: #1e2329;
                border: 1px solid #2b3139;
                border-radius: 4px;
            }
            QGroupBox {
                font-weight: bold;
                border: 1px solid #2b3139;
                border-radius: 4px;
                margin-top: 10px;
                padding-top: 15px;
                background-color: #1e2329;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 8px 0 8px;
                color: #f0f0f0;
                font-size: 12px;
            }
            QTableWidget {
                background-color: #1e2329;
                alternate-background-color: #2b3139;
                selection-background-color: #4a4a4a;
                gridline-color: #2b3139;
                border: 1px solid #2b3139;
                border-radius: 4px;
            }
            QTableWidget::item {
                padding: 8px;
                border-bottom: 1px solid #2b3139;
            }
            QHeaderView::section {
                background-color: #2b3139;
                padding: 8px;
                border: none;
                border-right: 1px solid #0b0e11;
                font-weight: bold;
                color: #f0f0f0;
            }
            QLineEdit {
                background-color: #2b3139;
                border: 1px solid #474d57;
                border-radius: 4px;
                padding: 14px;
                color: #f0f0f0;
                font-size: 16px;
            }
            QLineEdit:focus {
                border: 1px solid #f0b90b;
            }
            QComboBox {
                background-color: #2b3139;
                border: 1px solid #474d57;
                border-radius: 4px;
                padding: 14px;
                color: #f0f0f0;
                font-size: 16px;
            }
            QComboBox:focus {
                border: 1px solid #f0b90b;
            }
            QComboBox::drop-down {
                border: none;
                width: 20px;
            }
            QComboBox::down-arrow {
                image: none;
                border-left: 5px solid transparent;
                border-right: 5px solid transparent;
                border-top: 5px solid #f0f0f0;
            }
            QPushButton {
                background-color: #2b3139;
                border: 1px solid #474d57;
                border-radius: 4px;
                padding: 16px 24px;
                font-weight: bold;
                color: #f0f0f0;
                font-size: 16px;
            }
            QPushButton:hover {
                background-color: #474d57;
                border: 1px solid #f0b90b;
            }
            QPushButton:pressed {
                background-color: #1e2329;
            }
            QLabel {
                color: #f0f0f0;
            }
        """)

    def create_header(self):
        """상단 헤더 생성 (바이낸스 스타일) - 크기 최적화"""
        header = QFrame()
        header.setFixedHeight(120)  # 높이 더 크게 증가
        header.setStyleSheet("""
            QFrame {
                background-color: #1e2329;
                border: 1px solid #2b3139;
                border-radius: 6px;
                margin: 2px;
            }
        """)

        layout = QHBoxLayout(header)
        layout.setContentsMargins(15, 20, 15, 20)  # 여백 더 크게 증가

        # 왼쪽: 코인 정보 (더 컴팩트하게)
        left_section = QHBoxLayout()  # 수직 → 수평으로 변경

        # 코인 아이콘
        self.coin_icon = QLabel("₿")
        self.coin_icon.setStyleSheet("""
            font-size: 20px;
            color: #f7931a;
            font-weight: bold;
        """)
        left_section.addWidget(self.coin_icon)

        # 심볼 선택 (헤더용)
        self.header_symbol_combo = QComboBox()
        self.header_symbol_combo.addItems(Config.SUPPORTED_PAIRS)
        self.header_symbol_combo.currentTextChanged.connect(self.on_main_symbol_changed)
        self.header_symbol_combo.setStyleSheet("""
            QComboBox {
                font-size: 14px;
                font-weight: bold;
                background-color: transparent;
                border: none;
                color: #f0f0f0;
            }
        """)
        left_section.addWidget(self.header_symbol_combo)

        # 가격
        self.main_price_label = QLabel("$117,799.99")
        self.main_price_label.setStyleSheet("""
            font-size: 22px; 
            font-weight: bold; 
            color: #f0f0f0;
            margin-left: 10px;
        """)
        left_section.addWidget(self.main_price_label)

        # 변동률
        self.price_change_label = QLabel("+85.99 (+0.07%)")
        self.price_change_label.setStyleSheet("""
            font-size: 14px;
            color: #0ecb81;
            margin-left: 8px;
        """)
        left_section.addWidget(self.price_change_label)

        left_section.addStretch()
        layout.addLayout(left_section, 1)

        # 오른쪽: 포트폴리오 요약 (더 컴팩트하게)
        right_section = QHBoxLayout()  # 수직 → 수평으로 변경

        self.total_value_label = QLabel("총 자산: $10,000.00")
        self.total_value_label.setStyleSheet("font-size: 12px; color: #f0f0f0;")
        right_section.addWidget(self.total_value_label)

        right_section.addWidget(QLabel(" | "))  # 구분자

        self.profit_loss_label = QLabel("총 손익: +$0.00 (0.00%)")
        self.profit_loss_label.setStyleSheet("font-size: 12px; color: #0ecb81;")
        right_section.addWidget(self.profit_loss_label)

        layout.addLayout(right_section)

        return header

    def create_right_trading_panel(self):
        """호가창 아래 거래 패널 - 매수/레버리지/봇 기능"""
        panel = QFrame()
        panel.setStyleSheet("""
            QFrame {
                background-color: #1e2329;
                border: 1px solid #2b3139;
                border-radius: 6px;
                margin: 2px;
            }
        """)
        
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(10, 10, 10, 10)
        
        # 탭 위젯 추가
        tab_widget = QTabWidget()
        tab_widget.setStyleSheet("""
            QTabWidget::pane {
                border: 1px solid #2b3139;
                background-color: #1e2329;
                border-radius: 4px;
            }
            QTabBar::tab {
                background-color: #2b3139;
                color: #f0f0f0;
                padding: 8px 12px;
                margin-right: 1px;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
                font-size: 11px;
            }
            QTabBar::tab:selected {
                background-color: #f0b90b;
                color: #000;
                font-weight: bold;
            }
        """)
        
        # 현물 거래 탭
        spot_tab = self.create_compact_spot_tab()
        tab_widget.addTab(spot_tab, "💰 현물")
        
        # 레버리지 거래 탭
        leverage_tab = self.create_compact_leverage_tab()
        tab_widget.addTab(leverage_tab, "🚀 레버리지")
        
        # 트레이딩봇 탭
        bot_tab = self.create_compact_bot_tab()
        tab_widget.addTab(bot_tab, "🤖 봇")
        
        layout.addWidget(tab_widget)
        return panel

    def create_trading_history_panel(self):
        """하단 거래내역 패널"""
        panel = QFrame()
        panel.setFixedHeight(300)
        panel.setStyleSheet("""
            QFrame {
                background-color: #1e2329;
                border: 1px solid #2b3139;
                border-radius: 6px;
                margin: 2px;
            }
        """)
        
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(15, 15, 15, 15)
        
        # 탭 위젯 추가
        tab_widget = QTabWidget()
        tab_widget.setStyleSheet("""
            QTabWidget::pane {
                border: 1px solid #2b3139;
                background-color: #1e2329;
                border-radius: 4px;
            }
            QTabBar::tab {
                background-color: #2b3139;
                color: #f0f0f0;
                padding: 12px 20px;
                margin-right: 2px;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
            }
            QTabBar::tab:selected {
                background-color: #f0b90b;
                color: #000;
                font-weight: bold;
            }
        """)
        
        # 현물 보유내역 탭
        spot_history_tab = self.create_spot_history_tab()
        tab_widget.addTab(spot_history_tab, "💰 현물 보유내역")
        
        # 레버리지 보유현황 탭
        leverage_history_tab = self.create_leverage_history_tab()
        tab_widget.addTab(leverage_history_tab, "🚀 레버리지 보유현황")
        
        # 봇 거래내역 탭
        bot_history_tab = self.create_bot_history_tab()
        tab_widget.addTab(bot_history_tab, "🤖 봇 거래내역")
        
        layout.addWidget(tab_widget)
        return panel

    def create_bottom_panel(self):
        """하단 거래 패널 생성 - 레버리지 거래 추가"""
        panel = QFrame()
        panel.setFixedHeight(350)  # 하단 패널 높이 대폭 증가
        panel.setStyleSheet("""
            QFrame {
                background-color: #1e2329;
                border: 1px solid #2b3139;
                border-radius: 6px;
                margin: 2px;
            }
        """)

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(15, 20, 15, 20)  # 여백 더 크게 증가

        # 탭 위젯 추가
        tab_widget = QTabWidget()
        tab_widget.setStyleSheet("""
            QTabWidget::pane {
                border: 1px solid #2b3139;
                background-color: #1e2329;
                border-radius: 4px;
            }
            QTabBar::tab {
                background-color: #2b3139;
                color: #f0f0f0;
                padding: 20px 28px;
                margin-right: 2px;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
            }
            QTabBar::tab:selected {
                background-color: #f0b90b;
                color: #000;
                font-weight: bold;
            }
            QTabBar::tab:hover {
                background-color: #474d57;
            }
        """)

        # 현물 거래 탭
        spot_tab = self.create_spot_trading_tab()
        tab_widget.addTab(spot_tab, "💰 현물 거래")

        # 레버리지 거래 탭
        leverage_tab = self.create_leverage_trading_tab()
        tab_widget.addTab(leverage_tab, "🚀 레버리지 거래")

        # 트레이딩봇 탭
        bot_tab = self.create_trading_bot_tab()
        tab_widget.addTab(bot_tab, "🤖 트레이딩봇")

        layout.addWidget(tab_widget)
        return panel

    def create_spot_trading_tab(self):
        """현물 거래 탭"""
        tab = QWidget()
        layout = QHBoxLayout(tab)
        layout.setContentsMargins(20, 20, 20, 20)  # 여백 더 크게 증가

        # 왼쪽: 매수 섹션
        buy_section = QHBoxLayout()

        buy_label = QLabel("💰 매수:")
        buy_label.setStyleSheet("font-size: 14px; font-weight: bold; color: #0ecb81;")  # 폰트 크기 증가
        buy_section.addWidget(buy_label)

        self.quick_buy_input = QLineEdit()
        self.quick_buy_input.setPlaceholderText("USD 금액")
        self.quick_buy_input.setMaximumWidth(150)  # 너비 더 크게 증가
        buy_section.addWidget(self.quick_buy_input)

        self.quick_buy_btn = QPushButton("🚀 매수")
        self.quick_buy_btn.setStyleSheet("""
            QPushButton {
                background-color: #0ecb81;
                color: white;
                font-size: 16px;
                font-weight: bold;
                padding: 16px 20px;
                border: none;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #0bb86f;
            }
        """)
        self.quick_buy_btn.clicked.connect(self.execute_quick_buy)
        buy_section.addWidget(self.quick_buy_btn)

        layout.addLayout(buy_section, 1)

        # 구분선
        separator = QFrame()
        separator.setFrameShape(QFrame.VLine)
        separator.setStyleSheet("color: #2b3139;")
        layout.addWidget(separator)

        # 오른쪽: 매도 섹션
        sell_section = QHBoxLayout()

        sell_label = QLabel("💸 매도:")
        sell_label.setStyleSheet("font-size: 14px; font-weight: bold; color: #f6465d;")  # 폰트 크기 증가
        sell_section.addWidget(sell_label)

        self.quick_sell_input = QLineEdit()
        self.quick_sell_input.setPlaceholderText("비율 (%)")
        self.quick_sell_input.setMaximumWidth(150)  # 너비 더 크게 증가
        sell_section.addWidget(self.quick_sell_input)

        self.quick_sell_btn = QPushButton("📉 매도")
        self.quick_sell_btn.setStyleSheet("""
            QPushButton {
                background-color: #f6465d;
                color: white;
                font-size: 16px;  # 폰트 크기 더 증가
                font-weight: bold;
                padding: 16px 20px;  # 패딩 더 크게 증가
                border: none;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #f23645;
            }
        """)
        self.quick_sell_btn.clicked.connect(self.execute_quick_sell)
        sell_section.addWidget(self.quick_sell_btn)

        layout.addLayout(sell_section, 1)

        return tab

    def create_leverage_trading_tab(self):
        """레버리지 거래 탭"""
        tab = QWidget()
        layout = QHBoxLayout(tab)
        layout.setContentsMargins(20, 20, 20, 20)  # 여백 더 크게 증가

        # 레버리지 설정
        leverage_section = QVBoxLayout()
        leverage_label = QLabel("⚡ 레버리지:")
        leverage_label.setStyleSheet("font-size: 13px; font-weight: bold; color: #f0b90b;")  # 폰트 크기 증가
        leverage_section.addWidget(leverage_label)

        self.leverage_combo = QComboBox()
        self.leverage_combo.addItems(["1x", "2x", "3x", "5x", "10x", "20x", "50x", "75x", "100x", "125x"])
        self.leverage_combo.setCurrentText("10x")
        self.leverage_combo.setMaximumWidth(150)  # 너비 증가
        self.leverage_combo.setStyleSheet("""
            QComboBox {
                font-size: 13px;  # 폰트 크기 증가
                font-weight: bold;
                background-color: #2b3139;
                border: 1px solid #f0b90b;
                border-radius: 3px;
                padding: 6px;  # 패딩 증가
            }
        """)
        leverage_section.addWidget(self.leverage_combo)
        layout.addLayout(leverage_section)

        # 롱 포지션
        long_section = QVBoxLayout()
        long_label = QLabel("📈 롱:")
        long_label.setStyleSheet("font-size: 13px; font-weight: bold; color: #0ecb81;")  # 폰트 크기 증가
        long_section.addWidget(long_label)

        self.long_amount_input = QLineEdit()
        self.long_amount_input.setPlaceholderText("USD")
        self.long_amount_input.setMaximumWidth(120)  # 너비 더 크게 증가
        long_section.addWidget(self.long_amount_input)

        self.long_btn = QPushButton("🚀 롱")
        self.long_btn.setStyleSheet("""
            QPushButton {
                background-color: #0ecb81;
                color: white;
                font-size: 15px;  # 폰트 크기 더 증가
                font-weight: bold;
                padding: 14px 18px;  # 패딩 더 크게 증가
                border: none;
                border-radius: 3px;
            }
            QPushButton:hover {
                background-color: #0bb86f;
            }
        """)
        self.long_btn.clicked.connect(self.execute_long_position)
        long_section.addWidget(self.long_btn)
        layout.addLayout(long_section)

        # 구분선
        separator1 = QFrame()
        separator1.setFrameShape(QFrame.VLine)
        separator1.setStyleSheet("color: #2b3139;")
        layout.addWidget(separator1)

        # 숏 포지션
        short_section = QVBoxLayout()
        short_label = QLabel("📉 숏:")
        short_label.setStyleSheet("font-size: 13px; font-weight: bold; color: #f6465d;")  # 폰트 크기 증가
        short_section.addWidget(short_label)

        self.short_amount_input = QLineEdit()
        self.short_amount_input.setPlaceholderText("USD")
        self.short_amount_input.setMaximumWidth(120)  # 너비 더 크게 증가
        short_section.addWidget(self.short_amount_input)

        self.short_btn = QPushButton("📉 숏")
        self.short_btn.setStyleSheet("""
            QPushButton {
                background-color: #f6465d;
                color: white;
                font-size: 15px;  # 폰트 크기 더 증가
                font-weight: bold;
                padding: 14px 18px;  # 패딩 더 크게 증가
                border: none;
                border-radius: 3px;
            }
            QPushButton:hover {
                background-color: #f23645;
            }
        """)
        self.short_btn.clicked.connect(self.execute_short_position)
        short_section.addWidget(self.short_btn)
        layout.addLayout(short_section)

        # 구분선
        separator2 = QFrame()
        separator2.setFrameShape(QFrame.VLine)
        separator2.setStyleSheet("color: #2b3139;")
        layout.addWidget(separator2)

        # 포지션 관리
        manage_section = QVBoxLayout()
        manage_label = QLabel("🎯 관리:")
        manage_label.setStyleSheet("font-size: 13px; font-weight: bold; color: #f0f0f0;")  # 폰트 크기 증가
        manage_section.addWidget(manage_label)

        self.close_position_btn = QPushButton("❌ 청산")
        self.close_position_btn.setStyleSheet("""
            QPushButton {
                background-color: #ff7043;
                color: white;
                font-size: 13px;  # 폰트 크기 증가
                font-weight: bold;
                padding: 10px 14px;  # 패딩 증가
                border: none;
                border-radius: 3px;
            }
            QPushButton:hover {
                background-color: #ff5722;
            }
        """)
        self.close_position_btn.clicked.connect(self.close_current_position)
        manage_section.addWidget(self.close_position_btn)

        self.view_positions_btn = QPushButton("📊 포지션")
        self.view_positions_btn.setStyleSheet("""
            QPushButton {
                background-color: #2196f3;
                color: white;
                font-size: 13px;  # 폰트 크기 증가
                font-weight: bold;
                padding: 10px 14px;  # 패딩 증가
                border: none;
                border-radius: 3px;
            }
            QPushButton:hover {
                background-color: #1976d2;
            }
        """)
        self.view_positions_btn.clicked.connect(self.show_positions_dialog)
        manage_section.addWidget(self.view_positions_btn)
        layout.addLayout(manage_section)

        layout.addStretch()
        return tab

    def create_trading_bot_tab(self):
        """트레이딩봇 탭"""
        tab = QWidget()
        layout = QHBoxLayout(tab)
        layout.setContentsMargins(20, 20, 20, 20)  # 여백 더 크게 증가

        # 봇 설정
        bot_config_section = QVBoxLayout()
        bot_config_label = QLabel("🤖 봇 설정:")
        bot_config_label.setStyleSheet("font-size: 13px; font-weight: bold; color: #f0b90b;")  # 폰트 크기 증가
        bot_config_section.addWidget(bot_config_label)

        self.bot_symbol_combo = QComboBox()
        self.bot_symbol_combo.addItems(Config.SUPPORTED_PAIRS)
        self.bot_symbol_combo.setCurrentText("SOLUSDT")  # SOL을 기본값으로
        self.bot_symbol_combo.setMaximumWidth(180)
        self.bot_symbol_combo.setMinimumHeight(40)
        self.bot_symbol_combo.setStyleSheet("""
            QComboBox {
                font-size: 16px;
                background-color: #2b3139;
                border: 1px solid #f0b90b;
                border-radius: 5px;
                padding: 10px;
                min-height: 40px;
            }
        """)
        bot_config_section.addWidget(self.bot_symbol_combo)

        # 전략 선택 추가
        strategy_label = QLabel("📈 전략:")
        strategy_label.setStyleSheet("font-size: 12px; font-weight: bold; color: #00ff88;")
        bot_config_section.addWidget(strategy_label)

        self.bot_strategy_combo = QComboBox()
        self.bot_strategy_combo.addItems([
            "macd_final", "ma_crossover", "rsi_leverage",
            "bollinger_band", "momentum_spike", "triple_ma"
        ])
        self.bot_strategy_combo.setCurrentText("macd_final")
        self.bot_strategy_combo.setMaximumWidth(180)
        self.bot_strategy_combo.setMinimumHeight(40)
        self.bot_strategy_combo.setStyleSheet("""
            QComboBox {
                font-size: 16px;
                background-color: #2b3139;
                border: 1px solid #00ff88;
                border-radius: 5px;
                padding: 10px;
                min-height: 40px;
            }
        """)
        bot_config_section.addWidget(self.bot_strategy_combo)

        self.bot_amount_input = QLineEdit()
        self.bot_amount_input.setPlaceholderText("$200")
        self.bot_amount_input.setText("200")
        self.bot_amount_input.setMaximumWidth(180)
        self.bot_amount_input.setMinimumHeight(40)
        self.bot_amount_input.setStyleSheet("""
            QLineEdit {
                font-size: 16px;
                background-color: #2b3139;
                border: 1px solid #f0b90b;
                border-radius: 5px;
                padding: 10px;
                min-height: 40px;
                color: white;
            }
        """)
        bot_config_section.addWidget(self.bot_amount_input)
        layout.addLayout(bot_config_section)

        # 전략 파라미터 설정
        param_section = QVBoxLayout()
        param_label = QLabel("⚙️ 파라미터:")
        param_label.setStyleSheet("font-size: 13px; font-weight: bold; color: #ff9800;")
        param_section.addWidget(param_label)

        # 레버리지 설정
        leverage_label = QLabel("레버리지:")
        leverage_label.setStyleSheet("font-size: 11px; color: #f0f0f0;")
        param_section.addWidget(leverage_label)

        self.bot_leverage_combo = QComboBox()
        self.bot_leverage_combo.addItems(["1x", "2x", "3x", "5x", "10x"])
        self.bot_leverage_combo.setCurrentText("3x")
        self.bot_leverage_combo.setMaximumWidth(120)
        self.bot_leverage_combo.setMinimumHeight(35)
        self.bot_leverage_combo.setStyleSheet("""
            QComboBox {
                font-size: 14px;
                background-color: #2b3139;
                border: 1px solid #ff9800;
                border-radius: 5px;
                padding: 8px;
                min-height: 35px;
            }
        """)
        param_section.addWidget(self.bot_leverage_combo)

        # 포지션 크기
        position_label = QLabel("포지션(%):")
        position_label.setStyleSheet("font-size: 11px; color: #f0f0f0;")
        param_section.addWidget(position_label)

        self.bot_position_input = QLineEdit()
        self.bot_position_input.setPlaceholderText("30")
        self.bot_position_input.setText("30")
        self.bot_position_input.setMaximumWidth(120)
        self.bot_position_input.setMinimumHeight(35)
        self.bot_position_input.setStyleSheet("""
            QLineEdit {
                font-size: 14px;
                background-color: #2b3139;
                border: 1px solid #ff9800;
                border-radius: 5px;
                padding: 8px;
                min-height: 35px;
                color: white;
            }
        """)
        param_section.addWidget(self.bot_position_input)

        layout.addLayout(param_section)

        # 봇 제어
        bot_control_section = QVBoxLayout()
        bot_control_label = QLabel("🎮 제어:")
        bot_control_label.setStyleSheet("font-size: 13px; font-weight: bold; color: #00ff88;")  # 폰트 크기 증가
        bot_control_section.addWidget(bot_control_label)

        self.start_bot_btn = QPushButton("▶️ 시작")
        self.start_bot_btn.setStyleSheet("""
            QPushButton {
                background-color: #00C851;
                color: white;
                font-size: 16px;
                font-weight: bold;
                padding: 15px 25px;
                border: none;
                border-radius: 5px;
                min-width: 120px;
                min-height: 45px;
            }
            QPushButton:hover {
                background-color: #00A043;
            }
        """)
        self.start_bot_btn.clicked.connect(self.start_trading_bot)
        bot_control_section.addWidget(self.start_bot_btn)

        self.stop_bot_btn = QPushButton("⏹️ 정지")
        self.stop_bot_btn.setStyleSheet("""
            QPushButton {
                background-color: #ff4444;
                color: white;
                font-size: 16px;
                font-weight: bold;
                padding: 15px 25px;
                border: none;
                border-radius: 5px;
                min-width: 120px;
                min-height: 45px;
            }
            QPushButton:hover {
                background-color: #ff3333;
            }
        """)
        self.stop_bot_btn.clicked.connect(self.stop_trading_bot)
        self.stop_bot_btn.setEnabled(False)
        bot_control_section.addWidget(self.stop_bot_btn)
        layout.addLayout(bot_control_section)

        # 구분선
        separator1 = QFrame()
        separator1.setFrameShape(QFrame.VLine)
        separator1.setStyleSheet("color: #2b3139;")
        layout.addWidget(separator1)

        # 봇 상태
        bot_status_section = QVBoxLayout()
        bot_status_label = QLabel("📊 상태:")
        bot_status_label.setStyleSheet("font-size: 13px; font-weight: bold; color: #f0f0f0;")  # 폰트 크기 증가
        bot_status_section.addWidget(bot_status_label)

        self.bot_status_label = QLabel("정지됨")
        self.bot_status_label.setStyleSheet("font-size: 12px; color: #ff4444;")  # 폰트 크기 증가
        bot_status_section.addWidget(self.bot_status_label)

        self.bot_trades_label = QLabel("거래: 0회")
        self.bot_trades_label.setStyleSheet("font-size: 12px; color: #f0f0f0;")  # 폰트 크기 증가
        bot_status_section.addWidget(self.bot_trades_label)

        self.bot_pnl_label = QLabel("손익: $0.00")
        self.bot_pnl_label.setStyleSheet("font-size: 12px; color: #f0f0f0;")  # 폰트 크기 증가
        bot_status_section.addWidget(self.bot_pnl_label)

        self.bot_strategy_label = QLabel("전략: 없음")
        self.bot_strategy_label.setStyleSheet("font-size: 11px; color: #888;")
        bot_status_section.addWidget(self.bot_strategy_label)

        layout.addLayout(bot_status_section)

        # 구분선
        separator2 = QFrame()
        separator2.setFrameShape(QFrame.VLine)
        separator2.setStyleSheet("color: #2b3139;")
        layout.addWidget(separator2)

        # 봇 관리
        bot_manage_section = QVBoxLayout()
        bot_manage_label = QLabel("⚙️ 관리:")
        bot_manage_label.setStyleSheet("font-size: 13px; font-weight: bold; color: #f0f0f0;")  # 폰트 크기 증가
        bot_manage_section.addWidget(bot_manage_label)

        self.bot_settings_btn = QPushButton("⚙️ 설정")
        self.bot_settings_btn.setStyleSheet("""
            QPushButton {
                background-color: #2196f3;
                color: white;
                font-size: 13px;  # 폰트 크기 증가
                font-weight: bold;
                padding: 10px 14px;  # 패딩 증가
                border: none;
                border-radius: 3px;
            }
            QPushButton:hover {
                background-color: #1976d2;
            }
        """)
        self.bot_settings_btn.clicked.connect(self.show_bot_settings)
        bot_manage_section.addWidget(self.bot_settings_btn)

        self.bot_log_btn = QPushButton("📋 로그")
        self.bot_log_btn.setStyleSheet("""
            QPushButton {
                background-color: #ff9800;
                color: white;
                font-size: 13px;  # 폰트 크기 증가
                font-weight: bold;
                padding: 10px 14px;  # 패딩 증가
                border: none;
                border-radius: 3px;
            }
            QPushButton:hover {
                background-color: #f57c00;
            }
        """)
        self.bot_log_btn.clicked.connect(self.show_bot_log)
        bot_manage_section.addWidget(self.bot_log_btn)
        layout.addLayout(bot_manage_section)

        layout.addStretch()
        return tab

    def create_compact_spot_tab(self):
        """호가창 아래 현물 거래 탭 (컴팩트)"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(5, 5, 5, 5)
        
        # 심볼 선택
        symbol_layout = QHBoxLayout()
        symbol_layout.addWidget(QLabel("코인:"))
        self.compact_symbol_combo = QComboBox()
        self.compact_symbol_combo.addItems(Config.SUPPORTED_PAIRS)
        self.compact_symbol_combo.setCurrentText("SOLUSDT")
        symbol_layout.addWidget(self.compact_symbol_combo)
        layout.addLayout(symbol_layout)
        
        # 수량 입력
        amount_layout = QHBoxLayout()
        amount_layout.addWidget(QLabel("수량:"))
        self.compact_amount_input = QLineEdit("100")
        amount_layout.addWidget(self.compact_amount_input)
        layout.addLayout(amount_layout)
        
        # 매수/매도 버튼
        button_layout = QHBoxLayout()
        buy_btn = QPushButton("💰 매수")
        buy_btn.setStyleSheet("QPushButton { background-color: #00C851; color: white; padding: 8px; }")
        buy_btn.clicked.connect(self.compact_spot_buy)
        
        sell_btn = QPushButton("📉 매도")
        sell_btn.setStyleSheet("QPushButton { background-color: #ff4444; color: white; padding: 8px; }")
        sell_btn.clicked.connect(self.compact_spot_sell)
        
        button_layout.addWidget(buy_btn)
        button_layout.addWidget(sell_btn)
        layout.addLayout(button_layout)
        
        return tab

    def create_compact_leverage_tab(self):
        """호가창 아래 레버리지 거래 탭 (컴팩트)"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(5, 5, 5, 5)
        
        # 심볼 선택
        symbol_layout = QHBoxLayout()
        symbol_layout.addWidget(QLabel("코인:"))
        self.compact_lev_symbol_combo = QComboBox()
        self.compact_lev_symbol_combo.addItems(Config.SUPPORTED_PAIRS)
        symbol_layout.addWidget(self.compact_lev_symbol_combo)
        layout.addLayout(symbol_layout)
        
        # 레버리지/수량
        settings_layout = QHBoxLayout()
        settings_layout.addWidget(QLabel("레버리지:"))
        self.compact_lev_combo = QComboBox()
        self.compact_lev_combo.addItems(["1x", "2x", "3x", "5x", "10x"])
        self.compact_lev_combo.setCurrentText("3x")
        settings_layout.addWidget(self.compact_lev_combo)
        
        settings_layout.addWidget(QLabel("수량:"))
        self.compact_lev_amount_input = QLineEdit("100")
        settings_layout.addWidget(self.compact_lev_amount_input)
        layout.addLayout(settings_layout)
        
        # 롱/숏 버튼
        button_layout = QHBoxLayout()
        long_btn = QPushButton("🚀 롱")
        long_btn.setStyleSheet("QPushButton { background-color: #00C851; color: white; padding: 8px; }")
        long_btn.clicked.connect(self.compact_leverage_long)
        
        short_btn = QPushButton("📉 숏")
        short_btn.setStyleSheet("QPushButton { background-color: #ff4444; color: white; padding: 8px; }")
        short_btn.clicked.connect(self.compact_leverage_short)
        
        button_layout.addWidget(long_btn)
        button_layout.addWidget(short_btn)
        layout.addLayout(button_layout)
        
        return tab

    def create_compact_bot_tab(self):
        """호가창 아래 트레이딩봇 탭 (컴팩트)"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(5, 5, 5, 5)
        
        # 전략 선택
        strategy_layout = QHBoxLayout()
        strategy_layout.addWidget(QLabel("전략:"))
        self.compact_bot_strategy_combo = QComboBox()
        self.compact_bot_strategy_combo.addItems([
            "macd_final", "ma_crossover", "rsi_leverage",
            "bollinger_band", "momentum_spike", "triple_ma"
        ])
        strategy_layout.addWidget(self.compact_bot_strategy_combo)
        layout.addLayout(strategy_layout)
        
        # 수량 입력
        amount_layout = QHBoxLayout()
        amount_layout.addWidget(QLabel("수량:"))
        self.compact_bot_amount_input = QLineEdit("200")
        amount_layout.addWidget(self.compact_bot_amount_input)
        layout.addLayout(amount_layout)
        
        # 시작/정지 버튼
        button_layout = QHBoxLayout()
        start_btn = QPushButton("▶️ 시작")
        start_btn.setStyleSheet("QPushButton { background-color: #00C851; color: white; padding: 8px; }")
        start_btn.clicked.connect(self.start_trading_bot)
        
        stop_btn = QPushButton("⏹️ 정지")
        stop_btn.setStyleSheet("QPushButton { background-color: #ff4444; color: white; padding: 8px; }")
        stop_btn.clicked.connect(self.stop_trading_bot)
        
        button_layout.addWidget(start_btn)
        button_layout.addWidget(stop_btn)
        layout.addLayout(button_layout)
        
        return tab

    def create_spot_history_tab(self):
        """현물 보유내역 탭"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        # 보유내역 테이블
        self.spot_history_table = QTableWidget()
        self.spot_history_table.setColumnCount(5)
        self.spot_history_table.setHorizontalHeaderLabels([
            "코인", "수량", "구매가", "현재가", "손익"
        ])
        self.spot_history_table.setStyleSheet("""
            QTableWidget {
                background-color: #2b3139;
                alternate-background-color: #1e2329;
                color: white;
                gridline-color: #404040;
            }
            QHeaderView::section {
                background-color: #f0b90b;
                color: black;
                font-weight: bold;
                padding: 8px;
            }
        """)
        layout.addWidget(self.spot_history_table)
        
        # 초기 데이터 로드
        self.load_spot_history()
        
        return tab

    def create_leverage_history_tab(self):
        """레버리지 보유현황 탭"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        # 헤더
        header_layout = QHBoxLayout()
        header_label = QLabel("🚀 레버리지 포지션 보유현황")
        header_label.setStyleSheet("color: white; font-size: 14px; font-weight: bold; padding: 10px;")
        header_layout.addWidget(header_label)
        
        # 새로고침 버튼 제거 - 실시간 업데이트로 불필요
        
        header_layout.addStretch()
        layout.addLayout(header_layout)
        
        # 보유현황 테이블 (상태 콜럼 제거)
        self.leverage_history_table = QTableWidget()
        self.leverage_history_table.setColumnCount(8)
        self.leverage_history_table.setHorizontalHeaderLabels([
            "심볼", "방향", "레버리지", "진입가", "현재가", "수량", "손익(USDT)", "손익률(%)"
        ])
        self.leverage_history_table.setStyleSheet("""
            QTableWidget {
                background-color: #2b3139;
                alternate-background-color: #1e2329;
                color: white;
                gridline-color: #404040;
            }
            QHeaderView::section {
                background-color: #f0b90b;
                color: black;
                font-weight: bold;
                padding: 8px;
            }
        """)
        layout.addWidget(self.leverage_history_table)
        
        # 초기 데이터 로드
        self.refresh_leverage_positions()
        
        return tab
    
    def refresh_leverage_positions(self):
        """레버리지 포지션 새로고침"""
        try:
            print("🔄 레버리지 포지션 새로고침 중...")
            
            # 활성 포지션 가져오기
            active_positions = self.cross_position_manager.get_active_positions()
            
            # 테이블 초기화
            self.leverage_history_table.setRowCount(0)
            
            if not active_positions:
                # 포지션이 없을 때 메시지 표시
                self.leverage_history_table.setRowCount(1)
                no_position_item = QTableWidgetItem("현재 보유 중인 레버리지 포지션이 없습니다.")
                no_position_item.setTextAlignment(Qt.AlignCenter)
                self.leverage_history_table.setSpan(0, 0, 1, 9)
                self.leverage_history_table.setItem(0, 0, no_position_item)
                return
            
            # 포지션별로 행 추가
            self.leverage_history_table.setRowCount(len(active_positions))
            
            for row, position in enumerate(active_positions):
                try:
                    # 현재가 가져오기
                    current_price = self.current_prices.get(position['symbol'], position['entry_price'])
                    
                    # 손익 계산
                    if position['side'].upper() == 'LONG':
                        pnl_usdt = (current_price - position['entry_price']) * position['quantity']
                        pnl_percent = ((current_price / position['entry_price']) - 1) * 100 * position['leverage']
                    else:  # SHORT
                        pnl_usdt = (position['entry_price'] - current_price) * position['quantity']
                        pnl_percent = ((position['entry_price'] / current_price) - 1) * 100 * position['leverage']
                    
                    # 테이블 아이템 설정
                    items = [
                        position['symbol'],
                        "🟢 롱" if position['side'].upper() == 'LONG' else "🔴 숏",
                        f"{position['leverage']}x",
                        f"${position['entry_price']:,.2f}",
                        f"${current_price:,.2f}",
                        f"{position['quantity']:.6f}",
                        f"${pnl_usdt:,.2f}",
                        f"{pnl_percent:+.2f}%",
                        "🟢 활성" if pnl_usdt >= 0 else "🔴 손실"
                    ]
                    
                    for col, item_text in enumerate(items):
                        item = QTableWidgetItem(str(item_text))
                        item.setTextAlignment(Qt.AlignCenter)
                        
                        # 손익에 따른 색상 설정
                        if col == 6 or col == 7:  # 손익 USDT, 손익률
                            if pnl_usdt >= 0:
                                item.setForeground(QColor('#0ecb81'))  # 초록색
                            else:
                                item.setForeground(QColor('#f6465d'))  # 빨간색
                        elif col == 1:  # 방향
                            if "롱" in item_text:
                                item.setForeground(QColor('#0ecb81'))
                            else:
                                item.setForeground(QColor('#f6465d'))
                        else:
                            item.setForeground(QColor('white'))
                        
                        self.leverage_history_table.setItem(row, col, item)
                        
                except Exception as e:
                    print(f"포지션 {row} 처리 오류: {e}")
                    continue
            
            # 테이블 열 너비 자동 조정
            self.leverage_history_table.resizeColumnsToContents()
            
            print(f"✅ 레버리지 포지션 {len(active_positions)}개 로드 완료")
            
        except Exception as e:
            print(f"❌ 레버리지 포지션 새로고침 오류: {e}")
            QMessageBox.warning(self, "오류", f"포지션 로드 중 오류가 발생했습니다:\n{e}")

    def create_bot_history_tab(self):
        """봇 거래내역 탭"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        # 거래내역 테이블
        self.bot_history_table = QTableWidget()
        self.bot_history_table.setColumnCount(7)
        self.bot_history_table.setHorizontalHeaderLabels([
            "시간", "코인", "전략", "유형", "수량", "가격", "손익"
        ])
        self.bot_history_table.setStyleSheet("""
            QTableWidget {
                background-color: #2b3139;
                alternate-background-color: #1e2329;
                color: white;
                gridline-color: #404040;
            }
            QHeaderView::section {
                background-color: #f0b90b;
                color: black;
                font-weight: bold;
                padding: 8px;
            }
        """)
        layout.addWidget(self.bot_history_table)
        
        return tab

    def compact_spot_buy(self):
        """컴팩트 현물 매수"""
        try:
            symbol = self.compact_symbol_combo.currentText()
            amount = float(self.compact_amount_input.text())
            
            if amount <= 0:
                QMessageBox.warning(self, "입력 오류", "올바른 금액을 입력해주세요.")
                return
                
            # 현재 가격 가져오기
            current_price = self.trading_engine.get_current_price(symbol)
            if not current_price:
                QMessageBox.warning(self, "가격 오류", f"{symbol} 가격을 가져올 수 없습니다.")
                return
                
            quantity = amount / current_price
            
            # 매수 실행
            success = self.trading_engine.place_buy_order(
                symbol=symbol,
                amount_usd=amount
            )
            
            if success:
                QMessageBox.information(self, "매수 완료", 
                                      f"{symbol} ${amount:.2f} 매수 완료\n"
                                      f"수량: {quantity:.6f}\n"
                                      f"가격: ${current_price:.4f}")
                self.update_portfolio_display()
            else:
                QMessageBox.warning(self, "매수 실패", "매수 주문이 실패했습니다.")
                
        except ValueError:
            QMessageBox.warning(self, "입력 오류", "올바른 숫자를 입력해주세요.")
        except Exception as e:
            QMessageBox.critical(self, "오류", f"매수 중 오류가 발생했습니다:\n{e}")

    def compact_spot_sell(self):
        """컴팩트 현물 매도"""
        try:
            symbol = self.compact_symbol_combo.currentText()
            amount = float(self.compact_amount_input.text())
            
            if amount <= 0:
                QMessageBox.warning(self, "입력 오류", "올바른 금액을 입력해주세요.")
                return
                
            # 현재 가격 가져오기
            current_price = self.trading_engine.get_current_price(symbol)
            if not current_price:
                QMessageBox.warning(self, "가격 오류", f"{symbol} 가격을 가져올 수 없습니다.")
                return
                
            quantity = amount / current_price
            
            # 매도 실행  
            success = self.trading_engine.place_sell_order(
                symbol=symbol,
                quantity=quantity
            )
            
            if success:
                QMessageBox.information(self, "매도 완료", 
                                      f"{symbol} ${amount:.2f} 매도 완료\n"
                                      f"수량: {quantity:.6f}\n"
                                      f"가격: ${current_price:.4f}")
                self.update_portfolio_display()
            else:
                QMessageBox.warning(self, "매도 실패", "매도 주문이 실패했습니다.")
                
        except ValueError:
            QMessageBox.warning(self, "입력 오류", "올바른 숫자를 입력해주세요.")
        except Exception as e:
            QMessageBox.critical(self, "오류", f"매도 중 오류가 발생했습니다:\n{e}")

    def compact_leverage_long(self):
        """컴팩트 레버리지 롱"""
        try:
            symbol = self.compact_lev_symbol_combo.currentText()
            amount = float(self.compact_lev_amount_input.text())
            leverage_text = self.compact_lev_combo.currentText()
            leverage = int(leverage_text.replace('x', ''))
            
            if amount <= 0:
                QMessageBox.warning(self, "입력 오류", "올바른 금액을 입력해주세요.")
                return
                
            # 레버리지 롱 포지션 열기
            current_price = self.trading_engine.get_current_price(symbol)
            quantity = amount / current_price
            margin_required = amount / leverage
            
            success = self.cross_position_manager.open_position(
                symbol=symbol,
                side='LONG',
                quantity=quantity,
                price=current_price,
                leverage=leverage,
                margin_required=margin_required
            )
            
            if success:
                QMessageBox.information(self, "롱 포지션 오픈", 
                                      f"{symbol} 롱 포지션 오픈\n"
                                      f"금액: ${amount:.2f}\n"
                                      f"레버리지: {leverage}x")
                self.update_portfolio_display()
            else:
                QMessageBox.warning(self, "포지션 실패", "롱 포지션 오픈이 실패했습니다.")
                
        except ValueError:
            QMessageBox.warning(self, "입력 오류", "올바른 숫자를 입력해주세요.")
        except Exception as e:
            QMessageBox.critical(self, "오류", f"롱 포지션 오픈 중 오류가 발생했습니다:\n{e}")

    def compact_leverage_short(self):
        """컴팩트 레버리지 숏"""
        try:
            symbol = self.compact_lev_symbol_combo.currentText()
            amount = float(self.compact_lev_amount_input.text())
            leverage_text = self.compact_lev_combo.currentText()
            leverage = int(leverage_text.replace('x', ''))
            
            if amount <= 0:
                QMessageBox.warning(self, "입력 오류", "올바른 금액을 입력해주세요.")
                return
                
            # 레버리지 숏 포지션 열기
            current_price = self.trading_engine.get_current_price(symbol)
            quantity = amount / current_price
            margin_required = amount / leverage
            
            success = self.cross_position_manager.open_position(
                symbol=symbol,
                side='SHORT',
                quantity=quantity,
                price=current_price,
                leverage=leverage,
                margin_required=margin_required
            )
            
            if success:
                QMessageBox.information(self, "숏 포지션 오픈", 
                                      f"{symbol} 숏 포지션 오픈\n"
                                      f"금액: ${amount:.2f}\n"
                                      f"레버리지: {leverage}x")
                self.update_portfolio_display()
            else:
                QMessageBox.warning(self, "포지션 실패", "숏 포지션 오픈이 실패했습니다.")
                
        except ValueError:
            QMessageBox.warning(self, "입력 오류", "올바른 숫자를 입력해주세요.")
        except Exception as e:
            QMessageBox.critical(self, "오류", f"숏 포지션 오픈 중 오류가 발생했습니다:\n{e}")

    def create_binance_header(self):
        """바이낸스 스타일 상단 헤더"""
        header = QFrame()
        header.setFixedHeight(60)
        header.setStyleSheet("""
            QFrame {
                background-color: #1e2329;
                border-bottom: 1px solid #2b3139;
            }
        """)
        
        layout = QHBoxLayout(header)
        layout.setContentsMargins(20, 10, 20, 10)
        
        # 왼쪽: 코인 정보
        left_section = QHBoxLayout()
        
        # 코인 심볼
        self.symbol_label = QLabel("BTCUSDT")
        self.symbol_label.setStyleSheet("""
            QLabel {
                color: white;
                font-size: 16px;
                font-weight: bold;
            }
        """)
        left_section.addWidget(self.symbol_label)
        
        # 현재 가격
        self.current_price_label = QLabel("$118334.5900")
        self.current_price_label.setStyleSheet("""
            QLabel {
                color: #0ecb81;
                font-size: 24px;
                font-weight: bold;
                margin-left: 20px;
            }
        """)
        left_section.addWidget(self.current_price_label)
        
        # 변화율
        self.change_label = QLabel("- 504 candles - Last update: 02:29:58")
        self.change_label.setStyleSheet("""
            QLabel {
                color: #848e9c;
                font-size: 12px;
                margin-left: 10px;
            }
        """)
        left_section.addWidget(self.change_label)
        
        layout.addLayout(left_section)
        layout.addStretch()
        
        # 오른쪽: 사용자 정보
        self.balance_label = QLabel("잔고: $0.00")
        self.balance_label.setStyleSheet("""
            QLabel {
                color: #f0b90b;
                font-size: 14px;
                font-weight: bold;
            }
        """)
        layout.addWidget(self.balance_label)
        
        return header

    def create_binance_main_tabs(self):
        """바이낸스 스타일 메인 탭"""
        main_container = QFrame()
        main_container.setStyleSheet("QFrame { background-color: #0b0e11; }")
        
        layout = QVBoxLayout(main_container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # 상단 탭 바 제거됨
        
        # 메인 컨텐츠 영역
        content_area = QHBoxLayout()
        content_area.setContentsMargins(0, 0, 0, 0)
        content_area.setSpacing(0)
        
        # 왼쪽: 거래 패널들
        left_panel = self.create_binance_left_panel()
        content_area.addWidget(left_panel, 1)
        
        # 중앙: 차트
        chart_panel = self.create_binance_chart_panel()
        content_area.addWidget(chart_panel, 3)
        
        # 오른쪽: 호가창
        right_panel = self.create_binance_right_panel()
        content_area.addWidget(right_panel, 1)
        
        layout.addLayout(content_area)
        
        # 하단: 거래내역
        bottom_panel = self.create_binance_bottom_panel()
        layout.addWidget(bottom_panel)
        
        return main_container

    def create_binance_tab_bar(self):
        """바이낸스 스타일 탭 바"""
        tab_container = QFrame()
        tab_container.setFixedHeight(50)
        tab_container.setStyleSheet("""
            QFrame {
                background-color: #1e2329;
                border-bottom: 1px solid #2b3139;
            }
        """)
        
        layout = QHBoxLayout(tab_container)
        layout.setContentsMargins(20, 0, 20, 0)
        
        # 탭 버튼들
        tabs = [
            ("🔒 Spot 보유", True),
            ("⚡ Cross 포지션", False),
            ("📊 Spot 거래", False),
            ("🚀 Cross 내역", False),
            ("🤖 트레이딩봇", False)
        ]
        
        for tab_name, is_active in tabs:
            btn = QPushButton(tab_name)
            if is_active:
                btn.setStyleSheet("""
                    QPushButton {
                        background-color: #f0b90b;
                        color: black;
                        border: none;
                        padding: 12px 20px;
                        font-weight: bold;
                        border-radius: 4px;
                    }
                """)
            else:
                btn.setStyleSheet("""
                    QPushButton {
                        background-color: transparent;
                        color: #848e9c;
                        border: none;
                        padding: 12px 20px;
                    }
                    QPushButton:hover {
                        background-color: #2b3139;
                        color: white;
                    }
                """)
            layout.addWidget(btn)
        
        layout.addStretch()
        return tab_container

    def create_binance_left_panel(self):
        """바이낸스 스타일 왼쪽 거래 패널"""
        panel = QFrame()
        panel.setMaximumWidth(350)
        panel.setStyleSheet("""
            QFrame {
                background-color: #1e2329;
                border-right: 1px solid #2b3139;
            }
        """)
        
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(15, 15, 15, 15)
        
        # 심볼 선택 제거 - 헤더의 심볼 콤보박스만 사용
        # 호환성을 위해 main_symbol_combo를 header_symbol_combo로 연결
        if hasattr(self, 'header_symbol_combo'):
            self.main_symbol_combo = self.header_symbol_combo  # 호환성을 위해 변수 연결
        
        # 거래 유형 탭
        trade_tabs = QTabWidget()
        trade_tabs.setStyleSheet("""
            QTabWidget::pane {
                border: 1px solid #2b3139;
                background-color: #1e2329;
            }
            QTabBar::tab {
                background-color: #2b3139;
                color: #848e9c;
                padding: 10px 20px;
                margin-right: 2px;
            }
            QTabBar::tab:selected {
                background-color: #f0b90b;
                color: black;
                font-weight: bold;
            }
        """)
        
        # 현물 거래 탭
        spot_tab = self.create_binance_spot_tab()
        trade_tabs.addTab(spot_tab, "현물")
        
        # 레버리지 거래 탭
        leverage_tab = self.create_binance_leverage_tab()
        trade_tabs.addTab(leverage_tab, "레버리지")
        
        # 트레이딩봇 탭
        if ADVANCED_BOT_AVAILABLE:
            trading_bot_tab = self.create_trading_bot_tab()
            trade_tabs.addTab(trading_bot_tab, "🤖 트레이딩봇")
        
        layout.addWidget(trade_tabs)
        layout.addStretch()
        
        return panel

    def create_binance_chart_panel(self):
        """바이낸스 스타일 차트 패널"""
        panel = QFrame()
        panel.setStyleSheet("""
            QFrame {
                background-color: #0b0e11;
            }
        """)
        
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(10, 10, 10, 10)
        
        # 차트 헤더
        chart_header = QFrame()
        chart_header.setFixedHeight(40)
        chart_header.setStyleSheet("""
            QFrame {
                background-color: #1e2329;
                border-radius: 4px;
            }
        """)
        
        header_layout = QHBoxLayout(chart_header)
        header_layout.setContentsMargins(15, 0, 15, 0)
        
        # 차트 제어 버튼들
        controls = ["🔥 실시간", "📊 선형", "📈 상승", "📊 설정"]
        for control in controls:
            btn = QPushButton(control)
            btn.setStyleSheet("""
                QPushButton {
                    background-color: #2b3139;
                    color: white;
                    border: none;
                    padding: 8px 12px;
                    border-radius: 4px;
                    font-size: 12px;
                }
                QPushButton:hover {
                    background-color: #848e9c;
                }
            """)
            header_layout.addWidget(btn)
        
        header_layout.addStretch()
        layout.addWidget(chart_header)
        
        # 차트
        layout.addWidget(self.chart_widget)
        
        return panel

    def create_binance_right_panel(self):
        """바이낸스 스타일 오른쪽 호가창 패널"""
        panel = QFrame()
        panel.setMaximumWidth(300)
        panel.setStyleSheet("""
            QFrame {
                background-color: #1e2329;
                border-left: 1px solid #2b3139;
            }
        """)
        
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(15, 15, 15, 15)
        
        # 호가창 헤더
        header_label = QLabel("📊 호가창")
        header_label.setStyleSheet("""
            QLabel {
                color: white;
                font-size: 16px;
                font-weight: bold;
                margin-bottom: 10px;
            }
        """)
        layout.addWidget(header_label)
        
        # 호가창 위젯
        if ORDER_BOOK_AVAILABLE:
            self.order_book_widget = MatplotlibOrderBook(self.trading_engine)
            # 호가창 가격 클릭 시그널 연결
            self.order_book_widget.price_clicked.connect(self.on_orderbook_price_clicked)
            layout.addWidget(self.order_book_widget)
            
            # 현재 선택된 심볼로 초기화 (약간의 지연 후)
            # 콤보박스가 완전히 초기화된 후에 호가창 심볼 설정
            def init_orderbook_symbol():
                current_symbol = self.header_symbol_combo.currentText() if hasattr(self, 'header_symbol_combo') else "BTCUSDT"
                print(f"[호가창 초기화] 심볼: {current_symbol}")
                if hasattr(self, 'order_book_widget'):
                    self.order_book_widget.set_symbol(current_symbol)
            
            QTimer.singleShot(1000, init_orderbook_symbol)  # 1초 후 초기화
        else:
            placeholder = QLabel("호가창 모듈을 찾을 수 없습니다")
            placeholder.setAlignment(Qt.AlignCenter)
            placeholder.setStyleSheet("color: #848e9c; font-style: italic;")
            layout.addWidget(placeholder)
        
        return panel

    def create_binance_bottom_panel(self):
        """바이낸스 스타일 하단 거래내역 패널"""
        panel = QFrame()
        panel.setFixedHeight(250)
        panel.setStyleSheet("""
            QFrame {
                background-color: #1e2329;
                border-top: 1px solid #2b3139;
            }
        """)
        
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(15, 15, 15, 15)
        
        # 하단 탭 위젯
        bottom_tabs = QTabWidget()
        bottom_tabs.setStyleSheet("""
            QTabWidget::pane {
                border: 1px solid #2b3139;
                background-color: #1e2329;
            }
            QTabBar::tab {
                background-color: #2b3139;
                color: #848e9c;
                padding: 8px 16px;
                margin-right: 2px;
            }
            QTabBar::tab:selected {
                background-color: #f0b90b;
                color: black;
                font-weight: bold;
            }
        """)
        
        # 거래내역 탭들
        spot_history = self.create_spot_history_tab()
        bottom_tabs.addTab(spot_history, "현물 보유내역")
        
        leverage_history = self.create_leverage_history_tab()
        bottom_tabs.addTab(leverage_history, "레버리지 보유현황")
        
        bot_history = self.create_bot_history_tab()
        bottom_tabs.addTab(bot_history, "봇 거래내역")
        
        layout.addWidget(bottom_tabs)
        return panel

    def create_binance_spot_tab(self):
        """바이낸스 스타일 현물 거래 탭"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(10, 10, 10, 10)
        
        # 타입 선택
        type_layout = QHBoxLayout()
        limit_btn = QPushButton("지정가")
        market_btn = QPushButton("시장가")
        
        for btn in [limit_btn, market_btn]:
            btn.setStyleSheet("""
                QPushButton {
                    background-color: #2b3139;
                    color: white;
                    border: none;
                    padding: 8px 16px;
                    border-radius: 4px;
                }
                QPushButton:hover {
                    background-color: #848e9c;
                }
            """)
        
        market_btn.setStyleSheet(market_btn.styleSheet() + "background-color: #f0b90b; color: black;")
        
        type_layout.addWidget(limit_btn)
        type_layout.addWidget(market_btn)
        layout.addLayout(type_layout)
        
        # 가격 입력
        price_label = QLabel("가격")
        price_label.setStyleSheet("color: white; font-size: 12px;")
        layout.addWidget(price_label)
        
        self.spot_price_input = QLineEdit()
        self.spot_price_input.setPlaceholderText("시장가")
        self.spot_price_input.setStyleSheet("""
            QLineEdit {
                background-color: #2b3139;
                color: white;
                border: 1px solid #848e9c;
                padding: 8px;
                border-radius: 4px;
            }
        """)
        layout.addWidget(self.spot_price_input)
        
        # 수량 입력
        amount_label = QLabel("수량 (USDT)")
        amount_label.setStyleSheet("color: white; font-size: 12px;")
        layout.addWidget(amount_label)
        
        self.spot_amount_input = QLineEdit()
        self.spot_amount_input.setPlaceholderText("0.00")
        self.spot_amount_input.setStyleSheet(self.spot_price_input.styleSheet())
        layout.addWidget(self.spot_amount_input)
        
        # 자산 비율 슬라이더
        slider_label = QLabel("자산 비율")
        slider_label.setStyleSheet("color: white; font-size: 12px;")
        layout.addWidget(slider_label)
        
        self.asset_ratio_slider = QSlider(Qt.Horizontal)
        self.asset_ratio_slider.setMinimum(0)
        self.asset_ratio_slider.setMaximum(100)
        self.asset_ratio_slider.setValue(10)  # 기본값 10%
        self.asset_ratio_slider.setStyleSheet("""
            QSlider::groove:horizontal {
                border: 1px solid #848e9c;
                height: 8px;
                background: #2b3139;
                border-radius: 4px;
            }
            QSlider::handle:horizontal {
                background: #f0b90b;
                border: 1px solid #848e9c;
                width: 18px;
                margin: -5px 0;
                border-radius: 9px;
            }
            QSlider::sub-page:horizontal {
                background: #f0b90b;
                border-radius: 4px;
            }
        """)
        self.asset_ratio_slider.valueChanged.connect(self.on_slider_changed)
        layout.addWidget(self.asset_ratio_slider)
        
        # 슬라이더 값 표시
        self.slider_value_label = QLabel("10% (약 $0)")
        self.slider_value_label.setStyleSheet("color: #848e9c; font-size: 11px;")
        layout.addWidget(self.slider_value_label)
        
        # 매수/매도 버튼
        button_layout = QHBoxLayout()
        
        buy_btn = QPushButton("매수 BTC")
        buy_btn.setStyleSheet("""
            QPushButton {
                background-color: #0ecb81;
                color: white;
                border: none;
                padding: 12px;
                font-weight: bold;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #00a85a;
            }
        """)
        
        sell_btn = QPushButton("매도 BTC")
        sell_btn.setStyleSheet("""
            QPushButton {
                background-color: #f6465d;
                color: white;
                border: none;
                padding: 12px;
                font-weight: bold;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #d33f4a;
            }
        """)
        
        button_layout.addWidget(buy_btn)
        button_layout.addWidget(sell_btn)
        layout.addLayout(button_layout)
        
        buy_btn.clicked.connect(self.binance_spot_buy)
        sell_btn.clicked.connect(self.binance_spot_sell)
        
        layout.addStretch()
        return tab

    def create_binance_leverage_tab(self):
        """바이낸스 스타일 레버리지 거래 탭"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(10, 10, 10, 10)
        
        # 레버리지 설정
        leverage_layout = QHBoxLayout()
        leverage_label = QLabel("레버리지:")
        leverage_label.setStyleSheet("color: white; font-size: 12px;")
        leverage_layout.addWidget(leverage_label)
        
        self.leverage_combo = QComboBox()
        self.leverage_combo.addItems(["1x", "2x", "3x", "5x", "10x", "20x"])
        self.leverage_combo.setCurrentText("10x")
        self.leverage_combo.setStyleSheet("""
            QComboBox {
                background-color: #2b3139;
                color: white;
                border: 1px solid #848e9c;
                padding: 6px;
                border-radius: 4px;
            }
        """)
        leverage_layout.addWidget(self.leverage_combo)
        layout.addLayout(leverage_layout)
        
        # 가격 입력
        price_label = QLabel("가격 (USDT)")
        price_label.setStyleSheet("color: white; font-size: 12px;")
        layout.addWidget(price_label)
        
        self.lev_price_input = QLineEdit()
        self.lev_price_input.setPlaceholderText("시장가")
        self.lev_price_input.setStyleSheet("""
            QLineEdit {
                background-color: #2b3139;
                color: white;
                border: 1px solid #848e9c;
                padding: 8px;
                border-radius: 4px;
            }
        """)
        layout.addWidget(self.lev_price_input)
        
        # 수량 입력
        amount_label = QLabel("수량 (USDT)")
        amount_label.setStyleSheet("color: white; font-size: 12px;")
        layout.addWidget(amount_label)
        
        self.lev_amount_input = QLineEdit()
        self.lev_amount_input.setPlaceholderText("100.00")
        self.lev_amount_input.setStyleSheet("""
            QLineEdit {
                background-color: #2b3139;
                color: white;
                border: 1px solid #848e9c;
                padding: 8px;
                border-radius: 4px;
            }
        """)
        layout.addWidget(self.lev_amount_input)
        
        # 롱/숏 버튼
        button_layout = QHBoxLayout()
        
        long_btn = QPushButton("🚀 롱 오픈")
        long_btn.setStyleSheet("""
            QPushButton {
                background-color: #0ecb81;
                color: white;
                border: none;
                padding: 12px;
                font-weight: bold;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #00a85a;
            }
        """)
        
        short_btn = QPushButton("📉 숏 오픈")
        short_btn.setStyleSheet("""
            QPushButton {
                background-color: #f6465d;
                color: white;
                border: none;
                padding: 12px;
                font-weight: bold;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #d33f4a;
            }
        """)
        
        button_layout.addWidget(long_btn)
        button_layout.addWidget(short_btn)
        layout.addLayout(button_layout)
        
        long_btn.clicked.connect(self.binance_leverage_long)
        short_btn.clicked.connect(self.binance_leverage_short)
        
        layout.addStretch()
        return tab

    def create_trading_bot_tab(self):
        """트레이딩봇 컨트롤 탭"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(15)
        layout.setContentsMargins(15, 15, 15, 15)
        
        # 봇 상태 표시
        status_section = QVBoxLayout()
        
        status_label = QLabel("🤖 트레이딩봇 상태")
        status_label.setStyleSheet("color: white; font-size: 14px; font-weight: bold;")
        status_section.addWidget(status_label)
        
        self.bot_status_label = QLabel("중지됨 ⭕")
        self.bot_status_label.setStyleSheet("""
            QLabel {
                background-color: #2b3139;
                color: #f6465d;
                padding: 8px;
                border-radius: 4px;
                font-weight: bold;
            }
        """)
        status_section.addWidget(self.bot_status_label)
        layout.addLayout(status_section)
        
        # 전략 선택
        strategy_section = QVBoxLayout()
        
        strategy_label = QLabel("거래 전략")
        strategy_label.setStyleSheet("color: white; font-size: 12px;")
        strategy_section.addWidget(strategy_label)
        
        self.strategy_combo = QComboBox()
        self.strategy_combo.addItems(["macd_final", "rsi_bollinger", "ma_cross", "momentum"])
        self.strategy_combo.setStyleSheet("""
            QComboBox {
                background-color: #2b3139;
                color: white;
                border: 1px solid #848e9c;
                padding: 8px;
                border-radius: 4px;
            }
        """)
        strategy_section.addWidget(self.strategy_combo)
        layout.addLayout(strategy_section)
        
        # 레버리지 설정
        leverage_section = QVBoxLayout()
        
        leverage_label = QLabel("레버리지")
        leverage_label.setStyleSheet("color: white; font-size: 12px;")
        leverage_section.addWidget(leverage_label)
        
        self.bot_leverage_combo = QComboBox()
        self.bot_leverage_combo.addItems(["1x", "2x", "3x", "5x", "10x", "20x"])
        self.bot_leverage_combo.setCurrentText("3x")
        self.bot_leverage_combo.setStyleSheet("""
            QComboBox {
                background-color: #2b3139;
                color: white;
                border: 1px solid #848e9c;
                padding: 8px;
                border-radius: 4px;
            }
        """)
        leverage_section.addWidget(self.bot_leverage_combo)
        layout.addLayout(leverage_section)
        
        # 투자 금액
        amount_section = QVBoxLayout()
        
        amount_label = QLabel("투자 금액 (%)")
        amount_label.setStyleSheet("color: white; font-size: 12px;")
        amount_section.addWidget(amount_label)
        
        self.bot_amount_input = QLineEdit()
        self.bot_amount_input.setPlaceholderText("30.0")
        self.bot_amount_input.setText("30.0")
        self.bot_amount_input.setStyleSheet("""
            QLineEdit {
                background-color: #2b3139;
                color: white;
                border: 1px solid #848e9c;
                padding: 8px;
                border-radius: 4px;
            }
        """)
        amount_section.addWidget(self.bot_amount_input)
        layout.addLayout(amount_section)
        
        # 손절/익절 설정
        risk_section = QHBoxLayout()
        
        # 손절매
        stop_loss_layout = QVBoxLayout()
        stop_loss_label = QLabel("손절매 (%)")
        stop_loss_label.setStyleSheet("color: white; font-size: 10px;")
        stop_loss_layout.addWidget(stop_loss_label)
        
        self.stop_loss_input = QLineEdit()
        self.stop_loss_input.setPlaceholderText("-2.0")
        self.stop_loss_input.setText("-2.0")
        self.stop_loss_input.setStyleSheet("""
            QLineEdit {
                background-color: #2b3139;
                color: white;
                border: 1px solid #848e9c;
                padding: 6px;
                border-radius: 4px;
                font-size: 10px;
            }
        """)
        stop_loss_layout.addWidget(self.stop_loss_input)
        risk_section.addLayout(stop_loss_layout)
        
        # 익절매
        take_profit_layout = QVBoxLayout()
        take_profit_label = QLabel("익절매 (%)")
        take_profit_label.setStyleSheet("color: white; font-size: 10px;")
        take_profit_layout.addWidget(take_profit_label)
        
        self.take_profit_input = QLineEdit()
        self.take_profit_input.setPlaceholderText("8.0")
        self.take_profit_input.setText("8.0")
        self.take_profit_input.setStyleSheet("""
            QLineEdit {
                background-color: #2b3139;
                color: white;
                border: 1px solid #848e9c;
                padding: 6px;
                border-radius: 4px;
                font-size: 10px;
            }
        """)
        take_profit_layout.addWidget(self.take_profit_input)
        risk_section.addLayout(take_profit_layout)
        
        layout.addLayout(risk_section)
        
        # 봇 컨트롤 버튼
        button_layout = QHBoxLayout()
        
        self.start_bot_btn = QPushButton("🚀 봇 시작")
        self.start_bot_btn.setStyleSheet("""
            QPushButton {
                background-color: #0ecb81;
                color: white;
                border: none;
                padding: 12px;
                font-weight: bold;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #00a85a;
            }
        """)
        self.start_bot_btn.clicked.connect(self.start_trading_bot)
        button_layout.addWidget(self.start_bot_btn)
        
        self.stop_bot_btn = QPushButton("⏹️ 봇 중지")
        self.stop_bot_btn.setStyleSheet("""
            QPushButton {
                background-color: #f6465d;
                color: white;
                border: none;
                padding: 12px;
                font-weight: bold;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #d73747;
            }
        """)
        self.stop_bot_btn.clicked.connect(self.stop_trading_bot)
        self.stop_bot_btn.setEnabled(False)
        button_layout.addWidget(self.stop_bot_btn)
        
        layout.addLayout(button_layout)
        
        # 성과 표시
        performance_section = QVBoxLayout()
        
        perf_label = QLabel("📊 성과")
        perf_label.setStyleSheet("color: white; font-size: 12px; font-weight: bold;")
        performance_section.addWidget(perf_label)
        
        self.bot_performance_label = QLabel("거래: 0건 | 승률: 0% | 수익: 0 USDT")
        self.bot_performance_label.setStyleSheet("""
            QLabel {
                background-color: #2b3139;
                color: #fcd535;
                padding: 8px;
                border-radius: 4px;
                font-size: 10px;
            }
        """)
        performance_section.addWidget(self.bot_performance_label)
        layout.addLayout(performance_section)
        
        layout.addStretch()
        return tab

    def apply_binance_exchange_theme(self):
        """바이낸스 거래소 스타일 테마 적용"""
        self.setStyleSheet("""
            QMainWindow {
                background-color: #0b0e11;
                color: white;
            }
            QLabel {
                color: white;
            }
            QComboBox {
                background-color: #2b3139;
                color: white;
                border: 1px solid #848e9c;
                padding: 6px;
                border-radius: 4px;
            }
            QComboBox::drop-down {
                border: none;
            }
            QLineEdit {
                background-color: #2b3139;
                color: white;
                border: 1px solid #848e9c;
                padding: 6px;
                border-radius: 4px;
            }
            QTableWidget {
                background-color: #1e2329;
                alternate-background-color: #2b3139;
                color: white;
                gridline-color: #848e9c;
                border: none;
            }
            QHeaderView::section {
                background-color: #2b3139;
                color: white;
                font-weight: bold;
                padding: 8px;
                border: none;
            }
        """)

    def binance_spot_buy(self):
        """바이낸스 스타일 현물 매수"""
        try:
            symbol = self.header_symbol_combo.currentText() if hasattr(self, 'header_symbol_combo') else "BTCUSDT"
            amount_text = self.spot_amount_input.text().strip()
            
            if not amount_text:
                amount = 100.0  # 기본값
            else:
                amount = float(amount_text)
            
            success, message = self.trading_engine.place_buy_order(symbol=symbol, amount_usd=amount)
            if success:
                QMessageBox.information(self, "✅ 매수 성공", message or f"{symbol} ${amount:.2f} 매수 완료")
                self.spot_amount_input.clear()
                self.update_portfolio_display()
                # 거래내역 테이블 새로고침
                if hasattr(self, 'load_spot_history'):
                    self.load_spot_history()
            else:
                QMessageBox.warning(self, "❌ 매수 실패", message or "매수 주문이 실패했습니다.")
        except Exception as e:
            QMessageBox.critical(self, "오류", f"매수 중 오류가 발생했습니다:\n{e}")

    def binance_spot_sell(self):
        """바이낸스 스타일 현물 매도"""
        try:
            symbol = self.header_symbol_combo.currentText() if hasattr(self, 'header_symbol_combo') else "BTCUSDT"
            amount_text = self.spot_amount_input.text().strip()
            
            if not amount_text:
                success, message = self.trading_engine.place_sell_order(symbol=symbol, sell_all=True)
            else:
                current_price = self.trading_engine.get_current_price(symbol)
                if not current_price:
                    QMessageBox.warning(self, "가격 오류", f"{symbol} 가격을 가져올 수 없습니다.")
                    return
                quantity = float(amount_text) / current_price
                success, message = self.trading_engine.place_sell_order(symbol=symbol, quantity=quantity)
            
            if success:
                QMessageBox.information(self, "✅ 매도 성공", message or f"{symbol} 매도 완료")
                self.spot_amount_input.clear()
                self.update_portfolio_display()
                # 거래내역 테이블 새로고침
                if hasattr(self, 'load_spot_history'):
                    self.load_spot_history()
            else:
                QMessageBox.warning(self, "❌ 매도 실패", message or "매도 주문이 실패했습니다.")
        except Exception as e:
            QMessageBox.critical(self, "오류", f"매도 중 오류가 발생했습니다:\n{e}")

    def binance_leverage_long(self):
        """바이낸스 테스트넷 레버리지 롱 포지션"""
        try:
            symbol = self.header_symbol_combo.currentText() if hasattr(self, 'header_symbol_combo') else "BTCUSDT"
            amount_text = self.lev_amount_input.text().strip()
            leverage_text = self.leverage_combo.currentText().replace('x', '')
            
            # 수량 입력 필수 체크
            if not amount_text:
                QMessageBox.warning(self, "⚠️ 입력 오류", "거래 수량을 입력해주세요!")
                return
                
            try:
                amount = float(amount_text)
                if amount <= 0:
                    QMessageBox.warning(self, "⚠️ 입력 오류", "거래 수량은 0보다 커야 합니다!")
                    return
            except ValueError:
                QMessageBox.warning(self, "⚠️ 입력 오류", "올바른 숫자를 입력해주세요!")
                return
                
            leverage = int(leverage_text)
            
            current_price = self.current_prices.get(symbol, 0)
            if not current_price:
                QMessageBox.warning(self, "가격 오류", f"{symbol} 가격을 가져올 수 없습니다.")
                return
                
            # 실제 바이낸스 테스트넷 선물 거래
            notional_value = amount * leverage
            quantity = notional_value / current_price
            
            success, result = self.futures_client.create_futures_order(
                symbol=symbol,
                side='BUY',
                quantity=quantity,
                order_type='MARKET',
                leverage=leverage
            )
            
            if success:
                order_id = result.get('orderId', 'N/A')
                QMessageBox.information(self, "🚀 바이낸스 테스트넷 롱 성공", 
                                      f"✅ 바이낸스 테스트넷 선물 거래 성공!\n\n"
                                      f"📋 주문 ID: {order_id}\n"
                                      f"💰 심볼: {symbol}\n"
                                      f"📊 수량: {quantity:.6f}\n"
                                      f"💵 가격: ${current_price:,.2f}\n"
                                      f"🔥 레버리지: {leverage}x\n"
                                      f"💎 총 거래금액: ${notional_value:,.2f}")
                self.lev_amount_input.clear()
                
                # 레버리지 포지션 테이블 업데이트
                if hasattr(self, 'refresh_leverage_positions'):
                    self.refresh_leverage_positions()
            else:
                error_msg = result.get('msg', '알 수 없는 오류') if isinstance(result, dict) else str(result)
                QMessageBox.warning(self, "⚠️ 바이낸스 거래 실패", f"선물 거래 실패:\n{error_msg}")
                
        except Exception as e:
            QMessageBox.critical(self, "🚨 거래 오류", f"바이낸스 테스트넷 선물 거래 중 오류:\n{e}")

    def binance_leverage_short(self):
        """바이낸스 테스트넷 레버리지 숏 포지션"""
        try:
            symbol = self.header_symbol_combo.currentText() if hasattr(self, 'header_symbol_combo') else "BTCUSDT"
            amount_text = self.lev_amount_input.text().strip()
            leverage_text = self.leverage_combo.currentText().replace('x', '')
            
            # 수량 입력 필수 체크
            if not amount_text:
                QMessageBox.warning(self, "⚠️ 입력 오류", "거래 수량을 입력해주세요!")
                return
                
            try:
                amount = float(amount_text)
                if amount <= 0:
                    QMessageBox.warning(self, "⚠️ 입력 오류", "거래 수량은 0보다 커야 합니다!")
                    return
            except ValueError:
                QMessageBox.warning(self, "⚠️ 입력 오류", "올바른 숫자를 입력해주세요!")
                return
                
            leverage = int(leverage_text)
            
            current_price = self.current_prices.get(symbol, 0)
            if not current_price:
                QMessageBox.warning(self, "가격 오류", f"{symbol} 가격을 가져올 수 없습니다.")
                return
                
            # 실제 바이낸스 테스트넷 선물 거래
            notional_value = amount * leverage
            quantity = notional_value / current_price
            
            success, result = self.futures_client.create_futures_order(
                symbol=symbol,
                side='SELL',
                quantity=quantity,
                order_type='MARKET',
                leverage=leverage
            )
            
            if success:
                order_id = result.get('orderId', 'N/A')
                QMessageBox.information(self, "📉 바이낸스 테스트넷 숏 성공", 
                                      f"✅ 바이낸스 테스트넷 선물 거래 성공!\n\n"
                                      f"📋 주문 ID: {order_id}\n"
                                      f"💰 심볼: {symbol}\n"
                                      f"📊 수량: {quantity:.6f}\n"
                                      f"💵 가격: ${current_price:,.2f}\n"
                                      f"🔥 레버리지: {leverage}x\n"
                                      f"💎 총 거래금액: ${notional_value:,.2f}")
                self.lev_amount_input.clear()
                
                # 레버리지 포지션 테이블 업데이트
                if hasattr(self, 'refresh_leverage_positions'):
                    self.refresh_leverage_positions()
            else:
                error_msg = result.get('msg', '알 수 없는 오류') if isinstance(result, dict) else str(result)
                QMessageBox.warning(self, "⚠️ 바이낸스 거래 실패", f"선물 거래 실패:\n{error_msg}")
                
        except Exception as e:
            QMessageBox.critical(self, "🚨 거래 오류", f"바이낸스 테스트넷 선물 거래 중 오류:\n{e}")

    def load_spot_history(self):
        """현물 보유내역 로드"""
        try:
            import json
            
            # portfolio.json에서 보유 코인 정보 가져오기
            with open('data/portfolio.json', 'r') as f:
                portfolio = json.load(f)
            
            holdings = portfolio.get('holdings', {})
            
            # 거래내역에서 평균 구매가 계산
            with open('data/transactions.json', 'r') as f:
                transactions = json.load(f)
            
            # 각 코인별 평균 구매가 계산
            coin_purchase_info = {}
            for tx in transactions:
                if tx.get('type') == 'BUY':
                    symbol = tx.get('symbol', '').replace('USDT', '')
                    quantity = tx.get('quantity', 0)
                    price = tx.get('price', 0)
                    total_amount = tx.get('total_amount', 0)
                    
                    if symbol not in coin_purchase_info:
                        coin_purchase_info[symbol] = {
                            'total_quantity': 0,
                            'total_spent': 0
                        }
                    
                    coin_purchase_info[symbol]['total_quantity'] += quantity
                    coin_purchase_info[symbol]['total_spent'] += total_amount
            
            # 보유 중인 코인들만 테이블에 표시
            active_holdings = [(coin, amount) for coin, amount in holdings.items() if amount > 0.001]
            
            self.spot_history_table.setRowCount(len(active_holdings))
            
            for i, (coin, quantity) in enumerate(active_holdings):
                # 코인 이름
                self.spot_history_table.setItem(i, 0, QTableWidgetItem(coin))
                
                # 수량
                self.spot_history_table.setItem(i, 1, QTableWidgetItem(f"{quantity:.6f}"))
                
                # 평균 구매가 계산
                if coin in coin_purchase_info:
                    total_spent = coin_purchase_info[coin]['total_spent']
                    total_quantity = coin_purchase_info[coin]['total_quantity']
                    avg_purchase_price = total_spent / total_quantity if total_quantity > 0 else 0
                else:
                    avg_purchase_price = 0
                
                self.spot_history_table.setItem(i, 2, QTableWidgetItem(f"${avg_purchase_price:,.2f}"))
                
                # 현재가
                symbol = f"{coin}USDT"
                current_price = self.current_prices.get(symbol, 0)
                if current_price > 0:
                    self.spot_history_table.setItem(i, 3, QTableWidgetItem(f"${current_price:,.2f}"))
                    
                    # 손익 계산
                    if avg_purchase_price > 0:
                        current_value = current_price * quantity
                        purchase_value = avg_purchase_price * quantity
                        pnl = current_value - purchase_value
                        pnl_percent = ((current_price - avg_purchase_price) / avg_purchase_price) * 100
                        
                        pnl_text = f"${pnl:+,.2f} ({pnl_percent:+.1f}%)"
                        pnl_item = QTableWidgetItem(pnl_text)
                        
                        # 손익에 따른 색상 설정
                        if pnl > 0:
                            pnl_item.setForeground(QColor('#0ecb81'))  # 초록색
                        elif pnl < 0:
                            pnl_item.setForeground(QColor('#f6465d'))  # 빨간색
                        else:
                            pnl_item.setForeground(QColor('#848e9c'))  # 회색
                            
                        self.spot_history_table.setItem(i, 4, pnl_item)
                    else:
                        self.spot_history_table.setItem(i, 4, QTableWidgetItem("--"))
                else:
                    self.spot_history_table.setItem(i, 3, QTableWidgetItem("--"))
                    self.spot_history_table.setItem(i, 4, QTableWidgetItem("--"))
                    
        except Exception as e:
            print(f"보유내역 로드 오류: {e}")
            # 오류 발생 시 빈 테이블 표시
            if hasattr(self, 'spot_history_table'):
                self.spot_history_table.setRowCount(0)
    
    def update_trading_history_pnl(self):
        """보유내역의 실시간 P&L 업데이트"""
        try:
            if not hasattr(self, 'spot_history_table') or self.spot_history_table.rowCount() == 0:
                return
                
            for row in range(self.spot_history_table.rowCount()):
                # 코인 심볼 가져오기 (새로운 구조에서는 0번 컬럼)
                coin_item = self.spot_history_table.item(row, 0)
                if not coin_item:
                    continue
                    
                coin = coin_item.text()
                symbol = f"{coin}USDT"
                
                # 구매가 가져오기 (새로운 구조에서는 2번 컬럼)
                purchase_price_item = self.spot_history_table.item(row, 2)
                if not purchase_price_item or purchase_price_item.text() == "--":
                    continue
                    
                try:
                    purchase_price = float(purchase_price_item.text().replace('$', '').replace(',', ''))
                except:
                    continue
                
                # 수량 가져오기 (새로운 구조에서는 1번 컬럼)
                quantity_item = self.spot_history_table.item(row, 1)
                if not quantity_item:
                    continue
                    
                try:
                    quantity = float(quantity_item.text())
                except:
                    continue
                
                # 현재가 업데이트
                current_price = self.current_prices.get(symbol, 0)
                if current_price > 0:
                    # 현재가 표시 (3번 컬럼)
                    current_price_item = QTableWidgetItem(f"${current_price:,.2f}")
                    self.spot_history_table.setItem(row, 3, current_price_item)
                    
                    # 손익 계산
                    if purchase_price > 0:
                        current_value = current_price * quantity
                        purchase_value = purchase_price * quantity
                        pnl = current_value - purchase_value
                        pnl_percent = ((current_price - purchase_price) / purchase_price) * 100
                        
                        pnl_text = f"${pnl:+,.2f} ({pnl_percent:+.1f}%)"
                        pnl_item = QTableWidgetItem(pnl_text)
                        
                        # 손익에 따른 색상 설정
                        if pnl > 0:
                            pnl_item.setForeground(QColor('#0ecb81'))  # 초록색
                        elif pnl < 0:
                            pnl_item.setForeground(QColor('#f6465d'))  # 빨간색
                        else:
                            pnl_item.setForeground(QColor('#848e9c'))  # 회색
                            
                        self.spot_history_table.setItem(row, 4, pnl_item)
                    else:
                        self.spot_history_table.setItem(row, 4, QTableWidgetItem("--"))
                else:
                    # 현재가를 가져올 수 없는 경우
                    self.spot_history_table.setItem(row, 3, QTableWidgetItem("--"))
                    self.spot_history_table.setItem(row, 4, QTableWidgetItem("--"))
                    
        except Exception as e:
            print(f"보유내역 P&L 업데이트 오류: {e}")
    
    def update_leverage_positions_pnl(self):
        """레버리지 포지션의 실시간 P&L 업데이트"""
        try:
            if not hasattr(self, 'leverage_history_table') or self.leverage_history_table.rowCount() == 0:
                return
                
            for row in range(self.leverage_history_table.rowCount()):
                # 심볼 가져오기 (0번 콜럼)
                symbol_item = self.leverage_history_table.item(row, 0)
                if not symbol_item:
                    continue
                    
                symbol = symbol_item.text()
                
                # 방향 가져오기 (1번 콜럼)
                side_item = self.leverage_history_table.item(row, 1)
                if not side_item:
                    continue
                side = side_item.text()
                
                # 진입가 가져오기 (3번 콜럼)
                entry_price_item = self.leverage_history_table.item(row, 3)
                if not entry_price_item:
                    continue
                    
                try:
                    entry_price = float(entry_price_item.text().replace('$', '').replace(',', ''))
                except:
                    continue
                
                # 수량 가져오기 (5번 콜럼)
                quantity_item = self.leverage_history_table.item(row, 5)
                if not quantity_item:
                    continue
                    
                try:
                    quantity = float(quantity_item.text())
                except:
                    continue
                
                # 현재가 업데이트
                current_price = self.current_prices.get(symbol, entry_price)
                
                # 현재가 표시 (4번 콜럼)
                current_price_item = QTableWidgetItem(f"${current_price:,.2f}")
                self.leverage_history_table.setItem(row, 4, current_price_item)
                
                # 손익 계산
                if side.upper() == 'LONG':
                    pnl_usdt = (current_price - entry_price) * quantity
                    pnl_percent = ((current_price - entry_price) / entry_price) * 100
                else:  # SHORT
                    pnl_usdt = (entry_price - current_price) * quantity
                    pnl_percent = ((entry_price - current_price) / entry_price) * 100
                
                # 손익 표시 (6번 콜럼)
                pnl_item = QTableWidgetItem(f"${pnl_usdt:+,.2f}")
                if pnl_usdt >= 0:
                    pnl_item.setForeground(QColor("#0ecb81"))  # 초록
                else:
                    pnl_item.setForeground(QColor("#f6465d"))  # 빨간
                self.leverage_history_table.setItem(row, 6, pnl_item)
                
                # 손익률 표시 (7번 콜럼)
                pnl_percent_item = QTableWidgetItem(f"{pnl_percent:+.2f}%")
                if pnl_percent >= 0:
                    pnl_percent_item.setForeground(QColor("#0ecb81"))
                else:
                    pnl_percent_item.setForeground(QColor("#f6465d"))
                self.leverage_history_table.setItem(row, 7, pnl_percent_item)
                
        except Exception as e:
            print(f"레버리지 포지션 P&L 업데이트 오류: {e}")

    def load_leverage_history(self):
        """바이낸스 테스트넷 선물 포지션 및 거래내역 로드 (기존 호환성용)"""
        # 새로운 refresh_leverage_positions 함수로 대체
        if hasattr(self, 'refresh_leverage_positions'):
            self.refresh_leverage_positions()
            return
        
        # 기존 호환성을 위한 빈 함수
        print("레버리지 보유현황은 새로운 refresh_leverage_positions 함수를 사용합니다.")

    def create_menu_bar(self):
        """메뉴바 생성"""
        menubar = self.menuBar()
        menubar.setStyleSheet("""
            QMenuBar {
                background-color: #2b2b2b;
                color: white;
                border-bottom: 1px solid #555;
            }
            QMenuBar::item {
                padding: 5px 10px;
            }
            QMenuBar::item:selected {
                background-color: #4a4a4a;
            }
            QMenu {
                background-color: #2b2b2b;
                border: 1px solid #555;
            }
            QMenu::item {
                padding: 5px 20px;
            }
            QMenu::item:selected {
                background-color: #4a4a4a;
            }
        """)

        # 파일 메뉴
        file_menu = menubar.addMenu('파일')
        reset_action = QAction('포트폴리오 초기화', self)
        reset_action.triggered.connect(self.reset_portfolio)
        file_menu.addAction(reset_action)
        file_menu.addSeparator()
        exit_action = QAction('종료', self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        # 거래 메뉴
        trade_menu = menubar.addMenu('거래')
        trade_menu.addAction('빠른 매수', self.quick_buy)
        trade_menu.addAction('빠른 매도', self.quick_sell)
        trade_menu.addSeparator()
        trade_menu.addAction('🚀 롱 포지션', self.quick_long)
        trade_menu.addAction('📉 숏 포지션', self.quick_short)
        trade_menu.addAction('📊 포지션 현황', self.show_positions_dialog)
        trade_menu.addSeparator()
        trade_menu.addAction('🤖 봇 시작', self.start_trading_bot)
        trade_menu.addAction('🛑 봇 정지', self.stop_trading_bot)
        trade_menu.addAction('📊 봇 로그', self.show_bot_log)
        trade_menu.addSeparator()
        trade_menu.addAction('🔧 바이낸스 연결 테스트', self.test_binance_connection)
        trade_menu.addSeparator()
        trade_menu.addAction('전량 매도', self.sell_all_holdings)
        trade_menu.addAction('❌ 전체 포지션 청산', self.close_all_positions_menu)

        # 보기 메뉴
        view_menu = menubar.addMenu('보기')
        view_menu.addAction('전체화면', self.toggle_fullscreen)
        view_menu.addAction('차트 새로고침', lambda: self.chart_widget.update_chart())

        # 도움말 메뉴
        help_menu = menubar.addMenu('도움말')
        help_menu.addAction('정보', self.show_about)

    def init_price_thread(self):
        """최적화된 가격 업데이트 스레드 초기화"""
        self.price_thread = PriceUpdateThread(self.trading_engine)
        self.price_thread.price_updated.connect(self.update_prices_batch)
        self.price_thread.start()
        
        # 트레이딩봇 성과 업데이트 타이머 (15초마다 - 최적화)
        self.bot_performance_timer = QTimer()
        self.bot_performance_timer.timeout.connect(self.update_bot_performance)
        self.bot_performance_timer.start(15000)  # 15초로 증가

    def on_main_symbol_changed(self, symbol):
        """메인 심볼 변경 시 호출"""
        print(f"🔥🔥🔥 [메인 심볼 변경 함수 호출됨] {symbol} 🔥🔥🔥")
        print(f"[DEBUG] order_book_widget 존재 여부: {hasattr(self, 'order_book_widget')}")
        print(f"[DEBUG] ORDER_BOOK_AVAILABLE: {ORDER_BOOK_AVAILABLE}")
        
        # header_symbol_combo만 사용하므로 동기화 코드 제거
        
        # 코인 아이콘 변경
        coin_icons = {
            "BTCUSDT": "₿", "ETHUSDT": "Ξ", "BNBUSDT": "🅱",
            "ADAUSDT": "₳", "SOLUSDT": "◎", "XRPUSDT": "✕",
            "DOTUSDT": "●", "AVAXUSDT": "🔺", "MATICUSDT": "🔷", "LINKUSDT": "🔗"
        }
        if hasattr(self, 'coin_icon'):
            self.coin_icon.setText(coin_icons.get(symbol, "🪙"))

        # 코인별 색상 변경
        coin_colors = {
            "BTCUSDT": "#f7931a", "ETHUSDT": "#627eea", "BNBUSDT": "#f3ba2f",
            "ADAUSDT": "#0033ad", "SOLUSDT": "#00d4aa", "XRPUSDT": "#23292f",
            "DOTUSDT": "#e6007a", "AVAXUSDT": "#e84142", "MATICUSDT": "#8247e5", "LINKUSDT": "#375bd2"
        }
        color = coin_colors.get(symbol, "#f0b90b")
        if hasattr(self, 'coin_icon'):
            self.coin_icon.setStyleSheet(f"font-size: 24px; color: {color}; font-weight: bold;")

        # 상단 심볼 라벨 업데이트
        if hasattr(self, 'symbol_label'):
            print(f"[심볼 라벨 업데이트] {symbol}")
            self.symbol_label.setText(symbol)

        # 차트 업데이트
        if hasattr(self, 'chart_widget'):
            try:
                print(f"📈📈📈 [차트 업데이트 시도] {symbol} 📈📈📈")
                self.chart_widget.set_symbol(symbol)
                print(f"📈📈📈 [차트 업데이트 완료] {symbol} 📈📈📈")
            except Exception as e:
                print(f"❌❌❌ [차트 업데이트 오류] {symbol}: {e} ❌❌❌")

        # 호가창 업데이트
        if hasattr(self, 'order_book_widget') and ORDER_BOOK_AVAILABLE:
            try:
                print(f"💎💎💎 [호가창 업데이트 시도] {symbol} 💎💎💎")
                # 호가창이 완전히 로드되었는지 확인
                if self.order_book_widget and hasattr(self.order_book_widget, 'set_symbol'):
                    self.order_book_widget.set_symbol(symbol)
                    print(f"💎💎💎 [호가창 업데이트 완료] {symbol} 💎💎💎")
                else:
                    print(f"⚠️ 호가창이 아직 준비되지 않음")
            except Exception as e:
                print(f"❌❌❌ [호가창 업데이트 오류] {symbol}: {e} ❌❌❌")
                import traceback
                traceback.print_exc()
        else:
            print(f"❌❌❌ [호가창 업데이트 실패] hasattr: {hasattr(self, 'order_book_widget')}, AVAILABLE: {ORDER_BOOK_AVAILABLE} ❌❌❌")

        # 가격 업데이트 (바이낸스 스타일)
        if symbol in self.current_prices:
            price = self.current_prices[symbol]
            if hasattr(self, 'main_price_label'):
                self.main_price_label.setText(f"${price:,.4f}")
            # 바이낸스 헤더 가격 업데이트
            if hasattr(self, 'current_price_label'):
                self.current_price_label.setText(f"${price:,.4f}")
                
        print(f"✅✅✅ [메인 심볼 변경 함수 완료] {symbol} ✅✅✅")

    def on_orderbook_price_clicked(self, price):
        """호가창 가격 클릭 시 호출 - 바이낸스 스타일 입력창에 자동 입력 🚀"""
        if not ORDER_BOOK_AVAILABLE:
            return

        try:
            # 바이낸스 스타일 현물 거래 가격 입력창에 자동 입력
            if hasattr(self, 'spot_price_input'):
                self.spot_price_input.setText(f"{price:.4f}")
                
            # 레버리지 거래 가격 입력창에도 입력 (있을 경우)
            if hasattr(self, 'lev_price_input'):
                self.lev_price_input.setText(f"{price:.4f}")

            # 구형 입력창도 지원 (호환성)
            if hasattr(self, 'quick_buy_input'):
                amount = min(100.0, 1000.0 / price)
                self.quick_buy_input.setText(f"{amount:.2f}")

            print(f"📊 호가창 가격 클릭: ${price:.4f} - 가격 입력창에 자동 설정됨")

        except Exception as e:
            print(f"호가창 가격 클릭 처리 오류: {e}")

    def on_slider_changed(self, value):
        """자산 비율 슬라이더 변경 시 호출 - 금액과 수량 자동 계산"""
        try:
            # 현재 잔고 가져오기
            summary, _ = self.trading_engine.get_portfolio_status()
            if summary:
                total_balance = summary.get('balance', 0)
                amount = (total_balance * value) / 100
                
                # 현재 선택된 심볼과 가격 가져오기
                current_symbol = self.header_symbol_combo.currentText() if hasattr(self, 'header_symbol_combo') else "BTCUSDT"
                current_price = self.current_prices.get(current_symbol, 0)
                
                # 현물 거래 금액 입력창에 자동 설정
                if hasattr(self, 'spot_amount_input'):
                    self.spot_amount_input.setText(f"{amount:.2f}")
                
                # 레버리지 거래 금액 입력창에 자동 설정
                if hasattr(self, 'lev_amount_input'):
                    self.lev_amount_input.setText(f"{amount:.2f}")
                
                # 수량 계산 및 표시
                if current_price > 0:
                    quantity = amount / current_price
                    quantity_text = f" → {quantity:.6f} {current_symbol.replace('USDT', '')}"
                else:
                    quantity_text = ""
                
                # 슬라이더 값 라벨 업데이트 (수량 정보 포함)
                self.slider_value_label.setText(f"{value}% (${amount:,.2f}{quantity_text})")
            else:
                self.slider_value_label.setText(f"{value}% (약 $0)")
                
        except Exception as e:
            print(f"슬라이더 변경 처리 오류: {e}")

    def on_symbol_changed(self, new_symbol):
        """심볼 변경 시 차트와 호가창 업데이트"""
        try:
            print(f"심볼 변경: {new_symbol}")
            
            # 차트 업데이트
            if hasattr(self, 'chart_widget'):
                print(f"차트 위젯 업데이트: {new_symbol}")
                self.chart_widget.set_symbol(new_symbol)
                
            # 호가창 업데이트  
            if hasattr(self, 'order_book_widget') and ORDER_BOOK_AVAILABLE:
                print(f"호가창 위젯 업데이트: {new_symbol}")
                self.order_book_widget.set_symbol(new_symbol)
            else:
                print(f"호가창 업데이트 실패 - hasattr: {hasattr(self, 'order_book_widget')}, AVAILABLE: {ORDER_BOOK_AVAILABLE}")
                
            # 헤더의 심볼 라벨 업데이트
            if hasattr(self, 'symbol_label'):
                self.symbol_label.setText(new_symbol)
                
            # 현재 가격 업데이트
            if new_symbol in self.current_prices:
                price = self.current_prices[new_symbol]
                if hasattr(self, 'current_price_label'):
                    self.current_price_label.setText(f"${price:,.4f}")
                    
            print(f"✅ 심볼 변경 완료: {new_symbol}")
            
        except Exception as e:
            print(f"심볼 변경 처리 오류: {e}")

    def update_prices(self, prices):
        """가격 업데이트 - 바이낸스 스타일"""
        self.current_prices = prices
        current_symbol = self.header_symbol_combo.currentText() if hasattr(self, 'header_symbol_combo') else "BTCUSDT"

        if current_symbol in prices:
            price = prices[current_symbol]
            # 기존 스타일 레이블 업데이트
            if hasattr(self, 'main_price_label'):
                self.main_price_label.setText(f"${price:,.4f}")
            # 바이낸스 헤더 가격 업데이트
            if hasattr(self, 'current_price_label'):
                self.current_price_label.setText(f"${price:,.4f}")

            # 임시로 변동률 계산 (실제로는 24시간 데이터 필요)
            change = 85.99  # 예시 값
            change_pct = 0.07  # 예시 값

            if hasattr(self, 'price_change_label'):
                if change >= 0:
                    self.price_change_label.setText(f"+${change:.2f} (+{change_pct:.2f}%)")
                    self.price_change_label.setStyleSheet("font-size: 16px; color: #0ecb81; margin-left: 10px;")
                else:
                    self.price_change_label.setText(f"${change:.2f} ({change_pct:.2f}%)")
                    self.price_change_label.setStyleSheet("font-size: 16px; color: #f6465d; margin-left: 10px;")

        # 최적화: 백그라운드 워커가 포트폴리오 업데이트 처리
        # 기존 동기 호출을 비동기로 변경
        if hasattr(self, 'update_manager'):
            self.update_manager.request_portfolio_update()
        
        # 현물 보유내역 P&L 업데이트
        self.update_trading_history_pnl()
        
        # 레버리지 포지션 P&L 업데이트  
        self.update_leverage_positions_pnl()
        
        # 현물 및 레버리지 포지션 실시간 P&L 업데이트
        # 현물 보유내역 P&L 업데이트  
        self.update_trading_history_pnl()
        
        # 레버리지 포지션 P&L 업데이트
        self.update_leverage_positions_pnl()

        # 🤖 봇 상태 업데이트
        if hasattr(self, 'advanced_bot') and self.advanced_bot:
            self.update_bot_status_display()

        # 🚀 실제 바이낸스 포지션 모니터링 (고위험 포지션 경고)
        try:
            futures_positions = self.futures_client.get_position_info()
            if futures_positions:
                active_positions = [pos for pos in futures_positions if float(pos.get('positionAmt', 0)) != 0]

                # 위험한 포지션 확인 (-50% 이상 손실)
                high_risk_positions = []
                for position in active_positions:
                    entry_price = float(position.get('entryPrice', 0))
                    mark_price = float(position.get('markPrice', 0))
                    unrealized_pnl = float(position.get('unRealizedProfit', 0))
                    position_amt = float(position.get('positionAmt', 0))

                    if entry_price > 0 and position_amt != 0:
                        # 포지션 가치 계산
                        position_value = entry_price * abs(position_amt)
                        pnl_percentage = (unrealized_pnl / position_value) * 100 if position_value > 0 else 0

                        # -50% 이상 손실시 경고 대상
                        if pnl_percentage <= -50.0:
                            high_risk_positions.append({
                                'symbol': position['symbol'],
                                'side': 'LONG' if position_amt > 0 else 'SHORT',
                                'pnl_percentage': pnl_percentage,
                                'unrealized_pnl': unrealized_pnl
                            })

                # 고위험 포지션 경고
                if high_risk_positions:
                    risk_msg = "⚠️ 바이낸스 고위험 포지션 감지!\n\n"
                    for risk_pos in high_risk_positions:
                        risk_msg += f"• {risk_pos['symbol']} {risk_pos['side']} (손실: {risk_pos['pnl_percentage']:.1f}%)\n"

                    # 5분마다 한 번만 경고 (너무 자주 팝업 방지)
                    import time
                    current_time = time.time()
                    if not hasattr(self, 'last_risk_warning_time'):
                        self.last_risk_warning_time = 0

                    if current_time - self.last_risk_warning_time > 300:  # 5분 = 300초
                        QMessageBox.warning(self, "바이낸스 위험 경고", risk_msg)
                        self.last_risk_warning_time = current_time

        except Exception as e:
            self.logger.error(f"바이낸스 포지션 모니터링 오류: {e}")

        # 상태바 업데이트
        status_msg = f"마지막 업데이트: {datetime.now().strftime('%H:%M:%S')}"
        if hasattr(self, 'advanced_bot') and self.advanced_bot:
            status_msg += " | 🤖 고급봇 실행 중"
        self.statusBar().showMessage(status_msg)

    def update_portfolio_display(self):
        """레거시 포트폴리오 디스플레이 업데이트 (호환성용)"""
        # 백그라운드 워커가 있으면 사용, 없으면 기존 방식
        if hasattr(self, 'update_manager') and self.update_manager:
            self.update_manager.request_portfolio_update()
            return
        
        # 레거시 지원 (기존 코드 유지)
        self._legacy_update_portfolio_display()
    
    def _legacy_update_portfolio_display(self):
        """기존 포트폴리오 디스플레이 업데이트 (레거시)"""
        # 현물 거래 요약
        summary, message = self.trading_engine.get_portfolio_status()

        # 실제 바이낸스 선물 계정 정보
        try:
            futures_balance = self.futures_client.get_futures_balance()
            futures_positions = self.futures_client.get_position_info()

            # 활성 포지션만 필터링
            active_positions = [pos for pos in futures_positions if float(pos.get('positionAmt', 0)) != 0] if futures_positions else []

            # 총 미실현 손익 계산
            total_futures_pnl = sum(float(pos.get('unRealizedProfit', 0)) for pos in active_positions)

        except Exception as e:
            self.logger.error(f"바이낸스 데이터 조회 오류: {e}")
            futures_balance = {'balance': 0, 'available': 0}
            active_positions = []
            total_futures_pnl = 0

        if summary:
            # 현물 + 바이낸스 선물 총 자산 계산
            spot_value = summary['total_value']
            futures_value = futures_balance['balance'] + total_futures_pnl
            total_combined_value = spot_value + futures_value

            # 바이낸스 헤더 잔고 정보 업데이트
            self.balance_label.setText(f"잔고: ${total_combined_value:,.2f}")

            # 현물 손익
            spot_profit_loss = summary['profit_loss']
            spot_profit_loss_percent = summary['profit_loss_percent']

            # 선물 손익 (바이낸스)
            futures_profit_loss = total_futures_pnl

            # 총 손익 계산
            total_profit_loss = spot_profit_loss + futures_profit_loss
            total_profit_loss_percent = (total_profit_loss / Config.INITIAL_BALANCE) * 100

            # 손익 색상 설정
            if total_profit_loss >= 0:
                color = "#0ecb81"  # 초록색
                sign = "+"
            else:
                color = "#f6465d"  # 빨간색
                sign = ""

            # 기존 스타일에서만 profit_loss_label 업데이트
            if hasattr(self, 'profit_loss_label'):
                self.profit_loss_label.setText(
                    f"총 손익: {sign}${total_profit_loss:.2f} ({sign}{total_profit_loss_percent:.2f}%) "
                    f"[현물: {'+' if spot_profit_loss >= 0 else ''}${spot_profit_loss:.2f} | "
                    f"선물: {'+' if futures_profit_loss >= 0 else ''}${futures_profit_loss:.2f}]"
                )
                self.profit_loss_label.setStyleSheet(f"font-size: 12px; color: {color};")

                # 바이낸스 포지션 수 표시 (있는 경우)
                if active_positions:
                    position_info = f" | 🚀 바이낸스 포지션: {len(active_positions)}개"
                    current_text = self.profit_loss_label.text()
                    self.profit_loss_label.setText(current_text + position_info)

    def execute_quick_buy(self):
        """빠른 매수 실행"""
        symbol = self.header_symbol_combo.currentText() if hasattr(self, 'header_symbol_combo') else "BTCUSDT"
        if hasattr(self, 'quick_buy_input'):
            amount_text = self.quick_buy_input.text().strip()
        else:
            amount_text = "100"  # 기본값

        if not amount_text:
            QMessageBox.warning(self, "입력 오류", "매수 금액을 입력해주세요.")
            return

        try:
            amount = float(amount_text)
            success, message = self.trading_engine.place_buy_order(symbol, amount_usd=amount)

            if success:
                QMessageBox.information(self, "✅ 매수 성공", message)
                if hasattr(self, 'quick_buy_input'):
                    self.quick_buy_input.clear()
                self.update_portfolio_display()
            else:
                QMessageBox.warning(self, "❌ 매수 실패", message)

        except ValueError:
            QMessageBox.warning(self, "입력 오류", "올바른 숫자를 입력해주세요.")

    def execute_quick_sell(self):
        """빠른 매도 실행"""
        symbol = self.header_symbol_combo.currentText() if hasattr(self, 'header_symbol_combo') else "BTCUSDT"
        if hasattr(self, 'quick_sell_input'):
            percentage_text = self.quick_sell_input.text().strip()
        else:
            percentage_text = "100"  # 기본값 100%

        if not percentage_text:
            QMessageBox.warning(self, "입력 오류", "매도 비율을 입력해주세요.")
            return

        try:
            percentage = float(percentage_text)
            if percentage <= 0 or percentage > 100:
                QMessageBox.warning(self, "입력 오류", "1-100 사이의 비율을 입력해주세요.")
                return

            # 보유 수량 확인
            summary, _ = self.trading_engine.get_portfolio_status()
            currency = symbol.replace("USDT", "")

            if not summary or currency not in summary['holdings']:
                QMessageBox.warning(self, "매도 실패", f"{currency}을(를) 보유하고 있지 않습니다.")
                return

            available_quantity = summary['holdings'][currency]
            sell_quantity = available_quantity * (percentage / 100)

            success, message = self.trading_engine.place_sell_order(symbol, quantity=sell_quantity)

            if success:
                QMessageBox.information(self, "✅ 매도 성공", f"{percentage}% 매도 완료\n{message}")
                self.quick_sell_input.clear()
                self.update_portfolio_display()
            else:
                QMessageBox.warning(self, "❌ 매도 실패", message)

        except ValueError:
            QMessageBox.warning(self, "입력 오류", "올바른 숫자를 입력해주세요.")

    def execute_long_position(self):
        """실제 바이낸스 테스트넷에서 롱 포지션 진입"""
        symbol = self.main_symbol_combo.currentText()
        amount_text = self.long_amount_input.text().strip()
        leverage_text = self.leverage_combo.currentText().replace('x', '')

        if not amount_text:
            QMessageBox.warning(self, "입력 오류", "투자 금액을 입력해주세요.")
            return

        try:
            amount = float(amount_text)
            leverage = int(leverage_text)

            if amount <= 0:
                QMessageBox.warning(self, "입력 오류", "0보다 큰 금액을 입력해주세요.")
                return

            # 현재 가격 확인
            if symbol not in self.current_prices:
                QMessageBox.warning(self, "가격 오류", "현재 가격을 가져올 수 없습니다.")
                return

            current_price = self.current_prices[symbol]

            # 🚀 실제 바이낸스 선물 거래로 수량 계산
            # 증거금 기준으로 수량 계산 (레버리지 적용)
            notional_value = amount * leverage  # 명목 가치
            quantity = notional_value / current_price

            # 바이낸스 선물 클라이언트를 통해 실제 주문 실행
            success, result = self.futures_client.create_futures_order(
                symbol=symbol,
                side='BUY',  # 롱 포지션
                quantity=quantity,
                order_type='MARKET',
                leverage=leverage
            )

            if success:
                # 주문 성공
                order_id = result.get('orderId', 'N/A')
                filled_qty = float(result.get('executedQty', quantity))
                filled_price = float(result.get('avgPrice', current_price)) if result.get('avgPrice') else current_price

                QMessageBox.information(self, "✅ 롱 포지션 진입 성공",
                                        f"🚀 실제 바이낸스 테스트넷 거래 완료!\n\n"
                                        f"📋 주문 ID: {order_id}\n"
                                        f"💰 심볼: {symbol}\n"
                                        f"📈 방향: LONG (매수)\n"
                                        f"🔢 수량: {filled_qty:.8f}\n"
                                        f"💵 체결가: ${filled_price:,.4f}\n"
                                        f"⚡ 레버리지: {leverage}x\n"
                                        f"💎 증거금: ${amount:,.2f}\n"
                                        f"📊 명목가치: ${notional_value:,.2f}")

                self.long_amount_input.clear()
                self.update_portfolio_display()

                # 거래 로그 저장
                self.logger.info(f"🚀 LONG 포지션 진입: {symbol} {filled_qty:.8f} @ ${filled_price:.4f} ({leverage}x)")

            else:
                # 오류 타입에 따른 맞춤형 메시지
                if "Timeout" in str(result) or "-1007" in str(result):
                    QMessageBox.warning(self, "⏰ 바이낸스 서버 지연",
                                        f"바이낸스 테스트넷 서버 응답이 지연되고 있습니다.\n\n"
                                        f"❓ 주문 상태 확인 방법:\n"
                                        f"1. 📊 '포지션' 버튼으로 실제 포지션 확인\n"
                                        f"2. 🔄 잠시 후 다시 시도\n"
                                        f"3. 💰 계정 잔고 변화 확인\n\n"
                                        f"⚠️ 주문이 실행되었을 수도 있으니 중복 주문 주의!")

                    # 포지션 확인 버튼 제공
                    reply = QMessageBox.question(self, "포지션 확인",
                                                 "지금 바이낸스 포지션 현황을 확인하시겠습니까?",
                                                 QMessageBox.Yes | QMessageBox.No)

                    if reply == QMessageBox.Yes:
                        self.show_positions_dialog()
                elif "insufficient" in str(result).lower() or "-2019" in str(result):
                    QMessageBox.warning(self, "💰 잔고 부족",
                                        f"바이낸스 테스트넷 잔고가 부족합니다.\n\n"
                                        f"💡 해결 방법:\n"
                                        f"1. 투자 금액을 줄여보세요\n"
                                        f"2. 레버리지를 낮춰보세요\n"
                                        f"3. 계정 잔고를 확인해보세요")
                else:
                    QMessageBox.warning(self, "❌ 롱 포지션 실패",
                                        f"바이낸스 테스트넷 주문 실패:\n{result}\n\n"
                                        f"💡 일반적인 해결책:\n"
                                        f"• 잠시 후 다시 시도\n"
                                        f"• 네트워크 연결 확인\n"
                                        f"• 투자 금액 조정")

        except ValueError:
            QMessageBox.warning(self, "입력 오류", "올바른 숫자를 입력해주세요.")
        except Exception as e:
            QMessageBox.critical(self, "오류", f"바이낸스 API 오류:\n{e}")
            self.logger.error(f"롱 포지션 진입 실패: {e}")

    def execute_short_position(self):
        """실제 바이낸스 테스트넷에서 숏 포지션 진입"""
        symbol = self.main_symbol_combo.currentText()
        amount_text = self.short_amount_input.text().strip()
        leverage_text = self.leverage_combo.currentText().replace('x', '')

        if not amount_text:
            QMessageBox.warning(self, "입력 오류", "투자 금액을 입력해주세요.")
            return

        try:
            amount = float(amount_text)
            leverage = int(leverage_text)

            if amount <= 0:
                QMessageBox.warning(self, "입력 오류", "0보다 큰 금액을 입력해주세요.")
                return

            # 현재 가격 확인
            if symbol not in self.current_prices:
                QMessageBox.warning(self, "가격 오류", "현재 가격을 가져올 수 없습니다.")
                return

            current_price = self.current_prices[symbol]

            # 🚀 실제 바이낸스 선물 거래로 수량 계산
            # 증거금 기준으로 수량 계산 (레버리지 적용)
            notional_value = amount * leverage  # 명목 가치
            quantity = notional_value / current_price

            # 바이낸스 선물 클라이언트를 통해 실제 주문 실행
            success, result = self.futures_client.create_futures_order(
                symbol=symbol,
                side='SELL',  # 숏 포지션
                quantity=quantity,
                order_type='MARKET',
                leverage=leverage
            )

            if success:
                # 주문 성공
                order_id = result.get('orderId', 'N/A')
                filled_qty = float(result.get('executedQty', quantity))
                filled_price = float(result.get('avgPrice', current_price)) if result.get('avgPrice') else current_price

                QMessageBox.information(self, "✅ 숏 포지션 진입 성공",
                                        f"📉 실제 바이낸스 테스트넷 거래 완료!\n\n"
                                        f"📋 주문 ID: {order_id}\n"
                                        f"💰 심볼: {symbol}\n"
                                        f"📉 방향: SHORT (매도)\n"
                                        f"🔢 수량: {filled_qty:.8f}\n"
                                        f"💵 체결가: ${filled_price:,.4f}\n"
                                        f"⚡ 레버리지: {leverage}x\n"
                                        f"💎 증거금: ${amount:,.2f}\n"
                                        f"📊 명목가치: ${notional_value:,.2f}")

                self.short_amount_input.clear()
                self.update_portfolio_display()

                # 거래 로그 저장
                self.logger.info(f"📉 SHORT 포지션 진입: {symbol} {filled_qty:.8f} @ ${filled_price:.4f} ({leverage}x)")

            else:
                # 오류 타입에 따른 맞춤형 메시지
                if "Timeout" in str(result) or "-1007" in str(result):
                    QMessageBox.warning(self, "⏰ 바이낸스 서버 지연",
                                        f"바이낸스 테스트넷 서버 응답이 지연되고 있습니다.\n\n"
                                        f"❓ 주문 상태 확인 방법:\n"
                                        f"1. 📊 '포지션' 버튼으로 실제 포지션 확인\n"
                                        f"2. 🔄 잠시 후 다시 시도\n"
                                        f"3. 💰 계정 잔고 변화 확인\n\n"
                                        f"⚠️ 주문이 실행되었을 수도 있으니 중복 주문 주의!")

                    # 포지션 확인 버튼 제공
                    reply = QMessageBox.question(self, "포지션 확인",
                                                 "지금 바이낸스 포지션 현황을 확인하시겠습니까?",
                                                 QMessageBox.Yes | QMessageBox.No)

                    if reply == QMessageBox.Yes:
                        self.show_positions_dialog()
                elif "insufficient" in str(result).lower() or "-2019" in str(result):
                    QMessageBox.warning(self, "💰 잔고 부족",
                                        f"바이낸스 테스트넷 잔고가 부족합니다.\n\n"
                                        f"💡 해결 방법:\n"
                                        f"1. 투자 금액을 줄여보세요\n"
                                        f"2. 레버리지를 낮춰보세요\n"
                                        f"3. 계정 잔고를 확인해보세요")
                else:
                    QMessageBox.warning(self, "❌ 숏 포지션 실패",
                                        f"바이낸스 테스트넷 주문 실패:\n{result}\n\n"
                                        f"💡 일반적인 해결책:\n"
                                        f"• 잠시 후 다시 시도\n"
                                        f"• 네트워크 연결 확인\n"
                                        f"• 투자 금액 조정")

        except ValueError:
            QMessageBox.warning(self, "입력 오류", "올바른 숫자를 입력해주세요.")
        except Exception as e:
            QMessageBox.critical(self, "오류", f"바이낸스 API 오류:\n{e}")
            self.logger.error(f"숏 포지션 진입 실패: {e}")

    def close_current_position(self):
        """실제 바이낸스 테스트넷에서 현재 심볼의 포지션 청산"""
        symbol = self.main_symbol_combo.currentText()

        try:
            # 실제 바이낸스에서 포지션 정보 조회
            position_info = self.futures_client.get_position_info(symbol)

            if not position_info or position_info['size'] == 0:
                QMessageBox.information(self, "포지션 없음", f"{symbol}에 대한 활성 포지션이 없습니다.")
                return

            # 확인 다이얼로그
            side_text = "LONG 🚀" if position_info['side'] == 'LONG' else "SHORT 📉"
            pnl_text = f"${position_info['unrealized_pnl']:+.2f} ({position_info['percentage']:+.2f}%)"
            pnl_color = "🟢" if position_info['unrealized_pnl'] >= 0 else "🔴"

            reply = QMessageBox.question(
                self, '🚀 실제 포지션 청산 확인',
                f'바이낸스 테스트넷에서 {symbol} 포지션을 청산하시겠습니까?\n\n'
                f'📋 포지션 정보:\n'
                f'📊 방향: {side_text}\n'
                f'🔢 수량: {abs(position_info["size"]):.8f}\n'
                f'💵 진입가: ${position_info["entry_price"]:.4f}\n'
                f'📈 현재가: ${position_info["mark_price"]:.4f}\n'
                f'{pnl_color} 미실현 손익: {pnl_text}\n\n'
                f'⚠️ 이것은 실제 바이낸스 테스트넷 거래입니다!',
                QMessageBox.Yes | QMessageBox.No
            )

            if reply == QMessageBox.Yes:
                # 실제 바이낸스에서 포지션 청산
                success, result = self.futures_client.close_position(symbol)

                if success:
                    QMessageBox.information(self, "✅ 포지션 청산 완료",
                                            f"🎯 바이낸스 테스트넷 포지션 청산 성공!\n\n"
                                            f"💰 심볼: {symbol}\n"
                                            f"📊 청산된 방향: {side_text}\n"
                                            f"🔢 청산 수량: {abs(position_info['size']):.8f}\n"
                                            f"💵 청산가: ${position_info['mark_price']:.4f}\n"
                                            f"{pnl_color} 실현 손익: {pnl_text}")

                    self.update_portfolio_display()

                    # 거래 로그 저장
                    self.logger.info(f"🎯 포지션 청산: {symbol} {position_info['side']} 실현손익: ${position_info['unrealized_pnl']:.2f}")

                else:
                    QMessageBox.warning(self, "❌ 청산 실패",
                                        f"바이낸스 테스트넷 청산 실패:\n{result}")

        except Exception as e:
            QMessageBox.critical(self, "바이낸스 API 오류",
                                 f"포지션 정보 조회 중 오류:\n{e}")
            self.logger.error(f"포지션 청산 오류: {e}")

    def show_positions_dialog(self):
        """실제 바이낸스 테스트넷 포지션 현황 다이얼로그 표시"""
        try:
            # 실제 바이낸스에서 모든 포지션 조회
            all_positions = self.futures_client.get_position_info()

            if not all_positions:
                QMessageBox.warning(self, "API 오류", "바이낸스에서 포지션 정보를 가져올 수 없습니다.")
                return

            # 활성 포지션만 필터링 (수량이 0이 아닌 것)
            active_positions = [pos for pos in all_positions if float(pos.get('positionAmt', 0)) != 0]

            if not active_positions:
                QMessageBox.information(self, "🚀 바이낸스 포지션 현황",
                                        "현재 바이낸스 테스트넷에서 보유 중인 포지션이 없습니다.")
                return

            # 바이낸스 계정 잔고 조회
            futures_balance = self.futures_client.get_futures_balance()

            # 포지션 다이얼로그 생성
            dialog = QDialog(self)
            dialog.setWindowTitle("🚀 바이낸스 테스트넷 레버리지 포지션 현황")
            dialog.setGeometry(200, 200, 1000, 600)
            dialog.setStyleSheet(self.styleSheet())

            layout = QVBoxLayout(dialog)

            # 계정 요약 정보
            summary_label = QLabel(
                f"🏦 바이낸스 테스트넷 선물 계정\n"
                f"💰 USDT 잔고: ${futures_balance['balance']:.2f} | "
                f"💎 사용가능: ${futures_balance['available']:.2f} | "
                f"🎯 활성 포지션: {len(active_positions)}개"
            )
            summary_label.setStyleSheet("""
                font-size: 14px; 
                font-weight: bold; 
                padding: 15px; 
                background-color: #2b3139; 
                border-radius: 6px;
                border: 2px solid #f0b90b;
                color: #f0f0f0;
            """)
            layout.addWidget(summary_label)

            # 포지션 테이블
            table = QTableWidget()
            table.setColumnCount(9)
            table.setHorizontalHeaderLabels([
                "심볼", "방향", "수량", "진입가", "마크가", "미실현손익($)", "수익률(%)", "레버리지", "상태"
            ])
            table.setRowCount(len(active_positions))

            total_unrealized_pnl = 0.0

            for i, position in enumerate(active_positions):
                symbol = position['symbol']
                position_amt = float(position['positionAmt'])
                entry_price = float(position['entryPrice']) if position['entryPrice'] != '0.0' else 0
                mark_price = float(position['markPrice'])
                unrealized_pnl = float(position['unRealizedProfit'])
                percentage = float(position['percentage']) if 'percentage' in position else 0

                # 수익률 계산 (진입가 기준)
                if entry_price > 0:
                    if position_amt > 0:  # LONG
                        percentage = ((mark_price - entry_price) / entry_price) * 100
                    else:  # SHORT
                        percentage = ((entry_price - mark_price) / entry_price) * 100

                side = "LONG 🚀" if position_amt > 0 else "SHORT 📉"

                # 테이블 아이템 설정
                table.setItem(i, 0, QTableWidgetItem(symbol))
                table.setItem(i, 1, QTableWidgetItem(side))
                table.setItem(i, 2, QTableWidgetItem(f"{abs(position_amt):.8f}"))
                table.setItem(i, 3, QTableWidgetItem(f"${entry_price:.4f}"))
                table.setItem(i, 4, QTableWidgetItem(f"${mark_price:.4f}"))

                # 손익 색상 표시
                pnl_item = QTableWidgetItem(f"${unrealized_pnl:.2f}")
                pnl_pct_item = QTableWidgetItem(f"{percentage:.2f}%")

                if unrealized_pnl >= 0:
                    pnl_item.setForeground(QColor("#0ecb81"))
                    pnl_pct_item.setForeground(QColor("#0ecb81"))
                else:
                    pnl_item.setForeground(QColor("#f6465d"))
                    pnl_pct_item.setForeground(QColor("#f6465d"))

                table.setItem(i, 5, pnl_item)
                table.setItem(i, 6, pnl_pct_item)

                # 레버리지 정보 (바이낸스에서 직접 조회하거나 추정)
                leverage = "N/A"
                if entry_price > 0 and abs(position_amt) > 0:
                    # 포지션 가치로 레버리지 추정
                    position_value = entry_price * abs(position_amt)
                    # 실제로는 바이낸스 API에서 레버리지 정보를 가져와야 함
                    leverage = "Auto"

                table.setItem(i, 7, QTableWidgetItem(leverage))
                table.setItem(i, 8, QTableWidgetItem("활성"))

                total_unrealized_pnl += unrealized_pnl

            table.horizontalHeader().setStretchLastSection(True)
            table.setAlternatingRowColors(True)
            layout.addWidget(table)

            # 총 손익 표시
            total_pnl_label = QLabel(f"📊 총 미실현 손익: ${total_unrealized_pnl:+.2f}")
            if total_unrealized_pnl >= 0:
                total_pnl_label.setStyleSheet("font-size: 16px; font-weight: bold; color: #0ecb81; padding: 10px;")
            else:
                total_pnl_label.setStyleSheet("font-size: 16px; font-weight: bold; color: #f6465d; padding: 10px;")
            layout.addWidget(total_pnl_label)

            # 버튼
            button_layout = QHBoxLayout()

            close_all_btn = QPushButton("❌ 전체 청산 (실제 거래)")
            close_all_btn.setStyleSheet("""
                QPushButton {
                    background-color: #f6465d;
                    color: white;
                    font-weight: bold;
                    padding: 12px 20px;
                    border: none;
                    border-radius: 6px;
                    font-size: 13px;
                }
                QPushButton:hover {
                    background-color: #f23645;
                }
            """)
            close_all_btn.clicked.connect(lambda: self.close_all_binance_positions(dialog))
            button_layout.addWidget(close_all_btn)

            button_layout.addStretch()

            refresh_btn = QPushButton("🔄 새로고침")
            refresh_btn.clicked.connect(lambda: self.refresh_binance_positions_dialog(dialog, table, summary_label, total_pnl_label))
            button_layout.addWidget(refresh_btn)

            close_btn = QPushButton("닫기")
            close_btn.clicked.connect(dialog.close)
            button_layout.addWidget(close_btn)

            layout.addLayout(button_layout)

            dialog.exec_()

        except Exception as e:
            QMessageBox.critical(self, "바이낸스 API 오류",
                                 f"포지션 조회 중 오류 발생:\n{e}")
            self.logger.error(f"바이낸스 포지션 조회 오류: {e}")

    def close_all_binance_positions(self, dialog):
        """모든 바이낸스 포지션 청산"""
        reply = QMessageBox.question(
            self, '⚠️ 실제 전체 포지션 청산 확인',
            '바이낸스 테스트넷의 모든 레버리지 포지션을 청산하시겠습니까?\n\n'
            '⚠️ 이것은 실제 바이낸스 테스트넷 거래입니다!\n'
            '모든 활성 포지션이 시장가로 청산됩니다.',
            QMessageBox.Yes | QMessageBox.No
        )

        if reply == QMessageBox.Yes:
            try:
                # 모든 활성 포지션 조회
                all_positions = self.futures_client.get_position_info()
                active_positions = [pos for pos in all_positions if float(pos.get('positionAmt', 0)) != 0]

                success_count = 0
                total_positions = len(active_positions)

                for position in active_positions:
                    symbol = position['symbol']
                    success, result = self.futures_client.close_position(symbol)
                    if success:
                        success_count += 1
                        self.logger.info(f"포지션 청산 성공: {symbol}")
                    else:
                        self.logger.error(f"포지션 청산 실패: {symbol} - {result}")

                QMessageBox.information(self, "🎯 전체 청산 완료",
                                        f"바이낸스 테스트넷 포지션 청산 결과:\n\n"
                                        f"✅ 성공: {success_count}개\n"
                                        f"❌ 실패: {total_positions - success_count}개\n"
                                        f"📊 총 포지션: {total_positions}개")

                dialog.close()
                self.update_portfolio_display()

            except Exception as e:
                QMessageBox.critical(self, "청산 오류", f"전체 포지션 청산 중 오류:\n{e}")

    def refresh_binance_positions_dialog(self, dialog, table, summary_label, total_pnl_label):
        """바이낸스 포지션 다이얼로그 새로고침"""
        try:
            # 실제 바이낸스 데이터 다시 조회
            all_positions = self.futures_client.get_position_info()
            active_positions = [pos for pos in all_positions if float(pos.get('positionAmt', 0)) != 0]
            futures_balance = self.futures_client.get_futures_balance()

            # 요약 정보 업데이트
            summary_label.setText(
                f"🏦 바이낸스 테스트넷 선물 계정\n"
                f"💰 USDT 잔고: ${futures_balance['balance']:.2f} | "
                f"💎 사용가능: ${futures_balance['available']:.2f} | "
                f"🎯 활성 포지션: {len(active_positions)}개"
            )

            # 테이블 업데이트
            table.setRowCount(len(active_positions))
            total_unrealized_pnl = 0.0

            for i, position in enumerate(active_positions):
                mark_price = float(position['markPrice'])
                unrealized_pnl = float(position['unRealizedProfit'])

                table.setItem(i, 4, QTableWidgetItem(f"${mark_price:.4f}"))

                pnl_item = QTableWidgetItem(f"${unrealized_pnl:.2f}")
                if unrealized_pnl >= 0:
                    pnl_item.setForeground(QColor("#0ecb81"))
                else:
                    pnl_item.setForeground(QColor("#f6465d"))

                table.setItem(i, 5, pnl_item)
                total_unrealized_pnl += unrealized_pnl

            # 총 손익 업데이트
            total_pnl_label.setText(f"📊 총 미실현 손익: ${total_unrealized_pnl:+.2f}")
            if total_unrealized_pnl >= 0:
                total_pnl_label.setStyleSheet("font-size: 16px; font-weight: bold; color: #0ecb81; padding: 10px;")
            else:
                total_pnl_label.setStyleSheet("font-size: 16px; font-weight: bold; color: #f6465d; padding: 10px;")

        except Exception as e:
            QMessageBox.warning(dialog, "새로고침 오류", f"데이터 새로고침 중 오류:\n{e}")

    def start_trading_bot(self):
        """고급 트레이딩봇 시작 - 다양한 전략 지원"""
        if not ADVANCED_BOT_AVAILABLE:
            QMessageBox.warning(self, "모듈 오류",
                                "고급 트레이딩봇 모듈을 찾을 수 없습니다.\n\n"
                                "다음 파일들이 프로젝트 폴더에 있는지 확인하세요:\n"
                                "• trading_bot_integration.py\n"
                                "• strategy_adapter.py\n\n"
                                "파일을 추가한 후 프로그램을 다시 시작하세요.")
            return

        try:
            # 컴팩트 탭과 기본 탭 모두 지원
            if hasattr(self, 'compact_bot_strategy_combo'):
                symbol = "SOLUSDT"  # 기본값
                strategy = self.compact_bot_strategy_combo.currentText()
                amount_text = self.compact_bot_amount_input.text().strip()
                leverage_text = "3x"  # 기본값
                position_text = "30"  # 기본값
            else:
                symbol = self.bot_symbol_combo.currentText()
                strategy = self.bot_strategy_combo.currentText()
                amount_text = self.bot_amount_input.text().strip()
                leverage_text = self.bot_leverage_combo.currentText().replace('x', '')
                position_text = self.bot_position_input.text().strip()

            if not amount_text:
                QMessageBox.warning(self, "입력 오류", "거래 금액을 입력해주세요.")
                return

            amount = float(amount_text)
            leverage = int(leverage_text)
            position_size = float(position_text) if position_text else 30.0

            if amount < 50:
                QMessageBox.warning(self, "입력 오류", "거래 금액은 최소 $50 이상이어야 합니다.")
                return

            # 기존 봇이 실행 중이면 정지
            if hasattr(self, 'advanced_bot') and self.advanced_bot:
                self.stop_trading_bot()

            # 전략별 파라미터 설정
            strategy_params = self._get_strategy_params(strategy)

            # 🆕 선택된 전략으로 봇 설정 생성
            bot_config = TradingBotConfig(
                symbol=symbol,
                timeframe="1h",
                strategy_name=strategy,
                strategy_params=strategy_params,
                leverage=leverage,
                position_size_pct=position_size,
                stop_loss_pct=-2.0,
                take_profit_pct=8.0,
                max_positions=2
            )

            # 🆕 새로운 고급 봇 생성
            self.advanced_bot = AdvancedTradingBot(bot_config)

            # GUI 업데이트
            if hasattr(self, 'start_bot_btn'):
                self.start_bot_btn.setEnabled(False)
            if hasattr(self, 'stop_bot_btn'):
                self.stop_bot_btn.setEnabled(True)
            if hasattr(self, 'bot_status_label'):
                self.bot_status_label.setText("시작 중...")
                self.bot_status_label.setStyleSheet("font-size: 12px; color: #f0b90b;")
            if hasattr(self, 'bot_strategy_label'):
                self.bot_strategy_label.setText(f"전략: {strategy}")
                self.bot_strategy_label.setStyleSheet("font-size: 11px; color: #00ff88;")

            # 봇 시작 (비동기 처리)
            import asyncio
            import threading

            def run_bot():
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    loop.run_until_complete(self.advanced_bot.start())
                    # 성공 시 GUI 업데이트
                    if hasattr(self, 'bot_status_label'):
                        self.bot_status_label.setText("실행 중")
                        self.bot_status_label.setStyleSheet("font-size: 12px; color: #00C851;")
                except Exception as e:
                    # 실패 시 GUI 복원
                    if hasattr(self, 'start_bot_btn'):
                        self.start_bot_btn.setEnabled(True)
                    if hasattr(self, 'stop_bot_btn'):
                        self.stop_bot_btn.setEnabled(False)
                    if hasattr(self, 'bot_status_label'):
                        self.bot_status_label.setText("시작 실패")
                        self.bot_status_label.setStyleSheet("font-size: 12px; color: #f6465d;")
                    if hasattr(self, 'bot_strategy_label'):
                        self.bot_strategy_label.setText("전략: 없음")
                        self.bot_strategy_label.setStyleSheet("font-size: 11px; color: #888;")
                    QMessageBox.warning(self, "❌ 봇 시작 실패", f"봇 시작 중 오류:\n{e}")
                    self.advanced_bot = None
                finally:
                    loop.close()

            # 별도 스레드에서 봇 실행
            threading.Thread(target=run_bot, daemon=True).start()

            strategy_descriptions = {
                "macd_final": "MACD 크로스오버 + 트렌드 필터",
                "ma_crossover": "이동평균선 교차 전략",
                "rsi_leverage": "RSI 과매수/과매도 전략",
                "bollinger_band": "볼린저 밴드 반등 전략",
                "momentum_spike": "급등/급락 모멘텀 전략",
                "triple_ma": "삼중 이동평균 전략"
            }

            QMessageBox.information(self, "🤖 고급 봇 시작",
                                    f"고급 트레이딩봇이 시작됩니다!\n\n"
                                    f"📊 심볼: {symbol}\n"
                                    f"📈 전략: {strategy_descriptions.get(strategy, strategy)}\n"
                                    f"💰 포지션 크기: {position_size}%\n"
                                    f"⚡ 레버리지: {leverage}x\n"
                                    f"🎯 손절: -2% | 익절: +8%\n\n"
                                    f"🚀 백테스팅 검증 전략으로 자동 거래합니다!")

            self.logger.info(f"🤖 고급 트레이딩봇 시작: {symbol} - {strategy}")

        except ValueError:
            QMessageBox.warning(self, "입력 오류", "올바른 숫자를 입력해주세요.")
        except Exception as e:
            QMessageBox.critical(self, "오류", f"봇 시작 중 오류:\n{e}")
            self.logger.error(f"고급 봇 시작 오류: {e}")

    def _get_strategy_params(self, strategy_name: str) -> dict:
        """전략별 기본 파라미터 반환"""
        params = {
            "macd_final": {
                'regime_filter_period': 200,
                'fast_ma': 12,
                'slow_ma': 26,
                'signal_ma': 9
            },
            "ma_crossover": {
                'short_ma': 20,
                'long_ma': 60
            },
            "rsi_leverage": {
                'rsi_period': 14,
                'oversold_threshold': 30,
                'overbought_threshold': 70
            },
            "bollinger_band": {
                'bb_length': 20,
                'bb_std': 2
            },
            "momentum_spike": {
                'spike_pct': 3.0,
                'take_profit_pct': 1.0,
                'stop_loss_pct': -1.0
            },
            "triple_ma": {
                'short_ma': 10,
                'medium_ma': 20,
                'long_ma': 50
            }
        }

        return params.get(strategy_name, {})

    def stop_trading_bot(self):
        """고급 트레이딩봇 정지"""
        try:
            if not hasattr(self, 'advanced_bot') or not self.advanced_bot:
                return

            if hasattr(self, 'bot_status_label'):
                self.bot_status_label.setText("정지 중...")
                self.bot_status_label.setStyleSheet("font-size: 12px; color: #f0b90b;")

            # 봇 정지 (비동기 처리)
            import asyncio
            import threading

            def stop_bot():
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    loop.run_until_complete(self.advanced_bot.stop())

                    # GUI 업데이트
                    if hasattr(self, 'start_bot_btn'):
                        self.start_bot_btn.setEnabled(True)
                    if hasattr(self, 'stop_bot_btn'):
                        self.stop_bot_btn.setEnabled(False)
                    if hasattr(self, 'bot_status_label'):
                        self.bot_status_label.setText("정지됨")
                        self.bot_status_label.setStyleSheet("font-size: 12px; color: #ff4444;")
                    if hasattr(self, 'bot_strategy_label'):
                        self.bot_strategy_label.setText("전략: 없음")
                        self.bot_strategy_label.setStyleSheet("font-size: 11px; color: #888;")

                    # 성과 표시
                    total_trades = self.advanced_bot.performance_metrics.get('total_trades', 0)
                    total_pnl = self.advanced_bot.performance_metrics.get('total_pnl', 0)
                    winning_trades = self.advanced_bot.performance_metrics.get('winning_trades', 0)
                    win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0

                    QMessageBox.information(self, "🤖 고급 봇 정지",
                                            f"고급 트레이딩봇이 정지되었습니다.\n\n"
                                            f"📊 최종 성과:\n"
                                            f"• 총 거래: {total_trades}회\n"
                                            f"• 총 손익: ${total_pnl:+.2f}\n"
                                            f"• 승률: {win_rate:.1f}%\n"
                                            f"• 수익 거래: {winning_trades}회")

                    self.advanced_bot = None
                    self.logger.info("🤖 고급 트레이딩봇 정지됨")
                except Exception as e:
                    QMessageBox.critical(self, "오류", f"봇 정지 중 오류:\n{e}")
                    self.logger.error(f"고급 봇 정지 오류: {e}")
                finally:
                    loop.close()

            # 별도 스레드에서 봇 정지
            threading.Thread(target=stop_bot, daemon=True).start()

        except Exception as e:
            QMessageBox.critical(self, "오류", f"봇 정지 중 오류:\n{e}")
            self.logger.error(f"고급 봇 정지 오류: {e}")

    def update_bot_status_display(self):
        """봇 상태 디스플레이 업데이트 - 고급 봇용"""
        if not hasattr(self, 'advanced_bot') or not self.advanced_bot:
            self.bot_trades_label.setText("거래: 0회")
            self.bot_pnl_label.setText("손익: $0.00")
            self.bot_pnl_label.setStyleSheet("font-size: 12px; color: #f0f0f0;")
            return

        try:
            # 🆕 고급 봇 성과 지표
            total_trades = self.advanced_bot.performance_metrics.get('total_trades', 0)
            total_pnl = self.advanced_bot.performance_metrics.get('total_pnl', 0)

            self.bot_trades_label.setText(f"거래: {total_trades}회")

            pnl_text = f"손익: ${total_pnl:+.2f}"
            if total_pnl >= 0:
                self.bot_pnl_label.setStyleSheet("font-size: 12px; color: #00C851;")
            else:
                self.bot_pnl_label.setStyleSheet("font-size: 12px; color: #ff4444;")
            self.bot_pnl_label.setText(pnl_text)

        except Exception as e:
            self.logger.error(f"고급 봇 상태 업데이트 오류: {e}")

    def show_bot_settings(self):
        """봇 설정 다이얼로그"""
        dialog = QDialog(self)
        dialog.setWindowTitle("🤖 트레이딩봇 설정")
        dialog.setGeometry(300, 300, 800, 800)
        dialog.setStyleSheet(self.styleSheet())

        layout = QVBoxLayout(dialog)

        # 기본 설정
        basic_group = QGroupBox("기본 설정")
        basic_layout = QFormLayout(basic_group)

        symbol_combo = QComboBox()
        symbol_combo.addItems(Config.SUPPORTED_PAIRS)
        symbol_combo.setCurrentText(self.bot_symbol_combo.currentText())
        basic_layout.addRow("거래 심볼:", symbol_combo)

        amount_input = QLineEdit(self.bot_amount_input.text())
        basic_layout.addRow("기본 거래 금액 ($):", amount_input)

        layout.addWidget(basic_group)

        # 전략 설정
        strategy_group = QGroupBox("이동평균 전략 설정")
        strategy_layout = QFormLayout(strategy_group)

        short_ma_input = QLineEdit("3")
        strategy_layout.addRow("단기 이동평균:", short_ma_input)

        long_ma_input = QLineEdit("10")
        strategy_layout.addRow("장기 이동평균:", long_ma_input)

        timeframe_combo = QComboBox()
        timeframe_combo.addItems(["1m", "5m", "15m", "1h"])
        timeframe_combo.setCurrentText("1m")
        strategy_layout.addRow("시간대:", timeframe_combo)

        layout.addWidget(strategy_group)

        # 리스크 관리
        risk_group = QGroupBox("리스크 관리")
        risk_layout = QFormLayout(risk_group)

        max_loss_input = QLineEdit("1000")
        risk_layout.addRow("일일 최대 손실 ($):", max_loss_input)

        max_positions_input = QLineEdit("5")
        risk_layout.addRow("최대 포지션 수:", max_positions_input)

        layout.addWidget(risk_group)

        # 버튼
        button_layout = QHBoxLayout()

        save_btn = QPushButton("💾 저장")
        save_btn.clicked.connect(lambda: self.save_bot_settings(dialog, {
            'symbol': symbol_combo.currentText(),
            'amount': amount_input.text(),
            'short_ma': short_ma_input.text(),
            'long_ma': long_ma_input.text(),
            'timeframe': timeframe_combo.currentText(),
            'max_loss': max_loss_input.text(),
            'max_positions': max_positions_input.text()
        }))
        button_layout.addWidget(save_btn)

        cancel_btn = QPushButton("취소")
        cancel_btn.clicked.connect(dialog.close)
        button_layout.addWidget(cancel_btn)

        layout.addLayout(button_layout)

        dialog.exec_()

    def save_bot_settings(self, dialog, settings):
        """봇 설정 저장"""
        try:
            # GUI 업데이트
            self.bot_symbol_combo.setCurrentText(settings['symbol'])
            self.bot_amount_input.setText(settings['amount'])

            QMessageBox.information(dialog, "설정 저장", "봇 설정이 저장되었습니다.\n다음 시작 시 적용됩니다.")
            dialog.close()

        except Exception as e:
            QMessageBox.warning(dialog, "저장 오류", f"설정 저장 중 오류:\n{e}")

    def show_bot_log(self):
        """봇 로그 및 거래 내역 다이얼로그"""
        dialog = QDialog(self)
        dialog.setWindowTitle("🤖 봇 로그 & 거래 내역")
        dialog.setGeometry(200, 200, 1200, 800)
        dialog.setStyleSheet(self.styleSheet())

        layout = QVBoxLayout(dialog)

        # 탭 위젯
        tab_widget = QTabWidget()

        # 봇 상태 탭
        status_tab = QWidget()
        status_layout = QVBoxLayout(status_tab)

        if self.advanced_bot:
            status_text = QTextEdit()
            status_text.setReadOnly(True)
            status_text.append("🤖 고급 봇 현재 상태:")
            status_text.append(f"• 전략: MACD 최종 전략")
            status_text.append(f"• 총 거래: {self.advanced_bot.performance_metrics.get('total_trades', 0)}회")
            status_text.append(f"• 총 손익: ${self.advanced_bot.performance_metrics.get('total_pnl', 0):+.2f}")
            status_text.append(f"• 승률: {(self.advanced_bot.performance_metrics.get('winning_trades', 0) / max(1, self.advanced_bot.performance_metrics.get('total_trades', 1)) * 100):.1f}%")
            status_text.append(f"• 수익 거래: {self.advanced_bot.performance_metrics.get('winning_trades', 0)}회")
            status_text.append(f"• 레버리지: 3x")
            status_text.append(f"• 포지션 크기: 30%")

            status_layout.addWidget(status_text)
        else:
            no_bot_label = QLabel("현재 실행 중인 봇이 없습니다.")
            no_bot_label.setAlignment(Qt.AlignCenter)
            status_layout.addWidget(no_bot_label)

        tab_widget.addTab(status_tab, "📊 봇 상태")

        # 거래 내역 탭
        trades_tab = QWidget()
        trades_layout = QVBoxLayout(trades_tab)

        if self.advanced_bot:
            # 고급 봇의 거래 내역 표시
            trades_table = QTableWidget()
            trades_table.setColumnCount(6)
            trades_table.setHorizontalHeaderLabels(["시간", "심볼", "액션", "금액", "가격", "손익"])

            # 임시 거래 내역 (실제로는 봇에서 가져와야 함)
            trade_history = []
            trades_table.setRowCount(len(trade_history))

            for i, trade in enumerate(trade_history):
                trades_table.setItem(i, 0, QTableWidgetItem(trade.get('timestamp', '')[:19]))
                trades_table.setItem(i, 1, QTableWidgetItem(trade.get('symbol', '')))
                trades_table.setItem(i, 2, QTableWidgetItem(trade.get('action', '')))
                trades_table.setItem(i, 3, QTableWidgetItem(f"${trade.get('amount', 0):.2f}"))
                trades_table.setItem(i, 4, QTableWidgetItem(f"${trade.get('price', 0):.4f}"))

                pnl = trade.get('pnl', 0)
                pnl_item = QTableWidgetItem(f"${pnl:+.2f}")
                if pnl >= 0:
                    pnl_item.setForeground(QColor("#00C851"))
                else:
                    pnl_item.setForeground(QColor("#ff4444"))
                trades_table.setItem(i, 5, pnl_item)

            trades_table.horizontalHeader().setStretchLastSection(True)
            trades_layout.addWidget(trades_table)
        else:
            no_trades_label = QLabel("거래 내역이 없습니다.")
            no_trades_label.setAlignment(Qt.AlignCenter)
            trades_layout.addWidget(no_trades_label)

        tab_widget.addTab(trades_tab, "📋 거래 내역")

        layout.addWidget(tab_widget)

        # 닫기 버튼
        close_btn = QPushButton("닫기")
        close_btn.clicked.connect(dialog.close)
        layout.addWidget(close_btn)

        dialog.exec_()

    # 메뉴 액션들
    def quick_buy(self):
        """빠른 매수 다이얼로그"""
        dialog = QInputDialog()
        dialog.setStyleSheet(self.styleSheet())
        amount, ok = dialog.getDouble(self, '빠른 매수', '매수할 USD 금액을 입력하세요:', 100, 0, 999999, 2)
        if ok:
            self.quick_buy_input.setText(str(amount))
            self.execute_quick_buy()

    def quick_sell(self):
        """빠른 매도 다이얼로그"""
        dialog = QInputDialog()
        dialog.setStyleSheet(self.styleSheet())
        percentage, ok = dialog.getDouble(self, '빠른 매도', '매도할 비율(%)을 입력하세요:', 50, 1, 100, 1)
        if ok:
            self.quick_sell_input.setText(str(percentage))
            self.execute_quick_sell()

    def sell_all_holdings(self):
        """전체 보유 코인 매도"""
        reply = QMessageBox.question(
            self, '전량 매도 확인',
            '모든 보유 코인을 매도하시겠습니까?',
            QMessageBox.Yes | QMessageBox.No
        )

        if reply == QMessageBox.Yes:
            summary, _ = self.trading_engine.get_portfolio_status()
            if summary and summary['holdings']:
                success_count = 0
                for currency in summary['holdings'].keys():
                    symbol = f"{currency}USDT"
                    success, _ = self.trading_engine.place_sell_order(symbol, sell_all=True)
                    if success:
                        success_count += 1

                QMessageBox.information(self, "전량 매도 완료", f"{success_count}개 코인이 매도되었습니다.")
                self.update_portfolio_display()

    def quick_long(self):
        """빠른 롱 포지션 다이얼로그"""
        dialog = QDialog(self)
        dialog.setWindowTitle("🚀 빠른 롱 포지션")
        dialog.setGeometry(300, 300, 400, 200)
        dialog.setStyleSheet(self.styleSheet())

        layout = QVBoxLayout(dialog)

        # 금액 입력
        amount_layout = QHBoxLayout()
        amount_layout.addWidget(QLabel("투자 금액 (USD):"))
        amount_input = QLineEdit()
        amount_input.setPlaceholderText("예: 100")
        amount_layout.addWidget(amount_input)
        layout.addLayout(amount_layout)

        # 레버리지 선택
        leverage_layout = QHBoxLayout()
        leverage_layout.addWidget(QLabel("레버리지:"))
        leverage_combo = QComboBox()
        leverage_combo.addItems(["1x", "2x", "3x", "5x", "10x", "20x", "50x", "75x", "100x", "125x"])
        leverage_combo.setCurrentText("10x")
        leverage_layout.addWidget(leverage_combo)
        layout.addLayout(leverage_layout)

        # 버튼
        button_layout = QHBoxLayout()

        ok_btn = QPushButton("🚀 롱 진입")
        ok_btn.setStyleSheet("""
            QPushButton {
                background-color: #0ecb81;
                color: white;
                font-weight: bold;
                padding: 10px 20px;
                border: none;
                border-radius: 4px;
            }
        """)

        def execute_long():
            try:
                amount = float(amount_input.text())
                leverage = int(leverage_combo.currentText().replace('x', ''))

                symbol = self.header_symbol_combo.currentText() if hasattr(self, 'header_symbol_combo') else "BTCUSDT"
                current_price = self.current_prices.get(symbol, 0)

                if current_price <= 0:
                    QMessageBox.warning(dialog, "오류", "현재 가격을 가져올 수 없습니다.")
                    return

                notional_value = amount * leverage
                quantity = notional_value / current_price

                success, result = self.futures_client.create_futures_order(
                    symbol=symbol,
                    side='BUY',
                    quantity=quantity,
                    order_type='MARKET',
                    leverage=leverage
                )

                if success:
                    order_id = result.get('orderId', 'N/A')
                    QMessageBox.information(dialog, "✅ 롱 포지션 진입",
                                            f"🚀 바이낸스 테스트넷 롱 포지션 성공!\n\n"
                                            f"📋 주문 ID: {order_id}\n"
                                            f"💰 심볼: {symbol}\n"
                                            f"⚡ 레버리지: {leverage}x\n"
                                            f"💎 증거금: ${amount:.2f}")
                    dialog.close()
                    self.update_portfolio_display()
                else:
                    QMessageBox.warning(dialog, "❌ 진입 실패", f"바이낸스 주문 실패:\n{result}")

            except ValueError:
                QMessageBox.warning(dialog, "입력 오류", "올바른 숫자를 입력해주세요.")
            except Exception as e:
                QMessageBox.critical(dialog, "API 오류", f"바이낸스 API 오류:\n{e}")

        ok_btn.clicked.connect(execute_long)
        button_layout.addWidget(ok_btn)

        cancel_btn = QPushButton("취소")
        cancel_btn.clicked.connect(dialog.close)
        button_layout.addWidget(cancel_btn)

        layout.addLayout(button_layout)
        dialog.exec_()

    def quick_short(self):
        """빠른 숏 포지션 다이얼로그"""
        dialog = QDialog(self)
        dialog.setWindowTitle("📉 빠른 숏 포지션")
        dialog.setGeometry(300, 300, 400, 200)
        dialog.setStyleSheet(self.styleSheet())

        layout = QVBoxLayout(dialog)

        # 금액 입력
        amount_layout = QHBoxLayout()
        amount_layout.addWidget(QLabel("투자 금액 (USD):"))
        amount_input = QLineEdit()
        amount_input.setPlaceholderText("예: 100")
        amount_layout.addWidget(amount_input)
        layout.addLayout(amount_layout)

        # 레버리지 선택
        leverage_layout = QHBoxLayout()
        leverage_layout.addWidget(QLabel("레버리지:"))
        leverage_combo = QComboBox()
        leverage_combo.addItems(["1x", "2x", "3x", "5x", "10x", "20x", "50x", "75x", "100x", "125x"])
        leverage_combo.setCurrentText("10x")
        leverage_layout.addWidget(leverage_combo)
        layout.addLayout(leverage_layout)

        # 버튼
        button_layout = QHBoxLayout()

        ok_btn = QPushButton("📉 숏 진입")
        ok_btn.setStyleSheet("""
            QPushButton {
                background-color: #f6465d;
                color: white;
                font-weight: bold;
                padding: 10px 20px;
                border: none;
                border-radius: 4px;
            }
        """)

        def execute_short():
            try:
                amount = float(amount_input.text())
                leverage = int(leverage_combo.currentText().replace('x', ''))

                symbol = self.header_symbol_combo.currentText() if hasattr(self, 'header_symbol_combo') else "BTCUSDT"
                current_price = self.current_prices.get(symbol, 0)

                if current_price <= 0:
                    QMessageBox.warning(dialog, "오류", "현재 가격을 가져올 수 없습니다.")
                    return

                notional_value = amount * leverage
                quantity = notional_value / current_price

                success, result = self.futures_client.create_futures_order(
                    symbol=symbol,
                    side='SELL',
                    quantity=quantity,
                    order_type='MARKET',
                    leverage=leverage
                )

                if success:
                    order_id = result.get('orderId', 'N/A')
                    QMessageBox.information(dialog, "✅ 숏 포지션 진입",
                                            f"📉 바이낸스 테스트넷 숏 포지션 성공!\n\n"
                                            f"📋 주문 ID: {order_id}\n"
                                            f"💰 심볼: {symbol}\n"
                                            f"⚡ 레버리지: {leverage}x\n"
                                            f"💎 증거금: ${amount:.2f}")
                    dialog.close()
                    self.update_portfolio_display()
                else:
                    QMessageBox.warning(dialog, "❌ 진입 실패", f"바이낸스 주문 실패:\n{result}")

            except ValueError:
                QMessageBox.warning(dialog, "입력 오류", "올바른 숫자를 입력해주세요.")
            except Exception as e:
                QMessageBox.critical(dialog, "API 오류", f"바이낸스 API 오류:\n{e}")

        ok_btn.clicked.connect(execute_short)
        button_layout.addWidget(ok_btn)

        cancel_btn = QPushButton("취소")
        cancel_btn.clicked.connect(dialog.close)
        button_layout.addWidget(cancel_btn)

        layout.addLayout(button_layout)
        dialog.exec_()

    def close_all_positions_menu(self):
        """메뉴에서 전체 바이낸스 포지션 청산"""
        try:
            all_positions = self.futures_client.get_position_info()
            active_positions = [pos for pos in all_positions if float(pos.get('positionAmt', 0)) != 0] if all_positions else []

            if not active_positions:
                QMessageBox.information(self, "포지션 없음", "청산할 바이낸스 포지션이 없습니다.")
                return

            reply = QMessageBox.question(
                self, '⚠️ 실제 전체 포지션 청산 확인',
                f'바이낸스 테스트넷의 총 {len(active_positions)}개 레버리지 포지션을 청산하시겠습니까?\n\n'
                f'⚠️ 이것은 실제 바이낸스 테스트넷 거래입니다!',
                QMessageBox.Yes | QMessageBox.No
            )

            if reply == QMessageBox.Yes:
                success_count = 0

                for position in active_positions:
                    symbol = position['symbol']
                    success, result = self.futures_client.close_position(symbol)
                    if success:
                        success_count += 1
                        self.logger.info(f"바이낸스 포지션 청산: {symbol}")

                QMessageBox.information(self, "🎯 전체 청산 완료",
                                        f"바이낸스 테스트넷 포지션 청산 완료:\n"
                                        f"✅ 성공: {success_count}개\n"
                                        f"📊 총 포지션: {len(active_positions)}개")
                self.update_portfolio_display()

        except Exception as e:
            QMessageBox.critical(self, "바이낸스 API 오류",
                                 f"포지션 청산 중 오류:\n{e}")
            self.logger.error(f"전체 포지션 청산 오류: {e}")

    def test_binance_connection(self):
        """바이낸스 테스트넷 연결 테스트"""
        dialog = QDialog(self)
        dialog.setWindowTitle("🔧 바이낸스 연결 테스트")
        dialog.setGeometry(300, 300, 500, 400)
        dialog.setStyleSheet(self.styleSheet())

        layout = QVBoxLayout(dialog)

        # 테스트 결과 표시 영역
        result_text = QTextEdit()
        result_text.setReadOnly(True)
        result_text.setStyleSheet("""
            QTextEdit {
                background-color: #1e2329;
                color: #f0f0f0;
                border: 1px solid #2b3139;
                border-radius: 4px;
                padding: 10px;
                font-family: 'Courier New', monospace;
                font-size: 12px;
            }
        """)
        layout.addWidget(result_text)

        # 버튼
        button_layout = QHBoxLayout()

        test_btn = QPushButton("🔄 연결 테스트 시작")
        test_btn.setStyleSheet("""
            QPushButton {
                background-color: #f0b90b;
                color: black;
                font-weight: bold;
                padding: 10px 20px;
                border: none;
                border-radius: 4px;
            }
        """)

        def run_connection_test():
            result_text.clear()
            result_text.append("🔧 바이낸스 테스트넷 연결 테스트 시작...\n")
            QApplication.processEvents()

            # 1. 기본 연결 테스트
            result_text.append("1️⃣ 기본 연결 테스트...")
            try:
                import time
                start_time = time.time()
                balance = self.futures_client.get_futures_balance()
                response_time = time.time() - start_time

                if balance and balance['balance'] >= 0:
                    result_text.append(f"   ✅ 성공! (응답시간: {response_time:.2f}초)")
                    result_text.append(f"   💰 USDT 잔고: ${balance['balance']:.2f}")
                    result_text.append(f"   💎 사용가능: ${balance['available']:.2f}\n")
                else:
                    result_text.append("   ❌ 잔고 조회 실패\n")

            except Exception as e:
                result_text.append(f"   ❌ 실패: {e}\n")

            QApplication.processEvents()

            # 2. 포지션 정보 테스트
            result_text.append("2️⃣ 포지션 정보 조회 테스트...")
            try:
                start_time = time.time()
                positions = self.futures_client.get_position_info()
                response_time = time.time() - start_time

                if positions is not None:
                    active_count = len([p for p in positions if float(p.get('positionAmt', 0)) != 0])
                    result_text.append(f"   ✅ 성공! (응답시간: {response_time:.2f}초)")
                    result_text.append(f"   📊 총 포지션 수: {len(positions)}")
                    result_text.append(f"   🎯 활성 포지션: {active_count}개\n")
                else:
                    result_text.append("   ❌ 포지션 조회 실패\n")

            except Exception as e:
                result_text.append(f"   ❌ 실패: {e}\n")

            QApplication.processEvents()

            # 3. 최소 주문 테스트 (시뮬레이션)
            result_text.append("3️⃣ 주문 파라미터 검증 테스트...")
            try:
                symbol = "BTCUSDT"
                test_quantity = 0.001
                formatted_qty = self.futures_client.format_quantity(symbol, test_quantity)
                min_qty = self.futures_client.get_min_quantity(symbol)
                precision = self.futures_client.get_symbol_precision(symbol)

                result_text.append(f"   ✅ 심볼: {symbol}")
                result_text.append(f"   📏 최소 수량: {min_qty}")
                result_text.append(f"   🎯 정밀도: {precision}")
                result_text.append(f"   🔧 포맷팅 결과: {test_quantity} → {formatted_qty}\n")

            except Exception as e:
                result_text.append(f"   ❌ 실패: {e}\n")

            QApplication.processEvents()

            # 결과 요약
            result_text.append("=" * 50)
            result_text.append("🎯 테스트 완료!\n")
            result_text.append("💡 권장 사항:")
            result_text.append("• 모든 테스트가 성공했다면 레버리지 거래 가능")
            result_text.append("• 응답시간이 5초 이상이면 네트워크 최적화 필요")
            result_text.append("• 오류 발생 시 30초 후 재시도 권장")
            result_text.append("• 타임아웃 오류가 지속되면 VPN 사용 고려")

            # 스크롤을 맨 아래로
            result_text.moveCursor(result_text.textCursor().End)

        test_btn.clicked.connect(run_connection_test)
        button_layout.addWidget(test_btn)

        close_btn = QPushButton("닫기")
        close_btn.clicked.connect(dialog.close)
        button_layout.addWidget(close_btn)

        layout.addLayout(button_layout)

        # 초기 메시지
        result_text.append("🔧 바이낸스 테스트넷 연결 상태를 확인합니다.")
        result_text.append("'연결 테스트 시작' 버튼을 클릭하세요.\n")
        result_text.append("⚠️ 주의: 실제 주문은 발생하지 않습니다.")

        dialog.exec_()

    def reset_portfolio(self):
        """포트폴리오 초기화 (현물만, 바이낸스 선물은 실제 계정이므로 제외)"""
        reply = QMessageBox.question(
            self, '포트폴리오 초기화',
            '현물 거래 포트폴리오를 초기화하시겠습니까?\n\n'
            '⚠️ 주의: 바이낸스 테스트넷 선물 포지션은 실제 계정이므로\n'
            '초기화되지 않습니다. 별도로 청산해주세요.',
            QMessageBox.Yes | QMessageBox.No
        )

        if reply == QMessageBox.Yes:
            # 현물 거래만 초기화
            success, message = self.trading_engine.reset_portfolio()

            if success:
                QMessageBox.information(self, "초기화 완료",
                                        f"현물 거래 포트폴리오가 초기화되었습니다.\n\n"
                                        f"💡 바이낸스 선물 포지션이 있다면\n"
                                        f"'거래 → 전체 포지션 청산'으로 별도 청산하세요.")
                self.update_portfolio_display()
            else:
                QMessageBox.warning(self, "초기화 실패", f"현물 포트폴리오 초기화 실패:\n{message}")

    def toggle_fullscreen(self):
        """전체화면 토글"""
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

    def show_about(self):
        """정보 대화상자 표시"""
        QMessageBox.about(
            self, "🪙 Genius Coin Manager",
            "Genius Coin Manager v2.0\n\n"
            "🚀 실시간 차트 & 모의투자 프로그램\n\n"
            "✨ 새로운 기능:\n"
            "• 바이낸스 스타일 UI\n"
            "• 실시간 캔들스틱 차트\n"
            "• Q1~Q3 기반 스마트 스케일링\n"
            "• 다양한 시간대 (1분~1일)\n"
            "• 기술적 지표 (MA, Bollinger, RSI)\n"
            "• 빠른 거래 시스템\n\n"
            "🔧 기술 스택:\n"
            "Python 3.10 + PyQt5 + matplotlib\n"
            "python-binance + pandas + numpy\n\n"
            "⚠️ 이것은 모의투자 프로그램입니다."
        )

    def closeEvent(self, event):
        """프로그램 종료 시 호출"""
        try:
            # 트레이딩봇 정지
            if hasattr(self, 'advanced_bot') and self.advanced_bot:
                self.logger.info("프로그램 종료: 트레이딩봇 정지 중...")
                # 비동기 봇 정지는 여기서는 간단히 처리
                self.advanced_bot = None

            # 활성 바이낸스 포지션 확인
            futures_positions = self.futures_client.get_position_info()
            if futures_positions:
                active_positions = [pos for pos in futures_positions if float(pos.get('positionAmt', 0)) != 0]

                if active_positions:
                    reply = QMessageBox.question(
                        self, '⚠️ 활성 포지션 확인',
                        f'바이낸스 테스트넷에 {len(active_positions)}개의 활성 포지션이 있습니다.\n\n'
                        f'프로그램을 종료하면 포지션이 유지됩니다.\n'
                        f'포지션을 청산하고 종료하시겠습니까?',
                        QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel
                    )

                    if reply == QMessageBox.Cancel:
                        event.ignore()
                        return
                    elif reply == QMessageBox.Yes:
                        # 모든 포지션 청산
                        for position in active_positions:
                            try:
                                symbol = position['symbol']
                                self.futures_client.close_position(symbol)
                                self.logger.info(f"종료 시 포지션 청산: {symbol}")
                            except Exception as e:
                                self.logger.error(f"종료 시 포지션 청산 실패: {symbol} - {e}")

                        QMessageBox.information(self, "포지션 청산 완료", "모든 포지션이 청산되었습니다.")

        except Exception as e:
            self.logger.error(f"종료 시 바이낸스 확인 오류: {e}")

        # 모든 스레드 정리
        if hasattr(self, 'price_thread'):
            self.price_thread.stop()
        if hasattr(self, 'chart_update_thread'):
            self.chart_update_thread.stop()
        if hasattr(self, 'chart_widget') and hasattr(self.chart_widget, 'ws_manager'):
            self.chart_widget.ws_manager.stop()

        self.logger.info("🏁 Genius Coin Manager (바이낸스 테스트넷 + 트레이딩봇) 종료")
        event.accept()

    def start_trading_bot(self):
        """트레이딩봇 시작"""
        try:
            if not ADVANCED_BOT_AVAILABLE:
                QMessageBox.warning(self, "봇 모듈 오류", 
                                    "트레이딩봇 모듈을 찾을 수 없습니다.\n"
                                    "trading_bot_integration.py와 strategy_adapter.py 파일을 확인하세요.")
                return
            
            # 설정 값 가져오기
            symbol = self.header_symbol_combo.currentText() if hasattr(self, 'header_symbol_combo') else "BTCUSDT"
            strategy = self.strategy_combo.currentText()
            leverage = int(self.bot_leverage_combo.currentText().replace('x', ''))
            position_size = float(self.bot_amount_input.text() or "30.0")
            stop_loss = float(self.stop_loss_input.text() or "-2.0")
            take_profit = float(self.take_profit_input.text() or "8.0")
            
            # 봇 설정 생성
            bot_config = TradingBotConfig(
                symbol=symbol,
                timeframe="1h",
                strategy_name=strategy,
                leverage=leverage,
                position_size_pct=position_size,
                stop_loss_pct=stop_loss,
                take_profit_pct=take_profit,
                max_positions=2
            )
            
            # 기존 봇이 있다면 중지
            if self.advanced_bot and hasattr(self.advanced_bot, 'is_running') and self.advanced_bot.is_running:
                self.stop_trading_bot()
            
            # 새 봇 시작
            self.advanced_bot = AdvancedTradingBot(bot_config)
            
            # 비동기 실행을 위한 스레드 시작
            import threading
            def run_bot():
                import asyncio
                try:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    loop.run_until_complete(self.advanced_bot.start())
                except Exception as e:
                    print(f"봇 실행 오류: {e}")
                finally:
                    loop.close()
            
            self.bot_thread = threading.Thread(target=run_bot, daemon=True)
            self.bot_thread.start()
            
            # UI 업데이트
            self.bot_status_label.setText("실행 중 🟢")
            self.bot_status_label.setStyleSheet("""
                QLabel {
                    background-color: #2b3139;
                    color: #0ecb81;
                    padding: 8px;
                    border-radius: 4px;
                    font-weight: bold;
                }
            """)
            
            self.start_bot_btn.setEnabled(False)
            self.stop_bot_btn.setEnabled(True)
            
            QMessageBox.information(self, "🤖 봇 시작", 
                                    f"트레이딩봇이 시작되었습니다!\n"
                                    f"심볼: {symbol}\n"
                                    f"전략: {strategy}\n"
                                    f"레버리지: {leverage}x")
            
        except Exception as e:
            QMessageBox.critical(self, "봇 시작 오류", f"트레이딩봇 시작 중 오류가 발생했습니다:\n{e}")
    
    def stop_trading_bot(self):
        """트레이딩봇 중지"""
        try:
            if self.advanced_bot:
                # 봇 중지
                import asyncio
                import threading
                
                def stop_bot():
                    try:
                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)
                        loop.run_until_complete(self.advanced_bot.stop())
                    except Exception as e:
                        print(f"봇 중지 오류: {e}")
                    finally:
                        loop.close()
                
                stop_thread = threading.Thread(target=stop_bot, daemon=True)
                stop_thread.start()
                stop_thread.join(timeout=5)  # 5초 대기
                
            # UI 업데이트
            self.bot_status_label.setText("중지됨 ⭕")
            self.bot_status_label.setStyleSheet("""
                QLabel {
                    background-color: #2b3139;
                    color: #f6465d;
                    padding: 8px;
                    border-radius: 4px;
                    font-weight: bold;
                }
            """)
            
            self.start_bot_btn.setEnabled(True)
            self.stop_bot_btn.setEnabled(False)
            
            QMessageBox.information(self, "🤖 봇 중지", "트레이딩봇이 중지되었습니다.")
            
        except Exception as e:
            QMessageBox.critical(self, "봇 중지 오류", f"트레이딩봇 중지 중 오류가 발생했습니다:\n{e}")
    
    def update_bot_performance(self):
        """봇 성과 업데이트 (주기적으로 호출)"""
        try:
            if self.advanced_bot and hasattr(self.advanced_bot, 'performance_metrics'):
                metrics = self.advanced_bot.performance_metrics
                total_trades = metrics.get('total_trades', 0)
                winning_trades = metrics.get('winning_trades', 0)
                total_pnl = metrics.get('total_pnl', 0.0)
                
                win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0
                
                self.bot_performance_label.setText(
                    f"거래: {total_trades}건 | 승률: {win_rate:.1f}% | 수익: {total_pnl:.2f} USDT"
                )
        except Exception as e:
            print(f"봇 성과 업데이트 오류: {e}")

def main():
    # Qt 플러그인 경로 자동 설정 (macOS 호환성)
    import os
    try:
        import PyQt5
        pyqt5_path = os.path.dirname(PyQt5.__file__)
        plugin_path = os.path.join(pyqt5_path, 'Qt5', 'plugins')
        if os.path.exists(plugin_path):
            os.environ['QT_QPA_PLATFORM_PLUGIN_PATH'] = plugin_path
            print(f"Qt 플러그인 경로 설정: {plugin_path}")
    except Exception as e:
        print(f"Qt 경로 설정 중 오류 (무시 가능): {e}")

    app = QApplication(sys.argv)
    app.setStyle('Fusion')  # 모던한 스타일 적용

    # 애플리케이션 아이콘 및 정보 설정
    app.setApplicationName("Genius Coin Manager")
    app.setApplicationVersion("3.0")
    app.setOrganizationName("Genius Trading")

    try:
        window = TradingGUI()

        # 🚀 바이낸스 테스트넷 연결 확인
        try:
            futures_balance = window.futures_client.get_futures_balance()
            print(f"✅ 바이낸스 테스트넷 연결 성공!")
            print(f"💰 USDT 잔고: ${futures_balance['balance']:.2f}")
            print(f"💎 사용가능: ${futures_balance['available']:.2f}")

            # GUI에 연결 상태 표시
            window.statusBar().showMessage("🚀 바이낸스 테스트넷 연결됨")

        except Exception as e:
            print(f"⚠️ 바이낸스 테스트넷 연결 실패: {e}")
            QMessageBox.warning(window, "바이낸스 연결 오류",
                                f"바이낸스 테스트넷 연결에 실패했습니다:\n{e}\n\n"
                                f"현물 거래는 정상 작동하지만, 레버리지 거래는 불가능합니다.\n"
                                f"API 키와 네트워크 연결을 확인해주세요.")
            window.statusBar().showMessage("⚠️ 바이낸스 연결 실패 - 현물 거래만 가능")

        window.show()

        print("🚀 Genius Coin Manager v3.0 시작됨")
        print("📊 실시간 차트 + 바이낸스 테스트넷 레버리지 거래!")
        print("⚡ 레버리지 탭에서 실제 바이낸스 선물 거래 가능!")

        sys.exit(app.exec_())

    except Exception as e:
        print(f"❌ 애플리케이션 시작 오류: {e}")
        QMessageBox.critical(None, "시작 오류", f"프로그램을 시작할 수 없습니다:\n{e}")

if __name__ == '__main__':
    main()