# Use a current Python base image with maintained CA certificates.
FROM python:3.11-slim-bookworm

# Set the working directory in the container
WORKDIR /app/api

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && update-ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Copy the requirements file and install dependencies
COPY api/requirements.txt .
RUN python -m pip install --no-cache-dir \
    --trusted-host pypi.org \
    --trusted-host files.pythonhosted.org \
    -r requirements.txt

# Copy the rest of the application code
COPY api/ .

# Expose the port that the application will run on
# The container runtime injects the PORT environment variable.
ENV PORT 8080
EXPOSE $PORT

# Define the command to run the application
CMD exec gunicorn -k uvicorn.workers.UvicornWorker main:app --bind "0.0.0.0:$PORT"
