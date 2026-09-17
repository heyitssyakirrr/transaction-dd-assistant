FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app

# OpenShift assigns an arbitrary non-root UID. Group write keeps this image
# compatible if a future runtime directory is added.
RUN chgrp -R 0 /app && chmod -R g=u /app
EXPOSE 8080
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
