import sys
import time
from collections import deque
import queue  # 스레드 간 안전한 데이터 전달을 위한 큐
import can

from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QGroupBox,
)
from PySide6.QtCore import QThread, Signal, Qt
from PySide6.QtGui import QFont
import pyqtgraph as pg

COM_PORT = "COM6"
BITRATE = 500000


class CANWorker(QThread):
    data_received = Signal(int, int, int)
    connection_status = Signal(bool, str)

    def __init__(self, port, bitrate):
        super().__init__()
        self.port = port
        self.bitrate = bitrate
        self.running = True
        self.bus = None
        self.send_queue = queue.Queue()  # 송신 명령을 담을 스레드 안전 큐

    def run(self):
        try:
            self.bus = can.interface.Bus(
                interface="slcan", channel=self.port, bitrate=self.bitrate
            )
            self.connection_status.emit(True, f"Connected ({self.port})")
        except Exception as e:
            self.connection_status.emit(False, f"Connection Failed: {e}")
            return

        while self.running:
            # 1. 수신 처리 (타임아웃을 짧게 가져감)
            try:
                msg = self.bus.recv(timeout=0.02)
                if msg and msg.arbitration_id == 0x100 and len(msg.data) >= 4:
                    lux = (msg.data[0] << 8) | msg.data[1]
                    light_state = msg.data[2]
                    light_mode = msg.data[3]
                    self.data_received.emit(lux, light_state, light_mode)
            except Exception:
                pass

            # 2. 송신 큐에 대기 중인 제어 명령 비동기 처리
            if not self.send_queue.empty():
                mode_cmd = self.send_queue.get()
                msg = can.Message(
                    arbitration_id=0x200,
                    data=[mode_cmd, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00],
                    is_extended_id=False,
                )
                try:
                    # timeout을 부여하여 송신 실패 시에도 UI가 멈추지 않도록 방지
                    self.bus.send(msg, timeout=0.1)
                    print(f"[CAN TX] Mode Cmd Sent: {mode_cmd}")
                except can.CanError as e:
                    print(
                        f"[CAN TX Error] Failed to send 0x200 (No ACK or Bus Error): {e}"
                    )

        if self.bus:
            self.bus.shutdown()

    def send_mode_cmd(self, mode_cmd):
        """GUI 버튼 클릭 시 메인 스레드 멈춤 없이 큐에 전달만 수행"""
        self.send_queue.put(mode_cmd)

    def stop(self):
        self.running = False
        self.wait()


