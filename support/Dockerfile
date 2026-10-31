# Build with support/ as the context so nothing else in the repo (private/ in
# particular) is ever uploaded:  gcloud builds submit support/ ...
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8080
WORKDIR /app

COPY requirements.txt requirements-gcp.txt /app/support/
RUN pip install --no-cache-dir -r /app/support/requirements.txt -r /app/support/requirements-gcp.txt

COPY . /app/support/
RUN useradd --create-home tidy
USER tidy

CMD ["sh", "-c", "exec uvicorn support.app.main:app --host 0.0.0.0 --port ${PORT}"]
