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

        # 중앙 차트 영역 (크기 조정)
        self.chart_widget = CandlestickChart(self.trading_engine)
        # 차트 크기 적절하게 조정
        self.chart_widget.figure.set_size_inches(16, 8)  # 크기 줄임
        self.chart_widget.canvas.setMinimumHeight(500)  # 높이 줄임
        main_layout.addWidget(self.chart_widget, 1)

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

    def create_bottom_panel(self):
        """하단 거래 패널 생성 - 크기 최적화"""
        panel = QFrame()
        panel.setFixedHeight(80)  # 높이 줄임
        panel.setStyleSheet("""
            QFrame {
                background-color: #1e2329;
                border: 1px solid #2b3139;
                border-radius: 6px;
                margin: 2px;
            }
        """)

        layout = QHBoxLayout(panel)
        layout.setContentsMargins(15, 8, 15, 8)

        # 왼쪽: 매수 섹션 (더 컴팩트하게)
        buy_section = QHBoxLayout()  # 수직 → 수평으로 변경
        
        buy_label = QLabel("💰 매수:")
        buy_label.setStyleSheet("font-size: 12px; font-weight: bold; color: #0ecb81;")
        buy_section.addWidget(buy_label)
        
        self.quick_buy_input = QLineEdit()
        self.quick_buy_input.setPlaceholderText("USD 금액")
        self.quick_buy_input.setMaximumWidth(100)
        buy_section.addWidget(self.quick_buy_input)
        
        self.quick_buy_btn = QPushButton("🚀 매수")
        self.quick_buy_btn.setStyleSheet("""
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
        sell_label.setStyleSheet("font-size: 12px; font-weight: bold; color: #f6465d;")
        sell_section.addWidget(sell_label)
        
        self.quick_sell_input = QLineEdit()
        self.quick_sell_input.setPlaceholderText("비율 (%)")
        self.quick_sell_input.setMaximumWidth(100)
        sell_section.addWidget(self.quick_sell_input)
        
        self.quick_sell_btn = QPushButton("📉 매도")
        self.quick_sell_btn.setStyleSheet("""
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
        self.quick_sell_btn.clicked.connect(self.execute_quick_sell)
        sell_section.addWidget(self.quick_sell_btn)

        layout.addLayout(sell_section, 1)

        return panel

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
        
        # 가격 업데이트
        if symbol in self.current_prices:
            price = self.current_prices[symbol]
            self.main_price_label.setText(f"${price:,.4f}")

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
        
        # 상태바 업데이트
        self.statusBar().showMessage(f"마지막 업데이트: {datetime.now().strftime('%H:%M:%S')}")

    def update_portfolio_display(self):
        """포트폴리오 디스플레이 업데이트 - 헤더에 요약만 표시"""
        summary, message = self.trading_engine.get_portfolio_status()

        if summary:
            # 헤더에 요약 정보만 업데이트
            self.total_value_label.setText(f"총 자산: ${summary['total_value']:,.2f}")

            # 손익 색상 설정
            profit_loss = summary['profit_loss']
            profit_loss_percent = summary['profit_loss_percent']

            if profit_loss >= 0:
                color = "#0ecb81"  # 초록색
                sign = "+"
            else:
                color = "#f6465d"  # 빨간색
                sign = ""

            self.profit_loss_label.setText(f"총 손익: {sign}${profit_loss:.2f} ({sign}{profit_loss_percent:.2f}%)")
            self.profit_loss_label.setStyleSheet(f"font-size: 14px; color: {color};")

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
        
        # 가격 업데이트
        if symbol in self.current_prices:
            price = self.current_prices[symbol]
            self.main_price_label.setText(f"${price:,.4f}")

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
        
        # 상태바 업데이트
        self.statusBar().showMessage(f"마지막 업데이트: {datetime.now().strftime('%H:%M:%S')}")

    def update_portfolio_display(self):
        """포트폴리오 디스플레이 업데이트 - 헤더에 요약만 표시"""
        summary, message = self.trading_engine.get_portfolio_status()

        if summary:
            # 헤더에 요약 정보만 업데이트
            self.total_value_label.setText(f"총 자산: ${summary['total_value']:,.2f}")

            # 손익 색상 설정
            profit_loss = summary['profit_loss']
            profit_loss_percent = summary['profit_loss_percent']

            if profit_loss >= 0:
                color = "#0ecb81"  # 초록색
                sign = "+"
            else:
                color = "#f6465d"  # 빨간색
                sign = ""

            self.profit_loss_label.setText(f"총 손익: {sign}${profit_loss:.2f} ({sign}{profit_loss_percent:.2f}%)")
            self.profit_loss_label.setStyleSheet(f"font-size: 14px; color: {color};")

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

    def reset_portfolio(self):
        """포트폴리오 초기화"""
        reply = QMessageBox.question(
            self, '포트폴리오 초기화',
            '포트폴리오를 초기화하시겠습니까?\n모든 거래 내역이 삭제됩니다.',
            QMessageBox.Yes | QMessageBox.No
        )

        if reply == QMessageBox.Yes:
            success, message = self.trading_engine.reset_portfolio()

            if success:
                QMessageBox.information(self, "초기화 완료", message)
                self.update_portfolio_display()
            else:
                QMessageBox.warning(self, "초기화 실패", message)

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
        # 모든 스레드 정리
        if hasattr(self, 'price_thread'):
            self.price_thread.stop()
        if hasattr(self, 'chart_update_thread'):
            self.chart_update_thread.stop()
        if hasattr(self, 'chart_widget') and hasattr(self.chart_widget, 'ws_manager'):
            self.chart_widget.ws_manager.stop()
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
