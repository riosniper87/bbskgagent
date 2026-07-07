"""Rasterize Excel sheets to PNG via Excel COM (Windows).

Mirrors the PowerPoint COM pattern in pptx.py. Large used ranges are tiled so
each PNG stays within readable bounds for the VLM.
"""
from __future__ import annotations

import logging
import os
import time
from pathlib import Path

log = logging.getLogger(__name__)

MAX_SHEETS = 8
MAX_COLS_PER_TILE = 80
MAX_ROWS_PER_TILE = 120
EXPORT_WIDTH = 1280
SHEET_TIMEOUT_SEC = 90

_xl_app = None

# Excel constants
XL_SCREEN = 1
XL_PICTURE = 2
XL_TYPE_PDF = 0


def _get_excel_app():
    global _xl_app
    if _xl_app is not None:
        try:
            _ = _xl_app.Workbooks.Count
            return _xl_app
        except Exception:
            _xl_app = None
    import win32com.client

    app = win32com.client.Dispatch("Excel.Application")
    try:
        app.DisplayAlerts = False
        app.Visible = False
        app.ScreenUpdating = False
    except Exception:
        pass
    _xl_app = app
    return app


def cleanup_excel_app():
    global _xl_app
    if _xl_app is not None:
        try:
            _xl_app.Quit()
        except Exception:
            pass
        _xl_app = None


def _safe_sheet_name(name: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in name)[:40]


def _export_range_as_png(sheet, rng, out_path: str) -> bool:
    """Copy a range as picture and export via a temporary chart object."""
    chart_obj = None
    try:
        rng.CopyPicture(Appearance=XL_SCREEN, Format=XL_PICTURE)
        width = max(float(rng.Width), 100)
        height = max(float(rng.Height), 80)
        chart_obj = sheet.ChartObjects().Add(0, 0, width, height)
        chart_obj.Chart.Paste()
        chart_obj.Chart.Export(str(Path(out_path).resolve()), "PNG")
        return os.path.isfile(out_path)
    except Exception as exc:
        log.debug("range export failed: %s", exc)
        return False
    finally:
        if chart_obj is not None:
            try:
                chart_obj.Delete()
            except Exception:
                pass


def _tile_ranges(used, max_rows: int, max_cols: int):
    """Yield (row_off, col_off, Range) sub-ranges within UsedRange (1-based)."""
    start_row = used.Row
    start_col = used.Column
    nrows = used.Rows.Count
    ncols = used.Columns.Count
    for r0 in range(0, nrows, max_rows):
        for c0 in range(0, ncols, max_cols):
            r1 = min(r0 + max_rows, nrows)
            c1 = min(c0 + max_cols, ncols)
            abs_r1 = start_row + r0
            abs_c1 = start_col + c0
            abs_r2 = start_row + r1 - 1
            abs_c2 = start_col + c1 - 1
            yield r0, c0, sheet_range(used.Parent, abs_r1, abs_c1, abs_r2, abs_c2)


def sheet_range(sheet, r1, c1, r2, c2):
    return sheet.Range(sheet.Cells(r1, c1), sheet.Cells(r2, c2))


def rasterize_workbook(
    xlsx_path: str,
    workdir: str,
    att_id: str,
) -> list[tuple[str, str]]:
    """Return [(png_path, source_ref), ...] for each sheet (and tile if needed)."""
    app = _get_excel_app()
    abs_path = str(Path(xlsx_path).resolve())
    wb = app.Workbooks.Open(abs_path, ReadOnly=True, UpdateLinks=0)
    images: list[tuple[str, str]] = []
    deadline = time.monotonic() + SHEET_TIMEOUT_SEC * MAX_SHEETS
    try:
        count = min(wb.Worksheets.Count, MAX_SHEETS)
        for si in range(1, count + 1):
            if time.monotonic() > deadline:
                log.warning("excel rasterize timeout for %s", xlsx_path)
                break
            sheet = wb.Worksheets(si)
            sheet_name = str(sheet.Name)
            safe = _safe_sheet_name(sheet_name)
            try:
                used = sheet.UsedRange
                if used is None or used.Rows.Count < 1:
                    continue
            except Exception:
                continue

            nrows = used.Rows.Count
            ncols = used.Columns.Count
            needs_tile = nrows > MAX_ROWS_PER_TILE or ncols > MAX_COLS_PER_TILE

            if not needs_tile:
                ref = f"{att_id}#{sheet_name}"
                out = os.path.join(workdir, f"{att_id}_{safe}.png")
                if _export_range_as_png(sheet, used, out):
                    images.append((out, ref))
                continue

            tile_idx = 0
            for _, _, sub in _tile_ranges(used, MAX_ROWS_PER_TILE, MAX_COLS_PER_TILE):
                if time.monotonic() > deadline:
                    log.warning("excel rasterize timeout for %s", xlsx_path)
                    break
                ref = f"{att_id}#{sheet_name}_t{tile_idx}"
                out = os.path.join(workdir, f"{att_id}_{safe}_t{tile_idx}.png")
                if _export_range_as_png(sheet, sub, out):
                    images.append((out, ref))
                tile_idx += 1
    finally:
        wb.Close(SaveChanges=False)
    return images


def _force_kill_excel_processes() -> None:
    import subprocess

    try:
        subprocess.run(
            ["taskkill", "/IM", "EXCEL.EXE", "/F"],
            capture_output=True,
            timeout=10,
            check=False,
        )
    except Exception:
        pass


def _rasterize_worker(
    xlsx_path: str,
    workdir: str,
    att_id: str,
    conn,
) -> None:
    try:
        images = rasterize_workbook(xlsx_path, workdir, att_id)
        conn.send(("ok", images))
    except Exception as exc:
        conn.send(("err", str(exc)))
    finally:
        cleanup_excel_app()
    conn.close()


def _rasterize_in_subprocess(
    xlsx_path: str,
    workdir: str,
    att_id: str,
) -> list[tuple[str, str]] | None:
    """Run COM rasterize isolated; return None on subprocess timeout."""
    import multiprocessing as mp

    timeout = SHEET_TIMEOUT_SEC * MAX_SHEETS + 60
    ctx = mp.get_context("spawn")
    parent_conn, child_conn = ctx.Pipe(duplex=False)
    proc = ctx.Process(
        target=_rasterize_worker,
        args=(xlsx_path, workdir, att_id, child_conn),
    )
    proc.start()
    child_conn.close()
    try:
        if parent_conn.poll(timeout):
            status, payload = parent_conn.recv()
            proc.join(10)
            if status == "ok":
                return payload
            log.warning("Excel COM rasterize failed for %s: %s", xlsx_path, payload)
            return []
    finally:
        parent_conn.close()
        if proc.is_alive():
            proc.terminate()
            proc.join(5)
            if proc.is_alive():
                proc.kill()
                proc.join(5)
            cleanup_excel_app()
            _force_kill_excel_processes()
    return None


def rasterize_or_empty(xlsx_path: str, workdir: str, att_id: str) -> list[tuple[str, str]]:
    lower = str(xlsx_path).lower()
    if not lower.endswith((".xlsx", ".xlsm", ".xls")):
        return []
    for attempt in range(2):
        result = _rasterize_in_subprocess(xlsx_path, workdir, att_id)
        if result is not None:
            return result
        log.warning(
            "Excel COM rasterize timeout for %s (attempt %d)",
            xlsx_path,
            attempt + 1,
        )
        cleanup_excel_app()
        _force_kill_excel_processes()
    return []
