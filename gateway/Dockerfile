FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir "litellm[proxy]"

COPY start.sh /app/start.sh
COPY litellm.config.template.yaml /app/litellm.config.template.yaml

RUN chmod +x /app/start.sh

EXPOSE 4000

CMD ["/app/start.sh"]

