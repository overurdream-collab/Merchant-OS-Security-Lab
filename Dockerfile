FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY src ./src
COPY tests ./tests
COPY README.md .
ENV PYTHONPATH=/app/src
ENV PORT=8080
EXPOSE 8080
CMD ["python", "src/run_webhook.py"]
