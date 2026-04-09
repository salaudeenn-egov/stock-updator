"""
Summary rendering helpers for stock enrichment.
"""

import os
from IPython.display import display, HTML


def render_summary(summary_data):
    """Display a summary card and download link for the generated report."""
    if not summary_data:
        print("No report generated yet. Run the generation cell first.")
        return

    report_path = summary_data["report_path"]
    report_relpath = summary_data.get("report_relpath", report_path)
    report_name = os.path.basename(report_path)

    if summary_data.get("mode") == "update":
        display(
            HTML(
                f"""
                <div style="font-family: Arial, sans-serif; padding: 20px; border: 2px solid #f0ad4e; border-radius: 10px; background-color: #fcf8e3; margin: 20px 0;">
                    <h2 style="color: #8a6d3b; margin-top: 0;">Stock Update Result</h2>
                    <p><b>Total rows:</b> {summary_data['total_rows']}</p>
                    <p><b>Changed rows:</b> {summary_data['changed_rows']}</p>
                    <p><b>Updated successfully:</b> {summary_data['success_count']}</p>
                    <p><b>Failed:</b> {summary_data['failed_count']}</p>
                    <p><b>Skipped:</b> {summary_data['skipped_count']}</p>
                    <p><b>Output folder:</b> {summary_data.get('output_dir_relpath', summary_data['output_dir'])}</p>
                    <a href="{report_relpath}" download="{report_name}"
                       style="display: inline-block; padding: 10px 20px; background-color: #f0ad4e; color: white;
                              text-decoration: none; border-radius: 5px; font-weight: bold; font-size: 14px;">
                        Download {report_name}
                    </a>
                </div>
                """
            )
        )
        return

    display(
        HTML(
            f"""
            <div style="font-family: Arial, sans-serif; padding: 20px; border: 2px solid #007bff; border-radius: 10px; background-color: #f8f9fa; margin: 20px 0;">
                <h2 style="color: #007bff; margin-top: 0;">Stock  Report</h2>
                <p><b>Total rows:</b> {summary_data['total_rows']}</p>
                <p><b>Elastic matched:</b> {summary_data['matched_rows']}</p>
                <p><b>Elastic unmatched:</b> {summary_data['unmatched_rows']}</p>
                <p><b>Output folder:</b> {summary_data.get('output_dir_relpath', summary_data['output_dir'])}</p>
                <a href="{report_relpath}" download="{report_name}"
                   style="display: inline-block; padding: 10px 20px; background-color: #007bff; color: white;
                          text-decoration: none; border-radius: 5px; font-weight: bold; font-size: 14px;">
                    Download {report_name}
                </a>
            </div>
            """
        )
    )
