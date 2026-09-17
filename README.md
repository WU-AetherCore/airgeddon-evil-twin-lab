# Airgeddon Evil Twin Lab — WiFi 安全攻防实战实验室

> 一套从零起步的 **WiFi 安全研究实战项目**：基于 [Airgeddon](https://github.com/v1s1t0r1sh3r3/airgeddon) 的依赖环境，完整实现 **Evil Twin 自动化钓鱼攻击系统**，配备 Web 控制台一键操作、密码自动验证、假 AP 自动启停，以及从环境搭建到原理讲解的**全套中文教程**。

> ⚠️ **重要声明**：本项目仅用于**安全研究、教学演示、以及对自己拥有或已获授权的网络**进行安全测试。在大多数国家和地区，未经授权对他人 WiFi 实施攻击（包括 Deauth、伪造 AP、钓鱼）属于**违法行为**。使用者须自行承担一切法律责任。请务必在**自己的路由器/自己家的 WiFi** 上练习。

---

## ✨ 功能特性

| 能力 | 说明 |
|---|---|
| 🔍 一键扫描 | Web 界面扫描周围 WiFi，按信号强度排序，显示 SSID/BSSID/信道/加密方式 |
| ⚡ 一键攻击 | 选择目标后自动完成：deauth 踢人 → 伪造同名假 AP → DNS 劫持 → 钓鱼页收密码 |
| 🎣 Captive Portal | 运营商风格认证页，连接假 AP 自动弹出，输入密码即被捕获 |
| 🔐 密码自动验证 | 用抓到的真实 WPA2 握手对捕获密码做即时验证（aircrack-ng 单密码，1 秒出结果） |
| ✅ 自动收尾 | 验证通过 → 受害者页面显示成功 → 4 秒后自动关闭假 AP 恢复环境 |
| 📜 历史记录 | 只记录验证通过的正确密码，独立列显示 时间/WiFi/密码/设备 |
| 🚀 一键部署 | 自动安装 Airgeddon + 全部依赖 + 编译 hostapd-mana + 生成配置 |
| 📚 详细教程 | 8 篇中文教程：环境、侦察、抓握手、攻击原理、自动化系统、排错、防御 |

## 🏗 系统架构

```
┌─────────────────────────────────────────────────────────┐
│                    Web 控制台 (8090)                     │
│        evil_control.py · 扫描/启停/验证/历史记录          │
└──────────────┬───────────────────────────┬──────────────┘
               │ 启动攻击                    │ 密码验证回调
┌──────────────▼───────────┐   ┌───────────▼──────────────┐
│     攻击三件套            │   │  aircrack-ng 单密码验证    │
│  evil-hostapd 假AP(开放)  │   │  对真实握手 hccapx 比对    │
│  evil-dnsmasq DHCP+DNS劫持│   └───────────────────────────┘
│  evil-portal 钓鱼页(80)   │
└──────────────────────────┘
```

**攻击数据流**：受害手机连上假 AP → 系统检测请求被 DNS 劫持 → 钓鱼页自动弹出 → 输入密码 → portal 提交到 `/api/verify` → 与真实握手比对 → 通过则自动关闭假 AP，失败则提示重输。

## 📁 目录结构

```
airgeddon-evil-twin-lab/
├── README.md                  # 本文件
├── LICENSE                    # MIT 许可证
├── docs/                      # 8 篇详细中文教程
│   ├── 01-环境准备与依赖安装.md
│   ├── 02-侦察-扫描目标WiFi.md
│   ├── 03-被动抓取WPA2握手.md
│   ├── 04-EvilTwin钓鱼攻击原理.md
│   ├── 05-自动化系统部署与使用.md
│   ├── 06-密码自动验证机制.md
│   ├── 07-常见问题排错.md
│   └── 08-防御与法律合规.md
├── deploy/                    # 一键部署脚本
│   ├── deploy.sh              #   总入口（推荐）
│   ├── install-airgeddon.sh   #   Airgeddon + 依赖
│   └── build-hostapd-mana.sh  #   hostapd-mana 源码编译
└── scripts/                   # 核心程序
    ├── evil_control.py        #   Web 控制台（参数化配置）
    ├── portal.py              #   Captive Portal 钓鱼页
    ├── auto_capture_handshake.sh  # 自动抓握手
    ├── restart_control.sh     #   重启控制台
    ├── verify_password.sh     #   密码验证 CLI
    ├── config.env.example     #   环境变量配置模板
    ├── evil_auto.conf.example #   hostapd 配置模板
    └── dnsmasq_auto.conf.example # dnsmasq 配置模板
```

## 🚀 快速开始（3 步）

```bash
# 1. 一键部署（自动装依赖 + Airgeddon + 编译 hostapd-mana）
git clone https://github.com/WU-AetherCore/airgeddon-evil-twin-lab.git
cd airgeddon-evil-twin-lab
sudo bash deploy/deploy.sh

# 2. 配置（编辑 /opt/evil-twin/config.env 填网卡/SSID）
#    export WIFI_IFACE="wlx90de80defb54"   # 你的 USB 无线网卡
#    export PORTAL_SSID="目标WiFi名"

# 3. 启动控制台
sudo bash scripts/restart_control.sh
# 浏览器打开 http://<本机IP>:8090 → 扫描 → 选目标 → 开始攻击
```

> **硬件要求**：一台 Linux 主机（Ubuntu 20.04/22.04，x86_64 或 ARM64 均可）+ 一块支持监听模式（monitor）与 AP 模式的 USB 无线网卡（如 MT7612U / RTL8812AU / Atheros AR9271 等）。**不要**用机器内置网卡（会断网）。

## 📖 学习路径（推荐顺序）

1. [01-环境准备与依赖安装](docs/01-环境准备与依赖安装.md) — 硬件接线、依赖、Airgeddon、hostapd-mana 编译
2. [02-侦察-扫描目标WiFi](docs/02-侦察-扫描目标WiFi.md) — iw/airodump 扫描、目标信息、可行性判断
3. [03-被动抓取WPA2握手](docs/03-被动抓取WPA2握手.md) — 监听、deauth 触发重连、hash 提取
4. [04-EvilTwin钓鱼攻击原理](docs/04-EvilTwin钓鱼攻击原理.md) — 原理拆解：deauth → 假AP → DNS劫持 → Portal
5. [05-自动化系统部署与使用](docs/05-自动化系统部署与使用.md) — 控制台使用、完整攻击流程
6. [06-密码自动验证机制](docs/06-密码自动验证机制.md) — WPA2-PMK 验证原理、hash 配置、自动收尾
7. [07-常见问题排错](docs/07-常见问题排错.md) — 全部踩过的坑（端口占用/握手无效/不跳转等）
8. [08-防御与法律合规](docs/08-防御与法律合规.md) — 怎么防、法律红线

## 🛠 已验证环境

本项目在以下环境完成全链路实测（扫描 → 攻击 → 捕获 → 验证 → 自动关闭）：

- **主机**：Orange Pi 5 Pro / Ubuntu 22.04 (aarch64)
- **无线网卡**：MT7612U USB（支持 2.4/5G 监听 + AP）
- **工具版本**：Airgeddon v12.01、aircrack-ng 1.6、hcxtools 6.2.5、hostapd-mana v2.12（源码编译）
- **测试对象**：自家路由器（WPA2-PSK），全部测试经路由器主人授权

## 📄 许可证

[MIT](LICENSE)。Airgeddon 本身为 GPL 协议，使用其代码/脚本时请遵循上游许可。
