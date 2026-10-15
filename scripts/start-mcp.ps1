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

# 直接调用（不经过管道），uv 会继承本进程的输入输出，MCP 协议数据原样传递。
& $candidates[0] run --frozen --quiet --project $root xuanshang-canvas-mcp @args
exit $LASTEXITCODE
