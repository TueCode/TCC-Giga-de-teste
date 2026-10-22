# -*- coding: utf-8 -*-
from tkinter import ttk

def setup_style(root):
    try: root.call("tk", "scaling", 1.15)
    except Exception: pass
    style = ttk.Style(root)
    try:
        if "clam" in style.theme_names(): style.theme_use("clam")
    except Exception: pass
    style.configure(".", font=("Segoe UI", 10))
    style.configure("TButton", padding=(12,6))
    style.configure("TLabelframe", padding=(12,8))
    style.configure("TLabelframe.Label", font=("Segoe UI", 10, "bold"))
    style.configure("Form.TLabel", anchor="e")
