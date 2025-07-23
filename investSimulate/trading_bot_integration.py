# trading_bot_integration.py
# 기존 트레이딩봇에 백테스팅 전략을 통합하는 통합 모듈 (수정된 버전)

import asyncio
import logging
from datetime import datetime
from typing import Dict, List, Optional
from dataclasses import dataclass
import json

# 기존 프로젝트 모듈들 import (경로 수정)
try:
    from binance_futures_client import BinanceFuturesClient
except ImportError:
    BinanceFuturesClient = None

try:
    from portfolio_manager import PortfolioManager
except ImportError:
    PortfolioManager = None

try:
    from trading_engine import TradingEngine
except ImportError:
    TradingEngine = None

try:
    from cross_position_manager import CrossPositionManager
except ImportError:
    CrossPositionManager = None

# 전략 어댑터 import
from strategy_adapter import BacktestStrategyAdapter, TradingSignal, SignalType

@dataclass
class TradingBotConfig:
    """트레이딩봇 설정"""
    symbol: str = "BTCUSDT"
    timeframe: str = "1h"
    strategy_name: str = "macd_final"
    strategy_params: Dict = None
    leverage: int = 3
    position_size_pct: float = 50.0  # 자본의 50%만 사용
    stop_loss_pct: float = -2.0
    take_profit_pct: float = 10.0
    max_positions: int = 1

    def __post_init__(self):
        if self.strategy_params is None:
            self.strategy_params = {}

