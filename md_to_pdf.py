#!/usr/bin/env python3
"""마크다운 보고서를 PDF로 변환한다."""

import sys
from pathlib import Path

import markdown
from weasyprint import HTML

CSS = """
@page {
    size: A4;
    margin: 15mm;
}
body {
    font-family: "Noto Sans CJK KR", "Noto Sans KR", sans-serif;
    font-size: 9pt;
    line-height: 1.5;
    color: #1a1a1a;
}
h1 { font-size: 16pt; border-bottom: 2px solid #333; padding-bottom: 4px; }
h2 { font-size: 13pt; border-bottom: 1px solid #999; padding-bottom: 3px; margin-top: 14px; }
h3 { font-size: 11pt; margin-top: 10px; }
h4 { font-size: 10pt; margin-top: 8px; }
table {
    border-collapse: collapse;
    width: 100%;
    margin: 6px 0;
    font-size: 8pt;
}
th, td {
    border: 1px solid #ccc;
    padding: 3px 5px;
    text-align: left;
}
th { background: #f0f0f0; font-weight: bold; }
tr:nth-child(even) { background: #fafafa; }
blockquote {
    border-left: 3px solid #666;
    margin: 6px 0;
    padding: 4px 10px;
    background: #f9f9f9;
    font-size: 8.5pt;
}
code {
    background: #f0f0f0;
    padding: 1px 3px;
    border-radius: 2px;
    font-size: 8pt;
}
pre {
    background: #f5f5f5;
    padding: 6px;
    border-radius: 3px;
    font-size: 7.5pt;
    overflow-wrap: break-word;
    white-space: pre-wrap;
}
hr { border: none; border-top: 1px solid #ccc; margin: 8px 0; }
p { margin: 3px 0; }
ul, ol { margin: 3px 0; padding-left: 18px; }
"""


def convert(md_file, pdf_file=None):
    md_text = Path(md_file).read_text(encoding="utf-8")

    html_body = markdown.markdown(
        md_text,
        extensions=["tables", "fenced_code", "toc"],
    )

    html = f"""<!DOCTYPE html>
<html><head>
<meta charset="utf-8">
<style>{CSS}</style>
</head><body>{html_body}</body></html>"""

    if not pdf_file:
        pdf_file = str(Path(md_file).with_suffix(".pdf"))

    HTML(string=html).write_pdf(pdf_file)
    return pdf_file


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: md_to_pdf.py <report.md> [output.pdf]")
        sys.exit(1)

    md_file = sys.argv[1]
    pdf_file = sys.argv[2] if len(sys.argv) > 2 else None
    result = convert(md_file, pdf_file)
    print(result)
