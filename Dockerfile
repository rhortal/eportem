FROM python:3.11-slim

WORKDIR /app

COPY eportem /app

RUN pip install --upgrade pip && \
    pip install -r requirements.txt

ENV PYTHONUNBUFFERED=1
ENV USE_MOCK_SERVER=NO

EXPOSE 8010

CMD ["python", "web_ui/server.py"]
