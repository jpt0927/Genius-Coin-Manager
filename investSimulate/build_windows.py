#!/usr/bin/env python3
"""
Genius Coin Manager Windows 빌드 스크립트 (Python 버전)
크로스 플랫폼 호환성을 위한 Python 빌드 스크립트
"""

import os
import sys
import shutil
import subprocess
import platform

def print_header():
    """헤더 출력"""
    print("=" * 50)
    print("Genius Coin Manager Windows Build Script")
    print("=" * 50)
    print()

def check_platform():
    """플랫폼 확인"""
    if platform.system() != 'Windows':
        print("경고: 이 스크립트는 Windows용입니다.")
        print(f"현재 플랫폼: {platform.system()}")
        response = input("계속하시겠습니까? (y/n): ")
        if response.lower() != 'y':
            sys.exit(0)

def activate_venv():
    """가상환경 활성화"""
    venv_paths = ['venv', '.venv', 'env', '.env']
    for venv in venv_paths:
        activate_script = os.path.join(venv, 'Scripts', 'activate.bat')
        if os.path.exists(activate_script):
            print(f"가상환경 발견: {venv}")
            return venv
    return None

def install_requirements():
    """필수 패키지 설치"""
    print("\n필수 패키지 설치 중...")
    
    # pip 업그레이드
    subprocess.run([sys.executable, '-m', 'pip', 'install', '--upgrade', 'pip'])
    
    # PyInstaller 설치
    subprocess.run([sys.executable, '-m', 'pip', 'install', 'pyinstaller'])
    
    # requirements.txt가 있으면 설치
    if os.path.exists('requirements.txt'):
        subprocess.run([sys.executable, '-m', 'pip', 'install', '-r', 'requirements.txt'])
    else:
        print("경고: requirements.txt 파일을 찾을 수 없습니다.")
        # 최소 필수 패키지 설치
        essential_packages = [
            'PyQt5',
            'pandas',
            'numpy',
            'matplotlib',
            'mplfinance',
            'python-binance',
            'websocket-client',
            'python-dotenv',
            'pyqtgraph',
            'ta',
            'requests',
            'aiohttp'
        ]
        for package in essential_packages:
            subprocess.run([sys.executable, '-m', 'pip', 'install', package])

def clean_build():
    """이전 빌드 정리"""
    print("\n이전 빌드 파일 정리 중...")
    
    dirs_to_remove = ['build', 'dist', '__pycache__']
    files_to_remove = ['GeniusCoinManager.exe', '*.spec.log']
    
    for dir_name in dirs_to_remove:
        if os.path.exists(dir_name):
            shutil.rmtree(dir_name)
            print(f"  제거됨: {dir_name}/")
    
    for pattern in files_to_remove:
        import glob
        for file in glob.glob(pattern):
            os.remove(file)
            print(f"  제거됨: {file}")

def check_env_file():
    """env 파일 확인"""
    print("\n환경 설정 파일 확인 중...")
    
    if os.path.exists('.env'):
        print("✓ .env 파일을 찾았습니다. 빌드에 포함됩니다.")
        return True
    else:
        print("⚠ 경고: .env 파일을 찾을 수 없습니다!")
        print("  API 키가 필요한 경우 .env 파일을 생성해주세요.")
        print("\n.env 파일 예시:")
        print("  BINANCE_API_KEY=your_api_key_here")
        print("  BINANCE_API_SECRET=your_api_secret_here")
        
        response = input("\n.env 파일 없이 계속하시겠습니까? (y/n): ")
        return response.lower() == 'y'

def build_exe():
    """PyInstaller로 exe 빌드"""
    print("\nPyInstaller로 빌드 시작...")
    print("이 작업은 몇 분 정도 소요될 수 있습니다...")
    
    # spec 파일 확인
    if not os.path.exists('genius_coin_manager.spec'):
        print("오류: genius_coin_manager.spec 파일을 찾을 수 없습니다!")
        return False
    
    # PyInstaller 실행
    result = subprocess.run([
        sys.executable, '-m', 'PyInstaller',
        'genius_coin_manager.spec',
        '--clean',
        '--noconfirm'
    ], capture_output=True, text=True)
    
    if result.returncode != 0:
        print("\n빌드 실패!")
        print("오류 내용:")
        print(result.stderr)
        return False
    
    return True

