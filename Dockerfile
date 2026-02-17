FROM python:3.12-slim

# 시스템 패키지: WeasyPrint 의존성 + 한글 폰트 + cron + git + curl + Node.js
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl git cron \
    fonts-noto-cjk \
    libpango-1.0-0 libpangoft2-1.0-0 libcairo2 \
    libgdk-pixbuf-2.0-0 libffi-dev \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# Claude CLI 설치
RUN npm install -g @anthropic-ai/claude-code

# 작업 디렉토리
WORKDIR /app

# Python 의존성
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt markdown weasyprint requests

# 앱 코드 복사
COPY . .

# crontab 설치
COPY docker/crontab /etc/cron.d/potato-fin
RUN chmod 0644 /etc/cron.d/potato-fin && crontab /etc/cron.d/potato-fin

# 로그/데이터 디렉토리 생성
RUN mkdir -p /app/logs /app/data/monitor /app/보고서/한국 /app/보고서/브리핑 /app/보고서/뉴스

# 앱 사용자 생성 (Claude 인증용 홈 디렉토리)
RUN useradd -m -s /bin/bash app
ENV HOME=/home/app

# entrypoint
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
