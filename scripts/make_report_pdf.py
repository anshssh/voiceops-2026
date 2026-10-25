#!/usr/bin/env python3
"""Render report.md to report.pdf (simple Markdown -> PDF via reportlab)."""
import os
import re
import sys

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (Paragraph, SimpleDocTemplate, Spacer,
                                Table, TableStyle)
from reportlab.lib import colors

ROOT = os.path.join(os.path.dirname(__file__), "..")


def inline(text: str) -> str:
    text = text.replace("&", "&amp;")
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"`([^`]+)`", r"<font face='Courier' size='8'>\1</font>", text)
    return text


def main():
    src = open(os.path.join(ROOT, "report.md"), encoding="utf-8").read()
    styles = getSampleStyleSheet()
    body = ParagraphStyle("body", parent=styles["BodyText"], fontSize=9.5,
                          leading=13.5, spaceAfter=5)
    h1 = ParagraphStyle("h1", parent=styles["Title"], fontSize=16, leading=19)
    h2 = ParagraphStyle("h2", parent=styles["Heading2"], fontSize=12,
                        leading=15, spaceBefore=8, spaceAfter=4)
    story = []
    lines = src.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].rstrip()
        if line.startswith("|") and i + 1 < len(lines) and lines[i + 1].startswith("| ---"):
            rows = []
            while i < len(lines) and lines[i].startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                if not all(set(c) <= set("-: ") for c in cells):
                    rows.append([Paragraph(inline(c), body) for c in cells])
                i += 1
            table = Table(rows, hAlign="LEFT")
            table.setStyle(TableStyle([
                ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eeeeee")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]))
            story.append(table)
            story.append(Spacer(1, 4))
            continue
        if not line:
            i += 1
            continue
        if line.startswith("# "):
            story.append(Paragraph(inline(line[2:]), h1))
        elif line.startswith("## "):
            story.append(Paragraph(inline(line[3:]), h2))
        elif line.startswith("- "):
            story.append(Paragraph(inline(line), body))
        else:
            # join wrapped paragraph lines
            para = [line]
            while i + 1 < len(lines) and lines[i + 1].strip() and \
                    not lines[i + 1].startswith(("#", "- ", "|")):
                i += 1
                para.append(lines[i].rstrip())
            story.append(Paragraph(inline(" ".join(para)), body))
        i += 1
    out = os.path.join(ROOT, "report.pdf")
    SimpleDocTemplate(out, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm,
                      topMargin=16 * mm, bottomMargin=16 * mm).build(story)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
