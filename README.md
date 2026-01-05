#  Air Remote for Presentation Control and Virtual Pointer

![Image Placeholder: A concept image showing a small, handheld device (the Air Remote) and a computer screen displaying a virtual pointer being controlled by hand movement.]

## Abstract

This project describes the design and implementation of an **Air Remote** that enables users to control presentation slides and a virtual on-screen pointer using **hand gestures** instead of conventional devices like a mouse or laser pointer.

The system employs a **BMX160 Inertial Measurement Unit (IMU)** to capture hand motion and orientation. An **ESP32 microcontroller** processes this data and transmits it wirelessly to a second ESP32 using the low-latency **ESP-NOW** protocol. The receiver ESP32 then forwards the data to a host computer over serial communication, where a Python application interprets the commands and translates them into presentation actions (cursor movement, slide navigation).

Physical buttons on the device are mapped to keyboard inputs for common functions. This solution is **contactless, intuitive, and low-cost**, making it ideal for hygiene-sensitive settings (e.g., hospitals, laboratories) and budget-constrained educational institutions and users.

---

## 🚀 Key Features

* **Gesture Control:** Natural hand movements control the virtual cursor on the screen.
* **Virtual Pointer:** Replaces physical lasers with an on-screen digital cursor, fully visible in video conference calls (Zoom/Teams) and on LCD/LED displays.
* **Contactless Operation:** Enables sterile, hands-free interaction, suitable for sensitive environments.
* **Low Latency Wireless:** Utilises the robust ESP-NOW protocol for fast, real-time control.
* **Cost-Effective:** Provides high-end features (gesture control) at a budget-friendly price point.
* **Smart Power Management:** Features a Latch Circuit for reliable software-controlled power-off, maximising battery life.

---

## 3. System Overview

The Air Remote system is structured into two main modules operating in a master-slave configuration: the **Transmitter Node (Remote)** and the **Receiver Node (Dongle)**.

### 3.1 Block Diagram

| Module | Function | Key Components |
| :--- | :--- | :--- |
| **Transmitter Node (Remote)** | Reads motion data, button states, performs sensor fusion, and transmits wirelessly. | ESP32, BMX160 IMU, Latch Circuit, Push Buttons, 3.7V Li-Po Battery |
| **Wireless Link** | Low-latency, connectionless data transfer. | ESP-NOW Protocol |
| **Receiver Node (Dongle)** | Receives wireless packets and relays raw data to the host computer. | ESP32, USB Connection |
| **Host Processing** | Interprets raw serial data and translates it into standard mouse/keyboard actions. | Python Script (`pyserial`, `pyautogui`) |

---

## 4. Hardware Implementation

### 4.1 Component Selection

| Component | Rationale |
| :--- | :--- |
| **Microcontroller (ESP32)** | Built-in Wi-Fi/Bluetooth and native support for the low-latency **ESP-NOW** protocol. |
| **IMU Sensor (BMX160)** | High-precision 9-axis sensor (Accelerometer, Gyroscope, Magnetometer) essential for accurate orientation tracking and gesture translation. |
| **Power Management (Latch Circuit)** | Transistor-based circuit allowing the device to be powered ON by a momentary button press and powered OFF via software command, preserving battery life. |
| **Boost Converter Module** | Efficiently regulates the Li-Po battery voltage (3.7V) up to a stable 5V for reliable system operation. |
| **Input Buttons** | Tactile push-buttons for discrete events: Next Slide, Previous Slide, and Toggle Pointer On/Off. |

### 4.2 Circuit Design

* **Transmitter Circuit:** The BMX160 communicates with the ESP32 via the **I2C bus** (SDA/SCL). Buttons utilize digital GPIO pins with internal pull-up resistors.
* **Receiver Circuit:** A second ESP32 serves as the receiver and is powered directly by the host computer's USB port, requiring no external battery.

---

## 5. Software Implementation

The software architecture comprises firmware for both ESP32 units and a driver application on the host computer.

### 5.1 Transmitter Firmware

1.  Initializes I2C connection with the BMX160.
2.  Continuously reads the 6-axis data (Gyroscope X, Y, Z).
3.  Packages the orientation data (mapped to X/Y coordinates) and button states into a C `struct`.
4.  Transmits the `struct` wirelessly to the receiver's MAC address using **ESP-NOW**.

### 5.2 Receiver Firmware

1.  Operates in a passive listening mode for ESP-NOW packets.
2.  Parses the received `struct`.
3.  Immediately prints the values to the **Serial Monitor (UART)** in a standardised, comma-separated format for the computer to process (e.g., `X:120, Y:-45, B1:0, B2:1`).

### 5.3 Host Application (Python)

* **Libraries:** Built using `pyserial` and `pyautogui`.
* **Serial Listener:** Continuously monitors the USB serial port for incoming data strings from the receiver.
* **Mapping Logic:** Converts the sensor's orientation (specifically Pitch and Roll) into relative screen X and Y coordinates to control the mouse cursor.
* **Action Trigger:**
    * Specific button codes trigger keyboard simulations using `pyautogui.press('right')` for slide navigation.
    * Toggles a software-drawn red circle on the screen to simulate the virtual laser pointer.

---

## 6. Results and Discussion

The prototype was successfully tested, yielding positive results:

| Feature | Observation |
| :--- | :--- |
| **Gesture Control** | Hand movements accurately moved the cursor with minimal perceivable delay. |
| **Latency** | Low end-to-end latency ensured real-time pointing capability. |
| **Range** | Stable connection maintained up to 10 meters (line of sight) via ESP-NOW, suitable for standard lecture halls. |
| **Comparison** | Superior to standard IR remotes (no line-of-sight required) and laser pointers (digital pointer visible in video conferences). |

---

## 7. Conclusion and Future Work

### 7.1 Conclusion

This project successfully demonstrates a low-cost, contactless Air Remote using the BMX160 and ESP32. It provides an intuitive, reliable alternative to high-end presentation tools, offering gesture control and a virtual pointer without the safety concerns of physical lasers.

### 7.2 Future Scope

* **Bluetooth Low Energy (BLE) Migration:** Replace the ESP-NOW setup with BLE to enable direct connection to modern laptops, eliminating the need for a separate USB receiver dongle.
* **Enhanced Gesture Library:** Implement support for gestures such as scrolling (document navigation) and zooming (image manipulation).
* **Full Mouse Integration:** Utilize spare buttons for:
    * Left Click (momentary press command).
    * Right Click (press and hold command).

---

## 🙏 Special Thanks

I extend my sincere gratitude to **Okami** for his essential contributions and assistance with this project.
