"""Import and immutable versions for wide monitoring time series."""

import csv
import io
import math
import re
import uuid
import zipfile
from pathlib import Path
from xml.etree.ElementTree import ParseError

import numpy as np
import pandas as pd
from openpyxl import load_workbook
from openpyxl.utils.exceptions import InvalidFileException

from . import storage

MAX_BYTES = 20 * 1024 * 1024
MAX_ROWS = 100_000
MAX_COLUMNS = 256
MAX_CHANNELS = 32
TYPES = {"挠度", "应变", "位移", "温度", "倾角", "其他"}


def upload_path(token):
    if not re.fullmatch(r"[0-9a-f]{32}", token):
        raise KeyError(token)
    return storage.DATA / "monitor_uploads" / token


def table(content, name, sheet=None, preview=False):
    """Read headers and physical rows, preserving blank and malformed values."""
    if name.lower().endswith(".csv"):
        for encoding in ("utf-8-sig", "gb18030"):
            try:
                decoded = content.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        else:
            raise ValueError("CSV 编码无法识别，请使用 UTF-8 或 GB18030")
        try:
            return read_rows(
                csv.reader(io.StringIO(decoded, newline=""), strict=True), preview
            ), []
        except csv.Error as exc:
            raise ValueError("CSV 无法读取，请检查逗号分隔与引号") from exc
    workbook = open_xlsx(content)
    try:
        sheets = workbook.sheetnames
        if sheet and sheet not in sheets:
            raise ValueError("工作表不存在")
        ws = workbook[sheet or sheets[0]]
        if ws.max_column and ws.max_column > MAX_COLUMNS:
            raise ValueError(f"表格最多支持 {MAX_COLUMNS} 列，请先删减无关列")
        ws.reset_dimensions()
        return read_rows(ws.values, preview), sheets
    except (OSError, KeyError, ParseError, zipfile.BadZipFile) as exc:
        raise ValueError(
            "所选工作表无法读取，请用 Excel 另存为新的 .xlsx 后重试"
        ) from exc
    finally:
        workbook.close()


def open_xlsx(content):
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            if sum(item.file_size for item in archive.infolist()) > 150 * 1024 * 1024:
                raise ValueError("XLSX 解压后的文件过大")
        return load_workbook(
            io.BytesIO(content), read_only=True, data_only=True, keep_links=False
        )
    except (
        OSError,
        KeyError,
        ParseError,
        InvalidFileException,
        zipfile.BadZipFile,
    ) as exc:
        raise ValueError(
            "无法读取 Excel 文件。请确认文件可打开，并另存为 .xlsx 后重试"
        ) from exc


def read_rows(rows, preview):
    rows = iter(rows)
    headers = list(next(rows, ()))
    while headers and (headers[-1] is None or headers[-1] == ""):
        headers.pop()
    names = [str(h).strip() if h is not None else "" for h in headers]
    if len(names) < 2:
        raise ValueError(
            "第 1 行至少需要两列，例如「时间,跨中挠度(mm)」。Excel 请选数据工作表，CSV 请使用英文逗号分隔"
        )
    if any(not h or len(h) > 100 for h in names):
        raise ValueError(
            "第 1 行是表头。请取消合并单元格，为每列填写 1 到 100 字的列名"
        )
    if len(names) > MAX_COLUMNS:
        raise ValueError(f"表格最多支持 {MAX_COLUMNS} 列")
    if len(set(names)) != len(names):
        duplicates = list(dict.fromkeys(h for h in names if names.count(h) > 1))
        raise ValueError(
            "第 1 行有重复列名，请分别命名这些列：" + "、".join(duplicates[:5])
        )
    records = []
    for i, row in enumerate(rows, 2):
        if preview and len(records) == 12:
            break
        if i > MAX_ROWS + 1:
            raise ValueError("所选工作表最多支持 100,000 条数据")
        if any(v is not None and v != "" for v in row[len(names) :]):
            raise ValueError(f"第 {i} 行存在无表头的列；请使用时间列＋测点列宽表")
        values = list(row[: len(names)])
        records.append((i, values + [None] * (len(names) - len(values))))
    if not records:
        raise ValueError("表格缺少数据行")
    return names, records


