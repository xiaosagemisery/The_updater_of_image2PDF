# -*- coding: utf-8 -*-

import os
import shutil
import sys
import time
from pathlib import Path

import pytest
from PIL import Image

import Image2PDF as image2pdf
import web_fs
import web_gallery
import webapp


def _make_spread_image(path, left_color=(255, 0, 0), right_color=(0, 0, 255), size=(200, 100)):
    """构造一张左右两色的跨页图,方便断言拆分后哪一半在前面。"""
    w, h = size
    im = Image.new("RGB", size)
    im.paste(left_color, (0, 0, w // 2, h))
    im.paste(right_color, (w // 2, 0, w, h))
    im.save(path)


# ---------------------------------------------------------------------------
# Image2PDF: 新增的 results / on_book_done / auto 分派
# ---------------------------------------------------------------------------

def test_convert_one_dir_returns_pdf_and_first_page(tmp_path):
    for i in range(3):
        Image.new("RGB", (100, 150), (i * 40, 0, 0)).save(tmp_path / ("p%02d.png" % i))

    results = image2pdf.convert_images2PDF_one_dir(str(tmp_path))

    assert len(results) == 1
    result = results[0]
    assert os.path.exists(result["pdf_path"])
    assert result["page_count"] == 3
    assert Path(result["first_page"]).name == "p00.png"


def test_convert_one_dir_places_pdf_next_to_source_dir_not_inside_it(tmp_path):
    # PDF 应该和图片所在的目录同级(在它的上一级),不能塞进图片所在的目录内部,
    # 否则会和一堆原始扫描图混在一起。
    book_dir = tmp_path / "第01卷"
    book_dir.mkdir()
    for i in range(2):
        Image.new("RGB", (100, 150)).save(book_dir / ("p%02d.png" % i))

    results = image2pdf.convert_images2PDF_one_dir(str(book_dir))

    pdf_path = Path(results[0]["pdf_path"])
    assert pdf_path.parent == tmp_path  # 和 book_dir 同级,不是 book_dir 内部
    assert pdf_path.name == "第01卷.pdf"
    assert not (book_dir / "第01卷.pdf").exists()


def test_convert_one_dir_with_save_name_also_places_pdf_next_to_source_dir(tmp_path):
    book_dir = tmp_path / "第02卷"
    book_dir.mkdir()
    Image.new("RGB", (100, 150)).save(book_dir / "p00.png")

    results = image2pdf.convert_images2PDF_one_dir(str(book_dir), save_name="自定义名字.pdf")

    pdf_path = Path(results[0]["pdf_path"])
    assert pdf_path.parent == tmp_path
    assert pdf_path.name == "自定义名字.pdf"


def test_convert_auto_one_dir_dispatch_also_places_pdf_next_to_source_dir(tmp_path):
    book_dir = tmp_path / "漫画名"
    book_dir.mkdir()
    Image.new("RGB", (100, 150)).save(book_dir / "p00.png")

    mode, results = image2pdf.convert_images2PDF_auto(str(book_dir))

    assert mode == "one_dir"
    assert Path(results[0]["pdf_path"]).parent == tmp_path


def test_more_dirs_result_does_not_depend_on_converted_return(tmp_path, monkeypatch):
    # 与 filename_sort_test.py 里同样的手法: __converted 被替换成一个不做任何
    # 真实 I/O、且返回 None 的 fake。convert_images2PDF_more_dirs 必须仍能
    # 返回完整的 results 列表 —— 这是本次重构不能破坏的核心约束。
    book = tmp_path / "vol1"
    book.mkdir()
    (book / "page_1.png").write_bytes(b"not a real image")

    def fake_convert(save_name, pages, filename_sort_fn=None):
        return None

    monkeypatch.setattr(image2pdf, "__converted", fake_convert)

    results = image2pdf.convert_images2PDF_more_dirs(str(tmp_path))

    assert len(results) == 1
    assert results[0]["page_count"] == 1
    assert Path(results[0]["first_page"]).name == "page_1.png"


def test_auto_dispatch_matches_cli_rule(tmp_path):
    top_dir = tmp_path / "top"
    top_dir.mkdir()
    Image.new("RGB", (10, 10)).save(top_dir / "a.png")

    mode, results = image2pdf.convert_images2PDF_auto(str(top_dir))
    assert mode == "one_dir"
    assert len(results) == 1

    series_dir = tmp_path / "series"
    (series_dir / "vol1").mkdir(parents=True)
    Image.new("RGB", (10, 10)).save(series_dir / "vol1" / "a.png")

    mode2, results2 = image2pdf.convert_images2PDF_auto(str(series_dir))
    assert mode2 == "more_dirs"
    assert len(results2) == 1


def test_on_book_done_callback_receives_progress(tmp_path):
    for i in range(2):
        Image.new("RGB", (10, 10)).save(tmp_path / ("p%d.png" % i))

    calls = []
    image2pdf.convert_images2PDF_one_dir(
        str(tmp_path), on_book_done=lambda result, done, total: calls.append((done, total)))

    assert calls == [(1, 1)]


# ---------------------------------------------------------------------------
# Image2PDF: 页级转换进度 (on_page_progress)
# ---------------------------------------------------------------------------

def test_on_page_progress_reports_pages_for_one_dir(tmp_path):
    for i in range(4):
        Image.new("RGB", (10, 10)).save(tmp_path / ("p%d.png" % i))

    calls = []
    image2pdf.convert_images2PDF_one_dir(
        str(tmp_path),
        on_page_progress=lambda bn, bt, pd, pt: calls.append((bn, bt, pd, pt)))

    assert calls == [(1, 1, 1, 4), (1, 1, 2, 4), (1, 1, 3, 4), (1, 1, 4, 4)]


def test_on_page_progress_reports_book_context_for_more_dirs(tmp_path):
    vol1 = tmp_path / "vol1"
    vol2 = tmp_path / "vol2"
    vol1.mkdir()
    vol2.mkdir()
    for i in range(2):
        Image.new("RGB", (10, 10)).save(vol1 / ("p%d.png" % i))
    for i in range(3):
        Image.new("RGB", (10, 10)).save(vol2 / ("p%d.png" % i))

    calls = []
    image2pdf.convert_images2PDF_more_dirs(
        str(tmp_path),
        on_page_progress=lambda bn, bt, pd, pt: calls.append((bn, bt, pd, pt)))

    # vol1 (2 页) 按字典序排在 vol2 (3 页) 前面
    assert calls == [
        (1, 2, 1, 2), (1, 2, 2, 2),
        (2, 2, 1, 3), (2, 2, 2, 3), (2, 2, 3, 3),
    ]


def test_on_page_progress_counts_split_halves_when_double_page(tmp_path):
    for i in range(2):
        _make_spread_image(tmp_path / ("p%02d.png" % i))

    calls = []
    image2pdf.convert_images2PDF_one_dir(
        str(tmp_path), double_page=True, right_page_first=True,
        on_page_progress=lambda bn, bt, pd, pt: calls.append((bn, bt, pd, pt)))

    # 2 张跨页图 x 2 半 = 4 页
    assert calls == [(1, 1, 1, 4), (1, 1, 2, 4), (1, 1, 3, 4), (1, 1, 4, 4)]


def test_on_page_progress_default_none_no_behavior_change(tmp_path):
    for i in range(3):
        Image.new("RGB", (10, 10)).save(tmp_path / ("p%d.png" % i))

    results = image2pdf.convert_images2PDF_one_dir(str(tmp_path))  # 不传 on_page_progress

    assert results[0]["page_count"] == 3
    # 用完之后钩子必须复位
    assert image2pdf.__dict__["__page_progress_hook"] is None


# ---------------------------------------------------------------------------
# Image2PDF: 双页拼图拆分
# ---------------------------------------------------------------------------

def test_split_double_page_images_right_first_puts_right_half_first(tmp_path):
    img_path = tmp_path / "spread.png"
    _make_spread_image(img_path)  # 左=红 右=蓝

    split_fn = image2pdf.__dict__["__split_double_page_images"]
    expanded, temp_dir = split_fn([str(img_path)], True)
    try:
        assert len(expanded) == 2
        with Image.open(expanded[0]) as first:
            assert first.getpixel((10, 10))[:3] == (0, 0, 255)  # 右半(蓝)排在前面
        with Image.open(expanded[1]) as second:
            assert second.getpixel((10, 10))[:3] == (255, 0, 0)  # 左半(红)排在后面
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_split_double_page_images_left_first_puts_left_half_first(tmp_path):
    img_path = tmp_path / "spread.png"
    _make_spread_image(img_path)  # 左=红 右=蓝

    split_fn = image2pdf.__dict__["__split_double_page_images"]
    expanded, temp_dir = split_fn([str(img_path)], False)
    try:
        assert len(expanded) == 2
        with Image.open(expanded[0]) as first:
            assert first.getpixel((10, 10))[:3] == (255, 0, 0)  # 左半(红)排在前面
        with Image.open(expanded[1]) as second:
            assert second.getpixel((10, 10))[:3] == (0, 0, 255)  # 右半(蓝)排在后面
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_split_double_page_images_default_still_produces_png(tmp_path):
    # 回归护栏: 不传 split_as_jpeg 时必须还是无损 PNG,和引入这个参数之前完全一样
    img_path = tmp_path / "spread.png"
    _make_spread_image(img_path)

    split_fn = image2pdf.__dict__["__split_double_page_images"]
    expanded, temp_dir = split_fn([str(img_path)], True)
    try:
        assert all(p.endswith(".png") for p in expanded)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_split_double_page_images_as_jpeg_produces_jpg_and_keeps_order(tmp_path):
    img_path = tmp_path / "spread.png"
    _make_spread_image(img_path)  # 左=红 右=蓝

    split_fn = image2pdf.__dict__["__split_double_page_images"]
    expanded, temp_dir = split_fn([str(img_path)], True, split_as_jpeg=True)
    try:
        assert all(p.endswith(".jpg") for p in expanded)
        with Image.open(expanded[0]) as first:
            assert first.format == "JPEG"
            # JPEG 有损,不能断言像素精确相等,只判断蓝色分量明显更高(右半=蓝排在前面)
            px = first.getpixel((10, 10))
            assert px[2] > px[0]
        with Image.open(expanded[1]) as second:
            px = second.getpixel((10, 10))
            assert px[0] > px[2]  # 左半=红排在后面
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_split_double_page_images_as_jpeg_composites_transparency_on_white(tmp_path):
    # JPEG 没有透明通道,带 alpha 的半张图要先在白底上合成,不能直接 convert("RGB")
    # 把透明区域变黑(和 web_gallery.make_cover 的处理是同一套逻辑)。
    img_path = tmp_path / "spread_rgba.png"
    w, h = 200, 100
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))  # 全透明
    im.paste((255, 0, 0, 255), (0, 0, w // 2, h))
    im.paste((0, 0, 255, 255), (w // 2, 0, w, h))
    im.save(img_path)

    split_fn = image2pdf.__dict__["__split_double_page_images"]
    expanded, temp_dir = split_fn([str(img_path)], True, split_as_jpeg=True)
    try:
        with Image.open(expanded[0]) as first:
            assert first.mode == "RGB"
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_convert_one_dir_with_split_as_jpeg(tmp_path):
    for i in range(2):
        _make_spread_image(tmp_path / ("p%02d.png" % i))

    results = image2pdf.convert_images2PDF_one_dir(
        str(tmp_path), double_page=True, right_page_first=True, split_as_jpeg=True)

    assert results[0]["page_count"] == 4  # 2 张跨页图 x 2 半 = 4 页
    assert os.path.exists(results[0]["pdf_path"])


def test_double_page_doubles_page_count_and_cleans_up_temp_dir(tmp_path, monkeypatch):
    for i in range(2):
        _make_spread_image(tmp_path / ("p%02d.png" % i))

    split_fn = image2pdf.__dict__["__split_double_page_images"]
    captured_temp_dirs = []

    def spy(sorted_pages, right_page_first, split_as_jpeg=False):
        expanded, temp_dir = split_fn(sorted_pages, right_page_first, split_as_jpeg)
        captured_temp_dirs.append(temp_dir)
        return expanded, temp_dir

    monkeypatch.setattr(image2pdf, "__split_double_page_images", spy)

    results = image2pdf.convert_images2PDF_one_dir(
        str(tmp_path), double_page=True, right_page_first=True)

    assert results[0]["page_count"] == 4  # 2 张跨页图 x 2 半 = 4 页
    assert len(captured_temp_dirs) == 1
    assert not os.path.exists(captured_temp_dirs[0])  # 转换结束后临时目录必须被清理


def test_double_page_off_does_not_split(tmp_path, monkeypatch):
    for i in range(2):
        Image.new("RGB", (50, 80)).save(tmp_path / ("p%02d.png" % i))

    def _boom(*args, **kwargs):
        raise AssertionError("double_page=False 时不应该调用拆分函数")

    monkeypatch.setattr(image2pdf, "__split_double_page_images", _boom)

    results = image2pdf.convert_images2PDF_one_dir(str(tmp_path))  # double_page 默认 False

    assert results[0]["page_count"] == 2


def test_convert_more_dirs_with_double_page(tmp_path):
    vol_dir = tmp_path / "vol1"
    vol_dir.mkdir()
    for i in range(2):
        _make_spread_image(vol_dir / ("p%02d.png" % i))

    results = image2pdf.convert_images2PDF_more_dirs(
        str(tmp_path), double_page=True, right_page_first=True)

    assert len(results) == 1
    assert results[0]["page_count"] == 4


def test_build_arg_parser_double_page_requires_order():
    parser = image2pdf.__dict__["__build_arg_parser"]()
    validate = image2pdf.__dict__["__validate_cli_args"]

    args_ok = parser.parse_args(["--double-page", "--right-first"])
    validate(parser, args_ok)  # 不应该抛出

    args_missing_order = parser.parse_args(["--double-page"])
    with pytest.raises(SystemExit):
        validate(parser, args_missing_order)

    args_no_double_page = parser.parse_args([])
    validate(parser, args_no_double_page)  # 不开双页模式时不要求 order


def test_build_arg_parser_rejects_conflicting_order_flags():
    parser = image2pdf.__dict__["__build_arg_parser"]()
    with pytest.raises(SystemExit):
        parser.parse_args(["--double-page", "--right-first", "--left-first"])


# ---------------------------------------------------------------------------
# webapp: /api/convert 的双页参数
# ---------------------------------------------------------------------------

def test_api_convert_requires_right_page_first_when_double_page(tmp_path):
    Image.new("RGB", (50, 80)).save(tmp_path / "a.png")

    client = webapp.app.test_client()
    resp = client.post("/api/convert", json={"path": str(tmp_path), "double_page": True})

    assert resp.status_code == 400
    assert "right_page_first" in resp.get_json()["error"]


def test_api_convert_accepts_split_as_jpeg_without_requiring_it(tmp_path, monkeypatch):
    # split_as_jpeg 有安全默认值(False),不像 right_page_first 那样必须显式带上;
    # 不传的时候也应该能正常接受请求(不是 400)。
    monkeypatch.setattr(web_gallery, "DATA_DIR", str(tmp_path / "webdata"))
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    Image.new("RGB", (50, 80)).save(src_dir / "a.png")

    client = webapp.app.test_client()
    resp = client.post("/api/convert", json={
        "path": str(src_dir), "double_page": True, "right_page_first": True, "split_as_jpeg": True,
    })

    assert resp.status_code == 202
    job_id = resp.get_json()["job_id"]
    with webapp._jobs_lock:
        assert webapp._jobs[job_id]["split_as_jpeg"] is True

    for _ in range(50):
        with webapp._jobs_lock:
            status = webapp._jobs[job_id]["status"]
        if status in ("done", "error"):
            break
        time.sleep(0.05)
    assert status == "done"


# ---------------------------------------------------------------------------
# webapp: 转换进度百分比
# ---------------------------------------------------------------------------

def test_compute_percent_single_book():
    # book_total=1 (one_dir 模式): 百分比就是这一本书的页级进度
    assert webapp._compute_percent(1, 1, 0, 10) == 0
    assert webapp._compute_percent(1, 1, 5, 10) == 50
    assert webapp._compute_percent(1, 1, 10, 10) == 100


def test_compute_percent_multi_book():
    # book_total=2: 第 1 本刚开始渲染第 1/10 页 -> (0 + 1/10) / 2 = 5%
    assert webapp._compute_percent(1, 2, 1, 10) == 5
    # 第 1 本渲染完(page_done==page_total) -> (0 + 1) / 2 = 50%
    assert webapp._compute_percent(1, 2, 10, 10) == 50
    # 第 2 本(book_number=2) 渲染到一半 -> (1 + 0.5) / 2 = 75%
    assert webapp._compute_percent(2, 2, 5, 10) == 75
    # 第 2 本渲染完 -> (1 + 1) / 2 = 100%
    assert webapp._compute_percent(2, 2, 10, 10) == 100


def test_compute_percent_no_page_data_yet():
    # page_total 为 0/None 时,这一本贡献 0 进度,不应该抛除零错误
    assert webapp._compute_percent(1, 2, 0, 0) == 0
    assert webapp._compute_percent(2, 2, 0, None) == 50


def test_run_conversion_reports_percent_progress_one_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(web_gallery, "DATA_DIR", str(tmp_path / "webdata"))
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    for i in range(4):
        Image.new("RGB", (10, 10)).save(src_dir / ("p%d.png" % i))

    job_id = webapp._new_job(str(src_dir), "one_dir", 1)
    percents_during_run = []

    real_compute = webapp._compute_percent

    def spy(*args, **kwargs):
        pct = real_compute(*args, **kwargs)
        percents_during_run.append(pct)
        return pct

    monkeypatch.setattr(webapp, "_compute_percent", spy)

    webapp._run_conversion(job_id, str(src_dir))

    job = webapp._jobs[job_id]
    assert job["status"] == "done"
    assert job["percent"] == 100
    assert job["page_done"] == 4
    assert job["page_total"] == 4
    # 4 页 -> 4 次页级回调,百分比应该单调不减,且不是从头到尾只有一个数字
    assert percents_during_run == [25, 50, 75, 100]


def test_run_conversion_reports_percent_progress_more_dirs(tmp_path, monkeypatch):
    monkeypatch.setattr(web_gallery, "DATA_DIR", str(tmp_path / "webdata"))
    root = tmp_path / "root"
    vol1 = root / "vol1"
    vol2 = root / "vol2"
    vol1.mkdir(parents=True)
    vol2.mkdir(parents=True)
    for i in range(2):
        Image.new("RGB", (10, 10)).save(vol1 / ("p%d.png" % i))
    for i in range(2):
        Image.new("RGB", (10, 10)).save(vol2 / ("p%d.png" % i))

    job_id = webapp._new_job(str(root), "more_dirs", 2)
    webapp._run_conversion(job_id, str(root))

    job = webapp._jobs[job_id]
    assert job["status"] == "done"
    assert job["percent"] == 100
    assert job["done"] == 2
    assert job["total"] == 2


def test_run_conversion_empty_dir_sets_job_error_instead_of_raising(tmp_path, monkeypatch):
    # /api/convert 不再提前用 web_fs.preview() 做一次同步的全树遍历来判断"有没有图片"
    # (那是"点了开始转换迟迟没反应"的主因之一),所以这个判断挪到了这里:
    # convert_images2PDF_auto 跑完发现 results 是空列表时,job 应该被标记成 error,
    # 而不是让调用方看到一个未处理的异常或者误判成功。
    monkeypatch.setattr(web_gallery, "DATA_DIR", str(tmp_path / "webdata"))
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()

    job_id = webapp._new_job(str(empty_dir), "one_dir", 1)
    webapp._run_conversion(job_id, str(empty_dir))

    job = webapp._jobs[job_id]
    assert job["status"] == "error"
    assert "没有找到任何图片文件" in job["error"]


def test_api_convert_returns_immediately_without_walking_whole_tree(tmp_path, monkeypatch):
    # 回归护栏: /api/convert 不应该再调用 web_fs.preview (那是一次递归 os.walk)。
    # 直接 monkeypatch 成"一调用就报错",确认请求路径完全不会碰它。
    def _boom(*args, **kwargs):
        raise AssertionError("/api/convert 不应该再调用 web_fs.preview")

    monkeypatch.setattr(web_fs, "preview", _boom)
    monkeypatch.setattr(web_gallery, "DATA_DIR", str(tmp_path / "webdata"))

    src_dir = tmp_path / "src"
    src_dir.mkdir()
    Image.new("RGB", (10, 10)).save(src_dir / "a.png")

    client = webapp.app.test_client()
    resp = client.post("/api/convert", json={"path": str(src_dir)})

    assert resp.status_code == 202
    assert "job_id" in resp.get_json()

    # 后台线程会真的跑起来转换这一张图,等它跑完避免干扰后续测试里的 _running_job_id 状态
    job_id = resp.get_json()["job_id"]
    for _ in range(50):
        with webapp._jobs_lock:
            status = webapp._jobs[job_id]["status"]
        if status in ("done", "error"):
            break
        time.sleep(0.05)
    assert status == "done"


# ---------------------------------------------------------------------------
# web_fs: 路径规范化 / 403 处理
# ---------------------------------------------------------------------------

def test_normalize_dir_rejects_relative_path():
    with pytest.raises(web_fs.PathError):
        web_fs.normalize_dir("relative/path")


def test_normalize_dir_rejects_empty():
    with pytest.raises(web_fs.PathError):
        web_fs.normalize_dir("   ")


@pytest.mark.skipif(os.name != "nt", reason="裸盘符补全只在 Windows 上有意义")
def test_normalize_dir_fixes_bare_drive_letter():
    # os.path.abspath("C:") 在 Windows 上返回的是当前工作目录,不是 "C:\\",
    # normalize_dir 必须自己特判,不能依赖 abspath()
    assert web_fs.normalize_dir("C:") == "C:\\"


def test_parent_of_drive_root_is_none():
    assert web_fs.parent_of("C:\\") is None


def test_browse_permission_error_returns_403(tmp_path, monkeypatch):
    def _raise(*args, **kwargs):
        raise PermissionError("拒绝访问")

    monkeypatch.setattr(web_fs.os, "scandir", _raise)

    client = webapp.app.test_client()
    resp = client.get("/api/browse", query_string={"path": str(tmp_path)})

    assert resp.status_code == 403
    data = resp.get_json()
    assert "parent" in data


# ---------------------------------------------------------------------------
# web_gallery: 封面生成 / 索引原地更新
# ---------------------------------------------------------------------------

def test_cover_from_rgba_png_is_rgb_jpeg(tmp_path, monkeypatch):
    monkeypatch.setattr(web_gallery, "DATA_DIR", str(tmp_path / "webdata"))

    img_path = tmp_path / "p00.png"
    Image.new("RGBA", (800, 1200), (10, 20, 30, 128)).save(img_path)

    cover_name = web_gallery.make_cover(str(img_path), "abc123")

    assert cover_name == "abc123.jpg"
    cover_full = os.path.join(web_gallery._covers_dir(), cover_name)
    with Image.open(cover_full) as im:
        assert im.mode == "RGB"
        assert im.size[0] <= web_gallery.THUMB_SIZE[0]
        assert im.size[1] <= web_gallery.THUMB_SIZE[1]


def test_cover_ids_differ_for_same_basename_in_different_dirs():
    id_a = web_gallery.item_id("D:\\a\\same.pdf")
    id_b = web_gallery.item_id("D:\\b\\same.pdf")
    assert id_a != id_b


def test_gallery_upsert_updates_in_place(tmp_path, monkeypatch):
    monkeypatch.setattr(web_gallery, "DATA_DIR", str(tmp_path / "webdata"))

    img_path = tmp_path / "p00.png"
    Image.new("RGB", (100, 100)).save(img_path)
    pdf_path = tmp_path / "book.pdf"
    pdf_path.write_bytes(b"")

    result = {
        "pdf_path": str(pdf_path),
        "pdf_name": "book.pdf",
        "source_dir": str(tmp_path),
        "page_count": 1,
        "first_page": str(img_path),
    }

    item1 = web_gallery.upsert_result(result, batch_id="job-1")
    item2 = web_gallery.upsert_result(result, batch_id="job-2")

    items = web_gallery.list_items()
    assert len(items) == 1
    assert item1["id"] == item2["id"]
    assert item1["created_at"] == item2["created_at"]
    assert item2["updated_at"] >= item1["updated_at"]
    assert item2["batch_id"] == "job-2"


def test_gallery_delete_removes_cover_but_not_pdf(tmp_path, monkeypatch):
    monkeypatch.setattr(web_gallery, "DATA_DIR", str(tmp_path / "webdata"))

    img_path = tmp_path / "p00.png"
    Image.new("RGB", (100, 100)).save(img_path)
    pdf_path = tmp_path / "book.pdf"
    pdf_path.write_bytes(b"real pdf bytes")

    result = {
        "pdf_path": str(pdf_path),
        "pdf_name": "book.pdf",
        "source_dir": str(tmp_path),
        "page_count": 1,
        "first_page": str(img_path),
    }
    item = web_gallery.upsert_result(result)
    cover_full = os.path.join(web_gallery._covers_dir(), item["cover_file"])
    assert os.path.exists(cover_full)

    assert web_gallery.delete_item(item["id"]) is True
    assert not os.path.exists(cover_full)
    assert pdf_path.exists()  # PDF 本身绝不能被删除
    assert web_gallery.list_items() == []


# ---------------------------------------------------------------------------
# reportlab useA85: 关掉纯 Python 的 ASCII85 编码(性能瓶颈,见 Image2PDF.py 头部说明)
# ---------------------------------------------------------------------------

def test_use_a85_disabled_on_import():
    import reportlab.rl_config
    assert reportlab.rl_config.useA85 == 0


def test_converted_jpeg_pdf_has_no_ascii85_filter(tmp_path):
    # JPEG 直通路径(loadImageFromJPEG):关掉 useA85 后不应再套 ASCII85Decode,
    # 但 DCTDecode 直通本身要继续生效。
    book_dir = tmp_path / "book"
    book_dir.mkdir()
    Image.new("RGB", (60, 80), (10, 20, 30)).save(book_dir / "p00.jpg", "JPEG")

    results = image2pdf.convert_images2PDF_one_dir(str(book_dir))

    pdf_bytes = Path(results[0]["pdf_path"]).read_bytes()
    assert b"/ASCII85Decode" not in pdf_bytes
    assert b"/DCTDecode" in pdf_bytes


def test_converted_png_pdf_has_no_ascii85_filter(tmp_path):
    # PNG/raw 路径(loadImageFromA85/loadImageFromRaw):同样不应再套 ASCII85Decode。
    book_dir = tmp_path / "book"
    book_dir.mkdir()
    Image.new("RGB", (60, 80), (10, 20, 30)).save(book_dir / "p00.png")

    results = image2pdf.convert_images2PDF_one_dir(str(book_dir))

    pdf_bytes = Path(results[0]["pdf_path"]).read_bytes()
    assert b"/ASCII85Decode" not in pdf_bytes


# ---------------------------------------------------------------------------
# PyInstaller 打包: 冻结后 __file__/sys._MEIPASS 的行为和源码运行时不一样,
# _default_data_dir()/_resource_dir() 就是为了在两种环境下都取到正确路径。
# 不需要真的打包成 exe 也能测: 用 monkeypatch 模拟 sys.frozen/sys._MEIPASS。
# ---------------------------------------------------------------------------

def test_default_data_dir_source_run_is_repo_webdata(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert web_gallery._default_data_dir() == os.path.join(web_gallery.BASE_DIR, "webdata")


def test_default_data_dir_frozen_is_next_to_exe(monkeypatch, tmp_path):
    fake_exe = tmp_path / "dist" / "image2PDF-web.exe"
    fake_exe.parent.mkdir(parents=True)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(fake_exe))

    assert web_gallery._default_data_dir() == str(fake_exe.parent / "webdata")


def test_resource_dir_source_run_is_webapp_dir(monkeypatch):
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    assert webapp._resource_dir() == os.path.dirname(os.path.abspath(webapp.__file__))


def test_resource_dir_frozen_is_meipass(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    assert webapp._resource_dir() == str(tmp_path)
