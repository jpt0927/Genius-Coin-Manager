#!/usr/bin/env python3
"""
Genius Coin Manager macOS 빌드 스크립트 (Python 버전)
크로스 플랫폼 호환성을 위한 Python 빌드 스크립트
"""

import os
import sys
import shutil
import subprocess
import platform

# 색상 코드
class Colors:
    RED = '\033[0;31m'
    GREEN = '\033[0;32m'
    YELLOW = '\033[1;33m'
    NC = '\033[0m'  # No Color

def print_header():
    """헤더 출력"""
    print("=" * 50)
    print("Genius Coin Manager macOS Build Script")
    print("=" * 50)
    print()

def check_platform():
    """플랫폼 확인"""
    if platform.system() != 'Darwin':
        print(f"{Colors.YELLOW}경고: 이 스크립트는 macOS용입니다.{Colors.NC}")
        print(f"현재 플랫폼: {platform.system()}")
        response = input("계속하시겠습니까? (y/n): ")
        if response.lower() != 'y':
            sys.exit(0)

def activate_venv():
    """가상환경 활성화"""
    venv_paths = ['venv', '.venv', 'env', '.env']
    for venv in venv_paths:
        activate_script = os.path.join(venv, 'bin', 'activate')
        if os.path.exists(activate_script):
            print(f"✓ 가상환경 발견: {venv}")
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
        print(f"{Colors.YELLOW}경고: requirements.txt 파일을 찾을 수 없습니다.{Colors.NC}")
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
    files_to_remove = ['*.spec.log', 'GeniusCoinManager.dmg']
    app_to_remove = 'GeniusCoinManager.app'
    
    for dir_name in dirs_to_remove:
        if os.path.exists(dir_name):
            shutil.rmtree(dir_name)
            print(f"  제거됨: {dir_name}/")
    
    if os.path.exists(app_to_remove):
        shutil.rmtree(app_to_remove)
        print(f"  제거됨: {app_to_remove}")
    
    import glob
    for pattern in files_to_remove:
        for file in glob.glob(pattern):
            os.remove(file)
            print(f"  제거됨: {file}")

def check_env_file():
    """env 파일 확인"""
    print("\n환경 설정 파일 확인 중...")
    
    if os.path.exists('.env'):
        print(f"{Colors.GREEN}✓ .env 파일을 찾았습니다. 빌드에 포함됩니다.{Colors.NC}")
        return True
    else:
        print(f"{Colors.YELLOW}⚠ 경고: .env 파일을 찾을 수 없습니다!{Colors.NC}")
        print("  API 키가 필요한 경우 .env 파일을 생성해주세요.")
        print("\n.env 파일 예시:")
        print("  BINANCE_API_KEY=your_api_key_here")
        print("  BINANCE_API_SECRET=your_api_secret_here")
        
        response = input("\n.env 파일 없이 계속하시겠습니까? (y/n): ")
        return response.lower() == 'y'

def build_app():
    """PyInstaller로 앱 빌드"""
    print("\nPyInstaller로 빌드 시작...")
    print("이 작업은 몇 분 정도 소요될 수 있습니다...")
    
    # spec 파일 확인
    if not os.path.exists('genius_coin_manager.spec'):
        print(f"{Colors.RED}오류: genius_coin_manager.spec 파일을 찾을 수 없습니다!{Colors.NC}")
        return False
    
    # PyInstaller 실행
    result = subprocess.run([
        sys.executable, '-m', 'PyInstaller',
        'genius_coin_manager.spec',
        '--clean',
        '--noconfirm'
    ], capture_output=True, text=True)
    
    if result.returncode != 0:
        print(f"\n{Colors.RED}빌드 실패!{Colors.NC}")
        print("오류 내용:")
        print(result.stderr)
        return False
    
    return True

