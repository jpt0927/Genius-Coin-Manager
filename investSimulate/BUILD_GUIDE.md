# Genius Coin Manager 빌드 가이드

이 문서는 Genius Coin Manager를 Windows(exe)와 macOS(dmg)용 실행 파일로 빌드하는 방법을 설명합니다.

## 목차
- [사전 요구사항](#사전-요구사항)
- [빌드 준비](#빌드-준비)
- [Windows 빌드](#windows-빌드)
- [macOS 빌드](#macos-빌드)
- [문제 해결](#문제-해결)

## 사전 요구사항

### 공통 요구사항
- Python 3.8 이상
- Git
- 인터넷 연결 (패키지 다운로드용)

### Windows 전용
- Windows 10 이상
- Visual Studio Build Tools (선택사항)
- NSIS (인스톨러 생성용, 선택사항)

### macOS 전용
- macOS 10.13 (High Sierra) 이상
- Xcode Command Line Tools
- Homebrew (권장)

## 빌드 준비

### 1. 소스 코드 다운로드
```bash
git clone https://github.com/yourusername/Genius-Coin-Manager.git
cd Genius-Coin-Manager/investSimulate
```

### 2. 가상환경 생성 및 활성화

**Windows:**
```cmd
python -m venv venv
venv\Scripts\activate
```

**macOS/Linux:**
```bash
python3 -m venv venv
source venv/bin/activate
```

### 3. 의존성 설치
```bash
pip install -r requirements.txt
pip install pyinstaller
```

### 4. .env 파일 생성
API 키가 필요한 경우 `.env` 파일을 생성합니다:

```env
BINANCE_API_KEY=your_api_key_here
BINANCE_API_SECRET=your_api_secret_here
```

⚠️ **주의**: 실제 API 키를 빌드에 포함시킬 때는 보안에 주의하세요.

## Windows 빌드

### 방법 1: 배치 스크립트 사용 (권장)
```cmd
build_windows.bat
```

### 방법 2: Python 스크립트 사용
```cmd
python build_windows.py
```

### 방법 3: 수동 빌드
```cmd
# 이전 빌드 정리
rmdir /s /q build dist

# PyInstaller 실행
pyinstaller genius_coin_manager.spec --clean --noconfirm
```

### 빌드 결과
- 실행 파일 위치: `dist/GeniusCoinManager.exe`
- 바탕화면에 복사 옵션 제공

### Windows 인스톨러 생성 (선택사항)
NSIS가 설치되어 있다면 `build_windows.py` 실행 시 인스톨러 생성 옵션이 제공됩니다.

## macOS 빌드

### 방법 1: Shell 스크립트 사용 (권장)
```bash
chmod +x build_macos.sh
./build_macos.sh
```

### 방법 2: Python 스크립트 사용
```bash
python3 build_macos.py
```

### 방법 3: 수동 빌드
```bash
# 이전 빌드 정리
rm -rf build dist

# PyInstaller 실행
pyinstaller genius_coin_manager.spec --clean --noconfirm

# DMG 생성 (선택사항)
hdiutil create -volname "Genius Coin Manager" \
               -srcfolder dist/ \
               -ov -format UDZO \
               GeniusCoinManager.dmg
```

### 빌드 결과
- 앱 번들 위치: `dist/GeniusCoinManager.app`
- DMG 파일: `GeniusCoinManager.dmg` (선택사항)
- Applications 폴더 설치 옵션 제공

## 빌드 후 테스트

### Windows
1. `dist/GeniusCoinManager.exe` 실행
2. 모든 기능이 정상 작동하는지 확인
3. 특히 네트워크 연결 및 WebSocket 기능 테스트

### macOS
1. `dist/GeniusCoinManager.app` 실행
2. 처음 실행 시 보안 경고가 나타나면:
   - 시스템 환경설정 > 보안 및 개인 정보 보호
   - "확인된 개발자가 아님" 메시지 옆의 "열기" 클릭

## 문제 해결

### 공통 문제

#### "Module not found" 오류
```bash
pip install [missing_module]
```

#### PyInstaller 버전 충돌
```bash
pip uninstall pyinstaller
pip install pyinstaller==5.13.2
```

### Windows 특정 문제

#### 바이러스 백신 오탐지
- Windows Defender나 백신 프로그램에서 예외 처리
- 코드 서명 인증서 사용 고려

#### DLL 파일 누락
- Visual C++ Redistributable 설치
- Python을 공식 사이트에서 다운로드하여 재설치

### macOS 특정 문제

#### "앱이 손상되었습니다" 오류
```bash
xattr -cr /Applications/GeniusCoinManager.app
```

#### 코드 서명 없음 경고
- Apple Developer 계정으로 코드 서명 (유료)
- 또는 사용자가 수동으로 허용

## 배포 준비

### 버전 관리
1. `main_unified.py`에서 버전 번호 업데이트
2. `genius_coin_manager.spec`에서 버전 정보 업데이트

### 릴리스 체크리스트
- [ ] 모든 테스트 통과
- [ ] .env 파일에 실제 API 키가 없는지 확인
- [ ] 빌드 파일 크기 확인 (너무 크지 않은지)
- [ ] 다른 컴퓨터에서 테스트
- [ ] 바이러스 검사 수행

## 추가 옵션

### 자동 업데이트 기능
PyUpdater나 similar 도구를 사용하여 자동 업데이트 기능 추가 가능

### 다국어 지원
Qt Linguist를 사용하여 다국어 번역 파일 생성 및 포함

### 플러그인 시스템
동적 로딩을 위한 플러그인 디렉토리 구조 추가

## 지원 및 문의

문제가 발생하거나 질문이 있으시면:
- GitHub Issues: [링크]
- 이메일: support@geniuscoinmanager.com

---

마지막 업데이트: 2024년 1월