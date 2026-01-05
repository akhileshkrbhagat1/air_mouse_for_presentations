# air_mouse_overlay_fixed_sendinput.py
# Requirements:
#   pip install pyqt5 pyserial pyautogui
#
# Usage:
#   python air_mouse_overlay_fixed_sendinput.py --port COM3 --baud 115200

import sys
import threading
import queue
import argparse
import time
import re
import signal
import ctypes

from PyQt5 import QtWidgets, QtGui, QtCore
import serial
import pyautogui

pyautogui.FAILSAFE = False

RX_PATTERN = re.compile(
    r"RX\s*->\s*X:\s*([-\d\.]+)\s*Y:\s*([-\d\.]+)\s*Z:\s*([-\d\.]+)\s*\|\s*Buttons:\s*([01])\s+([01])\s+([01])\s+([01])",
    re.IGNORECASE
)

IS_WINDOWS = sys.platform.startswith("win")

# --- Windows SendInput setup ---
if IS_WINDOWS:
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32

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
    MOUSEEVENTF_RIGHTDOWN = 0x0008
    MOUSEEVENTF_RIGHTUP = 0x0010
    MOUSEEVENTF_ABSOLUTE = 0x8000
    MOUSEEVENTF_VIRTUALDESK = 0x4000

    class POINT(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

    def win_get_cursor_pos():
        pt = POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        return pt.x, pt.y

    def win_set_cursor_pos(x, y):
        return user32.SetCursorPos(int(x), int(y))

    def win_send_input_mouse(dwFlags, dx=0, dy=0, absolute=False):
        inp = INPUT()
        inp.type = INPUT_MOUSE
        inp.union.mi.dx = dx
        inp.union.mi.dy = dy
        inp.union.mi.mouseData = 0
        inp.union.mi.dwFlags = dwFlags
        inp.union.mi.time = 0
        inp.union.mi.dwExtraInfo = 0
        
        if absolute:
            inp.union.mi.dwFlags |= MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK
        
        n = user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))
        return n

    def win_absolute_move(x, y):
        # Get screen dimensions
        screen_width = user32.GetSystemMetrics(0)  # SM_CXSCREEN
        screen_height = user32.GetSystemMetrics(1)  # SM_CYSCREEN
        
        # Convert to absolute coordinates (0-65535)
        abs_x = int(x * 65535 / screen_width)
        abs_y = int(y * 65535 / screen_height)
        
        # Move cursor absolutely
        win_send_input_mouse(
            MOUSEEVENTF_MOVE,
            dx=abs_x,
            dy=abs_y,
            absolute=True
        )

# Serial reader thread
def serial_reader(port, baud, q, stop_event):
    try:
        ser = serial.Serial(port, baud, timeout=0.5)
    except Exception as e:
        q.put(("ERROR", f"Serial open error: {e}"))
        return
    q.put(("INFO", f"Opened {port} @ {baud}"))
    while not stop_event.is_set():
        try:
            raw = ser.readline()
            if not raw:
                continue
            line = raw.decode('utf-8', errors='ignore').strip()
            if not line:
                continue

            m = RX_PATTERN.search(line)
            if m:
                try:
                    x_val = float(m.group(1))
                    y_val = float(m.group(2))
                    z_val = float(m.group(3))
                    b1 = int(m.group(4))
                    b2 = int(m.group(5))
                    b3 = int(m.group(6))
                    b4 = int(m.group(7))
                except Exception:
                    continue
                q.put(("DATA", {"x": z_val, "y": y_val, "buttons": (b1, b2, b3, b4)}))
                continue

            parts = [p.strip() for p in line.split(",") if p.strip() != ""]
            if len(parts) >= 7:
                try:
                    xv = float(parts[0]); yv = float(parts[1]); zv = float(parts[2])
                    b1 = int(parts[3]); b2 = int(parts[4]); b3 = int(parts[5]); b4 = int(parts[6])
                    q.put(("DATA", {"x": zv, "y": yv, "buttons": (b1, b2, b3, b4)}))
                except Exception:
                    pass
        except Exception as e:
            q.put(("ERROR", f"Serial read error: {e}"))
            break
    try:
        ser.close()
    except:
        pass
    q.put(("INFO", "Serial thread exiting"))

