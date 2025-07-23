# main.py
import sys
import os
import logging
from datetime import datetime
from .trading_engine import TradingEngine
from .config import Config

def setup_logging():
    """로깅 설정"""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler('trading_log.txt'),
            logging.StreamHandler()
        ]
    )

def print_menu():
    """메뉴 출력"""
    print("\n" + "="*50)
    print("    Genius Coin Manager - 모의투자 프로그램")
    print("="*50)
    print("1. 포트폴리오 현황 조회")
    print("2. 시장 정보 조회")
    print("3. 매수 주문")
    print("4. 매도 주문")
    print("5. 거래 내역 조회")
    print("6. 가격 업데이트")
    print("7. 포트폴리오 초기화")
    print("8. GUI 모드 실행")
    print("9. 종료")
    print("="*50)

def display_portfolio_status(trading_engine):
    """포트폴리오 상태 출력"""
    summary, message = trading_engine.get_portfolio_status()

    if summary:
        print(f"\n📊 포트폴리오 현황")
        print(f"총 자산: ${summary['total_value']:.2f}")
        print(f"현금 잔고: ${summary['cash_balance']:.2f}")
        print(f"투자 금액: ${summary['invested_value']:.2f}")
        print(f"총 손익: ${summary['profit_loss']:.2f} ({summary['profit_loss_percent']:.2f}%)")
        print(f"거래 횟수: {summary['transaction_count']}")

        if summary['holdings']:
            print(f"\n💰 보유 코인:")
            for currency, quantity in summary['holdings'].items():
                symbol = f"{currency}USDT"
                current_price = trading_engine.current_prices.get(symbol, 0)
                value = quantity * current_price
                print(f"  {currency}: {quantity:.8f} (${value:.2f})")
        else:
            print("\n보유 중인 코인이 없습니다.")
    else:
        print(f"❌ 포트폴리오 조회 실패: {message}")

def display_market_info(trading_engine):
    """시장 정보 출력"""
    print("\n지원하는 거래쌍:")
    for i, symbol in enumerate(Config.SUPPORTED_PAIRS, 1):
        print(f"{i}. {symbol}")

    try:
        choice = int(input("\n조회할 거래쌍 번호를 선택하세요: ")) - 1
        if 0 <= choice < len(Config.SUPPORTED_PAIRS):
            symbol = Config.SUPPORTED_PAIRS[choice]

            market_data, message = trading_engine.get_market_data(symbol)

            if market_data:
                print(f"\n📈 {symbol} 시장 정보")
                print(f"현재가: ${market_data['current_price']:.4f}")
                print(f"24시간 변동: ${market_data['price_change_24h']:.4f} ({market_data['price_change_percent_24h']:.2f}%)")
                print(f"24시간 최고가: ${market_data['high_24h']:.4f}")
                print(f"24시간 최저가: ${market_data['low_24h']:.4f}")
                print(f"24시간 거래량: {market_data['volume_24h']:.2f}")
                print(f"매수 호가: ${market_data['bid_price']:.4f}")
                print(f"매도 호가: ${market_data['ask_price']:.4f}")
            else:
                print(f"❌ 시장 정보 조회 실패: {message}")
        else:
            print("❌ 잘못된 선택입니다.")
    except ValueError:
        print("❌ 올바른 숫자를 입력해주세요.")

def place_buy_order(trading_engine):
    """매수 주문 실행"""
    print("\n지원하는 거래쌍:")
    for i, symbol in enumerate(Config.SUPPORTED_PAIRS, 1):
        current_price = trading_engine.get_current_price(symbol)
        price_str = f"${current_price:.4f}" if current_price else "가격 조회 실패"
        print(f"{i}. {symbol} ({price_str})")

    try:
        choice = int(input("\n매수할 거래쌍 번호를 선택하세요: ")) - 1
        if 0 <= choice < len(Config.SUPPORTED_PAIRS):
            symbol = Config.SUPPORTED_PAIRS[choice]

            print("\n매수 방식을 선택하세요:")
            print("1. 금액으로 매수 (USD)")
            print("2. 수량으로 매수")

            method = input("선택 (1 또는 2): ").strip()

            if method == "1":
                amount = float(input("매수할 USD 금액을 입력하세요: "))
                success, message = trading_engine.place_buy_order(symbol, amount_usd=amount)
            elif method == "2":
                quantity = float(input("매수할 코인 수량을 입력하세요: "))
                success, message = trading_engine.place_buy_order(symbol, quantity=quantity)
            else:
                print("❌ 잘못된 선택입니다.")
                return

            if success:
                print(f"✅ {message}")
            else:
                print(f"❌ {message}")
        else:
            print("❌ 잘못된 선택입니다.")
    except ValueError:
        print("❌ 올바른 숫자를 입력해주세요.")

