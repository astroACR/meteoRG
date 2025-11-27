FROM python:3.10-slim
WORKDIR /backend
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
CMD exec uvicorn main:app --host 0.0.0.0 --port $PORT


