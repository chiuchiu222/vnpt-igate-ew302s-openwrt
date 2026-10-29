#!/usr/bin/env python3
"""
Lightweight RFC 1350 + RFC 2347/2348 (blksize/tsize/timeout) UDP TFTP Server
for serving C:\\tftp\\initramfs.itb to U-Boot at 192.168.77.1.
"""
import os
import socket
import struct
import sys
import threading

TFTP_ROOT = r"C:\tftp"
BIND_IP = "0.0.0.0"
BIND_PORT = 69


def handle_rrq(filename: str, opts: dict, client_addr: tuple):
    safe_name = os.path.basename(filename.replace("\\", "/"))
    filepath = os.path.join(TFTP_ROOT, safe_name)
    print(f"[TFTP] RRQ from {client_addr} for '{filename}' -> '{filepath}' opts={opts}", flush=True)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(3.0)

    if not os.path.isfile(filepath):
        err_msg = f"File not found: {safe_name}".encode("ascii") + b"\x00"
        sock.sendto(struct.pack("!HH", 5, 1) + err_msg, client_addr)
        sock.close()
        return

    filesize = os.path.getsize(filepath)
    blksize = 512
    oack_parts = []

    if "blksize" in opts:
        try:
            req_blk = int(opts["blksize"])
            blksize = max(8, min(req_blk, 1468))
            oack_parts.append(b"blksize\x00" + str(blksize).encode("ascii") + b"\x00")
        except ValueError:
            pass

    if "tsize" in opts:
        oack_parts.append(b"tsize\x00" + str(filesize).encode("ascii") + b"\x00")

    if "timeout" in opts:
        oack_parts.append(b"timeout\x00" + opts["timeout"].encode("ascii") + b"\x00")

    try:
        if oack_parts:
            oack_pkt = struct.pack("!H", 6) + b"".join(oack_parts)
            for _ in range(5):
                sock.sendto(oack_pkt, client_addr)
                try:
                    data, _ = sock.recvfrom(1024)
                    opcode, ack_blk = struct.unpack("!HH", data[:4])
                    if opcode == 4 and ack_blk == 0:
                        break
                except socket.timeout:
                    continue

        with open(filepath, "rb") as f:
            block_num = 1
            while True:
                chunk = f.read(blksize)
                pkt = struct.pack("!HH", 3, block_num & 0xFFFF) + chunk
                acked = False
                for _ in range(6):
                    sock.sendto(pkt, client_addr)
                    try:
                        data, _ = sock.recvfrom(1024)
                        opcode, ack_blk = struct.unpack("!HH", data[:4])
                        if opcode == 4 and ack_blk == (block_num & 0xFFFF):
                            acked = True
                            break
                    except socket.timeout:
                        continue
                if not acked:
                    print(f"[TFTP] Timeout on block {block_num}", flush=True)
                    break
                if len(chunk) < blksize:
                    print(f"[TFTP] Completed sending {safe_name} ({filesize} bytes) in {block_num} blocks.", flush=True)
                    break
                block_num += 1
    finally:
        sock.close()


def run_server():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((BIND_IP, BIND_PORT))
    print(f"[TFTP] Listening on {BIND_IP}:{BIND_PORT}, root={TFTP_ROOT}", flush=True)
    while True:
        data, addr = sock.recvfrom(2048)
        if len(data) < 4:
            continue
        opcode = struct.unpack("!H", data[:2])[0]
        if opcode == 1:  # RRQ
            parts = data[2:].split(b"\x00")
            parts = [p.decode("ascii", errors="ignore") for p in parts if p != ""]
            if len(parts) >= 2:
                filename = parts[0]
                opts = {}
                i = 2
                while i + 1 < len(parts):
                    opts[parts[i].lower()] = parts[i + 1]
                    i += 2
                threading.Thread(target=handle_rrq, args=(filename, opts, addr), daemon=True).start()


if __name__ == "__main__":
    run_server()
