"""
Processing helpers for stock enrichment report generation.
"""

import os
import shutil
from datetime import datetime

import pandas as pd
import ipywidgets as widgets
from IPython.display import display

from core.api_client import StockAPIClient
from core.config import load_app_config
from core.elasticsearch_client import ElasticsearchEnricher


def _flatten_additional_fields(stock_row):
    values = {}
    for item in stock_row.get("additionalFields", {}).get("fields", []):
        key = str(item.get("key", "")).strip()
        if key:
            values[f"api_{key}"] = item.get("value")
    return values


def _flatten_es_additional_fields(es_row):
    values = {}
    for item in es_row.get("additionalFields", {}).get("fields", []):
        key = str(item.get("key", "")).strip()
        if key:
            values[f"es_{key}"] = item.get("value")
    return values


def _build_output_dir(base_dir):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = os.path.join(base_dir, "outputs")
    os.makedirs(output_dir, exist_ok=True)
    return output_dir, timestamp


def clear_outputs_dir(base_dir):
    """Remove previous generated output folders before a new run."""
    outputs_dir = os.path.join(base_dir, "outputs")
    os.makedirs(outputs_dir, exist_ok=True)

    for name in os.listdir(outputs_dir):
        path = os.path.join(outputs_dir, name)
        if os.path.isdir(path):
            shutil.rmtree(path, ignore_errors=True)
        elif os.path.isfile(path):
            try:
                os.remove(path)
            except OSError:
                pass


def ensure_uploads_dir(base_dir):
    uploads_dir = os.path.join(base_dir, "uploads")
    os.makedirs(uploads_dir, exist_ok=True)
    return uploads_dir


def clear_uploads_dir(base_dir):
    """Remove previously uploaded files before a new run."""
    uploads_dir = ensure_uploads_dir(base_dir)

    for name in os.listdir(uploads_dir):
        path = os.path.join(uploads_dir, name)
        if os.path.isfile(path):
            try:
                os.remove(path)
            except OSError:
                pass
        elif os.path.isdir(path):
            shutil.rmtree(path, ignore_errors=True)


def _collect_boundary_keys(es_docs):
    keys = set()
    for es_row in es_docs.values():
        boundary = es_row.get("boundaryHierarchy", {}) or {}
        keys.update(boundary.keys())
    preferred_order = [
        "country",
        "state",
        "province",
        "region",
        "district",
        "county",
        "municipality",
        "city",
        "ward",
        "village",
        "areaOfResponsibility",
    ]
    ordered = [key for key in preferred_order if key in keys]
    remaining = sorted(key for key in keys if key not in preferred_order)
    return ordered + remaining


def _merge_rows(stock_rows, es_docs, boundary_keys):
    records = []

    for stock in stock_rows:
        stock_id = stock.get("id", "")
        es_row = es_docs.get(stock_id, {})
        boundary = es_row.get("boundaryHierarchy", {})

        record = {
            "id": stock_id,
            "facilityName": es_row.get("facilityName"),
            "transactingFacilityName": es_row.get("transactingFacilityName"),
            "quantity": stock.get("quantity"),
            "transactionType": stock.get("transactionType"),
            "transactionReason": stock.get("transactionReason"),
            "receiverId": stock.get("receiverId"),
            "senderId": stock.get("senderId"),
            "wayBillNumber": stock.get("wayBillNumber"),
            "dateOfEntry": stock.get("dateOfEntry"),
            "matchedInElastic": bool(es_row),
        }
        for key in boundary_keys:
            record[key] = boundary.get(key)
        records.append(record)

    return records


def _merge_elastic_rows(es_rows, boundary_keys):
    records = []

    for row in es_rows:
        boundary = row.get("boundaryHierarchy", {}) or {}
        record = {
            "id": row.get("id", ""),
            "facilityName": row.get("facilityName"),
            "transactingFacilityName": row.get("transactingFacilityName"),
            "quantity": row.get("physicalCount", row.get("quantity")),
            "transactionType": row.get("eventType", row.get("transactionType")),
            "transactionReason": row.get("reason", row.get("transactionReason")),
            "receiverId": row.get("receiverId"),
            "senderId": row.get("senderId"),
        }
        for key in boundary_keys:
            record[key] = boundary.get(key)
        records.append(record)

    return records


def _has_any_value(records, key):
    return any(record.get(key) not in (None, "") for record in records)


