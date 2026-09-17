#!/usr/bin/env bash
# ============================================================
# 密码验证工具: 用真实握手验证单个密码是否正确
# 用法: sudo bash verify_password.sh <握手hccapx> <AP_BSSID> <密码>
#   例: sudo bash verify_password.sh /opt/evil-twin/handshakes/gf7e.hccapx C8:75:F4:40:D6:8A 12345678
# 输出含 KEY FOUND 即密码正确
# ============================================================
set -e
HFILE="${1:?用法: $0 <hccapx文件> <AP_BSSID> <密码>}"
BSSID="${2:?}"
PWD="${3:?}"

TMP=$(mktemp /tmp/verify.XXXXXX.txt)
echo "$PWD" > "$TMP"

echo "==> 验证中: $PWD  (对 $HFILE)"
aircrack-ng -w "$TMP" -b "$BSSID" "$HFILE" 2>&1 | grep -aE "KEY FOUND|KEY NOT|No valid|handshake" | head -3
rm -f "$TMP"
