#!/usr/bin/env python3
import os
import time
import logging
import requests
import subprocess
import json
import psycopg2
import schedule
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
import yaml

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# --- Configuration ---
DB_PARAMS = {
    'dbname': os.environ.get('POSTGRES_DB', 'scorecard'),
    'user': os.environ.get('POSTGRES_USER', 'postgres'),
    'password': os.environ.get('POSTGRES_PASSWORD', 'postgres'),
    'host': os.environ.get('POSTGRES_HOST', 'postgres'),
    'port': os.environ.get('POSTGRES_PORT', '5432')
}

SONARQUBE_URL = os.environ.get('SONARQUBE_URL', 'http://sonarqube:9000')
SONARQUBE_TOKEN = os.environ.get('SONARQUBE_TOKEN', '')

SCORECARD_GITHUB_TOKEN = os.environ.get('SCORECARD_GITHUB_TOKEN', '')
REPOSITORIES_FILE = os.environ.get('REPOSITORIES_FILE', 'repositories.txt')

# --- Database Functions ---
def get_db_connection():
    """Establish a connection to the PostgreSQL database."""
    try:
        conn = psycopg2.connect(**DB_PARAMS)
        return conn
    except psycopg2.Error as e:
        logger.error(f"Database connection error: {e}")
        return None

def create_scan_record(conn, project_name):
    """Create a new scan record and return its ID."""
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "INSERT INTO project_scans (project_name) VALUES (%s) RETURNING scan_id;",
                (project_name,)
            )
            scan_id = cursor.fetchone()[0]
            conn.commit()
            logger.info(f"Created scan record for {project_name} with ID: {scan_id}")
            return scan_id
    except psycopg2.Error as e:
        logger.error(f"Failed to create scan record for {project_name}: {e}")
        conn.rollback()
        return None

