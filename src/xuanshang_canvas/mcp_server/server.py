"""玄上画布插件的 MCP 服务。

这一层只负责把核心库包装成工具、处理确认弹窗；规则都在 core 里执行。
"""

import logging
import re
import sys
from importlib import resources
from pathlib import Path
from typing import Annotated, Any, Callable

import anyio
import anyio.to_thread
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import ToolAnnotations
from pydantic import BaseModel, Field

from .. import __version__
from ..core.confirm import ConfirmRequest, show_popup
from ..core.errors import CanvasError
from ..core.service import CanvasService, Plan

WORKFLOW = """\
这是「玄上无限画布」插件，用来操作用户电脑上正在运行的画布。所有请求都经过用户本机的画布，用的是画布里登录的账号和积分。

必须遵守下面的规则（大部分由插件代码强制执行，违反时工具会拒绝并说明原因）：
"""


def _load_rules() -> str:
    try:
        text = resources.files("xuanshang_canvas").joinpath("RULES.md").read_text(encoding="utf-8")
    except (FileNotFoundError, ModuleNotFoundError, OSError):
        # 开发时直接从源码目录运行：规则源文件在仓库根目录 rules/RULES.md
        source = Path(__file__).resolve().parents[3] / "rules" / "RULES.md"
        text = source.read_text(encoding="utf-8") if source.exists() else ""
    return re.sub(r"<!--.*?-->\n?", "", text, flags=re.S)


service = CanvasService()
mcp = MCPServer(
    name="xuanshang-canvas",
    title="玄上画布插件",
    version=__version__,
    instructions=WORKFLOW + _load_rules(),
)

READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False)
WRITE = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=True)
# 花积分的操作花出去就收不回来，标成 destructive，让客户端默认每次都问用户。
SPEND = ToolAnnotations(read_only_hint=False, destructive_hint=True, idempotent_hint=False, open_world_hint=True)

ProjectArg = Annotated[str, Field(description="项目名称或项目 ID（用 list_projects 查）")]
ConfirmCodeArg = Annotated[
    str | None,
    Field(description="两步确认码。只有上一次调用返回了确认码、并且用户已经明确同意时才填；平时不要填"),
]


def _fail(exc: Exception) -> ToolError:
    if isinstance(exc, CanvasError):
        return ToolError(exc.message)
    return ToolError(f"插件内部出错（{type(exc).__name__}）：{exc}。请把这段信息告诉插件维护者。")


def _safe(fn: Callable[[], Any]) -> Any:
    try:
        return fn()
    except ToolError:
        raise
    except Exception as exc:  # noqa: BLE001 —— 统一转成给用户看的错误
        raise _fail(exc) from exc


async def _thread(fn: Callable[[], Any]) -> Any:
    try:
        return await anyio.to_thread.run_sync(fn)
    except ToolError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise _fail(exc) from exc


class _ConfirmForm(BaseModel):
    confirm: bool = Field(default=False, title="确认执行", description="勾选并提交表示确认；不勾或关闭表示取消")


def _supports_elicitation(ctx: Context | None) -> bool:
    try:
        caps = ctx.client_capabilities if ctx is not None else None
    except Exception:  # noqa: BLE001
        return False
    return caps is not None and getattr(caps, "elicitation", None) is not None


