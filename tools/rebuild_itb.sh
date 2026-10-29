#!/usr/bin/env bash
set -euo pipefail
export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

cd "$HOME/openwrt-ew302s"
SCRATCH="/mnt/c/Users/Admin/.gemini/antigravity/scratch/openwrt-ew302s"

# 1. Update DTS in source and kernel build_dir
cp -vf "$SCRATCH/mt7981b-vnpt-igate-ew302s.dts" target/linux/mediatek/dts/mt7981b-vnpt-igate-ew302s.dts
cp -vf "$SCRATCH/mt7981b-vnpt-igate-ew302s.dts" build_dir/target-aarch64_cortex-a53_musl/linux-mediatek_filogic/linux-6.12.112/arch/arm64/boot/dts/mediatek/mt7981b-vnpt-igate-ew302s.dts

# 2. Ensure 02_network and 99-ew302s-defaults have LAN=eth0 WAN=eth1
cp -vf "$SCRATCH/99-ew302s-defaults" files/etc/uci-defaults/99-ew302s-defaults
mkdir -p build_dir/target-aarch64_cortex-a53_musl/root-mediatek/etc/uci-defaults
cp -vf "$SCRATCH/99-ew302s-defaults" build_dir/target-aarch64_cortex-a53_musl/root-mediatek/etc/uci-defaults/99-ew302s-defaults

python3 -c '
p = "target/linux/mediatek/filogic/base-files/etc/board.d/02_network"
txt = open(p).read()
if "vnpt,igate-ew302s)" in txt:
    txt = txt.replace("ucidef_set_interface_lan \"eth0 eth1\"", "ucidef_set_interfaces_lan_wan \"eth0\" \"eth1\"")
    open(p, "w").write(txt)

p_root = "build_dir/target-aarch64_cortex-a53_musl/root-mediatek/etc/board.d/02_network"
try:
    txt_root = open(p_root).read()
    txt_root = txt_root.replace("ucidef_set_interface_lan \"eth0 eth1\"", "ucidef_set_interfaces_lan_wan \"eth0\" \"eth1\"")
    txt_root = txt_root.replace("ucidef_set_interfaces_lan_wan \"eth0 eth1\"", "ucidef_set_interfaces_lan_wan \"eth0\" \"eth1\"")
    open(p_root, "w").write(txt_root)
except Exception as e:
    print(e)
'

# 3. Update pcs-mtk-lynxi.c in kernel build tree to explicitly clear PN_SWAP when disabled and allow PHY state resolution on SGMII
python3 -c '
p = "build_dir/target-aarch64_cortex-a53_musl/linux-mediatek_filogic/linux-6.12.112/drivers/net/pcs/pcs-mtk-lynxi.c"
txt = open(p).read()

old_pnswap = """\t\tif (mpcs->flags & MTK_SGMII_FLAG_PN_SWAP)
\t\t\tregmap_update_bits(mpcs->regmap, SGMSYS_QPHY_WRAP_CTRL,
\t\t\t\t\t   SGMII_PN_SWAP_MASK,
\t\t\t\t\t   SGMII_PN_SWAP_TX_RX);"""

new_pnswap = """\t\tif (mpcs->flags & MTK_SGMII_FLAG_PN_SWAP)
\t\t\tregmap_update_bits(mpcs->regmap, SGMSYS_QPHY_WRAP_CTRL,
\t\t\t\t\t   SGMII_PN_SWAP_MASK,
\t\t\t\t\t   SGMII_PN_SWAP_TX_RX);
\t\telse
\t\t\tregmap_update_bits(mpcs->regmap, SGMSYS_QPHY_WRAP_CTRL,
\t\t\t\t\t   SGMII_PN_SWAP_MASK, 0);"""

if "SGMII_PN_SWAP_MASK, 0);" not in txt:
    assert old_pnswap in txt, "old_pnswap not found"
    txt = txt.replace(old_pnswap, new_pnswap, 1)

old_get_state = """\tregmap_read(mpcs->regmap, SGMSYS_PCS_ADVERTISE, &adv);
\tphylink_mii_c22_pcs_decode_state(state, bmsr, FIELD_GET(SGMII_LPA, adv));
}"""

