import sys
import backtesting
import invest_strategy
import dataset
import pandas as pd
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                             QPushButton, QComboBox, QTextEdit, QLabel, QProgressBar, QLineEdit,
                             QSpinBox, QDateEdit, QMessageBox, QCheckBox)
from PyQt5.QtGui import QFont
from PyQt5.QtCore import QThread, pyqtSignal, Qt, QDate
import pyqtgraph as pg

# --- 상수/설정 딕셔너리 ---
STRATEGIES = {
    "MA Crossover (Leverage)": {
        "function": invest_strategy.ma_crossover_leverage_strategy, "type": "leverage",
        "params": {
            'short_ma': {'type': 'int', 'value': 20},
            'long_ma': {'type': 'int', 'value': 50}
        }
    },
    "RSI (Leverage)": {
        "function": invest_strategy.rsi_leverage_strategy, "type": "leverage",
        "params": {
            'rsi_period': {'type': 'int', 'value': 14},
            'oversold_threshold': {'type': 'int', 'value': 30},
            'overbought_threshold': {'type': 'int', 'value': 70}
        }
    },
    "Bollinger Band (Leverage)": {
        "function": invest_strategy.bollinger_band_leverage_strategy, "type": "leverage",
        "params": {
            'bb_length': {'type': 'int', 'value': 20},
            'bb_std': {'type': 'int', 'value': 2}
        }
    },
    "ADX Filter Dual (Leverage)": {
        "function": invest_strategy.adx_filtered_dual_strategy, "type": "leverage",
        "params": {
            'adx_period': {'type': 'int', 'value': 14},
            'adx_threshold': {'type': 'int', 'value': 25},
            'rsi_period': {'type': 'int', 'value': 14},
            'oversold_threshold': {'type': 'int', 'value': 30},
            'overbought_threshold': {'type': 'int', 'value': 70},
            'ema_short_period': {'type': 'int', 'value': 12},
            'ema_long_period': {'type': 'int', 'value': 26},
            'stop_loss_pct': {'type': 'int', 'value': -5},
            'take_profit_pct': {'type': 'int', 'value': 10}
        }
    },
    "MACD Tracker (DOGE Optimized)": {
        "function": invest_strategy.macd_liquidity_tracker, "type": "leverage",
        "params": {
            'system_type': {'type': 'categorical', 'value': 'Fast', 'options': ['Normal', 'Fast', 'Safe', 'Crossover']},
            'fast_ma': {'type': 'int', 'value': 45},
            'slow_ma': {'type': 'int', 'value': 80},
            'signal_ma': {'type': 'int', 'value': 290},
            'use_trend_filter': {'type': 'categorical', 'value': True, 'options': [True, False]},
            'trend_ma_len': {'type': 'int', 'value': 50},
            'stop_loss_pct': {'type': 'int', 'value': 0},
            'take_profit_pct': {'type': 'int', 'value': 0}
        }
    },
    "MACD Tracker (revised)": {
        "function": invest_strategy.macd_liquidity_tracker_revised_crossover, "type": "leverage",
        "params": {
            'fast_ma': {'type': 'int', 'value': 21},
            'slow_ma': {'type': 'int', 'value': 55},
            'signal_ma': {'type': 'int', 'value': 8},
            'use_trend_filter': {'type': 'categorical', 'value': True, 'options': [True, False]},
            'trend_ma_len': {'type': 'int', 'value': 10},
            'long_trend_len': {'type': 'int', 'value': 4800},
            'stop_loss_pct': {'type': 'int', 'value': -10},
            'take_profit_pct': {'type': 'int', 'value': 0}
        }
    },
    "MACD Crossover (Dual Filter)": {
    "function": invest_strategy.macd_crossover_dual_filter,
    "type": "leverage",
    "params": {
        'fast_ma': {'type': 'int', 'value': 21},
        'slow_ma': {'type': 'int', 'value': 55},
        'signal_ma': {'type': 'int', 'value': 8},
        'trend_ma_len': {'type': 'int', 'value': 10}, # 단기 추세 필터
        'regime_filter_period': {'type': 'int', 'value': 4800}, # 장기 국면 필터 (1h 기준 200일)
        'stop_loss_pct': {'type': 'int', 'value': -5},
        'take_profit_pct': {'type': 'int', 'value': 0}
        }
    },
    # main.py의 STRATEGIES 딕셔너리에 추가
    "MACD Crossover + Filter": {
        "function": invest_strategy.macd_crossover_with_filter,
        "type": "leverage",
        "params": {
            'fast_ma': {'type': 'int', 'value': 21},
            'slow_ma': {'type': 'int', 'value': 55},
            'signal_ma': {'type': 'int', 'value': 8},
            'stop_loss_pct': {'type': 'int', 'value': -5},
            'take_profit_pct': {'type': 'int', 'value': 0},
            # 1시간봉 기준 200일 = 4800
            'regime_filter_period': {'type': 'int', 'value': 4800} 
        }
    },
    # main.py의 STRATEGIES 딕셔너리에 추가
    "MACD Advanced Filter": {
        "function": invest_strategy.macd_crossover_advanced_filter,
        "type": "leverage",
        "params": {
            'fast_ma': {'type': 'int', 'value': 21},
            'slow_ma': {'type': 'int', 'value': 55},
            'signal_ma': {'type': 'int', 'value': 8},
            'adx_period': {'type': 'int', 'value': 14},
            'adx_threshold': {'type': 'int', 'value': 20},
            'trend_ma_len': {'type': 'int', 'value': 50},
            'regime_filter_period': {'type': 'int', 'value': 4800},
            'stop_loss_pct': {'type': 'int', 'value': -5},
            'take_profit_pct': {'type': 'int', 'value': 0}
        }
    },
    "Simple MA Crossover (Spot)": {
        "function": invest_strategy.simple_ma_strategy,
        "type": "spot",
        "params": {
            'ma_period': {'type': 'int', 'value': 50}
        }
    },
    "Momentum Spike Scalping": {
        "function": invest_strategy.momentum_spike_scalping_long_short,
        "type": "leverage", # 현물 전용 전략
        "params": {
            'spike_pct': {'type': 'float', 'value': 3},
            'take_profit_pct': {'type': 'float', 'value': 1},
            'stop_loss_pct': {'type': 'float', 'value': -1}
        }
    },
    "Momentum Spike Scalping inverse": {
        "function": invest_strategy.momentum_spike_scalping_long_short_inverse,
        "type": "leverage", # 현물 전용 전략
        "params": {
            'spike_pct': {'type': 'float', 'value': 3},
            'take_profit_pct': {'type': 'float', 'value': 1},
            'stop_loss_pct': {'type': 'float', 'value': -1}
        }
    },
    "Final MACD Strategy": {
        "function": invest_strategy.macd_final_strategy,
        "type": "leverage",
        "params": {
            # 이 전략은 파라미터가 대부분 고정되어 있으므로,
            # 장기 추세 필터 기간만 조절할 수 있습니다.
            'regime_filter_period': {'type': 'int', 'value': 4800} 
        }
    },
    "Momentum Spike (50% Capital, L/S)": {
        "function": invest_strategy.momentum_spike_scalping_long_short_half_capital,
        "type": "leverage",
        "params": {
            'spike_pct': {'type': 'float', 'value': 3},
            'take_profit_pct': {'type': 'float', 'value': 1},
            'stop_loss_pct': {'type': 'float', 'value': -1}
        }
    },
    "Momentum Spike (50% Capital, Realistic)": {
        "function": invest_strategy.momentum_spike_scalping_long_short_realistic,
        "type": "leverage",
        "params": {
            'spike_pct': {'type': 'float', 'value': 3},
            'take_profit_pct': {'type': 'float', 'value': 1},
            'stop_loss_pct': {'type': 'float', 'value': -1},
            'min_order_size_btc': {'type': 'float', 'value': 0.001}
        }
    }
}
RESAMPLE_MAP = {"1분봉": "min", "5분봉": "5min", "15분봉": "15min", "1시간봉": "h", "4시간봉": "4h", "1일봉": "D"}
WINDOW_SIZE_MAP = {"3개월": pd.DateOffset(months=3), "6개월": pd.DateOffset(months=6), "1년": pd.DateOffset(years=1), "2년": pd.DateOffset(years=2)}
STEP_SIZE_MAP = {"1일": pd.DateOffset(days=1), "1주일": pd.DateOffset(weeks=1), "1개월": pd.DateOffset(months=1)}


