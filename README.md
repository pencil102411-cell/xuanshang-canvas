# 玄上画布插件（xuanshang-canvas）

让 Claude Code、Codex 等 AI 工具，用**同一套规则**操作你电脑上正在运行的「玄上无限画布」（也支持玄上内部版）：新建项目和认证分组、查项目、上传认证图片和参考视频、把素材放到画布上、建 Seedance 视频节点、提交生成、样片转成片、查进度。

- **不用每次启动**：在 AI 工具里装一次，以后打开 AI 工具就会在后台自动启动插件，插件再自己去找开着的画布。
- **不碰你的密钥**：插件不读取、不保存任何 API Key。所有请求都经过你本机的画布，用的是画布里登录的账号和积分。
- **只在你下指令时花积分**：提交生成、转成片只在你明确说要生成时才执行，不会自己主动提交。

---

## 一、安装：让 AI 帮你装

**准备**：Windows 电脑，装好并能正常打开「玄上无限画布」，在画布里登录自己的账号；装好 Claude Code 或 Codex。

把下面这段话**原样发给 Claude Code 或 Codex**，它会自己把插件装好：

> 请帮我安装玄上画布插件：按 https://github.com/pencil102411-cell/xuanshang-canvas 这个仓库 README 里「给 AI 的安装步骤」操作，装完运行自检，把结果告诉我。

安装过程中 AI 可能会请你批准运行命令，点允许就行。装好以后：

- **Claude Code**：新开一个会话；
- **Codex**：重启 Codex。

然后说一句「**用 canvas_status 看看画布连上了没有**」，看到「已连接」和画布名字，就装好了。

---

## 二、给 AI 的安装步骤

> 这一节是写给 AI 看的，使用者不用自己操作。所有命令都在普通权限的 PowerShell 里运行。插件仓库：https://github.com/pencil102411-cell/xuanshang-canvas

### 第 1 步：确认电脑上有 uv

插件靠 uv（Python 环境管理工具）运行。先检查：

```powershell
@((Get-Command uv.exe -ErrorAction SilentlyContinue).Source, "$env:USERPROFILE\.local\bin\uv.exe", "$env:LOCALAPPDATA\Microsoft\WinGet\Links\uv.exe") | Where-Object { $_ -and (Test-Path $_) }
```

什么都没输出就是没装，运行 `winget install --id=astral-sh.uv -e` 安装；winget 不可用时改用 `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`。装完不用重启：插件的启动脚本会自己去这些位置找 uv。

### 第 2 步（Claude Code）：用插件市场安装

```powershell
claude plugin marketplace add https://github.com/pencil102411-cell/xuanshang-canvas
claude plugin install xuanshang-canvas@xuanshang-tools
```

然后运行自检，顺便把依赖提前装到插件的数据目录（第一次要一两分钟）：

```powershell
$root = (Get-ChildItem "$env:USERPROFILE\.claude\plugins\cache\xuanshang-tools\xuanshang-canvas" -Directory | Sort-Object LastWriteTime -Descending | Select-Object -First 1).FullName
$env:UV_PROJECT_ENVIRONMENT = "$env:USERPROFILE\.claude\plugins\data\xuanshang-canvas-xuanshang-tools\venv"
powershell -NoProfile -ExecutionPolicy Bypass -File "$root\scripts\start-mcp.ps1" --check
```

画布开着时会显示「已连接」；画布没开会提示先打开画布，这也说明插件本身装好了。最后告诉用户新开一个会话。插件自带规则说明（技能 `xuanshang-canvas`），不用另外放规则文件。

可选：用户同意的话，把 `adapters/claude-code/permissions.json` 里 `plugin` 那组的 `permissions` 合并到 `~/.claude/settings.json`（所有插件工具直接放行，不再逐个弹出批准）。

### 第 2 步（Codex）：下载插件文件夹并登记

1. 下载插件到 `%USERPROFILE%\xuanshang-canvas`（不需要 git）。升级时先删掉旧文件夹：

   ```powershell
   $zip = "$env:TEMP\xuanshang-canvas.zip"; $tmp = "$env:TEMP\xuanshang-canvas-unzip"
   Invoke-WebRequest https://github.com/pencil102411-cell/xuanshang-canvas/archive/refs/heads/main.zip -OutFile $zip
   Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue; Expand-Archive $zip $tmp
   Move-Item "$tmp\xuanshang-canvas-main" "$env:USERPROFILE\xuanshang-canvas"
   ```

2. 自检并提前装好依赖：

   ```powershell
   powershell -NoProfile -ExecutionPolicy Bypass -File "$env:USERPROFILE\xuanshang-canvas\scripts\start-mcp.ps1" --check
   ```

