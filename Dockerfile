FROM python:3.11-slim

WORKDIR /app

# 安裝系統依賴和編譯工具
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    make \
    libffi-dev \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

# 複製 requirements.txt 並安裝 Python 依賴
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 複製應用程式碼
COPY . .

# 設定環境變數
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH

# 暴露端口
EXPOSE 7860

# 啟動應用程式
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "7860"]