# order_book_widget.py - matplotlib 기반 바이낸스 스타일 호가창
import sys
import json
import websocket
import threading
import time
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from PyQt5.QtWidgets import *
from PyQt5.QtCore import *
from PyQt5.QtGui import *
from datetime import datetime
from collections import OrderedDict
import platform

class BinanceOrderBookWebSocket:
    """바이낸스 호가창 WebSocket 관리자"""
    
    def __init__(self, symbol, callback):
        self.symbol = symbol.lower()
        self.callback = callback
        self.ws = None
        self.running = False
        self.reconnect_count = 0
        self.max_reconnects = 5
        
        # 호가 데이터 저장
        self.bids = OrderedDict()  # 매수호가 (가격: 수량)
        self.asks = OrderedDict()  # 매도호가 (가격: 수량)
        self.last_update_time = None
        
    def start(self):
        """WebSocket 연결 시작"""
        self.running = True
        self.connect()
        
    def connect(self):
        """WebSocket 연결"""
        try:
            # 바이낸스 실시간 호가창 WebSocket (20레벨, 100ms 업데이트)
            stream_name = f"{self.symbol}@depth20@100ms"
            url = f"wss://stream.binance.com:9443/ws/{stream_name}"
            
            print(f"호가창 WebSocket 연결 중: {url}")
            
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
            print(f"호가창 WebSocket 연결 오류: {e}")
            
    def on_open(self, ws):
        """연결 성공"""
        print(f"호가창 WebSocket 연결 성공: {self.symbol}")
        self.reconnect_count = 0
        
    def on_message(self, ws, message):
        """호가 데이터 수신"""
        try:
            data = json.loads(message)
            
            if 'bids' in data and 'asks' in data:
                # 호가 데이터 파싱
                self.bids.clear()
                self.asks.clear()
                
                # 매수호가 (bids) - 높은 가격순으로 정렬됨
                for bid in data['bids']:
                    price = float(bid[0])
                    quantity = float(bid[1])
                    if quantity > 0:  # 수량이 0보다 큰 것만
                        self.bids[price] = quantity
                
                # 매도호가 (asks) - 낮은 가격순으로 정렬됨
                for ask in data['asks']:
                    price = float(ask[0])
                    quantity = float(ask[1])
                    if quantity > 0:  # 수량이 0보다 큰 것만
                        self.asks[price] = quantity
                
                self.last_update_time = datetime.now()
                
                # 콜백 호출 (UI 업데이트)
                if self.callback:
                    self.callback(self.bids, self.asks)
                    
        except Exception as e:
            print(f"호가 데이터 처리 오류: {e}")
            
    def on_error(self, ws, error):
        """에러 처리"""
        print(f"호가창 WebSocket 에러: {error}")
        
    def on_close(self, ws, close_status_code, close_msg):
        """연결 종료"""
        print(f"호가창 WebSocket 연결 종료: {close_status_code}")
        
        if self.running and self.reconnect_count < self.max_reconnects:
            print(f"호가창 재연결 시도 ({self.reconnect_count + 1}/{self.max_reconnects})")
            time.sleep(2 ** self.reconnect_count)  # 지수 백오프
            self.reconnect_count += 1
            self.connect()
            
    def stop(self):
        """WebSocket 연결 종료"""
        self.running = False
        if self.ws:
            self.ws.close()