async def _confirm(ctx: Context | None, request: ConfirmRequest, code: str | None) -> dict[str, Any]:
    """规则 8：返回 {"status": confirmed / cancelled / pending, ...}。"""
    settings = service.settings
    mode = settings.confirm_mode
    timeout = settings.popup_timeout_seconds
    if code:
        await _thread(lambda: service.codes.redeem(request, code))
        return {"status": "confirmed", "method": "两步确认码（软限制）"}

    if mode in ("auto", "elicitation"):
        if _supports_elicitation(ctx):
            try:
                with anyio.fail_after(timeout):
                    answer = await ctx.elicit(f"{request.title}\n\n{request.sheet}", _ConfirmForm)
            except TimeoutError:
                return {"status": "cancelled", "reason": f"{timeout:.0f} 秒内没有确认，已按取消处理"}
            except Exception:  # noqa: BLE001 —— 客户端声称支持但实际弹不出来，退到下一档
                answer = None
            if answer is not None:
                if answer.action == "accept" and answer.data.confirm:
                    return {"status": "confirmed", "method": "AI 工具确认框"}
                return {"status": "cancelled", "reason": "用户在确认框里没有确认"}
        if mode == "elicitation":
            raise ToolError("配置要求只用 AI 工具确认框，但当前客户端不支持（或弹不出来）。请改配置 confirm_mode。")

    if mode in ("auto", "popup"):
        result = await anyio.to_thread.run_sync(lambda: show_popup(request.title, request.sheet, timeout))
        if result == "yes":
            return {"status": "confirmed", "method": "Windows 确认窗口"}
        if result == "no":
            return {"status": "cancelled", "reason": "用户在确认窗口点了「否」"}
        if result == "timeout":
            return {"status": "cancelled", "reason": f"确认窗口 {timeout:.0f} 秒内没人点，已按取消处理"}
        if mode == "popup":
            raise ToolError("配置要求只用 Windows 确认窗口，但当前环境弹不出窗口。请改配置 confirm_mode。")

    issued = service.codes.issue(request)
    return {"status": "pending", "code": issued}


async def _confirm_and_run(ctx: Context | None, plan: Plan, code: str | None) -> dict[str, Any]:
    if plan.request is None:
        return await _thread(plan.run)
    outcome = await _confirm(ctx, plan.request, code)
    if outcome["status"] == "confirmed":
        result = await _thread(plan.run)
        result["确认方式"] = outcome["method"]
        return result
    if outcome["status"] == "cancelled":
        return {"状态": "已取消，没有执行", "原因": outcome["reason"], "提醒": "不要换个方式重试，直接告诉用户已取消。"}
    return {
        "状态": "等待用户确认（还没有执行）",
        "确认单": plan.request.sheet,
        "确认码": outcome["code"],
        "下一步": "把上面的确认单原样给用户看。用户明确同意后，用同样的参数再调用一次，并带上 confirm_code。确认码 5 分钟内有效，只能用一次。",
        "提醒": "这是软限制：确认码在你手里，必须先问用户，绝对不能直接用。",
    }


# ---------------------------------------------------------------------- 只读工具


@mcp.tool(annotations=READ_ONLY)
def canvas_status(
    port: Annotated[int | None, Field(description="同时开着多个画布时，用它选定要用的那个（端口号见上次返回的「可选画布」）")] = None,
) -> dict[str, Any]:
    """查看画布是否在运行、是哪个程序（无限画布/内部版）、端口、版本是否兼容、项目数量。开始操作前先调一次。"""
    return _safe(lambda: service.status(port))


@mcp.tool(annotations=READ_ONLY)
def list_projects() -> dict[str, Any]:
    """列出画布里的项目（名称、ID、节点数）。"""
    return _safe(lambda: {"项目": service.list_projects()})


@mcp.tool(annotations=READ_ONLY)
def get_graph_summary(project: ProjectArg) -> dict[str, Any]:
    """项目节点摘要：每个视频节点的名字、参数、按顺序列出的接入素材（图片1、视频1……）、最近任务状态、
    是否已有生成好的视频（可以当参考）；以及认证图片节点、认证视频节点的名字和 ID。"""
    return _safe(lambda: service.graph_summary(project))


@mcp.tool(annotations=READ_ONLY)
def list_certified_groups(project: ProjectArg) -> dict[str, Any]:
    """项目的认证分组，以及组内每个素材（图片、视频）的认证状态（向玄上实时查）、是否已经放到画布上。"""
    return _safe(lambda: service.certified_groups(project))


