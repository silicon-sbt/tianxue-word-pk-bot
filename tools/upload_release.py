"""上传 Release 附件：直连真实 IP + 长重试。

背景（本机实测）：
  1. DNS 把 github 域名污染到 28.0.0.x，那批 IP 传大文件必被 reset。
  2. 用 DoH 查到真实 IP（20.205.243.161）后直连，小文件 100% 成功，
     大文件仍会中途断 —— 是运营商对长连接的限制，不是 GitHub 的问题。
  3. GitHub 的 release asset 上传**不支持 Content-Range 断点续传**，
     所以大文件只能整体重试，或切块传。

策略：
  文件小于 CHUNK_MB 就整体传；大于就切成多块，逐块传。
  每块失败自动重试 RETRIES 次，全部传完后给出合并命令。
"""
from __future__ import annotations

import hashlib
import http.client
import json
import pathlib
import socket
import ssl
import subprocess
import sys
import time

REPO = "silicon-sbt/tianxue-word-pk-bot"
TAG = "v1.0.0"
UPLOAD_HOST = "uploads.github.com"
CHUNK_MB = 4
RETRIES = 8


def doh(name: str) -> list[str]:
    for ep in (f"https://dns.google/resolve?name={name}&type=A",
               f"https://cloudflare-dns.com/dns-query?name={name}&type=A"):
        try:
            req = urllib_request(ep)
            d = json.loads(req)
            ips = [a["data"] for a in d.get("Answer", []) if a.get("type") == 1]
            if ips:
                return ips
        except Exception:
            continue
    return []


def urllib_request(url: str) -> bytes:
    import urllib.request
    req = urllib.request.Request(url, headers={"accept": "application/dns-json"})
    return urllib.request.urlopen(req, timeout=10).read()


def token() -> str:
    return subprocess.run(["gh", "auth", "token"], capture_output=True,
                          text=True).stdout.strip()


def release_id(tok: str) -> str:
    for _ in range(5):
        p = subprocess.run(
            ["gh", "api", f"repos/{REPO}/releases", "--jq",
             f'.[] | select(.tag_name=="{TAG}") | .id'],
            capture_output=True, text=True)
        if p.returncode == 0 and p.stdout.strip():
            return p.stdout.strip()
        time.sleep(3)
    return ""


def existing(tok: str) -> set[str]:
    p = subprocess.run(
        ["gh", "api", f"repos/{REPO}/releases/tags/{TAG}",
         "--jq", ".assets[].name"],
        capture_output=True, text=True)
    return set(p.stdout.split()) if p.returncode == 0 else set()


def post_asset(tok: str, rid: str, name: str, data: bytes, ip: str) -> bool:
    try:
        ctx = ssl.create_default_context()
        sock = socket.create_connection((ip, 443), timeout=30)
        ssock = ctx.wrap_socket(sock, server_hostname=UPLOAD_HOST)
        conn = http.client.HTTPSConnection(UPLOAD_HOST, 443, timeout=300)
        conn.sock = ssock
        url = f"/repos/{REPO}/releases/{rid}/assets?name={name}"
        conn.request("POST", url, body=data, headers={
            "Authorization": f"token {tok}",
            "Content-Type": "application/octet-stream",
            "Content-Length": str(len(data)),
            "Accept": "application/vnd.github+json",
            "User-Agent": "pk-uploader",
        })
        resp = conn.getresponse()
        body = resp.read().decode("utf-8", "replace")
        conn.close()
        if resp.status in (200, 201):
            return True
        # 已存在同名时 GitHub 回 422，先删再传
        if resp.status == 422 and "already_exists" in body:
            subprocess.run(["gh", "release", "delete-asset", TAG, name, "-y"],
                           capture_output=True)
            return False
        return False
    except Exception:  # noqa: BLE001
        return False


def upload_one(tok: str, rid: str, name: str, data: bytes, ips: list[str]) -> bool:
    print(f"  {name}  {len(data)/1024/1024:.2f} MB", end="", flush=True)
    for attempt in range(RETRIES):
        ip = ips[attempt % len(ips)]
        if post_asset(tok, rid, name, data, ip):
            print("  OK")
            return True
        print(f"  .{attempt+1}", end="", flush=True)
        time.sleep(1.5)
    print("  失败")
    return False


def sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def main() -> int:
    files = [pathlib.Path(p) for p in sys.argv[1:]]
    if not files:
        print("用法: python -X utf8 tools/upload_release.py <文件...>")
        return 2

    tok = token()
    rid = release_id(tok)
    if not tok or not rid:
        print("拿不到 token 或 release id")
        return 1
    ips = doh(UPLOAD_HOST) or ["20.205.243.161"]
    print(f"release {rid}  真实 IP {ips}\n")

    have = existing(tok)
    ok_all = True

    for f in files:
        if not f.exists():
            print(f"  跳过 {f}（不存在）")
            ok_all = False
            continue
        raw = f.read_bytes()
        size_mb = len(raw) / 1024 / 1024
        print(f"== {f.name}  {size_mb:.1f} MB  sha256={sha256(raw)[:16]} ==")

        if size_mb <= CHUNK_MB:
            if f.name in have:
                print("  已存在，跳过")
                continue
            if not upload_one(tok, rid, f.name, raw, ips):
                ok_all = False
            continue

        # 大文件切块
        chunk = CHUNK_MB * 1024 * 1024
        n = (len(raw) + chunk - 1) // chunk
        print(f"  切成 {n} 块，每块 {CHUNK_MB}MB")
        parts = []
        for i in range(n):
            a = i * chunk
            b = min(a + chunk, len(raw))
            part_name = f"{f.name}.part{i+1:02d}"
            parts.append(part_name)
            if part_name in have:
                print(f"  {part_name} 已存在")
                continue
            if not upload_one(tok, rid, part_name, raw[a:b], ips):
                ok_all = False

        if ok_all:
            print(f"\n  合并方法（Windows cmd）：")
            cmd = " + ".join([]) or "copy /b " + " + ".join(parts) + f" {f.name}"
            print(f"    {cmd}")
            print(f"  校验 sha256: {sha256(raw)}")

    print()
    print("全部完成" if ok_all else "有失败项")
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
