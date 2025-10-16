# FROM python:3.11.9-slim
# COPY requirements.txt requirements.txt
# RUN pip install -r requirements.txt
# COPY ./ /usr/app
# CMD [ "python", "main.py" ]
# Dockerfile.backend
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["uvicorn", "app:app", "0.0.0.0:8000"]