class OverlayWindow(QtWidgets.QWidget):
    def __init__(self, data_queue, sensitivity=1.0, dot_radius=10):
        flags = QtCore.Qt.FramelessWindowHint | QtCore.Qt.WindowStaysOnTopHint | QtCore.Qt.Tool
        super().__init__(flags=flags)
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground)
        self.setWindowFlag(QtCore.Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents)

        self.data_queue = data_queue
        screen = QtWidgets.QApplication.primaryScreen()
        size = screen.size()
        self.sw = size.width()
        self.sh = size.height()
        self.setGeometry(0, 0, self.sw, self.sh)

        self.sensitivity = sensitivity
        self.dot_radius = dot_radius

        self.cx = self.sw // 2
        self.cy = self.sh // 2

        self.lx = self.cx
        self.ly = self.cy

        self.ema_alpha = 0.2
        self.smoothed_x = float(self.lx)
        self.smoothed_y = float(self.ly)

        self.cal_x = 0.0
        self.cal_y = 0.0

        self.prev_buttons = (0,0,0,0)
        self.button_press_time = [0,0,0,0]
        self.is_rightclick_held = False
        self.laser_on = False
        self.cursor_moved_for_click = False
        self.original_cursor_pos = None

        self.timer = QtCore.QTimer()
        self.timer.timeout.connect(self.update_from_queue)
        self.timer.start(12)

        self._closing = False

    def update_from_queue(self):
        latest = None
        while True:
            try:
                msg, val = self.data_queue.get_nowait()
            except queue.Empty:
                break
            if msg == "DATA":
                latest = val
            elif msg == "ERROR":
                print("[ERROR]", val)
            elif msg == "INFO":
                print("[INFO]", val)

        if latest is not None:
            raw_x = latest["x"]
            raw_y = latest["y"]
            b1,b2,b3,b4 = latest["buttons"]

            SCALE = 8.0
            z_clamped = max(-SCALE, min(SCALE, raw_x))
            y_clamped = max(-SCALE, min(SCALE, raw_y))

            nx = z_clamped / SCALE
            ny = y_clamped / SCALE

            nx = (nx - self.cal_x) * self.sensitivity*2
            ny = (ny - self.cal_y) * self.sensitivity*2

            target_x = int(self.cx + nx * (self.sw / 2))
            target_y = int(self.cy + ny * (self.sh / 2))

            self.smoothed_x = (1 - self.ema_alpha) * self.smoothed_x + self.ema_alpha * target_x
            self.smoothed_y = (1 - self.ema_alpha) * self.smoothed_y + self.ema_alpha * target_y

            self.lx = int(self.smoothed_x)
            self.ly = int(self.smoothed_y)

            self._process_buttons((b1,b2,b3,b4))

            rad = max(60, self.dot_radius*4)
            self.repaint(QtCore.QRect(self.lx-rad, self.ly-rad, rad*2, rad*2))

    def _process_buttons(self, buttons):
        prev = self.prev_buttons
        now = buttons
        t = time.time()

        # b3 toggle laser (index 2)
        if now[2] == 1 and prev[2] == 0:
            self.laser_on = not self.laser_on
            print("Laser toggled ->", self.laser_on)
            if not self.laser_on and self.is_rightclick_held:
                self._mouse_up_at(self.lx, self.ly, button='right')
                self.is_rightclick_held = False

        # b2 (index 1) press start
        if now[1] == 1 and prev[1] == 0:
            self.button_press_time[1] = t

        # right-click hold start if held > 0.4s and laser is ON
        if now[1] == 1 and self.laser_on:
            if (t - self.button_press_time[1]) >= 0.4 and not self.is_rightclick_held:
                print("Start right-click hold at", (self.lx, self.ly))
                self._mouse_down_at(self.lx, self.ly, button='right')
                self.is_rightclick_held = True

        # release b2
        if now[1] == 0 and prev[1] == 1:
            duration = t - self.button_press_time[1]
            if self.is_rightclick_held:
                print("Release right-click at", (self.lx, self.ly))
                self._mouse_up_at(self.lx, self.ly, button='right')
                self.is_rightclick_held = False
            else:
                if duration < 0.4 and self.laser_on:
                    print("Left click at", (self.lx, self.ly))
                    self._click_at(self.lx, self.ly, button='left')

        # b1 right arrow (index 0)
        if now[0] == 1 and prev[0] == 0:
            print("Right arrow pressed")
            try:
                pyautogui.press('right')
            except Exception as e:
                print("Key press error:", e)

        # b4 left arrow (index 3)
        if now[3] == 1 and prev[3] == 0:
            print("Left arrow pressed")
            try:
                pyautogui.press('left')
            except Exception as e:
                print("Key press error:", e)

        self.prev_buttons = now

    # --- Fixed clicking functions ---
    def _click_at(self, x, y, button='left'):
        if IS_WINDOWS:
            try:
                # Save original position
                orig_x, orig_y = win_get_cursor_pos()
                
                # Move cursor absolutely to target position
                win_absolute_move(x, y)
                time.sleep(0.01)  # Allow time for cursor to move
                
                # Perform click
                if button == 'left':
                    win_send_input_mouse(MOUSEEVENTF_LEFTDOWN)
                    time.sleep(0.01)
                    win_send_input_mouse(MOUSEEVENTF_LEFTUP)
                else:
                    win_send_input_mouse(MOUSEEVENTF_RIGHTDOWN)
                    time.sleep(0.01)
                    win_send_input_mouse(MOUSEEVENTF_RIGHTUP)
                
                # Restore original position
                win_absolute_move(orig_x, orig_y)
            except Exception as e:
                print("Win click error:", e)
        else:
            # Non-Windows fallback
            try:
                old = pyautogui.position()
                pyautogui.moveTo(x, y, duration=0)
                pyautogui.click(button=button)
                pyautogui.moveTo(old.x, old.y, duration=0)
            except Exception as e:
                print("Fallback click error:", e)

    def _mouse_down_at(self, x, y, button='left'):
        if IS_WINDOWS:
            try:
                # Save original position
                self.original_cursor_pos = win_get_cursor_pos()
                
                # Move cursor absolutely to target position
                win_absolute_move(x, y)
                time.sleep(0.01)
                
                # Record that we moved the cursor for click operations
                self.cursor_moved_for_click = True
                
                # Perform mouse down
                if button == 'left':
                    win_send_input_mouse(MOUSEEVENTF_LEFTDOWN)
                else:
                    win_send_input_mouse(MOUSEEVENTF_RIGHTDOWN)
            except Exception as e:
                print("Win mouseDown error:", e)
        else:
            try:
                old = pyautogui.position()
                pyautogui.moveTo(x, y, duration=0)
                pyautogui.mouseDown(button=button)
                pyautogui.moveTo(old.x, old.y, duration=0)
            except Exception as e:
                print("Fallback mouseDown error:", e)

    def _mouse_up_at(self, x, y, button='left'):
        if IS_WINDOWS:
            try:
                # If we moved the cursor for the down event, move back to target position
                if self.cursor_moved_for_click:
                    win_absolute_move(x, y)
                    time.sleep(0.01)
                
                # Perform mouse up
                if button == 'left':
                    win_send_input_mouse(MOUSEEVENTF_LEFTUP)
                else:
                    win_send_input_mouse(MOUSEEVENTF_RIGHTUP)
                
                # Restore original position if we had moved it
                if self.cursor_moved_for_click and self.original_cursor_pos:
                    orig_x, orig_y = self.original_cursor_pos
                    win_absolute_move(orig_x, orig_y)
                    self.cursor_moved_for_click = False
                    self.original_cursor_pos = None
            except Exception as e:
                print("Win mouseUp error:", e)
                # Cleanup state on error
                self.cursor_moved_for_click = False
                self.original_cursor_pos = None
        else:
            try:
                old = pyautogui.position()
                pyautogui.moveTo(x, y, duration=0)
                pyautogui.mouseUp(button=button)
                pyautogui.moveTo(old.x, old.y, duration=0)
            except Exception as e:
                print("Fallback mouseUp error:", e)

    def paintEvent(self, event):
        if not self.laser_on:
            return
        qp = QtGui.QPainter(self)
        qp.setRenderHint(QtGui.QPainter.Antialiasing)
        r = self.dot_radius
        color = QtGui.QColor(255, 0, 0, 230)
        qp.setBrush(QtGui.QBrush(color))
        qp.setPen(QtCore.Qt.NoPen)
        qp.drawEllipse(int(self.lx - r), int(self.ly - r), r*2, r*2)

    def keyPressEvent(self, event):
        if event.key() == QtCore.Qt.Key_C:
            self.cal_x = ((self.lx - self.cx) / (self.sw / 2))
            self.cal_y = ((self.ly - self.cy) / (self.sh / 2))
            print(f"Calibrated! cal_x={self.cal_x:.3f}, cal_y={self.cal_y:.3f}")
        elif event.key() == QtCore.Qt.Key_Escape:
            QtWidgets.QApplication.quit()

    def closeEvent(self, event):
        if self.is_rightclick_held:
            try:
                self._mouse_up_at(self.lx, self.ly, button='right')
            except:
                pass
            self.is_rightclick_held = False
        if self.cursor_moved_for_click and self.original_cursor_pos:
            try:
                orig_x, orig_y = self.original_cursor_pos
                win_absolute_move(orig_x, orig_y)
            except:
                pass
            self.cursor_moved_for_click = False
            self.original_cursor_pos = None
        self._closing = True
        super().closeEvent(event)

def main():
    parser = argparse.ArgumentParser(description="Laser overlay (SendInput fix).")
    parser.add_argument("--port", required=True, help="Serial port (e.g. COM3 or /dev/ttyUSB0)")
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--sensitivity", type=float, default=1.0)
    parser.add_argument("--dot", type=int, default=12)
    args = parser.parse_args()

    q = queue.Queue()
    stop_event = threading.Event()
    reader = threading.Thread(target=serial_reader, args=(args.port, args.baud, q, stop_event), daemon=True)
    reader.start()

    app = QtWidgets.QApplication(sys.argv)
    overlay = OverlayWindow(q, sensitivity=args.sensitivity, dot_radius=args.dot)
    overlay.show()

    def sigint_handler(sig, frame):
        stop_event.set()
        QtWidgets.QApplication.quit()
    signal.signal(signal.SIGINT, sigint_handler)

    try:
        rc = app.exec_()
    finally:
        stop_event.set()
        reader.join(timeout=0.5)
    sys.exit(rc)

if __name__ == "__main__":
    main()
