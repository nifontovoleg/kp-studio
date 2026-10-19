FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends fonts-dejavu-core && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY studio/ studio/
COPY examples/ examples/
RUN useradd --create-home studio && mkdir /app/output && chown studio:studio /app/output
USER studio
ENTRYPOINT ["python", "-m", "studio"]
CMD ["examples/clients.csv", "--demo"]