def place_sell_order(trading_engine):
    """매도 주문 실행"""
    # 보유 코인 조회
    summary, _ = trading_engine.get_portfolio_status()

    if not summary or not summary['holdings']:
        print("❌ 보유 중인 코인이 없습니다.")
        return

    print("\n보유 코인:")
    holdings_list = list(summary['holdings'].items())
    for i, (currency, quantity) in enumerate(holdings_list, 1):
        symbol = f"{currency}USDT"
        current_price = trading_engine.get_current_price(symbol)
        value = quantity * current_price if current_price else 0
        price_str = f"${current_price:.4f}" if current_price else "가격 조회 실패"
        print(f"{i}. {currency}: {quantity:.8f} (${value:.2f}) @ {price_str}")

    try:
        choice = int(input("\n매도할 코인 번호를 선택하세요: ")) - 1
        if 0 <= choice < len(holdings_list):
            currency, available_quantity = holdings_list[choice]
            symbol = f"{currency}USDT"

            print(f"\n매도 방식을 선택하세요:")
            print(f"1. 수량 지정 매도 (보유량: {available_quantity:.8f})")
            print(f"2. 전량 매도")

            method = input("선택 (1 또는 2): ").strip()

            if method == "1":
                quantity = float(input("매도할 수량을 입력하세요: "))
                success, message = trading_engine.place_sell_order(symbol, quantity=quantity)
            elif method == "2":
                success, message = trading_engine.place_sell_order(symbol, sell_all=True)
            else:
                print("❌ 잘못된 선택입니다.")
                return

            if success:
                print(f"✅ {message}")
            else:
                print(f"❌ {message}")
        else:
            print("❌ 잘못된 선택입니다.")
    except ValueError:
        print("❌ 올바른 숫자를 입력해주세요.")

def display_transaction_history(trading_engine):
    """거래 내역 출력"""
    transactions, message = trading_engine.get_transaction_history(20)

    if transactions:
        print(f"\n📋 최근 거래 내역 (최대 20개)")
        print("-" * 80)
        print(f"{'타입':<6} {'심볼':<12} {'수량':<15} {'가격':<12} {'총액':<12} {'수수료':<8} {'시간':<20}")
        print("-" * 80)

        for tx in transactions:
            timestamp = datetime.fromisoformat(tx['timestamp']).strftime('%Y-%m-%d %H:%M:%S')
            print(f"{tx['type']:<6} {tx['symbol']:<12} {tx['quantity']:<15.8f} "
                  f"${tx['price']:<11.4f} ${tx['total_amount']:<11.2f} "
                  f"${tx['commission']:<7.2f} {timestamp}")
    else:
        print("❌ 거래 내역이 없습니다.")

def update_prices(trading_engine):
    """가격 업데이트"""
    print("\n⏳ 가격 업데이트 중...")

    if trading_engine.update_prices():
        print("✅ 가격 업데이트 완료")
        print(f"업데이트된 심볼 수: {len(trading_engine.current_prices)}")

        # 현재 가격 일부 출력
        print("\n📊 현재 가격:")
        for symbol, price in list(trading_engine.current_prices.items())[:5]:
            print(f"{symbol}: ${price:.4f}")

        if len(trading_engine.current_prices) > 5:
            print(f"... 및 {len(trading_engine.current_prices) - 5}개 더")
    else:
        print("❌ 가격 업데이트 실패")

def reset_portfolio(trading_engine):
    """포트폴리오 초기화"""
    confirm = input("\n⚠️  포트폴리오를 초기화하시겠습니까? 모든 거래 내역이 삭제됩니다. (y/N): ")

    if confirm.lower() == 'y':
        success, message = trading_engine.reset_portfolio()

        if success:
            print(f"✅ {message}")
        else:
            print(f"❌ {message}")
    else:
        print("초기화가 취소되었습니다.")

def run_gui():
    """GUI 모드 실행"""
    try:
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

        from .gui_app import main as gui_main
        print("\n🖥️  GUI 모드를 실행합니다...")
        gui_main()
    except ImportError as e:
        print(f"❌ GUI 모드를 실행할 수 없습니다.")
        print(f"오류 세부사항: {e}")
    except Exception as e:
        print(f"❌ GUI 실행 중 오류가 발생했습니다: {e}")

def main():
    setup_logging()
    print(" Genius Coin Manager 시작 중...")

    # 거래 엔진 초기화
    try:
        trading_engine = TradingEngine()
        print("거래 엔진 초기화 완료")

        # 초기 가격 업데이트
        print("초기 가격 데이터 로드 중...")
        if trading_engine.update_prices():
            print("가격 데이터 로드 완료")
        else:
            print("가격 데이터 로드 실패 (계속 진행)")

    except Exception as e:
        print(f"❌ 거래 엔진 초기화 실패: {e}")
        print("인터넷 연결과 API 키를 확인해주세요.")
        return

    # 메인 루프
    while True:
        try:
            print_menu()
            choice = input("\n메뉴를 선택하세요 (1-9): ").strip()

            if choice == "1":
                display_portfolio_status(trading_engine)

            elif choice == "2":
                display_market_info(trading_engine)

            elif choice == "3":
                place_buy_order(trading_engine)

            elif choice == "4":
                place_sell_order(trading_engine)

            elif choice == "5":
                display_transaction_history(trading_engine)

            elif choice == "6":
                update_prices(trading_engine)

            elif choice == "7":
                reset_portfolio(trading_engine)

            elif choice == "8":
                run_gui()

            elif choice == "9":
                print("\n👋 Genius Coin Manager를 종료합니다.")
                break

            else:
                print("❌ 잘못된 선택입니다. 1-9 사이의 숫자를 입력해주세요.")

        except KeyboardInterrupt:
            print("\n\n👋 프로그램이 중단되었습니다.")
            break
        except Exception as e:
            print(f"❌ 오류가 발생했습니다: {e}")

        # 계속하기 위해 엔터 키 대기
        if choice != "9":
            input("\n계속하려면 엔터를 누르세요...")

if __name__ == "__main__":
    main()
