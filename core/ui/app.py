"""
Interactive widget app for stock enrichment.
"""

import glob
import os
from datetime import datetime

import ipywidgets as widgets
from IPython.display import HTML, clear_output, display

from core.config import load_app_config
from core.utils.processor import ensure_uploads_dir, process_stock_report, process_stock_update


class StockEnrichmentApp:
    """Notebook widget UI for generating the stock enrichment report."""

    def __init__(self, config_path=None):
        self.summary_data = None
        self.config_path = config_path
        self.config = load_app_config(config_path)
        self._build_widgets()

    def _build_widgets(self):
        self.base_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        ensure_uploads_dir(self.base_dir)

        self.start_date_input = widgets.Text(
            value=self._format_display_date(self.config.get("report_min_date", "")),
            description="Start Date:",
            placeholder="DD-MM-YY or DD-MM-YYYY",
            style={"description_width": "260px"},
            layout=widgets.Layout(width="380px"),
        )
        self.end_date_input = widgets.Text(
            value=self._format_display_date(self.config.get("report_max_date", "")),
            description="End Date:",
            placeholder="DD-MM-YY or DD-MM-YYYY",
            style={"description_width": "260px"},
            layout=widgets.Layout(width="380px"),
        )
        self.generate_button = widgets.Button(
            description=" Generate Excel",
            button_style="primary",
            icon="play",
            layout=widgets.Layout(width="250px", height="50px"),
        )
        self.generate_button.on_click(self._on_generate_click)
        self.generate_download = widgets.Output()
        self.generate_output = widgets.Output()

        self.file_dropdown = widgets.Dropdown(
            options=[("-- Click Refresh to scan uploads --", "")],
            value="",
            description="Update File:",
            style={"description_width": "140px"},
            layout=widgets.Layout(width="600px"),
        )
        self.refresh_button = widgets.Button(
            description="Refresh Uploads",
            button_style="info",
            icon="refresh",
            layout=widgets.Layout(width="150px"),
        )
        self.refresh_button.on_click(self._refresh_file_list)
        self.update_button = widgets.Button(
            description=" Ingestion / Update",
            button_style="warning",
            icon="upload",
            layout=widgets.Layout(width="250px", height="50px"),
        )
        self.update_button.on_click(self._on_update_click)
        self.update_download = widgets.Output()
        self.update_output = widgets.Output()

        self.generate_status_label = widgets.HTML(
            value="<h3 style='color: #3498DB;'>Cell 2 ready. Generate directly from Elasticsearch using the date range.</h3>"
        )
        self.update_status_label = widgets.HTML(
            value="<h3 style='color: #3498DB;'>Cell 3 ready. Select an edited Excel/CSV, then run update.</h3>"
        )
        self._refresh_file_list()

    def _build_download_html(self, path, label, relpath=None):
        relpath = (relpath or os.path.relpath(path, self.base_dir)).replace("\\", "/")
        name = os.path.basename(path)
        return (
            f"<a href='{relpath}' download='{name}' "
            "style='display:inline-block;padding:10px 16px;background-color:#2E86C1;"
            "color:white;text-decoration:none;border-radius:6px;font-weight:bold;'>"
            f"{label}: {name}</a>"
        )

    def _build_config_html(self):
        rows = [
            ("Tenant ID", self.config.get("tenant_id", "")),
            ("Update URL", self.config.get("update_url", "")),
            ("Elastic URL", self.config.get("elastic_url", "")),
            ("Scroll API", self.config.get("elastic_scroll_api", "")),
            ("Date Field", self.config.get("elastic_date_field", "")),
            ("Start Date", self._format_display_date(self.config.get("report_min_date", ""))),
            ("End Date", self._format_display_date(self.config.get("report_max_date", ""))),
        ]
        items = "".join(
            f"<tr><td style='padding:4px 12px 4px 0; font-weight:bold;'>{label}</td><td style='padding:4px 0;'>{value}</td></tr>"
            for label, value in rows
        )
        return (
            "<div style='padding:12px 16px; border:1px solid #d9e2f2; border-radius:8px; background:#f8fbff; margin-bottom:12px;'>"
            "<div style='font-weight:bold; margin-bottom:8px;'>Loaded from config.json</div>"
            f"<table>{items}</table>"
            "</div>"
        )

    def _format_display_date(self, value):
        text = str(value or "").strip()
        if not text:
            return ""
        for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S.%fZ"):
            try:
                return datetime.strptime(text, fmt).strftime("%d-%m-%Y")
            except ValueError:
                continue
        return text

    def _parse_user_date(self, value):
        text = str(value or "").strip()
        formats = ("%d-%m-%y", "%d-%m-%Y", "%Y-%m-%d")
        for fmt in formats:
            try:
                return datetime.strptime(text, fmt).date()
            except ValueError:
                continue
        raise ValueError(f"Unsupported date format: {value}. Use DD-MM-YY, DD-MM-YYYY, or YYYY-MM-DD.")

    def _validate_date_inputs(self):
        start_date = self.start_date_input.value.strip()
        end_date = self.end_date_input.value.strip()
        min_date = self.config.get("report_min_date", "").strip()
        max_date = self.config.get("report_max_date", "").strip()

        if not start_date or not end_date:
            raise ValueError("Start Date and End Date are required.")

        start_value = self._parse_user_date(start_date)
        end_value = self._parse_user_date(end_date)
        if start_value > end_value:
            raise ValueError("Start Date cannot be after End Date.")

        if min_date:
            min_value = datetime.strptime(min_date, "%Y-%m-%d").date()
            if start_value < min_value or end_value < min_value:
                raise ValueError(f"Dates must be on or after {min_date}.")

        if max_date:
            max_value = datetime.strptime(max_date, "%Y-%m-%d").date()
            if start_value > max_value or end_value > max_value:
                raise ValueError(f"Dates must be on or before {max_date}.")

        return start_value.strftime("%Y-%m-%d"), end_value.strftime("%Y-%m-%d")

    def _on_generate_click(self, b):
        with self.generate_output:
            clear_output()

        try:
            start_date, end_date = self._validate_date_inputs()
        except Exception as exc:
            self.generate_status_label.value = f"<h3 style='color: red;'>Generation failed: {exc}</h3>"
            return

        self.generate_button.disabled = True
        with self.generate_download:
            clear_output()
        self.generate_status_label.value = "<h3 style='color: orange;'>Generating report from Elasticsearch...</h3>"

        def log(message):
            return None

        try:
            self.summary_data = process_stock_report(
                start_date=start_date,
                end_date=end_date,
                log=log,
                output_widget=self.generate_output,
                config_path=self.config_path,
            )
            self.generate_status_label.value = self.summary_data["status_label"]
            with self.generate_download:
                clear_output()
                display(HTML(self._build_download_html(
                    self.summary_data["report_path"],
                    "Download generated report",
                    relpath=self.summary_data.get("report_relpath"),
                )))
        except Exception as exc:
            self.generate_status_label.value = f"<h3 style='color: red;'>Generation failed: {exc}</h3>"
        finally:
            self.generate_button.disabled = False

    def _refresh_file_list(self, b=None):
        uploads_dir = os.path.join(self.base_dir, "uploads")
        upload_files = sorted(
            set(glob.glob(os.path.join(uploads_dir, "*.csv"))) |
            set(glob.glob(os.path.join(uploads_dir, "*.xlsx")))
        )
        if upload_files:
            self.file_dropdown.options = [("-- Select an upload file --", "")] + [
                (os.path.basename(f), f) for f in upload_files
            ]
        else:
            self.file_dropdown.options = [("No upload files found", "")]
        self.file_dropdown.value = ""

    def _on_update_click(self, b):
        with self.update_output:
            clear_output()

        input_path = self.file_dropdown.value
        if not input_path:
            self.update_status_label.value = (
                "<h3 style='color: red;'>Select a file from uploads/ before running update.</h3>"
            )
            return

        csv_path = os.path.abspath(input_path)
        if not os.path.exists(csv_path):
            self.update_status_label.value = f"<h3 style='color: red;'>File not found: {input_path}</h3>"
            return

        self.update_button.disabled = True
        with self.update_download:
            clear_output()
        self.update_status_label.value = "<h3 style='color: orange;'>Processing stock updates...</h3>"

        def log(message):
            return None

        try:
            self.summary_data = process_stock_update(
                csv_path=csv_path,
                log=log,
                output_widget=self.update_output,
                config_path=self.config_path,
            )
            self.update_status_label.value = self.summary_data["status_label"]
        except Exception as exc:
            self.update_status_label.value = f"<h3 style='color: red;'>Update failed: {exc}</h3>"
        finally:
            self.update_button.disabled = False

    def display_generation_section(self):
      
        
        display(
            widgets.VBox(
                [
                    self.start_date_input,
                    self.end_date_input,
                    self.generate_button,
                    self.generate_status_label,
                    self.generate_download,
                ]
            )
        )
        display(self.generate_output)
        print("\nGeneration section ready.")

    def display_update_section(self):
        display(HTML("<p style='color: #666;'>Place the edited CSV/XLSX in uploads/ and refresh the list.</p>"))
        display(widgets.HBox([self.file_dropdown, self.refresh_button]))
        display(self.update_status_label)
        display(self.update_button)
        display(self.update_output)
        print("\nUpdate section ready.")

    def display(self):
        self.display_generation_section()
        self.display_update_section()
