"""Streamlit JSON editor for `data/locations/` and `data/packs/`.

Run:
    pip install streamlit
    streamlit run scripts/data_editor.py
"""

from __future__ import annotations

import copy
import difflib
import json
from pathlib import Path
from typing import Any

import streamlit as st


ROOT = Path(__file__).resolve().parents[1]
TARGET_DIRS = [ROOT / "data" / "locations", ROOT / "data" / "packs"]


def _list_json_files() -> list[Path]:
    files: list[Path] = []
    for base in TARGET_DIRS:
        if base.exists():
            files.extend(sorted(base.rglob("*.json")))
    return files


def _relpath(path: Path) -> str:
    return str(path.relative_to(ROOT)).replace("\\", "/")


def _to_json_pointer_tokens(pointer: str) -> list[str]:
    p = str(pointer or "").strip()
    if p in ("", "/"):
        return []
    if not p.startswith("/"):
        raise ValueError("Pointer harus diawali '/'. Contoh: /district_graph/central")
    return [tok for tok in p.split("/")[1:]]


def _navigate(node: Any, tokens: list[str]) -> Any:
    cur = node
    for tok in tokens:
        if isinstance(cur, dict):
            if tok not in cur:
                raise KeyError(f"Key '{tok}' tidak ditemukan.")
            cur = cur[tok]
        elif isinstance(cur, list):
            if not tok.isdigit():
                raise KeyError(f"Index list harus angka, dapat '{tok}'.")
            idx = int(tok)
            if idx < 0 or idx >= len(cur):
                raise KeyError(f"Index {idx} di luar range list.")
            cur = cur[idx]
        else:
            raise KeyError("Path melewati node non-container.")
    return cur


def _navigate_parent(node: Any, tokens: list[str]) -> tuple[Any, str]:
    if not tokens:
        raise ValueError("Root tidak punya parent.")
    parent = _navigate(node, tokens[:-1])
    return parent, tokens[-1]


def _walk_schema(node: Any, pointer: str = "/") -> dict[str, str]:
    schema: dict[str, str] = {pointer: type(node).__name__}
    if isinstance(node, dict):
        for k, v in node.items():
            child_ptr = pointer.rstrip("/") + f"/{k}" if pointer != "/" else f"/{k}"
            schema.update(_walk_schema(v, child_ptr))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            child_ptr = pointer.rstrip("/") + f"/{i}" if pointer != "/" else f"/{i}"
            schema.update(_walk_schema(v, child_ptr))
    return schema


def _validate_type_compatibility(
    original: Any,
    edited: Any,
    pointer: str,
    *,
    allow_new_key: bool = False,
) -> tuple[bool, str]:
    schema = _walk_schema(original)
    expected = schema.get(pointer)
    if expected is None:
        if allow_new_key:
            return True, "Key baru (tidak ada skema historis), diperbolehkan."
        return False, f"Node '{pointer}' tidak ada di skema saat ini."
    got = type(edited).__name__
    if got != expected:
        return False, f"Tipe tidak cocok di '{pointer}': expected={expected}, got={got}"
    return True, "Tipe valid."


def _render_diff(before_obj: Any, after_obj: Any) -> str:
    before = json.dumps(before_obj, ensure_ascii=False, indent=2, sort_keys=True).splitlines()
    after = json.dumps(after_obj, ensure_ascii=False, indent=2, sort_keys=True).splitlines()
    diff = difflib.unified_diff(before, after, fromfile="before", tofile="after", lineterm="")
    return "\n".join(diff)


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _save_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _init_state(file_key: str, data: Any) -> None:
    st.session_state.setdefault(f"orig::{file_key}", copy.deepcopy(data))
    st.session_state.setdefault(f"work::{file_key}", copy.deepcopy(data))


