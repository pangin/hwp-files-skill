# -*- coding: utf-8 -*-
"""Build a synthetic HWPX form for regression-testing fill_hwpx.py.

Covers: plain / repeated / table-cell placeholders, and a placeholder split
across two runs (simulating Hancom's edit-history run splitting).

Usage:
    python tests/make_fill_fixture.py [OUT.hwpx]
    python scripts/fill_hwpx.py OUT.hwpx --mode scan     # expect 6 keys
"""
import contextlib
import io
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")

from hwpx.document import HwpxDocument

out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "fixture_form.hwpx")

chatter = io.StringIO()
with contextlib.redirect_stdout(chatter), contextlib.redirect_stderr(chatter):
    doc = HwpxDocument.new()
    doc.add_paragraph("고객사: {{고객사}} / 담당자: {{담당자}}")
    doc.add_paragraph("사업명은 {{사업명}}이며, 다시 한번 {{사업명}}이라 한다.")
    t = doc.add_table(2, 2)
    t.set_cell_text(0, 0, "설치 장소")
    t.set_cell_text(0, 1, "{{설치장소}}")
    t.set_cell_text(1, 0, "비고")
    t.set_cell_text(1, 1, "특이사항: {{비고}}")
    # split-run placeholder: {{성 + 명}} across two differently-styled runs
    p = doc.add_paragraph("", include_run=False)
    p.add_run("확인자 성명: {{성")
    p.add_run("명}} (인)", bold=True)
    doc.save_to_path(out)

print("fixture saved:", out)
print("expected placeholders: 고객사, 담당자, 사업명(x2), 설치장소(표), 비고(표), 성명(run 분절)")