def selected_table(token, sheet=None, preview=False):
    upload = storage.get("monitor_upload", token)
    return table(upload_path(token).read_bytes(), upload["name"], sheet, preview)


def begin_upload(content, filename):
    if not content or len(content) > MAX_BYTES:
        raise ValueError("请选择不超过 20 MB 的非空文件")
    name = Path(filename or "").name
    # For Excel, list all sheets even when the first one contains a cover page.
    if name.lower().endswith(".xlsx"):
        workbook = open_xlsx(content)
        try:
            sheets = workbook.sheetnames
        finally:
            workbook.close()
        if not sheets:
            raise ValueError("XLSX 文件没有工作表")
    elif name.lower().endswith(".csv"):
        sheets = []
        table(content, name, preview=True)
    else:
        raise ValueError(
            "请选择 .csv 或 .xlsx 文件。旧版 .xls 请先在 Excel 中另存为 .xlsx"
        )
    token = uuid.uuid4().hex
    path = upload_path(token)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    storage.save("monitor_upload", {"name": name}, token)
    return {"token": token, "name": name, "sheets": sheets}


def preview_table(token, sheet=None):
    (names, rows), _ = selected_table(token, sheet, True)
    suggested = next(
        (n for n in names if re.search(r"时间|日期|timestamp|time|date", n, re.I)),
        names[0],
    )
    return {
        "columns": names,
        "time_column": suggested,
        "rows": [[None if v is None else str(v)[:160] for v in row] for _, row in rows],
    }


def time_string(value):
    return pd.Timestamp(value).isoformat(timespec="milliseconds")


def parse_time(value):
    if (
        value is None
        or isinstance(value, (int, float, bool))
        or re.fullmatch(r"[+-]?\d+(\.\d+)?", str(value).strip())
    ):
        return None
    try:
        value = pd.Timestamp(value)
        if pd.isna(value) or not 1900 <= value.year <= 2200:
            return None
        if value.tzinfo is not None:
            value = value.tz_convert("Asia/Shanghai").tz_localize(None)
        return time_string(value.floor("ms"))
    except (TypeError, ValueError, OverflowError):
        return None


def numeric(value):
    if value is None or not str(value).strip():
        return None, "缺测"
    try:
        number = float(value)
        if (
            not isinstance(value, bool)
            and math.isfinite(number)
            and abs(number) <= 1e100
        ):
            return number, None
    except (TypeError, ValueError, OverflowError):
        pass
    return None, "非数值"


def interval_info(times):
    gaps = np.diff(pd.DatetimeIndex(sorted(set(times))).asi8) / 1e9
    if not len(gaps):
        return None, False
    intervals, counts = np.unique(gaps, return_counts=True)
    return float(intervals[counts.argmax()]), bool(
        len(intervals) == 1 and len(set(times)) == len(times)
    )


def confirm_upload(token, sheet, time_column, channels):
    upload = storage.get("monitor_upload", token)
    (names, rows), sheets = selected_table(token, sheet)
    if sheets and not sheet:
        raise ValueError("请选择 Excel 工作表")
    column_names = [c["name"] for c in channels]
    if time_column not in names or time_column in column_names:
        raise ValueError("时间列与测点列必须分别选择")
    if not 1 <= len(channels) <= MAX_CHANNELS or len(set(column_names)) != len(
        column_names
    ):
        raise ValueError("请选择 1 至 32 个不同的测点列")
    if any(c["name"] not in names or c["type"] not in TYPES for c in channels):
        raise ValueError("测点列或数据类型无法识别")
    positions = [names.index(n) for n in column_names]
    time_position = names.index(time_column)
    records, issues = [], []
    for row_id, row in rows:
        raw_time = row[time_position]
        stamp = parse_time(raw_time)
        if stamp is None:
            issues.append(
                {
                    "row": row_id,
                    "time": None,
                    "channel": time_column,
                    "kind": "无效时间",
                    "value": str(raw_time or "")[:160],
                }
            )
            continue
        values = []
        for c, position in zip(channels, positions):
            number, issue = numeric(row[position])
            values.append(number)
            if issue:
                issues.append(
                    {
                        "row": row_id,
                        "time": stamp,
                        "channel": c["name"],
                        "kind": issue,
                        "value": str(
                            row[position] if row[position] is not None else ""
                        )[:160],
                    }
                )
        records.append([stamp, row_id, *values])
    if not records:
        example = next((i for i in issues if i["value"]), issues[0])
        raise ValueError(
            f"「{time_column}」列没有可识别的日期时间（如第 {example['row']} 行）。"
            "请确认选中了时间列，并使用 Excel 日期单元格或 2025-10-01 09:00:00.001 格式。"
        )
    return new_dataset(
        name=upload["name"],
        sheet=sheet,
        channels=channels,
        records=records,
        issues=issues,
        upload=token,
        simulation=False,
    )