class AdvancedTradingBot:
    """
    백테스팅 전략을 실시간 트레이딩에 적용하는 고급 트레이딩봇
    """

    def __init__(self, config: TradingBotConfig):
        self.config = config
        self.logger = self._setup_logger()

        # 기존 모듈들 초기화
        try:
            self.binance_client = BinanceFuturesClient() if BinanceFuturesClient else None
            self.portfolio_manager = PortfolioManager() if PortfolioManager else None
            self.trading_engine = TradingEngine() if TradingEngine else None
            self.position_manager = CrossPositionManager() if CrossPositionManager else None
        except Exception as e:
            self.logger.error(f"Error initializing modules: {e}")
            # 기본적인 초기화만 수행
            self.binance_client = None
            self.portfolio_manager = None
            self.trading_engine = None
            self.position_manager = None

        # 전략 어댑터 초기화
        self.strategy_adapter = BacktestStrategyAdapter(
            strategy_name=config.strategy_name,
            params=config.strategy_params,
            leverage=config.leverage
        )

        # 상태 관리
        self.is_running = False
        self.current_positions = {}
        self.last_signal_time = None

        # 성능 추적
        self.trade_history = []
        self.performance_metrics = {
            'total_trades': 0,
            'winning_trades': 0,
            'total_pnl': 0.0,
            'max_drawdown': 0.0
        }

    def _setup_logger(self) -> logging.Logger:
        """로거 설정"""
        logger = logging.getLogger(f"TradingBot_{self.config.symbol}")
        logger.setLevel(logging.INFO)

        if not logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            )
            handler.setFormatter(formatter)
            logger.addHandler(handler)

        return logger

    async def start(self):
        """트레이딩봇 시작"""
        self.logger.info(f"Starting Advanced Trading Bot for {self.config.symbol}")
        self.logger.info(f"Strategy: {self.config.strategy_name}")
        self.logger.info(f"Parameters: {self.config.strategy_params}")

        # 모듈 초기화 확인
        if not self._check_modules():
            self.logger.error("Required modules not available - running in simulation mode")
            return await self._start_simulation_mode()

        self.is_running = True

        try:
            # 과거 데이터 초기 로딩
            await self._load_initial_data()

            # 실시간 데이터 스트림 시작
            await self._start_data_stream()

        except Exception as e:
            self.logger.error(f"Error starting bot: {e}")
            self.is_running = False

    def _check_modules(self) -> bool:
        """필수 모듈들이 제대로 초기화되었는지 확인"""
        return all([
            self.binance_client is not None,
            self.strategy_adapter is not None
        ])

    async def _start_simulation_mode(self):
        """시뮬레이션 모드로 실행 (실제 거래 없이 신호만 확인)"""
        self.logger.info("Starting in SIMULATION MODE - No real trades will be executed")
        self.is_running = True

        # 가상 데이터로 테스트
        while self.is_running:
            try:
                # 가상의 캔들 데이터 생성 (실제로는 외부 API에서 가져와야 함)
                sample_candle = await self._generate_sample_candle()

                if sample_candle:
                    # 전략 어댑터에 새 데이터 업데이트
                    self.strategy_adapter.update_data(sample_candle)

                    # 트레이딩 신호 확인
                    current_price = sample_candle['close']
                    signal = self.strategy_adapter.get_trading_signal(current_price)

                    # 신호 로깅만 수행 (실제 거래 없음)
                    if signal.signal_type != SignalType.NONE:
                        self.logger.info(f"SIMULATION - Signal: {signal.signal_type.value} "
                                         f"(Strength: {signal.strength:.2f}) - {signal.reason}")

                await asyncio.sleep(5)  # 5초마다 확인

            except KeyboardInterrupt:
                break
            except Exception as e:
                self.logger.error(f"Error in simulation: {e}")
                await asyncio.sleep(10)

    async def _generate_sample_candle(self) -> Optional[Dict]:
        """시뮬레이션용 가상 캔들 데이터 생성"""
        import random

        # 기본 가격 범위 (실제로는 외부 API에서 가져와야 함)
        base_price = 50000
        variation = random.uniform(-0.02, 0.02)  # ±2% 변동

        open_price = base_price * (1 + variation)
        close_price = open_price * (1 + random.uniform(-0.01, 0.01))
        high_price = max(open_price, close_price) * (1 + random.uniform(0, 0.005))
        low_price = min(open_price, close_price) * (1 - random.uniform(0, 0.005))

        return {
            'open': open_price,
            'high': high_price,
            'low': low_price,
            'close': close_price,
            'volume': random.uniform(100, 1000),
            'timestamp': int(datetime.now().timestamp())
        }

    async def stop(self):
        """트레이딩봇 중지"""
        self.logger.info("Stopping Advanced Trading Bot")
        self.is_running = False

        # 모든 포지션 청산 (실제 거래 모드인 경우만)
        if self._check_modules():
            await self._close_all_positions()

        # 성능 리포트 출력
        self._print_performance_report()

    async def _load_initial_data(self):
        """초기 데이터 로딩 (지표 계산을 위한 충분한 데이터)"""
        try:
            if not self.binance_client:
                # 시뮬레이션 모드에서는 가상 데이터 생성
                for _ in range(100):
                    candle = await self._generate_sample_candle()
                    self.strategy_adapter.update_data(candle)
                self.logger.info("Loaded simulated historical data")
                return

            # 실제 바이낸스에서 과거 데이터 가져오기
            # (binance_futures_client.py의 실제 메서드명에 맞춰 수정 필요)
            # klines = await self.binance_client.get_historical_klines(...)

            self.logger.info("Historical data loading not implemented - using simulation")

        except Exception as e:
            self.logger.error(f"Error loading initial data: {e}")
            raise

    async def _start_data_stream(self):
        """실시간 데이터 스트림 처리"""
        while self.is_running:
            try:
                # 최신 캔들 데이터 가져오기
                current_candle = await self._get_current_candle()

                if current_candle:
                    # 전략 어댑터에 새 데이터 업데이트
                    self.strategy_adapter.update_data(current_candle)

                    # 트레이딩 신호 확인
                    current_price = current_candle['close']
                    signal = self.strategy_adapter.get_trading_signal(current_price)

                    # 신호 처리
                    await self._process_trading_signal(signal, current_price)

                    # 기존 포지션 관리
                    await self._manage_existing_positions(current_price)

                # 1분 대기 (실제로는 웹소켓 사용 권장)
                await asyncio.sleep(60)

            except Exception as e:
                self.logger.error(f"Error in data stream: {e}")
                await asyncio.sleep(10)

    async def _get_current_candle(self) -> Optional[Dict]:
        """현재 캔들 데이터 가져오기"""
        try:
            if not self.binance_client:
                # 시뮬레이션 모드
                return await self._generate_sample_candle()

            # 실제 바이낸스 API 호출 (메서드명 확인 필요)
            # klines = await self.binance_client.get_klines(...)

            # 임시로 시뮬레이션 데이터 반환
            return await self._generate_sample_candle()

        except Exception as e:
            self.logger.error(f"Error getting current candle: {e}")
            return None

    async def _process_trading_signal(self, signal: TradingSignal, current_price: float):
        """트레이딩 신호 처리"""
        if signal.signal_type == SignalType.NONE:
            return

        # 신호 로깅
        self.logger.info(f"Signal detected: {signal.signal_type.value} "
                         f"(Strength: {signal.strength:.2f}) - {signal.reason}")

        # 실제 거래 모드인지 확인
        if not self._check_modules():
            self.logger.info("SIMULATION MODE - Signal logged but no trade executed")
            return

        # 리스크 관리 체크
        if not await self._risk_check(signal, current_price):
            self.logger.warning("Signal rejected by risk management")
            return

        # 포지션 한도 체크
        if len(self.current_positions) >= self.config.max_positions:
            self.logger.info("Maximum positions reached, skipping signal")
            return

        # 거래 실행
        await self._execute_trade(signal, current_price)

    async def _risk_check(self, signal: TradingSignal, current_price: float) -> bool:
        """리스크 관리 체크"""
        try:
            # 시뮬레이션 모드에서는 기본적인 체크만
            if not self.binance_client:
                return signal.strength >= 0.5

            # 실제 계좌 정보 확인 (메서드명 확인 필요)
            # account_info = await self.binance_client.get_account()
            # available_balance = float(account_info.get('totalWalletBalance', 0))

            # 임시로 기본 체크만 수행
            return signal.strength >= 0.5

        except Exception as e:
            self.logger.error(f"Error in risk check: {e}")
            return False

    async def _execute_trade(self, signal: TradingSignal, current_price: float):
        """거래 실행"""
        try:
            # 시뮬레이션 모드에서는 가상 거래만 기록
            if not self.binance_client:
                self._record_simulated_trade(signal, current_price)
                return

            # 실제 거래 실행 로직 (바이낸스 API 메서드에 맞춰 구현 필요)
            self.logger.info("Real trading execution not implemented yet")

        except Exception as e:
            self.logger.error(f"Error executing trade: {e}")

    def _record_simulated_trade(self, signal: TradingSignal, current_price: float):
        """시뮬레이션 거래 기록"""
        position_id = f"{signal.signal_type.value}_{datetime.now().timestamp()}"
        self.current_positions[position_id] = {
            'type': signal.signal_type.value,
            'entry_price': current_price,
            'quantity': 1.0,  # 가상 수량
            'timestamp': datetime.now(),
            'stop_loss': signal.stop_loss or self._calculate_stop_loss(current_price, signal.signal_type),
            'take_profit': signal.take_profit or self._calculate_take_profit(current_price, signal.signal_type)
        }

        self.logger.info(f"SIMULATED Trade: {signal.signal_type.value} at {current_price}")
        self.performance_metrics['total_trades'] += 1

    def _calculate_stop_loss(self, entry_price: float, signal_type: SignalType) -> float:
        """손절가 계산"""
        if signal_type == SignalType.LONG:
            return entry_price * (1 + self.config.stop_loss_pct / 100)
        else:
            return entry_price * (1 - self.config.stop_loss_pct / 100)

    def _calculate_take_profit(self, entry_price: float, signal_type: SignalType) -> float:
        """익절가 계산"""
        if signal_type == SignalType.LONG:
            return entry_price * (1 + self.config.take_profit_pct / 100)
        else:
            return entry_price * (1 - self.config.take_profit_pct / 100)

    async def _manage_existing_positions(self, current_price: float):
        """기존 포지션 관리 (손절/익절)"""
        positions_to_close = []

        for position_id, position in self.current_positions.items():
            should_close = False
            close_reason = ""

            # 손절 체크
            if position['type'] == 'long' and current_price <= position['stop_loss']:
                should_close = True
                close_reason = "Stop Loss"
            elif position['type'] == 'short' and current_price >= position['stop_loss']:
                should_close = True
                close_reason = "Stop Loss"

            # 익절 체크
            elif position['type'] == 'long' and current_price >= position['take_profit']:
                should_close = True
                close_reason = "Take Profit"
            elif position['type'] == 'short' and current_price <= position['take_profit']:
                should_close = True
                close_reason = "Take Profit"

            if should_close:
                positions_to_close.append((position_id, close_reason))

        # 포지션 청산
        for position_id, reason in positions_to_close:
            await self._close_position(position_id, current_price, reason)

    async def _close_position(self, position_id: str, current_price: float, reason: str):
        """포지션 청산"""
        try:
            position = self.current_positions[position_id]

            # P&L 계산
            if position['type'] == 'long':
                pnl = (current_price - position['entry_price']) * position['quantity']
            else:
                pnl = (position['entry_price'] - current_price) * position['quantity']

            self.logger.info(f"Position closed: {reason} - P&L: {pnl:.2f} USDT")

            # 성능 추적 업데이트
            self.performance_metrics['total_pnl'] += pnl
            if pnl > 0:
                self.performance_metrics['winning_trades'] += 1

            # 거래 히스토리에 추가
            self.trade_history.append({
                'entry_time': position['timestamp'],
                'exit_time': datetime.now(),
                'type': position['type'],
                'entry_price': position['entry_price'],
                'exit_price': current_price,
                'quantity': position['quantity'],
                'pnl': pnl,
                'exit_reason': reason
            })

            # 포지션 제거
            del self.current_positions[position_id]

        except Exception as e:
            self.logger.error(f"Error closing position {position_id}: {e}")

    async def _close_all_positions(self):
        """모든 포지션 청산"""
        current_price = 50000  # 기본값 (실제로는 현재 시장가격 가져와야 함)

        for position_id in list(self.current_positions.keys()):
            await self._close_position(position_id, current_price, "Bot Shutdown")

    def _print_performance_report(self):
        """성능 리포트 출력"""
        total_trades = self.performance_metrics['total_trades']
        winning_trades = self.performance_metrics['winning_trades']
        total_pnl = self.performance_metrics['total_pnl']

        win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0

        self.logger.info("=== PERFORMANCE REPORT ===")
        self.logger.info(f"Total Trades: {total_trades}")
        self.logger.info(f"Winning Trades: {winning_trades}")
        self.logger.info(f"Win Rate: {win_rate:.2f}%")
        self.logger.info(f"Total P&L: {total_pnl:.2f} USDT")
        self.logger.info("==========================")

# 사용 예시
async def main():
    """메인 실행 함수"""

    # 트레이딩봇 설정
    bot_config = TradingBotConfig(
        symbol="BTCUSDT",
        timeframe="1h",
        strategy_name='macd_final',
        strategy_params={'regime_filter_period': 200},
        leverage=3,
        position_size_pct=30.0,
        stop_loss_pct=-2.0,
        take_profit_pct=8.0,
        max_positions=2
    )

    # 트레이딩봇 시작
    bot = AdvancedTradingBot(bot_config)

    try:
        await bot.start()
    except KeyboardInterrupt:
        print("Stopping bot...")
        await bot.stop()

if __name__ == "__main__":
    asyncio.run(main())