# Project Scorecard

This project provides a data aggregation and analysis platform using Docker Compose. It includes SonarQube for code quality analysis, a custom data ingestion service for collecting metrics from SonarQube and OpenSSF Scorecard, and a PostgreSQL database to store the results.

## Components

- **SonarQube**: Code quality and security analysis platform.
- **PostgreSQL**: Central database for storing all collected data.
- **Data Ingestion Service**: A custom Python service that periodically fetches data from SonarQube and runs OpenSSF Scorecard against a list of repositories.
- **API**: A FastAPI-based service that exposes the collected data for querying.

## Prerequisites

- Docker and Docker Compose
- GitHub token with `repo` scope for OpenSSF Scorecard
- SonarQube token (once SonarQube is set up)

## Getting Started

1. Clone this repository:
   ```
   git clone <repository-url>
   cd scorecard
   ```

2. Create a `.env` file from the template:
   ```
   cp .env-example .env
   ```

3. Edit the `.env` file and add your tokens:
   ```
   SONARQUBE_TOKEN=your_sonarqube_token
   SCORECARD_GITHUB_TOKEN=your_github_token
   ```

4. Start the services:
   ```
   docker-compose up -d
   ```

5. Access the services:
   - **SonarQube**: http://localhost:9000 (default credentials: `admin`/`admin`)
   - **API**: http://localhost:8000/scan/{project_name}

## Architecture

- **PostgreSQL** serves as the central database with dedicated schemas:
  - `sonar`: Used by SonarQube for its internal data.
  - `scorecard`: Used by the data ingestion service to store collected metrics and calculated scores.

- **Data Ingestion Service** runs periodically to:
  - Fetch project metrics from SonarQube (every 6 hours)
  - Run OpenSSF Scorecard against repositories in `repositories.txt` (every 24 hours)
  - Store results in the PostgreSQL database

## Adding Repositories

To add repositories to be analyzed by OpenSSF Scorecard, edit the `data-ingestion/repositories.txt` file:

```
github.com/owner/repo1
github.com/owner/repo2
```

## Configuration

### PostgreSQL
- Default credentials: postgres/postgres
- Port: 5432

### SonarQube
- Initial setup: After first login, generate a token for the data ingestion service
- Port: 9000

### Backstage
- Port: 7007
- Customize by modifying files in the `backstage` directory

## Troubleshooting

- **SonarQube fails to start**: Ensure your Docker has enough memory allocated (at least 4GB)
- **Data ingestion issues**: Check logs with `docker-compose logs data-ingestion`
- **Backstage build errors**: Run `docker-compose logs backstage` for details

## License

[Your License]
