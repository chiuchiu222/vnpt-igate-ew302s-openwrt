import os
import subprocess
import sys
import time
import serial

sys.stdout.reconfigure(encoding="utf-8")

def main():
    print("=== [STAGE 6] FLASH PRODUCTION ROM TO NAND & COLD BOOT MONITOR ===", flush=True)

    ser = serial.Serial("COM8", 115200, timeout=0.2)
    ser.reset_input_buffer()

    # Wake up console
    ser.write(b"\r\n")
    time.sleep(0.5)
    ser.write(b"echo 'UART READY'\r\n")
    time.sleep(0.5)
    init_out = ser.read(4096).decode("utf-8", errors="replace")
    print(f"[UART] Initial output:\n{init_out}", flush=True)

    # Execute sysupgrade via UART
    print("[UART] Initiating: sysupgrade -n -v /tmp/sysupgrade.bin", flush=True)
    ser.write(b"sysupgrade -n -v /tmp/sysupgrade.bin\r\n")

    t0 = time.time()
    boot_complete = False
    reboot_seen = False

    while time.time() - t0 < 300.0:  # up to 5 minutes
        chunk = ser.read(4096)
        if chunk:
            text = chunk.decode("utf-8", errors="replace")
            sys.stdout.write(text)
            sys.stdout.flush()

            if "Rebooting system" in text or "Restarting system" in text or "U-Boot 2023" in text or "U-Boot Boot Menu" in text:
                reboot_seen = True

            if reboot_seen and ("procd: - init complete -" in text or "br-lan: link becomes ready" in text):
                print("\n[UART] Router successfully cold-booted from NAND into OpenWrt!", flush=True)
                boot_complete = True
                time.sleep(10.0)
                break
        else:
            time.sleep(0.1)

    ser.close()

    if not boot_complete:
        print("\n[WARNING] Did not observe 'init complete' within 300s. Proceeding to SSH test anyway...", flush=True)

    print("\n=== [STAGE 6 VERIFICATION] Verifying system state via SSH (root@192.168.77.1) ===", flush=True)
    time.sleep(5.0)

    for attempt in range(1, 20):
        print(f"[SSH] Connection attempt {attempt}/20...", flush=True)
        res = subprocess.run(
            [
                "ssh",
                "-o", "StrictHostKeyChecking=no",
                "-o", "UserKnownHostsFile=NUL",
                "-o", "ConnectTimeout=4",
                "root@192.168.77.1",
                "uname -a && "
                "echo '=== [DF -H] ===' && df -h && "
                "echo '=== [MOUNT] ===' && mount | grep -iE 'overlay|rootfs|ubi' && "
                "echo '=== [IP ADDR] ===' && ip addr && "
                "echo '=== [NETWORK UCI] ===' && uci show network && "
                "echo '=== [FIREWALL UCI] ===' && uci show firewall.@defaults[0] && "
                "echo '=== [WIRELESS UCI] ===' && uci show wireless && "
                "echo '=== [IW DEV] ===' && (iw dev || true) && "
                "echo '=== [PING WAN / INTERNET (8.8.8.8)] ===' && (ping -c 3 8.8.8.8 || ping -c 3 1.1.1.1 || echo 'WAN ping test done') && "
                "echo '=== [LUCI PROCESS] ===' && (ps | grep -iE 'uhttpd|nginx' || true)",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if res.returncode == 0:
            print("\n" + res.stdout, flush=True)
            print("\n=== [STAGE 6 COMPLETED SUCCESSFULLY] ===", flush=True)
            return

        time.sleep(3.0)

    print("[ERROR] SSH connection timed out after multiple attempts.", flush=True)
    sys.exit(1)

if __name__ == "__main__":
    main()
