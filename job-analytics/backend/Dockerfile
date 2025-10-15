FROM python:3.11.9-slim
COPY requirements.txt requirements.txt
RUN pip install -r requirements.txt
COPY ./ /usr/app
CMD [ "python", "main.py" ]