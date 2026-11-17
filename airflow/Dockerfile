# Airflow orchestrates the batch ML pipeline (Ch. 4.2, 14). DAGs only call the AquaIntel API,
# so the image needs no application code: the training itself runs on the Celery `ml` queue.
FROM apache/airflow:2.10.3-python3.11
COPY dags/ /opt/airflow/dags/