def process_stock_report(
    start_date,
    end_date,
    log,
    output_widget=None,
    config_path=None,
    elastic_chunk_size=500,
):
    """
    Fetch stock rows directly from Elasticsearch using an optional date range and save an Excel report.
    """
    notebook_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    config = load_app_config(config_path)
    output_dir, timestamp = _build_output_dir(notebook_root)
    excel_path = os.path.join(output_dir, f"stock_report_{timestamp}.xlsx")
    report_relpath = os.path.relpath(excel_path, notebook_root).replace("\\", "/")
    output_relpath = os.path.relpath(output_dir, notebook_root).replace("\\", "/")

    tenant_id = config["tenant_id"]
    elastic_url = config["elastic_url"]
    elastic_scroll_api = config.get("elastic_scroll_api", "")
    elastic_auth_header = config.get("elastic_auth_header", "")
    elastic_date_field = config.get("elastic_date_field", "Data.auditDetails.createdTime")

    log("=" * 70)
    log("[PHASE 1] FETCH STOCK FROM ELASTICSEARCH")
    log("=" * 70)
    log(f"[INFO] Tenant ID: {tenant_id}")
    log(f"[INFO] Elastic URL: {elastic_url}")
    log(f"[INFO] Start Date: {start_date or 'None'}")
    log(f"[INFO] End Date: {end_date or 'None'}")
    enricher = ElasticsearchEnricher(
        elastic_url,
        scroll_url=elastic_scroll_api,
        chunk_size=elastic_chunk_size,
        auth_header=elastic_auth_header,
        verify_ssl=False,
    )

    es_progress = widgets.IntProgress(value=0, min=0, max=1, bar_style="info", layout=widgets.Layout(width="500px"))
    es_label = widgets.HTML(value="<b>Searching Elasticsearch...</b>")
    if output_widget:
        with output_widget:
            display(widgets.HBox([es_progress, es_label]))

    es_rows = enricher.search_by_date_range(
        tenant_id=tenant_id,
        start_date=start_date,
        end_date=end_date,
        date_field=elastic_date_field,
        size=1000,
    )
    es_progress.bar_style = "success"
    es_progress.max = max(len(es_rows), 1)
    es_progress.value = max(len(es_rows), 1)
    es_label.value = f"<b>Elastic search complete: {len(es_rows)} rows</b>"
    log(f"[SUCCESS] Fetched {len(es_rows)} stock rows from Elasticsearch")

    log("")
    log("=" * 70)
    log("[PHASE 2] BUILD EXCEL REPORT")
    log("=" * 70)

    es_docs = {row.get("id"): row for row in es_rows if row.get("id")}
    boundary_keys = _collect_boundary_keys(es_docs)
    records = _merge_elastic_rows(es_rows, boundary_keys)
    df = pd.DataFrame(records)
    preferred_columns = [
        *boundary_keys,
        "facilityName",
        "transactingFacilityName",
        "id",
        "quantity",
        "transactionType",
        "transactionReason",
    ]
    if _has_any_value(records, "receiverId"):
        preferred_columns.append("receiverId")
    if _has_any_value(records, "senderId"):
        preferred_columns.append("senderId")
    df = df.reindex(columns=preferred_columns)
    df.to_excel(excel_path, index=False)

    matched = len(df)
    unmatched = 0

    log(f"[SAVED] {excel_path}")
    log(f"[SUMMARY] Total rows: {len(df)}")
    log(f"[SUMMARY] Elastic matched: {matched}")
    log(f"[SUMMARY] Elastic unmatched: {unmatched}")

    return {
        "status": "SUCCESS",
        "mode": "generate",
        "total_rows": len(df),
        "matched_rows": matched,
        "unmatched_rows": unmatched,
        "output_dir": output_dir,
        "output_dir_relpath": output_relpath,
        "report_path": excel_path,
        "report_relpath": report_relpath,
        "status_label": (
            f"<h3 style='color: green;'>Complete! Generated {len(df)} rows. "
            f"Matched {matched} rows in Elasticsearch.</h3>"
        ),
    }


def _safe_number(value):
    if value is None:
        return None
    text = str(value).strip()
    if text == "":
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _extract_error_message(exc):
    response = getattr(exc, "response", None)
    if response is None:
        return str(exc)
    try:
        return response.text
    except Exception:
        return str(exc)


