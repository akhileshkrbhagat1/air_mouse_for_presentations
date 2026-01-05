import sys
import threading
import queue
import argparse
import time
import re
import ctypes
from PyQt5 import QtWidgets, QtGui, QtCore
import serial
import pyautogui

pyautogui.FAILSAFE = False

IS_WINDOWS = sys.platform.startswith("win")

if IS_WINDOWS:
    user32 = ctypes.windll.user32
    ULONG_PTR = ctypes.c_size_t

    class MOUSEINPUT(ctypes.Structure):
        _fields_ = [
            ("dx", ctypes.c_long),
            ("dy", ctypes.c_long),
            ("mouseData", ctypes.c_ulong),
            ("dwFlags", ctypes.c_ulong),
            ("time", ctypes.c_ulong),
            ("dwExtraInfo", ULONG_PTR)
        ]

    class INPUT_union(ctypes.Union):
        _fields_ = [("mi", MOUSEINPUT)]

    class INPUT(ctypes.Structure):
        _fields_ = [
            ("type", ctypes.c_ulong),
            ("union", INPUT_union)
        ]

    INPUT_MOUSE = 0
    MOUSEEVENTF_MOVE = 0x0001
    MOUSEEVENTF_LEFTDOWN = 0x0002
    MOUSEEVENTF_LEFTUP = 0x0004
    MOUSEEVENTF_ABSOLUTE = 0x8000
    MOUSEEVENTF_VIRTUALDESK = 0x4000

RX_PATTERN = re.compile(
    r"RX\s*->\s*X:\s*([-\d\.]+)\s*Y:\s*([-\d\.]+)\s*Z:\s*([-\d\.]+)\s*\|\s*Buttons:\s*([01])\s+([01])\s+([01])\s+([01])",
    re.IGNORECASE
)

def serial_reader(port, baud, q, stop_event):
    try:
        ser = serial.Serial(port, baud, timeout=0.5)
    except Exception as e:
        q.put(("ERROR", f"Serial error: {e}"))
        return
    while not stop_event.is_set():
        try:
            line = ser.readline().decode('utf-8', errors='ignore').strip()
            if not line:
                continue
            m = RX_PATTERN.search(line)
            if m:
                try:
                    x_val = float(m.group(1))
                    y_val = float(m.group(2))
                    z_val = float(m.group(3))
                    buttons = tuple(int(m.group(i)) for i in range(4, 8))
                    q.put(("DATA", {
                        "x": z_val,  # Using Z for X-axis movement
                        "y": y_val,  # Using Y for Y-axis movement
                        "buttons": buttons
                    }))
                except:
                    pass
        except:
            break
    ser.close()

