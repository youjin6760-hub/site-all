FROM mcr.microsoft.com/playwright/python:v1.49.1-jammy

WORKDIR /app

COPY requirements.txt /app/requirements.txt

RUN pip install --no-cache-dir -r /app/requirements.txt

COPY . /app

ENV APP_ROOT=/app
ENV JOBS_DIR=/app/jobs
ENV PLAYWRIGHT_HEADLESS=true
ENV PYTHONUNBUFFERED=1

RUN mkdir -p /app/jobs

EXPOSE 7860

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "7860"]