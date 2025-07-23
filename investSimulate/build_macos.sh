#!/bin/bash
# Genius Coin Manager macOS 빌드 스크립트
# 이 스크립트는 macOS에서 .app 번들과 .dmg 파일을 생성합니다.

echo "=========================================="
echo "Genius Coin Manager macOS Build Script"
echo "=========================================="
echo

# 색상 정의
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 플랫폼 확인
if [[ "$OSTYPE" != "darwin"* ]]; then
    echo -e "${YELLOW}경고: 이 스크립트는 macOS용입니다.${NC}"
    echo "현재 플랫폼: $OSTYPE"
    read -p "계속하시겠습니까? (y/n): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# Python 가상환경 활성화
echo "가상환경 확인 중..."
if [ -d "venv" ]; then
    source venv/bin/activate
    echo "✓ 가상환경 활성화: venv"
elif [ -d ".venv" ]; then
    source .venv/bin/activate
    echo "✓ 가상환경 활성화: .venv"
elif [ -d "env" ]; then
    source env/bin/activate
    echo "✓ 가상환경 활성화: env"
fi

# 필요한 패키지 설치
echo
echo "필수 패키지 설치 중..."
pip install --upgrade pip
pip install pyinstaller

# requirements.txt가 있으면 설치
if [ -f "requirements.txt" ]; then
    pip install -r requirements.txt
else
    echo -e "${YELLOW}경고: requirements.txt 파일을 찾을 수 없습니다.${NC}"
    # 최소 필수 패키지 설치
    pip install PyQt5 pandas numpy matplotlib mplfinance python-binance \
                websocket-client python-dotenv pyqtgraph ta requests aiohttp
fi

# 이전 빌드 정리
echo
echo "이전 빌드 파일 정리 중..."
rm -rf build dist __pycache__
rm -f *.spec.log
rm -rf GeniusCoinManager.app
rm -f GeniusCoinManager.dmg

# .env 파일 확인
echo
if [ -f ".env" ]; then
    echo -e "${GREEN}✓ .env 파일을 찾았습니다. 빌드에 포함됩니다.${NC}"
else
    echo -e "${YELLOW}⚠ 경고: .env 파일을 찾을 수 없습니다!${NC}"
    echo "API 키가 필요한 경우 .env 파일을 생성해주세요."
    echo
    echo ".env 파일 예시:"
    echo "BINANCE_API_KEY=your_api_key_here"
    echo "BINANCE_API_SECRET=your_api_secret_here"
    echo
    read -p ".env 파일 없이 계속하시겠습니까? (y/n): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# PyInstaller로 빌드
echo
echo "PyInstaller로 빌드 시작..."
echo "이 작업은 몇 분 정도 소요될 수 있습니다..."

if [ ! -f "genius_coin_manager.spec" ]; then
    echo -e "${RED}오류: genius_coin_manager.spec 파일을 찾을 수 없습니다!${NC}"
    exit 1
fi

pyinstaller genius_coin_manager.spec --clean --noconfirm

# 빌드 결과 확인
echo
if [ -d "dist/GeniusCoinManager.app" ]; then
    echo -e "${GREEN}=========================================="
    echo "✓ 앱 번들 빌드 성공!"
    echo "앱 위치: dist/GeniusCoinManager.app"
    echo "==========================================${NC}"
    
    # DMG 생성 옵션
    echo
    read -p "DMG 인스톨러를 생성하시겠습니까? (y/n): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        create_dmg
    fi
    
    # Applications 폴더에 복사 옵션
    echo
    read -p "Applications 폴더에 앱을 설치하시겠습니까? (y/n): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo "관리자 권한이 필요할 수 있습니다..."
        sudo cp -R dist/GeniusCoinManager.app /Applications/
        echo -e "${GREEN}✓ Applications 폴더에 설치되었습니다.${NC}"
    fi
else
    echo -e "${RED}=========================================="
    echo "✗ 빌드 실패!"
    echo "오류를 확인하고 다시 시도해주세요."
    echo "==========================================${NC}"
    exit 1
fi

# DMG 생성 함수
create_dmg() {
    echo
    echo "DMG 인스톨러 생성 중..."
    
    # create-dmg 설치 확인
    if ! command -v create-dmg &> /dev/null; then
        echo "create-dmg를 설치합니다..."
        if command -v brew &> /dev/null; then
            brew install create-dmg
        else
            echo -e "${YELLOW}경고: Homebrew가 설치되어 있지 않습니다.${NC}"
            echo "수동 DMG 생성 방법을 사용합니다..."
            create_dmg_manual
            return
        fi
    fi
    
    # create-dmg를 사용한 DMG 생성
    if command -v create-dmg &> /dev/null; then
        create-dmg \
            --volname "Genius Coin Manager" \
            --volicon "assets/icon.icns" \
            --window-pos 200 120 \
            --window-size 600 400 \
            --icon-size 100 \
            --icon "GeniusCoinManager.app" 150 200 \
            --hide-extension "GeniusCoinManager.app" \
            --app-drop-link 450 200 \
            --background "assets/dmg_background.png" \
            "GeniusCoinManager.dmg" \
            "dist/"
        
        if [ -f "GeniusCoinManager.dmg" ]; then
            echo -e "${GREEN}✓ DMG 파일이 생성되었습니다: GeniusCoinManager.dmg${NC}"
        else
            echo -e "${YELLOW}create-dmg 실패. 수동 방법으로 시도합니다...${NC}"
            create_dmg_manual
        fi
    else
        create_dmg_manual
    fi
}

# 수동 DMG 생성 함수
create_dmg_manual() {
    echo "수동으로 DMG 생성 중..."
    
    # 임시 디렉토리 생성
    DMG_TEMP="dmg_temp"
    rm -rf "$DMG_TEMP"
    mkdir -p "$DMG_TEMP"
    
    # 앱 복사
    cp -R "dist/GeniusCoinManager.app" "$DMG_TEMP/"
    
    # Applications 심볼릭 링크 생성
    ln -s /Applications "$DMG_TEMP/Applications"
    
    # DMG 생성
    hdiutil create -volname "Genius Coin Manager" \
                   -srcfolder "$DMG_TEMP" \
                   -ov -format UDZO \
                   "GeniusCoinManager.dmg"
    
    # 임시 디렉토리 삭제
    rm -rf "$DMG_TEMP"
    
    if [ -f "GeniusCoinManager.dmg" ]; then
        echo -e "${GREEN}✓ DMG 파일이 생성되었습니다: GeniusCoinManager.dmg${NC}"
    else
        echo -e "${RED}✗ DMG 생성 실패${NC}"
    fi
}

echo
echo -e "${GREEN}빌드 프로세스가 완료되었습니다!${NC}"