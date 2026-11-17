FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml requirements.lock ./
COPY alembic.ini ./
RUN pip install --no-cache-dir -r requirements.lock
COPY migrations ./migrations
COPY services ./services
COPY packages ./packages
RUN pip install --no-cache-dir --no-deps .
EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && uvicorn services.api.main:app --host 0.0.0.0 --port 8000"]
