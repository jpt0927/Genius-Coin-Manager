# liquidation_test.py - 자동 청산 시스템 테스트
from cross_position_manager import CrossPositionManager
from config import Config
import time

def test_auto_liquidation():
    """자동 청산 시스템 테스트"""
    print("🧪 자동 청산 시스템 테스트 시작...")
    
    # Cross 포지션 매니저 초기화
    cross_manager = CrossPositionManager()
    
    # 테스트용 포지션 생성
    symbol = "ETHUSDT"
    side = "SHORT"
    entry_price = 3700.0
    leverage = 125
    quantity = 1000.0  # 큰 수량으로 테스트
    margin_required = 1000.0
    
    print(f"\n📊 테스트 포지션 생성:")
    print(f"심볼: {symbol}")
    print(f"방향: {side}")
    print(f"진입가: ${entry_price}")
    print(f"레버리지: {leverage}x")
    print(f"수량: {quantity}")
    print(f"증거금: ${margin_required}")
    
    # 포지션 생성
    success, message = cross_manager.open_position(
        symbol=symbol,
        side=side,
        quantity=quantity,
        price=entry_price,
        leverage=leverage,
        margin_required=margin_required
    )
    
    if not success:
        print(f"❌ 포지션 생성 실패: {message}")
        return
    
    print(f"✅ 포지션 생성 성공: {message}")
    
    # 시나리오별 가격 테스트
    test_scenarios = [
        ("정상 상태", 3705.0, False),      # 작은 손실
        ("마진콜 경고", 3850.0, False),    # -50% 정도 손실
        ("고위험 상태", 3950.0, False),    # -70% 정도 손실
        ("자동 청산 트리거", 4100.0, True), # -80% 이상 손실
    ]
    
    print("\n🎯 시나리오별 테스트:")
    print("-" * 60)
    
    for scenario_name, test_price, should_liquidate in test_scenarios:
        print(f"\n📈 시나리오: {scenario_name}")
        print(f"테스트 가격: ${test_price}")
        
        # 가격 업데이트 및 청산 조건 확인
        current_prices = {symbol: test_price}
        liquidated_positions = cross_manager.update_positions_pnl(current_prices)
        
        # 포지션 상태 확인
        position = cross_manager.find_position(symbol)
        
        if position:
            unrealized_pnl = cross_manager.calculate_unrealized_pnl(position, test_price)
            pnl_percentage = (unrealized_pnl / margin_required) * 100
            liquidation_price = cross_manager.calculate_liquidation_price(position)
            
            print(f"💰 미실현 손익: ${unrealized_pnl:,.2f}")
            print(f"📊 손익률: {pnl_percentage:.2f}%")
            print(f"⚠️ 청산가: ${liquidation_price:.2f}")
            
            if pnl_percentage <= -70:
                risk_level = "🔴 극위험"
            elif pnl_percentage <= -50:
                risk_level = "🟠 고위험"
            elif pnl_percentage <= -30:
                risk_level = "🟡 중위험"
            else:
                risk_level = "🟢 안전"
            
            print(f"🚨 위험도: {risk_level}")
            
            if liquidated_positions:
                print(f"🔥 자동 청산 실행됨!")
                for liq_pos in liquidated_positions:
                    print(f"   └─ {liq_pos['symbol']} {liq_pos['side']} 청산")
                break
            else:
                print(f"✅ 포지션 유지됨")
                
        else:
            print(f"❌ 포지션이 없습니다 (이미 청산됨?)")
            break
        
        time.sleep(1)  # 1초 대기
    
    print("\n" + "="*60)
    print("🧪 자동 청산 시스템 테스트 완료!")
    
    # 최종 상태 확인
    final_summary = cross_manager.get_cross_summary()
    print(f"\n📊 최종 상태:")
    print(f"잔여 포지션: {len(final_summary['positions'])}개")
    print(f"총 증거금: ${final_summary['margin_balance']:,.2f}")
    print(f"사용 증거금: ${final_summary['total_margin_used']:,.2f}")
    print(f"미실현 손익: ${final_summary['total_unrealized_pnl']:,.2f}")
    
    # 거래 내역 확인
    transactions, _ = cross_manager.get_cross_transactions(10)
    print(f"\n📋 최근 거래 내역 ({len(transactions)}개):")
    for tx in transactions[:3]:  # 최근 3개만 표시
        tx_type = tx['type']
        symbol = tx['symbol']
        side = tx.get('side', '')
        timestamp = tx['timestamp'][:19]  # 날짜만
        
        if tx_type == 'AUTO_LIQUIDATION':
            pnl_pct = tx.get('pnl_percentage', 0)
            print(f"   🔥 {timestamp}: {symbol} {side} 자동청산 (손실률: {pnl_pct:.1f}%)")
        elif tx_type == 'OPEN_POSITION':
            leverage = tx.get('leverage', 1)
            print(f"   📈 {timestamp}: {symbol} {side} 진입 ({leverage}x)")
        elif tx_type == 'CLOSE_POSITION':
            realized_pnl = tx.get('realized_pnl', 0)
            print(f"   💰 {timestamp}: {symbol} {side} 청산 (${realized_pnl:+,.2f})")

if __name__ == "__main__":
    test_auto_liquidation()
