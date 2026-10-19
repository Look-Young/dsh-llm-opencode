# dsh-llm-opencode

给 [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness) 用的插件：
**直连 OpenCode Go，一个 bundle 接入三种协议**，不需要本地网关、不需要代理进程。

## 它解决什么

DSH 自带的 `dsh-llm-pi-ai` 只允许自定义路由声明三种协议中的任意一种，但
OpenCode Go 的模型分散在不同协议上（`/responses`、`/chat/completions`、`/messages`），
而且模型清单经常变。本插件：

- 内置 3 条路由，按协议分组，**一次安装 = 32 个模型全部出现在模型列表里**；
- 保留 `opencode-go` 目录路由不动（官方目录里的模型照旧可用）；
- 自带 `tools/refresh-routes.py`，一条命令按上游实时清单重建路由；
- 自带 `tools/build-plugin.py`，DSH 升级后一条命令重新打补丁。

## 安装

### 方式一：从 GitHub 安装（推荐）

DSH 设置 → 插件 → 安装，填：

```
github:<你的用户名>/dsh-llm-opencode
```

或把本仓库克隆到本地后，在插件页选择「从目录安装」，目录选仓库根目录。

### 方式二：本地目录

```powershell
git clone https://github.com/<你的用户名>/dsh-llm-opencode
# DSH 插件页 → 安装 → 选这个目录
```

安装后**重启 DSH**，模型列表里会出现「OpenCode Go · Responses / Chat / Messages」三组。

## 前置条件

`~/.dsh/.credentials.yaml` 里要有 OpenCode 的 key：

```yaml
OPENCODE_GO_API_KEY: oc_sk_xxx
```

插件通过 `apiKeyEnv: OPENCODE_GO_API_KEY` 引用它。

## 为什么是「打补丁的插件」

DSH 官方插件的协议表只有 3 项，而 pi-ai 本身已实现第四种协议
（`google-generative-ai`）。本插件把官方 `dsh-llm-pi-ai` 的编译产物抽取出来，
打 4 处补丁（新增 google 协议 + 改内部名避免冲突）。

### ⚠️ 必须按「运行时那一份」打补丁

DSH 的 profile 插件**不是从 app.asar 解析依赖**的：`<profiles>/node_modules` 是一层
junction，指向安装时创建的依赖农场。因此存在两种版本可能不一致的情况：

| 来源 | 典型内容 |
| --- | --- |
| `app.asar` 内置（app 版本） | `dsh-llm-pi-ai@0.2.1-rc.2`、`pi-ai@1.1.0` |
| `<profiles>/node_modules` 农场（**插件实际解析到的**） | `dsh-llm-pi-ai@0.1.0-rc.6`、`pi-ai@0.82.1` |

如果照 asar 里的新版抽，补丁产物会 import 农场里不存在的包
（`@deepseek-ai/dsh-util-values`、`@earendil-works/pi-ai/utils/overflow`），
插件会**静默加载失败**——模型列表里什么都不会出现。

所以 `tools/build-plugin.py` 默认以 `<profiles>/node_modules/@deepseek-ai/dsh-llm-pi-ai`
为源（即运行时那一份），asar 仅作兜底。

改动 DSH 或重装插件后：

```powershell
python tools/build-plugin.py          # 重新抽取 + 打补丁
python tools/build-plugin.py --check  # 只检查是否需要刷新
python tools/build-plugin.py --source <某个官方 lib/index.js>
```

脚本会校验锚点唯一性；锚点位移会显式报错而不是静默产出坏包。

### 本地自检（推荐）

在 profile 目录下直接 import，确认能加载再推：

```powershell
cd $env:USERPROFILE\.dsh\profiles\desktop
node --input-type=module -e "import('./node_modules/dsh-llm-opencode/index.js').then(m=>console.log(m.supportedProtocols()))"
```

应输出包含 `google-generative-ai` 的四个协议。

## 刷新模型清单

```powershell
python tools/refresh-routes.py            # 探测并显示结果
python tools/refresh-routes.py --write    # 探测后重写 cordis.patch.yml
```

脚本按各自协议逐个请求上游，只保留真正返回 200 的模型，并自动带上
`input: [text, image]` 能力位（依据 `tools/modalities.json` 里实测的多模态表）。

## 已知限制

- **与 DSH 版本绑定**：升级 DSH 后需重跑 `tools/build-plugin.py`。
- **地区锁定的模型**（`gpt-5.6-luna`、`gpt-6-luna`）与 **Google 协议模型**
  （`gemini-4-argon-contributor`）不在默认路由里：前者需要代理，后者需要
  官方插件尚未暴露的协议（本插件的 `index.js` 已包含该协议，可在
  `cordis.patch.yml` 里自行加一条 `api: google-generative-ai` 的路由启用）。
- `x-opencode-session` 使用固定值（上游只要求该头存在）。

## 目录

| 文件 | 作用 |
| --- | --- |
| `index.js` | 插件本体（官方 `dsh-llm-pi-ai` + 5 处补丁） |
| `cordis.patch.yml` | bundle 补丁：插入插件行 + 内联路由配置 |
| `tools/build-plugin.py` | 从 DSH 安装包重新生成 `index.js` |
| `tools/refresh-routes.py` | 探测上游并重写路由 |
| `tools/modalities.json` | 实测的图片能力表 |
| `DESIGN.md` | 设计说明与取证记录 |

## 许可

MIT
