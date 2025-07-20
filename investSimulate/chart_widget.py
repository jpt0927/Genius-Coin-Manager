# chart_widget.py - WebSocket + matplotlib 전문 차트 (하이브리드)
import sys
import json
import websocket
import threading
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
import matplotlib.patches as patches
from PyQt5.QtWidgets import *
from PyQt5.QtCore import *
from PyQt5.QtGui import *
from binance.client import Client
import numpy as np
from datetime import datetime, timedelta
from collections import deque
import time
import platform

# 한글 폰트 설정
def setup_korean_font():
    """한글 폰트 설정 - 안전한 방식"""
    import matplotlib
    matplotlib.use('Qt5Agg')  # GUI 백엔드 설정을 먼저
    
    import matplotlib.pyplot as plt
    
    system = platform.system()
    
    if system == 'Darwin':  # macOS
        font_candidates = [
            'AppleGothic', 'Apple SD Gothic Neo', 'Nanum Gothic',
            'Malgun Gothic', 'DejaVu Sans'
        ]
    elif system == 'Windows':
        font_candidates = [
            'Malgun Gothic', 'Arial Unicode MS', 'Nanum Gothic',
            'DejaVu Sans'
        ]
    else:  # Linux
        font_candidates = [
            'Nanum Gothic', 'DejaVu Sans', 'Liberation Sans'
        ]
    
    for font_name in font_candidates:
        try:
            plt.rcParams['font.family'] = font_name
            plt.rcParams['axes.unicode_minus'] = False
            # 간단한 테스트 (Figure 생성하지 않고)
            print(f"한글 폰트 설정 시도: {font_name}")
            return True
        except Exception as e:
            print(f"폰트 {font_name} 설정 실패: {e}")
            continue
    
    print("한글 폰트를 찾을 수 없습니다. 기본 폰트를 사용합니다.")
    # 기본 설정
    try:
        plt.rcParams['font.family'] = 'DejaVu Sans'
        plt.rcParams['axes.unicode_minus'] = False
    except:
        pass
    return False

# 폰트 설정 실행
setup_korean_font()

