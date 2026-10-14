# -*- coding: utf-8 -*-
"""Sinh index.html ở gốc repo cho GitHub Pages từ web/index.html (bản nguồn, không có <head>).
Chạy: python web/build_pages.py  → ghi ../index.html với RAW_BASE = "data/" (đọc JSON cùng repo, cùng origin)."""
import pathlib
import re

here = pathlib.Path(__file__).resolve().parent
src = (here / "index.html").read_text(encoding="utf-8")
src, n1 = re.subn(r'const RAW_BASE = "[^"]*";', 'const RAW_BASE = "data/";', src, count=1)
assert n1 == 1, "không thấy RAW_BASE"
out = ('<!doctype html>\n<html lang="vi">\n<head>\n<meta charset="utf-8">\n'
       '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">\n'
       '<style>:root{color-scheme:light dark}body{margin:0;font:14px system-ui,sans-serif}img{max-width:100%}[hidden]{display:none!important}</style>\n'
       '</head>\n<body>\n' + src + '\n</body>\n</html>\n')
(here.parent / "index.html").write_text(out, encoding="utf-8")
print("ghi", here.parent / "index.html", len(out), "bytes")
