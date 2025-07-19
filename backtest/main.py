import visualization
import backtesting
import invest_strategy
import sys
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                             QPushButton, QComboBox, QLineEdit, QTextEdit, QLabel, QProgressBar)
from PyQt5.QtGui import QFont, QPixmap
from PyQt5.QtCore import QThread, pyqtSignal, Qt
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
import matplotlib.pyplot as plt
import pyqtgraph as pg
import pandas as pd

STRATEGIES = {
    "MA Crossover": invest_strategy.ma_crossover_strategy,
    "RSI": invest_strategy.ma_crossover_strategy
}

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
        controls_layout.addWidget(self.update_btn)

        # 전략 선택
        controls_layout.addWidget(QLabel('전략:'))
        self.strategy_combo = QComboBox()
        self.strategy_combo.addItems(STRATEGIES.keys())
        controls_layout.addWidget(self.strategy_combo)

        # 하이퍼 파라미터 입력

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

        selected_strategy_name = self.strategy_combo.currentText()
        strategy_function = STRATEGIES[selected_strategy_name]

        # 하이퍼파라미터 입력 받게 추가해야 함
        if selected_strategy_name == "MA Crossover":
            params = {'short_ma': 20, 'long_ma': 50}
        elif selected_strategy_name == "RSI":
            params = {'rsi_period': 14, 'oversold_threshold': 30, 'overbought_threshold': 70}
        else:
            params = {}

        self.worker = Worker(strategy_function, params)
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