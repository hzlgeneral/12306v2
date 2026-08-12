FROM python:3.9-slim
WORKDIR /app
RUN apt-get update && apt-get install -y build-essential libmupdf-dev && rm -rf /var/lib/apt/lists/*
RUN mkdir -p /app/uploads /app/output /app/发票
COPY app.py config.py email_handler.py ticket_core.py /app/
RUN pip install --no-cache-dir pymupdf pillow flask
COPY templates /app/templates/
EXPOSE 5100
CMD ["python", "/app/app.py"]