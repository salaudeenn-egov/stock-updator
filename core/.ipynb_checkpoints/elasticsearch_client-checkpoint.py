"""
Elasticsearch enrichment helpers for stock records.
"""

import base64
import warnings
from datetime import datetime, timedelta

import requests

DEFAULT_ELASTIC_AUTH_HEADER = "Basic ZWxhc3RpYzpXZWtueThyN1pyQ3NVcHBkU0Q5N0piUlQ="

warnings.filterwarnings("ignore", message="Unverified HTTPS request is being made.*")


class ElasticsearchEnricher:
    """Fetch Elasticsearch documents keyed by stock ID."""

    def __init__(
        self,
        elastic_url,
        scroll_url=None,
        id_field="Data.id.keyword",
        chunk_size=500,
        auth_header=None,
        verify_ssl=True,
    ):
        self.elastic_url = elastic_url.strip()
        self.scroll_url = (scroll_url or "").strip()
        self.id_field = id_field
        self.chunk_size = int(chunk_size)
        self.auth_header = (auth_header or DEFAULT_ELASTIC_AUTH_HEADER).strip()
        self.verify_ssl = bool(verify_ssl)
        self.session = requests.Session()

    @staticmethod
    def build_basic_auth(username, password):
        """Build a Basic auth header value from username and password."""
        token = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
        return f"Basic {token}"

    def _iter_chunks(self, values):
        for start in range(0, len(values), self.chunk_size):
            yield values[start:start + self.chunk_size]

    def _build_query(self, ids):
        return {
            "size": len(ids),
            "query": {
                "terms": {
                    self.id_field: ids
                }
            }
        }

    @staticmethod
    def _date_to_epoch_millis(value, end_of_day=False):
        parsed = datetime.strptime(value, "%Y-%m-%d")
        if end_of_day:
            parsed = parsed + timedelta(days=1) - timedelta(milliseconds=1)
        return int(parsed.timestamp() * 1000)

    @staticmethod
    def _date_to_iso_utc(value, end_of_day=False):
        parsed = datetime.strptime(value, "%Y-%m-%d")
        if end_of_day:
            return parsed.strftime("%Y-%m-%dT23:59:59Z")
        return parsed.strftime("%Y-%m-%dT00:00:00Z")

    @staticmethod
    def _uses_iso_date_range(date_field):
        return "@timestamp" in str(date_field)

    def _build_date_range_query(self, tenant_id, start_date, end_date, date_field, size):
        must = [{"term": {"Data.tenantId.keyword": tenant_id}}]
        range_query = {}
        iso_range = self._uses_iso_date_range(date_field)
        if start_date:
            range_query["gte"] = (
                self._date_to_iso_utc(start_date)
                if iso_range else
                self._date_to_epoch_millis(start_date)
            )
        if end_date:
            range_query["lte"] = (
                self._date_to_iso_utc(end_date, end_of_day=True)
                if iso_range else
                self._date_to_epoch_millis(end_date, end_of_day=True)
            )
        if range_query:
            must.append({"range": {date_field: range_query}})

        return {
            "size": size,
            "query": {
                "bool": {
                    "must": must,
                }
            }
        }

    def _headers(self):
        headers = {"Content-Type": "application/json"}
        if self.auth_header:
            headers["Authorization"] = self.auth_header
        return headers

    def fetch_by_ids(self, stock_ids, progress_callback=None):
        results = {}
        unique_ids = [stock_id for stock_id in dict.fromkeys(stock_ids) if stock_id]

        for index, chunk in enumerate(self._iter_chunks(unique_ids), start=1):
            response = self.session.post(
                self.elastic_url,
                headers=self._headers(),
                json=self._build_query(chunk),
                timeout=60,
                verify=self.verify_ssl,
            )
            response.raise_for_status()
            data = response.json()

            hits = data.get("hits", {}).get("hits", [])
            for hit in hits:
                source = hit.get("_source", {})
                doc = source.get("Data", source)
                stock_id = doc.get("id")
                if stock_id:
                    results[stock_id] = doc

            if progress_callback:
                progress_callback(index, len(chunk), len(results))

        return results

    def search_by_date_range(
        self,
        tenant_id,
        start_date=None,
        end_date=None,
        date_field="Data.@timestamp",
        size=5000,
    ):
        results = []
        scroll_id = None

        while True:
            if scroll_id is None:
                url = self.elastic_url.rstrip("/") + "/?scroll=10m"
                payload = self._build_date_range_query(
                    tenant_id=tenant_id,
                    start_date=start_date,
                    end_date=end_date,
                    date_field=date_field,
                    size=size,
                )
            else:
                if not self.scroll_url:
                    raise ValueError("scroll_url is required for Elasticsearch scroll requests")
                url = self.scroll_url
                payload = {"scroll": "10m", "scroll_id": scroll_id}

            response = self.session.post(
                url,
                headers=self._headers(),
                json=payload,
                timeout=60,
                verify=self.verify_ssl,
            )
            response.raise_for_status()
            data = response.json()
            hits = data.get("hits", {}).get("hits", [])
            if not hits:
                break

            for hit in hits:
                source = hit.get("_source", {})
                doc = source.get("Data", source)
                if isinstance(doc, dict):
                    results.append(doc)

            scroll_id = data.get("_scroll_id")

        return results
