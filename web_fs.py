# -*- coding: utf-8 -*-
"""
本地文件系统浏览与路径校验,供 webapp.py 的目录选择器使用。

只在 Windows 上做盘符枚举(用 GetLogicalDrives/GetDriveTypeW),其余平台退化为单个 "/" 根。
这是一个只在 127.0.0.1 上跑的本地小工具,这里的"校验"目的不是把用户关进某个目录里
(浏览器本来就有意暴露整棵目录树),而是避免几个已知会踩坑的地方:

- os.path.abspath("C:") 在 Windows 上返回的是"当前工作目录"而不是 "C:\\",
  所以裸盘符必须手动补 os.sep,并且绝不能对用户输入调用 abspath()。
- os.path.dirname("C:\\") 的结果还是 "C:\\" (不动点),用来判断"是否已经在盘符根"。
- os.scandir 在系统保留目录(如 $RECYCLE.BIN、System Volume Information)或断开的
  可移动介质上可能抛 PermissionError / OSError,要让调用方能优雅处理,而不是 500。
"""

import ctypes
import os
import string

import Image2PDF as image2pdf

# Image2PDF.__isAllow_file / __has_top_level_images 是模块级私有函数。
# 名称改编(name mangling)只发生在 class 定义体内的代码里,这里是模块级代码,
# 所以可以直接按字面名字访问,不会被改成 _Image2PDF__isAllow_file 之类的名字
# (与 test/filename_sort_test.py 里 image2pdf.__isAllow_file 的用法一致)。
# 通过 getattr 而不是重写一份扩展名白名单,避免两边逻辑drift。
_isAllow_file = image2pdf.__isAllow_file
_has_top_level_images = image2pdf.__has_top_level_images

# Windows FILE_ATTRIBUTE_* 常量
_FILE_ATTRIBUTE_HIDDEN = 0x2
_FILE_ATTRIBUTE_SYSTEM = 0x4

# GetDriveType 返回值
DRIVE_UNKNOWN = 0
DRIVE_NO_ROOT_DIR = 1
DRIVE_REMOVABLE = 2
DRIVE_FIXED = 3
DRIVE_REMOTE = 4
DRIVE_CDROM = 5
DRIVE_RAMDISK = 6

_DRIVE_TYPE_NAMES = {
    DRIVE_REMOVABLE: "removable",
    DRIVE_FIXED: "fixed",
    DRIVE_REMOTE: "remote",
    DRIVE_CDROM: "cdrom",
    DRIVE_RAMDISK: "ramdisk",
}


class PathError(ValueError):
    """用户提供的路径不合法(不存在 / 不是目录 / 不是绝对路径等)。"""


def list_drives():
    """
    列出本机可用的盘符。使用 GetLogicalDrives 位掩码而不是逐个 os.path.exists("A:\\"),
    因为对着空的光驱或断开的网络映射盘做 exists() 可能卡好几秒甚至弹系统对话框。
    """
    if os.name != "nt":
        return [{"name": "/", "path": "/", "type": "fixed"}]

    kernel32 = ctypes.windll.kernel32
    mask = kernel32.GetLogicalDrives()
    drives = []
    for i, letter in enumerate(string.ascii_uppercase):
        if not (mask >> i) & 1:
            continue
        root = "%s:%s" % (letter, os.sep)
        dtype = kernel32.GetDriveTypeW(root)
        if dtype in (DRIVE_UNKNOWN, DRIVE_NO_ROOT_DIR):
            continue
        drives.append({
            "name": letter + ":",
            "path": root,
            "type": _DRIVE_TYPE_NAMES.get(dtype, "unknown"),
        })
    return drives


def normalize_dir(raw):
    """
    规范化用户输入(粘贴框 / 面包屑 / 上一级)得到的路径字符串,返回一个存在的绝对目录路径。
    不合法时抛 PathError,附带中文错误信息。

    刻意不对相对路径调用 abspath() —— 那样会静默解析到服务器进程的当前工作目录
    (也就是这个仓库所在目录),对用户来说是一个非常confusing的失败模式。
    """
    if raw is None:
        raise PathError("路径为空")

    p = raw.strip().strip('"').strip("'")
    if not p:
        raise PathError("路径为空")

    p = os.path.expanduser(p)

    # 'C:' -> 'C:\\' ; 直接 abspath('C:') 在 Windows 上会返回当前工作目录,而不是盘符根
    if os.name == "nt" and len(p) == 2 and p[1] == ":" and p[0].isalpha():
        p = p + os.sep

    if not os.path.isabs(p):
        raise PathError("请输入绝对路径")

    p = os.path.normpath(p)

    if not os.path.isdir(p):
        raise PathError("路径不存在或不是文件夹: %s" % p)

    return p


