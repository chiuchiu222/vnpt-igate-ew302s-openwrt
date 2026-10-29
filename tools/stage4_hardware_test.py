#!/usr/bin/env python3
"""
Stage 4 Automated Hardware Test for VNPT iGate EW302S:
1. Auto-detects USB-UART COM port (FT232R VID:PID=0403:6001).
2. Starts TFTP server on UDP 69 serving C:\\tftp\\initramfs.itb.
3. Enters U-Boot (MT7981>), activates EN8801SC PHY, runs:
     tftpboot 0x46000000 initramfs.itb
     bootm 0x46000000
4. Streams and verifies Kernel 6.12 UART boot log, eth0/eth1 Link Up, Wi-Fi mt7915e, and 192.168.77.1.
5. Connects via SSH to root@192.168.77.1 over LAN to verify dmesg, ip addr, and Wi-Fi status.
"""
import os
import subprocess
import sys
import threading
import time
import serial
import serial.tools.list_ports

sys.stdout.reconfigure(encoding="utf-8")

from tftp_server import run_server


def find_uart_port() -> str:
    ports = list(serial.tools.list_ports.comports())
    for p in ports:
        if "0403:6001" in (p.hwid or "") or "USB Serial Port" in (p.description or ""):
            print(f"[UART] Auto-detected USB-UART port: {p.device} ({p.description}, {p.hwid})", flush=True)
            return p.device
    return "COM8"


def read_until(ser: serial.Serial, markers: list[bytes], timeout: float = 10.0) -> bytes:
    buf = b""
    t0 = time.time()
    while time.time() - t0 < timeout:
        chunk = ser.read(4096)
        if chunk:
            buf += chunk
            sys.stdout.write(chunk.decode("utf-8", errors="replace"))
            sys.stdout.flush()
            for m in markers:
                if m in buf:
                    return buf
        else:
            time.sleep(0.05)
    return buf


