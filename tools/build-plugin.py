#!/usr/bin/env python
"""从 DSH 安装包里重新抽取 dsh-llm-pi-ai 并打补丁，生成仓库根目录的 index.js。

DSH 升级后执行：
    python tools/build-plugin.py            # 重新生成
    python tools/build-plugin.py --check    # 只检查是否需要刷新

app.asar 路径可用环境变量 DSH_ASAR 覆盖。
"""
import argparse
import io
import json
import os
import struct
import sys

ASAR = os.environ.get("DSH_ASAR") or os.path.join(
    os.environ.get("LOCALAPPDATA", os.path.expanduser("~")),
    r"Programs\DeepSeek Harness\resources\app.asar")
SRC = "/dsh/node_modules/@deepseek-ai/dsh-llm-pi-ai"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PKG = "dsh-llm-opencode"
PLUGIN_ID = "llm-opencode"

PATCHES = [
    ('import { openAIResponsesApi } from "@earendil-works/pi-ai/api/openai-responses.lazy";',
     'import { openAIResponsesApi } from "@earendil-works/pi-ai/api/openai-responses.lazy";\n'
     'import { googleGenerativeAIApi } from "@earendil-works/pi-ai/api/google-generative-ai.lazy";',
     "引入 google 协议工厂"),
    ('\t"anthropic-messages": anthropicMessagesApi\n};',
     '\t"anthropic-messages": anthropicMessagesApi,\n'
     '\t"google-generative-ai": googleGenerativeAIApi\n};',
     "PROTOCOLS 加 google"),
    ('\t"openai-responses"\n]);',
     '\t"openai-responses",\n\t"google-generative-ai"\n]);',
     "LISTABLE_PROTOCOLS 加 google"),
    ('const name = "llm-pi-ai";', 'const name = "%s";' % PLUGIN_ID, "插件名"),
    ('const NS = "llm-pi-ai";', 'const NS = "%s";' % PLUGIN_ID, "命名空间"),
]


def read_asar(path):
    with open(ASAR, "rb") as fh:
        head = fh.read(16)
        hsz = struct.unpack("<I", head[4:8])[0]
        jlen = struct.unpack("<I", head[12:16])[0]
        fh.seek(16)
        root = json.loads(fh.read(jlen).decode("utf-8"))
        node = root
        for part in path.strip("/").split("/"):
            node = node["files"][part]
        fh.seek(8 + hsz + int(node["offset"]))
        return fh.read(int(node["size"]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    if not os.path.exists(ASAR):
        raise SystemExit("找不到 app.asar：%s（用 DSH_ASAR 环境变量指定）" % ASAR)

    src = read_asar(SRC + "/lib/index.js").decode("utf-8")
    pkg = json.loads(read_asar(SRC + "/package.json").decode("utf-8"))
    text = src
    for anchor, repl, why in PATCHES:
        if repl in text and anchor not in text:
            print("  已打过: %s" % why)
            continue
        if text.count(anchor) != 1:
            raise SystemExit("补丁锚点未唯一命中: %s —— DSH 版本可能变了" % why)
        text = text.replace(anchor, repl, 1)
        print("  已应用: %s" % why)

    out = os.path.join(ROOT, "index.js")
    if args.check:
        cur = io.open(out, encoding="utf-8").read() if os.path.exists(out) else ""
        print("上游版本 %s；当前包%s" % (pkg["version"], "已是最新" if cur == text else "需要刷新"))
        return 0 if cur == text else 1
    io.open(out, "w", encoding="utf-8", newline="\n").write(text)
    print("已写出 %s（上游 %s）" % (out, pkg["version"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