def process_stock_update(
    csv_path,
    log,
    output_widget=None,
    config_path=None,
):
    """
    Read an edited stock CSV, detect changed quantities, update only changed rows,
    and save a result report.
    """
    notebook_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    config = load_app_config(config_path)
    uploads_dir = ensure_uploads_dir(notebook_root)
    output_dir, timestamp = _build_output_dir(notebook_root)
    result_path = os.path.join(output_dir, f"stock_update_result_{timestamp}.xlsx")

    api_url = config["api_url"]
    update_url = config["update_url"]
    tenant_id = config["tenant_id"]
    auth_token = config.get("auth_token", "")

    uploaded_name = os.path.basename(csv_path)
    upload_copy = os.path.join(uploads_dir, uploaded_name)
    if os.path.abspath(csv_path) != os.path.abspath(upload_copy):
        shutil.copy(csv_path, upload_copy)

    log("=" * 70)
    log("[PHASE 1] READ UPLOADED FILE")
    log("=" * 70)
    log(f"[INFO] File: {uploaded_name}")

    lower_path = csv_path.lower()
    if lower_path.endswith(".xlsx"):
        df = pd.read_excel(csv_path)
    else:
        df = pd.read_csv(csv_path)
    required = {"id", "quantity"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Missing required columns: {sorted(missing)}")

    client = StockAPIClient(api_url, tenant_id, auth_token, page_size=100, update_url=update_url)
    ids = [str(v).strip() for v in df["id"].tolist() if str(v).strip()]

    log("")
    log("=" * 70)
    log("[PHASE 2] FETCH LIVE STOCK BY ID")
    log("=" * 70)

    fetch_progress = None
    fetch_label = None
    if output_widget:
        fetch_progress = widgets.IntProgress(value=0, min=0, max=max(len(ids), 1), bar_style="info", layout=widgets.Layout(width="500px"))
        fetch_label = widgets.HTML(value="<b>Fetching live stock: 0</b>")
        with output_widget:
            display(widgets.HBox([fetch_progress, fetch_label]))

    def on_fetch(index, total, stock_id, found):
        if fetch_progress is not None:
            fetch_progress.value = index
            fetch_label.value = f"<b>Fetched {index}/{total}: {stock_id} ({'found' if found else 'missing'})</b>"

    live_rows = client.fetch_stock_by_ids(ids, progress_callback=on_fetch)
    if fetch_progress is not None:
        fetch_progress.bar_style = "success"
        fetch_label.value = f"<b>Live fetch complete: {len(live_rows)} rows found</b>"

    log("")
    log("=" * 70)
    log("[PHASE 3] DETECT CHANGES AND UPDATE")
    log("=" * 70)

    result_records = []
    success_count = 0
    failed_count = 0
    skipped_count = 0
    changed_count = 0

    update_progress = None
    update_label = None
    if output_widget:
        update_progress = widgets.IntProgress(value=0, min=0, max=max(len(df), 1), bar_style="info", layout=widgets.Layout(width="500px"))
        update_label = widgets.HTML(value="<b>Updating rows: 0</b>")
        with output_widget:
            display(widgets.HBox([update_progress, update_label]))

    for index, row in df.iterrows():
        stock_id = str(row.get("id", "")).strip()
        uploaded_qty = _safe_number(row.get("quantity"))
        current_stock = live_rows.get(stock_id)

        record = row.to_dict()
        record["current_api_quantity"] = current_stock.get("quantity") if current_stock else None
        record["is_changed"] = False
        record["update_status"] = "SKIPPED"
        record["update_message"] = ""

        if not current_stock:
            failed_count += 1
            record["update_status"] = "FAILED"
            record["update_message"] = "Stock id not found in API"
        elif uploaded_qty is None:
            failed_count += 1
            record["update_status"] = "FAILED"
            record["update_message"] = "Uploaded quantity is empty or invalid"
        else:
            current_qty = _safe_number(current_stock.get("quantity"))
            is_changed = current_qty != uploaded_qty
            record["is_changed"] = bool(is_changed)

            if not is_changed:
                skipped_count += 1
                record["update_status"] = "SKIPPED"
                record["update_message"] = "Quantity unchanged"
            else:
                changed_count += 1
                stock_payload = dict(current_stock)
                stock_payload["quantity"] = int(uploaded_qty) if float(uploaded_qty).is_integer() else uploaded_qty
                try:
                    response = client.update_stock(stock_payload)
                    success_count += 1
                    record["update_status"] = "SUCCESS"
                    record["update_message"] = str(response)
                except Exception as exc:
                    failed_count += 1
                    record["update_status"] = "FAILED"
                    record["update_message"] = _extract_error_message(exc)

        result_records.append(record)

        if update_progress is not None:
            update_progress.value = index + 1
            update_label.value = f"<b>Processed {index + 1}/{len(df)} rows</b>"

    if update_progress is not None:
        update_progress.bar_style = "success"
        update_label.value = f"<b>Update complete: {len(df)}/{len(df)} rows</b>"

    result_df = pd.DataFrame(result_records)
    result_df.to_excel(result_path, index=False)

    log(f"[SAVED] {result_path}")
    log(f"[SUMMARY] Total rows: {len(result_df)}")
    log(f"[SUMMARY] Changed rows: {changed_count}")
    log(f"[SUMMARY] Updated successfully: {success_count}")
    log(f"[SUMMARY] Failed: {failed_count}")
    log(f"[SUMMARY] Skipped: {skipped_count}")

    return {
        "status": "SUCCESS",
        "mode": "update",
        "total_rows": len(result_df),
        "changed_rows": changed_count,
        "success_count": success_count,
        "failed_count": failed_count,
        "skipped_count": skipped_count,
        "output_dir": output_dir,
        "output_dir_relpath": os.path.relpath(output_dir, notebook_root).replace("\\", "/"),
        "report_path": result_path,
        "report_relpath": os.path.relpath(result_path, notebook_root).replace("\\", "/"),
        "status_label": (
            f"<h3 style='color: green;'>Update complete! Success {success_count}, "
            f"Failed {failed_count}, Skipped {skipped_count}.</h3>"
        ),
    }
