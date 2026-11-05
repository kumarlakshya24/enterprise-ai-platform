"""Generate the sample PDF documents (with real headings and a table) used by the corpus.

Run: python scripts/make_sample_pdfs.py
PDF metadata lives in a sidecar `<file>.meta.yaml`, which is how the ingestion
pipeline attaches team / visibility / version to formats without front-matter.
"""

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

ROOT = Path(__file__).resolve().parents[1] / "data" / "sample_docs"
styles = getSampleStyleSheet()


def build(path: Path, title: str, sections: list, meta: str) -> None:
    story = [Paragraph(title, styles["Title"]), Spacer(1, 12)]
    for heading, items in sections:
        story.append(Paragraph(heading, styles["Heading2"]))
        for item in items:
            if isinstance(item, list):  # table
                t = Table(item, hAlign="LEFT")
                t.setStyle(
                    TableStyle(
                        [
                            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                            ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                        ]
                    )
                )
                story += [t, Spacer(1, 8)]
            else:
                story += [Paragraph(item, styles["BodyText"]), Spacer(1, 6)]
    path.parent.mkdir(parents=True, exist_ok=True)
    SimpleDocTemplate(str(path), pagesize=LETTER, title=title).build(story)
    path.with_suffix(path.suffix + ".meta.yaml").write_text(meta)


build(
    ROOT / "security" / "security-incident-reporting.pdf",
    "Security Incident Reporting Procedure (SEC-PRO-007)",
    [
        (
            "Purpose",
            ["Every employee must report suspected security incidents so the Security team can contain them quickly."],
        ),
        (
            "How to Report",
            [
                "Report suspected incidents within 1 hour of discovery by emailing security@lumen-analytics.com or calling the security hotline at extension 7233.",
                "To report a phishing email, use the Report Phish button in Outlook. Do not forward the suspicious email to colleagues.",
            ],
        ),
        (
            "Response Targets",
            [
                [
                    ["Incident type", "Example", "Security response time"],
                    ["Critical", "Ransomware, active intrusion", "15 minutes"],
                    ["High", "Lost laptop, leaked credentials", "1 hour"],
                    ["Medium", "Phishing email reported", "4 hours"],
                    ["Low", "Policy question", "2 business days"],
                ]
            ],
        ),
        (
            "After Reporting",
            [
                "Do not attempt to investigate on your own. Keep the affected device powered on and disconnected from the network until Security contacts you."
            ],
        ),
    ],
    'doc_id: sec-incident-reporting\nteam: security\ndoc_type: procedure\nversion: "2.0"\nupdated: 2026-04-22\nvisibility: public\naudience: [all]\n',
)

build(
    ROOT / "company" / "code-of-conduct.pdf",
    "Code of Business Conduct (HR-POL-001)",
    [
        (
            "Gifts and Entertainment",
            [
                "Employees may accept gifts from vendors or customers with a value of up to $100 per year per business relationship. Gifts above $100 must be declined or reported to Legal.",
                "Cash and cash equivalents, such as gift cards, may never be accepted.",
            ],
        ),
        (
            "Conflicts of Interest",
            [
                "Employees must disclose potential conflicts of interest in the annual conflict-of-interest declaration in Workday every January."
            ],
        ),
        (
            "Speaking Up",
            [
                "Concerns can be raised anonymously through the Ethics Hotline at ethics.lumen-analytics.com. Retaliation against anyone who raises a concern in good faith is prohibited."
            ],
        ),
    ],
    'doc_id: hr-code-of-conduct\nteam: hr\ndoc_type: policy\nversion: "3.0"\nupdated: 2025-07-01\nvisibility: public\naudience: [all]\n',
)
print("PDFs written")