class OverlayWindow(QtWidgets.QWidget):
    def __init__(self, data_queue):
        super().__init__(flags=QtCore.Qt.FramelessWindowHint | 
                              QtCore.Qt.WindowStaysOnTopHint | 
                              QtCore.Qt.Tool)
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground)
        self.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents)
        
        screen = QtWidgets.QApplication.primaryScreen().size()
        self.sw, self.sh = screen.width(), screen.height()
        self.setGeometry(0, 0, self.sw, self.sh)
        
        self.data_queue = data_queue
        self.laser_on = False
        self.lx, self.ly = self.sw // 2, self.sh // 2
        self.prev_buttons = (0, 0, 0, 0)
        self.button_press_time = 0
        
        # Cursor state tracking
        self.cursor_visible = True
        if IS_WINDOWS:
            self._show_cursor(True)
        
        self.timer = QtCore.QTimer()
        self.timer.timeout.connect(self.process_data)
        self.timer.start(16)  # ~60 FPS

    def _show_cursor(self, show):
        if not IS_WINDOWS:
            return
        while True:
            count = user32.ShowCursor(show)
            if (show and count >= 0) or (not show and count < 0):
                break

    def _send_mouse_event(self, x, y, down=False):
        if not IS_WINDOWS:
            return
            
        screen_width = user32.GetSystemMetrics(0)
        screen_height = user32.GetSystemMetrics(1)
        
        # Convert to absolute coordinates (0-65535 range)
        dx = int(x * 65535 / screen_width)
        dy = int(y * 65535 / screen_height)
        
        flags = MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK
        if down:
            flags |= MOUSEEVENTF_LEFTDOWN
        else:
            flags |= MOUSEEVENTF_LEFTUP
        
        inp = INPUT()
        inp.type = INPUT_MOUSE
        inp.union.mi.dx = dx
        inp.union.mi.dy = dy
        inp.union.mi.dwFlags = flags
        user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))

    def process_data(self):
        while not self.data_queue.empty():
            msg, data = self.data_queue.get()
            if msg != "DATA":
                continue
                
            # Process movement
            nx = max(-1.0, min(1.0, data["x"] / 8.0))
            ny = max(-1.0, min(1.0, data["y"] / 8.0))
            
            self.lx = int(self.sw / 2 + nx * (self.sw / 2))
            self.ly = int(self.sh / 2 + ny * (self.sh / 2))
            
            # Process buttons
            b0, b1, b2, b3 = data["buttons"]
            
            # Toggle laser state (button 2)
            if b2 and not self.prev_buttons[2]:
                self.laser_on = not self.laser_on
                self._show_cursor(not self.laser_on)  # Hide cursor when laser on
                print(f"Laser {'ON' if self.laser_on else 'OFF'}")
            
            # Slide up (button 0) - only when laser is OFF
            if not self.laser_on and b0 and not self.prev_buttons[0]:
                print("Slide up detected")
                try:
                    pyautogui.press('up')
                except Exception as e:
                    print(f"Slide up error: {e}")
            
            # Slide down (button 3) - only when laser is OFF
            if not self.laser_on and b3 and not self.prev_buttons[3]:
                print("Slide down detected")
                try:
                    pyautogui.press('down')
                except Exception as e:
                    print(f"Slide down error: {e}")
            
            # Left click when laser is on (button 1)
            if self.laser_on:
                if b1 and not self.prev_buttons[1]:
                    self.button_press_time = time.time()
                elif not b1 and self.prev_buttons[1]:
                    press_duration = time.time() - self.button_press_time
                    if press_duration < 0.3:  # Quick press = click
                        self._send_mouse_event(self.lx, self.ly, down=True)
                        time.sleep(0.01)
                        self._send_mouse_event(self.lx, self.ly, down=False)
            
            self.prev_buttons = data["buttons"]
            self.update()

    def paintEvent(self, event):
        if not self.laser_on:
            return
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        
        # Big laser dot with glow effect
        center = QtCore.QPoint(self.lx, self.ly)
        
        # Outer glow
        gradient = QtGui.QRadialGradient(center, 25)
        gradient.setColorAt(0.0, QtGui.QColor(255, 100, 100, 200))
        gradient.setColorAt(0.7, QtGui.QColor(255, 50, 50, 150))
        gradient.setColorAt(1.0, QtGui.QColor(255, 0, 0, 0))
        
        painter.setBrush(QtGui.QBrush(gradient))
        painter.setPen(QtCore.Qt.NoPen)
        painter.drawEllipse(center, 25, 25)
        
        # Inner dot
        painter.setBrush(QtGui.QColor(255, 0, 0, 255))
        painter.drawEllipse(center, 8, 8)

    def closeEvent(self, event):
        if IS_WINDOWS and not self.cursor_visible:
            self._show_cursor(True)
        super().closeEvent(event)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", required=True)
    parser.add_argument("--baud", type=int, default=115200)
    args = parser.parse_args()

    data_queue = queue.Queue()
    stop_event = threading.Event()
    
    serial_thread = threading.Thread(
        target=serial_reader,
        args=(args.port, args.baud, data_queue, stop_event),
        daemon=True
    )
    serial_thread.start()

    app = QtWidgets.QApplication(sys.argv)
    window = OverlayWindow(data_queue)
    window.show()

    def cleanup():
        stop_event.set()
        if IS_WINDOWS:
            user32.ShowCursor(True)  # Ensure cursor visible on exit
    
    app.aboutToQuit.connect(cleanup)
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
