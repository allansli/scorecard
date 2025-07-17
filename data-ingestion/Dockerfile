FROM python:3.9-slim

WORKDIR /app

# Install required system dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends git curl ca-certificates && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Install Go for OpenSSF Scorecard CLI (using newer version)
RUN curl -L https://golang.org/dl/go1.20.5.linux-amd64.tar.gz | tar -C /usr/local -xzf -
ENV PATH=$PATH:/usr/local/go/bin

# Install Scorecard
RUN go install github.com/ossf/scorecard/v4@latest
ENV PATH=$PATH:/root/go/bin

# Copy requirements first for better caching
COPY data-ingestion/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the shared scoring configuration
COPY scoring_config/scoring_config.yaml ./scoring_config/scoring_config.yaml

# Copy the ingestion scripts
COPY data-ingestion/ .

# Run the data ingestion script
CMD ["python", "new_ingestor.py"]