class BinanceWebSocketManager:
    """바이낸스 WebSocket 관리자 - 하이브리드 방식"""
    
    def __init__(self, symbol, interval, callback, trading_engine):
        self.symbol = symbol.lower()
        self.interval = interval
        self.callback = callback
        self.trading_engine = trading_engine  # REST API 접근용
        self.ws = None
        self.running = False
        self.reconnect_count = 0
        self.max_reconnects = 10
        
        # 데이터 버퍼 (최대 1000개 캔들 유지)
        self.klines_buffer = deque(maxlen=1000)
        self.historical_loaded = False
        
    def start(self):
        """WebSocket 연결 시작 - 과거 데이터 먼저 로드"""
        self.running = True
        self.load_historical_data()
        self.connect()
        
    def load_historical_data(self):
        """REST API로 과거 데이터 로드"""
        try:
            print(f"=== 과거 데이터 로드 시작: {self.symbol.upper()} {self.interval} ===")
            
            # 시간대별 데이터 수량 설정
            limit_map = {
                "1m": 500,   # 500분 (약 8시간)
                "5m": 400,   # 2000분 (약 33시간)
                "15m": 200,  # 3000분 (약 50시간)
                "1h": 168,   # 168시간 (1주일)
                "4h": 180,   # 720시간 (30일)
                "1d": 100    # 100일
            }
            
            limit = limit_map.get(self.interval, 200)
            
            # 바이낸스 REST API로 과거 데이터 가져오기
            klines = self.trading_engine.client.get_klines(
                symbol=self.symbol.upper(),
                interval=self.interval,
                limit=limit
            )
            
            if klines:
                print(f"과거 데이터 {len(klines)}개 로드 완료")
                
                # 과거 데이터를 버퍼에 추가
                for kline in klines:
                    kline_data = {
                        'timestamp': pd.to_datetime(kline[0], unit='ms'),
                        'open': float(kline[1]),
                        'high': float(kline[2]),
                        'low': float(kline[3]),
                        'close': float(kline[4]),
                        'volume': float(kline[5]),
                        'is_closed': True  # 과거 데이터는 모두 완료된 캔들
                    }
                    self.klines_buffer.append(kline_data)
                
                self.historical_loaded = True
                print(f"=== 과거 데이터 버퍼 적재 완료: {len(self.klines_buffer)}개 ===")
                
                # 초기 차트 표시
                if self.callback:
                    self.callback(None, self.get_dataframe())
                    
            else:
                print("과거 데이터 로드 실패")
                
        except Exception as e:
            print(f"과거 데이터 로드 오류: {e}")
            import traceback
            traceback.print_exc()
        
    def connect(self):
        """WebSocket 연결"""
        try:
            stream_name = f"{self.symbol}@kline_{self.interval}"
            # 메인넷 WebSocket URL 사용 (테스트넷에서도 데이터 수신 가능)
            url = f"wss://stream.binance.com:9443/ws/{stream_name}"
            
            print(f"WebSocket 연결 중: {url}")
            
            self.ws = websocket.WebSocketApp(
                url,
                on_open=self.on_open,
                on_message=self.on_message,
                on_error=self.on_error,
                on_close=self.on_close
            )
            
            # 별도 스레드에서 실행
            self.ws_thread = threading.Thread(target=self.ws.run_forever)
            self.ws_thread.daemon = True
            self.ws_thread.start()
            
        except Exception as e:
            print(f"WebSocket 연결 오류: {e}")
            
    def on_open(self, ws):
        """연결 성공"""
        print(f"테스트넷 WebSocket 연결 성공: {self.symbol}@kline_{self.interval}")
        self.reconnect_count = 0
        
    def on_message(self, ws, message):
        """메시지 수신 - 실시간 데이터만 처리"""
        try:
            data = json.loads(message)
            
            if 'k' in data:  # kline 데이터
                kline = data['k']
                
                # 실시간 uiKlines 데이터 파싱
                kline_data = {
                    'timestamp': pd.to_datetime(kline['t'], unit='ms'),
                    'open': float(kline['o']),
                    'high': float(kline['h']),
                    'low': float(kline['l']),
                    'close': float(kline['c']),
                    'volume': float(kline['v']),
                    'is_closed': kline['x']  # 캔들 완료 여부
                }
                
                # 과거 데이터가 로드된 후에만 처리
                if self.historical_loaded:
                    # 버퍼에 추가/업데이트
                    self.update_buffer(kline_data)
                    
                    # 콜백 호출
                    if self.callback:
                        self.callback(kline_data, self.get_dataframe())
                else:
                    print("과거 데이터 로드 대기 중...")
                    
        except Exception as e:
            print(f"실시간 메시지 처리 오류: {e}")
            
    def update_buffer(self, kline_data):
        """데이터 버퍼 업데이트 - 하이브리드 방식"""
        timestamp = kline_data['timestamp']
        
        if not self.klines_buffer:
            # 버퍼가 비어있으면 그냥 추가
            self.klines_buffer.append(kline_data)
            return
            
        # 가장 최근 캔들과 비교
        last_candle = self.klines_buffer[-1]
        last_timestamp = last_candle['timestamp']
        
        if timestamp == last_timestamp:
            # 같은 시간대 - 현재 캔들 업데이트
            self.klines_buffer[-1] = kline_data
            print(f"현재 캔들 업데이트: {timestamp}")
        elif timestamp > last_timestamp:
            # 새로운 시간대 - 새 캔들 추가
            self.klines_buffer.append(kline_data)
            print(f"새 캔들 추가: {timestamp}")
        else:
            # 과거 시간대 - 무시 (이미 과거 데이터가 있음)
            print(f"과거 캔들 무시: {timestamp}")
            return
            
    def get_dataframe(self):
        """현재 버퍼를 DataFrame으로 변환"""
        if not self.klines_buffer:
            return None
            
        df = pd.DataFrame(list(self.klines_buffer))
        df.set_index('timestamp', inplace=True)
        return df
        
    def on_error(self, ws, error):
        """에러 처리"""
        print(f"WebSocket 에러: {error}")
        
    def on_close(self, ws, close_status_code, close_msg):
        """연결 종료"""
        print(f"WebSocket 연결 종료: {close_status_code} - {close_msg}")
        
        if self.running and self.reconnect_count < self.max_reconnects:
            print(f"재연결 시도 ({self.reconnect_count + 1}/{self.max_reconnects})")
            time.sleep(2 ** self.reconnect_count)  # 지수 백오프
            self.reconnect_count += 1
            self.connect()
            
    def stop(self):
        """WebSocket 연결 종료"""
        self.running = False
        if self.ws:
            self.ws.close()