def main() -> None:
    st.set_page_config(page_title="OMNI Data Editor", layout="wide")
    st.title("OMNI Internal Data Editor")
    st.caption("Editor JSON untuk data/locations dan data/packs (developer tool).")

    files = _list_json_files()
    if not files:
        st.error("Tidak ada file JSON pada data/locations atau data/packs.")
        return

    options = {_relpath(p): p for p in files}
    selected = st.sidebar.selectbox("Pilih file", list(options.keys()))
    selected_path = options[selected]
    file_key = selected

    try:
        current_disk = _load_json(selected_path)
    except Exception as exc:
        st.error(f"Gagal baca JSON: {exc}")
        return

    if st.sidebar.button("Reload dari disk"):
        st.session_state[f"orig::{file_key}"] = copy.deepcopy(current_disk)
        st.session_state[f"work::{file_key}"] = copy.deepcopy(current_disk)

    _init_state(file_key, current_disk)
    orig = st.session_state[f"orig::{file_key}"]
    work = st.session_state[f"work::{file_key}"]

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Current Working JSON")
        st.json(work, expanded=False)
    with col2:
        st.subheader("Tree/List")
        all_paths = sorted(_walk_schema(work).keys(), key=lambda x: (x.count("/"), x))
        st.dataframe({"path": all_paths}, use_container_width=True, hide_index=True)

    st.divider()
    st.subheader("Node Editor")
    mode = st.radio("Operation", ["Update node", "Add node", "Delete node"], horizontal=True)

    if mode == "Update node":
        ptr = st.text_input("JSON Pointer", value="/")
        raw = st.text_area("JSON value baru", value="{}", height=140)
        if st.button("Apply update"):
            try:
                tokens = _to_json_pointer_tokens(ptr)
                new_value = json.loads(raw)
                if not tokens:
                    ok, msg = _validate_type_compatibility(orig, new_value, "/", allow_new_key=False)
                    if not ok:
                        st.error(msg)
                    else:
                        st.session_state[f"work::{file_key}"] = new_value
                        st.success("Root berhasil di-update.")
                else:
                    parent, key = _navigate_parent(work, tokens)
                    full_ptr = "/" + "/".join(tokens)
                    ok, msg = _validate_type_compatibility(orig, new_value, full_ptr, allow_new_key=False)
                    if not ok:
                        st.error(msg)
                    else:
                        if isinstance(parent, dict):
                            parent[key] = new_value
                        elif isinstance(parent, list):
                            if not key.isdigit():
                                raise ValueError("Index list harus angka.")
                            parent[int(key)] = new_value
                        else:
                            raise ValueError("Parent node bukan dict/list.")
                        st.success("Node berhasil di-update.")
            except Exception as exc:
                st.error(f"Gagal update node: {exc}")

    elif mode == "Add node":
        parent_ptr = st.text_input("Parent JSON Pointer", value="/")
        key_input = st.text_input("Key (dict) atau index/list append pakai '+'", value="")
        raw = st.text_area("JSON value baru", value="{}", height=140)
        if st.button("Apply add"):
            try:
                tokens = _to_json_pointer_tokens(parent_ptr)
                parent = _navigate(work, tokens)
                val = json.loads(raw)
                if isinstance(parent, dict):
                    if not key_input:
                        raise ValueError("Key wajib untuk parent dict.")
                    target_ptr = parent_ptr.rstrip("/") + f"/{key_input}" if parent_ptr != "/" else f"/{key_input}"
                    allow_new = key_input not in parent
                    if (not allow_new) and not _validate_type_compatibility(orig, val, target_ptr)[0]:
                        ok, msg = _validate_type_compatibility(orig, val, target_ptr)
                        st.error(msg)
                    else:
                        parent[key_input] = val
                        st.success("Node berhasil ditambahkan/diubah.")
                elif isinstance(parent, list):
                    if key_input in ("", "+"):
                        parent.append(val)
                    else:
                        if not key_input.isdigit():
                            raise ValueError("Index list harus angka atau '+'.")
                        idx = int(key_input)
                        if idx < 0 or idx > len(parent):
                            raise ValueError("Index list di luar range insert.")
                        parent.insert(idx, val)
                    st.success("Item list berhasil ditambahkan.")
                else:
                    raise ValueError("Parent bukan dict/list.")
            except Exception as exc:
                st.error(f"Gagal add node: {exc}")

    else:
        ptr = st.text_input("JSON Pointer to delete", value="/")
        if st.button("Apply delete"):
            try:
                tokens = _to_json_pointer_tokens(ptr)
                if not tokens:
                    raise ValueError("Delete root tidak diizinkan.")
                parent, key = _navigate_parent(work, tokens)
                if isinstance(parent, dict):
                    if key not in parent:
                        raise KeyError("Key tidak ditemukan.")
                    del parent[key]
                elif isinstance(parent, list):
                    if not key.isdigit():
                        raise ValueError("Index list harus angka.")
                    idx = int(key)
                    if idx < 0 or idx >= len(parent):
                        raise IndexError("Index list di luar range.")
                    parent.pop(idx)
                else:
                    raise ValueError("Parent bukan dict/list.")
                st.success("Node berhasil dihapus.")
            except Exception as exc:
                st.error(f"Gagal delete node: {exc}")

    st.divider()
    st.subheader("Preview perubahan (sebelum overwrite)")
    diff_txt = _render_diff(orig, work)
    if diff_txt.strip():
        st.code(diff_txt, language="diff")
    else:
        st.info("Belum ada perubahan.")

    confirm = st.checkbox("Saya yakin overwrite file JSON asli.")
    if st.button("Save to file", type="primary", disabled=not confirm):
        try:
            # Final full-file parse/serialize check to avoid writing broken JSON.
            json.dumps(work)
            _save_json(selected_path, work)
            st.session_state[f"orig::{file_key}"] = copy.deepcopy(work)
            st.success(f"Tersimpan: {selected}")
        except Exception as exc:
            st.error(f"Gagal simpan: {exc}")


if __name__ == "__main__":
    main()
