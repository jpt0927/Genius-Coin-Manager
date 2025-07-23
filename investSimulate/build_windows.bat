@echo off
REM Genius Coin Manager Windows 빌드 스크립트
REM 이 스크립트는 Windows에서 exe 파일을 생성합니다.

echo ========================================
echo Genius Coin Manager Windows Build Script
echo ========================================
echo.

REM Python 가상환경 활성화 (있는 경우)
if exist "venv\Scripts\activate.bat" (
    echo 가상환경 활성화 중...
    call venv\Scripts\activate.bat
) else if exist ".venv\Scripts\activate.bat" (
    echo 가상환경 활성화 중...
    call .venv\Scripts\activate.bat
)

REM 필요한 패키지 설치 확인
echo.
echo 필수 패키지 확인 중...
pip install --upgrade pip
pip install pyinstaller
pip install -r requirements.txt

REM 이전 빌드 정리
echo.
echo 이전 빌드 파일 정리 중...
if exist "build" rmdir /s /q build
if exist "dist" rmdir /s /q dist
if exist "GeniusCoinManager.exe" del /f /q GeniusCoinManager.exe

REM .env 파일 확인
echo.
if exist ".env" (
    echo .env 파일을 찾았습니다. 빌드에 포함됩니다.
) else (
    echo 경고: .env 파일을 찾을 수 없습니다!
    echo API 키가 필요한 경우 .env 파일을 생성해주세요.
    echo.
    choice /C YN /M ".env 파일 없이 계속하시겠습니까?"
    if errorlevel 2 goto :END
)

REM PyInstaller로 빌드
echo.
echo PyInstaller로 빌드 시작...
echo 이 작업은 몇 분 정도 소요될 수 있습니다...
pyinstaller genius_coin_manager.spec --clean --noconfirm

REM 빌드 결과 확인
echo.
if exist "dist\GeniusCoinManager.exe" (
    echo ========================================
    echo 빌드 성공!
    echo 실행 파일: dist\GeniusCoinManager.exe
    echo ========================================
    
    REM 바탕화면에 복사 옵션
    echo.
    choice /C YN /M "바탕화면에 실행 파일을 복사하시겠습니까?"
    if errorlevel 1 (
        copy "dist\GeniusCoinManager.exe" "%USERPROFILE%\Desktop\"
        echo 바탕화면에 복사되었습니다.
    )
) else (
    echo ========================================
    echo 빌드 실패!
    echo 오류를 확인하고 다시 시도해주세요.
    echo ========================================
)

:END
echo.
pause