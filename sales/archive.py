"""
Архив сырых ответов (решение 04.10: каждая изменившаяся сводка и схема). На сервере — бакет Object Storage
(S3_BUCKET, папка raw/), на ноутбуке — data/raw_sales. Возвращает ссылку для observations.raw_ref.
"""

from __future__ import annotations

import gzip
import os
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_s3 = None


def save(operator: str, kind: str, ident: str, body: bytes) -> str:
    now = datetime.now()
    key = "raw/%s/%s/%s/%s_%s.json.gz" % (now.strftime("%Y/%m/%d"), operator, kind, ident.replace("/", "_"), now.strftime("%H%M%S"))
    data = gzip.compress(body)
    if os.environ.get("S3_BUCKET"):
        global _s3
        if _s3 is None:
            import boto3
            _s3 = boto3.session.Session().client("s3", endpoint_url="https://storage.yandexcloud.net", region_name="ru-central1",
                                                 aws_access_key_id=os.environ["S3_KEY_ID"], aws_secret_access_key=os.environ["S3_SECRET"])
        _s3.put_object(Bucket=os.environ["S3_BUCKET"], Key=key, Body=data)
        return "s3://%s/%s" % (os.environ["S3_BUCKET"], key)
    path = ROOT / "data" / "raw_sales" / key[4:]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return str(path.relative_to(ROOT))
