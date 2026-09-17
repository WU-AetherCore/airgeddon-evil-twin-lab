#!/usr/bin/env bash
# ============================================================
# Evil Twin Lab 一键部署脚本
# 功能:
#   1. 安装系统依赖 + Airgeddon
#   2. 编译 hostapd-mana
#   3. 准备项目目录与配置模板
# 用法: sudo bash deploy.sh [WIFI_INTERFACE]
#   例: sudo bash deploy.sh wlx90de80defb54
# ============================================================
set -e
export DEBIAN_FRONTEND=noninteractive

IFACE="${1:-}"
BASE_DIR="${EVIL_BASE_DIR:-/opt/evil-twin}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=============================================="
echo " Evil Twin Lab 一键部署"
echo " 项目目录: $BASE_DIR"
echo " 网卡接口: ${IFACE:-<未指定, 稍后配置>}"
echo "=============================================="

# ---------- 1. 依赖 ----------
echo ""
echo "[1/4] 安装系统依赖 + Airgeddon..."
bash "$SCRIPT_DIR/install-airgeddon.sh"

# ---------- 2. hostapd-mana ----------
echo ""
echo "[2/4] 编译 hostapd-mana (假 AP 核心)..."
bash "$SCRIPT_DIR/build-hostapd-mana.sh"

# ---------- 3. 项目目录 ----------
echo ""
echo "[3/4] 准备项目目录..."
mkdir -p "$BASE_DIR/handshakes"
cp "$SCRIPT_DIR/../scripts/evil_control.py" "$BASE_DIR/"
cp "$SCRIPT_DIR/../scripts/portal.py" "$BASE_DIR/"
if [ -z "$IFACE" ]; then
    IFACE=$(ls /sys/class/net | grep -E '^wl' | head -1 || true)
    echo "  自动探测网卡: ${IFACE:-<未找到, 请手动配置>}"
fi
cat > "$BASE_DIR/config.env" <<EOF
export WIFI_IFACE="${IFACE:-wlxYOUR_USB_WIFI_IFACE}"
export EVIL_BASE_DIR="$BASE_DIR"
export EVIL_CTRL_PORT="8090"
export EVIL_GATEWAY_IP="10.0.0.1"
export PORTAL_SSID="YOUR_WIFI_SSID"
export EVIL_HASHES=""
export CTRL_VERIFY_URL="http://127.0.0.1:8090/api/verify"
EOF
chmod 600 "$BASE_DIR/config.env"
echo "  配置已生成: $BASE_DIR/config.env (请编辑填写你的网卡/SSID/握手)"

# ---------- 4. 自检 ----------
echo ""
echo "[4/4] 自检..."
echo "  - aircrack-ng : $(aircrack-ng --help 2>&1 | head -1 || echo '缺失!')"
echo "  - hcxpcapngtool: $(hcxpcapngtool --version 2>&1 | head -1 || echo '缺失!')"
echo "  - dnsmasq     : $(dnsmasq --version 2>&1 | head -1 || echo '缺失!')"
echo "  - hostapd-mana: $(hostapd-mana -v 2>&1 | head -1 || echo '缺失! 请检查编译')"
echo ""
echo "=============================================="
echo " 部署完成！下一步:"
echo "  1) 编辑 $BASE_DIR/config.env 填网卡/SSID"
echo "  2) 抓取目标握手 (见 docs/03-被动抓取WPA2握手.md)"
echo "  3) 启动控制台: sudo bash $BASE_DIR/restart_control.sh"
echo "  4) 浏览器打开: http://<本机IP>:8090"
echo "=============================================="
