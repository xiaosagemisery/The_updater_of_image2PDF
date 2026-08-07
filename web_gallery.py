# -*- coding: utf-8 -*-
"""
Gallery 的持久化: 每次转换生成的 PDF 对应一张封面缩略图 + 一条 JSON 记录,
存在 webdata/ 目录下,服务重启后依然存在,并且可以持续累积。

- webdata/gallery.json  索引文件
- webdata/covers/<id>.jpg  封面缩略图,<id> 由 PDF 的绝对路径哈希得到

设计要点(详见各函数注释):
- id 由 PDF 的绝对路径算出,保证同名但不同目录的书(比如两个都叫"same"的文件夹)
  不会共用同一张封面。
- 同一个 PDF 路径重复转换 = 原地更新那一条记录并覆盖封面,而不是新增一条,
  否则会出现两条记录共享一张封面文件、删一条就把另一条的封面弄丢的问题。
"""

import hashlib
import json
import os
import threading
import time

from PIL import Image as pilImage
from PIL import ImageOps
from PIL import UnidentifiedImageError

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 用模块属性(而不是常量)存目录路径,方便测试用 monkeypatch 指到 tmp_path
DATA_DIR = os.environ.get("IMAGE2PDF_DATA_DIR") or os.path.join(BASE_DIR, "webdata")

THUMB_SIZE = (360, 480)

_LOCK = threading.Lock()


def _covers_dir():
    return os.path.join(DATA_DIR, "covers")


def _index_file():
    return os.path.join(DATA_DIR, "gallery.json")


def item_id(pdf_path):
    """
    根据 PDF 的绝对路径生成稳定 id。normcase 让同一个文件在大小写/斜杠不同写法下
    映射到同一个 id(Windows 路径不区分大小写);哈希覆盖完整路径,保证两个叫
    "same.pdf" 但目录不同的书不会撞在同一个封面文件名上。
    """
    key = os.path.normcase(os.path.abspath(pdf_path))
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


def make_cover(src_image, id_):
    """
    用源图(将来会成为 PDF 第一页的那张图)生成一张封面缩略图,保存为 <id>.jpg。

    失败(文件损坏 / 打不开等)时返回 None,调用方应当把 cover_file 存成 null,
    绝不能让一张读不出的首图拖垮整批转换。
    """
    covers_dir = _covers_dir()
    os.makedirs(covers_dir, exist_ok=True)
    dest = os.path.join(covers_dir, id_ + ".jpg")
    tmp = dest + ".tmp"

    try:
        with pilImage.open(src_image) as im:
            # EXIF 方向信息要在缩放之前处理,否则手机竖拍的照片缩完是横的
            im = ImageOps.exif_transpose(im) or im
            im.thumbnail(THUMB_SIZE, pilImage.LANCZOS)

            if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
                # JPEG 没有透明通道,直接 convert("RGB") 会把透明区域变黑,
                # 所以先在白底上合成再转 RGB
                rgba = im.convert("RGBA")
                flat = pilImage.new("RGB", rgba.size, (255, 255, 255))
                flat.paste(rgba, mask=rgba.split()[-1])
                im = flat
            elif im.mode != "RGB":
                im = im.convert("RGB")  # P / L / 1 / CMYK 等

            im.save(tmp, "JPEG", quality=82, optimize=True)
    except (OSError, UnidentifiedImageError):
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
        return None

    os.replace(tmp, dest)  # 原子替换,轮询中的浏览器不会读到写了一半的文件
    return os.path.basename(dest)


def _load_index():
    path = _index_file()
    if not os.path.exists(path):
        return {"version": 1, "items": []}

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict) or not isinstance(data.get("items"), list):
            raise ValueError("gallery.json 格式不对")
        return data
    except (OSError, ValueError, json.JSONDecodeError):
        # 索引损坏: 备份现场,从空索引重新开始,而不是让整个 Gallery 崩掉
        bad_path = path + ".bad-%d" % int(time.time())
        try:
            os.replace(path, bad_path)
        except OSError:
            pass
        return {"version": 1, "items": []}


def _save_index(data):
    os.makedirs(DATA_DIR, exist_ok=True)
    path = _index_file()
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def upsert_result(result, batch_id=None):
    """
    把 Image2PDF 的一条转换结果(见 Image2PDF.__make_result)写入 Gallery 索引,
    同时生成封面。如果这个 PDF 路径已经在索引里(重复转换同一个目录),
    原地更新那一条记录(保留 created_at 和排列位置),否则追加到末尾。

    返回写入/更新后的条目 dict。
    """
    id_ = item_id(result["pdf_path"])
    now = time.time()

    cover_file = None
    if result.get("first_page"):
        cover_file = make_cover(result["first_page"], id_)

    with _LOCK:
        data = _load_index()
        items = data["items"]

        existing = next((it for it in items if it["id"] == id_), None)
        if existing is not None:
            existing.update({
                "pdf_path": result["pdf_path"],
                "pdf_name": result["pdf_name"],
                "title": os.path.splitext(result["pdf_name"])[0],
                "source_dir": result["source_dir"],
                "page_count": result["page_count"],
                "cover_file": cover_file if cover_file else existing.get("cover_file"),
                "first_page": result.get("first_page"),
                "updated_at": now,
                "batch_id": batch_id,
            })
            item = existing
        else:
            item = {
                "id": id_,
                "pdf_path": result["pdf_path"],
                "pdf_name": result["pdf_name"],
                "title": os.path.splitext(result["pdf_name"])[0],
                "source_dir": result["source_dir"],
                "page_count": result["page_count"],
                "cover_file": cover_file,
                "first_page": result.get("first_page"),
                "created_at": now,
                "updated_at": now,
                "batch_id": batch_id,
            }
            items.append(item)

        _save_index(data)
        return dict(item)


def list_items():
    """
    返回所有条目,附带一个不落盘的 "missing" 字段:PDF 文件是否还在磁盘上,
    供前端把已经被移动/删除的书置灰显示。
    """
    with _LOCK:
        data = _load_index()
        items = [dict(it) for it in data["items"]]

    for it in items:
        it["missing"] = not os.path.exists(it["pdf_path"])
    return items


def delete_item(id_):
    """
    删除一条 Gallery 记录和它的封面文件,但绝不删除 PDF 本身
    (PDF 是用户在磁盘上的真实产出,Gallery 只是一个索引视图)。
    返回 True 表示确实删掉了一条,False 表示 id 不存在。
    """
    with _LOCK:
        data = _load_index()
        items = data["items"]
        item = next((it for it in items if it["id"] == id_), None)
        if item is None:
            return False

        items.remove(item)
        _save_index(data)

    cover_file = item.get("cover_file")
    if cover_file:
        cover_path = os.path.join(_covers_dir(), cover_file)
        if os.path.exists(cover_path):
            try:
                os.remove(cover_path)
            except OSError:
                pass

    return True


def cover_path(filename):
    """校验后返回封面文件的绝对路径,供 send_from_directory 使用。"""
    return _covers_dir()
