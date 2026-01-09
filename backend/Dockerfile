ARG PYTHON_VERSION=3.11-slim

FROM python:${PYTHON_VERSION}

ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

RUN mkdir -p /code

WORKDIR /code

COPY requirements.txt /tmp/requirements.txt
RUN set -ex && \
    pip install --upgrade pip && \
    pip install -r /tmp/requirements.txt && \
    rm -rf /root/.cache/
COPY . /code

ENV SECRET_KEY "cq6yZy8GDjcEkUFT3wU7Mi70TOPnHeZlSfPb95gFsSCIptbbo5"
RUN python manage.py collectstatic --noinput

EXPOSE 8000

CMD ["uvicorn", "fuel_optimization.asgi:application", "--host", "0.0.0.0", "--port", "8000"]
