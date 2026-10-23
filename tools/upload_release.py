"""把 Release 附件直连真实 IP 上传，绕过 DNS 污染。

背景：本机 DNS 把 github 相关域名都指到 28.0.0.x（污染段），
git push 走 github.com 还能通，但 uploads.github.com 传大文件时被掐断。

做法：用 DoH 查真实 IP，然后带真实 Host/SNI 直连上传。
"""
from __future__ import annotations

import http.client
import json
import pathlib
import socket
import ssl
import subprocess
import sys
import urllib.request

REPO = "silicon-sbt/tianxue-word-pk-bot"
TAG = "v1.0.0"
# DoH 查到的真实 IP
UPLOAD_HOST = "uploads.github.com"
UPLOAD_IP = "20.205.243.161"


def doh_resolve(name: str) -> list[str]:
    for ep in (f"https://dns.google/resolve?name={name}&type=A",
               f"https://cloudflare-dns.com/dns-query?name={name}&type=A"):
        try:
            req = urllib.request.Request(ep, headers={"accept": "application/dns-json"})
            d = json.loads(urllib.request.urlopen(req, timeout=8).read())
            ips = [a["data"] for a in d.get("Answer", []) if a.get("type") == 1]
            if ips:
                return ips
        except Exception:
            continue
    return []


def token() -> str:
    return subprocess.run(["gh", "auth", "token"], capture_output=True,
                          text=True).stdout.strip()


def release_id(tok: str) -> str:
    out = subprocess.run(
        ["gh", "api", f"repos/{REPO}/releases", "--jq",
         f'.[] | select(.tag_name=="{TAG}") | .id'],
        capture_output=True, text=True).stdout.strip()
    return out


def upload(tok: str, rid: str, path: pathlib.Path, ip: str) -> bool:
    data = path.read_bytes()
    size = len(data)
    print(f"  上传 {path.name}  {size/1024/1024:.1f} MB  ->  {ip}")

    ctx = ssl.create_default_context()
    # 关键：连 IP，但 SNI 和 Host 都用真实域名
    sock = socket.create_connection((ip, 443), timeout=60)
    ssock = ctx.wrap_socket(sock, server_hostname=UPLOAD_HOST)
    conn = http.client.HTTPSConnection(UPLOAD_HOST, 443, timeout=300)
    conn.sock = ssock

    url = f"/repos/{REPO}/releases/{rid}/assets?name={path.name}"
    try:
        conn.request("POST", url, body=data, headers={
            "Authorization": f"token {tok}",
            "Content-Type": "application/octet-stream",
            "Content-Length": str(size),
            "Accept": "application/vnd.github+json",
            "User-Agent": "pk-release-uploader",
        })
        resp = conn.getresponse()
        body = resp.read().decode("utf-8", "replace")
        print(f"    HTTP {resp.status}")
        if resp.status in (200, 201):
            j = json.loads(body)
            print(f"    成功: {j.get('browser_download_url')}")
            return True
        print(f"    失败: {body[:300]}")
        return False
    except Exception as e:  # noqa: BLE001
        print(f"    异常: {type(e).__name__}: {e}")
        return False
    finally:
        try:
            conn.close()
        except Exception:
            pass


def main() -> int:
    files = [pathlib.Path(p) for p in sys.argv[1:]]
    if not files:
        print("用法: python -X utf8 tools/upload_release.py <文件...>")
        return 2

    tok = token()
    if not tok:
        print("拿不到 gh token")
        return 1
    rid = release_id(tok)
    if not rid:
        print(f"找不到 tag {TAG} 的 release")
        return 1
    print(f"release id: {rid}\n")

    ips = doh_resolve(UPLOAD_HOST) or [UPLOAD_IP]
    ok = True
    for f in files:
        if not f.exists():
            print(f"  跳过（不存在）: {f}")
            ok = False
            continue
        done = False
        for ip in ips:
            if upload(tok, rid, f, ip):
                done = True
                break
            print(f"    换 IP 重试")
        if not done:
            # 兜底：走 gh 自带上传（DNS 正常时有概率成功）
            print("    尝试 gh release upload ...")
            r = subprocess.run(["gh", "release", "upload", TAG, str(f), "--clobber"],
                               capture_output=True, text=True)
            if r.returncode == 0:
                print("    成功")
                done = True
        ok = ok and done
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
