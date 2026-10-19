# dsh-llm-opencode 设计说明

> 2026-10-15 定稿。目标：**用 DSH 插件替代本地 Python 网关**，让 OpenCode Go 的四种协议
> 由 pi-ai 原生实现，不再依赖常驻进程、端口、watchdog 与崩溃自愈。

## 1. 为什么可行（取证结论）

| 事实 | 出处 |
| --- | --- |
| DSH 插件声明协议的 `PROTOCOLS` 表只有 3 项，注释写明"每种协议就是一行，只是没人需要" | `dsh-llm-pi-ai/lib/index.js:802` |
| pi-ai 已实现 Google 协议（含懒加载入口 `googleGenerativeAIApi`） | `pi-ai/dist/api/google-generative-ai.lazy.js` |
| `@google/genai@2.21.0` 已随应用发布（pi-ai 的依赖） | `dsh/node_modules/@google/genai/` |
| pi-ai 的 Google 实现用 `model.baseUrl` + `apiVersion=""`，正好拼出 `…/go/v1/models/{id}:streamGenerateContent?alt=sse` | `pi-ai/dist/api/google-generative-ai.js:269` |
| SDK 默认发 `x-goog-api-key`，OpenCode 接受（实测 200；`?key=` 查询参数 401） | 2026-10-15 直连探测 |
| 四条协议的实现都会带上 route 级 `model.headers` | `anthropic:741`、`openai-responses:176`、`openai-completions:532`、`google:275` |

## 2. 组件

### 2.1 插件包（`dsh-llm-opencode/`）

由 `build_plugin.py` 从 `app.asar` 抽取官方插件并打 5 处补丁：

1. 引入 `googleGenerativeAIApi`；
2. `PROTOCOLS` 增加 `"google-generative-ai"`；
3. `LISTABLE_PROTOCOLS` 增加同项（该路由因此支持"获取可用模型"）；
4. 插件内部名 `llm-pi-ai` → `llm-opencode`（避免与官方插件同名冲突）；
5. 设置命名空间 `NS` 同步改名。

产物：`index.js` + `package.json`（含 `dsh.bundle.patch`）+ `cordis.patch.yml`。
**不声明** `@deepseek-ai/*`、`@earendil-works/pi-ai` 依赖 —— 按官方约定由 dsh 安装目录解析，
避免与宿主产生第二份服务实例。

DSH 升级后用 `refresh-plugin.ps1`（内部调用 `build_plugin.py`）一条命令重新打补丁；
`-Check` 只报告当前包是否与最新补丁一致。

### 2.2 四条直连路由（一协议一路由）

由 `gen_opencode_routes.py` 生成，数据全部来自实测产物：

- 协议归属：`routes.json`（网关跑出来的实测映射，仅取 `upstream == "go"`）
- 图片能力：`model-modalities.json`（紫色方块 + 蓝圆两轮探测，24 个模型带 `input: [text, image]`）
- 展示名：沿用 profile patch 里 `opencode-live` 段的名称

| 路由 | api | 模型数 |
| --- | --- | --- |
| `oc-resp` | `openai-responses` | 11 |
| `oc-chat` | `openai-completions` | 22 |
| `oc-msg` | `anthropic-messages` | 7 |
| `oc-google` | `google-generative-ai` | 1 |

公共项：`baseURL=https://opencode.ai/inference/go/v1`、`apiKeyEnv=OPENCODE_GO_API_KEY`、
`headers: {x-opencode-session: <稳定值>, user-agent: dsh-opencode/1.0}`。

### 2.3 代理

DSH 自带 `@deepseek-ai/dsh-http-proxy`：launcher 读环境变量（`https_proxy` / `HTTPS_PROXY` /
`ALL_PROXY`），在第一个插件加载前装好 undici 全局 dispatcher；pi-ai provider 栈与标准 `fetch`
都会走它。**不读 Windows 系统代理设置**，且作用域是**整个进程**；本地回环永远直连。

因此地区锁定的 `gpt-5.6-luna` / `gpt-6-luna` 走 `C:\Users\Young\.dsh\.env` 里的
`HTTPS_PROXY=http://127.0.0.1:7899`。删除该行即可回退（此后这两个模型改由网关路由承担）。

## 3. 迁移与回滚

1. 生成插件包（`build_plugin.py`，已完成）；
2. 在 DSH 插件页安装 bundle（目标目录 = `dsh-llm-opencode` 绝对路径）；
3. `python gen_opencode_routes.py --apply` 写入 profile 路由；
4. 重启 DSH；
5. 逐协议验证（含图片与工具调用）；
6. 验证通过后再停用 `opencodex-gateway-watchdog` 计划任务。

回滚：`python gen_opencode_routes.py --remove`，插件页卸载 bundle，恢复
`cordis.patch.yml.bak-*`；网关脚本与配置均未删除，重启即回到 2026-10-15 的状态。

## 4. 已知风险

- **fork 与 DSH 版本绑定**：升级需重跑 `refresh-plugin.ps1`（脚本带锚点校验，锚点位移会显式报错）。
- **安装需人工**：当前会话没有 `plugin_manager` 工具，安装/卸载要在 DSH 插件页完成。
- **静态 session 头**：上游只要求该头存在；"一会话一头"属二期（可参考社区插件
  `dsh-x-opencode-session`）。
- **代理是全局的**：mihomo 挂掉则所有 DSH 出网受影响；`.env` 一行即可回退。
- **端到端验证受限**：我无法驱动 DSH UI，插件层只能验证到"包可加载、配置可组合"，
  真正的对话验证需要你在界面上选一次模型。