def parent_of(path):
    """
    返回上一级目录路径;如果已经在盘符根(dirname 是不动点),返回 None,
    表示前端应该切换回盘符列表,而不是显示一个点了没反应的按钮。
    """
    parent = os.path.dirname(path)
    if not parent or parent == path:
        return None
    return parent


def breadcrumbs(path):
    """把路径拆成面包屑列表 [{"name","path"}, ...],点击任意一段可以跳转过去。"""
    drive, rest = os.path.splitdrive(path)
    parts = [seg for seg in rest.split(os.sep) if seg]

    crumbs = []
    if drive:
        crumbs.append({"name": drive + os.sep, "path": drive + os.sep})

    current = drive + os.sep if drive else os.sep
    for part in parts:
        current = os.path.join(current, part)
        crumbs.append({"name": part, "path": current})

    return crumbs


def _is_hidden(entry):
    if os.name != "nt":
        return entry.name.startswith(".")
    try:
        attrs = entry.stat(follow_symlinks=False).st_file_attributes
    except (OSError, AttributeError):
        return False
    return bool(attrs & (_FILE_ATTRIBUTE_HIDDEN | _FILE_ATTRIBUTE_SYSTEM))


def list_dir(path, show_hidden=False):
    """
    列出 path 下的直接子目录(不含文件)。

    返回 (dirs, errors):
    - dirs: [{"name","path"}, ...] 按名称排序(不区分大小写)
    - errors: 迭代过程中遇到的、被跳过的错误信息列表(不会中断整体列举)

    调用方需要自行捕获顶层的 PermissionError / OSError(例如 path 本身不可读),
    这里只处理"目录内某一项读取失败"这种可以降级为部分结果的情况。
    """
    dirs = []
    errors = []

    it = os.scandir(path)  # 这里的 PermissionError 交给调用方处理 -> 403
    with it:
        while True:
            try:
                entry = next(it)
            except StopIteration:
                break
            except OSError as exc:
                errors.append(str(exc))
                break

            try:
                if not entry.is_dir(follow_symlinks=False):
                    continue
                if not show_hidden and _is_hidden(entry):
                    continue
            except OSError:
                # 常见于损坏的重解析点(reparse point) / 断开的网络挂载点
                continue

            dirs.append({"name": entry.name, "path": entry.path})

    dirs.sort(key=lambda d: d["name"].lower())
    return dirs, errors


def preview(path, max_dirs=2000):
    """
    预览"如果现在转换这个目录,会发生什么",镜像 Image2PDF.convert_images2PDF_auto 的判断规则:
    - 顶层直接有图片 -> mode="one_dir", 会生成 1 个 PDF
    - 顶层没有图片,只有子目录 -> mode="more_dirs", 遍历统计每个含图片的子目录

    注意: 这个函数只应该在用户点击"使用此目录"时调用一次,不要接到 /api/browse 里
    (否则每次点击都walk一遍可能是几万级文件的目录树,会卡住界面)。
    """
    if _has_top_level_images(path):
        count = 0
        for name in os.listdir(path):
            full = os.path.join(path, name)
            if os.path.isfile(full) and _isAllow_file(full):
                count += 1
        return {
            "mode": "one_dir",
            "book_count": 1,
            "books": [{"name": os.path.basename(path), "pages": count}],
            "truncated": False,
        }

    books = []
    truncated = False
    for parent, dirnames, filenames in os.walk(path, onerror=lambda e: None):
        count = sum(1 for f in filenames if _isAllow_file(os.path.join(parent, f)))
        if count > 0:
            books.append({"name": os.path.basename(parent) or parent, "pages": count})
            if len(books) >= max_dirs:
                truncated = True
                break

    return {
        "mode": "more_dirs" if books else "empty",
        "book_count": len(books),
        "books": books,
        "truncated": truncated,
    }