def create_dmg():
    """DMG 파일 생성"""
    print("\nDMG 인스톨러 생성 중...")
    
    # create-dmg 사용 가능 여부 확인
    create_dmg_available = subprocess.run(['which', 'create-dmg'], 
                                        capture_output=True).returncode == 0
    
    if not create_dmg_available:
        print("create-dmg를 설치합니다...")
        # Homebrew 확인
        brew_available = subprocess.run(['which', 'brew'], 
                                      capture_output=True).returncode == 0
        if brew_available:
            subprocess.run(['brew', 'install', 'create-dmg'])
            create_dmg_available = True
        else:
            print(f"{Colors.YELLOW}경고: Homebrew가 설치되어 있지 않습니다.{Colors.NC}")
    
    if create_dmg_available:
        # create-dmg 사용
        cmd = [
            'create-dmg',
            '--volname', 'Genius Coin Manager',
            '--window-pos', '200', '120',
            '--window-size', '600', '400',
            '--icon-size', '100',
            '--icon', 'GeniusCoinManager.app', '150', '200',
            '--hide-extension', 'GeniusCoinManager.app',
            '--app-drop-link', '450', '200',
        ]
        
        # 아이콘이 있으면 추가
        if os.path.exists('assets/icon.icns'):
            cmd.extend(['--volicon', 'assets/icon.icns'])
        
        # 배경 이미지가 있으면 추가
        if os.path.exists('assets/dmg_background.png'):
            cmd.extend(['--background', 'assets/dmg_background.png'])
        
        cmd.extend(['GeniusCoinManager.dmg', 'dist/'])
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode == 0:
            print(f"{Colors.GREEN}✓ DMG 파일이 생성되었습니다: GeniusCoinManager.dmg{Colors.NC}")
            return True
        else:
            print(f"{Colors.YELLOW}create-dmg 실패. 수동 방법으로 시도합니다...{Colors.NC}")
    
    # 수동 DMG 생성
    return create_dmg_manual()

def create_dmg_manual():
    """수동으로 DMG 생성"""
    print("수동으로 DMG 생성 중...")
    
    # 임시 디렉토리 생성
    dmg_temp = "dmg_temp"
    if os.path.exists(dmg_temp):
        shutil.rmtree(dmg_temp)
    os.makedirs(dmg_temp)
    
    # 앱 복사
    shutil.copytree("dist/GeniusCoinManager.app", 
                    os.path.join(dmg_temp, "GeniusCoinManager.app"))
    
    # Applications 심볼릭 링크 생성
    os.symlink("/Applications", os.path.join(dmg_temp, "Applications"))
    
    # DMG 생성
    result = subprocess.run([
        'hdiutil', 'create',
        '-volname', 'Genius Coin Manager',
        '-srcfolder', dmg_temp,
        '-ov',
        '-format', 'UDZO',
        'GeniusCoinManager.dmg'
    ], capture_output=True, text=True)
    
    # 임시 디렉토리 삭제
    shutil.rmtree(dmg_temp)
    
    if result.returncode == 0:
        print(f"{Colors.GREEN}✓ DMG 파일이 생성되었습니다: GeniusCoinManager.dmg{Colors.NC}")
        return True
    else:
        print(f"{Colors.RED}✗ DMG 생성 실패{Colors.NC}")
        return False

def install_to_applications():
    """Applications 폴더에 설치"""
    app_path = "dist/GeniusCoinManager.app"
    if not os.path.exists(app_path):
        return False
    
    response = input("\nApplications 폴더에 앱을 설치하시겠습니까? (y/n): ")
    if response.lower() == 'y':
        print("관리자 권한이 필요할 수 있습니다...")
        result = subprocess.run(['sudo', 'cp', '-R', app_path, '/Applications/'])
        if result.returncode == 0:
            print(f"{Colors.GREEN}✓ Applications 폴더에 설치되었습니다.{Colors.NC}")
            return True
    return False

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
    
    # 앱 빌드
    if build_app():
        print(f"\n{Colors.GREEN}" + "=" * 50)
        print("✓ 앱 번들 빌드 성공!")
        print(f"앱 위치: {os.path.abspath('dist/GeniusCoinManager.app')}")
        print("=" * 50 + f"{Colors.NC}")
        
        # DMG 생성 옵션
        response = input("\nDMG 인스톨러를 생성하시겠습니까? (y/n): ")
        if response.lower() == 'y':
            create_dmg()
        
        # Applications 폴더 설치 옵션
        install_to_applications()
        
        print(f"\n{Colors.GREEN}빌드 프로세스가 완료되었습니다!{Colors.NC}")
    else:
        print(f"\n{Colors.RED}" + "=" * 50)
        print("✗ 빌드 실패!")
        print("오류를 확인하고 다시 시도해주세요.")
        print("=" * 50 + f"{Colors.NC}")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n사용자에 의해 취소되었습니다.")
    except Exception as e:
        print(f"\n{Colors.RED}오류 발생: {e}{Colors.NC}")
        import traceback
        traceback.print_exc()