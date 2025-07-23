# gui_app.py - 새로운 실시간 차트 통합 버전
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
from trading_bot.bot_engine import TradingBot
from trading_bot.bot_config import BotConfig
from order_book_widget import MatplotlibOrderBook  # 호가창 위젯 추가

class PriceUpdateThread(QThread):
    """가격 업데이트를 위한 스레드"""
    price_updated = pyqtSignal(dict)

    def __init__(self, trading_engine):
        super().__init__()
        self.trading_engine = trading_engine
        self.running = False

    def run(self):
        self.running = True
        while self.running:
            if self.trading_engine.update_prices():
                self.price_updated.emit(self.trading_engine.current_prices)
            self.msleep(5000)  # 5초마다 업데이트

    def stop(self):
        self.running = False
        self.wait()

class TradingGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.trading_engine = TradingEngine()
        self.cross_position_manager = CrossPositionManager()
        
        # 🚀 바이낸스 선물 클라이언트 (재시도 로직 적용)
        base_futures_client = BinanceFuturesClient()
        self.futures_client = retry_wrapper.create_resilient_client(base_futures_client)
        
        # 🤖 트레이딩봇 시스템
        self.trading_bots = {}  # 여러 봇 관리
        self.active_bot = None
        
        self.current_prices = {}

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

    def init_ui(self):
        """UI 초기화 - 바이낸스 스타일 (창 크기 최적화)"""
        self.setWindowTitle("🪙 Genius Coin Manager - 실시간 차트 + 호가창 🚀")
        self.setGeometry(100, 100, 1700, 900)  # 창 크기 증가 (호가창 공간 확보)

        # 중앙 위젯 설정
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        # 메인 레이아웃 (수직)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setSpacing(8)  # 간격 증가
        main_layout.setContentsMargins(8, 8, 8, 8)  # 여백 증가

        # 상단 헤더 (코인 정보)
        header = self.create_header()
        main_layout.addWidget(header)

        # 중앙 영역: 차트 + 호가창 (수평 분할)
        center_layout = QHBoxLayout()
        
        # 왼쪽: 차트 영역 (큰 비중)
        chart_container = QWidget()
        chart_layout = QVBoxLayout(chart_container)
        chart_layout.setContentsMargins(0, 0, 0, 0)
        
        self.chart_widget = CandlestickChart(self.trading_engine)
        self.chart_widget.figure.set_size_inches(14, 8)  # 차트 크기 조정
        self.chart_widget.canvas.setMinimumHeight(500)
        chart_layout.addWidget(self.chart_widget)
        
        center_layout.addWidget(chart_container, 3)  # 3:1 비율로 차트가 더 크게
        
        # 오른쪽: 호가창 영역 🚀
        self.order_book_widget = MatplotlibOrderBook(self.trading_engine)
        self.order_book_widget.setMaximumWidth(350)  # 최대 너비 제한
        self.order_book_widget.setMinimumWidth(300)  # 최소 너비 설정
        
        # 호가창 가격 클릭 시 입력창에 자동 입력 🚀
        self.order_book_widget.price_clicked.connect(self.on_orderbook_price_clicked)
        
        center_layout.addWidget(self.order_book_widget, 1)  # 1 비율
        
        main_layout.addLayout(center_layout, 1)

        # 하단 거래 패널
        bottom_panel = self.create_bottom_panel()
        main_layout.addWidget(bottom_panel)

        # 상태바
        self.statusBar().showMessage("연결 중...")

        # 메뉴바
        self.create_menu_bar()

        # 차트 자동 업데이트 스레드
        self.chart_update_thread = ChartUpdateThread(self.chart_widget)
        self.chart_update_thread.update_signal.connect(self.chart_widget.update_chart)
        self.chart_update_thread.start()

        # 스타일 적용
        self.apply_binance_theme()

        # 초기 데이터 로드
        self.update_portfolio_display()

    def closeEvent(self, event):
        """애플리케이션 종료 시 정리 작업"""
        try:
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

        # 심볼 선택
        self.main_symbol_combo = QComboBox()
        self.main_symbol_combo.addItems(Config.SUPPORTED_PAIRS)
        self.main_symbol_combo.currentTextChanged.connect(self.on_main_symbol_changed)
        self.main_symbol_combo.setStyleSheet("""
            QComboBox {
                font-size: 14px;
                font-weight: bold;
                background-color: transparent;
                border: none;
                color: #f0f0f0;
            }
        """)
        left_section.addWidget(self.main_symbol_combo)

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

    def create_bottom_panel(self):
        """하단 거래 패널 생성 - 레버리지 거래 추가"""
        panel = QFrame()
        panel.setFixedHeight(200)  # 높이 더 크게 증가
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
                padding: 16px 24px;
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
        self.leverage_combo.addItems(["5x", "10x", "20x", "50x", "100x"])
        self.leverage_combo.setCurrentText("10x")
        self.leverage_combo.setMaximumWidth(90)  # 너비 증가
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
        self.bot_symbol_combo.setMaximumWidth(110)  # 너비 증가
        self.bot_symbol_combo.setStyleSheet("""
            QComboBox {
                font-size: 13px;  # 폰트 크기 증가
                background-color: #2b3139;
                border: 1px solid #f0b90b;
                border-radius: 3px;
                padding: 6px;  # 패딩 증가
            }
        """)
        bot_config_section.addWidget(self.bot_symbol_combo)

        self.bot_amount_input = QLineEdit()
        self.bot_amount_input.setPlaceholderText("$200")
        self.bot_amount_input.setText("200")
        self.bot_amount_input.setMaximumWidth(110)  # 너비 증가
        bot_config_section.addWidget(self.bot_amount_input)
        layout.addLayout(bot_config_section)

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
                font-size: 13px;  # 폰트 크기 증가
                font-weight: bold;
                padding: 10px 14px;  # 패딩 증가
                border: none;
                border-radius: 3px;
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
                font-size: 13px;  # 폰트 크기 증가
                font-weight: bold;
                padding: 10px 14px;  # 패딩 증가
                border: none;
                border-radius: 3px;
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

    def create_top_panel(self):
        """상단 거래 컨트롤 패널 생성"""
        panel = QFrame()
        panel.setFixedHeight(100)
        panel.setStyleSheet("""
            QFrame {
                background-color: #2b2b2b;
                border: 1px solid #555;
                border-radius: 5px;
                margin: 5px;
            }
        """)

        layout = QHBoxLayout(panel)

        # 현재 가격 정보
        price_group = self.create_price_info_group()
        layout.addWidget(price_group, 2)

        # 빠른 거래 섹션
        quick_trade_group = self.create_quick_trade_group()
        layout.addWidget(quick_trade_group, 3)

        return panel

    def create_price_info_group(self):
        """가격 정보 그룹"""
        group = QGroupBox("현재 시세")
        layout = QVBoxLayout(group)

        # 심볼 선택과 연동
        self.main_symbol_combo = QComboBox()
        self.main_symbol_combo.addItems(Config.SUPPORTED_PAIRS)
        self.main_symbol_combo.currentTextChanged.connect(self.on_main_symbol_changed)
        layout.addWidget(self.main_symbol_combo)

        # 가격 표시
        self.main_price_label = QLabel("$0.0000")
        self.main_price_label.setStyleSheet("""
            font-size: 24px; 
            font-weight: bold; 
            color: #00ff88;
            background-color: #1a1a1a;
            border: 1px solid #333;
            border-radius: 3px;
            padding: 5px;
            text-align: center;
        """)
        self.main_price_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.main_price_label)

        return group

    def create_quick_trade_group(self):
        """빠른 거래 그룹"""
        group = QGroupBox("빠른 거래")
        layout = QHBoxLayout(group)

        # 매수 섹션
        buy_layout = QVBoxLayout()
        buy_layout.addWidget(QLabel("매수 금액 (USD):"))
        self.quick_buy_input = QLineEdit()
        self.quick_buy_input.setPlaceholderText("예: 100")
        buy_layout.addWidget(self.quick_buy_input)

        self.quick_buy_btn = QPushButton("💰 빠른 매수")
        self.quick_buy_btn.setStyleSheet("""
            QPushButton {
                background-color: #00C851;
                color: white;
                font-size: 14px;
                font-weight: bold;
                padding: 10px;
            }
            QPushButton:hover {
                background-color: #00A843;
            }
        """)
        self.quick_buy_btn.clicked.connect(self.execute_quick_buy)
        buy_layout.addWidget(self.quick_buy_btn)

        layout.addLayout(buy_layout)

        # 매도 섹션
        sell_layout = QVBoxLayout()
        sell_layout.addWidget(QLabel("매도 비율 (%):"))
        self.quick_sell_input = QLineEdit()
        self.quick_sell_input.setPlaceholderText("예: 50 (50%)")
        sell_layout.addWidget(self.quick_sell_input)

        self.quick_sell_btn = QPushButton("💸 빠른 매도")
        self.quick_sell_btn.setStyleSheet("""
            QPushButton {
                background-color: #FF4444;
                color: white;
                font-size: 14px;
                font-weight: bold;
                padding: 10px;
            }
            QPushButton:hover {
                background-color: #FF3333;
            }
        """)
        self.quick_sell_btn.clicked.connect(self.execute_quick_sell)
        sell_layout.addWidget(self.quick_sell_btn)

        layout.addLayout(sell_layout)

        return group

    def create_sidebar(self):
        """사이드바 생성"""
        sidebar = QWidget()
        layout = QVBoxLayout(sidebar)

        # 포트폴리오 현황
        portfolio_group = self.create_portfolio_group()
        layout.addWidget(portfolio_group, 2)

        # 보유 코인
        holdings_group = self.create_holdings_group()
        layout.addWidget(holdings_group, 2)

        # 거래 내역
        history_group = self.create_history_group()
        layout.addWidget(history_group, 2)

        return sidebar

    def create_portfolio_group(self):
        """포트폴리오 현황 그룹"""
        group = QGroupBox("💼 포트폴리오 현황")
        layout = QVBoxLayout(group)

        # 포트폴리오 요약 정보
        self.total_value_label = QLabel("총 자산: $0.00")
        self.total_value_label.setStyleSheet("font-size: 16px; font-weight: bold; color: #00ff88;")
        layout.addWidget(self.total_value_label)

        self.cash_balance_label = QLabel("현금 잔고: $0.00")
        layout.addWidget(self.cash_balance_label)

        self.invested_value_label = QLabel("투자 금액: $0.00")
        layout.addWidget(self.invested_value_label)

        self.profit_loss_label = QLabel("총 손익: $0.00 (0.00%)")
        layout.addWidget(self.profit_loss_label)

        return group

    def create_holdings_group(self):
        """보유 코인 그룹"""
        group = QGroupBox("💰 보유 코인")
        layout = QVBoxLayout(group)

        self.holdings_table = QTableWidget()
        self.holdings_table.setColumnCount(4)
        self.holdings_table.setHorizontalHeaderLabels(["코인", "수량", "현재가", "평가액"])
        self.holdings_table.horizontalHeader().setStretchLastSection(True)
        self.holdings_table.setAlternatingRowColors(True)
        self.holdings_table.setMaximumHeight(200)
        layout.addWidget(self.holdings_table)

        return group

    def create_history_group(self):
        """거래 내역 그룹"""
        group = QGroupBox("📋 최근 거래")
        layout = QVBoxLayout(group)

        self.transaction_table = QTableWidget()
        self.transaction_table.setColumnCount(4)
        self.transaction_table.setHorizontalHeaderLabels(["타입", "심볼", "수량", "가격"])
        self.transaction_table.horizontalHeader().setStretchLastSection(True)
        self.transaction_table.setAlternatingRowColors(True)
        layout.addWidget(self.transaction_table)

        return group

    def init_price_thread(self):
        """가격 업데이트 스레드 초기화"""
        self.price_thread = PriceUpdateThread(self.trading_engine)
        self.price_thread.price_updated.connect(self.update_prices)
        self.price_thread.start()

    def on_main_symbol_changed(self, symbol):
        """메인 심볼 변경 시 호출"""
        # 코인 아이콘 변경
        coin_icons = {
            "BTCUSDT": "₿", "ETHUSDT": "Ξ", "BNBUSDT": "🅱",
            "ADAUSDT": "₳", "SOLUSDT": "◎", "XRPUSDT": "✕",
            "DOTUSDT": "●", "AVAXUSDT": "🔺", "MATICUSDT": "🔷", "LINKUSDT": "🔗"
        }
        self.coin_icon.setText(coin_icons.get(symbol, "🪙"))

        # 코인별 색상 변경
        coin_colors = {
            "BTCUSDT": "#f7931a", "ETHUSDT": "#627eea", "BNBUSDT": "#f3ba2f",
            "ADAUSDT": "#0033ad", "SOLUSDT": "#00d4aa", "XRPUSDT": "#23292f",
            "DOTUSDT": "#e6007a", "AVAXUSDT": "#e84142", "MATICUSDT": "#8247e5", "LINKUSDT": "#375bd2"
        }
        color = coin_colors.get(symbol, "#f0b90b")
        self.coin_icon.setStyleSheet(f"font-size: 24px; color: {color}; font-weight: bold;")

        # 차트도 함께 변경
        if hasattr(self.chart_widget, 'symbol_combo'):
            self.chart_widget.symbol_combo.setCurrentText(symbol)

        # 🚀 호가창도 함께 변경
        if hasattr(self, 'order_book_widget'):
            self.order_book_widget.set_symbol(symbol)

        # 가격 업데이트
        if symbol in self.current_prices:
            price = self.current_prices[symbol]
            self.main_price_label.setText(f"${price:,.4f}")

    def on_orderbook_price_clicked(self, price):
        """호가창 가격 클릭 시 호출 - 입력창에 자동 입력 🚀"""
        try:
            # 선택된 탭에 따라 해당 입력창에 가격 입력
            price_str = f"{price:.4f}"
            
            # 현재 활성화된 탭의 입력창에 가격 입력
            # 현물 거래의 경우 USD 금액으로 계산해서 입력
            if hasattr(self, 'quick_buy_input'):
                # 예시: $100 정도의 금액으로 자동 계산
                amount = min(100.0, 1000.0 / price)
                self.quick_buy_input.setText(f"{amount:.2f}")
            
            # 레버리지 거래의 경우 금액 입력
            if hasattr(self, 'long_amount_input'):
                self.long_amount_input.setText("100")  # 기본 $100
            
            if hasattr(self, 'short_amount_input'):
                self.short_amount_input.setText("100")  # 기본 $100
                
            # 상태바에 알림 표시
            self.statusBar().showMessage(f"📊 호가창 클릭: ${price:.4f} 가격 적용됨", 3000)
            
            self.logger.info(f"📊 호가창 가격 클릭: ${price:.4f}")
            
        except Exception as e:
            self.logger.error(f"호가창 가격 클릭 처리 오류: {e}")

    def update_prices(self, prices):
        """가격 업데이트 - 바이낸스 스타일"""
        self.current_prices = prices
        current_symbol = self.main_symbol_combo.currentText()

        if current_symbol in prices:
            price = prices[current_symbol]
            self.main_price_label.setText(f"${price:,.4f}")

            # 임시로 변동률 계산 (실제로는 24시간 데이터 필요)
            change = 85.99  # 예시 값
            change_pct = 0.07  # 예시 값

            if change >= 0:
                self.price_change_label.setText(f"+${change:.2f} (+{change_pct:.2f}%)")
                self.price_change_label.setStyleSheet("font-size: 16px; color: #0ecb81; margin-left: 10px;")
            else:
                self.price_change_label.setText(f"${change:.2f} ({change_pct:.2f}%)")
                self.price_change_label.setStyleSheet("font-size: 16px; color: #f6465d; margin-left: 10px;")

        # 포트폴리오 업데이트
        self.update_portfolio_display()
        
        # 🤖 봇 상태 업데이트
        if self.active_bot:
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
        if self.active_bot:
            status_msg += " | 🤖 봇 실행 중"
        self.statusBar().showMessage(status_msg)

    def update_portfolio_display(self):
        """포트폴리오 디스플레이 업데이트 - 현물 + 실제 바이낸스 레버리지"""
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

            # 헤더에 총합 정보 업데이트
            self.total_value_label.setText(f"총 자산: ${total_combined_value:,.2f}")

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

    def init_price_thread(self):
        """가격 업데이트 스레드 초기화"""
        self.price_thread = PriceUpdateThread(self.trading_engine)
        self.price_thread.price_updated.connect(self.update_prices)
        self.price_thread.start()

    def on_main_symbol_changed(self, symbol):
        """메인 심볼 변경 시 호출"""
        # 코인 아이콘 변경
        coin_icons = {
            "BTCUSDT": "₿", "ETHUSDT": "Ξ", "BNBUSDT": "🅱",
            "ADAUSDT": "₳", "SOLUSDT": "◎", "XRPUSDT": "✕",
            "DOTUSDT": "●", "AVAXUSDT": "🔺", "MATICUSDT": "🔷", "LINKUSDT": "🔗"
        }
        self.coin_icon.setText(coin_icons.get(symbol, "🪙"))

        # 코인별 색상 변경
        coin_colors = {
            "BTCUSDT": "#f7931a", "ETHUSDT": "#627eea", "BNBUSDT": "#f3ba2f",
            "ADAUSDT": "#0033ad", "SOLUSDT": "#00d4aa", "XRPUSDT": "#23292f",
            "DOTUSDT": "#e6007a", "AVAXUSDT": "#e84142", "MATICUSDT": "#8247e5", "LINKUSDT": "#375bd2"
        }
        color = coin_colors.get(symbol, "#f0b90b")
        self.coin_icon.setStyleSheet(f"font-size: 24px; color: {color}; font-weight: bold;")

        # 차트도 함께 변경
        if hasattr(self.chart_widget, 'symbol_combo'):
            self.chart_widget.symbol_combo.setCurrentText(symbol)

        # 🚀 호가창도 함께 변경
        if hasattr(self, 'order_book_widget'):
            self.order_book_widget.set_symbol(symbol)

        # 가격 업데이트
        if symbol in self.current_prices:
            price = self.current_prices[symbol]
            self.main_price_label.setText(f"${price:,.4f}")

    def on_orderbook_price_clicked(self, price):
        """호가창 가격 클릭 시 호출 - 입력창에 자동 입력 🚀"""
        try:
            # 선택된 탭에 따라 해당 입력창에 가격 입력
            price_str = f"{price:.4f}"
            
            # 현재 활성화된 탭의 입력창에 가격 입력
            # 현물 거래의 경우 USD 금액으로 계산해서 입력
            if hasattr(self, 'quick_buy_input'):
                # 예시: $100 정도의 금액으로 자동 계산
                amount = min(100.0, 1000.0 / price)
                self.quick_buy_input.setText(f"{amount:.2f}")
            
            # 레버리지 거래의 경우 금액 입력
            if hasattr(self, 'long_amount_input'):
                self.long_amount_input.setText("100")  # 기본 $100
            
            if hasattr(self, 'short_amount_input'):
                self.short_amount_input.setText("100")  # 기본 $100
                
            # 상태바에 알림 표시
            self.statusBar().showMessage(f"📊 호가창 클릭: ${price:.4f} 가격 적용됨", 3000)
            
            self.logger.info(f"📊 호가창 가격 클릭: ${price:.4f}")
            
        except Exception as e:
            self.logger.error(f"호가창 가격 클릭 처리 오류: {e}")

    def update_prices(self, prices):
        """가격 업데이트 - 바이낸스 스타일"""
        self.current_prices = prices
        current_symbol = self.main_symbol_combo.currentText()

        if current_symbol in prices:
            price = prices[current_symbol]
            self.main_price_label.setText(f"${price:,.4f}")

            # 임시로 변동률 계산 (실제로는 24시간 데이터 필요)
            change = 85.99  # 예시 값
            change_pct = 0.07  # 예시 값

            if change >= 0:
                self.price_change_label.setText(f"+${change:.2f} (+{change_pct:.2f}%)")
                self.price_change_label.setStyleSheet("font-size: 16px; color: #0ecb81; margin-left: 10px;")
            else:
                self.price_change_label.setText(f"${change:.2f} ({change_pct:.2f}%)")
                self.price_change_label.setStyleSheet("font-size: 16px; color: #f6465d; margin-left: 10px;")

        # 포트폴리오 업데이트
        self.update_portfolio_display()
        
        # 🤖 봇 상태 업데이트
        if self.active_bot:
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
        if self.active_bot:
            status_msg += " | 🤖 봇 실행 중"
        self.statusBar().showMessage(status_msg)

    def update_portfolio_display(self):
        """포트폴리오 디스플레이 업데이트 - 현물 + 실제 바이낸스 레버리지"""
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

            # 헤더에 총합 정보 업데이트
            self.total_value_label.setText(f"총 자산: ${total_combined_value:,.2f}")

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
        symbol = self.main_symbol_combo.currentText()
        amount_text = self.quick_buy_input.text().strip()

        if not amount_text:
            QMessageBox.warning(self, "입력 오류", "매수 금액을 입력해주세요.")
            return

        try:
            amount = float(amount_text)
            success, message = self.trading_engine.place_buy_order(symbol, amount_usd=amount)

            if success:
                QMessageBox.information(self, "✅ 매수 성공", message)
                self.quick_buy_input.clear()
                self.update_portfolio_display()
            else:
                QMessageBox.warning(self, "❌ 매수 실패", message)

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

    def get_user_friendly_error_message(self, error_msg):
        """사용자 친화적인 오류 메시지 변환"""
        error_msg = str(error_msg).lower()
        
        if 'timeout' in error_msg or '-1007' in error_msg:
            return "서버 응답 시간 초과 (네트워크 지연)"
        elif 'insufficient' in error_msg or 'balance' in error_msg:
            return "잔고 부족"
        elif 'precision' in error_msg or 'lot size' in error_msg:
            return "주문 수량이 규정에 맞지 않음"
        elif 'market is closed' in error_msg:
            return "시장이 휴장 중"
        elif 'rate limit' in error_msg:
            return "요청 빈도 제한 초과"
        elif 'symbol' in error_msg and 'not found' in error_msg:
            return "지원하지 않는 거래쌍"
        else:
            return "일시적인 서버 오류"

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

    def start_trading_bot(self):
        """트레이딩봇 시작"""
        try:
            symbol = self.bot_symbol_combo.currentText()
            amount_text = self.bot_amount_input.text().strip()
            
            if not amount_text:
                QMessageBox.warning(self, "입력 오류", "거래 금액을 입력해주세요.")
                return
            
            amount = float(amount_text)
            if amount < 50:
                QMessageBox.warning(self, "입력 오류", "거래 금액은 최소 $50 이상이어야 합니다.")
                return
            
            # 기존 봇이 실행 중이면 정지
            if self.active_bot:
                self.stop_trading_bot()
            
            # 봇 설정 생성
            bot_config = BotConfig(
                bot_name=f"MA Cross Bot - {symbol}",
                strategy_name="ma_cross",
                symbol=symbol,
                base_amount=amount,
                trading_mode="spot",
                is_active=True
            )
            
            # 봇 생성 및 시작
            self.active_bot = TradingBot(bot_config, self.trading_engine)
            
            # 봇 시그널 연결
            self.active_bot.signal_generated.connect(self.on_bot_signal)
            self.active_bot.trade_executed.connect(self.on_bot_trade)
            self.active_bot.status_changed.connect(self.on_bot_status_changed)
            self.active_bot.error_occurred.connect(self.on_bot_error)
            
            # 봇 시작
            success, message = self.active_bot.start()
            
            if success:
                self.start_bot_btn.setEnabled(False)
                self.stop_bot_btn.setEnabled(True)
                self.bot_status_label.setText("실행 중")
                self.bot_status_label.setStyleSheet("font-size: 10px; color: #00C851;")
                
                QMessageBox.information(self, "🤖 봇 시작", 
                    f"트레이딩봇이 시작되었습니다!\n\n"
                    f"📊 심볼: {symbol}\n"
                    f"💰 거래 금액: ${amount:.2f}\n"
                    f"📈 전략: 이동평균 교차\n"
                    f"⚡ 모드: 현물 거래\n\n"
                    f"봇이 자동으로 거래를 시작합니다.")
                
                self.logger.info(f"🤖 트레이딩봇 시작: {symbol} ${amount}")
            else:
                QMessageBox.warning(self, "❌ 봇 시작 실패", message)
                self.active_bot = None
                
        except ValueError:
            QMessageBox.warning(self, "입력 오류", "올바른 숫자를 입력해주세요.")
        except Exception as e:
            QMessageBox.critical(self, "오류", f"봇 시작 중 오류:\n{e}")
            self.logger.error(f"봇 시작 오류: {e}")

    def stop_trading_bot(self):
        """트레이딩봇 정지"""
        try:
            if not self.active_bot:
                return
            
            success, message = self.active_bot.stop()
            
            if success:
                self.start_bot_btn.setEnabled(True)
                self.stop_bot_btn.setEnabled(False)
                self.bot_status_label.setText("정지됨")
                self.bot_status_label.setStyleSheet("font-size: 12px; color: #ff4444;")  # 폰트 크기 증가
                
                # 최종 성과 표시
                bot_status = self.active_bot.get_bot_status()
                risk_metrics = bot_status.get('risk_metrics', {})
                
                QMessageBox.information(self, "🤖 봇 정지", 
                    f"트레이딩봇이 정지되었습니다.\n\n"
                    f"📊 최종 성과:\n"
                    f"• 총 거래: {risk_metrics.get('daily_trades', 0)}회\n"
                    f"• 일일 손익: ${risk_metrics.get('daily_pnl', 0):+.2f}\n"
                    f"• 성공률: {risk_metrics.get('success_rate_24h', 0):.1f}%\n"
                    f"• 현재 포지션: {risk_metrics.get('current_positions', 0)}개")
                
                self.active_bot = None
                self.logger.info("🤖 트레이딩봇 정지됨")
            else:
                QMessageBox.warning(self, "❌ 봇 정지 실패", message)
                
        except Exception as e:
            QMessageBox.critical(self, "오류", f"봇 정지 중 오류:\n{e}")
            self.logger.error(f"봇 정지 오류: {e}")

    def on_bot_signal(self, signal_data):
        """봇 신호 수신"""
        action = signal_data.get('action', 'HOLD')
        price = signal_data.get('price', 0)
        reason = signal_data.get('reason', '')
        
        self.logger.info(f"🔔 봇 신호: {action} @${price:.4f} - {reason}")
        
        # 상태바에 표시
        if action != 'HOLD':
            self.statusBar().showMessage(f"🤖 봇 신호: {action} @${price:.4f}", 3000)

    def on_bot_trade(self, trade_data):
        """봇 거래 실행 알림"""
        symbol = trade_data.get('symbol', '')
        action = trade_data.get('action', '')
        amount = trade_data.get('amount', 0)
        price = trade_data.get('price', 0)
        success = trade_data.get('success', False)
        
        if success:
            self.logger.info(f"✅ 봇 거래 성공: {action} {symbol} ${amount:.2f} @${price:.4f}")
            
            # 상태바에 표시
            self.statusBar().showMessage(f"🤖 봇 거래: {action} {symbol} ${amount:.2f}", 5000)
            
            # 포트폴리오 업데이트
            self.update_portfolio_display()
            
            # 봇 통계 업데이트
            self.update_bot_status_display()
        else:
            self.logger.warning(f"❌ 봇 거래 실패: {action} {symbol}")

    def on_bot_status_changed(self, status):
        """봇 상태 변경"""
        status_map = {
            "running": ("실행 중", "#00C851"),
            "stopped": ("정지됨", "#ff4444"),
            "paused": ("일시정지", "#ff9800"),
            "error": ("오류", "#f44336")
        }
        
        text, color = status_map.get(status, ("알 수 없음", "#f0f0f0"))
        self.bot_status_label.setText(text)
        self.bot_status_label.setStyleSheet(f"font-size: 10px; color: {color};")

    def on_bot_error(self, error_msg):
        """봇 오류 처리"""
        self.logger.error(f"🤖 봇 오류: {error_msg}")
        QMessageBox.warning(self, "🤖 봇 오류", f"트레이딩봇에서 오류가 발생했습니다:\n{error_msg}")

    def update_bot_status_display(self):
        """봇 상태 디스플레이 업데이트"""
        if not self.active_bot:
            self.bot_trades_label.setText("거래: 0회")
            self.bot_pnl_label.setText("손익: $0.00")
            return
        
        try:
            bot_status = self.active_bot.get_bot_status()
            risk_metrics = bot_status.get('risk_metrics', {})
            
            trades = risk_metrics.get('daily_trades', 0)
            pnl = risk_metrics.get('daily_pnl', 0)
            
            self.bot_trades_label.setText(f"거래: {trades}회")
            
            pnl_text = f"손익: ${pnl:+.2f}"
            if pnl >= 0:
                self.bot_pnl_label.setStyleSheet("font-size: 10px; color: #00C851;")
            else:
                self.bot_pnl_label.setStyleSheet("font-size: 10px; color: #ff4444;")
            self.bot_pnl_label.setText(pnl_text)
            
        except Exception as e:
            self.logger.error(f"봇 상태 업데이트 오류: {e}")

    def show_bot_settings(self):
        """봇 설정 다이얼로그"""
        dialog = QDialog(self)
        dialog.setWindowTitle("🤖 트레이딩봇 설정")
        dialog.setGeometry(300, 300, 500, 600)
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
        dialog.setGeometry(200, 200, 800, 600)
        dialog.setStyleSheet(self.styleSheet())

        layout = QVBoxLayout(dialog)

        # 탭 위젯
        tab_widget = QTabWidget()

        # 봇 상태 탭
        status_tab = QWidget()
        status_layout = QVBoxLayout(status_tab)

        if self.active_bot:
            bot_status = self.active_bot.get_bot_status()
            risk_metrics = bot_status.get('risk_metrics', {})

            status_text = QTextEdit()
            status_text.setReadOnly(True)
            status_text.append("🤖 봇 현재 상태:")
            status_text.append(f"• 상태: {bot_status.get('bot_status', {}).get('status', 'Unknown')}")
            status_text.append(f"• 일일 거래: {risk_metrics.get('daily_trades', 0)}회")
            status_text.append(f"• 일일 손익: ${risk_metrics.get('daily_pnl', 0):+.2f}")
            status_text.append(f"• 성공률: {risk_metrics.get('success_rate_24h', 0):.1f}%")
            status_text.append(f"• 현재 포지션: {risk_metrics.get('current_positions', 0)}개")
            status_text.append(f"• 연속 손실: {risk_metrics.get('consecutive_losses', 0)}회")
            status_text.append(f"• 리스크 레벨: {risk_metrics.get('risk_level', 'UNKNOWN')}")

            status_layout.addWidget(status_text)
        else:
            no_bot_label = QLabel("현재 실행 중인 봇이 없습니다.")
            no_bot_label.setAlignment(Qt.AlignCenter)
            status_layout.addWidget(no_bot_label)

        tab_widget.addTab(status_tab, "📊 봇 상태")

        # 거래 내역 탭
        trades_tab = QWidget()
        trades_layout = QVBoxLayout(trades_tab)

        if self.active_bot:
            trade_history = self.active_bot.get_trade_history(50)
            
            trades_table = QTableWidget()
            trades_table.setColumnCount(6)
            trades_table.setHorizontalHeaderLabels(["시간", "심볼", "액션", "금액", "가격", "손익"])
            trades_table.setRowCount(len(trade_history))

            for i, trade in enumerate(trade_history):
                trades_table.setItem(i, 0, QTableWidgetItem(trade['timestamp'][:19]))
                trades_table.setItem(i, 1, QTableWidgetItem(trade['symbol']))
                trades_table.setItem(i, 2, QTableWidgetItem(trade['action']))
                trades_table.setItem(i, 3, QTableWidgetItem(f"${trade['amount']:.2f}"))
                trades_table.setItem(i, 4, QTableWidgetItem(f"${trade['price']:.4f}"))
                
                pnl_item = QTableWidgetItem(f"${trade['pnl']:+.2f}")
                if trade['pnl'] >= 0:
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

    def execute_quick_sell(self):
        """빠른 매도 실행"""
        symbol = self.main_symbol_combo.currentText()
        percentage_text = self.quick_sell_input.text().strip()

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

    def get_user_friendly_error_message(self, error_msg):
        """사용자 친화적인 오류 메시지 변환"""
        error_msg = str(error_msg).lower()
        
        if 'timeout' in error_msg or '-1007' in error_msg:
            return "서버 응답 시간 초과 (네트워크 지연)"
        elif 'insufficient' in error_msg or 'balance' in error_msg:
            return "잔고 부족"
        elif 'precision' in error_msg or 'lot size' in error_msg:
            return "주문 수량이 규정에 맞지 않음"
        elif 'market is closed' in error_msg:
            return "시장이 휴장 중"
        elif 'rate limit' in error_msg:
            return "요청 빈도 제한 초과"
        elif 'symbol' in error_msg and 'not found' in error_msg:
            return "지원하지 않는 거래쌍"
        else:
            return "일시적인 서버 오류"

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

    def start_trading_bot(self):
        """트레이딩봇 시작"""
        try:
            symbol = self.bot_symbol_combo.currentText()
            amount_text = self.bot_amount_input.text().strip()
            
            if not amount_text:
                QMessageBox.warning(self, "입력 오류", "거래 금액을 입력해주세요.")
                return
            
            amount = float(amount_text)
            if amount < 50:
                QMessageBox.warning(self, "입력 오류", "거래 금액은 최소 $50 이상이어야 합니다.")
                return
            
            # 기존 봇이 실행 중이면 정지
            if self.active_bot:
                self.stop_trading_bot()
            
            # 봇 설정 생성
            bot_config = BotConfig(
                bot_name=f"MA Cross Bot - {symbol}",
                strategy_name="ma_cross",
                symbol=symbol,
                base_amount=amount,
                trading_mode="spot",
                is_active=True
            )
            
            # 봇 생성 및 시작
            self.active_bot = TradingBot(bot_config, self.trading_engine)
            
            # 봇 시그널 연결
            self.active_bot.signal_generated.connect(self.on_bot_signal)
            self.active_bot.trade_executed.connect(self.on_bot_trade)
            self.active_bot.status_changed.connect(self.on_bot_status_changed)
            self.active_bot.error_occurred.connect(self.on_bot_error)
            
            # 봇 시작
            success, message = self.active_bot.start()
            
            if success:
                self.start_bot_btn.setEnabled(False)
                self.stop_bot_btn.setEnabled(True)
                self.bot_status_label.setText("실행 중")
                self.bot_status_label.setStyleSheet("font-size: 10px; color: #00C851;")
                
                QMessageBox.information(self, "🤖 봇 시작", 
                    f"트레이딩봇이 시작되었습니다!\n\n"
                    f"📊 심볼: {symbol}\n"
                    f"💰 거래 금액: ${amount:.2f}\n"
                    f"📈 전략: 이동평균 교차\n"
                    f"⚡ 모드: 현물 거래\n\n"
                    f"봇이 자동으로 거래를 시작합니다.")
                
                self.logger.info(f"🤖 트레이딩봇 시작: {symbol} ${amount}")
            else:
                QMessageBox.warning(self, "❌ 봇 시작 실패", message)
                self.active_bot = None
                
        except ValueError:
            QMessageBox.warning(self, "입력 오류", "올바른 숫자를 입력해주세요.")
        except Exception as e:
            QMessageBox.critical(self, "오류", f"봇 시작 중 오류:\n{e}")
            self.logger.error(f"봇 시작 오류: {e}")

    def stop_trading_bot(self):
        """트레이딩봇 정지"""
        try:
            if not self.active_bot:
                return
            
            success, message = self.active_bot.stop()
            
            if success:
                self.start_bot_btn.setEnabled(True)
                self.stop_bot_btn.setEnabled(False)
                self.bot_status_label.setText("정지됨")
                self.bot_status_label.setStyleSheet("font-size: 12px; color: #ff4444;")  # 폰트 크기 증가
                
                # 최종 성과 표시
                bot_status = self.active_bot.get_bot_status()
                risk_metrics = bot_status.get('risk_metrics', {})
                
                QMessageBox.information(self, "🤖 봇 정지", 
                    f"트레이딩봇이 정지되었습니다.\n\n"
                    f"📊 최종 성과:\n"
                    f"• 총 거래: {risk_metrics.get('daily_trades', 0)}회\n"
                    f"• 일일 손익: ${risk_metrics.get('daily_pnl', 0):+.2f}\n"
                    f"• 성공률: {risk_metrics.get('success_rate_24h', 0):.1f}%\n"
                    f"• 현재 포지션: {risk_metrics.get('current_positions', 0)}개")
                
                self.active_bot = None
                self.logger.info("🤖 트레이딩봇 정지됨")
            else:
                QMessageBox.warning(self, "❌ 봇 정지 실패", message)
                
        except Exception as e:
            QMessageBox.critical(self, "오류", f"봇 정지 중 오류:\n{e}")
            self.logger.error(f"봇 정지 오류: {e}")

    def on_bot_signal(self, signal_data):
        """봇 신호 수신"""
        action = signal_data.get('action', 'HOLD')
        price = signal_data.get('price', 0)
        reason = signal_data.get('reason', '')
        
        self.logger.info(f"🔔 봇 신호: {action} @${price:.4f} - {reason}")
        
        # 상태바에 표시
        if action != 'HOLD':
            self.statusBar().showMessage(f"🤖 봇 신호: {action} @${price:.4f}", 3000)

    def on_bot_trade(self, trade_data):
        """봇 거래 실행 알림"""
        symbol = trade_data.get('symbol', '')
        action = trade_data.get('action', '')
        amount = trade_data.get('amount', 0)
        price = trade_data.get('price', 0)
        success = trade_data.get('success', False)
        
        if success:
            self.logger.info(f"✅ 봇 거래 성공: {action} {symbol} ${amount:.2f} @${price:.4f}")
            
            # 상태바에 표시
            self.statusBar().showMessage(f"🤖 봇 거래: {action} {symbol} ${amount:.2f}", 5000)
            
            # 포트폴리오 업데이트
            self.update_portfolio_display()
            
            # 봇 통계 업데이트
            self.update_bot_status_display()
        else:
            self.logger.warning(f"❌ 봇 거래 실패: {action} {symbol}")

    def on_bot_status_changed(self, status):
        """봇 상태 변경"""
        status_map = {
            "running": ("실행 중", "#00C851"),
            "stopped": ("정지됨", "#ff4444"),
            "paused": ("일시정지", "#ff9800"),
            "error": ("오류", "#f44336")
        }
        
        text, color = status_map.get(status, ("알 수 없음", "#f0f0f0"))
        self.bot_status_label.setText(text)
        self.bot_status_label.setStyleSheet(f"font-size: 10px; color: {color};")

    def on_bot_error(self, error_msg):
        """봇 오류 처리"""
        self.logger.error(f"🤖 봇 오류: {error_msg}")
        QMessageBox.warning(self, "🤖 봇 오류", f"트레이딩봇에서 오류가 발생했습니다:\n{error_msg}")

    def update_bot_status_display(self):
        """봇 상태 디스플레이 업데이트"""
        if not self.active_bot:
            self.bot_trades_label.setText("거래: 0회")
            self.bot_pnl_label.setText("손익: $0.00")
            return
        
        try:
            bot_status = self.active_bot.get_bot_status()
            risk_metrics = bot_status.get('risk_metrics', {})
            
            trades = risk_metrics.get('daily_trades', 0)
            pnl = risk_metrics.get('daily_pnl', 0)
            
            self.bot_trades_label.setText(f"거래: {trades}회")
            
            pnl_text = f"손익: ${pnl:+.2f}"
            if pnl >= 0:
                self.bot_pnl_label.setStyleSheet("font-size: 10px; color: #00C851;")
            else:
                self.bot_pnl_label.setStyleSheet("font-size: 10px; color: #ff4444;")
            self.bot_pnl_label.setText(pnl_text)
            
        except Exception as e:
            self.logger.error(f"봇 상태 업데이트 오류: {e}")

    def show_bot_settings(self):
        """봇 설정 다이얼로그"""
        dialog = QDialog(self)
        dialog.setWindowTitle("🤖 트레이딩봇 설정")
        dialog.setGeometry(300, 300, 500, 600)
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
        dialog.setGeometry(200, 200, 800, 600)
        dialog.setStyleSheet(self.styleSheet())

        layout = QVBoxLayout(dialog)

        # 탭 위젯
        tab_widget = QTabWidget()

        # 봇 상태 탭
        status_tab = QWidget()
        status_layout = QVBoxLayout(status_tab)

        if self.active_bot:
            bot_status = self.active_bot.get_bot_status()
            risk_metrics = bot_status.get('risk_metrics', {})

            status_text = QTextEdit()
            status_text.setReadOnly(True)
            status_text.append("🤖 봇 현재 상태:")
            status_text.append(f"• 상태: {bot_status.get('bot_status', {}).get('status', 'Unknown')}")
            status_text.append(f"• 일일 거래: {risk_metrics.get('daily_trades', 0)}회")
            status_text.append(f"• 일일 손익: ${risk_metrics.get('daily_pnl', 0):+.2f}")
            status_text.append(f"• 성공률: {risk_metrics.get('success_rate_24h', 0):.1f}%")
            status_text.append(f"• 현재 포지션: {risk_metrics.get('current_positions', 0)}개")
            status_text.append(f"• 연속 손실: {risk_metrics.get('consecutive_losses', 0)}회")
            status_text.append(f"• 리스크 레벨: {risk_metrics.get('risk_level', 'UNKNOWN')}")

            status_layout.addWidget(status_text)
        else:
            no_bot_label = QLabel("현재 실행 중인 봇이 없습니다.")
            no_bot_label.setAlignment(Qt.AlignCenter)
            status_layout.addWidget(no_bot_label)

        tab_widget.addTab(status_tab, "📊 봇 상태")

        # 거래 내역 탭
        trades_tab = QWidget()
        trades_layout = QVBoxLayout(trades_tab)

        if self.active_bot:
            trade_history = self.active_bot.get_trade_history(50)
            
            trades_table = QTableWidget()
            trades_table.setColumnCount(6)
            trades_table.setHorizontalHeaderLabels(["시간", "심볼", "액션", "금액", "가격", "손익"])
            trades_table.setRowCount(len(trade_history))

            for i, trade in enumerate(trade_history):
                trades_table.setItem(i, 0, QTableWidgetItem(trade['timestamp'][:19]))
                trades_table.setItem(i, 1, QTableWidgetItem(trade['symbol']))
                trades_table.setItem(i, 2, QTableWidgetItem(trade['action']))
                trades_table.setItem(i, 3, QTableWidgetItem(f"${trade['amount']:.2f}"))
                trades_table.setItem(i, 4, QTableWidgetItem(f"${trade['price']:.4f}"))
                
                pnl_item = QTableWidgetItem(f"${trade['pnl']:+.2f}")
                if trade['pnl'] >= 0:
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
        leverage_combo.addItems(["5x", "10x", "20x", "50x", "100x"])
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
                
                symbol = self.main_symbol_combo.currentText()
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

    def start_trading_bot(self):
        """트레이딩봇 시작"""
        try:
            symbol = self.bot_symbol_combo.currentText()
            amount_text = self.bot_amount_input.text().strip()
            
            if not amount_text:
                QMessageBox.warning(self, "입력 오류", "거래 금액을 입력해주세요.")
                return
            
            amount = float(amount_text)
            if amount < 50:
                QMessageBox.warning(self, "입력 오류", "거래 금액은 최소 $50 이상이어야 합니다.")
                return
            
            # 기존 봇이 실행 중이면 정지
            if self.active_bot:
                self.stop_trading_bot()
            
            # 봇 설정 생성
            bot_config = BotConfig(
                bot_name=f"MA Cross Bot - {symbol}",
                strategy_name="ma_cross",
                symbol=symbol,
                base_amount=amount,
                trading_mode="spot",
                is_active=True
            )
            
            # 봇 생성 및 시작
            self.active_bot = TradingBot(bot_config, self.trading_engine)
            
            # 봇 시그널 연결
            self.active_bot.signal_generated.connect(self.on_bot_signal)
            self.active_bot.trade_executed.connect(self.on_bot_trade)
            self.active_bot.status_changed.connect(self.on_bot_status_changed)
            self.active_bot.error_occurred.connect(self.on_bot_error)
            
            # 봇 시작
            success, message = self.active_bot.start()
            
            if success:
                self.start_bot_btn.setEnabled(False)
                self.stop_bot_btn.setEnabled(True)
                self.bot_status_label.setText("실행 중")
                self.bot_status_label.setStyleSheet("font-size: 10px; color: #00C851;")
                
                QMessageBox.information(self, "🤖 봇 시작", 
                    f"트레이딩봇이 시작되었습니다!\n\n"
                    f"📊 심볼: {symbol}\n"
                    f"💰 거래 금액: ${amount:.2f}\n"
                    f"📈 전략: 이동평균 교차\n"
                    f"⚡ 모드: 현물 거래\n\n"
                    f"봇이 자동으로 거래를 시작합니다.")
                
                self.logger.info(f"🤖 트레이딩봇 시작: {symbol} ${amount}")
            else:
                QMessageBox.warning(self, "❌ 봇 시작 실패", message)
                self.active_bot = None
                
        except ValueError:
            QMessageBox.warning(self, "입력 오류", "올바른 숫자를 입력해주세요.")
        except Exception as e:
            QMessageBox.critical(self, "오류", f"봇 시작 중 오류:\n{e}")
            self.logger.error(f"봇 시작 오류: {e}")

    def stop_trading_bot(self):
        """트레이딩봇 정지"""
        try:
            if not self.active_bot:
                return
            
            success, message = self.active_bot.stop()
            
            if success:
                self.start_bot_btn.setEnabled(True)
                self.stop_bot_btn.setEnabled(False)
                self.bot_status_label.setText("정지됨")
                self.bot_status_label.setStyleSheet("font-size: 12px; color: #ff4444;")  # 폰트 크기 증가
                
                # 최종 성과 표시
                bot_status = self.active_bot.get_bot_status()
                risk_metrics = bot_status.get('risk_metrics', {})
                
                QMessageBox.information(self, "🤖 봇 정지", 
                    f"트레이딩봇이 정지되었습니다.\n\n"
                    f"📊 최종 성과:\n"
                    f"• 총 거래: {risk_metrics.get('daily_trades', 0)}회\n"
                    f"• 일일 손익: ${risk_metrics.get('daily_pnl', 0):+.2f}\n"
                    f"• 성공률: {risk_metrics.get('success_rate_24h', 0):.1f}%\n"
                    f"• 현재 포지션: {risk_metrics.get('current_positions', 0)}개")
                
                self.active_bot = None
                self.logger.info("🤖 트레이딩봇 정지됨")
            else:
                QMessageBox.warning(self, "❌ 봇 정지 실패", message)
                
        except Exception as e:
            QMessageBox.critical(self, "오류", f"봇 정지 중 오류:\n{e}")
            self.logger.error(f"봇 정지 오류: {e}")

    def on_bot_signal(self, signal_data):
        """봇 신호 수신"""
        action = signal_data.get('action', 'HOLD')
        price = signal_data.get('price', 0)
        reason = signal_data.get('reason', '')
        
        self.logger.info(f"🔔 봇 신호: {action} @${price:.4f} - {reason}")
        
        # 상태바에 표시
        if action != 'HOLD':
            self.statusBar().showMessage(f"🤖 봇 신호: {action} @${price:.4f}", 3000)

    def on_bot_trade(self, trade_data):
        """봇 거래 실행 알림"""
        symbol = trade_data.get('symbol', '')
        action = trade_data.get('action', '')
        amount = trade_data.get('amount', 0)
        price = trade_data.get('price', 0)
        success = trade_data.get('success', False)
        
        if success:
            self.logger.info(f"✅ 봇 거래 성공: {action} {symbol} ${amount:.2f} @${price:.4f}")
            
            # 상태바에 표시
            self.statusBar().showMessage(f"🤖 봇 거래: {action} {symbol} ${amount:.2f}", 5000)
            
            # 포트폴리오 업데이트
            self.update_portfolio_display()
            
            # 봇 통계 업데이트
            self.update_bot_status_display()
        else:
            self.logger.warning(f"❌ 봇 거래 실패: {action} {symbol}")

    def on_bot_status_changed(self, status):
        """봇 상태 변경"""
        status_map = {
            "running": ("실행 중", "#00C851"),
            "stopped": ("정지됨", "#ff4444"),
            "paused": ("일시정지", "#ff9800"),
            "error": ("오류", "#f44336")
        }
        
        text, color = status_map.get(status, ("알 수 없음", "#f0f0f0"))
        self.bot_status_label.setText(text)
        self.bot_status_label.setStyleSheet(f"font-size: 10px; color: {color};")

    def on_bot_error(self, error_msg):
        """봇 오류 처리"""
        self.logger.error(f"🤖 봇 오류: {error_msg}")
        QMessageBox.warning(self, "🤖 봇 오류", f"트레이딩봇에서 오류가 발생했습니다:\n{error_msg}")

    def update_bot_status_display(self):
        """봇 상태 디스플레이 업데이트"""
        if not self.active_bot:
            self.bot_trades_label.setText("거래: 0회")
            self.bot_pnl_label.setText("손익: $0.00")
            return
        
        try:
            bot_status = self.active_bot.get_bot_status()
            risk_metrics = bot_status.get('risk_metrics', {})
            
            trades = risk_metrics.get('daily_trades', 0)
            pnl = risk_metrics.get('daily_pnl', 0)
            
            self.bot_trades_label.setText(f"거래: {trades}회")
            
            pnl_text = f"손익: ${pnl:+.2f}"
            if pnl >= 0:
                self.bot_pnl_label.setStyleSheet("font-size: 10px; color: #00C851;")
            else:
                self.bot_pnl_label.setStyleSheet("font-size: 10px; color: #ff4444;")
            self.bot_pnl_label.setText(pnl_text)
            
        except Exception as e:
            self.logger.error(f"봇 상태 업데이트 오류: {e}")

    def show_bot_settings(self):
        """봇 설정 다이얼로그"""
        dialog = QDialog(self)
        dialog.setWindowTitle("🤖 트레이딩봇 설정")
        dialog.setGeometry(300, 300, 500, 600)
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
        dialog.setGeometry(200, 200, 800, 600)
        dialog.setStyleSheet(self.styleSheet())

        layout = QVBoxLayout(dialog)

        # 탭 위젯
        tab_widget = QTabWidget()

        # 봇 상태 탭
        status_tab = QWidget()
        status_layout = QVBoxLayout(status_tab)

        if self.active_bot:
            bot_status = self.active_bot.get_bot_status()
            risk_metrics = bot_status.get('risk_metrics', {})

            status_text = QTextEdit()
            status_text.setReadOnly(True)
            status_text.append("🤖 봇 현재 상태:")
            status_text.append(f"• 상태: {bot_status.get('bot_status', {}).get('status', 'Unknown')}")
            status_text.append(f"• 일일 거래: {risk_metrics.get('daily_trades', 0)}회")
            status_text.append(f"• 일일 손익: ${risk_metrics.get('daily_pnl', 0):+.2f}")
            status_text.append(f"• 성공률: {risk_metrics.get('success_rate_24h', 0):.1f}%")
            status_text.append(f"• 현재 포지션: {risk_metrics.get('current_positions', 0)}개")
            status_text.append(f"• 연속 손실: {risk_metrics.get('consecutive_losses', 0)}회")
            status_text.append(f"• 리스크 레벨: {risk_metrics.get('risk_level', 'UNKNOWN')}")

            status_layout.addWidget(status_text)
        else:
            no_bot_label = QLabel("현재 실행 중인 봇이 없습니다.")
            no_bot_label.setAlignment(Qt.AlignCenter)
            status_layout.addWidget(no_bot_label)

        tab_widget.addTab(status_tab, "📊 봇 상태")

        # 거래 내역 탭
        trades_tab = QWidget()
        trades_layout = QVBoxLayout(trades_tab)

        if self.active_bot:
            trade_history = self.active_bot.get_trade_history(50)
            
            trades_table = QTableWidget()
            trades_table.setColumnCount(6)
            trades_table.setHorizontalHeaderLabels(["시간", "심볼", "액션", "금액", "가격", "손익"])
            trades_table.setRowCount(len(trade_history))

            for i, trade in enumerate(trade_history):
                trades_table.setItem(i, 0, QTableWidgetItem(trade['timestamp'][:19]))
                trades_table.setItem(i, 1, QTableWidgetItem(trade['symbol']))
                trades_table.setItem(i, 2, QTableWidgetItem(trade['action']))
                trades_table.setItem(i, 3, QTableWidgetItem(f"${trade['amount']:.2f}"))
                trades_table.setItem(i, 4, QTableWidgetItem(f"${trade['price']:.4f}"))
                
                pnl_item = QTableWidgetItem(f"${trade['pnl']:+.2f}")
                if trade['pnl'] >= 0:
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
        leverage_combo.addItems(["5x", "10x", "20x", "50x", "100x"])
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
                
                symbol = self.main_symbol_combo.currentText()
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

    def start_trading_bot(self):
        """트레이딩봇 시작"""
        try:
            symbol = self.bot_symbol_combo.currentText()
            amount_text = self.bot_amount_input.text().strip()
            
            if not amount_text:
                QMessageBox.warning(self, "입력 오류", "거래 금액을 입력해주세요.")
                return
            
            amount = float(amount_text)
            if amount < 50:
                QMessageBox.warning(self, "입력 오류", "거래 금액은 최소 $50 이상이어야 합니다.")
                return
            
            # 기존 봇이 실행 중이면 정지
            if self.active_bot:
                self.stop_trading_bot()
            
            # 봇 설정 생성
            bot_config = BotConfig(
                bot_name=f"MA Cross Bot - {symbol}",
                strategy_name="ma_cross",
                symbol=symbol,
                base_amount=amount,
                trading_mode="spot",
                is_active=True
            )
            
            # 봇 생성 및 시작
            self.active_bot = TradingBot(bot_config, self.trading_engine)
            
            # 봇 시그널 연결
            self.active_bot.signal_generated.connect(self.on_bot_signal)
            self.active_bot.trade_executed.connect(self.on_bot_trade)
            self.active_bot.status_changed.connect(self.on_bot_status_changed)
            self.active_bot.error_occurred.connect(self.on_bot_error)
            
            # 봇 시작
            success, message = self.active_bot.start()
            
            if success:
                self.start_bot_btn.setEnabled(False)
                self.stop_bot_btn.setEnabled(True)
                self.bot_status_label.setText("실행 중")
                self.bot_status_label.setStyleSheet("font-size: 10px; color: #00C851;")
                
                QMessageBox.information(self, "🤖 봇 시작", 
                    f"트레이딩봇이 시작되었습니다!\n\n"
                    f"📊 심볼: {symbol}\n"
                    f"💰 거래 금액: ${amount:.2f}\n"
                    f"📈 전략: 이동평균 교차\n"
                    f"⚡ 모드: 현물 거래\n\n"
                    f"봇이 자동으로 거래를 시작합니다.")
                
                self.logger.info(f"🤖 트레이딩봇 시작: {symbol} ${amount}")
            else:
                QMessageBox.warning(self, "❌ 봇 시작 실패", message)
                self.active_bot = None
                
        except ValueError:
            QMessageBox.warning(self, "입력 오류", "올바른 숫자를 입력해주세요.")
        except Exception as e:
            QMessageBox.critical(self, "오류", f"봇 시작 중 오류:\n{e}")
            self.logger.error(f"봇 시작 오류: {e}")

    def stop_trading_bot(self):
        """트레이딩봇 정지"""
        try:
            if not self.active_bot:
                return
            
            success, message = self.active_bot.stop()
            
            if success:
                self.start_bot_btn.setEnabled(True)
                self.stop_bot_btn.setEnabled(False)
                self.bot_status_label.setText("정지됨")
                self.bot_status_label.setStyleSheet("font-size: 12px; color: #ff4444;")  # 폰트 크기 증가
                
                # 최종 성과 표시
                bot_status = self.active_bot.get_bot_status()
                risk_metrics = bot_status.get('risk_metrics', {})
                
                QMessageBox.information(self, "🤖 봇 정지", 
                    f"트레이딩봇이 정지되었습니다.\n\n"
                    f"📊 최종 성과:\n"
                    f"• 총 거래: {risk_metrics.get('daily_trades', 0)}회\n"
                    f"• 일일 손익: ${risk_metrics.get('daily_pnl', 0):+.2f}\n"
                    f"• 성공률: {risk_metrics.get('success_rate_24h', 0):.1f}%\n"
                    f"• 현재 포지션: {risk_metrics.get('current_positions', 0)}개")
                
                self.active_bot = None
                self.logger.info("🤖 트레이딩봇 정지됨")
            else:
                QMessageBox.warning(self, "❌ 봇 정지 실패", message)
                
        except Exception as e:
            QMessageBox.critical(self, "오류", f"봇 정지 중 오류:\n{e}")
            self.logger.error(f"봇 정지 오류: {e}")

    def on_bot_signal(self, signal_data):
        """봇 신호 수신"""
        action = signal_data.get('action', 'HOLD')
        price = signal_data.get('price', 0)
        reason = signal_data.get('reason', '')
        
        self.logger.info(f"🔔 봇 신호: {action} @${price:.4f} - {reason}")
        
        # 상태바에 표시
        if action != 'HOLD':
            self.statusBar().showMessage(f"🤖 봇 신호: {action} @${price:.4f}", 3000)

    def on_bot_trade(self, trade_data):
        """봇 거래 실행 알림"""
        symbol = trade_data.get('symbol', '')
        action = trade_data.get('action', '')
        amount = trade_data.get('amount', 0)
        price = trade_data.get('price', 0)
        success = trade_data.get('success', False)
        
        if success:
            self.logger.info(f"✅ 봇 거래 성공: {action} {symbol} ${amount:.2f} @${price:.4f}")
            
            # 상태바에 표시
            self.statusBar().showMessage(f"🤖 봇 거래: {action} {symbol} ${amount:.2f}", 5000)
            
            # 포트폴리오 업데이트
            self.update_portfolio_display()
            
            # 봇 통계 업데이트
            self.update_bot_status_display()
        else:
            self.logger.warning(f"❌ 봇 거래 실패: {action} {symbol}")

    def on_bot_status_changed(self, status):
        """봇 상태 변경"""
        status_map = {
            "running": ("실행 중", "#00C851"),
            "stopped": ("정지됨", "#ff4444"),
            "paused": ("일시정지", "#ff9800"),
            "error": ("오류", "#f44336")
        }
        
        text, color = status_map.get(status, ("알 수 없음", "#f0f0f0"))
        self.bot_status_label.setText(text)
        self.bot_status_label.setStyleSheet(f"font-size: 10px; color: {color};")

    def on_bot_error(self, error_msg):
        """봇 오류 처리"""
        self.logger.error(f"🤖 봇 오류: {error_msg}")
        QMessageBox.warning(self, "🤖 봇 오류", f"트레이딩봇에서 오류가 발생했습니다:\n{error_msg}")

    def update_bot_status_display(self):
        """봇 상태 디스플레이 업데이트"""
        if not self.active_bot:
            self.bot_trades_label.setText("거래: 0회")
            self.bot_pnl_label.setText("손익: $0.00")
            return
        
        try:
            bot_status = self.active_bot.get_bot_status()
            risk_metrics = bot_status.get('risk_metrics', {})
            
            trades = risk_metrics.get('daily_trades', 0)
            pnl = risk_metrics.get('daily_pnl', 0)
            
            self.bot_trades_label.setText(f"거래: {trades}회")
            
            pnl_text = f"손익: ${pnl:+.2f}"
            if pnl >= 0:
                self.bot_pnl_label.setStyleSheet("font-size: 10px; color: #00C851;")
            else:
                self.bot_pnl_label.setStyleSheet("font-size: 10px; color: #ff4444;")
            self.bot_pnl_label.setText(pnl_text)
            
        except Exception as e:
            self.logger.error(f"봇 상태 업데이트 오류: {e}")

    def show_bot_settings(self):
        """봇 설정 다이얼로그"""
        dialog = QDialog(self)
        dialog.setWindowTitle("🤖 트레이딩봇 설정")
        dialog.setGeometry(300, 300, 500, 600)
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
        dialog.setGeometry(200, 200, 800, 600)
        dialog.setStyleSheet(self.styleSheet())

        layout = QVBoxLayout(dialog)

        # 탭 위젯
        tab_widget = QTabWidget()

        # 봇 상태 탭
        status_tab = QWidget()
        status_layout = QVBoxLayout(status_tab)

        if self.active_bot:
            bot_status = self.active_bot.get_bot_status()
            risk_metrics = bot_status.get('risk_metrics', {})

            status_text = QTextEdit()
            status_text.setReadOnly(True)
            status_text.append("🤖 봇 현재 상태:")
            status_text.append(f"• 상태: {bot_status.get('bot_status', {}).get('status', 'Unknown')}")
            status_text.append(f"• 일일 거래: {risk_metrics.get('daily_trades', 0)}회")
            status_text.append(f"• 일일 손익: ${risk_metrics.get('daily_pnl', 0):+.2f}")
            status_text.append(f"• 성공률: {risk_metrics.get('success_rate_24h', 0):.1f}%")
            status_text.append(f"• 현재 포지션: {risk_metrics.get('current_positions', 0)}개")
            status_text.append(f"• 연속 손실: {risk_metrics.get('consecutive_losses', 0)}회")
            status_text.append(f"• 리스크 레벨: {risk_metrics.get('risk_level', 'UNKNOWN')}")

            status_layout.addWidget(status_text)
        else:
            no_bot_label = QLabel("현재 실행 중인 봇이 없습니다.")
            no_bot_label.setAlignment(Qt.AlignCenter)
            status_layout.addWidget(no_bot_label)

        tab_widget.addTab(status_tab, "📊 봇 상태")

        # 거래 내역 탭
        trades_tab = QWidget()
        trades_layout = QVBoxLayout(trades_tab)

        if self.active_bot:
            trade_history = self.active_bot.get_trade_history(50)
            
            trades_table = QTableWidget()
            trades_table.setColumnCount(6)
            trades_table.setHorizontalHeaderLabels(["시간", "심볼", "액션", "금액", "가격", "손익"])
            trades_table.setRowCount(len(trade_history))

            for i, trade in enumerate(trade_history):
                trades_table.setItem(i, 0, QTableWidgetItem(trade['timestamp'][:19]))
                trades_table.setItem(i, 1, QTableWidgetItem(trade['symbol']))
                trades_table.setItem(i, 2, QTableWidgetItem(trade['action']))
                trades_table.setItem(i, 3, QTableWidgetItem(f"${trade['amount']:.2f}"))
                trades_table.setItem(i, 4, QTableWidgetItem(f"${trade['price']:.4f}"))
                
                pnl_item = QTableWidgetItem(f"${trade['pnl']:+.2f}")
                if trade['pnl'] >= 0:
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

    def start_trading_bot(self):
        """트레이딩봇 시작"""
        try:
            symbol = self.bot_symbol_combo.currentText()
            amount_text = self.bot_amount_input.text().strip()
            
            if not amount_text:
                QMessageBox.warning(self, "입력 오류", "거래 금액을 입력해주세요.")
                return
            
            amount = float(amount_text)
            if amount < 50:
                QMessageBox.warning(self, "입력 오류", "거래 금액은 최소 $50 이상이어야 합니다.")
                return
            
            # 기존 봇이 실행 중이면 정지
            if self.active_bot:
                self.stop_trading_bot()
            
            # 봇 설정 생성
            bot_config = BotConfig(
                bot_name=f"MA Cross Bot - {symbol}",
                strategy_name="ma_cross",
                symbol=symbol,
                base_amount=amount,
                trading_mode="spot",
                is_active=True
            )
            
            # 봇 생성 및 시작
            self.active_bot = TradingBot(bot_config, self.trading_engine)
            
            # 봇 시그널 연결
            self.active_bot.signal_generated.connect(self.on_bot_signal)
            self.active_bot.trade_executed.connect(self.on_bot_trade)
            self.active_bot.status_changed.connect(self.on_bot_status_changed)
            self.active_bot.error_occurred.connect(self.on_bot_error)
            
            # 봇 시작
            success, message = self.active_bot.start()
            
            if success:
                self.start_bot_btn.setEnabled(False)
                self.stop_bot_btn.setEnabled(True)
                self.bot_status_label.setText("실행 중")
                self.bot_status_label.setStyleSheet("font-size: 10px; color: #00C851;")
                
                QMessageBox.information(self, "🤖 봇 시작", 
                    f"트레이딩봇이 시작되었습니다!\n\n"
                    f"📊 심볼: {symbol}\n"
                    f"💰 거래 금액: ${amount:.2f}\n"
                    f"📈 전략: 이동평균 교차\n"
                    f"⚡ 모드: 현물 거래\n\n"
                    f"봇이 자동으로 거래를 시작합니다.")
                
                self.logger.info(f"🤖 트레이딩봇 시작: {symbol} ${amount}")
            else:
                QMessageBox.warning(self, "❌ 봇 시작 실패", message)
                self.active_bot = None
                
        except ValueError:
            QMessageBox.warning(self, "입력 오류", "올바른 숫자를 입력해주세요.")
        except Exception as e:
            QMessageBox.critical(self, "오류", f"봇 시작 중 오류:\n{e}")
            self.logger.error(f"봇 시작 오류: {e}")

    def stop_trading_bot(self):
        """트레이딩봇 정지"""
        try:
            if not self.active_bot:
                return
            
            success, message = self.active_bot.stop()
            
            if success:
                self.start_bot_btn.setEnabled(True)
                self.stop_bot_btn.setEnabled(False)
                self.bot_status_label.setText("정지됨")
                self.bot_status_label.setStyleSheet("font-size: 12px; color: #ff4444;")  # 폰트 크기 증가
                
                # 최종 성과 표시
                bot_status = self.active_bot.get_bot_status()
                risk_metrics = bot_status.get('risk_metrics', {})
                
                QMessageBox.information(self, "🤖 봇 정지", 
                    f"트레이딩봇이 정지되었습니다.\n\n"
                    f"📊 최종 성과:\n"
                    f"• 총 거래: {risk_metrics.get('daily_trades', 0)}회\n"
                    f"• 일일 손익: ${risk_metrics.get('daily_pnl', 0):+.2f}\n"
                    f"• 성공률: {risk_metrics.get('success_rate_24h', 0):.1f}%\n"
                    f"• 현재 포지션: {risk_metrics.get('current_positions', 0)}개")
                
                self.active_bot = None
                self.logger.info("🤖 트레이딩봇 정지됨")
            else:
                QMessageBox.warning(self, "❌ 봇 정지 실패", message)
                
        except Exception as e:
            QMessageBox.critical(self, "오류", f"봇 정지 중 오류:\n{e}")
            self.logger.error(f"봇 정지 오류: {e}")

    def on_bot_signal(self, signal_data):
        """봇 신호 수신"""
        action = signal_data.get('action', 'HOLD')
        price = signal_data.get('price', 0)
        reason = signal_data.get('reason', '')
        
        self.logger.info(f"🔔 봇 신호: {action} @${price:.4f} - {reason}")
        
        # 상태바에 표시
        if action != 'HOLD':
            self.statusBar().showMessage(f"🤖 봇 신호: {action} @${price:.4f}", 3000)

    def on_bot_trade(self, trade_data):
        """봇 거래 실행 알림"""
        symbol = trade_data.get('symbol', '')
        action = trade_data.get('action', '')
        amount = trade_data.get('amount', 0)
        price = trade_data.get('price', 0)
        success = trade_data.get('success', False)
        
        if success:
            self.logger.info(f"✅ 봇 거래 성공: {action} {symbol} ${amount:.2f} @${price:.4f}")
            
            # 상태바에 표시
            self.statusBar().showMessage(f"🤖 봇 거래: {action} {symbol} ${amount:.2f}", 5000)
            
            # 포트폴리오 업데이트
            self.update_portfolio_display()
            
            # 봇 통계 업데이트
            self.update_bot_status_display()
        else:
            self.logger.warning(f"❌ 봇 거래 실패: {action} {symbol}")

    def on_bot_status_changed(self, status):
        """봇 상태 변경"""
        status_map = {
            "running": ("실행 중", "#00C851"),
            "stopped": ("정지됨", "#ff4444"),
            "paused": ("일시정지", "#ff9800"),
            "error": ("오류", "#f44336")
        }
        
        text, color = status_map.get(status, ("알 수 없음", "#f0f0f0"))
        self.bot_status_label.setText(text)
        self.bot_status_label.setStyleSheet(f"font-size: 10px; color: {color};")

    def on_bot_error(self, error_msg):
        """봇 오류 처리"""
        self.logger.error(f"🤖 봇 오류: {error_msg}")
        QMessageBox.warning(self, "🤖 봇 오류", f"트레이딩봇에서 오류가 발생했습니다:\n{error_msg}")

    def update_bot_status_display(self):
        """봇 상태 디스플레이 업데이트"""
        if not self.active_bot:
            self.bot_trades_label.setText("거래: 0회")
            self.bot_pnl_label.setText("손익: $0.00")
            return
        
        try:
            bot_status = self.active_bot.get_bot_status()
            risk_metrics = bot_status.get('risk_metrics', {})
            
            trades = risk_metrics.get('daily_trades', 0)
            pnl = risk_metrics.get('daily_pnl', 0)
            
            self.bot_trades_label.setText(f"거래: {trades}회")
            
            pnl_text = f"손익: ${pnl:+.2f}"
            if pnl >= 0:
                self.bot_pnl_label.setStyleSheet("font-size: 10px; color: #00C851;")
            else:
                self.bot_pnl_label.setStyleSheet("font-size: 10px; color: #ff4444;")
            self.bot_pnl_label.setText(pnl_text)
            
        except Exception as e:
            self.logger.error(f"봇 상태 업데이트 오류: {e}")

    def show_bot_settings(self):
        """봇 설정 다이얼로그"""
        dialog = QDialog(self)
        dialog.setWindowTitle("🤖 트레이딩봇 설정")
        dialog.setGeometry(300, 300, 500, 600)
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
        dialog.setGeometry(200, 200, 800, 600)
        dialog.setStyleSheet(self.styleSheet())

        layout = QVBoxLayout(dialog)

        # 탭 위젯
        tab_widget = QTabWidget()

        # 봇 상태 탭
        status_tab = QWidget()
        status_layout = QVBoxLayout(status_tab)

        if self.active_bot:
            bot_status = self.active_bot.get_bot_status()
            risk_metrics = bot_status.get('risk_metrics', {})

            status_text = QTextEdit()
            status_text.setReadOnly(True)
            status_text.append("🤖 봇 현재 상태:")
            status_text.append(f"• 상태: {bot_status.get('bot_status', {}).get('status', 'Unknown')}")
            status_text.append(f"• 일일 거래: {risk_metrics.get('daily_trades', 0)}회")
            status_text.append(f"• 일일 손익: ${risk_metrics.get('daily_pnl', 0):+.2f}")
            status_text.append(f"• 성공률: {risk_metrics.get('success_rate_24h', 0):.1f}%")
            status_text.append(f"• 현재 포지션: {risk_metrics.get('current_positions', 0)}개")
            status_text.append(f"• 연속 손실: {risk_metrics.get('consecutive_losses', 0)}회")
            status_text.append(f"• 리스크 레벨: {risk_metrics.get('risk_level', 'UNKNOWN')}")

            status_layout.addWidget(status_text)
        else:
            no_bot_label = QLabel("현재 실행 중인 봇이 없습니다.")
            no_bot_label.setAlignment(Qt.AlignCenter)
            status_layout.addWidget(no_bot_label)

        tab_widget.addTab(status_tab, "📊 봇 상태")

        # 거래 내역 탭
        trades_tab = QWidget()
        trades_layout = QVBoxLayout(trades_tab)

        if self.active_bot:
            trade_history = self.active_bot.get_trade_history(50)
            
            trades_table = QTableWidget()
            trades_table.setColumnCount(6)
            trades_table.setHorizontalHeaderLabels(["시간", "심볼", "액션", "금액", "가격", "손익"])
            trades_table.setRowCount(len(trade_history))

            for i, trade in enumerate(trade_history):
                trades_table.setItem(i, 0, QTableWidgetItem(trade['timestamp'][:19]))
                trades_table.setItem(i, 1, QTableWidgetItem(trade['symbol']))
                trades_table.setItem(i, 2, QTableWidgetItem(trade['action']))
                trades_table.setItem(i, 3, QTableWidgetItem(f"${trade['amount']:.2f}"))
                trades_table.setItem(i, 4, QTableWidgetItem(f"${trade['price']:.4f}"))
                
                pnl_item = QTableWidgetItem(f"${trade['pnl']:+.2f}")
                if trade['pnl'] >= 0:
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

    def start_trading_bot(self):
        """트레이딩봇 시작"""
        try:
            symbol = self.bot_symbol_combo.currentText()
            amount_text = self.bot_amount_input.text().strip()
            
            if not amount_text:
                QMessageBox.warning(self, "입력 오류", "거래 금액을 입력해주세요.")
                return
            
            amount = float(amount_text)
            if amount < 50:
                QMessageBox.warning(self, "입력 오류", "거래 금액은 최소 $50 이상이어야 합니다.")
                return
            
            # 기존 봇이 실행 중이면 정지
            if self.active_bot:
                self.stop_trading_bot()
            
            # 봇 설정 생성
            bot_config = BotConfig(
                bot_name=f"MA Cross Bot - {symbol}",
                strategy_name="ma_cross",
                symbol=symbol,
                base_amount=amount,
                trading_mode="spot",
                is_active=True
            )
            
            # 봇 생성 및 시작
            self.active_bot = TradingBot(bot_config, self.trading_engine)
            
            # 봇 시그널 연결
            self.active_bot.signal_generated.connect(self.on_bot_signal)
            self.active_bot.trade_executed.connect(self.on_bot_trade)
            self.active_bot.status_changed.connect(self.on_bot_status_changed)
            self.active_bot.error_occurred.connect(self.on_bot_error)
            
            # 봇 시작
            success, message = self.active_bot.start()
            
            if success:
                self.start_bot_btn.setEnabled(False)
                self.stop_bot_btn.setEnabled(True)
                self.bot_status_label.setText("실행 중")
                self.bot_status_label.setStyleSheet("font-size: 10px; color: #00C851;")
                
                QMessageBox.information(self, "🤖 봇 시작", 
                    f"트레이딩봇이 시작되었습니다!\n\n"
                    f"📊 심볼: {symbol}\n"
                    f"💰 거래 금액: ${amount:.2f}\n"
                    f"📈 전략: 이동평균 교차\n"
                    f"⚡ 모드: 현물 거래\n\n"
                    f"봇이 자동으로 거래를 시작합니다.")
                
                self.logger.info(f"🤖 트레이딩봇 시작: {symbol} ${amount}")
            else:
                QMessageBox.warning(self, "❌ 봇 시작 실패", message)
                self.active_bot = None
                
        except ValueError:
            QMessageBox.warning(self, "입력 오류", "올바른 숫자를 입력해주세요.")
        except Exception as e:
            QMessageBox.critical(self, "오류", f"봇 시작 중 오류:\n{e}")
            self.logger.error(f"봇 시작 오류: {e}")

    def stop_trading_bot(self):
        """트레이딩봇 정지"""
        try:
            if not self.active_bot:
                return
            
            success, message = self.active_bot.stop()
            
            if success:
                self.start_bot_btn.setEnabled(True)
                self.stop_bot_btn.setEnabled(False)
                self.bot_status_label.setText("정지됨")
                self.bot_status_label.setStyleSheet("font-size: 12px; color: #ff4444;")  # 폰트 크기 증가
                
                # 최종 성과 표시
                bot_status = self.active_bot.get_bot_status()
                risk_metrics = bot_status.get('risk_metrics', {})
                
                QMessageBox.information(self, "🤖 봇 정지", 
                    f"트레이딩봇이 정지되었습니다.\n\n"
                    f"📊 최종 성과:\n"
                    f"• 총 거래: {risk_metrics.get('daily_trades', 0)}회\n"
                    f"• 일일 손익: ${risk_metrics.get('daily_pnl', 0):+.2f}\n"
                    f"• 성공률: {risk_metrics.get('success_rate_24h', 0):.1f}%\n"
                    f"• 현재 포지션: {risk_metrics.get('current_positions', 0)}개")
                
                self.active_bot = None
                self.logger.info("🤖 트레이딩봇 정지됨")
            else:
                QMessageBox.warning(self, "❌ 봇 정지 실패", message)
                
        except Exception as e:
            QMessageBox.critical(self, "오류", f"봇 정지 중 오류:\n{e}")
            self.logger.error(f"봇 정지 오류: {e}")

    def on_bot_signal(self, signal_data):
        """봇 신호 수신"""
        action = signal_data.get('action', 'HOLD')
        price = signal_data.get('price', 0)
        reason = signal_data.get('reason', '')
        
        self.logger.info(f"🔔 봇 신호: {action} @${price:.4f} - {reason}")
        
        # 상태바에 표시
        if action != 'HOLD':
            self.statusBar().showMessage(f"🤖 봇 신호: {action} @${price:.4f}", 3000)

    def on_bot_trade(self, trade_data):
        """봇 거래 실행 알림"""
        symbol = trade_data.get('symbol', '')
        action = trade_data.get('action', '')
        amount = trade_data.get('amount', 0)
        price = trade_data.get('price', 0)
        success = trade_data.get('success', False)
        
        if success:
            self.logger.info(f"✅ 봇 거래 성공: {action} {symbol} ${amount:.2f} @${price:.4f}")
            
            # 상태바에 표시
            self.statusBar().showMessage(f"🤖 봇 거래: {action} {symbol} ${amount:.2f}", 5000)
            
            # 포트폴리오 업데이트
            self.update_portfolio_display()
            
            # 봇 통계 업데이트
            self.update_bot_status_display()
        else:
            self.logger.warning(f"❌ 봇 거래 실패: {action} {symbol}")

    def on_bot_status_changed(self, status):
        """봇 상태 변경"""
        status_map = {
            "running": ("실행 중", "#00C851"),
            "stopped": ("정지됨", "#ff4444"),
            "paused": ("일시정지", "#ff9800"),
            "error": ("오류", "#f44336")
        }
        
        text, color = status_map.get(status, ("알 수 없음", "#f0f0f0"))
        self.bot_status_label.setText(text)
        self.bot_status_label.setStyleSheet(f"font-size: 10px; color: {color};")

    def on_bot_error(self, error_msg):
        """봇 오류 처리"""
        self.logger.error(f"🤖 봇 오류: {error_msg}")
        QMessageBox.warning(self, "🤖 봇 오류", f"트레이딩봇에서 오류가 발생했습니다:\n{error_msg}")

    def update_bot_status_display(self):
        """봇 상태 디스플레이 업데이트"""
        if not self.active_bot:
            self.bot_trades_label.setText("거래: 0회")
            self.bot_pnl_label.setText("손익: $0.00")
            return
        
        try:
            bot_status = self.active_bot.get_bot_status()
            risk_metrics = bot_status.get('risk_metrics', {})
            
            trades = risk_metrics.get('daily_trades', 0)
            pnl = risk_metrics.get('daily_pnl', 0)
            
            self.bot_trades_label.setText(f"거래: {trades}회")
            
            pnl_text = f"손익: ${pnl:+.2f}"
            if pnl >= 0:
                self.bot_pnl_label.setStyleSheet("font-size: 10px; color: #00C851;")
            else:
                self.bot_pnl_label.setStyleSheet("font-size: 10px; color: #ff4444;")
            self.bot_pnl_label.setText(pnl_text)
            
        except Exception as e:
            self.logger.error(f"봇 상태 업데이트 오류: {e}")

    def show_bot_settings(self):
        """봇 설정 다이얼로그"""
        dialog = QDialog(self)
        dialog.setWindowTitle("🤖 트레이딩봇 설정")
        dialog.setGeometry(300, 300, 500, 600)
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
        dialog.setGeometry(200, 200, 800, 600)
        dialog.setStyleSheet(self.styleSheet())

        layout = QVBoxLayout(dialog)

        # 탭 위젯
        tab_widget = QTabWidget()

        # 봇 상태 탭
        status_tab = QWidget()
        status_layout = QVBoxLayout(status_tab)

        if self.active_bot:
            bot_status = self.active_bot.get_bot_status()
            risk_metrics = bot_status.get('risk_metrics', {})

            status_text = QTextEdit()
            status_text.setReadOnly(True)
            status_text.append("🤖 봇 현재 상태:")
            status_text.append(f"• 상태: {bot_status.get('bot_status', {}).get('status', 'Unknown')}")
            status_text.append(f"• 일일 거래: {risk_metrics.get('daily_trades', 0)}회")
            status_text.append(f"• 일일 손익: ${risk_metrics.get('daily_pnl', 0):+.2f}")
            status_text.append(f"• 성공률: {risk_metrics.get('success_rate_24h', 0):.1f}%")
            status_text.append(f"• 현재 포지션: {risk_metrics.get('current_positions', 0)}개")
            status_text.append(f"• 연속 손실: {risk_metrics.get('consecutive_losses', 0)}회")
            status_text.append(f"• 리스크 레벨: {risk_metrics.get('risk_level', 'UNKNOWN')}")

            status_layout.addWidget(status_text)
        else:
            no_bot_label = QLabel("현재 실행 중인 봇이 없습니다.")
            no_bot_label.setAlignment(Qt.AlignCenter)
            status_layout.addWidget(no_bot_label)

        tab_widget.addTab(status_tab, "📊 봇 상태")

        # 거래 내역 탭
        trades_tab = QWidget()
        trades_layout = QVBoxLayout(trades_tab)

        if self.active_bot:
            trade_history = self.active_bot.get_trade_history(50)
            
            trades_table = QTableWidget()
            trades_table.setColumnCount(6)
            trades_table.setHorizontalHeaderLabels(["시간", "심볼", "액션", "금액", "가격", "손익"])
            trades_table.setRowCount(len(trade_history))

            for i, trade in enumerate(trade_history):
                trades_table.setItem(i, 0, QTableWidgetItem(trade['timestamp'][:19]))
                trades_table.setItem(i, 1, QTableWidgetItem(trade['symbol']))
                trades_table.setItem(i, 2, QTableWidgetItem(trade['action']))
                trades_table.setItem(i, 3, QTableWidgetItem(f"${trade['amount']:.2f}"))
                trades_table.setItem(i, 4, QTableWidgetItem(f"${trade['price']:.4f}"))
                
                pnl_item = QTableWidgetItem(f"${trade['pnl']:+.2f}")
                if trade['pnl'] >= 0:
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
            if self.active_bot:
                self.logger.info("프로그램 종료: 트레이딩봇 정지 중...")
                self.active_bot.stop()

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