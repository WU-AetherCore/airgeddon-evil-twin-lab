#!/usr/bin/env bash
# ============================================================
# Airgeddon + 依赖一键安装脚本
# 适用: Ubuntu 20.04/22.04 (x86_64 / aarch64)
# 用法: sudo bash install-airgeddon.sh
# ============================================================
set -e
export DEBIAN_FRONTEND=noninteractive

echo "[1/4] 安装系统依赖..."
apt-get update -y
apt-get install -y \
    git iw wireless-tools wpasupplicant \
    aircrack-ng reaver bully hashcat \
    hcxtools hcxdumptool \
    dnsmasq hostapd \
    net-tools dkms build-essential \
    libssl-dev libnl-3-dev libnl-genl-3-dev libpcap-dev \
    pkg-config libtool autoconf automake make gcc g++ \
    xterm iproute2 net-tools rfkill \
    python3 python3-pip curl wget || true

echo "[2/4] 安装 Airgeddon (GitHub) ..."
if [ ! -d /opt/airgeddon ]; then
    git clone --depth 1 https://github.com/v1s1t0r1sh3r3/airgeddon.git /opt/airgeddon
fi
cd /opt/airgeddon
chmod +x airgeddon.sh

echo "[3/4] 检查 Airgeddon 依赖..."
# airgeddon 自带依赖检查（-c 只检查不启动）
bash airgeddon.sh -c 2>/dev/null | tail -20 || true

echo "[4/4] 完成。运行方式:"
echo "  cd /opt/airgeddon && sudo bash airgeddon.sh"
echo "  注意: 第一次启动会提示安装缺失依赖, 按 y 自动安装即可"
