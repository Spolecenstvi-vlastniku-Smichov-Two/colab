#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Sanitize Jupyter notebooks so they pass strict nbformat validation and GitHub preview.

- Ensures top-level nbformat fields.
- Coerces cell.id to string (or generates one).
- Ensures cell.source is a single string.
- Normalizes cell metadata (tags -> list[str], execution subkeys -> str).
- Normalizes code outputs (text fields -> str, traceback -> list[str]).
- Leaves code & markdown content intact.
- Optional: strip outputs if STRIP_OUTPUTS=true env is set.

Usage:
  python tools/sanitize_ipynb.py [--strip-outputs]  # sanitize all *.ipynb
"""
import os, sys, json, uuid, glob, argparse
from pathlib import Path

def to_s(x):
    if isinstance(x, str): return x
    if isinstance(x, list): return "".join(to_s(i) for i in x)
    return str(x)

def sanitize_notebook(path: Path, strip_outputs: bool=False) -> bool:
    raw = json.loads(path.read_text(encoding="utf-8"))
    changed = False

    # Top-level
    if raw.get("nbformat") != 4:
        raw["nbformat"] = 4; changed = True
    if not isinstance(raw.get("nbformat_minor"), int):
        raw["nbformat_minor"] = 5; changed = True
    md = raw.get("metadata")
    if not isinstance(md, dict):
        raw["metadata"] = {}; changed = True
        md = raw["metadata"]
    li = md.get("language_info")
    if not isinstance(li, dict):
        md["language_info"] = {"name": "python"}; changed = True
    else:
        if "name" not in li or not isinstance(li["name"], str):
            li["name"] = "python"; changed = True
    # kernelspec (helps some viewers)
    ks = md.get("kernelspec")
    if not isinstance(ks, dict):
        md["kernelspec"] = {"name": "python3", "display_name": "Python 3"}; changed = True
    else:
        if ks.get("name") is None: ks["name"] = "python3"; changed = True
        if ks.get("display_name") is None: ks["display_name"] = "Python 3"; changed = True

    # Cells
    cells = raw.get("cells")
    if not isinstance(cells, list):
        raw["cells"] = []; changed = True
        cells = raw["cells"]

    for c in cells:
        # id must be a string
        cid = c.get("id")
        if cid is None or not isinstance(cid, str) or not cid:
            c["id"] = uuid.uuid4().hex[:8]; changed = True

        # source must be a single string
        if "source" in c and not isinstance(c["source"], str):
            c["source"] = to_s(c["source"]); changed = True

        # metadata must be dict
        if not isinstance(c.get("metadata", {}), dict):
            c["metadata"] = {}; changed = True

        # metadata.tags -> list[str]
        tags = c["metadata"].get("tags")
        if isinstance(tags, list):
            new_tags = [to_s(t) for t in tags if t is not None]
            if new_tags != tags:
                c["metadata"]["tags"] = new_tags; changed = True

        # metadata.execution.* -> strings (fixes "0 is not of type 'string'")
        exec_md = c["metadata"].get("execution")
        if isinstance(exec_md, dict):
            for k, v in list(exec_md.items()):
                if not isinstance(v, str):
                    exec_md[k] = to_s(v); changed = True

        # attachments on markdown/raw must be dict
        if c.get("cell_type") in ("markdown", "raw") and "attachments" in c and not isinstance(c["attachments"], dict):
            c["attachments"] = {}; changed = True

        # code outputs
        if c.get("cell_type") == "code":
            if strip_outputs:
                if c.get("outputs"): changed = True
                c["outputs"] = []
                if c.get("execution_count") is not None:
                    c["execution_count"] = None; changed = True
            else:
                outs = c.get("outputs") or []
                if not isinstance(outs, list): outs = []; c["outputs"] = outs; changed = True
                for o in outs:
                    if not isinstance(o.get("metadata", {}), dict):
                        o["metadata"] = {}; changed = True
                    ot = o.get("output_type")

                    if ot == "stream":
                        if "text" in o and not isinstance(o["text"], str):
                            o["text"] = to_s(o["text"]); changed = True
                        if "name" in o and not isinstance(o["name"], str):
                            o["name"] = to_s(o["name"]); changed = True

                    elif ot in ("display_data", "execute_result"):
                        data = o.get("data") or {}
                        if not isinstance(data, dict):
                            o["data"] = {}; changed = True
                            data = o["data"]
                        for k, v in list(data.items()):
                            if k.startswith("text/") or k == "text/plain" or k.startswith("image/"):
                                if not isinstance(v, str):
                                    data[k] = to_s(v); changed = True
                            else:
                                # for non-text mimetypes, keep dict/list; coerce other scalars
                                if not isinstance(v, (dict, list, str)):
                                    data[k] = to_s(v); changed = True
                        if ot == "execute_result":
                            # optional field; if present must be int or null
                            ec = o.get("execution_count")
                            if ec is not None and not isinstance(ec, int):
                                o["execution_count"] = None; changed = True

                    elif ot == "error":
                        if "traceback" in o:
                            tb = o["traceback"]
                            if isinstance(tb, list):
                                new_tb = [to_s(t) for t in tb]
                            else:
                                new_tb = [to_s(tb)]
                            if new_tb != tb:
                                o["traceback"] = new_tb; changed = True
                        for fld in ("ename", "evalue"):
                            if fld in o and not isinstance(o[fld], str):
                                o[fld] = to_s(o[fld]); changed = True

                # execution_count on cell
                ec = c.get("execution_count")
                if ec is not None and not isinstance(ec, int):
                    c["execution_count"] = None; changed = True

    if changed:
        path.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
    return changed

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--strip-outputs", action="store_true", help="Remove all code outputs for lighter diffs and bulletproof preview.")
    args = ap.parse_args()

    strip = args.strip_outputs or os.getenv("STRIP_OUTPUTS", "false").lower() in ("1","true","yes")

    # Find notebooks (skip checkpoints)
    files = [Path(p) for p in glob.glob("**/*.ipynb", recursive=True) if ".ipynb_checkpoints" not in p]
    changed_any = False
    for path in files:
        if sanitize_notebook(path, strip_outputs=strip):
            print(f"Sanitized: {path}")
            changed_any = True

    if changed_any:
        sys.exit(2)  # signal "changes made"
    print("All notebooks already clean.")
    return 0

if __name__ == "__main__":
    sys.exit(main())
