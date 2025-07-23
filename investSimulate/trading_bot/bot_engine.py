# bot_engine.py - 트레이딩봇 메인 엔진
import logging
import time
import threading
from datetime import datetime
from typing import Dict, Any, Optional, Callable
from PyQt5.QtCore import QObject, pyqtSignal

from .bot_config import BotConfig, BotStatus
from .risk_manager import RiskManager
from .strategies.ma_cross_strategy import MACrossStrategy
from .strategies.base_strategy import TradingSignal

class TradingBot(QObject):
    """트레이딩봇 메인 엔진"""
    
    # PyQt 시그널 정의 (GUI 업데이트용)
    signal_generated = pyqtSignal(object)  # 신호 발생
    trade_executed = pyqtSignal(object)    # 거래 실행
    status_changed = pyqtSignal(str)       # 상태 변경
    error_occurred = pyqtSignal(str)       # 에러 발생
    
    def __init__(self, config: BotConfig, trading_engine):
        super().__init__()
        self.config = config
        self.trading_engine = trading_engine
        self.logger = logging.getLogger(__name__)
        
        # 컴포넌트 초기화
        self.status = BotStatus()
        self.risk_manager = RiskManager(config)
        
        # 🔥 실제 보유 포지션과 동기화
        self._sync_positions_with_portfolio()
        
        self.strategy = self._create_strategy()
        
        # 봇 상태
        self.running = False
        self.thread = None
        self.last_data_update = None
        
        self.logger.info(f"트레이딩봇 초기화 완료: {config.bot_name}")
    
    def _create_strategy(self):
        """설정에 따른 전략 생성"""
        try:
            if self.config.strategy_name == "ma_cross":
                return MACrossStrategy(self.config)
            else:
                raise ValueError(f"지원하지 않는 전략: {self.config.strategy_name}")
        except Exception as e:
            self.logger.error(f"전략 생성 오류: {e}")
            raise
    
    def start(self) -> tuple[bool, str]:
        """봇 시작"""
        try:
            # 설정 검증
            is_valid, validation_msg = self.config.validate()
            if not is_valid:
                return False, f"설정 오류: {validation_msg}"
            
            # 이미 실행 중인지 확인
            if self.running:
                return False, "봇이 이미 실행 중입니다"
            
            # 거래 가능 여부 확인
            should_pause, pause_reason = self.risk_manager.should_pause_trading()
            if should_pause:
                return False, f"거래 불가: {pause_reason}"
            
            # 봇 시작
            self.running = True
            self.status.start()
            
            # 🔥 시작 전 포지션 재동기화
            self._sync_positions_with_portfolio()
            
            # 별도 스레드에서 실행
            self.thread = threading.Thread(target=self._run_loop, daemon=True)
            self.thread.start()
            
            self.status_changed.emit("running")
            self.logger.info("트레이딩봇 시작됨")
            
            return True, "트레이딩봇이 시작되었습니다"
            
        except Exception as e:
            error_msg = f"봇 시작 오류: {e}"
            self.logger.error(error_msg)
            self.status.set_error(error_msg)
            self.error_occurred.emit(error_msg)
            return False, error_msg
    
    def stop(self) -> tuple[bool, str]:
        """봇 정지"""
        try:
            if not self.running:
                return False, "봇이 실행 중이 아닙니다"
            
            self.running = False
            self.status.stop()
            
            # 스레드 종료 대기
            if self.thread and self.thread.is_alive():
                self.thread.join(timeout=5.0)
            
            self.status_changed.emit("stopped")
            self.logger.info("트레이딩봇 정지됨")
            
            return True, "트레이딩봇이 정지되었습니다"
            
        except Exception as e:
            error_msg = f"봇 정지 오류: {e}"
            self.logger.error(error_msg)
            return False, error_msg
    
    def _run_loop(self):
        """봇 메인 실행 루프"""
        self.logger.info("봇 실행 루프 시작")
        
        while self.running:
            try:
                # 일시정지 상태 확인
                if self.status.status == BotStatus.PAUSED:
                    time.sleep(1)
                    continue
                
                # 리스크 확인
                should_pause, pause_reason = self.risk_manager.should_pause_trading()
                if should_pause:
                    self.pause(pause_reason)
                    continue
                
                # 가격 데이터 업데이트 및 신호 확인
                self._check_signals()
                
                # 1초 대기 (더 빠른 반응을 위해 5초에서 1초로 단축)
                time.sleep(1)
                
            except Exception as e:
                self.logger.error(f"봇 실행 루프 오류: {e}")
                self.status.set_error(str(e))
                self.error_occurred.emit(str(e))
                time.sleep(10)  # 오류 시 10초 대기
        
        self.logger.info("봇 실행 루프 종료")
    
    def _check_signals(self):
        """신호 확인 및 처리"""
        try:
            # 현재 가격 데이터 가져오기
            current_prices = getattr(self.trading_engine, 'current_prices', {})
            if not current_prices or self.config.symbol not in current_prices:
                self.logger.debug("가격 데이터 없음")
                return
            
            # 차트 데이터 가져오기 (5분봉)
            chart_data = self._get_chart_data()
            if chart_data is None or len(chart_data) < 30:
                self.logger.debug("차트 데이터 부족")
                return
            
            # 전략으로부터 신호 생성
            signal = self.strategy.get_signal(chart_data)
            
            if signal.action != TradingSignal.HOLD:
                self.logger.info(f"신호 감지: {signal}")
                self.signal_generated.emit(signal.to_dict())
                
                # 신호에 따른 거래 실행
                self._execute_trade(signal)
            
        except Exception as e:
            self.logger.error(f"신호 확인 오류: {e}")
    
    def _get_chart_data(self):
        """차트 데이터 가져오기"""
        try:
            # 바이낸스 클라이언트에서 1분봉 데이터 가져오기 (더 빠른 반응)
            klines = self.trading_engine.client.get_klines(
                symbol=self.config.symbol,
                interval="1m",  # 1분봉으로 변경 (5분봉에서 변경)
                limit=50  # 50개로 줄임 (100개에서 50개로)
            )
            
            if not klines:
                return None
            
            # DataFrame으로 변환
            import pandas as pd
            df = pd.DataFrame(klines, columns=[
                'timestamp', 'open', 'high', 'low', 'close', 'volume',
                'close_time', 'quote_asset_volume', 'number_of_trades',
                'taker_buy_base_asset_volume', 'taker_buy_quote_asset_volume', 'ignore'
            ])
            
            # 데이터 타입 변환
            for col in ['open', 'high', 'low', 'close', 'volume']:
                df[col] = pd.to_numeric(df[col], errors='coerce')
            
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            df.set_index('timestamp', inplace=True)
            
            return df[['open', 'high', 'low', 'close', 'volume']]
            
        except Exception as e:
            self.logger.error(f"차트 데이터 조회 오류: {e}")
            return None
    
    def _execute_trade(self, signal: TradingSignal):
        """거래 실행"""
        try:
            symbol = self.config.symbol
            action = signal.action
            signal_strength = signal.strength
            price = signal.price
            
            # 거래 금액 계산
            base_amount = self.config.base_amount
            trade_amount = self.risk_manager.calculate_position_size(signal_strength, base_amount)
            
            # 리스크 확인
            allowed, risk_msg = self.risk_manager.check_trading_allowed(symbol, action, trade_amount)
            if not allowed:
                self.logger.warning(f"🚫 거래 차단: {risk_msg}")
                return
            
            self.logger.info(f"✅ 거래 허용: {action} {symbol} ${trade_amount:.2f}")
            
            # 실제 거래 실행
            if action == TradingSignal.BUY:
                self.logger.info(f"🔄 매수 주문 실행 중: {symbol} ${trade_amount:.2f}")
                success, message = self.trading_engine.place_buy_order(symbol, amount_usd=trade_amount)
            elif action == TradingSignal.SELL:
                self.logger.info(f"🔄 매도 주문 실행 중: {symbol} 전량 매도")
                # 보유 수량 확인 후 전량 매도
                success, message = self.trading_engine.place_sell_order(symbol, sell_all=True)
            else:
                self.logger.warning(f"⚠️ 알 수 없는 거래 액션: {action}")
                return
            
            # 거래 결과 처리
            self.logger.info(f"💼 거래 결과: {action} {symbol} - Success: {success}, Message: {message}")
            
            if success:
                # 🔥 실제 포트폴리오 데이터로 정확한 손익 계산 (GUI와 동일한 방식)
                pnl = 0.0
                try:
                    coin_symbol = symbol.replace('USDT', '')  # BTCUSDT -> BTC
                    
                    if action == "SELL":
                        # 매도시: GUI와 동일한 방식으로 실제 손익 계산
                        # 현재 보유량 조회
                        quantity = self.trading_engine.portfolio.get_holding_quantity(symbol)
                        
                        if quantity > 0:
                            # 평균 매수가 계산 (봇 자체 거래 내역 기반)
                            avg_price = self._calculate_avg_buy_price(coin_symbol)
                            
                            # 매도 수량 계산
                            sell_quantity = min(quantity, trade_amount / price)
                            
                            # 실제 손익 = (현재가 - 평균매수가) × 매도수량
                            if avg_price > 0:
                                pnl = (price - avg_price) * sell_quantity
                                self.logger.info(f"💰 실제 매도 손익: ({price:.2f} - {avg_price:.2f}) × {sell_quantity:.4f} = ${pnl:+.2f}")
                                self.logger.info(f"매도 세부사항: 평균매수가=${avg_price:.2f}, 매도가=${price:.2f}, 수량={sell_quantity:.4f}")
                            else:
                                # 평균가 데이터가 없으면 웹소켓 기준 추정
                                pnl = trade_amount * 0.01  # 1% 추정 수익
                                self.logger.warning(f"⚠️ 평균매수가 데이터 없음, 추정 손익: ${pnl:+.2f}")
                        else:
                            self.logger.warning(f"⚠️ 매도할 {coin_symbol} 보유량이 없음")
                            
                    else:
                        # 매수시: 수수료만 차감
                        pnl = -trade_amount * 0.001  # 0.1% 수수료
                        self.logger.info(f"💳 매수 수수료: ${pnl:+.2f}")
                        
                except Exception as e:
                    self.logger.error(f"❌ 실제 손익 계산 오류: {e}")
                    pnl = 0.0
                
                # 리스크 매니저에 기록
                self.risk_manager.record_trade(
                    symbol=symbol,
                    action=action,
                    amount=trade_amount,
                    price=price,
                    pnl=pnl,
                    strategy=self.config.strategy_name
                )
                
                # 봇 상태 업데이트
                self.status.last_signal_time = datetime.now()
                
                # GUI에 알림
                trade_info = {
                    'timestamp': datetime.now().isoformat(),
                    'symbol': symbol,
                    'action': action,
                    'amount': trade_amount,
                    'price': price,
                    'signal_strength': signal_strength,
                    'reason': signal.reason,
                    'success': True,
                    'message': message
                }
                self.trade_executed.emit(trade_info)
                
                self.logger.info(f"🤖 봇 거래 기록 완료: {action} {symbol} ${trade_amount:.2f} @${price:.4f}")
                
                # GUI 즉시 업데이트 요청
                if hasattr(self, 'parent') and hasattr(self.parent(), 'update_bot_trades_table'):
                    self.parent().update_bot_trades_table()
                
            else:
                self.logger.error(f"봇 거래 실행 실패: {message}")
                
        except Exception as e:
            error_msg = f"거래 실행 오류: {e}"
            self.logger.error(error_msg)
            self.error_occurred.emit(error_msg)
    
    def pause(self, reason: str = "사용자 요청"):
        """봇 일시정지"""
        self.status.pause(reason)
        self.status_changed.emit("paused")
        self.logger.info(f"트레이딩봇 일시정지: {reason}")
    
    def get_bot_status(self) -> Dict[str, Any]:
        """봇 상태 정보 반환"""
        try:
            status_info = self.status.get_status_info()
            risk_metrics = self.risk_manager.get_risk_metrics()
            
            return {
                'bot_status': status_info,
                'risk_metrics': risk_metrics,
                'config': self.config.to_dict(),
                'last_update': datetime.now().isoformat()
            }
            
        except Exception as e:
            self.logger.error(f"봇 상태 조회 오류: {e}")
            return {}
    
    def get_trade_history(self, limit: int = 50) -> list:
        """봇 거래 내역 반환"""
        try:
            return self.risk_manager.get_trade_history(limit)
        except Exception as e:
            self.logger.error(f"거래 내역 조회 오류: {e}")
            return []
    
    def _calculate_avg_buy_price(self, coin_symbol: str) -> float:
        """코인의 평균 매수가 계산 (GUI calculate_average_buy_price와 동일한 로직)"""
        try:
            # 거래 내역에서 해당 코인의 매수 거래만 추출
            trade_history = self.risk_manager.get_trade_history(1000)  # 충분한 내역
            
            total_cost = 0.0
            total_quantity = 0.0
            
            for trade in trade_history:
                if trade.get('symbol', '').replace('USDT', '') == coin_symbol and trade.get('action') == 'BUY':
                    amount = trade.get('amount', 0)
                    price = trade.get('price', 0)
                    if price > 0:
                        quantity = amount / price
                        total_cost += amount
                        total_quantity += quantity
            
            if total_quantity > 0:
                avg_price = total_cost / total_quantity
                self.logger.debug(f"{coin_symbol} 평균매수가 계산: ${avg_price:.2f} (총 비용: ${total_cost:.2f}, 총 수량: {total_quantity:.4f})")
                return avg_price
            else:
                self.logger.debug(f"{coin_symbol} 매수 내역 없음")
                return 0.0
                
        except Exception as e:
            self.logger.error(f"평균매수가 계산 오류: {e}")
            return 0.0
    
    def _sync_positions_with_portfolio(self):
        """리스크 매니저의 포지션 추적을 실제 포트폴리오와 동기화"""
        try:
            # 실제 보유 중인 코인들을 확인하여 리스크 매니저 동기화
            supported_pairs = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT']  # 지원하는 거래쌍
            
            for symbol in supported_pairs:
                try:
                    quantity = self.trading_engine.portfolio.get_holding_quantity(symbol)
                    if quantity > 0:
                        # 실제 보유 중이면 리스크 매니저에 포지션 추가
                        self.risk_manager.position_symbols.add(symbol)
                        self.logger.info(f"🔄 포지션 동기화: {symbol} 보유량 {quantity:.6f} -> 포지션 추가")
                    else:
                        # 보유하지 않으면 포지션에서 제거
                        self.risk_manager.position_symbols.discard(symbol)
                        
                except Exception as e:
                    self.logger.warning(f"⚠️ {symbol} 보유량 확인 실패: {e}")
            
            # 현재 포지션 수 업데이트
            self.risk_manager.current_positions = len(self.risk_manager.position_symbols)
            
            self.logger.info(f"✅ 포지션 동기화 완료: {list(self.risk_manager.position_symbols)} ({self.risk_manager.current_positions}개)")
            
        except Exception as e:
            self.logger.error(f"❌ 포지션 동기화 오류: {e}")