@mcp.tool(annotations=READ_ONLY)
def get_task(
    project: ProjectArg,
    task_id: Annotated[str | None, Field(description="任务 ID")] = None,
    node: Annotated[str | None, Field(description="节点名或节点 ID；给了就查这个节点最近一次任务")] = None,
) -> dict[str, Any]:
    """查某个任务，或某个节点最近一次任务的状态、进度和输出文件。只在用户问进度时调用，不要反复轮询。"""
    return _safe(lambda: service.get_task(project, task_id, node))


# ---------------------------------------------------------------------- 写入工具


@mcp.tool(annotations=WRITE)
async def upload_certified_image(
    project: ProjectArg,
    file_path: Annotated[str, Field(description="本地图片的完整路径，如 C:\\素材\\司徒陌-面部.png")],
    group: Annotated[str, Field(description="认证分组名或分组 ID（用 list_certified_groups 查）")],
    ctx: Context,
    display_name: Annotated[str | None, Field(description="放到画布上时显示的名字，不填就用原文件名")] = None,
    confirm_code: ConfirmCodeArg = None,
) -> dict[str, Any]:
    """本地图片按原质量上传并认证（JPG/PNG/WEBP/BMP/GIF）。返回素材 ID、存储去向、上传核对结果、认证状态。
    长边超过 6000px 的图会被画布压缩，插件会先请用户确认。上传后要再用 add_certified_asset_node 放到画布上。"""
    plan = await _thread(lambda: service.plan_upload(project, file_path, group, display_name, "image"))
    return await _confirm_and_run(ctx, plan, confirm_code)


@mcp.tool(annotations=WRITE)
async def upload_certified_video(
    project: ProjectArg,
    file_path: Annotated[str, Field(description="本地参考视频的完整路径（MP4 或 MOV），如 D:\\预演\\16-20-镜127.mp4")],
    group: Annotated[str, Field(description="认证分组名或分组 ID（用 list_certified_groups 查）")],
    display_name: Annotated[str | None, Field(description="放到画布上时显示的名字，不填就用原文件名")] = None,
) -> dict[str, Any]:
    """本地参考视频按原文件上传并认证（不转码、不剪辑）。返回素材 ID、存储去向、大小核对结果、认证状态。
    本地参考视频必须先认证才能接到视频节点上；画布上已生成的视频不用这一步。认证完再用 add_certified_asset_node 放到画布上。"""
    return await _thread(lambda: service.plan_upload(project, file_path, group, display_name, "video").run())


@mcp.tool(annotations=WRITE)
def add_certified_asset_node(
    project: ProjectArg,
    asset_ids: Annotated[list[str], Field(description="要放到画布上的认证素材 ID 列表（图片、视频都行）")],
    display_names: Annotated[
        list[str] | None, Field(description="和 asset_ids 一一对应的显示名；不填就用上传时记下的原始中文名")
    ] = None,
    allow_duplicate: Annotated[bool, Field(description="画布上已经有这个素材的节点时，是否还要再放一个")] = False,
) -> dict[str, Any]:
    """把已认证的素材（图片或视频）放到画布上，自动找空位，排成一列。只接受「已认证」的素材。"""
    return _safe(lambda: service.add_certified_nodes(project, asset_ids, display_names, allow_duplicate))


