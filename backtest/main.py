import visualization
import backtesting
import invest_strategy
import dataset
import sys
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QCheckBox, QSpinBox,
                             QPushButton, QComboBox, QLineEdit, QTextEdit, QLabel, QProgressBar, QMessageBox)
from PyQt5.QtGui import QFont, QPixmap
from PyQt5.QtCore import QThread, pyqtSignal, Qt
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
import matplotlib.pyplot as plt
import pyqtgraph as pg
import pandas as pd

STRATEGIES = {
    "MA Crossover (Spot)": {
        "function": invest_strategy.ma_crossover_strategy,
        "type": "spot",  # 'spot': 일반(현물) 거래, 'leverage': 레버리지 거래
        "params": {'short_ma': 20, 'long_ma': 50}
    },
    "MA Crossover (Leverage)": {
        "function": invest_strategy.ma_crossover_leverage_strategy,
        "type": "leverage",
        "params": {'short_ma': 20, 'long_ma': 50}
    },
    "RSI (Spot)": {
        "function": invest_strategy.rsi_strategy,
        "type": "spot",
        "params": {'rsi_period': 14, 'oversold_threshold': 30, 'overbought_threshold': 70}
    },
    "RSI (Leverage)": {
        "function": invest_strategy.rsi_leverage_strategy,
        "type": "leverage",
        "params": {'rsi_period': 14, 'oversold_threshold': 30, 'overbought_threshold': 70}
    },
    "Bollinger Band (Spot)": {
        "function": invest_strategy.bollinger_band_strategy,
        "type": "spot",
        "params": {'bb_length': 20, 'bb_std': 2}
    },
    "Bollinger Band (Leverage)": {
        "function": invest_strategy.bollinger_band_leverage_strategy,
        "type": "leverage",
        "params": {'bb_length': 20, 'bb_std': 2}
    },
    "ADX Filtered Dual Strategy (Leverage)": {
        "function": invest_strategy.adx_filtered_dual_strategy,
        "type": "leverage",
        "params": {
            'adx_period': 10, 'adx_threshold': 25,
            'rsi_period': 14, 'oversold_threshold': 30, 'overbought_threshold': 70,
            'ema_short_period': 12, 'ema_long_period': 26,
            'stop_loss_pct': -1.5, 'take_profit_pct': 3.0
        }
    }
}

class LeverageWorker(QThread):
    progress = pyqtSignal(int, int)
    finished = pyqtSignal(dict)
    plot_update = pyqtSignal(object, float, float)

    def __init__(self, strategy_function, strategy_param, leverage):
        super().__init__()
        self.strategy_function = strategy_function
        self.strategy_param = strategy_param
        self.leverage = leverage
    
    def run(self):
        # backtesting.leverage_backtest 함수를 호출합니다.
        results = backtesting.leverage_backtest(
            self.strategy_function,
            self.strategy_param,
            self.leverage,
            progress_callback=self.progress.emit,
            plot_callback=self.plot_update.emit
        )

        if results:
            self.finished.emit(results)

class Worker(QThread):
    # 신호 정의
    progress = pyqtSignal(int, int)
    finished = pyqtSignal(dict)
    plot_update = pyqtSignal(object, float, float)

    def __init__(self, strategy_function, strategy_param):
        super().__init__()
        self.strategy_function = strategy_function
        self.strategy_param = strategy_param
    
    def run(self):
        results = backtesting.backtest(
            self.strategy_function,
            self.strategy_param,
            progress_callback=self.progress.emit,
            plot_callback=self.plot_update.emit
        )

        if results:
            self.finished.emit(results)

