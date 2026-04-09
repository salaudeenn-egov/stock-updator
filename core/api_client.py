"""
API client for fetching stock records from the stock search endpoint.
"""

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import requests


class StockAPIClient:
    """Fetch paginated stock rows from the stock search API."""

    def __init__(self, api_url, tenant_id, auth_token=None, page_size=500, update_url=None):
        self.api_url = api_url.strip()
        self.tenant_id = tenant_id.strip()
        self.auth_token = (auth_token or "").strip()
        self.page_size = int(page_size)
        self.update_url = (update_url or self.api_url.replace("/_search", "/_update")).strip()
        self.session = requests.Session()

    def _build_user_info(self):
        tenant_id = self.tenant_id
        return {
            "id": 0,
            "userName": "stock-enrichment",
            "name": "Stock Enrichment",
            "mobileNumber": "9999999999",
            "type": "EMPLOYEE",
            "tenantId": tenant_id,
            "roles": [
                {"code": "SUPERUSER", "name": "Super User", "tenantId": tenant_id},
                {"code": "SYSTEM_ADMINISTRATOR", "name": "System Administrator", "tenantId": tenant_id},
                {"code": "WAREHOUSE_MANAGER", "name": "Warehouse Manager", "tenantId": tenant_id},
            ],
            "uuid": "stock-enrichment",
        }

    def _build_url(self, offset, limit):
        parsed = urlsplit(self.api_url)
        query = dict(parse_qsl(parsed.query, keep_blank_values=True))
        query["tenantId"] = self.tenant_id
        query["offset"] = str(offset)
        query["limit"] = str(limit)
        return urlunsplit(
            (parsed.scheme, parsed.netloc, parsed.path, urlencode(query), parsed.fragment)
        )

    def _build_payload(self):
        return {
            "RequestInfo": self._build_request_info(),
            "Stock": {"tenantId": self.tenant_id},
        }

    def _build_request_info(self):
        info = {
            "apiId": "stock-enrichment",
            "ver": "1.0",
            "ts": 0,
            "action": "POST",
            "did": "stock-enrichment",
            "key": "stock-enrichment",
            "msgId": "stock-enrichment",
            "requesterId": "stock-enrichment",
            "userInfo": self._build_user_info(),
        }
        if self.auth_token:
            info["authToken"] = self.auth_token
        return info

    def fetch_all_stock(self, progress_callback=None, max_records=None):
        rows = []
        offset = 0
        max_records = int(max_records) if max_records else None

        while True:
            url = self._build_url(offset, self.page_size)
            response = self.session.post(url, json=self._build_payload(), timeout=60)
            response.raise_for_status()

            data = response.json()
            page_rows = data.get("Stock", [])
            if max_records is not None:
                remaining = max_records - len(rows)
                if remaining <= 0:
                    break
                rows.extend(page_rows[:remaining])
            else:
                rows.extend(page_rows)

            if progress_callback:
                progress_callback(len(rows), len(page_rows), offset)

            if max_records is not None and len(rows) >= max_records:
                break

            if len(page_rows) < self.page_size:
                break

            offset += self.page_size

        return rows

    def fetch_stock_by_ids(self, stock_ids, progress_callback=None):
        found = {}
        ids = [stock_id for stock_id in dict.fromkeys(stock_ids) if stock_id]

        for index, stock_id in enumerate(ids, start=1):
            payload = {
                "RequestInfo": self._build_request_info(),
                "Stock": {"id": [stock_id]},
            }
            response = self.session.post(self._build_url(0, 100), json=payload, timeout=60)
            response.raise_for_status()
            rows = response.json().get("Stock", [])
            if rows:
                found[stock_id] = rows[0]
            if progress_callback:
                progress_callback(index, len(ids), stock_id, bool(rows))

        return found

    def update_stock(self, stock_payload):
        payload = {
            "RequestInfo": self._build_request_info(),
            "Stock": stock_payload,
        }
        response = self.session.post(self.update_url, json=payload, timeout=60)
        response.raise_for_status()
        return response.json()