new_get_state = """\tregmap_read(mpcs->regmap, SGMSYS_PCS_ADVERTISE, &adv);
\tphylink_mii_c22_pcs_decode_state(state, bmsr, FIELD_GET(SGMII_LPA, adv));
\tif (state->interface == PHY_INTERFACE_MODE_SGMII && !state->link) {
\t\tstate->link = true;
\t\tstate->an_complete = true;
\t\tstate->speed = SPEED_1000;
\t\tstate->duplex = DUPLEX_FULL;
\t}
}"""

if "state->interface == PHY_INTERFACE_MODE_SGMII && !state->link" not in txt:
    assert old_get_state in txt, "old_get_state not found"
    txt = txt.replace(old_get_state, new_get_state, 1)

open(p, "w").write(txt)
'

# 3b. Patch en8801sc.c to set EN8801S_TX_POLARITY_REVERSE (0x3 in 0x0cf8) and pulse BIT(4) in phase1 & phase2 (matching EW302S U-Boot 0x4362d..0x4367d)
python3 -c '
for p in [
    "target/linux/mediatek/files/drivers/net/phy/en8801sc.c",
    "build_dir/target-aarch64_cortex-a53_musl/linux-mediatek_filogic/linux-6.12.112/drivers/net/phy/en8801sc.c",
]:
    txt = open(p).read()
    txt = txt.replace("EN8801S_TX_POLARITY_NORMAL;", "EN8801S_TX_POLARITY_REVERSE;")
    old_p2 = "\tpbus_data = airoha_pbus_read(mbus, pbus_addr, 0x1690);"
    new_p2 = """\tpbus_data = airoha_pbus_read(mbus, pbus_addr, EN8801S_RG_LTR_CTL);
\tret = airoha_pbus_write(mbus, pbus_addr, EN8801S_RG_LTR_CTL, pbus_data | 0x13);
\tif (ret < 0)
\t\treturn ret;
\tmdelay(10);
\tpbus_data = (pbus_data & ~0x10) | EN8801S_RX_POLARITY_NORMAL | EN8801S_TX_POLARITY_REVERSE;
\tret = airoha_pbus_write(mbus, pbus_addr, EN8801S_RG_LTR_CTL, pbus_data);
\tif (ret < 0)
\t\treturn ret;

\tpbus_data = airoha_pbus_read(mbus, pbus_addr, 0x1690);"""
    if "pbus_data | 0x13" not in txt:
        assert old_p2 in txt, f"old_p2 not found in {p}"
        txt = txt.replace(old_p2, new_p2, 1)
    open(p, "w").write(txt)
    print("Patched", p)
'

# 4. Recompile kernel DTB and install initramfs.itb + squashfs-sysupgrade.bin
make target/linux/compile -j$(nproc) V=s
make target/linux/install -j$(nproc) V=s

BIN_DIR="bin/targets/mediatek/filogic"
ITB_FILE="$BIN_DIR/immortalwrt-mediatek-filogic-vnpt_igate_ew302s-initramfs.itb"
TARGET_OPENWRT_ITB="$BIN_DIR/openwrt-mediatek-filogic-vnpt_igate_ew302s-initramfs.itb"
SYSUPGRADE_FILE="$BIN_DIR/immortalwrt-mediatek-filogic-vnpt_igate_ew302s-squashfs-sysupgrade.bin"

cp -vf "$ITB_FILE" "$TARGET_OPENWRT_ITB"
mkdir -p /mnt/c/tftp
cp -vf "$TARGET_OPENWRT_ITB" /mnt/c/tftp/initramfs.itb
cp -vf "$SYSUPGRADE_FILE" /mnt/c/tftp/openwrt-mediatek-filogic-vnpt_igate_ew302s-squashfs-sysupgrade.bin
ls -lh "$TARGET_OPENWRT_ITB" /mnt/c/tftp/initramfs.itb /mnt/c/tftp/openwrt-mediatek-filogic-vnpt_igate_ew302s-squashfs-sysupgrade.bin
echo "=== [REBUILD ITB COMPLETED SUCCESSFULLY] ==="
