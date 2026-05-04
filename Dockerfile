# Use a Python base image
FROM python:3.10-slim-buster

# Set the working directory in the container
WORKDIR /app

# Copy the requirements file and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code
COPY . .

# Expose the port that the application will run on
# Cloud Run injects the PORT environment variable
ENV PORT 8080
EXPOSE $PORT

# Define the command to run the application
CMD exec uvicorn api.main:app --host 0.0.0.0 --port "$PORT"
