FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml requirements.lock ./
COPY services ./services
COPY packages ./packages
RUN pip install --no-cache-dir -r requirements.lock && pip install --no-cache-dir --no-deps .
EXPOSE 8000
CMD ["uvicorn", "services.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
