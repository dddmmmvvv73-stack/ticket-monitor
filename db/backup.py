"""
Ночная копия базы в Object Storage (Яндекс Облако): pg_dump → gzip → бакет, папка backups/.

    python3 -m db.backup           сделать копию
    python3 -m db.backup lifecycle  задать срок хранения копий (30 дней) — один раз

Нужны переменные окружения (на сервере — /etc/ticket-monitor.env): DATABASE_URL, S3_KEY_ID, S3_SECRET, S3_BUCKET.
"""

from __future__ import annotations

import gzip
import os
import subprocess
import sys
from datetime import datetime

KEEP_DAYS = 30
ENDPOINT = "https://storage.yandexcloud.net"


def _s3():
    import boto3  # только на сервере
    return boto3.session.Session().client("s3", endpoint_url=ENDPOINT, region_name="ru-central1",
                                          aws_access_key_id=os.environ["S3_KEY_ID"],
                                          aws_secret_access_key=os.environ["S3_SECRET"])


def backup() -> str:
    dump = subprocess.run(["pg_dump", "--no-owner", "--format=plain", os.environ["DATABASE_URL"]],
                          check=True, capture_output=True).stdout
    key = "backups/ticket_monitor-%s.sql.gz" % datetime.now().strftime("%Y%m%d-%H%M")
    _s3().put_object(Bucket=os.environ["S3_BUCKET"], Key=key, Body=gzip.compress(dump))
    return "%s (%.1f МБ, сжато)" % (key, len(gzip.compress(dump)) / 1e6)


def lifecycle() -> None:
    _s3().put_bucket_lifecycle_configuration(
        Bucket=os.environ["S3_BUCKET"],
        LifecycleConfiguration={"Rules": [{"ID": "backups-%dd" % KEEP_DAYS, "Status": "Enabled",
                                           "Filter": {"Prefix": "backups/"}, "Expiration": {"Days": KEEP_DAYS}}]})


if __name__ == "__main__":
    if sys.argv[1:2] == ["lifecycle"]:
        lifecycle()
        print("Копии базы хранятся %d дней" % KEEP_DAYS)
    else:
        print("Копия базы:", backup())