def store_metadata_record(conn, scan_id, key, value, source):
    """Store a single metadata record."""
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO scan_metadata (scan_id, metric_key, metric_value, metric_source)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (scan_id, metric_key, metric_source) DO UPDATE SET
                    metric_value = EXCLUDED.metric_value;
                """,
                (scan_id, key, str(value), source)
            )
    except psycopg2.Error as e:
        logger.error(f"Failed to store metadata for scan {scan_id}: {key}={value} from {source}. Error: {e}")
        conn.rollback()

def update_final_score(conn, scan_id, score):
    """Update the final score for a given scan."""
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "UPDATE project_scans SET final_score = %s WHERE scan_id = %s;",
                (score, scan_id)
            )
            conn.commit()
            logger.info(f"Updated final score for scan ID {scan_id} to {score}")
    except psycopg2.Error as e:
        logger.error(f"Failed to update final score for scan {scan_id}: {e}")
        conn.rollback()

# --- Data Collection Functions ---
def collect_sonarqube_metrics(project_key, scan_id):
    """Collect metrics from SonarQube for a specific project."""
    logger.info(f"Collecting SonarQube metrics for {project_key} (Scan ID: {scan_id})")
    if not SONARQUBE_TOKEN:
        logger.warning("SonarQube token not set. Skipping SonarQube collection.")
        return

    conn = get_db_connection()
    if not conn:
        return

    try:
        auth = (SONARQUBE_TOKEN, '')
        metric_keys = 'bugs,vulnerabilities,code_smells,coverage,duplicated_lines_density'
        response = requests.get(
            f"{SONARQUBE_URL}/api/measures/component",
            params={'component': project_key, 'metricKeys': metric_keys},
            auth=auth
        )
        response.raise_for_status()
        measures = response.json().get('component', {}).get('measures', [])

        for measure in measures:
            store_metadata_record(conn, scan_id, measure['metric'], measure['value'], 'sonarqube')
        
        conn.commit()
        logger.info(f"Successfully collected SonarQube metrics for {project_key}")
    except requests.RequestException as e:
        logger.error(f"SonarQube API error for {project_key}: {e}")
    finally:
        if conn:
            conn.close()

def collect_openssf_metrics(repo_url, scan_id):
    """Collect metrics from OpenSSF Scorecard for a specific repository."""
    logger.info(f"Collecting OpenSSF Scorecard metrics for {repo_url} (Scan ID: {scan_id})")
    if not SCORECARD_GITHUB_TOKEN:
        logger.warning("Scorecard GitHub token not set. Skipping OpenSSF collection.")
        return

    conn = get_db_connection()
    if not conn:
        return

    try:
        env = os.environ.copy()
        env['GITHUB_AUTH_TOKEN'] = SCORECARD_GITHUB_TOKEN
        result = subprocess.run(
            ['scorecard', '--repo', repo_url, '--format', 'json'],
            capture_output=True, text=True, env=env
        )

        if result.returncode != 0:
            logger.error(f"Scorecard command failed for {repo_url}: {result.stderr}")
            return

        scorecard_data = json.loads(result.stdout)
        store_metadata_record(conn, scan_id, 'overall_score', scorecard_data.get('score', 0), 'openssf')

        for check in scorecard_data.get('checks', []) :
            store_metadata_record(conn, scan_id, check['name'], check['score'], 'openssf')
        
        conn.commit()
        logger.info(f"Successfully collected OpenSSF Scorecard metrics for {repo_url}")
    except (json.JSONDecodeError, subprocess.SubprocessError) as e:
        logger.error(f"Error running or parsing Scorecard for {repo_url}: {e}")
    finally:
        if conn:
            conn.close()

# --- Scoring Algorithm ---
def load_scoring_config():
    """Load the scoring formula from the YAML configuration file."""
    config_path = os.path.join(os.path.dirname(__file__), 'scoring_config.yaml')
    with open(config_path, 'r') as f:
        return yaml.safe_load(f)

def calculate_final_score(scan_id):
    """Calculate the final score based on the configurable formula."""
    conn = get_db_connection()
    if not conn:
        return 0.0

    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT metric_key, metric_value, metric_source FROM scan_metadata WHERE scan_id = %s;", (scan_id,))
            records = cursor.fetchall()
    finally:
        conn.close()

    if not records:
        logger.warning(f"No metadata found for scan ID {scan_id}. Cannot calculate score.")
        return 0.0

    config = load_scoring_config()
    metrics_config = config.get('metrics', [])
    
    metrics_by_source = {rec[2]: {} for rec in records}
    for key, value, source in records:
        try:
            metrics_by_source[source][key] = float(value)
        except (ValueError, TypeError):
            pass

    total_score = 0
    total_weight = 0

    for metric_def in metrics_config:
        source = metric_def['source']
        key = metric_def['key']
        weight = metric_def['weight']
        m_type = metric_def['type']

        raw_value = metrics_by_source.get(source, {}).get(key, -1)

        # Gracefully skip metrics that are in the config but not found in the scan data
        if raw_value == -1:
            continue

        metric_score = 0
        if m_type == 'direct':
            metric_score = raw_value
        elif m_type == 'direct_scaled':
            metric_score = raw_value * metric_def.get('scale_factor', 1)
        elif m_type == 'inverted_scaled':
            max_score = metric_def.get('max_score', 100)
            metric_score = max(0, max_score - (raw_value * metric_def.get('scale_factor', 1)))
        elif m_type == 'inverted_percentage':
            max_score = metric_def.get('max_score', 100)
            metric_score = max_score - raw_value

        total_score += metric_score * weight
        total_weight += weight

    # The final score is the sum of weighted scores, not a normalized average
    final_score = total_score
    return round(final_score, 2)

# --- Main Workflow ---
def run_ingestion_workflow():
    """Run the full ingestion workflow for all repositories."""
    logger.info("Starting new ingestion workflow...")
    try:
        with open(REPOSITORIES_FILE, 'r') as f:
            repositories = [line.strip() for line in f if line.strip()]
    except FileNotFoundError:
        logger.error(f"Repositories file not found at {REPOSITORIES_FILE}. Aborting.")
        return

    for repo_url in repositories:
        project_name = repo_url.split('/')[-1]
        logger.info(f"Processing project: {project_name} ({repo_url})")
        
        conn = get_db_connection()
        if not conn:
            continue

        scan_id = create_scan_record(conn, project_name)
        conn.close()

        if not scan_id:
            continue

        # Run collection in parallel
        with ThreadPoolExecutor(max_workers=2) as executor:
            # SonarQube project key is often the same as the repo name
            executor.submit(collect_sonarqube_metrics, project_name, scan_id)
            executor.submit(collect_openssf_metrics, repo_url, scan_id)

        # Calculate and update the final score
        final_score = calculate_final_score(scan_id)
        
        conn = get_db_connection()
        if conn:
            update_final_score(conn, scan_id, final_score)
            conn.close()

    logger.info("Ingestion workflow completed.")

def main():
    """Main function to schedule and run the ingestion workflow."""
    logger.info("Initializing ingestor...")
    
    # Run once on startup
    run_ingestion_workflow()
    
    # Schedule to run every 24 hours
    schedule.every(24).hours.do(run_ingestion_workflow)
    
    logger.info("Scheduler started. Waiting for next run.")
    while True:
        schedule.run_pending()
        time.sleep(60)

if __name__ == "__main__":
    main()
