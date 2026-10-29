# OpenWrt / ImmortalWrt for VNPT iGate EW302S

Dự án cung cấp mã nguồn mở, Device Tree (DTS), kernel driver patches và bộ công cụ tự động hóa hoàn chỉnh để chạy **OpenWrt / ImmortalWrt 25.12 (Kernel 6.12+)** trên thiết bị Wi-Fi 6 Mesh **VNPT iGate EW302S**.

---

## 1. Thông số phần cứng (Hardware Specifications)

| Thành phần | Chi tiết |
| :--- | :--- |
| **SoC** | MediaTek MT7981B (Filogic 820) Dual-core ARM Cortex-A53 @ 1.3GHz |
| **RAM** | 256 MiB DDR3 |
| **Flash** | 128 MiB SPI-NAND (Winbond W25N01KV) |
| **Cổng Ethernet 0 (LAN)** | 1000M/100M/10M qua PHY **Airoha EN8801SC** (Giao tiếp SGMII, MDIO `0x18`, Reset GPIO 39) |
| **Cổng Ethernet 1 (WAN)** | 1000M/100M/10M qua **MediaTek MT7981 Internal PHY** (GMAC) |
| **Wi-Fi 2.4GHz** | MediaTek MT7981B / MT7915E 802.11b/g/n/ax 2x2 MIMO (băng thông HE40, tối đa 574 Mbps) |
| **Wi-Fi 5GHz** | MediaTek MT7981B / MT7915E 802.11a/n/ac/ax 2x2 MIMO (**băng thông HE160**, tối đa 2402 Mbps) |
| **Đèn LED (5 LEDs)** | Power (GPIO 8), Inet_L (GPIO 9), WAN_L (GPIO 10), WAN_R (GPIO 11), Inet_R (GPIO 13) |
| **Nút bấm** | WPS (GPIO 0, Active Low) |
| **Cổng UART** | Header 4 chân trên bo mạch, Baudrate `115200 8N1` (GND - TX - RX - 3V3) |

---

## 2. Các điểm kỹ thuật cốt lõi (Reverse-Engineering Findings)

1. **Airoha EN8801SC SGMII TX Polarity**:
   - Mạch phần cứng bo mạch VNPT EW302S đảo cực đường truyền phát (TX pair) giữa SoC MT7981B và PHY EN8801SC.
   - Bắt buộc phải kích hoạt `EN8801S_TX_POLARITY_REVERSE` (giá trị `0x3` tại PBUS register `0x0cf8` / `EN8801S_RG_LTR_CTL`). Nếu không, MT7981 có thể phát dữ liệu tới EN8801SC nhưng chiều nhận (RX) sẽ bị drop 100% gói tin.
   - SGMII PN-Swap trên MT7981 (`mediatek,pnswap` trong DTS) phải được **vô hiệu hóa** (xóa bỏ).

2. **Địa chỉ MAC cố định từ phân vùng Factory**:
   - Base MAC gốc của thiết bị được lưu tại offset `0x04` trong phân vùng `Factory` (`/dev/mtd2`).
   - Cấu hình DTS sử dụng `nvmem-layout` và `mac-base`:
     - Base MAC (`Factory 0x04`): Gán cho Wi-Fi 2.4GHz (`phy0-ap0`)
     - Base MAC + 1: Gán cho LAN (`eth0` / `br-lan`)
     - Base MAC + 2: Gán cho WAN (`eth1`)
     - Base MAC với bit U/L lật: Gán cho Wi-Fi 5GHz (`phy1-ap0`)

3. **Cấu trúc NAND UBI & Tương thích U-Boot Stock**:
   - Lệnh khởi động tự động của U-Boot gốc VNPT gọi `mtkboardboot`, tự động đọc volume `kernel` trong phân vùng `ubi` (`/dev/mtd4`) vào địa chỉ RAM `0x46000000` và gọi `bootm`.
   - Phân vùng UBI được tạo chuẩn gồm 3 volume:
     - Volume 0: `kernel` (chứa FIT image nén LZMA)
     - Volume 1: `rootfs` (chứa SquashFS)
     - Volume 2: `rootfs_data` (chứa UBIFS overlay đọc/ghi cho `/overlay`)

---

## 3. Cấu trúc thư mục Repository

