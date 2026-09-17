#!/usr/bin/env bash
# ============================================================
# 重启 Evil Twin 控制台（停止攻击 + 恢复网卡 + 重启控制服务）
# 用法: sudo bash restart_control.sh
# ============================================================
export PATH=$PATH:/usr/sbin:/usr/local/sbin
BASE_DIR="${EVIL_BASE_DIR:-/opt/evil-twin}"
IFACE="${WIFI_IFACE:-wlxYOUR_USB_WIFI_IFACE}"

echo "==> 停止攻击服务..."
systemctl stop evil-hostapd evil-portal evil-dnsmasq 2>/dev/null || true
systemctl reset-failed evil-hostapd evil-portal evil-dnsmasq 2>/dev/null || true
systemctl start systemd-resolved 2>/dev/null || true

echo "==> 恢复网卡为 managed..."
ip link set "$IFACE" down 2>/dev/null || true
iw dev "$IFACE" set type managed 2>/dev/null || true
ip addr flush dev "$IFACE" 2>/dev/null || true
ip link set "$IFACE" up 2>/dev/null || true
nmcli dev set "$IFACE" managed yes 2>/dev/null || true
sleep 1

echo "==> 重启控制台..."
systemctl stop evil-ctrl 2>/dev/null || true
systemctl reset-failed evil-ctrl 2>/dev/null || true
systemd-run --unit=evil-ctrl --collect python3 "$BASE_DIR/evil_control.py" 2>&1 | tail -1
sleep 3
systemctl is-active evil-ctrl || true

echo "==> 完成。访问 http://<本机IP>:8090"
