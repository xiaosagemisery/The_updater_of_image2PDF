# -*- coding: utf-8 -*-
"""
本地网页界面: 在浏览器里选一个本机文件夹,调用 Image2PDF 里完全不变的转换逻辑,
转换完成后把每本书的封面追加展示到 Gallery 里。

只监听 127.0.0.1,是给单机用户自用的小工具,不是对外服务:
- 不做用户认证,靠"只有本机能连上"这一点做边界。
- 目录浏览接口本来就是要暴露整个文件系统树给用户自己看,所以这里的校验重点
  不是"把用户关起来",而是防跨源请求(见 _check_host / _require_json)和防路径穿越
  (封面必须走 send_from_directory,不能拼接用户传入的绝对路径)。
"""

import os
import sys
import threading
import time
import traceback
import uuid
import webbrowser

from flask import Flask, jsonify, render_template, request, send_from_directory
from werkzeug.exceptions import HTTPException

import Image2PDF as image2pdf
import web_fs
import web_gallery


def _resource_dir():
    """
    templates/static 这两个目录所在的位置。源码运行时就是本文件所在目录(和
    Flask(__name__) 默认推算的位置一样)。PyInstaller onefile 冻结后,这两个
    目录会被解压到 sys._MEIPASS 这个临时目录下,Flask 靠 __file__ 做的默认推算
    在冻结环境里不可靠,必须显式指过去,否则打开页面直接 TemplateNotFound。
    """
    return getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))


app = Flask(__name__,
            template_folder=os.path.join(_resource_dir(), "templates"),
            static_folder=os.path.join(_resource_dir(), "static"))


# ---------------------------------------------------------------------------
# 任务(转换)注册表: 单任务、后台线程 + 轮询,足够本地小工具使用,
# 不需要引入队列/Celery 之类的重量级方案。
# ---------------------------------------------------------------------------

_jobs_lock = threading.Lock()
_jobs = {}
_running_job_id = None


def _compute_percent(book_number, book_total, page_done, page_total):
    """
    根据"当前是第几本书/总共几本书"(1-based)和"当前书渲染到第几页/总共几页",
    算出一个 0-100 的整体百分比。page_total 为 0/None 时视为当前书还没有页级数据,
    这一本贡献 0 进度。抽成纯函数是为了不用真的跑一次转换也能单独测试这个公式。
    """
    fraction = ((book_number - 1) + (page_done / page_total if page_total else 0)) / book_total
    return min(100, round(fraction * 100))


def _new_job(path, mode_hint, total_hint, double_page=False, right_page_first=True,
             split_as_jpeg=False):
    job_id = "job-%s" % uuid.uuid4().hex[:12]
    _jobs[job_id] = {
        "id": job_id,
        "status": "running",
        "path": path,
        "mode": mode_hint,
        "total": total_hint,
        "done": 0,
        "current": None,
        "item_ids": [],
        "double_page": double_page,
        "right_page_first": right_page_first,
        "split_as_jpeg": split_as_jpeg,
        "page_done": None,
        "page_total": None,
        "percent": 0,
        "started_at": time.time(),
        "finished_at": None,
        "error": None,
    }
    return job_id