```text
├── config/
│   └── ew302s.config          # OpenWrt diffconfig tối ưu cho EW302S
├── dts/
│   └── mt7981b-vnpt-igate-ew302s.dts   # Device Tree DTS hoàn chỉnh
├── patches/
│   └── 0001-mediatek-filogic-add-support-for-VNPT-iGate-EW302S.patch # Patch chuẩn git OpenWrt
├── rootfs-overlay/
│   └── etc/uci-defaults/99-ew302s-defaults  # Kịch bản khởi chạy tối ưu ban đầu
└── tools/
    ├── tftp_server.py         # TFTP Server độc lập bằng Python (port 69)
    ├── stage4_hardware_test.py # Script kiểm thử tự động phần cứng qua UART + SSH
    ├── flash_nand_and_monitor.py # Script flash NAND tự động và giám sát Cold Boot
    └── rebuild_itb.sh         # Script biên dịch nhanh kernel & đóng gói firmware
```

---

## 4. Hướng dẫn Biên dịch từ Mã nguồn

### Bước 1: Chuẩn bị môi trường & Clone nguồn ImmortalWrt
```bash
# Trên Ubuntu 22.04 / 24.04 / 26.04 (hoặc WSL2)
sudo apt update
sudo apt install -y build-essential git python3 gawk libncurses-dev libssl-dev zlib1g-dev swig unzip wget rsync time file bzr libelf-dev

git clone -b openwrt-25.12 https://github.com/immortalwrt/immortalwrt.git openwrt-ew302s
cd openwrt-ew302s
./scripts/feeds update -a && ./scripts/feeds install -a
```

### Bước 2: Áp dụng Patch hỗ trợ EW302S
```bash
git apply /path/to/patches/0001-mediatek-filogic-add-support-for-VNPT-iGate-EW302S.patch
cp /path/to/rootfs-overlay/etc/uci-defaults/99-ew302s-defaults files/etc/uci-defaults/
chmod +x files/etc/uci-defaults/99-ew302s-defaults
```

### Bước 3: Nạp cấu hình & Biên dịch
```bash
cp /path/to/config/ew302s.config .config
make defconfig
make -j$(nproc) V=s
```

File kết quả sẽ nằm tại `bin/targets/mediatek/filogic/`:
* `openwrt-mediatek-filogic-vnpt_igate_ew302s-initramfs.itb` (ROM chạy thử nghiệm trên RAM qua TFTP)
* `openwrt-mediatek-filogic-vnpt_igate_ew302s-squashfs-sysupgrade.bin` (ROM nạp vĩnh viễn vào NAND)

---

## 5. Hướng dẫn Nạp ROM

### Phương pháp 1: Chạy thử trên RAM qua TFTP (Không rủi ro, không chạm Flash)
1. Kết nối cáp USB-UART với cổng UART trên router (Baud: 115200 8N1).
2. Cắm cáp mạng từ cổng LAN router vào máy tính, đặt IP tĩnh cho PC: `192.168.77.2/24`.
3. Khởi động TFTP Server phục vụ file `initramfs.itb`.
4. Bật nguồn router, nhấn phím bất kỳ để dừng tại menu U-Boot (`MT7981>`).
5. Trong console U-Boot:
   ```text
   setenv ipaddr 192.168.77.1
   setenv serverip 192.168.77.2
   tftpboot 0x46000000 initramfs.itb
   bootm 0x46000000
   ```

### Phương pháp 2: Nạp vĩnh viễn vào NAND Flash qua Sysupgrade
Khi đang ở trong hệ thống OpenWrt (RAM hoặc ROM cũ):
1. Truyền file sysupgrade lên router:
   ```bash
   scp -O openwrt-mediatek-filogic-vnpt_igate_ew302s-squashfs-sysupgrade.bin root@192.168.77.1:/tmp/sysupgrade.bin
   ```
2. Kiểm tra tính tương thích:
   ```bash
   sysupgrade -T /tmp/sysupgrade.bin
   ```
3. Thực thi ghi Flash và khởi động lại:
   ```bash
   sysupgrade -n -v /tmp/sysupgrade.bin
   ```
Router sẽ tự động xóa UBI cũ, tạo lại volume, ghi kernel/rootfs và reboot vào firmware mới vĩnh viễn.

---

## 6. Thông tin Truy cập Mặc định

* **Địa chỉ IP LAN**: `192.168.77.1` (Cổng `eth0`)
* **Địa chỉ WAN**: Tự động nhận DHCP từ Modem gốc (Cổng `eth1`)
* **Giao diện Web LuCI**: `http://192.168.77.1`
* **Tài khoản**: `root` (Mật khẩu: Để trống)
* **Wi-Fi 2.4GHz**: SSID `ImmortalWrt`, Kênh 1, Băng thông HE40
* **Wi-Fi 5GHz**: SSID `ImmortalWrt`, Kênh 36, **Băng thông HE160 (2402 Mbps)**
* **Tăng tốc mạng**: MediaTek Hardware Flow Offloading (HNAT) bật sẵn.

---

## 7. Giấy phép (License)
Mã nguồn phát hành theo giấy phép [GPL-2.0 / MIT](LICENSE).
