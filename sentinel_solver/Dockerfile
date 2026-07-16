# sentinel-solver: 无头浏览器跑真实官方 Sentinel sdk.js，生成 openai-sentinel-token / so-token。
# 用官方 Playwright 镜像（自带 chromium），免去 playwright install 步骤。
FROM mcr.microsoft.com/playwright/python:v1.49.0-noble

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
# 装与 playwright 版本匹配的 chromium（含 headless shell），base image 自带的是其它版本会不匹配。
RUN playwright install chromium

COPY app.py runner.py ./

EXPOSE 8000
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