def _run_conversion(job_id, path, double_page=False, right_page_first=True, split_as_jpeg=False):
    try:
        def on_book_done(result, done, total):
            item = web_gallery.upsert_result(result, batch_id=job_id)
            with _jobs_lock:
                job = _jobs.get(job_id)
                if job is None:
                    return
                job["done"] = done
                job["total"] = total
                job["current"] = result["pdf_name"]
                job["item_ids"].append(item["id"])
                # 每完成一本书就把百分比对齐一次,避免逐页累积的浮点误差让它卡在 99%
                job["percent"] = round(done / total * 100) if total else 100

        def on_page_progress(book_number, book_total, page_done, page_total):
            with _jobs_lock:
                job = _jobs.get(job_id)
                if job is None:
                    return
                job["page_done"] = page_done
                job["page_total"] = page_total
                job["percent"] = _compute_percent(book_number, book_total, page_done, page_total)

        mode, results = image2pdf.convert_images2PDF_auto(
            path, on_book_done=on_book_done, on_page_progress=on_page_progress,
            double_page=double_page, right_page_first=right_page_first,
            split_as_jpeg=split_as_jpeg)

        with _jobs_lock:
            job = _jobs.get(job_id)
            if job is not None:
                if len(results) == 0:
                    # /api/convert 不再提前做一次全树遍历来判断"目录里到底有没有图片"
                    # (那次遍历本身就是"准备很久才开始转换"的主因之一),所以这个判断
                    # 挪到这里、拿到 convert_images2PDF_auto 的真实结果之后再做。
                    job["status"] = "error"
                    job["error"] = "该目录及其子目录下没有找到任何图片文件"
                else:
                    job["status"] = "done"
                    job["mode"] = mode
                    job["total"] = len(results)
                    job["done"] = len(results)
                    job["percent"] = 100
                job["finished_at"] = time.time()
    except Exception:
        with _jobs_lock:
            job = _jobs.get(job_id)
            if job is not None:
                job["status"] = "error"
                job["error"] = traceback.format_exc()
                job["finished_at"] = time.time()
    finally:
        global _running_job_id
        with _jobs_lock:
            if _running_job_id == job_id:
                _running_job_id = None


# ---------------------------------------------------------------------------
# 安全: Host 头白名单 + 仅接受 JSON 的写操作,细节见模块顶部注释
# ---------------------------------------------------------------------------

@app.before_request
def _check_host():
    # 只看主机名部分,和实际监听端口无关;这样能挡住 DNS rebinding
    # (恶意网页把自己的域名解析到 127.0.0.1,借受害者的浏览器读本机目录树)
    host = request.host.split(":")[0]
    if host not in ("127.0.0.1", "localhost"):
        return jsonify({"error": "禁止访问"}), 403


def _require_json():
    if not request.is_json:
        return jsonify({"error": "请求必须是 application/json"}), 415
    return None


@app.after_request
def _no_cache_api(resp):
    if request.path.startswith("/api/"):
        resp.headers["Cache-Control"] = "no-store"
    return resp


@app.errorhandler(Exception)
def _handle_error(exc):
    # 保证前端永远只需要解析 JSON,不用去处理 Werkzeug 的 HTML traceback 页。
    # HTTPException(404/405 等 Flask/Werkzeug 自己抛出的路由错误)要保留其
    # 真实状态码,否则例如访问一个不存在的路由也会被这里错误地报成 500。
    if isinstance(exc, HTTPException):
        return jsonify({"error": exc.description or exc.name}), exc.code
    return jsonify({"error": str(exc) or exc.__class__.__name__}), 500


# ---------------------------------------------------------------------------
# 页面
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")


# ---------------------------------------------------------------------------
# 目录浏览 API
# ---------------------------------------------------------------------------

@app.route("/api/drives")
def api_drives():
    return jsonify({"drives": web_fs.list_drives()})


@app.route("/api/browse")
def api_browse():
    raw = request.args.get("path", "")
    show_hidden = request.args.get("show_hidden") == "1"

    if not raw:
        return jsonify({
            "path": None,
            "parent": None,
            "at_root": True,
            "breadcrumbs": [],
            "dirs": web_fs.list_drives(),
            "errors": [],
            "is_drive_list": True,
        })

    try:
        path = web_fs.normalize_dir(raw)
    except web_fs.PathError as exc:
        return jsonify({"error": str(exc)}), 400

    try:
        dirs, errors = web_fs.list_dir(path, show_hidden=show_hidden)
    except PermissionError:
        return jsonify({
            "error": "没有权限读取该目录",
            "path": path,
            "parent": web_fs.parent_of(path),
        }), 403
    except OSError as exc:
        return jsonify({"error": str(exc), "path": path}), 400

    parent = web_fs.parent_of(path)
    return jsonify({
        "path": path,
        "parent": parent,
        "at_root": parent is None,
        "breadcrumbs": web_fs.breadcrumbs(path),
        "dirs": dirs,
        "errors": errors,
        "is_drive_list": False,
    })


@app.route("/api/preview")
def api_preview():
    raw = request.args.get("path", "")
    try:
        path = web_fs.normalize_dir(raw)
    except web_fs.PathError as exc:
        return jsonify({"error": str(exc)}), 400

    try:
        result = web_fs.preview(path)
    except PermissionError:
        return jsonify({"error": "没有权限读取该目录"}), 403

    result["path"] = path
    return jsonify(result)