3. 把 `adapters/codex/config.toml` 的内容加到 `%USERPROFILE%\.codex\config.toml` 末尾，把里面的 `C:/Users/你的用户名/xuanshang-canvas` 换成实际路径（用正斜杠）。已经有 `[mcp_servers.xuanshang-canvas]` 这一段时，替换掉旧的。这段配置把等待时间调长了（Codex 默认启动只等 10 秒、每次调用只等 60 秒，不够用）。旧版配置里如果有 `[mcp_servers.xuanshang-canvas.tools.submit_generation]`、`[mcp_servers.xuanshang-canvas.tools.create_final_video]` 这两小段，一起删掉。
4. 把 `adapters/codex/skills/xuanshang-canvas` 整个文件夹复制到 `%USERPROFILE%\.agents\skills\`（没有就新建）。这是给 Codex 的规则说明。
5. 告诉用户重启 Codex。

### 第 2 步（其他 MCP 工具：Cursor、Claude Desktop、Gemini CLI、VS Code 等）

按 Codex 的第 1、2 步下载并自检，再照 `adapters/generic/` 里的示例添加配置（VS Code 用 `vscode-mcp.json`，其他用 `mcp.json`），把路径换成实际位置。这些工具没有专门的规则文件，规则主要靠插件代码强制执行和工具说明。

---

## 三、日常怎么用

直接用中文跟 AI 说要做什么，例如：

- 「新建一个项目，叫『第09集-场12』」
- 「在第09集-场12 这个项目里建三个认证分组：人物、场景、参考视频」
- 「看看 16-20 测试这个项目里有哪些视频节点」
- 「把 D:\素材\司徒陌-面部.png 传到 16-20 测试项目的人物分组，认证完放到画布上」
- 「把 D:\预演\镜127.mp4 作为参考视频上传认证，放到画布上」
- 「新建一个视频节点，叫『镜127』，接司徒陌两张图和刚才的参考视频，提示词是……」
- 「提交镜127」（直接提交，会花积分）
- 「镜127 的样片好了没有？」「把这个样片转成片」

AI 会按插件的规则来做，做完会告诉你结果、核对情况和需要注意的地方。

---

## 四、插件会替你守住的规则（摘要）

完整规则见 [rules/RULES.md](rules/RULES.md)，这里说最常碰到的几条：

| 规则 | 说明 |
|---|---|
| 只加不改不删 | 只新增节点和连线；要改就新建一个，重名自动加 -v2、-v3，旧的保留 |
| 引用写法跟画布一致 | 统一写成半角 `(图片1)`、`(视频1)`，和画布界面保存后的样子一样；`@图片1`、全角 `（图片1）` 会自动转过来 |
| 引用和素材对得上 | 编号不能超过接入的素材数，接入的每个素材都要被引用，否则拒绝创建 |
| 原质量上传 | 超过 6000px 的图会被画布压缩，先问你；上传后核对大小和尺寸 |
| 参考视频要认证 | 本地参考视频先上传认证；画布上已经生成好的视频可以直接当参考 |
| 只在你下指令时花积分 | 提交生成、转成片只在你明确要求时执行；同一节点已有任务在跑时拒绝，避免重复扣积分 |
| 提交后不盯进度 | 你问进度时才去查 |

---

## 五、配置项（可选）

不配置也能用。要改默认参数，新建 `C:\Users\你的用户名\AppData\Roaming\xuanshang-canvas\config.json`，只写要改的项：

```json
{
  "video_defaults": {
    "model": "Doubao-Seedance-2.5",
    "seedanceMode": "multimodal",
    "resolution": "draft",
    "ratio": "21:9",
    "seed": 1,
    "outputFormat": "mp4",
    "webSearch": false,
    "duration": 5
  },
  "certify_wait_seconds": 50,
  "size_tolerance": 0.05
}
```

| 配置项 | 意思 | 默认 |
|---|---|---|
| `video_defaults` | 新建视频节点时没指定的参数用这些 | 见上 |
| `canvas_port` | 写死画布端口（一般不用，插件会自己找） | 不写 |
| `certify_wait_seconds` | 上传后最多等认证多少秒 | 50 |
| `size_tolerance` | 上传后大小差多少以内只提示不报错 | 0.05（5%） |

也可以用环境变量：`CANVAS_PORT`、`XUANSHANG_CERTIFY_WAIT_SECONDS`；配置文件位置可用 `XUANSHANG_CANVAS_CONFIG` 指定。

> 等待时间要比 AI 工具自己的等待上限短。Codex 按上面的配置是 300 秒；如果你把 Codex 的 `tool_timeout_sec` 调得更长，这里也可以跟着调长。

---

## 六、常见问题

**提示「请先打开玄上无限画布」**：画布没开，或者刚开还没启动完。打开画布、等界面出来后再试。

**提示「同时开着 2 个画布」**：比如无限画布和内部版都开着。告诉 AI 用哪个，它会带上端口号选定；只开一个就不会问。

**上传后说「认证中」**：玄上那边认证慢，插件最多等 50 秒就先返回。过一会儿让 AI 用 `list_certified_groups` 查，变成「已认证」后再放到画布上。

**结果里写着「公共图床」**：玄上存储上传失败时，画布会自动改传到公共图床，文件会在公网上。是否继续用这个素材由你决定。

**参考视频上传或生成时报错**：Seedance 对参考视频有格式、时长、大小、分辨率限制，具体数值还没查清。插件会把画布的原始报错原样给你，照着报错改视频即可。

**提示「画布版本和插件不兼容」**：画布升级后内部接口变了。把报错发给插件维护者。

**Claude Code / Codex 说插件启动失败（比如 Connection closed）**：跟 AI 说「按玄上画布插件 README 里给 AI 的安装步骤，重新检查 uv 并运行自检」。自检会把依赖装好并显示具体报错。第一次启动要下载依赖，网络慢时可能超时，自检通过后再新开会话试一次。

---

## 七、已验证的画布版本

| 程序 | 构建号 | 状态 |
|---|---|---|
| 玄上内部版 | 20260923203739 | 已实测：读取、建项目、上传认证、放节点、建视频节点 |
| 玄上无限画布 | 20260923203516 | 和内部版同一套接口，待实测 |

`canvas_status` 会显示当前画布的构建号和是否实测过。

---

## 八、给维护者

```
xuanshang-canvas/
├── .claude-plugin/          # Claude Code 插件清单和插件市场清单（仓库根目录就是插件）
├── .mcp.json                # Claude Code 插件启动 MCP 服务的配置
├── skills/xuanshang-canvas/ # Claude Code 规则文件（自动生成）
├── src/xuanshang_canvas/
│   ├── core/                # 核心库：连接画布 + 统一规则，所有写入都经过这里
│   └── mcp_server/          # MCP 服务（所有 AI 工具共用）
├── rules/RULES.md           # 规则源文件（唯一来源）
├── docs/api-notes.md        # 画布内部接口记录
├── adapters/
│   ├── claude-code/         # 权限建议
│   ├── codex/               # config.toml 片段、规则文件（自动生成）
│   └── generic/             # 其他 MCP 工具的配置示例
├── scripts/                 # start-mcp.ps1 启动插件；build_adapters.py 生成规则文件
├── pyproject.toml           # 直接依赖，固定版本
└── uv.lock                  # 全部间接依赖的固定版本
```

- 改规则只改 `rules/RULES.md`，然后运行 `python scripts/build_adapters.py` 重新生成各家的规则文件；`--check` 只检查是否一致。MCP 服务的使用说明直接读 `RULES.md`。
- 所有 AI 工具都通过 `scripts/start-mcp.ps1` 启动插件。它自己去 uv 的常见安装位置找 uv，再运行 `uv run --frozen --quiet --project <插件目录> xuanshang-canvas-mcp`。不直接写 `uv`，是因为 Windows 上刚装好 uv 时，已经开着的程序（包括 Claude 应用）看不到新的 PATH，会报 Connection closed。
- 为什么 Claude Code 插件放在仓库根目录而不是 `adapters/claude-code/`：启动脚本要从插件自己的文件夹运行，插件目录里必须有 Python 源码。依赖装在 `${CLAUDE_PLUGIN_DATA}/venv`，插件更新时保留。
- 为什么用 `uv run --frozen --project` 而不是 `uvx --from`：在开着 Windows Defender 的电脑上实测，uvx 在临时目录里装依赖时会被 Defender 锁住 pywin32 的文件而失败（`os error 32`）；装到固定目录（`uv run`、`uv tool install`）没有这个问题。`--frozen` 按 `uv.lock` 装，所有间接依赖的版本也是固定的。
- `start-mcp.ps1` 要保存成带 BOM 的 UTF-8，否则 Windows PowerShell 5.1 读中文会乱码。
- 依赖升级：改 `pyproject.toml` 后运行 `uv lock`，测完再发布。
- 本地调试：`powershell -NoProfile -ExecutionPolicy Bypass -File scripts\start-mcp.ps1 --check`；或在 Claude Code 里 `claude --plugin-dir .` 临时加载。
- 发新版：改 `.claude-plugin/plugin.json`、`pyproject.toml`、`src/xuanshang_canvas/__init__.py` 里的版本号，运行 `uv lock`，推到 GitHub。已安装的用户运行 `claude plugin marketplace update xuanshang-tools` 再 `claude plugin update xuanshang-canvas@xuanshang-tools`。
- 画布接口细节见 `docs/api-notes.md`。画布升级后先跑 `canvas_status` 看兼容性检查。