class ECUDashboard(QMainWindow):
    def __init__(self):
        super().__init__()
        self.time_data = deque(maxlen=100)
        self.lux_data = deque(maxlen=100)
        self.start_time = time.time()

        self.init_ui()

        self.can_worker = CANWorker(COM_PORT, BITRATE)
        self.can_worker.data_received.connect(self.update_dashboard)
        self.can_worker.connection_status.connect(self.update_status)
        self.can_worker.start()

    def init_ui(self):
        self.setWindowTitle("STM32 Body ECU Dashboard")
        self.resize(800, 650)
        self.setStyleSheet("background-color: #1E1E2E; color: #CDD6F4;")

        main_layout = QVBoxLayout()

        top_layout = QHBoxLayout()
        title_label = QLabel("🚗 AutoLight ECU Monitor")
        title_label.setFont(QFont("Arial", 18, QFont.Weight.Bold))

        self.status_label = QLabel("Connecting...")
        self.status_label.setFont(QFont("Arial", 11))
        self.status_label.setStyleSheet("color: #FAB387;")

        top_layout.addWidget(title_label)
        top_layout.addStretch()
        top_layout.addWidget(self.status_label)
        main_layout.addLayout(top_layout)

        status_layout = QHBoxLayout()

        lux_box = self.create_card("Illuminance (Lux)", "#89B4FA")
        self.lux_label = QLabel("0 lx")
        self.lux_label.setFont(QFont("Arial", 28, QFont.Weight.Bold))
        self.lux_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lux_label.setStyleSheet("color: #89B4FA;")
        lux_box.layout().addWidget(self.lux_label)

        mode_box = self.create_card("Operating Mode", "#A6E3A1")
        self.mode_label = QLabel("AUTO")
        self.mode_label.setFont(QFont("Arial", 24, QFont.Weight.Bold))
        self.mode_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.mode_label.setStyleSheet("color: #A6E3A1;")
        mode_box.layout().addWidget(self.mode_label)

        light_box = self.create_card("Headlight", "#F9E2AF")
        self.light_label = QLabel("💡 OFF")
        self.light_label.setFont(QFont("Arial", 24, QFont.Weight.Bold))
        self.light_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.light_label.setStyleSheet("color: #585B70;")
        light_box.layout().addWidget(self.light_label)

        status_layout.addWidget(lux_box)
        status_layout.addWidget(mode_box)
        status_layout.addWidget(light_box)
        main_layout.addLayout(status_layout)

        graph_box = self.create_card("Real-time Lux History", "#CDD6F4")
        self.graph_widget = pg.PlotWidget()
        self.graph_widget.setBackground("#181825")
        self.graph_widget.showGrid(x=True, y=True, alpha=0.3)
        self.graph_widget.setLabel("left", "Lux")
        self.graph_widget.setLabel("bottom", "Time (s)")
        self.curve = self.graph_widget.plot(pen=pg.mkPen(color="#89B4FA", width=2))

        graph_box.layout().addWidget(self.graph_widget)
        main_layout.addWidget(graph_box)

        ctrl_box = self.create_card("Remote ECU Control (CAN 0x200)", "#FAB387")
        ctrl_layout = QHBoxLayout()

        btn_auto = QPushButton("AUTO Mode")
        btn_force_on = QPushButton("FORCE ON")
        btn_force_off = QPushButton("FORCE OFF")

        btn_style = """
            QPushButton {
                background-color: #313244; color: #CDD6F4; 
                font-size: 13px; font-weight: bold; 
                padding: 8px; border-radius: 6px; border: 1px solid #45475A;
            }
            QPushButton:hover { background-color: #45475A; }
            QPushButton:pressed { background-color: #585B70; }
        """
        for btn in (btn_auto, btn_force_on, btn_force_off):
            btn.setStyleSheet(btn_style)

        btn_auto.clicked.connect(lambda: self.can_worker.send_mode_cmd(0))
        btn_force_on.clicked.connect(lambda: self.can_worker.send_mode_cmd(1))
        btn_force_off.clicked.connect(lambda: self.can_worker.send_mode_cmd(2))

        ctrl_layout.addWidget(btn_auto)
        ctrl_layout.addWidget(btn_force_on)
        ctrl_layout.addWidget(btn_force_off)
        ctrl_box.layout().addLayout(ctrl_layout)

        main_layout.addWidget(ctrl_box)

        central_widget = QWidget()
        central_widget.setLayout(main_layout)
        self.setCentralWidget(central_widget)

    def create_card(self, title, color):
        box = QGroupBox(title)
        box.setStyleSheet(f"""
            QGroupBox {{
                font-size: 13px; font-weight: bold; color: {color};
                border: 1px solid #45475A; border-radius: 8px; margin-top: 10px;
            }}
            QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 5px; }}
        """)
        layout = QVBoxLayout()
        box.setLayout(layout)
        return box

    def update_status(self, connected, msg):
        if connected:
            self.status_label.setText(f"🟢 {msg}")
            self.status_label.setStyleSheet("color: #A6E3A1;")
        else:
            self.status_label.setText(f"🔴 {msg}")
            self.status_label.setStyleSheet("color: #F38BA8;")

    def update_dashboard(self, lux, light_state, light_mode):
        self.lux_label.setText(f"{lux} lx")

        mode_map = {0: "AUTO", 1: "FORCE ON", 2: "FORCE OFF"}
        self.mode_label.setText(mode_map.get(light_mode, "UNKNOWN"))

        if light_state == 1:
            self.light_label.setText("💡 ON")
            self.light_label.setStyleSheet("color: #F9E2AF; font-weight: bold;")
        else:
            self.light_label.setText("💡 OFF")
            self.light_label.setStyleSheet("color: #585B70;")

        self.time_data.append(time.time() - self.start_time)
        self.lux_data.append(lux)
        self.curve.setData(list(self.time_data), list(self.lux_data))

    def closeEvent(self, event):
        self.can_worker.stop()
        event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = ECUDashboard()
    window.show()
    sys.exit(app.exec())
