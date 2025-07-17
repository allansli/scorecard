# Use an official Python runtime as a parent image
FROM python:3.9-slim

# Set the working directory in the container
WORKDIR /app

# Copy the dependencies file to the working directory
COPY api/requirements.txt .

# Install any needed dependencies specified in requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy the shared scoring configuration
COPY scoring_config/scoring_config.yaml ./scoring_config/scoring_config.yaml

# Copy the content of the local api directory to the working directory
COPY api/ .

# Expose port 8000 for the API
EXPOSE 8000

# Run the Uvicorn server
CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000"]
