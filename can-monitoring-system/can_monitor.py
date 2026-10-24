import can
import time

# 1. CANable 시리얼 포트 설정 
# SLCAN 방식(CANable 기본 펌웨어) 기준 설정
COM_PORT = 'COM6'  # 예: 장치 관리자에서 확인한 COM 포트
BITRATE = 500000   # 500 kbps

def parse_can_message(msg):
    """STM32 Body ECU(0x100) 데이터 파싱 함수"""
    if msg.arbitration_id == 0x100 and len(msg.data) >= 4:
        # Data[0~1]: Lux 값 (High Byte << 8 | Low Byte)
        lux = (msg.data[0] << 8) | msg.data[1]
        
        # Data[2]: 라이트 점등 상태 (0: OFF, 1: ON)
        light_state = "ON" if msg.data[2] == 1 else "OFF"
        
        # Data[3]: 스위치 모드 (0: AUTO, 1: FORCE ON, 2: FORCE OFF)
        mode_map = {0: "AUTO", 1: "FORCE ON", 2: "FORCE OFF"}
        light_mode = mode_map.get(msg.data[3], "UNKNOWN")
        
        # 파싱 결과 콘솔 출력
        print(f"[ECU Status] Lux: {lux:4d} lx | Mode: {light_mode:<9s} | Headlight: {light_state}")

def main():
    print(f"Connecting to CANable on {COM_PORT} ({BITRATE/1000} kbps)...")
    
    try:
        # python-can의 slcan(Serial Line CAN) 인터페이스 연결
        bus = can.interface.Bus(interface='slcan', channel=COM_PORT, bitrate=BITRATE)
        print("Connected successfully! Listening for CAN messages...\n")
        
        while True:
            # CAN 메세지 수신 (타임아웃 1초)
            message = bus.recv(timeout=1.0)
            if message is not None:
                parse_can_message(message)
                
    except KeyboardInterrupt:
        print("\nStopping CAN Monitor...")
    except Exception as e:
        print(f"Error: {e}")
    finally:
        if 'bus' in locals():
            bus.shutdown()

if __name__ == '__main__':
    main()