FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY backend ./backend
COPY frontend ./frontend
COPY config/phrases.json ./config/phrases.json
RUN useradd --create-home appuser && chown -R appuser:appuser /app
USER appuser
EXPOSE 8765
CMD ["python", "-m", "backend.app", "--host", "0.0.0.0", "--port", "8765"]
