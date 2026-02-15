FROM python:3.13-slim

RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN mkdir -p uploads

EXPOSE 8000
CMD ["gunicorn", "-w", "2", "--preload", "-b", "0.0.0.0:8000", "app:app"]