@mcp.tool(annotations=WRITE)
def create_video_node(
    project: ProjectArg,
    name: Annotated[str, Field(description="节点名字；和已有视频节点重名时自动加 -v2、-v3")],
    prompt: Annotated[str, Field(description="提示词。用 (图片N)、(视频N) 引用素材（半角括号，和画布一致）；@图片N、全角（图片N）会自动转成半角")],
    image_nodes: Annotated[
        list[str] | None, Field(description="按顺序排列的图片节点（节点名或 ID），第一个就是 (图片1)")
    ] = None,
    video_nodes: Annotated[
        list[str] | None,
        Field(description="按顺序排列的视频节点（节点名或 ID），第一个就是 (视频1)。可以是认证过的参考视频，也可以是画布上已生成的视频"),
    ] = None,
    duration: Annotated[int | None, Field(description="时长（秒）。Seedance 2.5 可选 4–30，-1 表示自动；不填用默认 5")] = None,
    ratio: Annotated[str | None, Field(description="画面比例：adaptive、21:9、16:9、4:3、1:1、3:4、9:16；不填用默认 21:9")] = None,
    resolution: Annotated[str | None, Field(description="draft（样片）、480p、720p、1080p；不填用默认 draft")] = None,
    seed: Annotated[int | None, Field(description="随机种子，-1 表示随机；不填用默认 1")] = None,
    model: Annotated[str | None, Field(description="不填用默认 Doubao-Seedance-2.5")] = None,
    seedance_mode: Annotated[
        str | None, Field(description="multimodal（多模态参考，默认）、first-frame、first-last-frame、video-edit、video-extend")
    ] = None,
    output_format: Annotated[str | None, Field(description="mp4（默认）或 mov")] = None,
    web_search: Annotated[bool | None, Field(description="是否开联网搜索，默认关")] = None,
) -> dict[str, Any]:
    """新建 Seedance 视频生成节点并连好素材。会检查：引用格式（自动统一成画布的 (图片N) 写法）、引用编号和接入素材是否对得上、
    素材是否已认证/已生成、参数是否合规；建完马上读回核对。不会提交生成。"""
    overrides = {
        "duration": duration,
        "ratio": ratio,
        "resolution": resolution,
        "seed": seed,
        "model": model,
        "seedanceMode": seedance_mode,
        "outputFormat": output_format,
        "webSearch": web_search,
    }
    return _safe(lambda: service.create_video_node(project, name, prompt, image_nodes, video_nodes, overrides))


@mcp.tool(annotations=SPEND)
async def submit_generation(
    project: ProjectArg,
    node: Annotated[str, Field(description="要提交的视频节点（节点名或 ID）")],
    ctx: Context,
    confirm_code: ConfirmCodeArg = None,
) -> dict[str, Any]:
    """提交生成任务（花积分）。每次都要用户单独确认：插件会弹确认框/确认窗口，用户点确认才提交。
    同一节点已有任务在跑时直接拒绝。提交后只返回任务 ID，不会自动盯进度。"""
    plan = await _thread(lambda: service.plan_submit(project, node))
    return await _confirm_and_run(ctx, plan, confirm_code)


@mcp.tool(annotations=SPEND)
async def create_final_video(
    project: ProjectArg,
    ctx: Context,
    task_id: Annotated[str | None, Field(description="样片任务 ID")] = None,
    node: Annotated[str | None, Field(description="视频节点名或 ID；给了就用这个节点最近一次成功的样片")] = None,
    confirm_code: ConfirmCodeArg = None,
) -> dict[str, Any]:
    """把 Seedance 2.5 样片转成 1080p 成片（花积分），每次都要用户单独确认。画布会在样片节点旁边新建「成片生成」节点。"""
    plan = await _thread(lambda: service.plan_final_video(project, task_id, node))
    return await _confirm_and_run(ctx, plan, confirm_code)


def main() -> None:
    # 每个 HTTP 请求都打一行日志太吵，只留警告和错误。
    for name in ("httpx2", "httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)
    if sys.platform == "win32":
        # 让报错信息里的中文在 Windows 控制台不乱码（stdout 是 MCP 协议通道，只改 stderr）。
        try:
            sys.stderr.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    if "--check" in sys.argv[1:]:
        # 装完自检：不启动 MCP 服务，只连一次画布、打印结果。顺便把依赖提前装好。
        import json

        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
        result = service.status()
        print(f"玄上画布插件 {__version__} 已就绪。")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        sys.exit(0 if result.get("已连接") else 1)
    mcp.run("stdio")


if __name__ == "__main__":
    main()
