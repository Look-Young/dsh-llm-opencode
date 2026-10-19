#!/usr/bin/env python
"""探测 OpenCode Go 上游，刷新 cordis.patch.yml 里的路由清单。

    python tools/refresh-routes.py            # 只显示结果
    python tools/refresh-routes.py --write    # 写回 cordis.patch.yml

只保留真正返回 200 的模型；图片能力位来自 tools/modalities.json。
"""
import argparse
import io
import json
import os
import re
import sys
import time
import uuid

import requests
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATCH = os.path.join(ROOT, "cordis.patch.yml")
MODAL = os.path.join(ROOT, "tools", "modalities.json")
BASE = "https://opencode.ai/inference/go/v1"
CREDS = os.path.expanduser(r"~\.dsh\.credentials.yaml")

ROUTE_NAME = {"openai-responses": "oc-resp", "openai-completions": "oc-chat",
              "anthropic-messages": "oc-msg"}
ROUTE_TITLE = {"openai-responses": "OpenCode Go · Responses",
               "openai-completions": "OpenCode Go · Chat",
               "anthropic-messages": "OpenCode Go · Messages"}
# 每个协议优先试的模型顺序；上游新增的模型会自动按 responses -> chat -> messages 探测
PROBE_ORDER = ["openai-responses", "openai-completions", "anthropic-messages"]


def api_key():
    for line in io.open(CREDS, encoding="utf-8"):
        if "OPENCODE_GO_API_KEY" in line:
            return line.split(":", 1)[1].strip()
    raise SystemExit("~/.dsh/.credentials.yaml 里没有 OPENCODE_GO_API_KEY")


def live_models(key):
    r = requests.get(BASE + "/models", timeout=30, headers={
        "Authorization": "Bearer " + key, "x-opencode-session": uuid.uuid4().hex,
        "user-agent": "dsh-opencode/1.0"})
    r.raise_for_status()
    return [m["id"] for m in r.json().get("data", [])]


def probe(model, api, key, sid):
    h = {"Content-Type": "application/json", "x-opencode-session": sid,
         "user-agent": "dsh-opencode/1.0"}
    if api == "openai-responses":
        url, body = BASE + "/responses", {"model": model, "input": "hi",
                                          "max_output_tokens": 16, "stream": True}
        h["Authorization"] = "Bearer " + key
    elif api == "openai-completions":
        url, body = BASE + "/chat/completions", {"model": model, "max_tokens": 16, "stream": True,
                                                 "messages": [{"role": "user", "content": "hi"}]}
        h["Authorization"] = "Bearer " + key
    else:
        url, body = BASE + "/messages", {"model": model, "max_tokens": 16, "stream": True,
                                         "messages": [{"role": "user", "content": "hi"}]}
        h["x-api-key"] = key
        h["anthropic-version"] = "2023-06-01"
    for attempt in (1, 2):
        try:
            r = requests.post(url, headers=h, json=body, timeout=90, stream=True)
            r.close()
            if r.status_code == 200:
                return True
            if r.status_code in (429, 500, 502, 503, 504) and attempt == 1:
                time.sleep(2)
                continue
            return False
        except Exception:
            if attempt == 1:
                time.sleep(2)
                continue
            return False
    return False


def render(by_api, session):
    lines = ["# dsh-llm-opencode: 直连 OpenCode Go，一个 bundle 接入三种协议。",
             "# 路由配置内联在这里，所以安装本 bundle 后模型立刻出现，无需再改 profile。",
             "- insert:", "    - id: llm-opencode", "      name: '%s'" % "dsh-llm-opencode",
             "      config:", "        providers:"]
    total = 0
    for api in PROBE_ORDER:
        models = by_api.get(api) or []
        if not models:
            continue
        total += len(models)
        lines += ["          %s:" % ROUTE_NAME[api],
                  "            api: %s" % api,
                  "            displayName: %s" % ROUTE_TITLE[api],
                  "            baseURL: %s" % BASE,
                  "            apiKeyEnv: OPENCODE_GO_API_KEY",
                  "            headers:",
                  "              x-opencode-session: %s" % session,
                  "              user-agent: dsh-opencode/1.0",
                  "            models:"]
        for mid, name, has_img in models:
            lines.append("              - id: %s" % mid)
            lines.append("                name: %s" % name)
            if has_img:
                lines.append("                input: [text, image]")
    return "\n".join(lines) + "\n", total


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()

    caps = json.load(io.open(MODAL, encoding="utf-8")) if os.path.exists(MODAL) else {}
    key = api_key()
    sid = "dsh-opencode-" + uuid.uuid4().hex[:24]
    ids = live_models(key)
    print("上游 %d 个模型，逐个探测协议…" % len(ids))

    by_api = {}
    dropped = []
    for mid in ids:
        placed = None
        for api in PROBE_ORDER:
            if probe(mid, api, key, sid):
                placed = api
                break
        if not placed:
            dropped.append(mid)
            print("  %-34s 无可用协议" % mid)
            continue
        name = mid
        has_img = "image" in ((caps.get(mid) or {}).get("input") or [])
        by_api.setdefault(placed, []).append((mid, name, has_img))
        print("  %-34s -> %s%s" % (mid, placed, "  [image]" if has_img else ""))

    text, total = render(by_api, sid)
    print("\n可用 %d 个；不可用 %d 个: %s" % (total, len(dropped), ", ".join(dropped) or "无"))
    if args.write:
        io.open(PATCH, "w", encoding="utf-8", newline="\n").write(text)
        print("已写入 %s" % PATCH)
    else:
        print("（未写入；加 --write 生效）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
