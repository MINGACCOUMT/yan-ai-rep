"""sentinel-solver HTTP 服务。

契约（与 utils/sentinel.py 的 _solve_via_runtime 对齐）：
    POST /solve
      请求:  {"device_id","flow","user_agent","sec_ch_ua","observer_wait_ms"}
      响应:  {"sentinel_token","so_token","oai_sc","sdk"}
    GET /health -> {"ok": true}

未填 seam（_run_sdk 抛 NotImplementedError）时返回 501，方便 app 侧感知并降级。
"""
from __future__ import annotations

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from runner import solve

app = FastAPI(title="sentinel-solver")


class SolveRequest(BaseModel):
    device_id: str
    flow: str
    user_agent: str = ""
    sec_ch_ua: str = ""
    observer_wait_ms: int = Field(default=5000, ge=0, le=60000)


@app.get("/health")
def health() -> dict:
    return {"ok": True}


@app.post("/solve")
def solve_endpoint(req: SolveRequest) -> dict:
    try:
        return solve(
            req.device_id,
            req.flow,
            req.user_agent,
            req.sec_ch_ua,
            req.observer_wait_ms,
        )
    except NotImplementedError as exc:
        # seam 未填充（等 HAR）：显式 501，app 侧会降级到进程内拼接
        raise HTTPException(status_code=501, detail=f"seam_unfilled: {exc}")
    except Exception as exc:  # 浏览器/SDK 运行异常
        raise HTTPException(status_code=500, detail=f"solver_error: {str(exc)[:200]}")