def new_dataset(
    *, name, sheet, channels, records, issues, upload, simulation, identifier=None
):
    dataset_id = identifier or uuid.uuid4().hex
    version = storage.save(
        "monitor_version",
        {
            "dataset_id": dataset_id,
            "parent_id": None,
            "label": "原始数据",
            "records": sorted(records, key=lambda r: (r[0], r[1])),
            "steps": [],
            "issues": issues,
        },
        f"{dataset_id}-original",
    )
    times = [r[0] for r in records]
    interval, regular = interval_info(times)
    return storage.save(
        "monitor_dataset",
        {
            "name": name,
            "sheet": sheet,
            "channels": channels,
            "original_id": version["id"],
            "upload": upload,
            "simulation": simulation,
            "start": min(times),
            "end": max(times),
            "samples": len(times),
            "interval": interval,
            "regular": regular,
            "invalid_times": sum(issue["kind"] == "无效时间" for issue in issues),
            "source": "固定种子模拟数据" if simulation else "用户上传",
        },
        dataset_id,
    )


def seed():
    try:
        storage.get("monitor_dataset", "monitor-demo")
        return
    except KeyError:
        pass
    rng = np.random.default_rng(20261115)
    timeline = pd.date_range("2025-10-01", periods=336, freq="h")
    t = np.arange(len(timeline))
    movement = 2.1 + 0.002 * t + 0.5 * np.sin(2 * np.pi * t / 24)
    a = movement + rng.normal(0, 0.06, len(t))
    b = 0.75 * movement + rng.normal(0, 0.05, len(t))
    a[180:186] += 1.5
    records = [
        [time_string(stamp), i + 2, float(a[i]), None if i in (47, 48) else float(b[i])]
        for i, stamp in enumerate(timeline)
    ]
    new_dataset(
        identifier="monitor-demo",
        name="桥梁挠度监测示例",
        sheet=None,
        simulation=True,
        upload=None,
        channels=[
            {"name": name, "type": "挠度", "unit": "mm"}
            for name in ("跨中 A", "跨中 B")
        ],
        records=records,
        issues=[
            {
                "row": i + 2,
                "time": records[i][0],
                "channel": "跨中 B",
                "kind": "缺测",
                "value": "",
            }
            for i in (47, 48)
        ],
    )


def get_version(dataset, version_id=None):
    version = storage.get("monitor_version", version_id or dataset["original_id"])
    if version["dataset_id"] != dataset["id"]:
        raise ValueError("数据版本不属于所选数据集")
    return version


def frame(dataset, version):
    columns = [c["name"] for c in dataset["channels"]]
    records = version["records"]
    result = pd.DataFrame([r[2:] for r in records], columns=columns, dtype=float)
    result.index = pd.DatetimeIndex([r[0] for r in records], name="时间")
    return result


def derived_body(dataset, version, result, step, row_ids=None):
    if len(result) > MAX_ROWS:
        raise ValueError("处理结果超过 100,000 行，请缩小时间范围或增加采样间隔")
    ids = row_ids if row_ids is not None else [None] * len(result)
    records = [
        [time_string(t), row, *[None if pd.isna(x) else float(x) for x in values]]
        for row, (t, values) in zip(
            ids, zip(result.index, result.itertuples(index=False, name=None))
        )
    ]
    return {
        "dataset_id": dataset["id"],
        "parent_id": version["id"],
        "label": step["label"],
        "records": records,
        "steps": [*version["steps"], step],
        "issues": version["issues"],
    }
