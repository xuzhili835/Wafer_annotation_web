"""三种导出:全量留痕 csv / 多数票定稿 csv / VOC XML zip。全部实时快照。"""
from __future__ import annotations

import csv
import io
import json
import zipfile
from datetime import datetime
from xml.sax.saxutils import escape

from app.db import connect


def _active_annotations(conn) -> list:
    return conn.execute(
        "SELECT * FROM annotations WHERE revoked = 0 ORDER BY submitted_at, id"
    ).fetchall()


def export_annotations_csv() -> str:
    conn = connect()
    try:
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["id", "stem", "annotator", "submitted_at", "revoked", "is_empty", "boxes"])
        for r in conn.execute(
            "SELECT id,stem,annotator,submitted_at,revoked,is_empty,boxes_json FROM annotations ORDER BY id"
        ):
            w.writerow([r["id"], r["stem"], r["annotator"], r["submitted_at"],
                        r["revoked"], r["is_empty"], r["boxes_json"]])
        return buf.getvalue()
    finally:
        conn.close()


def export_labels_voted_csv() -> str:
    conn = connect()
    try:
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["stem", "status", "final_box_count", "final_boxes"])
        imgs = conn.execute("SELECT stem, final_id FROM images ORDER BY stem").fetchall()
        finals = {r["id"]: r for r in conn.execute(
            "SELECT id, boxes_json, is_empty FROM annotations WHERE revoked=0")}
        for im in imgs:
            fid = im["final_id"]
            if fid and fid in finals:
                f = finals[fid]
                status = "empty" if f["is_empty"] else "final"
                w.writerow([im["stem"], status,
                            0 if f["is_empty"] else len(json.loads(f["boxes_json"])),
                            "" if f["is_empty"] else f["boxes_json"]])
            else:
                w.writerow([im["stem"], "pending", "", ""])
        return buf.getvalue()
    finally:
        conn.close()


def export_voc_xml_zip() -> tuple[bytes, int]:
    """仅定稿图入包;与数据方测试集 XML 同构(annotation/size/object/bndbox)。"""
    conn = connect()
    try:
        imgs = conn.execute(
            "SELECT i.stem, i.path, i.w, i.h, a.boxes_json FROM images i"
            " JOIN annotations a ON a.id = i.final_id WHERE i.final_id IS NOT NULL"
            " ORDER BY i.stem").fetchall()
        buf = io.BytesIO()
        count = 0
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for im in imgs:
                boxes = json.loads(im["boxes_json"])
                parts = [
                    "<annotation>",
                    f"\t<folder>wafer_labels</folder>",
                    f"\t<filename>{escape(im['stem'])}.png</filename>",
                    f"\t<path>{escape(im['stem'])}.png</path>",
                    "\t<source>\n\t\t<database>wafer_annotation_web</database>\n\t</source>",
                    f"\t<size>\n\t\t<width>{im['w']}</width>\n\t\t<height>{im['h']}</height>"
                    f"\n\t\t<depth>1</depth>\n\t</size>",
                    "\t<segmented>0</segmented>",
                ]
                for b in boxes:
                    parts.append(
                        "\t<object>\n"
                        f"\t\t<name>{escape(b['code'])}</name>\n"
                        "\t\t<pose>Unspecified</pose>\n\t\t<truncated>0</truncated>\n"
                        "\t\t<difficult>0</difficult>\n"
                        "\t\t<bndbox>\n"
                        f"\t\t\t<xmin>{int(b['x0'])}</xmin>\n\t\t\t<ymin>{int(b['y0'])}</ymin>\n"
                        f"\t\t\t<xmax>{int(b['x1'])}</xmax>\n\t\t\t<ymax>{int(b['y1'])}</ymax>\n"
                        "\t\t</bndbox>\n\t</object>")
                parts.append("</annotation>")
                z.writestr(f"{im['stem']}.xml", "\n".join(parts))
                count += 1
        return buf.getvalue(), count
    finally:
        conn.close()
