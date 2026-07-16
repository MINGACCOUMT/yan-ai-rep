# sentinel-solver

无头浏览器（Playwright + chromium）跑**真实官方 Sentinel sdk.js**，生成注册流程需要的
`openai-sentinel-token` 与 `openai-sentinel-so-token`。

## 为什么单独做这个

`utils/sentinel.py` 进程内手写拼接的 sentinel token，其 `t`(turnstile)/`so` 字段依赖
`solve_turnstile_token` 解释器，而该解释器跟不上当前 SDK(`20260219f9f6`) 的字节码，
解出来是空的。官方 sdk.js 是浏览器模块（依赖 window/document/fetch/crypto），只能让它在
真浏览器里跑。so-token 更是 `sessionObserverToken`，需要 observer 观察会话约 5000ms 才产出。
所以用一个侧车跑真 sdk.js，最抗 SDK 升级。

## HTTP 契约

```
POST /solve
  req:  {"device_id","flow","user_agent","sec_ch_ua","observer_wait_ms"}
  resp: {"sentinel_token","so_token","oai_sc","sdk"}
GET /health -> {"ok": true}
```

`utils/sentinel.py` 的 `_solve_via_runtime` 通过环境变量
`CHATGPT2API_SENTINEL_SOLVER_URL` 调用它；未配或 5xx/501 时自动降级到进程内拼接。

## ⚠️ 待 HAR 填充（3 处 seam，全在 `runner.py::_run_sdk`）

1. **SEAM-1** bootstrap 页面 URL（哪个页面加载 sdk.js 并挂 `window.SentinelSDK`）。
2. **SEAM-2** `SentinelSDK.token(...)` 调用签名。
3. **SEAM-3** `sessionObserverToken(...)` 调用方式（5000ms observer）。

未填时 `/solve` 返回 `501 seam_unfilled`。HAR 到手后只改这三处 TODO，其余不动。

## 启动

```bash
docker compose -f docker-compose.yml -f docker-compose.sentinel.yml up -d --build
```

本地探测：
```bash
curl -s http://127.0.0.1:8011/health
curl -s -XPOST http://127.0.0.1:8011/solve \
  -H 'content-type: application/json' \
  -d '{"device_id":"00000000-0000-0000-0000-000000000000","flow":"oauth_create_account"}'
```
