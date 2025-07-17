import os
import logging
import psycopg2
import yaml
from fastapi import FastAPI, HTTPException
from psycopg2.extras import RealDictCursor

# --- Configuration ---
DB_PARAMS = {
    'dbname': os.environ.get('POSTGRES_DB', 'scorecard'),
    'user': os.environ.get('POSTGRES_USER', 'postgres'),
    'password': os.environ.get('POSTGRES_PASSWORD', 'postgres'),
    'host': os.environ.get('POSTGRES_HOST', 'postgres'),
    'port': os.environ.get('POSTGRES_PORT', '5432')
}

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- FastAPI App ---
app = FastAPI(
    title="Project Scorecard API",
    description="API to retrieve project scan results and metadata.",
    version="1.0.0"
)

# --- Database Connection ---
def get_db_connection():
    """Establish a connection to the PostgreSQL database."""
    try:
        conn = psycopg2.connect(**DB_PARAMS)
        return conn
    except psycopg2.Error as e:
        logger.error(f"Database connection error: {e}")
        raise HTTPException(status_code=500, detail="Database connection failed.")

# --- Load Scoring Config ---
def load_scoring_config():
    """Load the scoring formula from the YAML configuration file."""
    # Adjust the path to be relative to the api directory
    config_path = os.path.join(os.path.dirname(__file__), 'scoring_config', 'scoring_config.yaml')
    try:
        with open(config_path, 'r') as f:
            return yaml.safe_load(f)
    except FileNotFoundError:
        return None

# --- Scoring Calculation ---
def calculate_max_score(scoring_config):
    """Calculate the maximum possible score from the scoring configuration."""
    if not scoring_config or 'metrics' not in scoring_config:
        return 0

    max_score = 0
    for metric in scoring_config['metrics']:
        metric_max_score = 0;
        weight = metric.get('weight', 1.0)
        metric_type = metric.get('type')

        if metric_type == 'direct_scaled':
            # Use the base_max_value from config, defaulting to 10 for backward compatibility
            base_max = metric.get('base_max_value', 10)
            metric_max_score = base_max * metric.get('scale_factor', 1) * weight
            max_score += metric_max_score
            logger.info(f"Direct scaled metric: {metric['name']}, base_max: {base_max}, max score: {metric_max_score}")
        elif metric_type == 'direct':
            # Direct percentage, max 100
            metric_max_score = 100 * weight
            max_score += metric_max_score
            logger.info(f"Direct metric: {metric['name']}, max score: {metric_max_score}")
        elif metric_type in ['inverted_scaled', 'inverted_percentage']:
            # Score starts at max_score and decreases
            metric_max_score = metric.get('max_score', 0) * weight
            max_score += metric_max_score
            logger.info(f"Inverted metric: {metric['name']}, max score: {metric_max_score}")
            
    return max_score

# --- API Endpoint ---
@app.get("/scan/{project_name}")
def get_latest_scan(project_name: str):
    """
    Retrieve the latest scan results for a given project name.

    This endpoint returns the most recent scan record, including the final score
    and all associated metadata from sources like SonarQube and OpenSSF Scorecard.
    """
    logger.info(f"Received request for latest scan of project: {project_name}")
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            # Find the most recent scan for the project
            cursor.execute(
                """ 
                SELECT scan_id, project_name, scan_date, final_score
                FROM project_scans
                WHERE project_name = %s
                AND final_score IS NOT NULL
                ORDER BY scan_date DESC
                LIMIT 1;
                """,
                (project_name,)
            )
            latest_scan = cursor.fetchone()

            if not latest_scan:
                logger.warning(f"No scan found for project: {project_name}")
                raise HTTPException(status_code=404, detail="Project not found or no scans available.")

            scan_id = latest_scan['scan_id']

            # Fetch all metadata and their scores for that scan
            cursor.execute(
                """
                SELECT
                    sm.metric_key,
                    sm.metric_value,
                    sm.metric_source,
                    ms.score
                FROM
                    scan_metadata sm
                LEFT JOIN
                    metadata_scores ms ON sm.metadata_id = ms.metadata_id
                WHERE
                    sm.scan_id = %s;
                """,
                (scan_id,)
            )
            metadata_records = cursor.fetchall()

            # Group metadata by source and sort keys
            grouped_metadata = {}
            for record in metadata_records:
                source = record['metric_source']
                if source not in grouped_metadata:
                    grouped_metadata[source] = []
                grouped_metadata[source].append({
                    'metric_key': record['metric_key'],
                    'metric_value': record['metric_value'],
                    'score': record['score']
                })
            
            # Sort the metrics within each group
            for source in grouped_metadata:
                grouped_metadata[source] = sorted(grouped_metadata[source], key=lambda x: x['metric_key'])

            # Load scoring formula from config and format for response
            scoring_config = load_scoring_config()
            if scoring_config:
                max_score = calculate_max_score(scoring_config)
                formula_details = {
                    "description": scoring_config.get('description'),
                    "calculation_logic": scoring_config.get('calculation_logic'),
                    "metrics": scoring_config.get('metrics')
                }
                latest_scan['max_score'] = max_score # Add max score to the response
                latest_scan['scoring_formula'] = formula_details
            else:
                latest_scan['scoring_formula'] = {"error": "Scoring configuration not found."}
                latest_scan['max_score'] = 0

            # Combine the results
            latest_scan['metadata'] = grouped_metadata
            return latest_scan

    except psycopg2.Error as e:
        logger.error(f"Database query error for project {project_name}: {e}")
        raise HTTPException(status_code=500, detail="An error occurred while fetching scan results.")
    finally:
        if conn:
            conn.close()

@app.get("/")
def read_root():
    return {"message": "Welcome to the Project Scorecard API. Go to /docs for documentation."}
