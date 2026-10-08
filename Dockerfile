FROM python:3.14-alpine
RUN adduser -D -u 10001 appuser
WORKDIR /app

COPY app/requirements.txt .
RUN pip install --no-cache-dir \
    -r requirements.txt

COPY --chown=appuser:appuser app/app.py .
USER appuser

EXPOSE 8000
CMD [ "python", "app.py" ]
