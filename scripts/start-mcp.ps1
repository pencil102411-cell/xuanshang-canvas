# 启动玄上画布插件的 MCP 服务（Claude Code、Codex 等都通过它启动）。
# 自己去 uv 的常见安装位置找，不依赖 PATH：Windows 上刚装好 uv 时，已经开着的程序看不到新的 PATH。
# 用法：powershell -NoProfile -ExecutionPolicy Bypass -File <插件文件夹>\scripts\start-mcp.ps1 [--check]

$root = Split-Path -Parent $PSScriptRoot
$found = Get-Command uv.exe -ErrorAction SilentlyContinue
$candidates = @(@(
    $(if ($found) { $found.Source }),
    (Join-Path $env:USERPROFILE '.local\bin\uv.exe'),
    (Join-Path $env:LOCALAPPDATA 'Microsoft\WinGet\Links\uv.exe'),
    (Join-Path $env:USERPROFILE '.cargo\bin\uv.exe'),
    (Join-Path $env:LOCALAPPDATA 'Programs\uv\uv.exe')
) | Where-Object { $_ -and (Test-Path -LiteralPath $_) })

if (-not $candidates) {
    [Console]::Error.WriteLine('没找到 uv。请先安装：在 PowerShell 里运行 winget install --id=astral-sh.uv -e ，装好后重新打开 AI 工具。')
    exit 1
}

# 依赖目录按版本分开（Claude Code 通过 UV_PROJECT_ENVIRONMENT 指定基础位置）。
# 原因：升级插件时，旧版本的会话可能还开着、占用着旧依赖目录里的文件，新版本如果用同一个目录就更新不了。
$base = $env:UV_PROJECT_ENVIRONMENT
if ($base) {
    $version = 'dev'
    $match = Select-String -LiteralPath (Join-Path $root 'pyproject.toml') -Pattern '^version\s*=\s*"([^"]+)"' -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($match) { $version = $match.Matches[0].Groups[1].Value }
    $current = "$base-$version"
    $env:UV_PROJECT_ENVIRONMENT = $current

    # 清理旧版本的依赖目录：先改名试探，改名成功说明没有程序在用，再删除；正在用的跳过，下次再清。
    $parent = Split-Path -Parent $base
    $leaf = Split-Path -Leaf $base
    if (Test-Path -LiteralPath $parent) {
        Get-ChildItem -LiteralPath $parent -Directory -ErrorAction SilentlyContinue |
            Where-Object { ($_.Name -eq $leaf -or $_.Name -like "$leaf-*") -and $_.FullName -ne $current } |
            ForEach-Object {
                $trash = "$($_.FullName).delete-$PID"
                try {
                    Rename-Item -LiteralPath $_.FullName -NewName (Split-Path -Leaf $trash) -ErrorAction Stop
                    Remove-Item -LiteralPath $trash -Recurse -Force -ErrorAction SilentlyContinue
                } catch { }
            }
    }
}

# 用 python -m 启动（而不是 venv 里的 xuanshang-canvas-mcp.exe），运行中的会话不会锁住需要更新的程序文件。
# 直接调用（不经过管道），uv 会继承本进程的输入输出，MCP 协议数据原样传递。
& $candidates[0] run --frozen --quiet --project $root python -m xuanshang_canvas.mcp_server.server @args
exit $LASTEXITCODE