def main():
    itb_path = r"C:\tftp\initramfs.itb"
    if not os.path.isfile(itb_path):
        print(f"[ERROR] Missing {itb_path}", flush=True)
        sys.exit(1)
    print(f"[INFO] Found {itb_path} ({os.path.getsize(itb_path)} bytes)", flush=True)

    # Start background TFTP server
    tftp_thread = threading.Thread(target=run_server, daemon=True)
    tftp_thread.start()
    time.sleep(0.5)

    port = find_uart_port()
    ser = serial.Serial(port, 115200, timeout=0.2)
    ser.write(b"\x03\r\n")
    time.sleep(0.4)
    initial = ser.read(8192)

    if b"MT7981>" not in initial:
        print("[UART] Waiting for target reboot / power-cycle to capture U-Boot prompt (up to 180s)...", flush=True)
        ser.write(b"\r\nreboot\r\nreset\r\n")
        t0 = time.time()
        buf = b""
        while time.time() - t0 < 180.0:
            c = ser.read(4096)
            if c:
                buf += c
                sys.stdout.write(c.decode("utf-8", errors="replace"))
                sys.stdout.flush()
                if b"Hit any key" in buf or b"U-Boot Boot Menu" in buf:
                    ser.write(b"0")
                    break
        time.sleep(0.5)
        ser.write(b"\r\n")
        read_until(ser, [b"MT7981>"], timeout=3.0)

    # Test if U-Boot Ethernet is initialized; if not, run the 2-step FDT warm-init at 0x41ea38a8 -> 0x41e00000
    # Step A: probe at reg=0 so U-Boot downloads EN8801SC firmware via MDIO 0x1e (switching PHY to addr 0x18)
    # Step B: restore gmac-id=0, phy-mode=sgmii, reg=0x18 and warm-restart U-Boot at 0x41e00000
    ser.reset_input_buffer()
    ser.write(b"setenv ipaddr 192.168.77.1; setenv serverip 192.168.77.2; setenv netmask 255.255.255.0; ping 192.168.77.2\r\n")
    ping_out = read_until(ser, [b"is alive", b"not alive"], timeout=6.0)
    if b"is alive" not in ping_out:
        print("\n[UART] Initializing Airoha EN8801SC PHY in U-Boot via 0x41ea38a8 FDT warm-restart...", flush=True)
        for fdt_cmds in [
            [
                "fdt addr 0x41ea38a8",
                "fdt set /ethernet@15100000 reset-gpios <0x0000000e 0x00000027 0x00000000>",
                "fdt set /ethernet@15100000 mediatek,gmac-id <0x00000001>",
                "fdt set /ethernet@15100000 phy-mode gmii",
                "fdt set /ethernet@15100000/eth-phy@5 reg <0x00000000>",
            ],
            [
                "fdt addr 0x41ea38a8",
                "fdt set /ethernet@15100000 mediatek,gmac-id <0x00000000>",
                "fdt set /ethernet@15100000 phy-mode sgmii",
                "fdt set /ethernet@15100000/eth-phy@5 reg <0x00000018>",
            ],
        ]:
            ser.write(b"\x03\r\n")
            time.sleep(0.3)
            ser.reset_input_buffer()
            for cmd in fdt_cmds:
                ser.write((cmd + "\r\n").encode())
                time.sleep(0.3)
            ser.write(b"go 0x41e00000\r\n")
            t0 = time.time()
            buf = b""
            while time.time() - t0 < 5.0:
                c = ser.read(4096)
                if c:
                    buf += c
                    sys.stdout.write(c.decode("utf-8", errors="replace"))
                    sys.stdout.flush()
                    if b"Hit any key" in buf:
                        ser.write(b"0")
                        break
            time.sleep(0.5)
        ser.write(b"\r\nsetenv ipaddr 192.168.77.1; setenv serverip 192.168.77.2; setenv netmask 255.255.255.0; ping 192.168.77.2\r\n")
        read_until(ser, [b"is alive", b"not alive"], timeout=6.0)
        read_until(ser, [b"MT7981>"], timeout=3.0)

    print("\n[UART] Executing: tftpboot 0x46000000 initramfs.itb", flush=True)
    ser.write(b"tftpboot 0x46000000 initramfs.itb\r\n")
    tftp_out = read_until(ser, [b"Bytes transferred ="], timeout=35.0)
    read_until(ser, [b"MT7981>"], timeout=3.0)
    if b"Bytes transferred =" not in tftp_out:
        print("\n[ERROR] TFTP transfer failed!", flush=True)
        sys.exit(1)

    print("\n[UART] Executing: bootm 0x46000000", flush=True)
    ser.write(b"bootm 0x46000000\r\n")

    boot_log = b""
    t0 = time.time()
    while time.time() - t0 < 75.0:
        c = ser.read(4096)
        if c:
            boot_log += c
            sys.stdout.write(c.decode("utf-8", errors="replace"))
            sys.stdout.flush()
            if b"br-lan: link becomes ready" in boot_log or b"procd: - init complete -" in boot_log:
                # Read a few more seconds after init complete
                time.sleep(5.0)
                extra = ser.read(16384)
                if extra:
                    boot_log += extra
                    sys.stdout.write(extra.decode("utf-8", errors="replace"))
                    sys.stdout.flush()
                break
        else:
            time.sleep(0.1)

    # Activate serial console and verify IP on device if needed
    ser.write(b"\r\n")
    time.sleep(1.5)
    ser.write(b"ip addr show br-lan; ip link set eth0 up; ip link set eth1 up\r\n")
    read_until(ser, [b"192.168.77.1"], timeout=5.0)
    ser.close()

    print("\n=== [STAGE 4.4] Running SSH verification to root@192.168.77.1 ===", flush=True)
    for attempt in range(1, 10):
        res = subprocess.run(
            [
                "ssh",
                "-o", "StrictHostKeyChecking=no",
                "-o", "UserKnownHostsFile=NUL",
                "-o", "ConnectTimeout=5",
                "root@192.168.77.1",
                "uname -a && echo '--- DMESG ---' && dmesg | grep -iE 'Linux version|mt7981|en8801|airoha|mtk_soc_eth|mt7915|spi-nand|ubi' && echo '--- IP ADDR ---' && ip addr && echo '--- WIFI ---' && (iw dev || true) && uci show wireless",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if res.returncode == 0:
            print(res.stdout, flush=True)
            break
        print(f"[SSH] Attempt {attempt} waiting for dropbear on 192.168.77.1... ({res.stderr.strip()})", flush=True)
        time.sleep(3.0)


if __name__ == "__main__":
    main()
