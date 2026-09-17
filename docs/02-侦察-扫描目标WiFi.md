# 第 2 章 侦察：找到攻击目标

> 攻击之前先摸清目标：SSID、BSSID、信道、加密方式、信号强度。所有侦察均**被动或低影响**，属正常无线运维操作。

## 2.1 用 iw 扫描（managed 模式）

```bash
# 确保网卡是 managed + up
sudo nmcli dev set wlxYOUR_IFACE managed yes
sudo ip link set wlxYOUR_IFACE up

# 全信道扫描
sudo iw dev wlxYOUR_IFACE scan | grep -E "BSS |SSID:|freq:|signal:|RSN|WPA"
```

输出示例：

```
BSS c8:75:f4:40:d6:8a(on wlxYOUR_IFACE)
    SSID: CMCC-gf7e
    freq: 2437
    signal: -66.00 dBm
    RSN:  WPA-PSK-CCMP+TKIP
```

字段含义：
- **BSS**：AP 的 MAC（BSSID），攻击时 deauth 的目标
- **SSID**：WiFi 名字
- **freq**：2437MHz = 信道 6（`(2437-2407)/5=6`）
- **signal**：信号强度，越接近 0 越强（-30 极强 / -70 较弱）
- **RSN / WPA**：加密方式（WPA2-PSK / WPA3 等）

## 2.2 用 airodump-ng 扫描（monitor 模式，更专业）

```bash
# 切监听模式
sudo nmcli dev set wlxYOUR_IFACE managed no
sudo ip link set wlxYOUR_IFACE down
sudo iw dev wlxYOUR_IFACE set type monitor
sudo ip link set wlxYOUR_IFACE up

# 扫描（每 3 秒刷新，Ctrl+C 退出）
sudo airodump-ng wlxYOUR_IFACE
```

```
 BSSID              CH  ENC   CIPHER  AUTH  ESSID
 C8:75:F4:40:D6:8A   6  WPA2  CCMP    PSK   CMCC-gf7e
 FA:07:B2:AC:30:45   6  WPA2  CCMP    PSK   WU_5G
```

## 2.3 记录目标信息

本项目实战目标示例（**请替换为你自己的目标**）：

| 字段 | 值 |
|---|---|
| SSID | CMCC-gf7e |
| BSSID | C8:75:F4:40:D6:8A |
| 信道 | 6（2.4GHz，无 5G） |
| 加密 | WPA2-PSK (CCMP) |

## 2.4 攻击可行性判断

| 条件 | 判断 |
|---|---|
| 加密为 WPA/WPA2-PSK | ✅ 可攻击（Evil Twin 针对 PSK） |
| 加密为 WPA3-SAE | ⚠️ 较难（有 Dragonfly 握手保护，部分旧设备仍会降级） |
| 企业级 802.1X | ⚠️ 需要证书伪造，超出本项目范围 |
| 开放网络 | 无需攻击，直接连 |

> ⚠️ **只对自己拥有或已获授权的网络测试**。扫描他人网络在部分地区也受法律约束。

## 2.5 信号与信道细节（实战经验）

- 2.4GHz 信道 1/6/11 互不重叠，5GHz 信道更多
- 受害者手机/设备最好离假 AP 近一些（同一房间），deauth 和假 AP 广播更稳
- 目标 AP 有多个 BSSID（双频）时，选择**受害者设备连接的那个频段**（本项目的假 AP 只在 2.4GHz，所以目标也选 2.4GHz 的 BSSID）

侦察完成 → 进入 [第 3 章：抓握手](03-被动抓取WPA2握手.md)。