# ---------------------------------------------------------------------------
# 转换任务 API
# ---------------------------------------------------------------------------

@app.route("/api/convert", methods=["POST"])
def api_convert():
    err = _require_json()
    if err:
        return err

    body = request.get_json(silent=True) or {}
    raw = body.get("path", "")
    try:
        path = web_fs.normalize_dir(raw)
    except web_fs.PathError as exc:
        return jsonify({"error": str(exc)}), 400

    double_page = bool(body.get("double_page", False))
    right_page_first = bool(body.get("right_page_first", True))
    if double_page and "right_page_first" not in body:
        return jsonify({"error": "开启双页模式时必须指定哪边页码小(right_page_first)"}), 400
    # split_as_jpeg 有安全的默认值(False=无损 PNG,和原来的行为一样),不需要像
    # right_page_first 那样强制要求前端必须显式带上这个字段。
    split_as_jpeg = bool(body.get("split_as_jpeg", False))

    global _running_job_id
    with _jobs_lock:
        if _running_job_id is not None:
            return jsonify({"error": "已有任务在运行", "job_id": _running_job_id}), 409

        # 这里不再调用 web_fs.preview(path) 做一次递归的全树遍历统计页数——那是"点了
        # 开始转换之后迟迟没反应"的主因,而且 /api/preview 在用户点"使用此目录"时已经
        # 走过一次、马上 convert_images2PDF_auto 内部自己的遍历又要走一次,重复了三次。
        # 这里只做一次廉价的顶层判断猜一下 mode,真实的 book 数量在后台线程真正跑起来、
        # on_book_done/on_page_progress 拿到第一次真实数据时会自动纠正 job["total"]。
        try:
            mode_hint = "one_dir" if web_fs._has_top_level_images(path) else "more_dirs"
        except PermissionError:
            return jsonify({"error": "没有权限读取该目录"}), 403

        job_id = _new_job(path, mode_hint, 1, double_page=double_page,
                           right_page_first=right_page_first, split_as_jpeg=split_as_jpeg)
        _running_job_id = job_id

    thread = threading.Thread(
        target=_run_conversion,
        args=(job_id, path, double_page, right_page_first, split_as_jpeg),
        daemon=True)
    thread.start()

    return jsonify({"job_id": job_id}), 202


@app.route("/api/jobs/<job_id>")
def api_job_status(job_id):
    with _jobs_lock:
        job = _jobs.get(job_id)
        if job is None:
            return jsonify({"error": "任务不存在"}), 404
        return jsonify(dict(job))


# ---------------------------------------------------------------------------
# Gallery API
# ---------------------------------------------------------------------------

@app.route("/api/gallery")
def api_gallery():
    items = web_gallery.list_items()
    out = []
    for it in items:
        entry = dict(it)
        if it.get("cover_file"):
            entry["cover_url"] = "/covers/%s?v=%s" % (it["cover_file"], it["updated_at"])
        else:
            entry["cover_url"] = None
        out.append(entry)
    # 保持追加顺序(旧的在前,新的在后),与"依次追加为下一项"的要求一致
    return jsonify({"items": out})


@app.route("/api/gallery/<item_id>", methods=["DELETE"])
def api_gallery_delete(item_id):
    ok = web_gallery.delete_item(item_id)
    if not ok:
        return jsonify({"error": "记录不存在"}), 404
    return jsonify({"ok": True})


@app.route("/covers/<path:filename>")
def covers(filename):
    # 必须用 send_from_directory,不能拼接用户可控的绝对路径,
    # 否则"浏览封面"会变成一个任意文件读取漏洞
    return send_from_directory(web_gallery.cover_path(filename), filename)


def main():
    port = int(os.environ.get("PORT", 5000))
    url = "http://127.0.0.1:%d" % port
    print("[*] image2PDF 网页界面已启动: %s" % url)
    threading.Timer(1.0, lambda: webbrowser.open(url)).start()

    # use_reloader=False: reloader 会重新执行整个模块,产生两份任务/Gallery状态,
    # 轮询请求会随机打到某一个进程,必须关掉。
    app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False, threaded=True)


if __name__ == "__main__":
    main()
