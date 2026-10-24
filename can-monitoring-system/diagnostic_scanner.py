import sys
import time
import can
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QComboBox,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QGroupBox,
    QTextEdit,
)
from PySide6.QtCore import QThread, Signal, Qt
from PySide6.QtGui import QFont

COM_PORT = "COM6"
BITRATE = 500000


# ==========================================
# 1. CAN 진단 통신 스레드
# ==========================================
class DiagnosticWorker(QThread):
    dtc_response = Signal(dict)
    log_signal = Signal(str)

    def __init__(self, port, bitrate):
        super().__init__()
        self.port = port
        self.bitrate = bitrate
        self.running = True
        self.bus = None

    def run(self):
        try:
            self.bus = can.interface.Bus(
                interface="slcan", channel=self.port, bitrate=self.bitrate
            )
            self.log_signal.emit(f"🟢 CANable 진단 인터페이스 연결 성공 ({self.port})")
        except Exception as e:
            self.log_signal.emit(f"🔴 연결 실패: {e}")
            return

        while self.running:
            try:
                msg = self.bus.recv(timeout=0.1)
                # 진단 응답 메세지 (CAN ID: 0x7E8)
                if msg and msg.arbitration_id == 0x7E8:
                    dtc_code = (msg.data[0] << 8) | msg.data[1]  # 예: 0xB101
                    sensor_status = msg.data[
                        2
                    ]  # 0: 정상, 1: 센서 단선, 2: 액추에이터 고장
                    lux_value = (msg.data[3] << 8) | msg.data[4]

                    response_data = {
                        "dtc": dtc_code,
                        "status": sensor_status,
                        "lux": lux_value,
                    }
                    self.dtc_response.emit(response_data)
                    self.log_signal.emit(
                        f"[RX 0x7E8] 진단 응답 수신: DTC=0x{dtc_code:04X}, Status={sensor_status}"
                    )
            except Exception:
                pass

        if self.bus:
            self.bus.shutdown()

    def send_diag_request(self, service_id, param=0x00):
        """진단 요청 전송 (CAN ID: 0x7E0)"""
        if self.bus:
            # Data[0]: Service ID (0x19: Read DTC, 0x14: Clear DTC, 0x2F: Fault Inject)
            msg = can.Message(
                arbitration_id=0x7E0,
                data=[service_id, param, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00],
                is_extended_id=False,
            )
            try:
                self.bus.send(msg)

                # Service ID별 상세 로그 출력
                if service_id == 0x19:
                    log_msg = "[TX 0x7E0] Service 0x19: Read DTC (고장 코드 읽기 요청)"
                elif service_id == 0x14:
                    log_msg = "[TX 0x7E0] Service 0x14: Clear DTC (고장 코드 소거 요청)"
                elif service_id == 0x2F:
                    status_str = (
                        "Fault INJECT (0x01)"
                        if param == 0x01
                        else "Fault RESTORE (0x00)"
                    )
                    log_msg = f"[TX 0x7E0] Service 0x2F: {status_str}"
                else:
                    log_msg = f"[TX 0x7E0] Service ID: 0x{service_id:02X}, Param: 0x{param:02X}"

                self.log_signal.emit(log_msg)
            except Exception as e:
                self.log_signal.emit(f"🔴 송신 에러: {e}")

    def stop(self):
        self.running = False
        self.wait()