class MatplotlibOrderBook(QWidget):
    """matplotlib 기반 바이낸스 스타일 호가창 - 최적화 버전"""
    
    # 가격 클릭 시그널 추가 🚀
    price_clicked = pyqtSignal(float)
    
    def __init__(self, trading_engine):
        super().__init__()
        self.trading_engine = trading_engine
        self.current_symbol = "BTCUSDT"
        self.ws_manager = None
        
        # 현재 가격 (차트와 동기화용)
        self.current_price = 0
        
        # 호가 데이터
        self.bids = OrderedDict()
        self.asks = OrderedDict()
        
        # 클릭 처리를 위한 가격 영역 저장
        self.price_regions = []  # [(y_start, y_end, price), ...]
        
        # matplotlib 최적화를 위한 객체 캐싱 🚀
        self.ax = None
        self.text_objects = {
            'ask_prices': [],
            'ask_quantities': [],
            'ask_totals': [],
            'bid_prices': [],
            'bid_quantities': [],
            'bid_totals': [],
            'current_price': None,
            'spread_info': None,
            'headers': []
        }
        self.background_patches = {
            'ask_backgrounds': [],
            'bid_backgrounds': [],
            'ask_bars': [],
            'bid_bars': []
        }
        self.chart_initialized = False
        
        # 업데이트 최적화
        self.last_render_time = 0
        self.render_interval = 0.2  # 200ms마다 한 번만 렌더링
        
        # UI 설정
        self.setup_ui()
        self.start_websocket()
        
    def setup_ui(self):
        """UI 설정"""
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # 헤더 (호가창 제목)
        header = self.create_header()
        layout.addWidget(header)
        
        # matplotlib 호가창
        self.figure = Figure(figsize=(4, 10), facecolor='#0d1421')
        self.canvas = FigureCanvas(self.figure)
        self.canvas.setMinimumWidth(300)
        self.canvas.setMinimumHeight(600)
        
        # 마우스 클릭 이벤트 연결 🚀
        self.canvas.mpl_connect('button_press_event', self.on_canvas_click)
        
        layout.addWidget(self.canvas)
        
        # 상태 표시
        self.status_label = QLabel("호가창 연결 중...")
        self.status_label.setStyleSheet("""
            color: #ffd700; 
            padding: 3px; 
            font-size: 10px;
            background-color: #1e2329;
        """)
        layout.addWidget(self.status_label)
        
        self.setLayout(layout)
        
    def create_header(self):
        """호가창 헤더 생성"""
        header = QFrame()
        header.setFixedHeight(35)
        header.setStyleSheet("""
            QFrame {
                background-color: #1e2329;
                border-bottom: 1px solid #2b3139;
            }
            QLabel {
                color: #f0f0f0;
                font-weight: bold;
                font-size: 12px;
            }
        """)
        
        layout = QHBoxLayout(header)
        layout.setContentsMargins(10, 5, 10, 5)
        
        # 제목
        title_label = QLabel("📊 호가창 (Order Book)")
        layout.addWidget(title_label)
        
        layout.addStretch()
        
        # 호가 레벨 표시
        level_label = QLabel("20단계")
        level_label.setStyleSheet("color: #8a8a8a; font-size: 10px;")
        layout.addWidget(level_label)
        
        return header
        
    def start_websocket(self):
        """WebSocket 시작"""
        if self.ws_manager:
            self.ws_manager.stop()
            
        self.ws_manager = BinanceOrderBookWebSocket(
            self.current_symbol,
            self.on_orderbook_data
        )
        self.ws_manager.start()
        
    def on_orderbook_data(self, bids, asks):
        """호가 데이터 수신 콜백 - 렌더링 최적화 적용 🚀"""
        try:
            self.bids = bids
            self.asks = asks
            
            # 현재가 계산 (중간값)
            if bids and asks:
                best_bid = max(bids.keys())  # 최고 매수가
                best_ask = min(asks.keys())  # 최저 매도가
                self.current_price = (best_bid + best_ask) / 2
            
            # 렌더링 주기 제한 (200ms) 🚀
            import time
            current_time = time.time()
            if current_time - self.last_render_time >= self.render_interval:
                self.smart_update_orderbook()
                self.last_render_time = current_time
            
            # 상태 업데이트 (항상)
            self.status_label.setText(
                f"실시간: {datetime.now().strftime('%H:%M:%S')} | "
                f"매수:{len(bids)} 매도:{len(asks)}"
            )
            
        except Exception as e:
            print(f"호가창 데이터 처리 오류: {e}")
            
    def initialize_chart_objects(self):
        """차트 객체들을 한 번만 초기화 🚀"""
        try:
            if self.chart_initialized:
                return
                
            # Figure 설정
            if self.ax is None:
                self.ax = self.figure.add_subplot(111)
                self.ax.set_facecolor('#0d1421')
                self.ax.set_xlim(0, 10)
                self.ax.set_ylim(0, 50)
                self.ax.axis('off')
            
            # 헤더 텍스트 생성 (한 번만)
            if not self.text_objects['headers']:
                self.text_objects['headers'] = [
                    self.ax.text(1, 48, "가격(USDT)", fontsize=10, color='#8a8a8a', weight='bold', ha='left'),
                    self.ax.text(5, 48, "수량(BTC)", fontsize=10, color='#8a8a8a', weight='bold', ha='center'),
                    self.ax.text(8.5, 48, "총액", fontsize=10, color='#8a8a8a', weight='bold', ha='right')
                ]
            
            # 호가 라인용 텍스트 객체들 생성 (매도 15개 + 매수 15개)
            y_positions_ask = [46 - i * 1.3 for i in range(15)]  # 상단 15개
            y_positions_bid = [20 - i * 1.3 for i in range(15)]  # 하단 15개
            
            # 매도호가 텍스트 객체들
            for y_pos in y_positions_ask:
                price_text = self.ax.text(1, y_pos, "", fontsize=9, color='#f84960', weight='bold', ha='left', va='center')
                qty_text = self.ax.text(5, y_pos, "", fontsize=9, color='#f0f0f0', ha='center', va='center')
                total_text = self.ax.text(8.5, y_pos, "", fontsize=8, color='#8a8a8a', ha='right', va='center')
                
                self.text_objects['ask_prices'].append(price_text)
                self.text_objects['ask_quantities'].append(qty_text)
                self.text_objects['ask_totals'].append(total_text)
                
                # 배경 패치
                bg_patch = plt.Rectangle((0.2, y_pos-0.8), 9.6, 1.5, facecolor='#2a1a1a', alpha=0.3)
                bar_patch = plt.Rectangle((9.8, y_pos-0.8), 0, 1.5, facecolor='#f84960', alpha=0.15)
                
                self.ax.add_patch(bg_patch)
                self.ax.add_patch(bar_patch)
                
                self.background_patches['ask_backgrounds'].append(bg_patch)
                self.background_patches['ask_bars'].append(bar_patch)
            
            # 매수호가 텍스트 객체들
            for y_pos in y_positions_bid:
                price_text = self.ax.text(1, y_pos, "", fontsize=9, color='#02c076', weight='bold', ha='left', va='center')
                qty_text = self.ax.text(5, y_pos, "", fontsize=9, color='#f0f0f0', ha='center', va='center')
                total_text = self.ax.text(8.5, y_pos, "", fontsize=8, color='#8a8a8a', ha='right', va='center')
                
                self.text_objects['bid_prices'].append(price_text)
                self.text_objects['bid_quantities'].append(qty_text)
                self.text_objects['bid_totals'].append(total_text)
                
                # 배경 패치
                bg_patch = plt.Rectangle((0.2, y_pos-0.8), 9.6, 1.5, facecolor='#1a2a1a', alpha=0.3)
                bar_patch = plt.Rectangle((9.8, y_pos-0.8), 0, 1.5, facecolor='#02c076', alpha=0.15)
                
                self.ax.add_patch(bg_patch)
                self.ax.add_patch(bar_patch)
                
                self.background_patches['bid_backgrounds'].append(bg_patch)
                self.background_patches['bid_bars'].append(bar_patch)
            
            # 현재가 라인 생성
            self.current_price_line = self.ax.axhline(y=25, color='#f0b90b', linewidth=2, alpha=0.8)
            
            # 현재가/스프레드 텍스트
            self.text_objects['current_price'] = self.ax.text(5, 26, "", fontsize=12, color='#f0b90b', 
                                                            weight='bold', ha='center', va='center')
            self.text_objects['spread_info'] = self.ax.text(5, 24, "", fontsize=8, color='#8a8a8a', 
                                                          ha='center', va='center')
            
            self.chart_initialized = True
            print("차트 객체 초기화 완료 🚀")
            
        except Exception as e:
            print(f"차트 초기화 오류: {e}")
            import traceback
            traceback.print_exc()

    def smart_update_orderbook(self):
        """스마트 호가창 업데이트 - figure.clear() 없이 🚀"""
        try:
            # 차트 객체가 초기화되지 않았으면 초기화
            if not self.chart_initialized:
                self.initialize_chart_objects()
            
            # 클릭 영역 초기화
            self.price_regions.clear()
            
            # 확장된 호가 데이터 생성
            extended_asks, extended_bids = self.generate_extended_orderbook()
            
            # 매도호가 업데이트 (상단)
            if extended_asks:
                ask_prices = sorted(extended_asks.keys())[:15]
                ask_prices.reverse()  # 높은 가격이 위에
                
                # 수량 최대값 계산 (바 차트용)
                max_ask_qty = max(extended_asks.values()) if extended_asks else 1
                
                for i, price in enumerate(ask_prices):
                    if i >= len(self.text_objects['ask_prices']):
                        break
                        
                    quantity = extended_asks[price]
                    total = price * quantity
                    
                    # 텍스트만 업데이트 (객체 재사용) 🚀
                    self.text_objects['ask_prices'][i].set_text(f"{price:,.2f}")
                    self.text_objects['ask_quantities'][i].set_text(f"{quantity:.6f}")
                    self.text_objects['ask_totals'][i].set_text(f"${total:,.0f}")
                    
                    # 바 차트 업데이트
                    bar_width = (quantity / max_ask_qty) * 4 if max_ask_qty > 0 else 0
                    bar_patch = self.background_patches['ask_bars'][i]
                    bar_patch.set_width(bar_width)
                    bar_patch.set_x(9.8 - bar_width)
                    
                    # 클릭 영역 저장
                    y_pos = 46 - i * 1.3
                    self.price_regions.append((y_pos-0.8, y_pos+0.7, price))
                
                # 나머지 라인 비우기
                for i in range(len(ask_prices), len(self.text_objects['ask_prices'])):
                    self.text_objects['ask_prices'][i].set_text("")
                    self.text_objects['ask_quantities'][i].set_text("")
                    self.text_objects['ask_totals'][i].set_text("")
                    self.background_patches['ask_bars'][i].set_width(0)
            
            # 매수호가 업데이트 (하단)
            if extended_bids:
                bid_prices = sorted(extended_bids.keys(), reverse=True)[:15]
                
                # 수량 최대값 계산 (바 차트용)
                max_bid_qty = max(extended_bids.values()) if extended_bids else 1
                
                for i, price in enumerate(bid_prices):
                    if i >= len(self.text_objects['bid_prices']):
                        break
                        
                    quantity = extended_bids[price]
                    total = price * quantity
                    
                    # 텍스트만 업데이트 (객체 재사용) 🚀
                    self.text_objects['bid_prices'][i].set_text(f"{price:,.2f}")
                    self.text_objects['bid_quantities'][i].set_text(f"{quantity:.6f}")
                    self.text_objects['bid_totals'][i].set_text(f"${total:,.0f}")
                    
                    # 바 차트 업데이트
                    bar_width = (quantity / max_bid_qty) * 4 if max_bid_qty > 0 else 0
                    bar_patch = self.background_patches['bid_bars'][i]
                    bar_patch.set_width(bar_width)
                    bar_patch.set_x(9.8 - bar_width)
                    
                    # 클릭 영역 저장
                    y_pos = 20 - i * 1.3
                    self.price_regions.append((y_pos-0.8, y_pos+0.7, price))
                
                # 나머지 라인 비우기
                for i in range(len(bid_prices), len(self.text_objects['bid_prices'])):
                    self.text_objects['bid_prices'][i].set_text("")
                    self.text_objects['bid_quantities'][i].set_text("")
                    self.text_objects['bid_totals'][i].set_text("")
                    self.background_patches['bid_bars'][i].set_width(0)
            
            # 현재가 정보 업데이트
            if self.current_price > 0:
                if self.bids and self.asks:
                    best_bid = max(self.bids.keys())
                    best_ask = min(self.asks.keys())
                    spread = best_ask - best_bid
                    spread_pct = (spread / self.current_price) * 100
                    
                    current_text = f"${self.current_price:,.2f}"
                    spread_text = f"스프레드: ${spread:.2f} ({spread_pct:.3f}%)"
                else:
                    current_text = f"${self.current_price:,.2f}"
                    spread_text = "스프레드: -"
                
                # 현재가 텍스트 업데이트 🚀
                self.text_objects['current_price'].set_text(current_text)
                self.text_objects['spread_info'].set_text(spread_text)
            
            # 효율적인 렌더링 (draw_idle 사용) 🚀
            self.canvas.draw_idle()
            
        except Exception as e:
            print(f"스마트 호가창 업데이트 오류: {e}")
            import traceback
            traceback.print_exc()
            
    def generate_extended_orderbook(self):
        """호가 범위 확장 - 현재가 기준 ±1% 범위"""
        extended_asks = OrderedDict()
        extended_bids = OrderedDict()
        
        if not self.current_price or self.current_price <= 0:
            return self.asks, self.bids
        
        try:
            # 가격 범위 설정 (현재가 ±1%)
            price_range_pct = 0.01  # 1%
            min_price = self.current_price * (1 - price_range_pct)
            max_price = self.current_price * (1 + price_range_pct)
            
            # 가격 단위 설정 (현재가에 따라 적절한 단위)
            if self.current_price > 100000:
                price_step = 1.0  # $1 단위
            elif self.current_price > 10000:
                price_step = 0.5  # $0.5 단위
            elif self.current_price > 1000:
                price_step = 0.1  # $0.1 단위
            else:
                price_step = 0.01  # $0.01 단위
            
            # 실제 호가 데이터 먼저 추가
            for price, quantity in self.asks.items():
                if min_price <= price <= max_price:
                    extended_asks[price] = quantity
                    
            for price, quantity in self.bids.items():
                if min_price <= price <= max_price:
                    extended_bids[price] = quantity
            
            # 빈 가격대 채우기 (시뮬레이션 데이터)
            current_price_int = int(self.current_price / price_step) * price_step
            
            # 매도호가 확장 (현재가 위쪽)
            for i in range(1, 50):  # 최대 50개 가격대
                price = current_price_int + (i * price_step)
                if price > max_price:
                    break
                if price not in extended_asks:
                    # 시뮬레이션 수량 (가격이 높을수록 적게)
                    sim_quantity = 0.001 + (0.01 / i)
                    extended_asks[price] = sim_quantity
            
            # 매수호가 확장 (현재가 아래쪽)
            for i in range(1, 50):  # 최대 50개 가격대
                price = current_price_int - (i * price_step)
                if price < min_price:
                    break
                if price not in extended_bids:
                    # 시뮬레이션 수량 (가격이 낮을수록 적게)
                    sim_quantity = 0.001 + (0.01 / i)
                    extended_bids[price] = sim_quantity
            
            return extended_asks, extended_bids
            
        except Exception as e:
            print(f"호가 범위 확장 오류: {e}")
            return self.asks, self.bids
    
    def on_canvas_click(self, event):
        """호가창 클릭 이벤트 처리 🚀"""
        try:
            if event.inaxes is None or event.ydata is None:
                return
            
            # 클릭한 Y좌표
            click_y = event.ydata
            
            # 클릭한 위치의 가격 찾기
            for y_start, y_end, price in self.price_regions:
                if y_start <= click_y <= y_end:
                    print(f"호가창 클릭: 가격 ${price:.2f}")
                    # 시그널 발송하여 주문창에 가격 전달
                    self.price_clicked.emit(price)
                    break
                    
        except Exception as e:
            print(f"호가창 클릭 처리 오류: {e}")
            
    def set_symbol(self, symbol):
        """심볼 변경"""
        if symbol != self.current_symbol:
            self.current_symbol = symbol
            self.status_label.setText(f"심볼 변경: {symbol} 호가창 연결 중...")
            self.start_websocket()
            
    def closeEvent(self, event):
        """위젯 종료 시 WebSocket 정리"""
        if self.ws_manager:
            self.ws_manager.stop()
        super().closeEvent(event)