class DataUpdateWorker(QThread):
    finished = pyqtSignal()
    error = pyqtSignal(str)

    def run(self):
        try:
            dataset.update_data(file_name='backtest/data.csv')
            self.finished.emit()
        except Exception as e:
            self.error.emit(str(e))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.regions = []

        self.setWindowTitle('Genius Coin Manager - Backtester')
        self.setGeometry(300, 300, 1200, 800) # x, y, width, height

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        self.main_layout = QVBoxLayout(central_widget)

        controls_layout = QHBoxLayout()

        # 데이터 업데이트 버튼
        self.update_btn = QPushButton('데이터 업데이트')
        self.update_btn.clicked.connect(self.handle_data_update)
        controls_layout.addWidget(self.update_btn)

        # 전략 선택
        controls_layout.addWidget(QLabel('전략:'))
        self.strategy_combo = QComboBox()
        self.strategy_combo.addItems(STRATEGIES.keys())
        controls_layout.addWidget(self.strategy_combo)

        # 하이퍼 파라미터 입력
        # 레버리지 스핀박스 (체크박스는 제거)
        self.leverage_spinbox = QSpinBox()
        self.leverage_spinbox.setRange(1, 125)
        self.leverage_spinbox.setValue(10)
        self.leverage_spinbox.setSuffix('x')
        controls_layout.addWidget(self.leverage_spinbox)

        # 백테스팅 실행 버튼
        self.run_btn = QPushButton('백테스팅 실행')
        controls_layout.addWidget(self.run_btn)
        self.main_layout.addLayout(controls_layout)

        # 그래프 영역
        self.plot_widget = pg.PlotWidget(axisItems={'bottom': pg.DateAxisItem()})
        self.plot_widget.setBackground('w')
        self.plot_widget.setMinimumSize(600, 500)
        self.main_layout.addWidget(self.plot_widget)

        self.plot_widget.addLegend()
        self.plot_widget.getPlotItem().getAxis('left').setLabel('Return (%)')
        self.plot_widget.getPlotItem().getAxis('bottom').setLabel('Start Date of Window')
        self.plot_widget.showGrid(x=True, y=True)

        self.plot_widget.addLine(y=0, pen=pg.mkPen('r', style=Qt.DashLine))

        self.strategy_line = self.plot_widget.plot(pen=pg.mkPen('b', width=2), name='Strategy Return')
        self.market_line = self.plot_widget.plot(pen=pg.mkPen('g', width=2), name='Market Return')
        
        # 진행바
        self.progress_bar = QProgressBar(self)
        self.progress_bar.setValue(0)
        self.main_layout.addWidget(self.progress_bar)

        # 결과 로그 영역
        self.results_text = QTextEdit()
        self.results_text.setReadOnly(True)
        self.results_text.setText('백테스팅 결과가 여기에 출력됩니다.')
        self.main_layout.addWidget(self.results_text)

        self.run_btn.clicked.connect(self.run_backtest)
        self.strategy_combo.currentTextChanged.connect(self.on_strategy_change)
        self.on_strategy_change(self.strategy_combo.currentText())

    def on_strategy_change(self, strategy_name):
        """콤보박스에서 선택된 전략에 따라 레버리지 입력창의 활성화 여부를 결정합니다."""
        if not strategy_name:
            return
            
        strategy_type = STRATEGIES[strategy_name].get('type', 'spot')

        if strategy_type == 'leverage':
            self.leverage_spinbox.setEnabled(True)
        else: # 'spot'
            self.leverage_spinbox.setEnabled(False)

    def handle_data_update(self):
        self.update_btn.setEnabled(False)
        self.run_btn.setEnabled(False)
        self.results_text.setText("데이터 업데이트를 시작합니다...")

        # 데이터 업데이트 워커 생성 및 시작
        self.data_worker = DataUpdateWorker()
        self.data_worker.finished.connect(self.on_data_update_finished)
        self.data_worker.error.connect(self.on_data_update_error)
        self.data_worker.start()
    
    def on_data_update_finished(self):
        """데이터 업데이트 성공 시 호출될 메소드"""
        self.results_text.append("데이터 업데이트가 완료되었습니다.")
        QMessageBox.information(self, "알림", "데이터 업데이트가 성공적으로 완료되었습니다.")
        self.update_btn.setEnabled(True)
        self.run_btn.setEnabled(True)


    def on_data_update_error(self, err_msg):
        """데이터 업데이트 실패 시 호출될 메소드"""
        self.results_text.append(f"데이터 업데이트 중 오류 발생: {err_msg}")
        QMessageBox.critical(self, "오류", f"데이터 업데이트 중 오류가 발생했습니다:\n{err_msg}")
        self.update_btn.setEnabled(True)
        self.run_btn.setEnabled(True)
    
    def run_backtest(self):
        self.run_btn.setEnabled(False)
        self.results_text.setText("백테스팅을 시작합니다. 잠시만 기다려주세요...")
        self.results_text.append("데이터를 불러오고 있습니다.")

        for region in self.regions:
            self.plot_widget.removeItem(region)
        self.regions = []

        self.in_alpha_region = False
        self.region_start_x = None

        self.x_data, self.y_strategy, self.y_market = [], [], []
        self.strategy_line.setData(self.x_data, self.y_strategy)
        self.market_line.setData(self.x_data, self.y_market)

        selected_name = self.strategy_combo.currentText()
        strategy_info = STRATEGIES[selected_name]
        
        strategy_function = strategy_info["function"]
        strategy_type = strategy_info["type"]
        params = strategy_info["params"] # 기본 파라미터를 가져옴 (향후 UI에서 수정 가능)

        if strategy_type == 'leverage':
            leverage_value = self.leverage_spinbox.value()
            self.results_text.append(f"\n레버리지 백테스팅 모드 (전략: {selected_name}, 레버리지: {leverage_value}x)")
            self.worker = LeverageWorker(strategy_function, params, leverage_value)
        
        else: # 'spot'
            self.results_text.append(f"\n일반 백테스팅 모드 (전략: {selected_name})")
            self.worker = Worker(strategy_function, params)

        # Worker 연결 및 시작 (공통 로직)
        self.worker.progress.connect(self.update_progress)
        self.worker.plot_update.connect(self.update_plot)
        self.worker.finished.connect(self.display_results)
        self.worker.finished.connect(lambda: self.run_btn.setEnabled(True))
        self.worker.start()

    def update_progress(self, current_step, total_steps):
        progress_percent = int((current_step / total_steps) * 100)
        self.progress_bar.setValue(progress_percent)

        self.results_text.append(f"({current_step}/{total_steps}) 구간 테스트 완료...")
    
    def update_plot(self, start_date, strategy_return, market_return):
        self.x_data.append(start_date.timestamp())
        self.y_strategy.append(strategy_return)
        self.y_market.append(market_return)

        self.strategy_line.setData(self.x_data, self.y_strategy)
        self.market_line.setData(self.x_data, self.y_market)

        current_x = start_date.timestamp()

        if strategy_return > market_return:
            if not self.in_alpha_region:
                self.in_alpha_region = True
                self.region_start_x = current_x
        else:
            if self.in_alpha_region:
                self.in_alpha_region = False
                region = pg.LinearRegionItem(values=[self.region_start_x, self.x_data[-2]], brush=pg.mkBrush(200, 255, 200, 50))
                region.setZValue(-10)
                self.plot_widget.addItem(region)
                self.regions.append(region)
    
    def display_plot(self, fig):
        self.canvas = FigureCanvas(fig)

        old_widget = self.main_layout.itemAt(1).widget()
        self.main_layout.replaceWidget(old_widget, self.canvas)
        old_widget.deleteLater()

    def display_results(self, results):
        self.results_text.append("\n===== 최종 결과 =====")
        for key, value in results.items():
            self.results_text.append(f"{key}: {value}")



if __name__ == "__main__":
    app = QApplication(sys.argv)

    app_font = QFont("NanumGothic", 10)
    app.setFont(app_font)

    window = MainWindow()
    window.show()
    sys.exit(app.exec_())