# ==========================================
# 2. 진단기 메인 GUI
# ==========================================
class DiagnosticScanner(QMainWindow):
    def __init__(self):
        super().__init__()
        self.init_ui()

        self.worker = DiagnosticWorker(COM_PORT, BITRATE)
        self.worker.dtc_response.connect(self.process_dtc_response)
        self.worker.log_signal.connect(self.add_log)
        self.worker.start()

    def init_ui(self):
        self.setWindowTitle("🛠️ Automotive Diagnostic Tool (OBD-II / UDS Scanner)")
        self.resize(950, 700)
        self.setStyleSheet(
            "background-color: #111827; color: #F3F4F6; font-family: 'Malgun Gothic', sans-serif;"
        )

        main_layout = QVBoxLayout()

        # --- 상단: 차량 및 시스템 선택 ---
        top_box = QGroupBox("1. 차량 및 시스템 선택 (Vehicle & System Selection)")
        top_box.setStyleSheet(
            "QGroupBox { font-weight: bold; color: #3B82F6; border: 1px solid #374151; border-radius: 6px; margin-top: 8px; } QGroupBox::title { subcontrol-origin: margin; left: 10px; }"
        )
        top_layout = QHBoxLayout()

        self.cb_vehicle = QComboBox()
        self.cb_vehicle.addItems(
            [
                "[Prototype] STM32 ECU Benchmark",
            ]
        )

        self.cb_system = QComboBox()
        self.cb_system.addItems(
            [
                "HCM (Headlight Control Module)",
            ]
        )

        combo_style = "QComboBox { background-color: #1F2937; color: #F3F4F6; padding: 6px; border: 1px solid #4B5563; border-radius: 4px; min-width: 200px; }"
        self.cb_vehicle.setStyleSheet(combo_style)
        self.cb_system.setStyleSheet(combo_style)

        top_layout.addWidget(QLabel("차량 모델:"))
        top_layout.addWidget(self.cb_vehicle)
        top_layout.addSpacing(20)
        top_layout.addWidget(QLabel("진단 시스템:"))
        top_layout.addWidget(self.cb_system)
        top_layout.addStretch()

        top_box.setLayout(top_layout)
        main_layout.addWidget(top_box)

        # --- 중단: 진단 컨트롤 버튼 ---
        ctrl_box = QGroupBox("2. 진단 기능 메뉴 (Diagnostic Functions)")
        ctrl_box.setStyleSheet(
            "QGroupBox { font-weight: bold; color: #10B981; border: 1px solid #374151; border-radius: 6px; margin-top: 8px; } QGroupBox::title { subcontrol-origin: margin; left: 10px; }"
        )
        ctrl_layout = QHBoxLayout()

        btn_scan = QPushButton("🔍 전체 시스템 DTC 스캔 (0x19)")
        btn_clear = QPushButton("🗑️ 고장 코드 소거 (0x14)")
        btn_inject_fault = QPushButton("⚠️ [테스트] 고장 주입 (Fault Inject)")
        btn_restore_fault = QPushButton("✅ [테스트] 고장 해제 (Restore)")

        btn_scan.setStyleSheet(
            "QPushButton { background-color: #2563EB; color: white; font-weight: bold; padding: 10px; border-radius: 5px; } QPushButton:hover { background-color: #1D4ED8; }"
        )
        btn_clear.setStyleSheet(
            "QPushButton { background-color: #DC2626; color: white; font-weight: bold; padding: 10px; border-radius: 5px; } QPushButton:hover { background-color: #B91C1C; }"
        )
        btn_inject_fault.setStyleSheet(
            "QPushButton { background-color: #D97706; color: white; font-weight: bold; padding: 10px; border-radius: 5px; } QPushButton:hover { background-color: #B45309; }"
        )
        btn_restore_fault.setStyleSheet(
            "QPushButton { background-color: #059669; color: white; font-weight: bold; padding: 10px; border-radius: 5px; } QPushButton:hover { background-color: #047857; }"
        )

        btn_scan.clicked.connect(lambda: self.worker.send_diag_request(0x19))
        btn_clear.clicked.connect(self.clear_dtc_and_rescan)
        btn_inject_fault.clicked.connect(lambda: self.inject_fault(True))  # 고장 주입
        btn_restore_fault.clicked.connect(lambda: self.inject_fault(False))  # 고장 해제

        ctrl_layout.addWidget(btn_scan)
        ctrl_layout.addWidget(btn_clear)
        ctrl_layout.addWidget(btn_inject_fault)
        ctrl_layout.addWidget(btn_restore_fault)
        ctrl_box.setLayout(ctrl_layout)
        main_layout.addWidget(ctrl_box)

        # --- 진단 결과 테이블 ---
        result_box = QGroupBox("3. 진단 결과 리포트 (Diagnostic Result Table)")
        result_box.setStyleSheet(
            "QGroupBox { font-weight: bold; color: #F59E0B; border: 1px solid #374151; border-radius: 6px; margin-top: 8px; } QGroupBox::title { subcontrol-origin: margin; left: 10px; }"
        )
        result_layout = QVBoxLayout()

        self.table = QTableWidget(2, 4)
        self.table.setHorizontalHeaderLabels(
            [
                "진단 항목 (System/Sensor)",
                "상태 (Status)",
                "DTC 코드",
                "진단 상세 설명 (Description)",
            ]
        )
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.table.setStyleSheet(
            "QTableWidget { background-color: #1F2937; gridline-color: #374151; color: #F3F4F6; } QHeaderView::section { background-color: #374151; color: #F3F4F6; font-weight: bold; }"
        )

        # 테이블 초기 데이터 세팅
        self.set_table_row(
            0, "BH1750 Illuminance Sensor", "미진단", "-", "스캔을 진행해주세요."
        )
        self.set_table_row(
            1, "Headlight Relay / Actuator", "미진단", "-", "스캔을 진행해주세요."
        )

        result_layout.addWidget(self.table)
        result_box.setLayout(result_layout)
        main_layout.addWidget(result_box)

        # --- 하단: CAN 진단 통신 로그 ---
        log_box = QGroupBox("4. CAN Bus Diagnostic Raw Log (0x7E0 / 0x7E8)")
        log_box.setStyleSheet(
            "QGroupBox { font-weight: bold; color: #9CA3AF; border: 1px solid #374151; border-radius: 6px; margin-top: 8px; } QGroupBox::title { subcontrol-origin: margin; left: 10px; }"
        )
        log_layout = QVBoxLayout()

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumHeight(120)
        self.log_text.setStyleSheet(
            "QTextEdit { background-color: #030712; color: #10B981; font-family: 'Consolas', monospace; font-size: 11px; }"
        )

        log_layout.addWidget(self.log_text)
        log_box.setLayout(log_layout)
        main_layout.addWidget(log_box)

        # 메인 레이아웃 설정
        central_widget = QWidget()
        central_widget.setLayout(main_layout)
        self.setCentralWidget(central_widget)

    def set_table_row(self, row, item_name, status, dtc, desc):
        self.table.setItem(row, 0, QTableWidgetItem(item_name))

        status_item = QTableWidgetItem(status)
        if "정상" in status or "PASS" in status:
            status_item.setForeground(Qt.GlobalColor.green)
        elif "고장" in status or "FAIL" in status:
            status_item.setForeground(Qt.GlobalColor.red)
        else:
            status_item.setForeground(Qt.GlobalColor.gray)

        self.table.setItem(row, 1, status_item)
        self.table.setItem(row, 2, QTableWidgetItem(dtc))
        self.table.setItem(row, 3, QTableWidgetItem(desc))

    def process_dtc_response(self, data):
        dtc = data["dtc"]
        status = data["status"]

        if status == 0 and dtc == 0x0000:
            # 정상 상태
            self.set_table_row(
                0,
                "BH1750 Illuminance Sensor",
                "🟢 정상 (PASS)",
                "None",
                "센서 통신 및 측정값 정상 범위",
            )
            self.set_table_row(
                1,
                "Headlight Relay / Actuator",
                "🟢 정상 (PASS)",
                "None",
                "헤드라이트 구동 회로 정상",
            )
            self.add_log("✅ 진단 결과: 모든 시스템 정상 (No DTC Found)")
        elif status == 1 or dtc == 0xB101:
            # 센서 고장 발생
            self.set_table_row(
                0,
                "BH1750 Illuminance Sensor",
                "🔴 고장 (FAIL)",
                "B1001",
                "조도 센서 단선/단락 (Open/Short Circuit)",
            )
            self.set_table_row(
                1,
                "Headlight Relay / Actuator",
                "🟢 정상 (PASS)",
                "None",
                "헤드라이트 구동 회로 정상",
            )
            self.add_log("⚠️ 진단 결과: DTC B1001 감지됨 (하드웨어 고장 원인 미해결)")

    def inject_fault(self, is_fault):
        """고장 주입(True) 또는 고장 해제(False) 명령을 전송하고 자동 스캔"""
        param = 0x01 if is_fault else 0x00
        self.worker.send_diag_request(0x2F, param)

        if is_fault:
            self.add_log(
                "⚠️ [Fault Injection] 가상 고장 주입 전송 (B1001 조도센서 단선 발생) -> [🔍 DTC 스캔]을 눌러 확인하세요."
            )
        else:
            self.add_log(
                "✅ [Fault Restore] 가상 고장 해제 전송 (센서 수리 완료) -> [🗑️ 고장 코드 소거] 후 스캔해보세요."
            )

    def clear_dtc_and_rescan(self):
        """고장 코드를 소거(0x14)하고 0.3초 뒤 자동으로 재스캔(0x19) 수행"""
        self.worker.send_diag_request(0x14)  # 소거 요청
        self.add_log("🧹 고장 코드 소거(Clear DTC) 명령 전송 완료")

        # 0.3초 뒤에 자동 재스캔을 보내서 현재 상태 확인
        from PySide6.QtCore import QTimer

        QTimer.singleShot(300, lambda: self.worker.send_diag_request(0x19))

    def add_log(self, text):
        self.log_text.append(f"[{time.strftime('%H:%M:%S')}] {text}")

    def closeEvent(self, event):
        self.worker.stop()
        event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = DiagnosticScanner()
    window.show()
    sys.exit(app.exec())
