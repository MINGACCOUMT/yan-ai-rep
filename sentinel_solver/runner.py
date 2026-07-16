"""sentinel-solver 浏览器 runner：跑真实官方 Sentinel sdk.js，产出 openai-sentinel-token / so-token。

工作原理（已用 HAR + 实测验证）：
  - 官方 SDK 挂在 sentinel.openai.com 的 iframe 里：
      https://sentinel.openai.com/backend-api/sentinel/frame.html?sv=<SDK_VERSION>
    该 frame 加载 .../sentinel/<SDK_VERSION>/sdk.js，暴露 window.SentinelSDK = {init, token, sessionObserverToken}。
  - 关键：以「顶层页面」加载 frame.html，可绕过 SDK 的 "should not be called from within an iframe" 守卫。
  - await SentinelSDK.token({id, flow})
      -> SDK 自己 POST /backend-api/sentinel/req，内部解 proofofwork(p) + turnstile(t)，
         返回完整 openai-sentinel-token 字符串 {"p","t","c","flow"}（t 非空，这正是修复核心）。
  - await SentinelSDK.sessionObserverToken({id, flow})  -> so-token（session observer）。
    ⚠️ 已知限制：在「隔离的 frame.html 顶层页」里，sessionObserverToken 目前恒返回 null
       （observer collector 很可能依赖真实 auth.openai.com 父页面上下文/行为信号）。
       因此 so-token 目前多半为空；sentinel-token 本身已含解好的 t，是协议修复的主体。
"""
from __future__ import annotations

import os
from typing import Any

from playwright.sync_api import sync_playwright

# 对齐的目标 SDK 版本（与 utils/sentinel.py 的 SENTINEL_SDK_VERSION 一致）。
SDK_VERSION = "20260219f9f6"
SENTINEL_FRAME_URL = f"https://sentinel.openai.com/backend-api/sentinel/frame.html?sv={SDK_VERSION}"
# 可选代理：sentinel.openai.com 会对某些出口 IP 直接 CF 硬封（"You have been blocked"），
# 这时浏览器加载不了 frame.html → 没有 SentinelSDK。走干净代理绕开。由环境变量配置。
SOLVER_PROXY = (os.environ.get("SENTINEL_SOLVER_PROXY") or "").strip()
DEFAULT_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/149.0.0.0 Safari/537.36"
)


def solve(
    device_id: str,
    flow: str,
    user_agent: str = "",
    sec_ch_ua: str = "",
    observer_wait_ms: int = 5000,
) -> dict[str, Any]:
    """启动无头浏览器加载 frame.html，调官方 SDK 生成 token，返回 {sentinel_token, so_token, oai_sc, sdk}。"""
    ua = user_agent or DEFAULT_UA
    extra_http_headers = {"sec-ch-ua": sec_ch_ua} if sec_ch_ua else None

    with sync_playwright() as p:
        launch_kwargs = {"headless": True}
        if SOLVER_PROXY:
            launch_kwargs["proxy"] = {"server": SOLVER_PROXY}
        browser = p.chromium.launch(**launch_kwargs)
        try:
            context = browser.new_context(user_agent=ua, extra_http_headers=extra_http_headers or None)
            context.add_cookies([{
                "name": "oai-did",
                "value": device_id,
                "domain": ".openai.com",
                "path": "/",
            }])
            page = context.new_page()
            result = _run_sdk(page, device_id, flow, observer_wait_ms)
        finally:
            browser.close()

    result["sdk"] = SDK_VERSION
    return result


def _run_sdk(page, device_id: str, flow: str, observer_wait_ms: int) -> dict[str, Any]:
    """加载 frame.html 并调官方 SDK。SEAM-1/2 已验证通过；so-token 见模块 docstring 的已知限制。"""
    page.goto(SENTINEL_FRAME_URL, wait_until="networkidle", timeout=30000)
    # networkidle 只保证网络空闲，不保证 sdk.js 已执行完；显式等 SentinelSDK 挂到 window 上，
    # 否则会 race 出 "SentinelSDK not ready"（app 拿到 500 就降级到进程内空 t 的 solver）。
    page.wait_for_function(
        "() => typeof window.SentinelSDK !== 'undefined' && window.SentinelSDK"
        " && typeof window.SentinelSDK.token === 'function'",
        timeout=15000,
    )

    # 全部在「同一次 evaluate」里完成，并把 cfg 钉到 window：
    # SDK 的会话存储 ne 是 Map、按「config 对象引用」做 key，token() 和 sessionObserverToken() 必须用同一对象。
    return page.evaluate(
        """
        async ({id, flow, waitMs}) => {
            const SDK = window.SentinelSDK;
            if (!SDK) throw new Error('SentinelSDK not ready on frame.html');
            const cfg = {id, flow};
            window.__sentinel_cfg = cfg;

            // 1) openai-sentinel-token：SDK 内部 fetch /sentinel/req 并解 PoW + turnstile
            const sentinel_token = await SDK.token(cfg);
            if (typeof sentinel_token !== 'string' || !sentinel_token) {
                throw new Error('SDK.token returned no string');
            }

            // 2) 给 session observer collector 留采集时间（官方前端约 5000ms）
            if (waitMs > 0) await new Promise(r => setTimeout(r, waitMs));

            // 3) so-token（sessionObserverToken）；隔离 frame 下可能为 null
            let so_token = '';
            try {
                const so = await SDK.sessionObserverToken(cfg);
                if (typeof so === 'string' && so) so_token = so;
            } catch (e) { /* so-token 非必需，忽略 */ }

            // 4) oai-sc cookie（SDK 写在 sentinel.openai.com，回带给 app 写进自己的 session）
            const m = document.cookie.match(/oai-sc=([^;]+)/);
            const oai_sc = m ? m[1] : '';

            return {sentinel_token, so_token, oai_sc};
        }
        """,
        {"id": device_id, "flow": flow, "waitMs": observer_wait_ms},
    )
