#!/usr/bin/env bash
# ============================================================
# hostapd-mana 源码编译安装脚本
# 说明: 本项目的 Evil Twin 假 AP 依赖 hostapd-mana 的
#       mana_wpaout 开放模式特性；发行版自带的 hostapd 不支持，
#       需要从源码编译。
# 用法: sudo bash build-hostapd-mana.sh
# ============================================================
set -e
export DEBIAN_FRONTEND=noninteractive

echo "[1/5] 安装编译依赖..."
apt-get update -y
apt-get install -y build-essential pkg-config libssl-dev \
    libnl-3-dev libnl-genl-3-dev libnl-route-3-dev \
    libpcap-dev git || true

echo "[2/5] 克隆 hostapd-mana 源码..."
MANA_DIR=/opt/hostapd-mana
if [ ! -d "$MANA_DIR" ]; then
    git clone --depth 1 https://github.com/sensepost/hostapd-mana.git "$MANA_DIR"
fi
cd "$MANA_DIR"

echo "[3/5] 编译..."
cd hostapd
if [ ! -f .config ]; then
    cp defconfig .config 2>/dev/null || true
fi
sed -i 's/#CONFIG_MANA/CONFIG_MANA/g' .config 2>/dev/null || true
sed -i 's/#CONFIG_SAE/CONFIG_SAE/g' .config 2>/dev/null || true
make -j$(nproc)

echo "[4/5] 安装到 /usr/local/sbin/hostapd-mana..."
install -m 755 hostapd "$MANA_DIR/../hostapd-mana" 2>/dev/null || true
install -m 755 hostapd /usr/local/sbin/hostapd-mana
ln -sf /usr/local/sbin/hostapd-mana /usr/sbin/hostapd-mana 2>/dev/null || true

echo "[5/5] 验证..."
hostapd-mana -v 2>&1 | head -3 || /usr/local/sbin/hostapd-mana -v 2>&1 | head -3
echo "完成: $(which hostapd-mana)"
echo "验证 mana 特性:"
hostapd-mana -h 2>&1 | grep -i mana | head -5 || echo "  (用 -h 查看, 支持 mana_wpaout 即可)"