# --- Worker 클래스들 ---
class DataUpdateWorker(QThread):
    finished = pyqtSignal(); error = pyqtSignal(str)
    def run(self):
        try: dataset.update_data(); self.finished.emit()
        except Exception as e: self.error.emit(str(e))

class RollingWindowWorker(QThread):
    progress = pyqtSignal(int, int); finished = pyqtSignal(dict); plot_update = pyqtSignal(object, float, float)
    def __init__(self, sf, sp, lev, rp, ws, ss):
        super().__init__()
        self.sf, self.sp, self.lev, self.rp, self.ws, self.ss = sf, sp, lev, rp, ws, ss
    def run(self):
        func = backtesting.leverage_backtest if self.lev > 1 else backtesting.backtest
        if self.lev > 1:
            results = func(self.sf, self.sp, self.lev, self.rp, self.ws, self.ss, self.progress.emit, self.plot_update.emit)
        else:
            results = func(self.sf, self.sp, self.rp, self.ws, self.ss, self.progress.emit, self.plot_update.emit)
        if results: self.finished.emit(results)

class FullPeriodWorker(QThread):
    """전체 기간 테스트용 Worker 수정"""
    # ⭐ plot_update 시그널 추가
    plot_update = pyqtSignal(object, float, float)
    finished = pyqtSignal(object, dict)

    def __init__(self, sf, sp, lev, rp, sd):
        super().__init__()
        self.sf, self.sp, self.lev, self.rp, self.sd = sf, sp, lev, rp, sd

    def run(self):
        # ⭐ backtest_full_period 함수에 plot_callback으로 self.plot_update.emit 전달
        results_df, summary = backtesting.backtest_full_period(
            self.sf, self.sp, self.rp, self.sd, leverage=self.lev, plot_callback=self.plot_update.emit
        )
        if summary:
            self.finished.emit(results_df, summary)