def copy_to_desktop():
    """바탕화면에 복사"""
    exe_path = os.path.join('dist', 'GeniusCoinManager.exe')
    
    if not os.path.exists(exe_path):
        return False
    
    desktop_path = os.path.join(os.path.expanduser('~'), 'Desktop')
    if os.path.exists(desktop_path):
        response = input("\n바탕화면에 실행 파일을 복사하시겠습니까? (y/n): ")
        if response.lower() == 'y':
            shutil.copy2(exe_path, desktop_path)
            print(f"✓ 바탕화면에 복사되었습니다: {desktop_path}")
            return True
    
    return False

def create_installer():
    """NSIS를 사용한 인스톨러 생성 (선택사항)"""
    print("\n인스톨러 생성 옵션")
    response = input("NSIS 인스톨러를 생성하시겠습니까? (y/n): ")
    
    if response.lower() != 'y':
        return
    
    # NSIS 스크립트 생성
    nsis_script = """
!define APP_NAME "Genius Coin Manager"
!define APP_VERSION "1.0.0"
!define APP_PUBLISHER "Genius"
!define APP_ICON "assets\\icon.ico"

Name "${APP_NAME}"
OutFile "GeniusCoinManager_Setup.exe"
InstallDir "$PROGRAMFILES\\${APP_NAME}"
RequestExecutionLevel admin

Section "MainSection" SEC01
    SetOutPath "$INSTDIR"
    File "dist\\GeniusCoinManager.exe"
    File ".env"
    
    CreateDirectory "$SMPROGRAMS\\${APP_NAME}"
    CreateShortcut "$SMPROGRAMS\\${APP_NAME}\\${APP_NAME}.lnk" "$INSTDIR\\GeniusCoinManager.exe"
    CreateShortcut "$DESKTOP\\${APP_NAME}.lnk" "$INSTDIR\\GeniusCoinManager.exe"
SectionEnd

Section "Uninstall"
    Delete "$INSTDIR\\GeniusCoinManager.exe"
    Delete "$INSTDIR\\.env"
    Delete "$SMPROGRAMS\\${APP_NAME}\\${APP_NAME}.lnk"
    Delete "$DESKTOP\\${APP_NAME}.lnk"
    RMDir "$SMPROGRAMS\\${APP_NAME}"
    RMDir "$INSTDIR"
SectionEnd
"""
    
    with open('installer.nsi', 'w') as f:
        f.write(nsis_script)
    
    print("NSIS 스크립트가 생성되었습니다: installer.nsi")
    print("NSIS를 설치한 후 다음 명령을 실행하세요:")
    print("  makensis installer.nsi")

def main():
    """메인 함수"""
    print_header()
    
    # 플랫폼 확인
    check_platform()
    
    # 가상환경 확인
    venv = activate_venv()
    if venv:
        print(f"가상환경 사용: {venv}")
    
    # 필수 패키지 설치
    install_requirements()
    
    # 이전 빌드 정리
    clean_build()
    
    # .env 파일 확인
    if not check_env_file():
        print("\n빌드를 취소했습니다.")
        return
    
    # exe 빌드
    if build_exe():
        print("\n" + "=" * 50)
        print("✓ 빌드 성공!")
        print(f"실행 파일: {os.path.abspath('dist/GeniusCoinManager.exe')}")
        print("=" * 50)
        
        # 바탕화면 복사
        copy_to_desktop()
        
        # 인스톨러 생성 옵션
        create_installer()
    else:
        print("\n" + "=" * 50)
        print("✗ 빌드 실패!")
        print("오류를 확인하고 다시 시도해주세요.")
        print("=" * 50)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n사용자에 의해 취소되었습니다.")
    except Exception as e:
        print(f"\n오류 발생: {e}")
        import traceback
        traceback.print_exc()
    
    input("\n종료하려면 Enter 키를 누르세요...")