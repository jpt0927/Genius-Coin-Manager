# realmain.py (수정 완료)

import sys
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QHBoxLayout, 
                             QPushButton, QVBoxLayout, QLabel)
from PyQt5.QtGui import QFont, QIcon
from PyQt5.QtCore import Qt, QSize

# 백테스터 메인 윈도우 import
from backtest.main import MainWindow as BacktestWindow

# ⭐ [수정된 부분] 새로운 gui_app.py의 TradingGUI 클래스를 import 합니다.
# 이전 SimulateMainWindow 대신 TradingGUI를 SimulateWindow 라는 별칭으로 가져옵니다.
from investSimulate.gui_app import TradingGUI as SimulateWindow

class MainLauncher(QMainWindow):
    def __init__(self):
        super().__init__()
        self.backtest_win = None
        self.simulate_win = None

        self.setWindowTitle("🚀 Genius Coin Manager")
        self.setGeometry(400, 400, 700, 400)

        # 폰트 설정
        self.app_font = QFont("NanumGothic", 12)
        try:
             # 아이콘 설정 (아이콘 파일이 필요하다면 경로 지정)
             # self.setWindowIcon(QIcon('path/to/icon.png'))
            pass
        except:
            pass
        
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        # 전체 레이아웃
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(40, 40, 40, 40)
        main_layout.setSpacing(20)

        # 제목 라벨
        title_label = QLabel("Genius Coin Manager")
        title_label.setFont(QFont("NanumGothic", 28, QFont.Bold))
        title_label.setAlignment(Qt.AlignCenter)
        
        # 버튼을 담을 레이아웃
        buttons_layout = QHBoxLayout()
        buttons_layout.setSpacing(30)

        # 백테스트 버튼
        self.backtest_btn = QPushButton("📈\n\n백테스트 실행")
        self.backtest_btn.clicked.connect(self.launch_backtester)

        # 모의투자 버튼
        self.simulate_btn = QPushButton("💻\n\n모의투자 실행")
        self.simulate_btn.clicked.connect(self.launch_simulator)

        # 버튼 스타일링
        for btn in [self.backtest_btn, self.simulate_btn]:
            btn.setFont(QFont("NanumGothic", 16, QFont.Bold))
            btn.setIconSize(QSize(64, 64))
            btn.setMinimumSize(300, 200)
            btn.setStyleSheet("""
                QPushButton {
                    background-color: #4CAF50; /* Green */
                    border: none;
                    color: white;
                    padding: 15px 32px;
                    text-align: center;
                    text-decoration: none;
                    font-size: 16px;
                    margin: 4px 2px;
                    border-radius: 10px;
                }
                QPushButton:hover {
                    background-color: #45a049;
                }
                QPushButton:pressed {
                    background-color: #3e8e41;
                }
            """)

        buttons_layout.addWidget(self.backtest_btn)
        buttons_layout.addWidget(self.simulate_btn)

        main_layout.addWidget(title_label)
        main_layout.addStretch()
        main_layout.addLayout(buttons_layout)
        main_layout.addStretch()
    
    def launch_backtester(self):
        """백테스터 윈도우를 실행합니다."""
        # 창이 이미 열려있으면 새로 열지 않고 기존 창을 활성화합니다.
        if not self.backtest_win or not self.backtest_win.isVisible():
            self.backtest_win = BacktestWindow()
            self.backtest_win.show()
        else:
            self.backtest_win.activateWindow()

    def launch_simulator(self):
        """모의투자 윈도우를 실행합니다."""
        if not self.simulate_win or not self.simulate_win.isVisible():
            # ⭐ [수정된 부분] SimulateWindow (즉, TradingGUI 클래스)를 인스턴스화합니다.
            self.simulate_win = SimulateWindow()
            self.simulate_win.show()
        else:
            self.simulate_win.activateWindow()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    
    # 나눔고딕 폰트 적용 시도
    try:
        app_font = QFont("NanumGothic", 10)
        app.setFont(app_font)
    except Exception as e:
        print(f"나눔고딕 폰트를 찾을 수 없습니다. 기본 폰트로 실행됩니다. (오류: {e})")
        
    launcher = MainLauncher()
    launcher.show()
    sys.exit(app.exec_())