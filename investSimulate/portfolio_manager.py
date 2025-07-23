# portfolio_manager.py
import json
import os
import logging
from datetime import datetime
from .config import Config

class PortfolioManager:
    def __init__(self):
        self.portfolio_file = os.path.join(Config.DATA_DIR, "portfolio.json")
        self.transactions_file = os.path.join(Config.DATA_DIR, "transactions.json")
        self.logger = logging.getLogger(__name__)
        
        # 데이터 디렉토리 생성
        os.makedirs(Config.DATA_DIR, exist_ok=True)
        
        # 포트폴리오와 거래 내역 로드
        self.portfolio = self.load_portfolio()
        self.transactions = self.load_transactions()

    def load_portfolio(self):
        """포트폴리오 데이터 로드"""
        try:
            if os.path.exists(self.portfolio_file):
                with open(self.portfolio_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            else:
                # 초기 포트폴리오 생성
                initial_portfolio = {
                    'balance': Config.INITIAL_BALANCE,
                    'holdings': {},
                    'total_invested': 0.0,
                    'total_profit_loss': 0.0,
                    'last_updated': datetime.now().isoformat()
                }
                self.save_portfolio_data(initial_portfolio)
                return initial_portfolio
        except Exception as e:
            self.logger.error(f"포트폴리오 로드 오류: {e}")
            return {
                'balance': Config.INITIAL_BALANCE,
                'holdings': {},
                'total_invested': 0.0,
                'total_profit_loss': 0.0,
                'last_updated': datetime.now().isoformat()
            }

    def load_transactions(self):
        """거래 내역 로드"""
        try:
            if os.path.exists(self.transactions_file):
                with open(self.transactions_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            else:
                return []
        except Exception as e:
            self.logger.error(f"거래 내역 로드 오류: {e}")
            return []

    def save_portfolio(self):
        """포트폴리오 저장"""
        self.save_portfolio_data(self.portfolio)

    def save_portfolio_data(self, portfolio_data):
        """포트폴리오 데이터 저장"""
        try:
            portfolio_data['last_updated'] = datetime.now().isoformat()
            with open(self.portfolio_file, 'w', encoding='utf-8') as f:
                json.dump(portfolio_data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            self.logger.error(f"포트폴리오 저장 오류: {e}")

    def save_transactions(self):
        """거래 내역 저장"""
        try:
            with open(self.transactions_file, 'w', encoding='utf-8') as f:
                json.dump(self.transactions, f, indent=2, ensure_ascii=False)
        except Exception as e:
            self.logger.error(f"거래 내역 저장 오류: {e}")

    def buy_coin(self, symbol, quantity, price):
        """코인 매수"""
        try:
            total_cost = quantity * price
            commission = total_cost * Config.COMMISSION_RATE

            # 수수료 포함 총 비용
            total_with_commission = total_cost + commission

            # 잔고 확인
            if self.portfolio['balance'] < total_with_commission:
                return False, f"잔고 부족 (필요: ${total_with_commission:.2f}, 보유: ${self.portfolio['balance']:.2f})"

            # 코인 심볼에서 통화 추출 (예: BTCUSDT -> BTC)
            currency = symbol.replace('USDT', '')

            # 포트폴리오 업데이트
            self.portfolio['balance'] -= total_with_commission
            
            if currency in self.portfolio['holdings']:
                self.portfolio['holdings'][currency] += quantity
            else:
                self.portfolio['holdings'][currency] = quantity

            self.portfolio['total_invested'] += total_cost

            # 거래 내역 추가
            transaction = {
                'type': 'BUY',
                'symbol': symbol,
                'currency': currency,
                'quantity': quantity,
                'price': price,
                'total_amount': total_cost,
                'commission': commission,
                'timestamp': datetime.now().isoformat()
            }
            self.transactions.append(transaction)

            # 저장
            self.save_portfolio()
            self.save_transactions()

            self.logger.info(f"매수 완료: {symbol} {quantity} @ ${price}")
            return True, f"매수 완료: {currency} {quantity:.8f} @ ${price:.4f} (수수료: ${commission:.2f})"

        except Exception as e:
            error_msg = f"매수 처리 중 오류: {e}"
            self.logger.error(error_msg)
            return False, error_msg

    def sell_coin(self, symbol, quantity, price):
        """코인 매도"""
        try:
            # 코인 심볼에서 통화 추출
            currency = symbol.replace('USDT', '')

            # 보유량 확인
            if currency not in self.portfolio['holdings']:
                return False, f"{currency}를 보유하고 있지 않습니다"

            available_quantity = self.portfolio['holdings'][currency]
            if available_quantity < quantity:
                return False, f"보유량 부족 ({currency}: {available_quantity:.8f} < {quantity:.8f})"

            # 매도 금액 계산
            total_amount = quantity * price
            commission = total_amount * Config.COMMISSION_RATE
            net_amount = total_amount - commission

            # 포트폴리오 업데이트
            self.portfolio['balance'] += net_amount
            self.portfolio['holdings'][currency] -= quantity

            # 보유량이 0이 되면 제거
            if self.portfolio['holdings'][currency] <= 0:
                del self.portfolio['holdings'][currency]

            # 거래 내역 추가
            transaction = {
                'type': 'SELL',
                'symbol': symbol,
                'currency': currency,
                'quantity': quantity,
                'price': price,
                'total_amount': total_amount,
                'commission': commission,
                'net_amount': net_amount,
                'timestamp': datetime.now().isoformat()
            }
            self.transactions.append(transaction)

            # 저장
            self.save_portfolio()
            self.save_transactions()

            self.logger.info(f"매도 완료: {symbol} {quantity} @ ${price}")
            return True, f"매도 완료: {currency} {quantity:.8f} @ ${price:.4f} (수수료: ${commission:.2f})"

        except Exception as e:
            error_msg = f"매도 처리 중 오류: {e}"
            self.logger.error(error_msg)
            return False, error_msg

    def get_holding_quantity(self, symbol):
        """특정 코인의 보유량 조회"""
        currency = symbol.replace('USDT', '')
        return self.portfolio['holdings'].get(currency, 0)

    def get_portfolio_summary(self, current_prices=None):
        """포트폴리오 요약 정보 반환"""
        try:
            if current_prices is None:
                current_prices = {}

            summary = {
                'cash_balance': self.portfolio['balance'],
                'holdings': self.portfolio['holdings'].copy(),
                'total_invested': self.portfolio['total_invested'],
                'invested_value': 0.0,  # 현재 투자 평가액
                'total_value': self.portfolio['balance'],  # 총 자산
                'profit_loss': 0.0,  # 손익
                'profit_loss_percent': 0.0,  # 손익률
                'transaction_count': len(self.transactions)
            }

            # 현재 보유 코인의 평가액 계산
            for currency, quantity in self.portfolio['holdings'].items():
                symbol = f"{currency}USDT"
                current_price = current_prices.get(symbol, 0)
                market_value = quantity * current_price
                summary['invested_value'] += market_value

            # 총 자산 = 현금 잔고 + 투자 평가액
            summary['total_value'] = summary['cash_balance'] + summary['invested_value']

            # 손익 계산 (현재 총 자산 - 초기 자금)
            summary['profit_loss'] = summary['total_value'] - Config.INITIAL_BALANCE

            # 손익률 계산
            if Config.INITIAL_BALANCE > 0:
                summary['profit_loss_percent'] = (summary['profit_loss'] / Config.INITIAL_BALANCE) * 100

            return summary

        except Exception as e:
            self.logger.error(f"포트폴리오 요약 계산 오류: {e}")
            return None
