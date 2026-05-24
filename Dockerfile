FROM python:3.11-slim

WORKDIR /app

ARG LIQUIBASE_VERSION=4.29.2

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev curl ca-certificates default-jre-headless \
    && curl -fsSL "https://github.com/liquibase/liquibase/releases/download/v${LIQUIBASE_VERSION}/liquibase-${LIQUIBASE_VERSION}.tar.gz" \
       -o /tmp/liquibase.tar.gz \
    && mkdir -p /opt/liquibase \
    && tar -xzf /tmp/liquibase.tar.gz -C /opt/liquibase \
    && ln -s /opt/liquibase/liquibase /usr/local/bin/liquibase \
    && rm /tmp/liquibase.tar.gz \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir torch==2.5.1 --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir .

COPY app ./app
COPY eval ./eval
COPY db ./db
COPY scripts ./scripts
COPY liquibase.properties ./
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8000
ENTRYPOINT ["/entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
