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
from binance_futures_client import BinanceFuturesClient  # 실제 API 사용
from order_book_widget import MatplotlibOrderBook  # 호가창 위젯 추가
from cross_position_manager import CrossPositionManager  # Cross 포지션 관리자 🚀

class PriceWebSocketThread(QThread):
    """포트폴리오용 실시간 가격 WebSocket"""
    price_updated = pyqtSignal(dict)

    def __init__(self, trading_engine):
        super().__init__()
        self.trading_engine = trading_engine
        self.running = False
        self.ws_connections = {}
        
    def run(self):
        self.running = True
        # 지원되는 모든 심볼의 실시간 가격 구독
        for symbol in Config.SUPPORTED_PAIRS:
            self.subscribe_ticker(symbol)
        
        # 이벤트 루프 유지
        while self.running:
            self.msleep(1000)

    def subscribe_ticker(self, symbol):
        """실시간 가격 WebSocket 구독 (포트폴리오용)"""
        import websocket
        import json
        import threading
        
        stream_name = f"{symbol.lower()}@ticker"
        ws_url = f"wss://stream.binance.com:9443/ws/{stream_name}"
        
        def on_message(ws, message):
            try:
                data = json.loads(message)
                price = float(data['c'])  # 현재가
                
                # 현재 가격 캐시 업데이트
                if not hasattr(self.trading_engine, 'current_prices'):
                    self.trading_engine.current_prices = {}
                self.trading_engine.current_prices[symbol] = price
                
                # 포트폴리오 업데이트 신호 발송
                self.price_updated.emit(self.trading_engine.current_prices)
                
                print(f"💰 Portfolio Price: {symbol} ${price:.4f} (WebSocket)")
                
            except Exception as e:
                print(f"가격 WebSocket 오류: {e}")
        
        def on_error(ws, error):
            print(f"가격 WebSocket 에러 ({symbol}): {error}")
        
        def on_close(ws, close_status_code, close_msg):
            print(f"가격 WebSocket 종료 ({symbol})")
            if symbol in self.ws_connections:
                del self.ws_connections[symbol]
        
        def on_open(ws):
            print(f"💰 포트폴리오 가격 WebSocket 연결: {symbol}")
        
        ws = websocket.WebSocketApp(
            ws_url,
            on_message=on_message,
            on_error=on_error,
            on_close=on_close,
            on_open=on_open
        )
        
        def run_ws():
            ws.run_forever()
        
        thread = threading.Thread(target=run_ws)
        thread.daemon = True
        thread.start()
        
        self.ws_connections[symbol] = ws

    def stop(self):
        self.running = False
        # 모든 WebSocket 연결 종료
        for ws in self.ws_connections.values():
            ws.close()
        self.ws_connections.clear()
        self.wait()

class TradingGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.trading_engine = TradingEngine()
        self.futures_client = BinanceFuturesClient()  # 실제 바이낸스 선물 API 사용!
        self.cross_manager = CrossPositionManager()  # Cross 포지션 관리자 🚀
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

        self.init_ui()
        self.init_price_thread()
        
        # 포지션 업데이트 타이머
        self.position_timer = QTimer()
        self.position_timer.timeout.connect(self.update_position_info)
        self.position_timer.start(3000)  # 3초마다 포지션 정보 업데이트

    def init_ui(self):
        """UI 초기화 - 바이낸스 스타일 (창 크기 최적화)"""
        self.setWindowTitle("🪙 Genius Coin Manager - 실시간 차트 모의투자")
        self.setGeometry(100, 100, 1400, 800)  # 창 크기 줄임

        # 중앙 위젯 설정
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        # 메인 레이아웃 (수직)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setSpacing(3)  # 간격 줄임
        main_layout.setContentsMargins(3, 3, 3, 3)  # 여백 줄임

        # 상단 헤더 (코인 정보)
        header = self.create_header()
        main_layout.addWidget(header)

        # 중앙 영역 (차트 + 호가창 + 주문창) - 가로 분할 🚀
        center_widget = QWidget()
        center_layout = QHBoxLayout(center_widget)
        center_layout.setContentsMargins(3, 3, 3, 3)
        center_layout.setSpacing(5)
        
        # 차트 영역 (왼쪽, 60%) - 세로 분할로 변경
        chart_panel = QWidget()
        chart_layout = QVBoxLayout(chart_panel)
        chart_layout.setContentsMargins(0, 0, 0, 0)
        chart_layout.setSpacing(5)
        
        # 차트 위젯 (상단)
        self.chart_widget = CandlestickChart(self.trading_engine)
        self.chart_widget.figure.set_size_inches(10, 6)  # 높이 줄임
        self.chart_widget.canvas.setMinimumHeight(400)   # 높이 줄임
        chart_layout.addWidget(self.chart_widget, 3)     # 60% 할당
        
        # 포트폴리오 정보 탭 위젯 (하단)
        portfolio_tabs = self.create_portfolio_tabs()
        chart_layout.addWidget(portfolio_tabs, 2)        # 40% 할당
        
        center_layout.addWidget(chart_panel, 3)  # 60% 할당
        
        # 오른쪽 패널 (호가창 + 주문창) - 세로 분할
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(5)
        
        # 호가창 (위쪽, 70%)
        self.order_book_widget = MatplotlibOrderBook(self.trading_engine)
        right_layout.addWidget(self.order_book_widget, 7)
        
        # 주문창 (아래쪽, 30%)
        self.trading_panel = self.create_trading_panel()
        right_layout.addWidget(self.trading_panel, 3)
        
        center_layout.addWidget(right_panel, 2)  # 40% 할당
        
        main_layout.addWidget(center_widget, 1)

        # 하단 포트폴리오 요약만 (거래 패널은 오른쪽으로 이동)
        bottom_panel = self.create_portfolio_summary()
        main_layout.addWidget(bottom_panel)

        # 상태바
        self.statusBar().showMessage("연결 중...")

        # 메뉴바
        self.create_menu_bar()

        # 차트 자동 업데이트 스레드
        self.chart_update_thread = ChartUpdateThread(self.chart_widget)
        self.chart_update_thread.update_signal.connect(self.chart_widget.update_chart)
        self.chart_update_thread.start()

        # 호가창 클릭 시그널 연결 🚀
        if hasattr(self, 'order_book_widget'):
            self.order_book_widget.price_clicked.connect(self.on_price_clicked_from_orderbook)
        
        # 스타일 적용
        self.apply_binance_theme()

        # 초기 데이터 로드
        self.update_portfolio_display()
        
        # 초기 테이블 로드
        self.update_transactions_table()
        self.update_cross_display()  # Cross 포지션 초기 로드 🚀
        self.update_cross_transactions_only()  # Cross 거래 내역 초기 로드 🚀

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
                padding: 8px;
                color: #f0f0f0;
                font-size: 13px;
            }
            QLineEdit:focus {
                border: 1px solid #f0b90b;
            }
            QComboBox {
                background-color: #2b3139;
                border: 1px solid #474d57;
                border-radius: 4px;
                padding: 8px;
                color: #f0f0f0;
                font-size: 13px;
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
                padding: 10px 15px;
                font-weight: bold;
                color: #f0f0f0;
                font-size: 13px;
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
        header.setFixedHeight(60)  # 높이 줄임
        header.setStyleSheet("""
            QFrame {
                background-color: #1e2329;
                border: 1px solid #2b3139;
                border-radius: 6px;
                margin: 2px;
            }
        """)

        layout = QHBoxLayout(header)
        layout.setContentsMargins(15, 5, 15, 5)  # 여백 줄임

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

    def create_trading_panel(self):
        """오른쪽 패널용 세로형 주문창 생성 🚀"""
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
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        # 탭 위젯 생성
        tab_widget = QTabWidget()
        tab_widget.setStyleSheet("""
            QTabWidget::pane {
                border: 1px solid #2b3139;
                background-color: #1e2329;
            }
            QTabBar::tab {
                background-color: #2b3139;
                color: #f0f0f0;
                padding: 8px 20px;
                margin-right: 2px;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
            }
            QTabBar::tab:selected {
                background-color: #f0b90b;
                color: #000000;
                font-weight: bold;
            }
            QTabBar::tab:hover {
                background-color: #474d57;
            }
        """)

        # Spot 거래 탭
        spot_tab = self.create_vertical_spot_tab()
        tab_widget.addTab(spot_tab, "Spot")

        # Cross 거래 탭 (레버리지)
        cross_tab = self.create_vertical_cross_tab()
        tab_widget.addTab(cross_tab, "Cross")

        layout.addWidget(tab_widget)
        return panel

    def create_vertical_spot_tab(self):
        """세로형 Spot 거래 탭"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(8)

        # 가격 입력 (호가창에서 자동 입력) 🚀
        price_layout = QHBoxLayout()
        price_layout.addWidget(QLabel("가격:"))
        self.spot_price_input = QLineEdit()
        self.spot_price_input.setPlaceholderText("호가창에서 클릭")
        self.spot_price_input.setStyleSheet("""
            QLineEdit {
                background-color: #2b3139;
                border: 2px solid #f0b90b;
                color: #f0b90b;
                font-weight: bold;
            }
        """)
        price_layout.addWidget(self.spot_price_input)
        layout.addLayout(price_layout)

        # 수량 입력
        amount_layout = QHBoxLayout()
        amount_layout.addWidget(QLabel("수량:"))
        self.spot_amount_input = QLineEdit()
        self.spot_amount_input.setPlaceholderText("USD 금액")
        amount_layout.addWidget(self.spot_amount_input)
        layout.addLayout(amount_layout)

        # 매수/매도 버튼
        buttons_layout = QHBoxLayout()
        
        self.spot_buy_btn = QPushButton("🚀 매수")
        self.spot_buy_btn.setStyleSheet("""
            QPushButton {
                background-color: #0ecb81;
                color: white;
                font-size: 12px;
                font-weight: bold;
                padding: 12px;
                border: none;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #0bb86f;
            }
        """)
        self.spot_buy_btn.clicked.connect(self.execute_spot_buy_with_price)
        buttons_layout.addWidget(self.spot_buy_btn)
        
        self.spot_sell_btn = QPushButton("📉 매도")
        self.spot_sell_btn.setStyleSheet("""
            QPushButton {
                background-color: #f6465d;
                color: white;
                font-size: 12px;
                font-weight: bold;
                padding: 12px;
                border: none;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #f23645;
            }
        """)
        self.spot_sell_btn.clicked.connect(self.execute_spot_sell_with_price)
        buttons_layout.addWidget(self.spot_sell_btn)
        
        layout.addLayout(buttons_layout)
        
        layout.addStretch()
        return widget

    def create_vertical_cross_tab(self):
        """세로형 Cross 거래 탭 (레버리지)"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(8)

        # 레버리지 설정
        leverage_layout = QHBoxLayout()
        leverage_layout.addWidget(QLabel("레버리지:"))
        self.leverage_combo = QComboBox()
        leverage_options = ["2x", "3x", "5x", "10x", "20x", "50x", "100x", "125x"]
        self.leverage_combo.addItems(leverage_options)
        self.leverage_combo.setCurrentText("10x")
        leverage_layout.addWidget(self.leverage_combo)
        layout.addLayout(leverage_layout)

        # 가격 입력 (호가창에서 자동 입력) 🚀
        price_layout = QHBoxLayout()
        price_layout.addWidget(QLabel("가격:"))
        self.cross_price_input = QLineEdit()
        self.cross_price_input.setPlaceholderText("호가창에서 클릭")
        self.cross_price_input.setStyleSheet("""
            QLineEdit {
                background-color: #2b3139;
                border: 2px solid #f0b90b;
                color: #f0b90b;
                font-weight: bold;
            }
        """)
        price_layout.addWidget(self.cross_price_input)
        layout.addLayout(price_layout)

        # 수량 입력
        amount_layout = QHBoxLayout()
        amount_layout.addWidget(QLabel("수량:"))
        self.cross_amount_input = QLineEdit()
        self.cross_amount_input.setPlaceholderText("USDT")
        amount_layout.addWidget(self.cross_amount_input)
        layout.addLayout(amount_layout)

        # 롱/숏 버튼
        buttons_layout = QHBoxLayout()
        
        self.long_btn = QPushButton("📈 롱")
        self.long_btn.setStyleSheet("""
            QPushButton {
                background-color: #0ecb81;
                color: white;
                font-size: 12px;
                font-weight: bold;
                padding: 12px;
                border: none;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #0bb86f;
            }
        """)
        self.long_btn.clicked.connect(self.execute_long_with_price)
        buttons_layout.addWidget(self.long_btn)
        
        self.short_btn = QPushButton("📉 숏")
        self.short_btn.setStyleSheet("""
            QPushButton {
                background-color: #f6465d;
                color: white;
                font-size: 12px;
                font-weight: bold;
                padding: 12px;
                border: none;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #f23645;
            }
        """)
        self.short_btn.clicked.connect(self.execute_short_with_price)
        buttons_layout.addWidget(self.short_btn)
        
        layout.addLayout(buttons_layout)

        # 포지션 청산 버튼
        self.close_btn = QPushButton("⚡ 전량 청산")
        self.close_btn.setStyleSheet("""
            QPushButton {
                background-color: #f0b90b;
                color: #000000;
                font-size: 12px;
                font-weight: bold;
                padding: 10px;
                border: none;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #d9a441;
            }
        """)
        self.close_btn.clicked.connect(self.close_position)
        layout.addWidget(self.close_btn)
        
        # 모든 포지션 청산 버튼 추가 🚀
        self.close_all_btn = QPushButton("🔥 모든 포지션 청산")
        self.close_all_btn.setStyleSheet("""
            QPushButton {
                background-color: #f6465d;
                color: white;
                font-size: 12px;
                font-weight: bold;
                padding: 10px;
                border: none;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #f23645;
            }
        """)
        self.close_all_btn.clicked.connect(self.close_all_cross_positions)
        layout.addWidget(self.close_all_btn)
        
        # 현재 포지션 정보
        self.position_label = QLabel("포지션: 없음")
        self.position_label.setStyleSheet("font-size: 10px; color: #8a8a8a;")
        layout.addWidget(self.position_label)
        
        layout.addStretch()
        return widget

    def create_portfolio_summary(self):
        """하단 포트폴리오 요약"""
        panel = QFrame()
        panel.setFixedHeight(60)
        panel.setStyleSheet("""
            QFrame {
                background-color: #1e2329;
                border: 1px solid #2b3139;
                border-radius: 6px;
                margin: 2px;
            }
        """)

        layout = QHBoxLayout(panel)
        layout.setContentsMargins(15, 10, 15, 10)

        # 포트폴리오 요약 정보
        self.portfolio_summary_label = QLabel("총 자산: $10,000.00 | 현금: $10,000.00 | 손익: $0.00 (0.00%)")
        self.portfolio_summary_label.setStyleSheet("font-size: 12px; color: #f0f0f0;")
        layout.addWidget(self.portfolio_summary_label)

        layout.addStretch()

        # 빠른 리셋 버튼
        reset_btn = QPushButton("🔄 리셋")
        reset_btn.setStyleSheet("""
            QPushButton {
                background-color: #474d57;
                color: white;
                font-size: 11px;
                padding: 8px 15px;
                border: none;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #5a6169;
            }
        """)
        reset_btn.clicked.connect(self.reset_portfolio)
        layout.addWidget(reset_btn)

        return panel

    def create_portfolio_tabs(self):
        """차트 하단 포트폴리오 정보 탭 위젯 생성 - Spot/Cross 분리"""
        tab_widget = QTabWidget()
        tab_widget.setFixedHeight(300)
        tab_widget.setStyleSheet("""
            QTabWidget::pane {
                border: 1px solid #2b3139;
                background-color: #1e2329;
                border-radius: 4px;
            }
            QTabBar::tab {
                background-color: #2b3139;
                color: #f0f0f0;
                padding: 8px 16px;
                margin-right: 2px;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
                font-size: 12px;
            }
            QTabBar::tab:selected {
                background-color: #f0b90b;
                color: #000000;
                font-weight: bold;
            }
            QTabBar::tab:hover {
                background-color: #474d57;
            }
        """)

        # Spot 보유 코인 탭
        spot_holdings_tab = self.create_spot_holdings_tab()
        tab_widget.addTab(spot_holdings_tab, "💰 Spot 보유")

        # Cross 포지션 탭 🚀
        cross_positions_tab = self.create_cross_positions_tab()
        tab_widget.addTab(cross_positions_tab, "⚡ Cross 포지션")

        # Spot 거래 내역 탭
        spot_transactions_tab = self.create_spot_transactions_tab()
        tab_widget.addTab(spot_transactions_tab, "📋 Spot 거래")

        # Cross 거래 내역 탭 🚀
        cross_transactions_tab = self.create_cross_transactions_tab()
        tab_widget.addTab(cross_transactions_tab, "📋 Cross 내역")

        return tab_widget

    def create_spot_holdings_tab(self):
        """Spot 보유 코인 탭 생성 🚀"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(10, 10, 10, 10)

        # Spot 보유 코인 테이블
        self.holdings_table = QTableWidget()
        self.holdings_table.setColumnCount(7)
        self.holdings_table.setHorizontalHeaderLabels([
            "코인", "수량", "평균매수가", "현재가", "평가액", "수익률", "수익금"
        ])
        
        # 테이블 스타일링
        self.holdings_table.setStyleSheet("""
            QTableWidget {
                background-color: #1e2329;
                alternate-background-color: #2b3139;
                selection-background-color: #474d57;
                gridline-color: #2b3139;
                border: 1px solid #2b3139;
                border-radius: 4px;
                color: #f0f0f0;
            }
            QTableWidget::item {
                padding: 8px;
                border-bottom: 1px solid #2b3139;
            }
            QHeaderView::section {
                background-color: #2b3139;
                padding: 8px;
                border: none;
                border-right: 1px solid #1e2329;
                font-weight: bold;
                color: #f0f0f0;
                font-size: 11px;
            }
        """)
        
        # 테이블 설정
        self.holdings_table.horizontalHeader().setStretchLastSection(True)
        self.holdings_table.setAlternatingRowColors(True)
        self.holdings_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.holdings_table.verticalHeader().setVisible(False)
        
        # 클릭 이벤트 연결
        self.holdings_table.cellClicked.connect(self.on_holding_clicked)
        
        layout.addWidget(self.holdings_table)
        return widget

    def create_cross_positions_tab(self):
        """Cross 포지션 탭 생성 🚀"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(10, 10, 10, 10)

        # Cross 포지션 테이블
        self.cross_positions_table = QTableWidget()
        self.cross_positions_table.setColumnCount(8)
        self.cross_positions_table.setHorizontalHeaderLabels([
            "심볼", "방향", "수량", "진입가", "현재가", "레버리지", "미실현손익", "수익률"
        ])
        
        # 테이블 스타일링
        self.cross_positions_table.setStyleSheet("""
            QTableWidget {
                background-color: #1e2329;
                alternate-background-color: #2b3139;
                selection-background-color: #474d57;
                gridline-color: #2b3139;
                border: 1px solid #2b3139;
                border-radius: 4px;
                color: #f0f0f0;
            }
            QTableWidget::item {
                padding: 8px;
                border-bottom: 1px solid #2b3139;
            }
            QHeaderView::section {
                background-color: #2b3139;
                padding: 8px;
                border: none;
                border-right: 1px solid #1e2329;
                font-weight: bold;
                color: #f0f0f0;
                font-size: 11px;
            }
        """)
        
        # 테이블 설정
        self.cross_positions_table.horizontalHeader().setStretchLastSection(True)
        self.cross_positions_table.setAlternatingRowColors(True)
        self.cross_positions_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.cross_positions_table.verticalHeader().setVisible(False)
        
        # 더블클릭으로 청산 기능
        self.cross_positions_table.doubleClicked.connect(self.on_cross_position_double_clicked)
        
        layout.addWidget(self.cross_positions_table)
        return widget

    def create_spot_transactions_tab(self):
        """Spot 거래 내역 탭 생성 🚀"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(10, 10, 10, 10)

        # Spot 거래 내역 테이블
        self.transactions_table = QTableWidget()
        self.transactions_table.setColumnCount(8)
        self.transactions_table.setHorizontalHeaderLabels([
            "시간", "타입", "코인", "수량", "가격", "총액", "수수료", "상태"
        ])
        
        # 테이블 스타일링
        self.transactions_table.setStyleSheet("""
            QTableWidget {
                background-color: #1e2329;
                alternate-background-color: #2b3139;
                selection-background-color: #474d57;
                gridline-color: #2b3139;
                border: 1px solid #2b3139;
                border-radius: 4px;
                color: #f0f0f0;
            }
            QTableWidget::item {
                padding: 8px;
                border-bottom: 1px solid #2b3139;
            }
            QHeaderView::section {
                background-color: #2b3139;
                padding: 8px;
                border: none;
                border-right: 1px solid #1e2329;
                font-weight: bold;
                color: #f0f0f0;
                font-size: 11px;
            }
        """)
        
        # 테이블 설정
        self.transactions_table.horizontalHeader().setStretchLastSection(True)
        self.transactions_table.setAlternatingRowColors(True)
        self.transactions_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.transactions_table.verticalHeader().setVisible(False)
        
        layout.addWidget(self.transactions_table)
        return widget

    def create_cross_transactions_tab(self):
        """Cross 거래 내역 탭 생성 🚀"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(10, 10, 10, 10)

        # Cross 거래 내역 테이블
        self.cross_transactions_table = QTableWidget()
        self.cross_transactions_table.setColumnCount(8)
        self.cross_transactions_table.setHorizontalHeaderLabels([
            "시간", "타입", "심볼", "방향", "수량", "가격", "레버리지", "손익"
        ])
        
        # 테이블 스타일링
        self.cross_transactions_table.setStyleSheet("""
            QTableWidget {
                background-color: #1e2329;
                alternate-background-color: #2b3139;
                selection-background-color: #474d57;
                gridline-color: #2b3139;
                border: 1px solid #2b3139;
                border-radius: 4px;
                color: #f0f0f0;
            }
            QTableWidget::item {
                padding: 8px;
                border-bottom: 1px solid #2b3139;
            }
            QHeaderView::section {
                background-color: #2b3139;
                padding: 8px;
                border: none;
                border-right: 1px solid #1e2329;
                font-weight: bold;
                color: #f0f0f0;
                font-size: 11px;
            }
        """)
        
        # 테이블 설정
        self.cross_transactions_table.horizontalHeader().setStretchLastSection(True)
        self.cross_transactions_table.setAlternatingRowColors(True)
        self.cross_transactions_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.cross_transactions_table.verticalHeader().setVisible(False)
        
        layout.addWidget(self.cross_transactions_table)
        return widget

    def on_price_clicked_from_orderbook(self, price):
        """호가창에서 가격 클릭 시 호출 🚀"""
        try:
            price_str = f"{price:.2f}"
            print(f"호가창 클릭된 가격을 주문창에 반영: ${price_str}")
            
            # Spot 탭의 가격 입력창에 반영
            if hasattr(self, 'spot_price_input'):
                self.spot_price_input.setText(price_str)
                
            # Cross 탭의 가격 입력창에 반영
            if hasattr(self, 'cross_price_input'):
                self.cross_price_input.setText(price_str)
                
            # 시각적 피드백
            self.statusBar().showMessage(f"호가창에서 가격 선택: ${price_str}", 3000)
            
        except Exception as e:
            print(f"가격 클릭 처리 오류: {e}")

    def execute_spot_buy_with_price(self):
        """가격 지정 Spot 매수"""
        symbol = self.main_symbol_combo.currentText()
        price_text = self.spot_price_input.text().strip()
        amount_text = self.spot_amount_input.text().strip()

        if not price_text:
            QMessageBox.warning(self, "입력 오류", "호가창에서 가격을 선택하거나 직접 입력해주세요.")
            return
            
        if not amount_text:
            QMessageBox.warning(self, "입력 오류", "매수 금액을 입력해주세요.")
            return

        try:
            price = float(price_text)
            amount = float(amount_text)
            
            # 시장가 대신 지정가로 주문 (시뮬레이션)
            success, message = self.trading_engine.place_buy_order(symbol, amount_usd=amount)

            if success:
                QMessageBox.information(self, "✅ 지정가 매수 성공", 
                                      f"가격: ${price:.2f}\n{message}")
                self.spot_price_input.clear()
                self.spot_amount_input.clear()
                self.update_portfolio_display()
            else:
                QMessageBox.warning(self, "❌ 매수 실패", message)

        except ValueError:
            QMessageBox.warning(self, "입력 오류", "올바른 숫자를 입력해주세요.")

    def execute_spot_sell_with_price(self):
        """가격 지정 Spot 매도"""
        symbol = self.main_symbol_combo.currentText()
        price_text = self.spot_price_input.text().strip()
        amount_text = self.spot_amount_input.text().strip()

        if not price_text:
            QMessageBox.warning(self, "입력 오류", "호가창에서 가격을 선택하거나 직접 입력해주세요.")
            return
            
        if not amount_text:
            QMessageBox.warning(self, "입력 오류", "매도 비율을 입력해주세요.")
            return

        try:
            price = float(price_text)
            percentage = float(amount_text)
            
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
                QMessageBox.information(self, "✅ 지정가 매도 성공", 
                                      f"가격: ${price:.2f}\n{percentage}% 매도 완료\n{message}")
                self.spot_price_input.clear()
                self.spot_amount_input.clear()
                self.update_portfolio_display()
            else:
                QMessageBox.warning(self, "❌ 매도 실패", message)

        except ValueError:
            QMessageBox.warning(self, "입력 오류", "올바른 숫자를 입력해주세요.")

    def execute_long_with_price(self):
        """가격 지정 롱 포지션 - Cross 포지션 관리자 사용 🚀"""
        symbol = self.main_symbol_combo.currentText()
        price_text = self.cross_price_input.text().strip()
        amount_text = self.cross_amount_input.text().strip()
        leverage_text = self.leverage_combo.currentText().replace('x', '')

        if not price_text:
            QMessageBox.warning(self, "입력 오류", "호가창에서 가격을 선택하거나 직접 입력해주세요.")
            return
            
        if not amount_text:
            QMessageBox.warning(self, "입력 오류", "투자 금액을 입력해주세요.")
            return

        try:
            price = float(price_text)
            amount = float(amount_text)
            leverage = int(leverage_text)
            
            # BTC 수량 계산
            total_value = amount * leverage
            quantity = total_value / price
            quantity = round(quantity, 8)
            
            # 필요 증거금 계산 (투자 금액 = 증거금)
            margin_required = amount
            
            # Cross 포지션 관리자를 통해 포지션 생성 🚀
            success, message = self.cross_manager.open_position(
                symbol=symbol,
                side='LONG',
                quantity=quantity,
                price=price,
                leverage=leverage,
                margin_required=margin_required
            )
            
            if success:
                QMessageBox.information(
                    self, "✅ 롱 포지션 성공", 
                    f"🚀 롱 포지션 진입 완료!\n"
                    f"심볼: {symbol}\n"
                    f"지정가: ${price:.2f}\n"
                    f"레버리지: {leverage}x\n"
                    f"수량: {quantity} BTC\n"
                    f"증거금: ${margin_required:.2f}\n\n"
                    f"{message}"
                )
                self.cross_price_input.clear()
                self.cross_amount_input.clear()
                
                # Cross 포지션 정보 업데이트 🚀
                self.update_cross_display()
                # Cross 거래 내역 업데이트 (새 거래 발생) 🚀
                self.update_cross_transactions_only()
            else:
                QMessageBox.warning(self, "❌ 롱 포지션 실패", f"오류: {message}")

        except ValueError:
            QMessageBox.warning(self, "입력 오류", "올바른 숫자를 입력해주세요.")

    def execute_short_with_price(self):
        """가격 지정 숏 포지션 - Cross 포지션 관리자 사용 🚀"""
        symbol = self.main_symbol_combo.currentText()
        price_text = self.cross_price_input.text().strip()
        amount_text = self.cross_amount_input.text().strip()
        leverage_text = self.leverage_combo.currentText().replace('x', '')

        if not price_text:
            QMessageBox.warning(self, "입력 오류", "호가창에서 가격을 선택하거나 직접 입력해주세요.")
            return
            
        if not amount_text:
            QMessageBox.warning(self, "입력 오류", "투자 금액을 입력해주세요.")
            return

        try:
            price = float(price_text)
            amount = float(amount_text)
            leverage = int(leverage_text)
            
            # BTC 수량 계산
            total_value = amount * leverage
            quantity = total_value / price
            quantity = round(quantity, 8)
            
            # 필요 증거금 계산 (투자 금액 = 증거금)
            margin_required = amount
            
            # Cross 포지션 관리자를 통해 포지션 생성 🚀
            success, message = self.cross_manager.open_position(
                symbol=symbol,
                side='SHORT',
                quantity=quantity,
                price=price,
                leverage=leverage,
                margin_required=margin_required
            )
            
            if success:
                QMessageBox.information(
                    self, "✅ 숏 포지션 성공", 
                    f"📉 숏 포지션 진입 완료!\n"
                    f"심볼: {symbol}\n"
                    f"지정가: ${price:.2f}\n"
                    f"레버리지: {leverage}x\n"
                    f"수량: {quantity} BTC\n"
                    f"증거금: ${margin_required:.2f}\n\n"
                    f"{message}"
                )
                self.cross_price_input.clear()
                self.cross_amount_input.clear()
                
                # Cross 포지션 정보 업데이트 🚀
                self.update_cross_display()
                # Cross 거래 내역 업데이트 (새 거래 발생) 🚀
                self.update_cross_transactions_only()
            else:
                QMessageBox.warning(self, "❌ 숏 포지션 실패", f"오류: {message}")

        except ValueError:
            QMessageBox.warning(self, "입력 오류", "올바른 숫자를 입력해주세요.")

    def create_bottom_panel(self):
        """하단 거래 패널 생성 - Spot/Cross 탭 추가"""
        panel = QFrame()
        panel.setFixedHeight(200)  # 높이 증가
        panel.setStyleSheet("""
            QFrame {
                background-color: #1e2329;
                border: 1px solid #2b3139;
                border-radius: 6px;
                margin: 2px;
            }
        """)

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(10, 5, 10, 5)

        # 탭 위젯 생성
        tab_widget = QTabWidget()
        tab_widget.setStyleSheet("""
            QTabWidget::pane {
                border: 1px solid #2b3139;
                background-color: #1e2329;
            }
            QTabBar::tab {
                background-color: #2b3139;
                color: #f0f0f0;
                padding: 8px 20px;
                margin-right: 2px;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
            }
            QTabBar::tab:selected {
                background-color: #f0b90b;
                color: #000000;
                font-weight: bold;
            }
            QTabBar::tab:hover {
                background-color: #474d57;
            }
        """)

        # Spot 거래 탭
        spot_tab = self.create_spot_trading_tab()
        tab_widget.addTab(spot_tab, "Spot")

        # Cross 거래 탭 (레버리지)
        cross_tab = self.create_cross_trading_tab()
        tab_widget.addTab(cross_tab, "Cross")

        layout.addWidget(tab_widget)
        return panel

    def create_spot_trading_tab(self):
        """Spot 거래 탭 (기존 방식)"""
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(10, 5, 10, 5)

        # 왼쪽: 매수 섹션
        buy_section = QHBoxLayout()
        
        buy_label = QLabel("💰 매수:")
        buy_label.setStyleSheet("font-size: 12px; font-weight: bold; color: #0ecb81;")
        buy_section.addWidget(buy_label)
        
        self.spot_buy_input = QLineEdit()
        self.spot_buy_input.setPlaceholderText("USD 금액")
        self.spot_buy_input.setMaximumWidth(100)
        buy_section.addWidget(self.spot_buy_input)
        
        self.spot_buy_btn = QPushButton("🚀 매수")
        self.spot_buy_btn.setStyleSheet("""
            QPushButton {
                background-color: #0ecb81;
                color: white;
                font-size: 12px;
                font-weight: bold;
                padding: 8px 12px;
                border: none;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #0bb86f;
            }
        """)
        self.spot_buy_btn.clicked.connect(self.execute_spot_buy)
        buy_section.addWidget(self.spot_buy_btn)

        layout.addLayout(buy_section, 1)

        # 구분선
        separator = QFrame()
        separator.setFrameShape(QFrame.VLine)
        separator.setStyleSheet("color: #2b3139;")
        layout.addWidget(separator)

        # 오른쪽: 매도 섹션
        sell_section = QHBoxLayout()
        
        sell_label = QLabel("💸 매도:")
        sell_label.setStyleSheet("font-size: 12px; font-weight: bold; color: #f6465d;")
        sell_section.addWidget(sell_label)
        
        self.spot_sell_input = QLineEdit()
        self.spot_sell_input.setPlaceholderText("비율 (%)")
        self.spot_sell_input.setMaximumWidth(100)
        sell_section.addWidget(self.spot_sell_input)
        
        self.spot_sell_btn = QPushButton("📉 매도")
        self.spot_sell_btn.setStyleSheet("""
            QPushButton {
                background-color: #f6465d;
                color: white;
                font-size: 12px;
                font-weight: bold;
                padding: 8px 12px;
                border: none;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #f23645;
            }
        """)
        self.spot_sell_btn.clicked.connect(self.execute_spot_sell)
        sell_section.addWidget(self.spot_sell_btn)

        layout.addLayout(sell_section, 1)

        return widget

    def create_cross_trading_tab(self):
        """Cross 거래 탭 (레버리지)"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(10, 5, 10, 5)

        # 레버리지 설정 섹션
        leverage_section = QHBoxLayout()
        
        leverage_label = QLabel("⚡ 레버리지:")
        leverage_label.setStyleSheet("font-size: 12px; font-weight: bold; color: #f0b90b;")
        leverage_section.addWidget(leverage_label)
        
        self.leverage_combo = QComboBox()
        leverage_options = ["2x", "3x", "5x", "10x", "20x", "50x", "100x", "125x"]
        self.leverage_combo.addItems(leverage_options)
        self.leverage_combo.setCurrentText("10x")
        self.leverage_combo.setStyleSheet("""
            QComboBox {
                background-color: #2b3139;
                border: 1px solid #f0b90b;
                border-radius: 4px;
                padding: 5px;
                color: #f0f0f0;
                font-weight: bold;
            }
        """)
        leverage_section.addWidget(self.leverage_combo)
        
        # 현재 포지션 정보
        self.position_label = QLabel("포지션: 없음")
        self.position_label.setStyleSheet("font-size: 11px; color: #8a8a8a;")
        leverage_section.addWidget(self.position_label)
        
        leverage_section.addStretch()
        layout.addLayout(leverage_section)

        # 거래 섹션
        trading_section = QHBoxLayout()

        # 롱 포지션 (매수)
        long_section = QVBoxLayout()
        
        long_label = QLabel("📈 롱 (Long)")
        long_label.setStyleSheet("font-size: 12px; font-weight: bold; color: #0ecb81;")
        long_section.addWidget(long_label)
        
        long_input_layout = QHBoxLayout()
        long_input_layout.addWidget(QLabel("금액:"))
        self.long_input = QLineEdit()
        self.long_input.setPlaceholderText("USDT")
        self.long_input.setMaximumWidth(80)
        long_input_layout.addWidget(self.long_input)
        long_section.addLayout(long_input_layout)
        
        self.long_btn = QPushButton("🚀 롱 진입")
        self.long_btn.setStyleSheet("""
            QPushButton {
                background-color: #0ecb81;
                color: white;
                font-size: 11px;
                font-weight: bold;
                padding: 8px;
                border: none;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #0bb86f;
            }
        """)
        self.long_btn.clicked.connect(self.execute_long_position)
        long_section.addWidget(self.long_btn)

        trading_section.addLayout(long_section, 1)

        # 구분선
        separator = QFrame()
        separator.setFrameShape(QFrame.VLine)
        separator.setStyleSheet("color: #2b3139;")
        trading_section.addWidget(separator)

        # 숏 포지션 (매도)
        short_section = QVBoxLayout()
        
        short_label = QLabel("📉 숏 (Short)")
        short_label.setStyleSheet("font-size: 12px; font-weight: bold; color: #f6465d;")
        short_section.addWidget(short_label)
        
        short_input_layout = QHBoxLayout()
        short_input_layout.addWidget(QLabel("금액:"))
        self.short_input = QLineEdit()
        self.short_input.setPlaceholderText("USDT")
        self.short_input.setMaximumWidth(80)
        short_input_layout.addWidget(self.short_input)
        short_section.addLayout(short_input_layout)
        
        self.short_btn = QPushButton("📉 숏 진입")
        self.short_btn.setStyleSheet("""
            QPushButton {
                background-color: #f6465d;
                color: white;
                font-size: 11px;
                font-weight: bold;
                padding: 8px;
                border: none;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #f23645;
            }
        """)
        self.short_btn.clicked.connect(self.execute_short_position)
        short_section.addWidget(self.short_btn)

        trading_section.addLayout(short_section, 1)

        # 구분선
        separator2 = QFrame()
        separator2.setFrameShape(QFrame.VLine)
        separator2.setStyleSheet("color: #2b3139;")
        trading_section.addWidget(separator2)

        # 포지션 청산
        close_section = QVBoxLayout()
        
        close_label = QLabel("🔄 청산")
        close_label.setStyleSheet("font-size: 12px; font-weight: bold; color: #f0b90b;")
        close_section.addWidget(close_label)
        
        self.close_btn = QPushButton("⚡ 전량 청산")
        self.close_btn.setStyleSheet("""
            QPushButton {
                background-color: #f0b90b;
                color: #000000;
                font-size: 11px;
                font-weight: bold;
                padding: 8px;
                border: none;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #d9a441;
            }
        """)
        self.close_btn.clicked.connect(self.close_position)
        close_section.addWidget(self.close_btn)

        trading_section.addLayout(close_section, 1)

        layout.addLayout(trading_section)

        return widget

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
        trade_menu.addAction('전량 매도', self.sell_all_holdings)

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
        """실시간 가격 WebSocket 초기화 🚀"""
        self.price_thread = PriceWebSocketThread(self.trading_engine)
        self.price_thread.price_updated.connect(self.update_prices)
        self.price_thread.start()
        
        # 데이터 소스 표시
        self.current_price_source = 'WebSocket (실시간)'

    def on_main_symbol_changed(self, symbol):
        """메인 심볼 변경 시 호출"""
        # 코인 아이콘 변경 (3개 메이저 코인)
        coin_icons = {
            "BTCUSDT": "₿",     # 비트코인
            "ETHUSDT": "Ξ",     # 이더리움
            "SOLUSDT": "◎"      # 솔라나
        }
        self.coin_icon.setText(coin_icons.get(symbol, "🪙"))
        
        # 코인별 색상 변경 (3개 메이저 코인)
        coin_colors = {
            "BTCUSDT": "#f7931a",   # 비트코인 오렌지
            "ETHUSDT": "#627eea",   # 이더리움 블루
            "SOLUSDT": "#00d4aa"    # 솔라나 그린
        }
        color = coin_colors.get(symbol, "#f0b90b")
        self.coin_icon.setStyleSheet(f"font-size: 20px; color: {color}; font-weight: bold;")
        
        # 차트도 함께 변경
        if hasattr(self.chart_widget, 'symbol_combo'):
            self.chart_widget.symbol_combo.setCurrentText(symbol)
        
        # 호가창도 함께 변경 🚀
        if hasattr(self, 'order_book_widget'):
            self.order_book_widget.set_symbol(symbol)
        
        # 가격 업데이트
        if symbol in self.current_prices:
            price = self.current_prices[symbol]
            self.main_price_label.setText(f"${price:,.4f}")

    def update_prices(self, prices):
        """가격 업데이트 - 바이낸스 스타일 (동기화 개선)"""
        # 🚀 가격 데이터 검증 및 동기화
        validated_prices = self.validate_and_sync_prices(prices)
        self.current_prices = validated_prices
        
        current_symbol = self.main_symbol_combo.currentText()

        if current_symbol in validated_prices:
            price = validated_prices[current_symbol]
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

        # Cross 포지션 미실현 손익 업데이트 🚀
        if hasattr(self, 'cross_manager') and validated_prices:
            liquidated_positions = self.cross_manager.update_positions_pnl(validated_prices)
            
            # 자동 청산 알림 🚨
            if liquidated_positions:
                self.show_liquidation_alert(liquidated_positions)
        
        # 포트폴리오 업데이트 (검증된 가격으로)
        self.update_portfolio_display()
        
        # 상태바 업데이트 (데이터 소스 정보 포함)
        source_info = getattr(self, 'current_price_source', 'REST API')
        self.statusBar().showMessage(f"가격 업데이트: {datetime.now().strftime('%H:%M:%S')} ({source_info})")
    
    def validate_and_sync_prices(self, new_prices):
        """가격 데이터 검증 및 동기화 🚀"""
        if not hasattr(self, 'previous_prices'):
            self.previous_prices = {}
            
        validated_prices = {}
        
        for symbol, price in new_prices.items():
            prev_price = self.previous_prices.get(symbol, price)
            
            # 급격한 가격 변동 검증 (5% 이상 변동시 확인)
            if prev_price > 0:
                change_pct = abs(price - prev_price) / prev_price
                if change_pct > 0.05:  # 5% 이상 변동
                    print(f"⚠️ 급격한 가격 변동 감지: {symbol} {prev_price:.4f} → {price:.4f} ({change_pct:.2f}%)")
                    
                    # 실무에서는 여기서 추가 검증 로직
                    # 예: 다른 소스와 교차 검증, 이상치 필터링 등
                    
            validated_prices[symbol] = price
            
        # 이전 가격 업데이트
        self.previous_prices.update(validated_prices)
        return validated_prices

    def update_portfolio_display(self):
        """포트폴리오 디스플레이 업데이트 - Spot과 Cross 통합 표시 🚀"""
        summary, message = self.trading_engine.get_portfolio_status()

        if summary:
            # Cross 포지션 정보도 함께 가져오기
            cross_summary = self.cross_manager.get_cross_summary(self.current_prices)
            
            # 통합 자산 계산
            spot_total_value = summary['total_value']
            cross_total_value = cross_summary['total_value'] if cross_summary else 0
            combined_total_value = spot_total_value + cross_total_value
            
            # 통합 손익 계산
            spot_profit_loss = summary['profit_loss']
            cross_profit_loss = cross_summary['total_unrealized_pnl'] if cross_summary else 0
            combined_profit_loss = spot_profit_loss + cross_profit_loss
            
            # 통합 손익률 계산
            initial_balance = Config.INITIAL_BALANCE
            combined_profit_loss_percent = (combined_profit_loss / initial_balance) * 100

            # 헤더에 통합 정보 업데이트
            self.total_value_label.setText(f"총 자산: ${combined_total_value:,.2f}")

            # 손익 색상 설정
            if combined_profit_loss >= 0:
                color = "#0ecb81"  # 초록색
                sign = "+"
            else:
                color = "#f6465d"  # 빨간색
                sign = ""

            self.profit_loss_label.setText(f"총 손익: {sign}${combined_profit_loss:.2f} ({sign}{combined_profit_loss_percent:.2f}%)")
            self.profit_loss_label.setStyleSheet(f"font-size: 12px; color: {color};")
            
            # 하단 포트폴리오 요약 업데이트 (Spot + Cross 분리 표시)
            if hasattr(self, 'portfolio_summary_label'):
                summary_text = (
                    f"총 자산: ${combined_total_value:,.2f} | "
                    f"Spot: ${spot_total_value:,.2f} | "
                    f"Cross: ${cross_total_value:,.2f} | "
                    f"현금: ${summary['cash_balance']:,.2f} | "
                    f"손익: {sign}${combined_profit_loss:.2f} ({sign}{combined_profit_loss_percent:.2f}%)"
                )
                self.portfolio_summary_label.setText(summary_text)
                self.portfolio_summary_label.setStyleSheet(f"font-size: 12px; color: {color};")
            
            # 보유 코인 테이블 업데이트 (Spot만)
            self.update_holdings_table(summary)
            
            # 거래 내역 테이블 업데이트 (Spot만)
            self.update_transactions_table()
            
            # Cross 포지션 및 거래 내역 업데이트
            self.update_cross_display()

    def update_holdings_table(self, summary):
        """보유 코인 테이블 업데이트"""
        try:
            if not summary or not summary.get('holdings'):
                self.holdings_table.setRowCount(0)
                return

            holdings = summary['holdings']
            
            # 지원되는 코인만 필터링 (DOT 등 제거) 🚀
            filtered_holdings = {
                currency: quantity for currency, quantity in holdings.items()
                if f"{currency}USDT" in Config.SUPPORTED_PAIRS
            }
            
            print(f"\n=== 보유 코인 테이블 업데이트 ===")
            print(f"전체 보유 코인: {holdings}")
            print(f"필터링된 보유 코인: {filtered_holdings}")
            
            self.holdings_table.setRowCount(len(filtered_holdings))

            for row, (currency, quantity) in enumerate(filtered_holdings.items()):
                symbol = f"{currency}USDT"
                current_price = self.current_prices.get(symbol, 0)
                
                print(f"\n--- {currency} 처리 중 ---")
                print(f"수량: {quantity}, 현재가: {current_price}")
                
                # 평가액 계산
                market_value = quantity * current_price if current_price else 0
                
                # 평균 매수가 계산 (디버깅 강화)
                avg_buy_price = self.calculate_average_buy_price(currency)
                
                # 수익률 및 수익금 계산
                if avg_buy_price > 0:
                    profit_loss = market_value - (quantity * avg_buy_price)
                    profit_pct = (profit_loss / (quantity * avg_buy_price)) * 100
                    print(f"수익 계산: 평가액={market_value:.2f}, 매수원가={quantity * avg_buy_price:.2f}")
                    print(f"수익금={profit_loss:.2f}, 수익률={profit_pct:.2f}%")
                else:
                    profit_loss = 0
                    profit_pct = 0
                    print(f"평균 매수가가 0이므로 수익률 계산 불가")

                # 테이블에 데이터 입력
                self.holdings_table.setItem(row, 0, QTableWidgetItem(currency))
                self.holdings_table.setItem(row, 1, QTableWidgetItem(f"{quantity:.8f}"))
                self.holdings_table.setItem(row, 2, QTableWidgetItem(f"${avg_buy_price:,.2f}"))
                self.holdings_table.setItem(row, 3, QTableWidgetItem(f"${current_price:,.2f}"))
                self.holdings_table.setItem(row, 4, QTableWidgetItem(f"${market_value:,.2f}"))
                
                # 수익률 색상 설정
                profit_pct_item = QTableWidgetItem(f"{profit_pct:+.2f}%")
                profit_loss_item = QTableWidgetItem(f"${profit_loss:+,.2f}")
                
                if profit_loss >= 0:
                    profit_pct_item.setForeground(QColor("#0ecb81"))  # 초록색
                    profit_loss_item.setForeground(QColor("#0ecb81"))
                else:
                    profit_pct_item.setForeground(QColor("#f6465d"))  # 빨간색
                    profit_loss_item.setForeground(QColor("#f6465d"))
                
                self.holdings_table.setItem(row, 5, profit_pct_item)
                self.holdings_table.setItem(row, 6, profit_loss_item)

        except Exception as e:
            print(f"보유 코인 테이블 업데이트 오류: {e}")

    def calculate_average_buy_price(self, currency):
        """특정 코인의 평균 매수가 계산"""
        try:
            transactions, _ = self.trading_engine.get_transaction_history(100)  # 최근 100개 거래
            
            if not transactions:
                return 0
            
            total_quantity = 0
            total_cost = 0
            
            for tx in transactions:
                # 다양한 필드명으로 심볼 확인
                tx_symbol = tx.get('symbol')
                tx_currency = tx.get('currency')
                
                # 매칭 조건 확인 (여러 방법으로)
                is_matching = False
                if tx_currency == currency:  # currency 필드로 매칭
                    is_matching = True
                elif tx_symbol == f"{currency}USDT":  # symbol 필드로 매칭
                    is_matching = True
                
                if is_matching and tx.get('type') == 'BUY':
                    quantity = tx.get('quantity', 0)
                    total_amount = tx.get('total_amount', 0)
                    
                    total_quantity += quantity
                    total_cost += total_amount
            
            if total_quantity > 0:
                avg_price = total_cost / total_quantity
                return avg_price
            else:
                return 0
            
        except Exception as e:
            print(f"평균 매수가 계산 오류: {e}")
            return 0

    def update_transactions_table(self):
        """거래 내역 테이블 업데이트"""
        try:
            transactions, _ = self.trading_engine.get_transaction_history(20)  # 최근 20개 거래
            
            self.transactions_table.setRowCount(len(transactions))

            for row, tx in enumerate(transactions):
                # 시간 포맷팅
                timestamp = datetime.fromisoformat(tx['timestamp']).strftime('%m/%d %H:%M')
                
                # 거래 타입 이모지
                type_emoji = "🚀" if tx['type'] == 'BUY' else "📉"
                trade_type = f"{type_emoji} {tx['type']}"
                
                # 테이블에 데이터 입력
                self.transactions_table.setItem(row, 0, QTableWidgetItem(timestamp))
                
                # 거래 타입 색상 설정
                type_item = QTableWidgetItem(trade_type)
                if tx['type'] == 'BUY':
                    type_item.setForeground(QColor("#0ecb81"))
                else:
                    type_item.setForeground(QColor("#f6465d"))
                self.transactions_table.setItem(row, 1, type_item)
                
                self.transactions_table.setItem(row, 2, QTableWidgetItem(tx['currency']))
                self.transactions_table.setItem(row, 3, QTableWidgetItem(f"{tx['quantity']:.8f}"))
                self.transactions_table.setItem(row, 4, QTableWidgetItem(f"${tx['price']:,.2f}"))
                self.transactions_table.setItem(row, 5, QTableWidgetItem(f"${tx['total_amount']:,.2f}"))
                self.transactions_table.setItem(row, 6, QTableWidgetItem(f"${tx['commission']:.4f}"))
                self.transactions_table.setItem(row, 7, QTableWidgetItem("완료"))

        except Exception as e:
            print(f"거래 내역 테이블 업데이트 오류: {e}")

    def update_cross_positions_table(self):
        """Cross 포지션 테이블 업데이트 🚀"""
        try:
            cross_summary = self.cross_manager.get_cross_summary(self.current_prices)
            
            if not cross_summary or not cross_summary['positions']:
                self.cross_positions_table.setRowCount(0)
                return

            positions = cross_summary['positions']
            self.cross_positions_table.setRowCount(len(positions))

            for row, position in enumerate(positions):
                symbol = position['symbol']
                side = position['side']
                quantity = position['quantity']
                entry_price = position['entry_price']
                leverage = position['leverage']
                margin_used = position['margin_used']
                
                # 현재가 및 미실현 손익
                current_price = position.get('current_price', entry_price)
                unrealized_pnl = position.get('unrealized_pnl', 0)
                
                # 수익률 계산 - 올바른 방식으로 수정 🚀
                profit_pct = (unrealized_pnl / margin_used) * 100 if margin_used > 0 else 0

                # 테이블에 데이터 입력
                self.cross_positions_table.setItem(row, 0, QTableWidgetItem(symbol))
                
                # 방향 색상 설정
                side_item = QTableWidgetItem(f"{side}")
                if side == 'LONG':
                    side_item.setForeground(QColor("#0ecb81"))
                else:
                    side_item.setForeground(QColor("#f6465d"))
                self.cross_positions_table.setItem(row, 1, side_item)
                
                self.cross_positions_table.setItem(row, 2, QTableWidgetItem(f"{quantity:.8f}"))
                self.cross_positions_table.setItem(row, 3, QTableWidgetItem(f"${entry_price:,.2f}"))
                self.cross_positions_table.setItem(row, 4, QTableWidgetItem(f"${current_price:,.2f}"))
                self.cross_positions_table.setItem(row, 5, QTableWidgetItem(f"{leverage}x"))
                
                # 미실현손익 색상 설정
                pnl_item = QTableWidgetItem(f"${unrealized_pnl:+,.2f}")
                profit_pct_item = QTableWidgetItem(f"{profit_pct:+.2f}%")
                
                if unrealized_pnl >= 0:
                    pnl_item.setForeground(QColor("#0ecb81"))
                    profit_pct_item.setForeground(QColor("#0ecb81"))
                else:
                    pnl_item.setForeground(QColor("#f6465d"))
                    profit_pct_item.setForeground(QColor("#f6465d"))
                
                self.cross_positions_table.setItem(row, 6, pnl_item)
                self.cross_positions_table.setItem(row, 7, profit_pct_item)

        except Exception as e:
            print(f"Cross 포지션 테이블 업데이트 오류: {e}")

    def update_cross_transactions_table(self):
        """Cross 거래 내역 테이블 업데이트 🚀"""
        try:
            transactions, _ = self.cross_manager.get_cross_transactions(20)  # 최근 20개
            
            self.cross_transactions_table.setRowCount(len(transactions))

            for row, tx in enumerate(transactions):
                # 시간 포맷팅
                timestamp = datetime.fromisoformat(tx['timestamp']).strftime('%m/%d %H:%M')
                
                # 거래 타입
                tx_type = tx['type']
                symbol = tx['symbol']
                side = tx.get('side', '')
                quantity = tx.get('quantity', 0)
                price = tx.get('price', tx.get('entry_price', tx.get('close_price', 0)))
                leverage = tx.get('leverage', 1)
                
                # 손익 (청산 시에만)
                realized_pnl = tx.get('realized_pnl', 0)
                
                # 테이블에 데이터 입력
                self.cross_transactions_table.setItem(row, 0, QTableWidgetItem(timestamp))
                
                # 타입 색상 설정
                type_text = "진입" if tx_type == 'OPEN_POSITION' else "청산"
                type_item = QTableWidgetItem(type_text)
                if tx_type == 'OPEN_POSITION':
                    type_item.setForeground(QColor("#f0b90b"))
                else:
                    type_item.setForeground(QColor("#0ecb81" if realized_pnl >= 0 else "#f6465d"))
                self.cross_transactions_table.setItem(row, 1, type_item)
                
                self.cross_transactions_table.setItem(row, 2, QTableWidgetItem(symbol))
                
                # 방향 색상 설정
                side_item = QTableWidgetItem(side)
                if side == 'LONG':
                    side_item.setForeground(QColor("#0ecb81"))
                elif side == 'SHORT':
                    side_item.setForeground(QColor("#f6465d"))
                self.cross_transactions_table.setItem(row, 3, side_item)
                
                self.cross_transactions_table.setItem(row, 4, QTableWidgetItem(f"{quantity:.8f}"))
                self.cross_transactions_table.setItem(row, 5, QTableWidgetItem(f"${price:,.2f}"))
                self.cross_transactions_table.setItem(row, 6, QTableWidgetItem(f"{leverage}x"))
                
                # 손익 (청산시에만 표시)
                if tx_type == 'CLOSE_POSITION':
                    pnl_item = QTableWidgetItem(f"${realized_pnl:+,.2f}")
                    if realized_pnl >= 0:
                        pnl_item.setForeground(QColor("#0ecb81"))
                    else:
                        pnl_item.setForeground(QColor("#f6465d"))
                    self.cross_transactions_table.setItem(row, 7, pnl_item)
                else:
                    self.cross_transactions_table.setItem(row, 7, QTableWidgetItem("-"))

        except Exception as e:
            print(f"Cross 거래 내역 테이블 업데이트 오류: {e}")

    def on_cross_position_double_clicked(self, index):
        """Cross 포지션 더블클릭 시 청산 🚀"""
        try:
            row = index.row()
            symbol_item = self.cross_positions_table.item(row, 0)
            if symbol_item:
                symbol = symbol_item.text()
                
                # 해당 심볼로 전환 후 청산
                self.main_symbol_combo.setCurrentText(symbol)
                self.close_position()
                
        except Exception as e:
            print(f"Cross 포지션 더블클릭 처리 오류: {e}")

    def on_holding_clicked(self, row, column):
        """보유 코인 테이블 클릭 시 해당 코인으로 전환"""
        try:
            # 클릭한 행에서 코인 심볼 가져오기
            currency_item = self.holdings_table.item(row, 0)  # 첫 번째 컬럼 (코인)
            if currency_item is None:
                return
                
            currency = currency_item.text()
            symbol = f"{currency}USDT"
            
            # 지원되는 심볼인지 확인
            if symbol not in Config.SUPPORTED_PAIRS:
                self.statusBar().showMessage(f"⚠️ {symbol}은 지원되지 않는 거래쌍입니다.", 3000)
                return
            
            # 메인 심볼 콤보박스 변경 (이 함수가 모든 연동을 처리함)
            self.main_symbol_combo.setCurrentText(symbol)
            
            # 시각적 피드백
            self.statusBar().showMessage(f"🔄 {currency}로 전환되었습니다.", 2000)
            
            # 선택된 행 하이라이트 효과
            self.holdings_table.selectRow(row)
            
            print(f"보유 코인 클릭: {currency} → {symbol} 전환 완료")
            
        except Exception as e:
            print(f"보유 코인 클릭 처리 오류: {e}")
            self.statusBar().showMessage(f"❌ 심볼 전환 중 오류가 발생했습니다.", 3000)
    def execute_long_position(self):
        """롱 포지션 진입 (시뮬레이션)"""
        symbol = self.main_symbol_combo.currentText()
        amount_text = self.long_input.text().strip()
        leverage_text = self.leverage_combo.currentText().replace('x', '')

        if not amount_text:
            QMessageBox.warning(self, "입력 오류", "투자 금액을 입력해주세요.")
            return

        try:
            amount = float(amount_text)
            leverage = int(leverage_text)
            
            # 현재 가격 조회
            current_price = self.current_prices.get(symbol, 0)
            if not current_price:
                QMessageBox.warning(self, "오류", "가격 정보를 가져올 수 없습니다.")
                return
            
            # BTC 수량 계산 (레버리지 적용된 총 거래 금액 기준)
            total_value = amount * leverage
            quantity = total_value / current_price
            # 정밀도 조정은 futures_client에서 처리하므로 여기서는 기본 반올림만
            quantity = round(quantity, 8)  # 충분한 정밀도로 계산
            
            # 시뮬레이션 거래 실행
            success, result = self.futures_client.create_futures_order(
                symbol=symbol,
                side='BUY',
                quantity=quantity,
                price=current_price,
                leverage=leverage
            )
            
            if success:
                QMessageBox.information(
                    self, "✅ 롱 포지션 성공", 
                    f"🚀 롱 포지션 진입 완료!\n"
                    f"심볼: {symbol}\n"
                    f"레버리지: {leverage}x\n"
                    f"수량: {quantity} BTC\n"
                    f"진입가: ${current_price:,.2f}\n"
                    f"총 거래금액: ${total_value:,.2f}\n\n"
                    f"🎯 실제 바이낸스 테스트넷으로 주문되었습니다!"
                )
                self.long_input.clear()
                self.update_position_info()
            else:
                QMessageBox.warning(self, "❌ 롱 포지션 실패", f"오류: {result}")

        except ValueError:
            QMessageBox.warning(self, "입력 오류", "올바른 숫자를 입력해주세요.")
        except Exception as e:
            QMessageBox.warning(self, "오류", f"롱 포지션 실행 중 오류: {e}")

    def execute_short_position(self):
        """숏 포지션 진입 (시뮬레이션)"""
        symbol = self.main_symbol_combo.currentText()
        amount_text = self.short_input.text().strip()
        leverage_text = self.leverage_combo.currentText().replace('x', '')

        if not amount_text:
            QMessageBox.warning(self, "입력 오류", "투자 금액을 입력해주세요.")
            return

        try:
            amount = float(amount_text)
            leverage = int(leverage_text)
            
            # 현재 가격 조회
            current_price = self.current_prices.get(symbol, 0)
            if not current_price:
                QMessageBox.warning(self, "오류", "가격 정보를 가져올 수 없습니다.")
                return
            
            # BTC 수량 계산 (레버리지 적용된 총 거래 금액 기준)
            total_value = amount * leverage
            quantity = total_value / current_price
            # 정밀도 조정은 futures_client에서 처리하므로 여기서는 기본 반올림만
            quantity = round(quantity, 8)  # 충분한 정밀도로 계산
            
            # 시뮬레이션 거래 실행
            success, result = self.futures_client.create_futures_order(
                symbol=symbol,
                side='SELL',
                quantity=quantity,
                price=current_price,
                leverage=leverage
            )
            
            if success:
                QMessageBox.information(
                    self, "✅ 숏 포지션 성공", 
                    f"📉 숏 포지션 진입 완료!\n"
                    f"심볼: {symbol}\n"
                    f"레버리지: {leverage}x\n"
                    f"수량: {quantity} BTC\n"
                    f"진입가: ${current_price:,.2f}\n"
                    f"총 거래금액: ${total_value:,.2f}\n\n"
                    f"🎯 실제 바이낸스 테스트넷으로 주문되었습니다!"
                )
                self.short_input.clear()
                self.update_position_info()
            else:
                QMessageBox.warning(self, "❌ 숏 포지션 실패", f"오류: {result}")

        except ValueError:
            QMessageBox.warning(self, "입력 오류", "올바른 숫자를 입력해주세요.")
        except Exception as e:
            QMessageBox.warning(self, "오류", f"숏 포지션 실행 중 오류: {e}")

    def update_position_info(self):
        """포지션 정보 업데이트 - Cross 포지션 관리자 사용 🚀 (청산가격 포함)"""
        try:
            symbol = self.main_symbol_combo.currentText()
            
            # Cross 포지션 관리자에서 포지션 정보 가져오기
            position = self.cross_manager.find_position(symbol)
            
            if position:
                # 포지션이 있는 경우
                side = position['side']
                quantity = position['quantity']
                entry_price = position['entry_price']
                leverage = position['leverage']
                margin_used = position['margin_used']
                
                # 현재 가격으로 미실현 손익 계산
                current_price = self.current_prices.get(symbol, entry_price)
                unrealized_pnl = self.cross_manager.calculate_unrealized_pnl(position, current_price)
                
                # PnL 퍼센트 계산 - 올바른 방식
                pnl_percentage = (unrealized_pnl / margin_used) * 100 if margin_used > 0 else 0
                
                # 청산가격 계산
                liquidation_price = self.cross_manager.calculate_liquidation_price(position)
                
                # 청산까지의 거리 계산
                if side == 'LONG':
                    distance_to_liquidation = ((current_price - liquidation_price) / current_price) * 100
                elif side == 'SHORT':
                    distance_to_liquidation = ((liquidation_price - current_price) / current_price) * 100
                else:
                    distance_to_liquidation = 0
                
                # 위험도 등급 설정
                if pnl_percentage <= -70:
                    risk_level = "🔴 극위험"
                    risk_color = "#f6465d"
                elif pnl_percentage <= -50:
                    risk_level = "🟠 고위험"
                    risk_color = "#ff8c00"
                elif pnl_percentage <= -30:
                    risk_level = "🟡 중위험"
                    risk_color = "#f0b90b"
                elif pnl_percentage <= -10:
                    risk_level = "🟢 저위험"
                    risk_color = "#0ecb81"
                else:
                    risk_level = "✅ 안전"
                    risk_color = "#0ecb81"
                
                if side == 'LONG':
                    icon = "📈"
                    color = "#0ecb81"
                elif side == 'SHORT':
                    icon = "📉"
                    color = "#f6465d"
                else:
                    icon = ""
                    color = "#8a8a8a"
                
                pnl_color = "#0ecb81" if unrealized_pnl >= 0 else "#f6465d"
                
                position_text = f"{icon} {side}: {quantity:.6f} BTC | " \
                              f"진입: ${entry_price:,.2f} | 현재: ${current_price:,.2f} | " \
                              f"PnL: ${unrealized_pnl:,.2f} ({pnl_percentage:+.2f}%) | " \
                              f"청산가: ${liquidation_price:,.2f} | {risk_level} [{leverage}x]"
                
                self.position_label.setText(position_text)
                # 위험도에 따라 색상 변경
                if pnl_percentage <= -50:
                    self.position_label.setStyleSheet(f"font-size: 10px; color: {risk_color}; font-weight: bold;")
                else:
                    self.position_label.setStyleSheet(f"font-size: 10px; color: {color}; font-weight: bold;")
                
                # 청산 버튼 활성화
                self.close_btn.setEnabled(True)
                
            else:
                # 포지션이 없는 경우
                self.position_label.setText("포지션: 없음")
                self.position_label.setStyleSheet("font-size: 10px; color: #8a8a8a;")
                
                # 청산 버튼 비활성화
                self.close_btn.setEnabled(False)
                
        except Exception as e:
            self.position_label.setText("포지션 정보 로드 실패")
            self.position_label.setStyleSheet("font-size: 10px; color: #f6465d;")
            print(f"포지션 정보 업데이트 오류: {e}")

    def update_cross_display(self):
        """Cross 포지션 디스플레이 업데이트 🚀 (거래내역 제외)"""
        try:
            # 포지션 정보 업데이트 (실시간)
            self.update_position_info()
            
            # Cross 포지션 테이블 업데이트 (실시간)
            if hasattr(self, 'cross_positions_table'):
                self.update_cross_positions_table()
                
            # 포트폴리오 요약에 Cross 정보 반영
            self.update_portfolio_with_cross()
            
        except Exception as e:
            print(f"Cross 디스플레이 업데이트 오류: {e}")

    def update_cross_transactions_only(self):
        """Cross 거래 내역만 업데이트 🚀 (새 거래 발생시에만 호출)"""
        try:
            if hasattr(self, 'cross_transactions_table'):
                self.update_cross_transactions_table()
        except Exception as e:
            print(f"Cross 거래 내역 업데이트 오류: {e}")

    def update_portfolio_with_cross(self):
        """포트폴리오 요약에 Cross 포지션 정보 통합 🚀"""
        try:
            # 기본 Spot 포트폴리오 정보
            summary, _ = self.trading_engine.get_portfolio_status()
            
            # Cross 포지션 요약 정보
            cross_summary = self.cross_manager.get_cross_summary(self.current_prices)
            
            if summary and cross_summary:
                # 통합 총 자산 = Spot 총 자산 + Cross 총 가치
                total_value = summary['total_value'] + cross_summary['total_value']
                
                # 통합 손익 계산
                spot_profit_loss = summary['profit_loss']
                cross_profit_loss = cross_summary['total_unrealized_pnl']
                total_profit_loss = spot_profit_loss + cross_profit_loss
                
                # 퍼센트 계산
                initial_balance = Config.INITIAL_BALANCE
                total_profit_loss_percent = (total_profit_loss / initial_balance) * 100
                
                # 헤더 업데이트
                self.total_value_label.setText(f"총 자산: ${total_value:,.2f}")
                
                # 손익 색상 설정
                if total_profit_loss >= 0:
                    color = "#0ecb81"
                    sign = "+"
                else:
                    color = "#f6465d"
                    sign = ""
                
                self.profit_loss_label.setText(f"총 손익: {sign}${total_profit_loss:.2f} ({sign}{total_profit_loss_percent:.2f}%)")
                self.profit_loss_label.setStyleSheet(f"font-size: 12px; color: {color};")
                
                # 하단 포트폴리오 요약 업데이트
                if hasattr(self, 'portfolio_summary_label'):
                    summary_text = (
                        f"총 자산: ${total_value:,.2f} | "
                        f"Spot: ${summary['total_value']:,.2f} | "
                        f"Cross: ${cross_summary['total_value']:,.2f} | "
                        f"손익: {sign}${total_profit_loss:.2f} ({sign}{total_profit_loss_percent:.2f}%)"
                    )
                    self.portfolio_summary_label.setText(summary_text)
                    self.portfolio_summary_label.setStyleSheet(f"font-size: 12px; color: {color};")
                    
        except Exception as e:
            print(f"포트폴리오 Cross 통합 업데이트 오류: {e}")

    # 기존 메서드들은 그대로 유지...
    def execute_spot_buy(self):
        """Spot 매수 실행"""
        symbol = self.main_symbol_combo.currentText()
        amount_text = self.spot_buy_input.text().strip()

        if not amount_text:
            QMessageBox.warning(self, "입력 오류", "매수 금액을 입력해주세요.")
            return

        try:
            amount = float(amount_text)
            success, message = self.trading_engine.place_buy_order(symbol, amount_usd=amount)

            if success:
                QMessageBox.information(self, "✅ Spot 매수 성공", message)
                self.spot_buy_input.clear()
                self.update_portfolio_display()
            else:
                QMessageBox.warning(self, "❌ Spot 매수 실패", message)

        except ValueError:
            QMessageBox.warning(self, "입력 오류", "올바른 숫자를 입력해주세요.")

    def execute_spot_sell(self):
        """Spot 매도 실행"""
        symbol = self.main_symbol_combo.currentText()
        percentage_text = self.spot_sell_input.text().strip()

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
                QMessageBox.information(self, "✅ Spot 매도 성공", f"{percentage}% 매도 완료\n{message}")
                self.spot_sell_input.clear()
                self.update_portfolio_display()
            else:
                QMessageBox.warning(self, "❌ Spot 매도 실패", message)

        except ValueError:
            QMessageBox.warning(self, "입력 오류", "올바른 숫자를 입력해주세요.")

    def execute_quick_buy(self):
        """빠른 매수 실행"""
        # 다이얼로그에서 입력받기
        dialog = QInputDialog()
        dialog.setStyleSheet(self.styleSheet())
        amount, ok = dialog.getDouble(self, '빠른 매수', '매수할 USD 금액을 입력하세요:', 100, 0, 999999, 2)
        
        if not ok:
            return
            
        symbol = self.main_symbol_combo.currentText()

        try:
            success, message = self.trading_engine.place_buy_order(symbol, amount_usd=amount)

            if success:
                QMessageBox.information(self, "✅ 매수 성공", message)
                self.update_portfolio_display()
            else:
                QMessageBox.warning(self, "❌ 매수 실패", message)

        except Exception as e:
            QMessageBox.warning(self, "오류", f"매수 처리 중 오류: {e}")

    def execute_quick_sell(self):
        """빠른 매도 실행"""
        # 다이얼로그에서 입력받기
        dialog = QInputDialog()
        dialog.setStyleSheet(self.styleSheet())
        percentage, ok = dialog.getDouble(self, '빠른 매도', '매도할 비율(%)을 입력하세요:', 50, 1, 100, 1)
        
        if not ok:
            return
            
        symbol = self.main_symbol_combo.currentText()

        try:
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
                self.update_portfolio_display()
            else:
                QMessageBox.warning(self, "❌ 매도 실패", message)

        except Exception as e:
            QMessageBox.warning(self, "오류", f"매도 처리 중 오류: {e}")

    # 메뉴 액션들
    def quick_buy(self):
        """빠른 매수 다이얼로그"""
        self.execute_quick_buy()

    def quick_sell(self):
        """빠른 매도 다이얼로그"""
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

    def reset_portfolio(self):
        """포트폴리오 초기화 - Spot과 Cross 모두 초기화 🚀"""
        reply = QMessageBox.question(
            self, '포트폴리오 초기화',
            '포트폴리오를 초기화하시겠습니까?\n'
            '• Spot 보유 코인 및 거래 내역\n'
            '• Cross 포지션 및 거래 내역\n'
            '모든 데이터가 삭제됩니다.',
            QMessageBox.Yes | QMessageBox.No
        )

        if reply == QMessageBox.Yes:
            # Spot 포트폴리오 초기화
            spot_success, spot_message = self.trading_engine.reset_portfolio()
            
            # Cross 포지션 초기화
            cross_success, cross_message = self.cross_manager.reset_cross_data()

            if spot_success and cross_success:
                QMessageBox.information(self, "✅ 초기화 완료", 
                                      f"포트폴리오가 성공적으로 초기화되었습니다.\n\n"
                                      f"Spot: {spot_message}\n"
                                      f"Cross: {cross_message}")
                self.update_portfolio_display()
                self.update_cross_display()
                # Cross 거래 내역도 초기화되었으므로 업데이트 🚀
                self.update_cross_transactions_only()
            else:
                error_msg = []
                if not spot_success:
                    error_msg.append(f"Spot 초기화 실패: {spot_message}")
                if not cross_success:
                    error_msg.append(f"Cross 초기화 실패: {cross_message}")
                
                QMessageBox.warning(self, "❌ 초기화 실패", "\n".join(error_msg))

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

    def show_liquidation_alert(self, liquidated_positions):
        """자동 청산 알림 표시 🚨"""
        try:
            if not liquidated_positions:
                return
            
            # 알림 메시지 구성
            alert_title = "🚨 자동 청산 발생!"
            alert_message = f"⚠️ {len(liquidated_positions)}개 포지션이 자동 청산되었습니다:\n\n"
            
            total_loss = 0
            for liq_pos in liquidated_positions:
                symbol = liq_pos['symbol']
                side = liq_pos['side']
                pnl_pct = liq_pos['pnl_percentage']
                liquidation_price = liq_pos['liquidation_price']
                
                side_icon = "📈" if side == 'LONG' else "📉"
                alert_message += f"{side_icon} {symbol} {side}\n"
                alert_message += f"   청산가: ${liquidation_price:,.2f}\n"
                alert_message += f"   손실률: {pnl_pct:.1f}%\n\n"
            
            alert_message += "💡 위험도가 높은 포지션은 자동으로 청산됩니다.\n"
            alert_message += "포지션 관리에 더욱 주의해주세요."
            
            # 알림 대화상자 표시
            msg_box = QMessageBox()
            msg_box.setIcon(QMessageBox.Warning)
            msg_box.setWindowTitle(alert_title)
            msg_box.setText(alert_message)
            msg_box.setStyleSheet("""
                QMessageBox {
                    background-color: #1e2329;
                    color: #f0f0f0;
                }
                QMessageBox QLabel {
                    color: #f0f0f0;
                    font-size: 12px;
                }
                QMessageBox QPushButton {
                    background-color: #f6465d;
                    color: white;
                    border: none;
                    padding: 8px 16px;
                    border-radius: 4px;
                    font-weight: bold;
                }
                QMessageBox QPushButton:hover {
                    background-color: #f23645;
                }
            """)
            
            # 확인 버튼만 표시
            msg_box.setStandardButtons(QMessageBox.Ok)
            msg_box.exec_()
            
            # 상태바에도 알림 표시
            self.statusBar().showMessage(
                f"🚨 {len(liquidated_positions)}개 포지션 자동 청산됨", 
                10000  # 10초간 표시
            )
            
        except Exception as e:
            print(f"청산 알림 표시 오류: {e}")

    def closeEvent(self, event):
        """프로그램 종료 시 호출"""
        # 모든 스레드와 타이머 정리
        if hasattr(self, 'price_thread'):
            self.price_thread.stop()
        if hasattr(self, 'chart_update_thread'):
            self.chart_update_thread.stop()
        if hasattr(self, 'chart_widget') and hasattr(self.chart_widget, 'ws_manager'):
            self.chart_widget.ws_manager.stop()
        if hasattr(self, 'order_book_widget'):  # 호가창 WebSocket 정리 🚀
            self.order_book_widget.closeEvent(event)
        if hasattr(self, 'position_timer'):
            self.position_timer.stop()
        super().closeEvent(event)

    def close_position(self):
        """포지션 청산 - Cross 포지션 관리자 사용 🚀"""
        symbol = self.main_symbol_combo.currentText()
        
        try:
            # Cross 포지션 관리자에서 포지션 확인
            position = self.cross_manager.find_position(symbol)
            if not position:
                QMessageBox.information(self, "알림", "청산할 포지션이 없습니다.")
                return
            
            # 현재 가격 가져오기
            current_price = self.current_prices.get(symbol, 0)
            if not current_price:
                QMessageBox.warning(self, "오류", "현재 가격 정보를 가져올 수 없습니다.")
                return
            
            # 미실현 손익 계산
            unrealized_pnl = self.cross_manager.calculate_unrealized_pnl(position, current_price)
            
            # 청산 확인
            side_text = "롱" if position['side'] == 'LONG' else "숏"
            pnl_text = f"${unrealized_pnl:,.2f}"
            pnl_color = "수익" if unrealized_pnl >= 0 else "손실"
            
            reply = QMessageBox.question(
                self, '포지션 청산 확인',
                f"현재 {side_text} 포지션을 청산하시겠습니까?\n\n"
                f"포지션 크기: {position['quantity']:.8f} BTC\n"
                f"진입가: ${position['entry_price']:,.2f}\n"
                f"현재가: ${current_price:,.2f}\n"
                f"레버리지: {position['leverage']}x\n"
                f"미실현 {pnl_color}: {pnl_text}\n\n"
                f"💼 Cross 포지션 관리자로 청산됩니다.",
                QMessageBox.Yes | QMessageBox.No
            )
            
            if reply == QMessageBox.Yes:
                # Cross 포지션 관리자로 청산
                success, message = self.cross_manager.close_position(symbol, current_price)
                
                if success:
                    QMessageBox.information(self, "✅ 청산 완료", 
                                          f"{message}\n\n"
                                          f"실현 손익: {pnl_text}")
                    
                    # Cross 디스플레이 업데이트
                    self.update_cross_display()
                    # Cross 거래 내역 업데이트 (청산 거래 발생) 🚀
                    self.update_cross_transactions_only()
                else:
                    QMessageBox.warning(self, "❌ 청산 실패", message)
                    
        except Exception as e:
            QMessageBox.warning(self, "오류", f"포지션 청산 중 오류: {e}")

    def close_all_cross_positions(self):
        """모든 Cross 포지션 일괄 청산 🚀"""
        try:
            # 현재 모든 포지션 확인
            cross_summary = self.cross_manager.get_cross_summary(self.current_prices)
            
            if not cross_summary or not cross_summary['positions']:
                QMessageBox.information(self, "알림", "청산할 포지션이 없습니다.")
                return
            
            positions = cross_summary['positions']
            position_count = len(positions)
            
            # 총 미실현 손익 계산
            total_unrealized_pnl = sum(pos.get('unrealized_pnl', 0) for pos in positions)
            
            # 청산 확인
            pnl_text = f"${total_unrealized_pnl:,.2f}"
            pnl_color = "수익" if total_unrealized_pnl >= 0 else "손실"
            
            position_list = "\n".join([
                f"• {pos['symbol']} {pos['side']} {pos['leverage']}x: ${pos.get('unrealized_pnl', 0):+,.2f}"
                for pos in positions
            ])
            
            reply = QMessageBox.question(
                self, '모든 포지션 청산 확인',
                f"모든 Cross 포지션을 청산하시겠습니까?\n\n"
                f"📊 총 {position_count}개 포지션:\n{position_list}\n\n"
                f"💰 총 미실현 {pnl_color}: {pnl_text}\n\n"
                f"⚠️ 이 작업은 되돌릴 수 없습니다.",
                QMessageBox.Yes | QMessageBox.No
            )
            
            if reply == QMessageBox.Yes:
                closed_count = 0
                total_realized_pnl = 0
                errors = []
                
                # 모든 포지션 청산
                for position in positions:
                    symbol = position['symbol']
                    current_price = self.current_prices.get(symbol, position['entry_price'])
                    
                    success, message = self.cross_manager.close_position(symbol, current_price)
                    
                    if success:
                        closed_count += 1
                        realized_pnl = self.cross_manager.calculate_unrealized_pnl(position, current_price)
                        total_realized_pnl += realized_pnl
                    else:
                        errors.append(f"{symbol}: {message}")
                
                # 결과 메시지
                if closed_count > 0:
                    result_msg = f"✅ {closed_count}개 포지션 청산 완료!\n\n"
                    result_msg += f"💰 총 실현 손익: ${total_realized_pnl:+,.2f}"
                    
                    if errors:
                        result_msg += f"\n\n❌ 청산 실패:\n" + "\n".join(errors)
                    
                    QMessageBox.information(self, "포지션 청산 완료", result_msg)
                    
                    # Cross 디스플레이 업데이트
                    self.update_cross_display()
                    # Cross 거래 내역 업데이트 (일괄 청산 거래 발생) 🚀
                    self.update_cross_transactions_only()
                else:
                    error_msg = "❌ 모든 포지션 청산 실패:\n" + "\n".join(errors)
                    QMessageBox.warning(self, "청산 실패", error_msg)
                    
        except Exception as e:
            QMessageBox.warning(self, "오류", f"일괄 청산 중 오류: {e}")
            print(f"일괄 청산 오류: {e}")

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
    app.setApplicationVersion("2.0")
    app.setOrganizationName("Genius Trading")

    try:
        window = TradingGUI()
        window.show()
        
        print("🚀 Genius Coin Manager 시작됨")
        print("📊 실시간 차트와 모의투자를 즐겨보세요!")
        
        sys.exit(app.exec_())
        
    except Exception as e:
        print(f"❌ 애플리케이션 시작 오류: {e}")
        QMessageBox.critical(None, "시작 오류", f"프로그램을 시작할 수 없습니다:\n{e}")

if __name__ == '__main__':
    main()
