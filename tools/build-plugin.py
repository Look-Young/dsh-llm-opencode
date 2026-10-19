#!/usr/bin/env python
"""从"运行时实际使用的那份"官方插件重新抽取并打补丁，生成仓库根目录的 index.js。

为什么不是从 app.asar 抽：profile 的 node_modules 是 junction 指向一个旧版 npx 缓存
（例如 @deepseek-ai/dsh-* 0.1.0-rc.6、pi-ai 0.82.1），插件运行时解析到的就是那一层。
照 asar 里的新版抽，会 import 到旧层不存在的包（如 dsh-util-values、pi-ai/utils/overflow），
插件会直接加载失败。所以默认源 = profile 里已安装的官方插件，asar 仅作兜底。

用法:
    python tools/build-plugin.py            # 重新生成 index.js + package.json
    python tools/build-plugin.py --check    # 只检查是否需要刷新
    python tools/build-plugin.py --source <官方插件 lib/index.js 路径>
"""
import argparse
import io
import json
import os
import struct
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOME = os.path.expanduser("~")
PROFILE_PLUGIN = os.path.join(
    HOME, ".dsh", "profiles", "node_modules", "@deepseek-ai", "dsh-llm-pi-ai")
ASAR = os.environ.get("DSH_ASAR") or os.path.join(
    os.environ.get("LOCALAPPDATA", HOME),
    r"Programs\DeepSeek Harness\resources\app.asar")

PKG = "dsh-llm-opencode"
ROW = "llm-opencode"

# 4 处补丁（锚点对 0.1.0-rc.6 与 0.2.x 都成立）
PATCHES = [
    (
        'import { openAIResponsesApi } from "@earendil-works/pi-ai/api/openai-responses.lazy";',
        'import { openAIResponsesApi } from "@earendil-works/pi-ai/api/openai-responses.lazy";\n'
        'import { googleGenerativeAIApi } from "@earendil-works/pi-ai/api/google-generative-ai.lazy";',
        "引入 google 协议工厂",
    ),
    (
        '\t"anthropic-messages": anthropicMessagesApi\n};',
        '\t"anthropic-messages": anthropicMessagesApi,\n'
        '\t"google-generative-ai": googleGenerativeAIApi\n};',
        "PROTOCOLS 表增加 google",
    ),
    (
        'const name = "llm-pi-ai";',
        'const name = "%s";' % ROW,
        "插件内部名 -> llm-opencode",
    ),
    (
        'settingsNamespace("llm-pi-ai")',
        'settingsNamespace("%s")' % ROW,
        "设置命名空间 -> llm-opencode",
    ),
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


def locate_source(explicit):
    """返回 (index.js 文本, 版本, 来源说明)。优先运行时那一份。"""
    if explicit:
        path = explicit
        if not os.path.exists(path):
            raise SystemExit("指定源不存在: %s" % path)
        pkg = os.path.join(os.path.dirname(os.path.dirname(path)), "package.json")
        ver = json.load(io.open(pkg, encoding="utf-8")).get("version") if os.path.exists(pkg) else "?"
        return io.open(path, encoding="utf-8").read(), ver, path

    local = os.path.join(PROFILE_PLUGIN, "lib", "index.js")
    if os.path.exists(local):
        pkg = os.path.join(PROFILE_PLUGIN, "package.json")
        ver = json.load(io.open(pkg, encoding="utf-8")).get("version", "?")
        return io.open(local, encoding="utf-8").read(), ver, "profile 运行时层 (%s)" % local

    if not os.path.exists(ASAR):
        raise SystemExit("既找不到 profile 里的官方插件，也找不到 app.asar")
    text = read_asar("/dsh/node_modules/@deepseek-ai/dsh-llm-pi-ai/lib/index.js").decode("utf-8")
    ver = json.loads(read_asar("/dsh/node_modules/@deepseek-ai/dsh-llm-pi-ai/package.json")
                     .decode("utf-8")).get("version", "?")
    return text, ver, "app.asar 内置 (%s)" % ASAR


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--source")
    args = ap.parse_args()

    src, ver, origin = locate_source(args.source)
    print("源: %s  版本 %s" % (origin, ver))

    text = src
    for anchor, repl, why in PATCHES:
        if repl in text and anchor not in text:
            print("  已打过: %s" % why)
            continue
        if text.count(anchor) != 1:
            raise SystemExit("锚点未唯一命中(%d 次): %s —— 版本可能又变了" % (text.count(anchor), why))
        text = text.replace(anchor, repl, 1)
        print("  已应用: %s" % why)

    out_index = os.path.join(ROOT, "index.js")
    out_pkg = os.path.join(ROOT, "package.json")
    if args.check:
        cur = io.open(out_index, encoding="utf-8").read() if os.path.exists(out_index) else ""
        print("当前包%s" % ("已是最新" if cur == text else "需要刷新"))
        return 0 if cur == text else 1

    io.open(out_index, "w", encoding="utf-8", newline="\n").write(text)

    manifest = {
        "name": PKG,
        "version": ver + "-oc.1",
        "private": True,
        "type": "module",
        "main": "index.js",
        "exports": {".": "./index.js"},
        "files": ["index.js", "cordis.patch.yml", "README.md", "LICENSE", "DESIGN.md", "tools"],
        "dsh": {"bundle": {"patch": "./cordis.patch.yml"}},
        "meta": {
            "title": "OpenCode Go (多协议直连)",
            "description": "直连 OpenCode Go：responses / chat / messages / google 四种协议分组路由，"
                           "安装即用，自带模型清单刷新与插件重建脚本。",
        },
    }
    io.open(out_pkg, "w", encoding="utf-8", newline="\n").write(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")

    print("\n已写出 index.js (%d 字节) 与 package.json (版本 %s-oc.1)" % (len(text.encode()), ver))
    return 0


if __name__ == "__main__":
    sys.exit(main())