class ProfessionalPlotlyChart(QWidget):
    """전문적인 Plotly 차트 위젯"""
    
    def __init__(self, trading_engine):
        super().__init__()
        self.trading_engine = trading_engine
        self.current_symbol = "BTCUSDT"
        self.current_interval = "1m"
        self.ws_manager = None
        self.df = None
        
        # 기술적 지표 설정
        self.indicators = {
            'ma7': True,
            'ma25': True,
            'ma99': True,
            'bollinger': False,
            'rsi': False
        }
        
        self.setup_ui()
        self.start_websocket()
        
    def setup_ui(self):
        """UI 설정"""
        layout = QVBoxLayout()
        
        # 제어 패널
        control_panel = self.create_control_panel()
        layout.addWidget(control_panel)
        
        # matplotlib 차트를 위한 FigureCanvas (적정 크기)
        from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
        from matplotlib.figure import Figure
        
        # Figure 초기화 시 DPI 명시적 설정 🔧
        self.figure = Figure(figsize=(16, 7), dpi=100, facecolor='#0d1421')  # DPI 추가
        self.canvas = FigureCanvas(self.figure)
        self.canvas.setMinimumHeight(450)  # 적정 높이
        
        # Figure의 DPI 확인 및 강제 설정
        if self.figure.dpi is None:
            self.figure.set_dpi(100)
        
        # matplotlib의 스레드 안전성을 위한 설정
        import matplotlib
        matplotlib.use('Qt5Agg')  # GUI 백엔드 명시적 설정
        
        # 마우스 이벤트 연결 (줌 기능)
        self.canvas.mpl_connect('scroll_event', self.on_scroll)
        self.canvas.mpl_connect('button_press_event', self.on_click)
        
        layout.addWidget(self.canvas)
        
        # 상태 표시
        self.status_label = QLabel("WebSocket 연결 중...")
        self.status_label.setStyleSheet("color: #ffd700; padding: 5px;")
        layout.addWidget(self.status_label)
        
        self.setLayout(layout)
        
        # 줌 상태 변수
        self.zoom_factor = 1.0
        self.manual_ylim = None
        
    def create_control_panel(self):
        """제어 패널 생성"""
        panel = QFrame()
        panel.setFixedHeight(80)
        panel.setStyleSheet("""
            QFrame {
                background-color: #1e1e1e;
                border: 1px solid #333;
                border-radius: 5px;
                margin: 5px;
            }
            QLabel {
                color: white;
                font-weight: bold;
                font-size: 12px;
            }
            QComboBox, QPushButton {
                background-color: #2d2d2d;
                color: white;
                border: 1px solid #555;
                border-radius: 3px;
                padding: 5px;
                min-width: 80px;
                font-size: 11px;
            }
            QComboBox::drop-down {
                border: none;
            }
            QPushButton {
                background-color: #0078d4;
            }
            QPushButton:hover {
                background-color: #106ebe;
            }
            QPushButton:checked {
                background-color: #00ff88;
                color: black;
            }
        """)
        
        layout = QGridLayout(panel)
        
        # 첫 번째 행: 심볼과 시간대
        row1_layout = QHBoxLayout()
        
        row1_layout.addWidget(QLabel("Symbol:"))
        self.symbol_combo = QComboBox()
        self.symbol_combo.addItems([
            "BTCUSDT", "ETHUSDT", "SOLUSDT"  # 3개 메이저 코인
        ])
        self.symbol_combo.setCurrentText(self.current_symbol)
        self.symbol_combo.currentTextChanged.connect(self.on_symbol_changed)
        row1_layout.addWidget(self.symbol_combo)
        
        row1_layout.addWidget(QLabel("   Timeframe:"))
        
        # 시간대 버튼들
        self.interval_buttons = {}
        intervals = [("1m", "1m"), ("5m", "5m"), ("15m", "15m"), ("1h", "1h"), ("4h", "4h"), ("1d", "1d")]
        
        for display, code in intervals:
            btn = QPushButton(display)
            btn.setCheckable(True)
            btn.clicked.connect(lambda checked, c=code: self.on_interval_changed(c))
            self.interval_buttons[code] = btn
            row1_layout.addWidget(btn)
            
        self.interval_buttons["1m"].setChecked(True)
        
        row1_layout.addStretch()
        layout.addLayout(row1_layout, 0, 0)
        
        # 두 번째 행: 지표 설정 및 줌 컨트롤
        row2_layout = QHBoxLayout()
        
        row2_layout.addWidget(QLabel("Indicators:"))
        
        # 지표 체크박스들
        self.indicator_checkboxes = {}
        indicators = [("MA7", "ma7"), ("MA25", "ma25"), ("MA99", "ma99"), ("Bollinger", "bollinger"), ("RSI", "rsi")]
        
        for display, code in indicators:
            cb = QCheckBox(display)
            cb.setChecked(self.indicators.get(code, False))
            cb.setStyleSheet("color: white; font-size: 11px;")
            cb.stateChanged.connect(lambda state, c=code: self.on_indicator_toggled(c, state))
            self.indicator_checkboxes[code] = cb
            row2_layout.addWidget(cb)
            
        # 줌 컨트롤 추가
        row2_layout.addWidget(QLabel("   Zoom:"))
        
        zoom_in_btn = QPushButton("🔍+")
        zoom_in_btn.setMaximumWidth(40)
        zoom_in_btn.clicked.connect(lambda: self.manual_zoom(0.8))
        row2_layout.addWidget(zoom_in_btn)
        
        zoom_out_btn = QPushButton("🔍-")
        zoom_out_btn.setMaximumWidth(40)
        zoom_out_btn.clicked.connect(lambda: self.manual_zoom(1.25))
        row2_layout.addWidget(zoom_out_btn)
        
        zoom_reset_btn = QPushButton("Reset")
        zoom_reset_btn.setMaximumWidth(50)
        zoom_reset_btn.clicked.connect(self.reset_zoom)
        row2_layout.addWidget(zoom_reset_btn)
        
        row2_layout.addStretch()
        
        # 연결 상태 표시
        self.connection_status = QLabel("●")
        self.connection_status.setStyleSheet("color: #ff4444; font-size: 14px;")
        row2_layout.addWidget(QLabel("Connection:"))
        row2_layout.addWidget(self.connection_status)
        
        layout.addLayout(row2_layout, 1, 0)
        
        return panel
        
    def on_symbol_changed(self, symbol):
        """심볼 변경"""
        if symbol != self.current_symbol:
            self.current_symbol = symbol
            self.restart_websocket()
            
    def on_interval_changed(self, interval):
        """시간대 변경"""
        # 다른 버튼들 체크 해제
        for btn in self.interval_buttons.values():
            btn.setChecked(False)
        self.interval_buttons[interval].setChecked(True)
        
        if interval != self.current_interval:
            self.current_interval = interval
            self.restart_websocket()
            
    def on_indicator_toggled(self, indicator, state):
        """지표 토글"""
        self.indicators[indicator] = state == 2  # Qt.Checked
        if self.df is not None:
            self.update_chart(self.df)
            
    def start_websocket(self):
        """WebSocket 시작 - trading_engine 전달"""
        if self.ws_manager:
            self.ws_manager.stop()
            
        self.ws_manager = BinanceWebSocketManager(
            self.current_symbol,
            self.current_interval,
            self.on_websocket_data,
            self.trading_engine  # REST API 접근을 위해 전달
        )
        self.ws_manager.start()
        
    def restart_websocket(self):
        """WebSocket 재시작"""
        self.status_label.setText(f"Switching to {self.current_symbol} {self.current_interval}...")
        self.connection_status.setStyleSheet("color: #ffd700; font-size: 14px;")
        self.start_websocket()
        
    def on_websocket_data(self, kline_data, df):
        """WebSocket 데이터 수신 - 하이브리드 방식"""
        try:
            if df is not None and len(df) > 0:
                self.df = df
                
                # 데이터 상태 로그 (과도한 로그 방지)
                if kline_data is None:
                    print(f"=== 초기 과거 데이터 로드 완료: {len(df)}개 캔들 ===")
                elif kline_data.get('is_closed', False):
                    print(f"=== 새 캔들 완료: {kline_data['timestamp']} ===")
                
                # 차트 업데이트
                self.update_chart(df)
                
                # 연결 상태 업데이트
                self.connection_status.setStyleSheet("color: #00ff88; font-size: 14px;")
                
                # 상태 정보 업데이트
                current_price = df['close'].iloc[-1]
                data_source = "Historical + Live" if len(df) > 10 else "Live Only"
                self.status_label.setText(
                    f"{data_source}: {self.current_symbol} - ${current_price:.4f} - "
                    f"{len(df)} candles - Last update: {datetime.now().strftime('%H:%M:%S')}"
                )
                
        except Exception as e:
            print(f"차트 업데이트 오류: {e}")
            import traceback
            traceback.print_exc()
            
    def calculate_indicators(self, df):
        """기술적 지표 계산"""
        indicators_data = {}
        
        if self.indicators['ma7'] and len(df) >= 7:
            indicators_data['MA7'] = df['close'].rolling(7).mean()
            
        if self.indicators['ma25'] and len(df) >= 25:
            indicators_data['MA25'] = df['close'].rolling(25).mean()
            
        if self.indicators['ma99'] and len(df) >= 99:
            indicators_data['MA99'] = df['close'].rolling(99).mean()
            
        if self.indicators['bollinger'] and len(df) >= 20:
            sma20 = df['close'].rolling(20).mean()
            std20 = df['close'].rolling(20).std()
            indicators_data['BB_Upper'] = sma20 + (std20 * 2)
            indicators_data['BB_Lower'] = sma20 - (std20 * 2)
            indicators_data['BB_Middle'] = sma20
            
        if self.indicators['rsi'] and len(df) >= 14:
            delta = df['close'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
            rs = gain / loss
            indicators_data['RSI'] = 100 - (100 / (1 + rs))
            
        return indicators_data
        
    def calculate_technical_indicators(self, df):
        """기술적 지표를 DataFrame에 직접 추가"""
        if self.indicators['ma7'] and len(df) >= 7:
            df['MA7'] = df['close'].rolling(7).mean()
            
        if self.indicators['ma25'] and len(df) >= 25:
            df['MA25'] = df['close'].rolling(25).mean()
            
        if self.indicators['ma99'] and len(df) >= 99:
            df['MA99'] = df['close'].rolling(99).mean()
            
        if self.indicators['bollinger'] and len(df) >= 20:
            sma20 = df['close'].rolling(20).mean()
            std20 = df['close'].rolling(20).std()
            df['BB_Upper'] = sma20 + (std20 * 2)
            df['BB_Lower'] = sma20 - (std20 * 2)
            df['BB_Middle'] = sma20
            
        if self.indicators['rsi'] and len(df) >= 14:
            delta = df['close'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
            rs = gain / loss
            df['RSI'] = 100 - (100 / (1 + rs))
            
    def draw_professional_candlesticks(self, ax, df):
        """전문적인 캔들스틱 그리기 - 크기 최적화 🚀"""
        from matplotlib.patches import Rectangle
        import matplotlib.patches as patches
        
        x_values = range(len(df))
        
        # 캔들 크기 최적화 🚀
        candle_count = len(df)
        
        # 시간대별 기본 폭 설정
        width_map = {
            "1m": 0.5,
            "5m": 0.6, 
            "15m": 0.7,
            "1h": 0.75,
            "4h": 0.8,
            "1d": 0.85
        }
        base_width = width_map.get(self.current_interval, 0.6)
        
        # 데이터 양에 따른 동적 조정
        if candle_count > 100:
            dynamic_factor = 0.4  # 많은 데이터일 때 더 좁게
        elif candle_count > 50:
            dynamic_factor = 0.6
        else:
            dynamic_factor = 0.8  # 적은 데이터일 때 더 넓게
            
        # 최종 캔들 폭 계산
        optimal_width = base_width * dynamic_factor
        optimal_width = max(0.2, min(0.9, optimal_width))  # 0.2~0.9 범위로 제한
        
        print(f"캔들 크기 최적화: {self.current_interval}, 수량: {candle_count}, 폭: {optimal_width:.2f}")
        
        for i, (idx, row) in enumerate(df.iterrows()):
            open_price = row['open']
            high_price = row['high']
            low_price = row['low']
            close_price = row['close']
            
            # 상승/하락 색상 결정
            is_bullish = close_price >= open_price
            body_color = '#02c076' if is_bullish else '#f84960'
            wick_color = body_color
            
            # 상하 심지 먼저 그리기 (캔들 뒤에 보이도록)
            ax.plot([i, i], [low_price, high_price], 
                   color=wick_color, linewidth=1.2, alpha=0.9, zorder=1)
            
            # 캔들 몸통 그리기 (최적화된 폭 사용) 🚀
            body_height = abs(close_price - open_price)
            body_bottom = min(open_price, close_price)
            
            # 도지 캔들 처리 (몸통이 매우 작은 경우)
            if body_height < (high_price - low_price) * 0.01:
                body_height = (high_price - low_price) * 0.01
                
            # 최적화된 캔들 폭 적용 🚀
            rect = Rectangle(
                (i - optimal_width/2, body_bottom), optimal_width, body_height,
                facecolor=body_color, edgecolor=body_color,
                alpha=0.95, linewidth=0.6, zorder=2
            )
            ax.add_patch(rect)
                   
    def draw_moving_averages(self, ax, df):
        """이동평균선 그리기"""
        x_values = range(len(df))
        
        if 'MA7' in df.columns and self.indicators['ma7']:
            ax.plot(x_values, df['MA7'], color='#ffd700', linewidth=1.5, alpha=0.8, label='MA(7)')
            
        if 'MA25' in df.columns and self.indicators['ma25']:
            ax.plot(x_values, df['MA25'], color='#ff6b6b', linewidth=1.5, alpha=0.8, label='MA(25)')
            
        if 'MA99' in df.columns and self.indicators['ma99']:
            ax.plot(x_values, df['MA99'], color='#4ecdc4', linewidth=1.5, alpha=0.8, label='MA(99)')
            
    def draw_bollinger_bands(self, ax, df):
        """볼린저 밴드 그리기"""
        if 'BB_Upper' in df.columns and 'BB_Lower' in df.columns:
            x_values = range(len(df))
            ax.plot(x_values, df['BB_Upper'], color='#adccff', linewidth=1, alpha=0.6)
            ax.plot(x_values, df['BB_Lower'], color='#adccff', linewidth=1, alpha=0.6)
            ax.fill_between(x_values, df['BB_Upper'], df['BB_Lower'], 
                           color='#adccff', alpha=0.1)
                           
    def draw_volume_chart(self, ax, df):
        """거래량 차트 그리기 - 캔들과 동일한 폭으로 최적화 🚀"""
        x_values = range(len(df))
        colors = ['#02c076' if row['close'] >= row['open'] else '#f84960' 
                 for _, row in df.iterrows()]
        
        # 캔들과 동일한 폭 계산 🚀
        candle_count = len(df)
        
        # 시간대별 기본 폭 설정
        width_map = {
            "1m": 0.5,
            "5m": 0.6, 
            "15m": 0.7,
            "1h": 0.75,
            "4h": 0.8,
            "1d": 0.85
        }
        base_width = width_map.get(self.current_interval, 0.6)
        
        # 데이터 양에 따른 동적 조정
        if candle_count > 100:
            dynamic_factor = 0.4
        elif candle_count > 50:
            dynamic_factor = 0.6
        else:
            dynamic_factor = 0.8
            
        # 최종 거래량 바 폭 계산
        optimal_width = base_width * dynamic_factor
        optimal_width = max(0.2, min(0.9, optimal_width))
        
        # 거래량 바 그리기 (캔들과 동일한 폭) 🚀
        bars = ax.bar(x_values, df['volume'], color=colors, alpha=0.7, 
                     width=optimal_width, linewidth=0)
        
        # 거래량 이동평균
        if len(df) >= 20:
            vol_ma = df['volume'].rolling(20).mean()
            ax.plot(x_values, vol_ma, color='#ffd700', linewidth=1.5, alpha=0.8)
            
    def draw_rsi_chart(self, ax, df):
        """RSI 차트 그리기"""
        if 'RSI' in df.columns:
            x_values = range(len(df))
            ax.plot(x_values, df['RSI'], color='#9966cc', linewidth=2)
            
            # 과매수/과매도 라인
            ax.axhline(y=70, color='#f84960', linestyle='--', alpha=0.7, linewidth=1)
            ax.axhline(y=30, color='#02c076', linestyle='--', alpha=0.7, linewidth=1)
            ax.axhline(y=50, color='#666666', linestyle='-', alpha=0.3, linewidth=0.5)
            
    def style_price_chart(self, ax, df, current_price, change, change_pct):
        """가격 차트 스타일링 - 증권사 HTS 스타일 (Q1~Q3 + 여백)"""
        # 배경색과 격자
        ax.set_facecolor('#0d1421')
        ax.grid(True, color='#1e2329', alpha=0.3, linewidth=0.5)
        ax.tick_params(colors='#8a8a8a', labelsize=9)
        
        # 테두리 색상
        for spine in ax.spines.values():
            spine.set_color('#1e2329')
            
        # 실제 데이터 범위 (항상 계산)
        actual_range = df['high'].max() - df['low'].min()
        
        # 수동 줌이 설정되어 있으면 그것을 사용
        if hasattr(self, 'manual_ylim') and self.manual_ylim is not None:
            ax.set_ylim(self.manual_ylim)
            used_range = self.manual_ylim[1] - self.manual_ylim[0]
        else:
            # 증권사 HTS 스타일: Q1~Q3 기반 범위 설정
            all_prices = []
            all_prices.extend(df['high'].tolist())
            all_prices.extend(df['low'].tolist())
            
            # Q1, Q3 계산 (25th, 75th percentile)
            import numpy as np
            q1 = np.percentile(all_prices, 25)
            q3 = np.percentile(all_prices, 75)
            iqr = q3 - q1
            
            # 실무 기준: Q1~Q3 + 적정 여백
            if iqr > 0:
                # IQR이 있는 경우: Q1~Q3 범위 + 20% 여백
                margin = iqr * 0.2
                price_low = q1 - margin
                price_high = q3 + margin
            else:
                # IQR이 0인 경우 (변동이 거의 없음): 현재가 기준 ±0.5% 범위
                margin = current_price * 0.005
                price_low = current_price - margin
                price_high = current_price + margin
            
            # 실제 데이터 범위와 비교하여 조정
            actual_low = df['low'].min()
            actual_high = df['high'].max()
            
            # Q1~Q3 범위가 실제 데이터를 너무 많이 잘라내지 않도록 보정
            if price_low > actual_low * 1.02:  # 실제 최저가보다 2% 이상 높으면
                price_low = actual_low * 0.99   # 실제 최저가 -1%로 조정
            if price_high < actual_high * 0.98:  # 실제 최고가보다 2% 이상 낮으면  
                price_high = actual_high * 1.01  # 실제 최고가 +1%로 조정
                
            ax.set_ylim(price_low, price_high)
            
            # 실제 사용된 범위 계산
            used_range = price_high - price_low
            
        ax.set_xlim(-0.5, len(df) - 0.5)
        
        # 제목과 정보 표시 (HTS 스타일)
        change_color = '#02c076' if change >= 0 else '#f84960'
        title_info = f"{self.current_symbol} • ${current_price:.4f}"
        change_info = f"{change:+.4f} ({change_pct:+.2f}%)"
        
        # 실제 데이터 범위 vs 표시 범위 정보
        range_info = f"Display Range: ${used_range:.2f} | Data Range: ${actual_range:.2f} • {self.current_interval}"
        
        ax.text(0.01, 0.98, title_info, transform=ax.transAxes, 
               fontsize=16, fontweight='bold', color='white', va='top')
        ax.text(0.01, 0.93, change_info, transform=ax.transAxes, 
               fontsize=12, color=change_color, va='top', fontweight='bold')
        ax.text(0.01, 0.88, range_info, transform=ax.transAxes, 
               fontsize=9, color='#8a8a8a', va='top')
        
        # 범례
        if any([self.indicators['ma7'], self.indicators['ma25'], self.indicators['ma99']]):
            legend = ax.legend(loc='upper right', fancybox=True, framealpha=0.1, 
                             fontsize=9, labelcolor='white')
            legend.get_frame().set_facecolor('#1e2329')
            
    def style_volume_chart(self, ax, df):
        """거래량 차트 스타일링"""
        ax.set_facecolor('#0d1421')
        ax.grid(True, color='#1e2329', alpha=0.3, linewidth=0.5)
        ax.tick_params(colors='#8a8a8a', labelsize=8)
        
        for spine in ax.spines.values():
            spine.set_color('#1e2329')
            
        ax.set_xlim(-0.5, len(df) - 0.5)
        ax.set_ylim(0, df['volume'].max() * 1.1)
        
        # 거래량 정보
        total_volume = df['volume'].iloc[-1]
        vol_info = f"Vol: {total_volume:.2f}"
        ax.text(0.01, 0.95, vol_info, transform=ax.transAxes, 
               fontsize=9, color='#b7bdc6', va='top')
               
    def style_rsi_chart(self, ax):
        """RSI 차트 스타일링"""
        ax.set_facecolor('#0d1421')
        ax.grid(True, color='#1e2329', alpha=0.3, linewidth=0.5)
        ax.tick_params(colors='#8a8a8a', labelsize=8)
        
        for spine in ax.spines.values():
            spine.set_color('#1e2329')
            
        ax.set_ylim(0, 100)
        ax.set_ylabel('RSI', color='#8a8a8a', fontsize=9)
        
        # RSI 구간 배경색
        ax.axhspan(70, 100, color='#f84960', alpha=0.1)
        ax.axhspan(0, 30, color='#02c076', alpha=0.1)
        
    def finalize_chart_layout(self, df):
        """차트 레이아웃 마무리"""
        # X축 시간 레이블 설정 (마지막 subplot에만)
        all_subplots = self.figure.get_axes()
        if all_subplots:
            last_ax = all_subplots[-1]
            
            # 시간 레이블 설정
            step = max(1, len(df) // 8)
            x_ticks = range(0, len(df), step)
            
            if self.current_interval in ['1s', '1m', '5m']:
                time_format = '%H:%M'
            elif self.current_interval in ['1h']:
                time_format = '%m/%d %H:%M'
            else:
                time_format = '%m/%d'
                
            x_labels = []
            for i in x_ticks:
                if i < len(df):
                    if hasattr(df.index[i], 'strftime'):
                        time_str = df.index[i].strftime(time_format)
                    else:
                        time_str = str(i)
                    x_labels.append(time_str)
                    
            last_ax.set_xticks(x_ticks)
            last_ax.set_xticklabels(x_labels, rotation=0, ha='center')
            
            # 다른 subplot들은 x축 레이블 숨김
            for ax in all_subplots[:-1]:
                ax.set_xticklabels([])
                
        # 전체 배경
        self.figure.patch.set_facecolor('#0d1421')
        
    def update_chart(self, df):
        """전문적인 matplotlib 차트 업데이트 - 스레드 안전성 강화"""
        try:
            if df is None or len(df) < 2:
                print(f"데이터 부족: df 길이 {len(df) if df is not None else 'None'}")
                return
            
            # matplotlib 스레드 안전성 확인
            if self.figure is None:
                print("Figure가 None입니다. 차트 초기화가 필요합니다.")
                return
            
            if self.figure.dpi is None:
                print("Figure DPI가 None입니다. 강제 설정합니다.")
                self.figure.set_dpi(100)
            
            # 데이터 필터링 - 이상치 제거
            df_filtered = self.filter_outliers(df)
            if df_filtered is None or len(df_filtered) < 2:
                print("필터링 후 데이터 부족")
                return
            
            # 데이터 디버깅 정보
            print(f"차트 업데이트: {len(df_filtered)}개 캔들, 가격 범위: {df_filtered['low'].min():.2f} - {df_filtered['high'].max():.2f}")
            print(f"최근 캔들: O:{df_filtered['open'].iloc[-1]:.2f}, H:{df_filtered['high'].iloc[-1]:.2f}, L:{df_filtered['low'].iloc[-1]:.2f}, C:{df_filtered['close'].iloc[-1]:.2f}")
                
            # 이동평균 계산
            self.calculate_technical_indicators(df_filtered)
            
            # Figure 클리어 (안전하게)
            try:
                self.figure.clear()
            except Exception as e:
                print(f"Figure 클리어 오류: {e}")
                return
            
            # 현재 가격과 변화율 계산
            current_price = df_filtered['close'].iloc[-1]
            prev_price = df_filtered['close'].iloc[-2] if len(df_filtered) > 1 else current_price
            change = current_price - prev_price
            change_pct = (change / prev_price) * 100 if prev_price != 0 else 0
            
            # RSI 표시 여부에 따른 서브플롯 구성
            has_rsi = self.indicators.get('rsi', False) and len(df_filtered) >= 14
            
            try:
                if has_rsi:
                    gs = self.figure.add_gridspec(4, 1, height_ratios=[3, 1, 1, 0.5], hspace=0.1)
                    ax_price = self.figure.add_subplot(gs[0])
                    ax_volume = self.figure.add_subplot(gs[1], sharex=ax_price)
                    ax_rsi = self.figure.add_subplot(gs[2], sharex=ax_price)
                else:
                    gs = self.figure.add_gridspec(3, 1, height_ratios=[3, 1, 0.3], hspace=0.1)
                    ax_price = self.figure.add_subplot(gs[0])
                    ax_volume = self.figure.add_subplot(gs[1], sharex=ax_price)
            except Exception as e:
                print(f"Subplot 생성 오류: {e}")
                return
                
            # 차트 요소들 그리기 (각각 try-catch로 보호)
            try:
                # 1. 전문적인 캔들스틱 차트
                self.draw_professional_candlesticks(ax_price, df_filtered)
            except Exception as e:
                print(f"캔들스틱 그리기 오류: {e}")
            
            try:
                # 2. 이동평균선들
                self.draw_moving_averages(ax_price, df_filtered)
            except Exception as e:
                print(f"이동평균 그리기 오류: {e}")
            
            try:
                # 3. 볼린저 밴드
                if self.indicators.get('bollinger', False):
                    self.draw_bollinger_bands(ax_price, df_filtered)
            except Exception as e:
                print(f"볼린저 밴드 그리기 오류: {e}")
            
            try:
                # 4. 거래량 차트
                self.draw_volume_chart(ax_volume, df_filtered)
            except Exception as e:
                print(f"거래량 차트 그리기 오류: {e}")
            
            try:
                # 5. RSI (선택사항)
                if has_rsi:
                    self.draw_rsi_chart(ax_rsi, df_filtered)
            except Exception as e:
                print(f"RSI 차트 그리기 오류: {e}")
            
            try:
                # 6. 가격 차트 스타일링
                self.style_price_chart(ax_price, df_filtered, current_price, change, change_pct)
            except Exception as e:
                print(f"가격 차트 스타일링 오류: {e}")
            
            try:
                # 7. 거래량 차트 스타일링
                self.style_volume_chart(ax_volume, df_filtered)
            except Exception as e:
                print(f"거래량 차트 스타일링 오류: {e}")
            
            try:
                # 8. RSI 차트 스타일링 (있는 경우)
                if has_rsi:
                    self.style_rsi_chart(ax_rsi)
            except Exception as e:
                print(f"RSI 차트 스타일링 오류: {e}")
            
            try:
                # 9. 전체 차트 설정
                self.finalize_chart_layout(df_filtered)
            except Exception as e:
                print(f"차트 레이아웃 마무리 오류: {e}")
            
            try:
                # Canvas 업데이트 (메인 스레드에서 안전하게)
                self.canvas.draw()
            except Exception as e:
                print(f"Canvas 그리기 오류: {e}")
                
        except Exception as e:
            print(f"matplotlib 차트 업데이트 전체 오류: {e}")
            import traceback
            traceback.print_exc()
            
    def filter_outliers(self, df):
        """최근 데이터 기반 필터링 및 Y축 범위 최적화 - 캔들 수 최적화 🚀"""
        try:
            # 시간 간격별 표시할 캔들 수 설정 (캔들 크기 고려)
            display_candles = {
                "1m": 80,    # 1시간 20분 (더 많이 표시)
                "5m": 90,    # 7.5시간 (더 많이 표시)
                "15m": 80,   # 20시간 (더 많이 표시)
                "1h": 60,    # 60시간 (2.5일)
                "4h": 50,    # 200시간 (8일)
                "1d": 40     # 40일
            }
            
            max_candles = display_candles.get(self.current_interval, 60)
            
            # 최근 데이터만 사용
            if len(df) > max_candles:
                df_recent = df.tail(max_candles).copy()
                print(f"캔들 수 최적화: {len(df)} -> {max_candles}개 ({self.current_interval})")
            else:
                df_recent = df.copy()
                
            # 추가적인 이상치 제거 (현재가 기준)
            current_price = df_recent['close'].iloc[-1]
            
            # 현재가의 ±5% 범위를 벗어나는 극단적 이상치만 제거 (실무 기준 강화)
            price_min = current_price * 0.95  # -5%
            price_max = current_price * 1.05  # +5%
            
            mask = (
                (df_recent['open'] >= price_min) & (df_recent['open'] <= price_max) &
                (df_recent['high'] >= price_min) & (df_recent['high'] <= price_max) &
                (df_recent['low'] >= price_min) & (df_recent['low'] <= price_max) &
                (df_recent['close'] >= price_min) & (df_recent['close'] <= price_max)
            )
            
            df_filtered = df_recent[mask].copy()
            
            # 추가 필터링이 있었다면 로그
            if len(df_filtered) < len(df_recent):
                print(f"이상치 제거: {len(df_recent)} -> {len(df_filtered)}개 캔들")
                
            return df_filtered
            
        except Exception as e:
            print(f"데이터 필터링 오류: {e}")
            return df
    def manual_zoom(self, factor):
        """수동 줌 조정"""
        if not hasattr(self, 'zoom_factor'):
            self.zoom_factor = 1.0
            
        self.zoom_factor *= factor
        self.zoom_factor = max(0.1, min(10.0, self.zoom_factor))
        
        if self.df is not None:
            # 현재 가격 차트의 축 가져오기
            axes = self.figure.get_axes()
            if axes:
                ax_price = axes[0]
                ylim = ax_price.get_ylim()
                center = (ylim[0] + ylim[1]) / 2
                
                # 새로운 범위 계산
                price_high = self.df['high'].max()
                price_low = self.df['low'].min()
                base_range = price_high - price_low
                new_range = base_range * self.zoom_factor
                
                self.manual_ylim = (center - new_range/2, center + new_range/2)
                self.update_chart(self.df)
                
    def reset_zoom(self):
        """줌 리셋"""
        self.zoom_factor = 1.0
        self.manual_ylim = None
        if self.df is not None:
            self.update_chart(self.df)

    def on_scroll(self, event):
        """마우스 휠 스크롤로 Y축 줌"""
        if event.inaxes is None:
            return
            
        # 가격 차트에서만 작동
        if event.inaxes == self.figure.get_axes()[0]:
            if event.button == 'up':
                # 확대
                self.zoom_factor *= 0.9
            elif event.button == 'down':
                # 축소
                self.zoom_factor *= 1.1
                
            # 줌 제한
            self.zoom_factor = max(0.1, min(10.0, self.zoom_factor))
            
            # 현재 Y축 범위 가져오기
            ylim = event.inaxes.get_ylim()
            center = (ylim[0] + ylim[1]) / 2
            height = (ylim[1] - ylim[0]) * self.zoom_factor
            
            # 새로운 Y축 범위 설정
            new_ylim = (center - height/2, center + height/2)
            self.manual_ylim = new_ylim
            event.inaxes.set_ylim(new_ylim)
            
            # 차트 업데이트
            self.canvas.draw()
            
    def on_click(self, event):
        """마우스 클릭으로 줌 리셋"""
        if event.dblclick and event.inaxes is not None:
            # 더블클릭으로 줌 리셋
            self.zoom_factor = 1.0
            self.manual_ylim = None
            if self.df is not None:
                self.update_chart(self.df)
                
    def closeEvent(self, event):
        """위젯 종료 시 WebSocket 정리"""
        if self.ws_manager:
            self.ws_manager.stop()
        event.accept()

# 기존 CandlestickChart 클래스를 새로운 것으로 교체
CandlestickChart = ProfessionalPlotlyChart

# 업데이트 스레드도 단순화
class ChartUpdateThread(QThread):

    # //정리하기
    update_signal = pyqtSignal()
    
    def __init__(self, chart_widget):
        super().__init__()
        self.chart_widget = chart_widget
        self.running = False
        
    def run(self):
        # WebSocket이 실시간 업데이트를 처리하므로 이 스레드는 비활성화
        pass
                
    def stop(self):
        self.running = False
        self.wait()
