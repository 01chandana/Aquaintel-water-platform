#!/usr/bin/env bash
# Topics from Table 5.2. Messages are keyed by asset id, so ordering is per asset within a partition.
# retention.ms = days * 86 400 000
set -euo pipefail
BOOTSTRAP=${BOOTSTRAP:-kafka:9092}
create() {  # name partitions retention_days
  kafka-topics --bootstrap-server "$BOOTSTRAP" --create --if-not-exists --topic "$1" \
    --partitions "$2" --replication-factor 1 --config retention.ms=$(( $3 * 86400000 ))
}
create telemetry.raw          12 7
create telemetry.processed    12 30
create telemetry.dlq           3 30
create alerts.generated        6 90
create alerts.acknowledged     6 90
create kpis.computed           3 90
create ml.inference.request    3 7
create ml.inference.result     3 30
create audit.events            3 365
create assets.changed          3 90
kafka-topics --bootstrap-server "$BOOTSTRAP" --list