# --- 메인 윈도우 ---
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.param_widgets, self.regions = {}, []
        self.zero_line = None
        self.setWindowTitle('Genius Coin Manager - Backtester'); self.setGeometry(200, 200, 1400, 900)
        central_widget = QWidget(); self.setCentralWidget(central_widget)
        self.main_layout = QVBoxLayout(central_widget)

        strategy_layout = QHBoxLayout()
        self.update_btn = QPushButton('데이터 업데이트'); strategy_layout.addWidget(self.update_btn)
        strategy_layout.addWidget(QLabel('테스트 타입:')); self.test_type_combo = QComboBox(); self.test_type_combo.addItems(["롤링 윈도우 테스트", "전체 기간 테스트"]); strategy_layout.addWidget(self.test_type_combo)
        strategy_layout.addWidget(QLabel('전략:')); self.strategy_combo = QComboBox(); self.strategy_combo.addItems(STRATEGIES.keys()); strategy_layout.addWidget(self.strategy_combo)
        self.leverage_spinbox = QSpinBox(); self.leverage_spinbox.setRange(1, 125); self.leverage_spinbox.setSuffix('x'); strategy_layout.addWidget(self.leverage_spinbox)
        self.main_layout.addLayout(strategy_layout)

        settings_layout = QHBoxLayout()
        settings_layout.addWidget(QLabel("시간봉:")); self.resample_combo = QComboBox(); self.resample_combo.addItems(RESAMPLE_MAP.keys()); self.resample_combo.setCurrentText("1시간봉"); settings_layout.addWidget(self.resample_combo)
        settings_layout.addWidget(QLabel("롤링 기간:")); self.window_size_combo = QComboBox(); self.window_size_combo.addItems(WINDOW_SIZE_MAP.keys()); self.window_size_combo.setCurrentText("6개월"); settings_layout.addWidget(self.window_size_combo)
        settings_layout.addWidget(QLabel("롤링 간격:")); self.step_size_combo = QComboBox(); self.step_size_combo.addItems(STEP_SIZE_MAP.keys()); self.step_size_combo.setCurrentText("1일"); settings_layout.addWidget(self.step_size_combo)
        settings_layout.addWidget(QLabel("전체 기간 시작일:")); self.start_date_edit = QDateEdit(QDate.currentDate().addYears(-3)); self.start_date_edit.setCalendarPopup(True); settings_layout.addWidget(self.start_date_edit)

        # ⭐ 1. 로그 스케일 체크박스 UI 추가
        self.log_scale_checkbox = QCheckBox("Y축 로그 스케일")
        settings_layout.addWidget(self.log_scale_checkbox)
        
        self.main_layout.addLayout(settings_layout)

        self.main_layout.addLayout(settings_layout)

        self.params_layout = QHBoxLayout(); self.main_layout.addLayout(self.params_layout)
        self.run_btn = QPushButton('백테스팅 실행'); self.main_layout.addWidget(self.run_btn)
        
        self.plot_widget = pg.PlotWidget(axisItems={'bottom': pg.DateAxisItem()}); self.plot_widget.setBackground('w'); self.plot_widget.addLegend(); self.plot_widget.showGrid(x=True, y=True)
        self.strategy_line = self.plot_widget.plot(pen=pg.mkPen('b', width=2), name='Strategy'); self.market_line = self.plot_widget.plot(pen=pg.mkPen('g', width=2), name='Market')
        self.main_layout.addWidget(self.plot_widget)
        self.progress_bar = QProgressBar(self); self.main_layout.addWidget(self.progress_bar)
        self.results_text = QTextEdit(); self.results_text.setReadOnly(True); self.main_layout.addWidget(self.results_text)
        
        self.run_btn.clicked.connect(self.run_backtest); self.update_btn.clicked.connect(self.handle_data_update)
        self.strategy_combo.currentTextChanged.connect(self.on_strategy_change); self.test_type_combo.currentTextChanged.connect(self.on_test_type_change)
        self.on_strategy_change(self.strategy_combo.currentText()); self.on_test_type_change(self.test_type_combo.currentText())

        # ⭐ 2. 체크박스 신호 연결 추가
        self.log_scale_checkbox.stateChanged.connect(self.toggle_log_scale)

        self.on_strategy_change(self.strategy_combo.currentText())
        self.on_test_type_change(self.test_type_combo.currentText())

        # ⭐ 3. 로그 스케일 적용 함수 추가
    def toggle_log_scale(self, state):
        """Y축의 로그 스케일 모드를 켜고 끕니다."""
        is_log_mode = (state == Qt.Checked)
        self.plot_widget.getPlotItem().setLogMode(y=is_log_mode)

    def on_test_type_change(self, test_type):
        is_rolling = (test_type == "롤링 윈도우 테스트")
        self.window_size_combo.setEnabled(is_rolling); self.step_size_combo.setEnabled(is_rolling)
        self.start_date_edit.setEnabled(not is_rolling)

    def on_strategy_change(self, strategy_name):
        if not strategy_name: return
        for widget in self.param_widgets.values():
            self.params_layout.removeWidget(widget['label']); self.params_layout.removeWidget(widget['input'])
            widget['label'].deleteLater(); widget['input'].deleteLater()
        self.param_widgets.clear()
        
        strategy_type = STRATEGIES[strategy_name].get('type', 'spot')
        self.leverage_spinbox.setEnabled(strategy_type == 'leverage')
        if strategy_type != 'leverage': self.leverage_spinbox.setValue(1)
        
        params_config = STRATEGIES[strategy_name].get('params', {})
        for name, info in params_config.items():
            label = QLabel(f"{name}:")
            param_type = info.get('type', 'int')
            default_value = info.get('value', 0)
            
            if param_type == 'int':
                input_widget = QSpinBox()
                input_widget.setRange(-10000, 100000)
                input_widget.setValue(int(default_value))
            elif param_type == 'categorical':
                input_widget = QComboBox()
                options = info.get('options', [])
                if all(isinstance(opt, bool) for opt in options):
                    str_options = ['On' if opt else 'Off' for opt in options]
                    input_widget.addItems(str_options)
                    input_widget.setCurrentText('On' if default_value else 'Off')
                else:
                    input_widget.addItems([str(opt) for opt in options])
                    input_widget.setCurrentText(str(default_value))
            else:
                input_widget = QLineEdit(str(default_value))

            self.params_layout.addWidget(label); self.params_layout.addWidget(input_widget)
            self.param_widgets[name] = {'label': label, 'input': input_widget, 'info': info}

    def prepare_backtest(self):
        self.run_btn.setEnabled(False); self.progress_bar.setValue(0); self.results_text.setText("백테스팅을 시작합니다...")
        for region in self.regions: self.plot_widget.removeItem(region)
        self.regions.clear(); self.strategy_line.setData([], []); self.market_line.setData([], [])

    def run_backtest(self):
        self.prepare_backtest()
        selected_name = self.strategy_combo.currentText(); strategy_info = STRATEGIES[selected_name]
        
        updated_params = {}
        for name, widget_info in self.param_widgets.items():
            widget = widget_info['input']
            param_type = widget_info['info']['type']
            if isinstance(widget, QSpinBox): updated_params[name] = widget.value()
            elif isinstance(widget, QComboBox):
                current_text = widget.currentText()
                options = widget_info['info']['options']
                if all(isinstance(opt, bool) for opt in options): updated_params[name] = (current_text == 'On')
                else: updated_params[name] = current_text
            else: updated_params[name] = widget.text()

        leverage = self.leverage_spinbox.value()
        resample_period = RESAMPLE_MAP[self.resample_combo.currentText()]
        
        if self.test_type_combo.currentText() == "롤링 윈도우 테스트":
            self.setup_rolling_window_ui()
            window_size = WINDOW_SIZE_MAP[self.window_size_combo.currentText()]; step_size = STEP_SIZE_MAP[self.step_size_combo.currentText()]
            self.worker = RollingWindowWorker(strategy_info["function"], updated_params, leverage, resample_period, window_size, step_size)
            self.worker.progress.connect(self.update_progress); self.worker.plot_update.connect(self.update_rolling_plot); self.worker.finished.connect(self.display_rolling_results)
        else:
            self.setup_full_period_ui()
            naive_date = self.start_date_edit.date().toPyDate()
            start_date = pd.Timestamp(naive_date, tz='UTC')
            self.worker = FullPeriodWorker(strategy_info["function"], updated_params, leverage, resample_period, start_date)
            
            # ⭐ plot_update 시그널을 새 그래프 업데이트 함수에 연결
            self.worker.plot_update.connect(self.update_full_period_plot)
            self.worker.finished.connect(self.display_full_period_results)
        
        self.worker.finished.connect(lambda: self.run_btn.setEnabled(True))
        self.worker.start()

    def setup_rolling_window_ui(self):
        """롤링 윈도우 테스트용 UI 설정"""
        self.plot_widget.getPlotItem().getAxis('left').setLabel('Return (%)')
        self.plot_widget.getPlotItem().getAxis('bottom').setLabel('Start Date of Window')
        
        # 기존에 선이 있으면 제거
        if self.zero_line:
            self.plot_widget.removeItem(self.zero_line)
            self.zero_line = None
            
        # ⭐ 2. 0% 기준선을 생성하고 변수에 저장
        self.zero_line = self.plot_widget.addLine(y=0, pen=pg.mkPen('r', style=Qt.DashLine))
        self.x_data, self.y_strategy, self.y_market = [], [], []

    def setup_full_period_ui(self):
        """전체 기간 테스트용 UI 설정"""
        self.plot_widget.getPlotItem().getAxis('left').setLabel('Balance ($)')
        self.plot_widget.getPlotItem().getAxis('bottom').setLabel('Date')
        if self.zero_line:
            self.plot_widget.removeItem(self.zero_line)
            self.zero_line = None
        # ⭐ 그래프 데이터를 저장할 리스트 초기화
        self.x_data, self.y_strategy, self.y_market = [], [], []
    
    def update_full_period_plot(self, timestamp, strategy_balance, market_balance):
        """⭐ 전체 기간 그래프를 실시간으로 업데이트하는 새 함수"""
        self.x_data.append(timestamp.timestamp())
        self.y_strategy.append(strategy_balance)
        self.y_market.append(market_balance)
        self.strategy_line.setData(self.x_data, self.y_strategy)
        self.market_line.setData(self.x_data, self.y_market)
    
    def display_full_period_results(self, results_df, summary):
        """⭐ 전체 기간 최종 결과 표시 (그래프 그리기 로직 제거)"""
        self.progress_bar.setValue(100)
        self.results_text.append("\n===== 전체 기간 최종 결과 =====")
        
        # 텍스트 결과만 표시
        for key, value in summary.items():
            self.results_text.append(f"{key}: {value}")

    def update_progress(self, current, total): self.progress_bar.setValue(int((current / total) * 100))
    def update_rolling_plot(self, start_date, sr, mr):
        self.x_data.append(start_date.timestamp()); self.y_strategy.append(sr); self.y_market.append(mr)
        self.strategy_line.setData(self.x_data, self.y_strategy); self.market_line.setData(self.x_data, self.y_market)
    def display_rolling_results(self, results):
        self.progress_bar.setValue(100); self.results_text.append("\n===== 롤링 윈도우 최종 결과 =====")
        for key, value in results.items(): self.results_text.append(f"{key}: {value}")
    def display_full_period_results(self, results_df, summary):
        self.progress_bar.setValue(100); self.results_text.append("\n===== 전체 기간 최종 결과 =====")
        for key, value in summary.items(): self.results_text.append(f"{key}: {value}")
        if not results_df.empty:
            timestamps = results_df.index.astype(int) / 10**9
            self.strategy_line.setData(timestamps, results_df['Strategy'].values); self.market_line.setData(timestamps, results_df['Market'].values)

    def handle_data_update(self):
        self.run_btn.setEnabled(False); self.update_btn.setEnabled(False); self.results_text.setText("데이터 업데이트를 시작합니다...")
        self.data_worker = DataUpdateWorker(); self.data_worker.finished.connect(self.on_data_update_finished); self.data_worker.error.connect(self.on_data_update_error); self.data_worker.start()
    def on_data_update_finished(self):
        QMessageBox.information(self, "알림", "데이터 업데이트가 성공적으로 완료되었습니다."); self.run_btn.setEnabled(True); self.update_btn.setEnabled(True); self.results_text.append("데이터 업데이트 완료.")
    def on_data_update_error(self, err_msg):
        QMessageBox.critical(self, "오류", f"데이터 업데이트 중 오류가 발생했습니다:\n{err_msg}"); self.run_btn.setEnabled(True); self.update_btn.setEnabled(True); self.results_text.append(f"오류: {err_msg}")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    try:
        app_font = QFont("NanumGothic", 10)
        app.setFont(app_font)
    except:
        print("나눔고딕 폰트 없음. 기본 폰트로 실행됩니다.")
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())