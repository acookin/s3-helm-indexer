FROM python:3.9-slim-buster

RUN apt-get update && apt-get install -y curl gnupg2 && \
    curl https://baltocdn.com/helm/signing.asc | apt-key add - && \
    apt-get install -y apt-transport-https && \
    echo "deb https://baltocdn.com/helm/stable/debian/ all main" | tee /etc/apt/sources.list.d/helm-stable-debian.list && \
    apt-get update && \
    apt-get install -y helm && \
    apt-get clean

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

ENV ACCESS_KEY=
ENV SECRET_KEY=
ENV S3_BUCKET=
ENV S3_KEY=

COPY helm_indexer.py .

ENTRYPOINT ["python", "helm_indexer.py"]
