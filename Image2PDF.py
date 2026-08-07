import argparse
import os
import shutil
import tempfile
import time
from PIL import Image as pilImage
from reportlab.pdfgen import canvas

# 支持的图片类型
__allow_type = {".jpg", ".jpeg", ".bmp", ".png"}

__rootDir = ""

# 页级转换进度钩子: 调用方(convert_images2PDF_one_dir/more_dirs)在调用 __converted 前设置,
# __converted 每渲染完一页就会调用它上报 (page_done, page_total)。用模块级变量而不是给
# __converted 加参数,是为了不改变它的调用签名——test/filename_sort_test.py 里
# monkeypatch.setattr(image2pdf, "__converted", fake_convert) 会把 __converted 整个替换掉,
# 这段读钩子的代码在被 mock 时根本不会执行,所以不影响现有测试。
__page_progress_hook = None

def convert_images2PDF_one_dir(file_dir, save_name=None, filename_sort_fn=None, on_book_done=None,
                                double_page=False, right_page_first=True, on_page_progress=None):
    '''
    转换一个目录文件夹下的图片至 PDF
    :param file_dir:
    :param file_name: 如果为空,则以当前文件夹的名称命名, 必须是.pdf结尾
    :param filename_sort_fn:
    文件名排序的回调函数,当此回调函数有值时,在文件名排序时,会回调,并将 file 的完整路径返回。
    回调函数需要返回一个可转换整形的内容,函数根据此回调函数的返回值,对文件名排序

    比如:
        现实中,文件名会是
        test_01_doc_0.png、
        test_01_doc_1.png、
        test_01_doc_2.png、
        test_01_doc_3.png、
        test_01_doc_11.png、
        test_01_doc_21.png
        等等,我们也希望读取出来的顺序如此,但是 mac、win 下,包括sort 排序出来的结果都不理想。

        结果为
        test_01_doc_0.png、
        test_01_doc_1.png、
        test_01_doc_11.png、
        test_01_doc_2.png、
        test_01_doc_21.png、
        test_01_doc_3.png

        不是我们想要得到的。

        通过 filename_sort_fn(filename) 返回的整形数字,对齐正确的排序
    :param on_book_done:
    每转换完一本书后的回调函数,签名为 on_book_done(result, done_count, total_count),
    result 见 __make_result。供 Web 界面等调用方获取转换结果 / 展示进度使用,默认不启用。
    :param double_page:
    图片内容是否为双页拼图(一张图其实是左右拼在一起的两页),为 True 时会先把 file_dir 下
    每一张图沿垂直中线左右各切成一页,再拼进 PDF,不影响 __converted 的调用方式(见 __split_double_page_images)。
    :param right_page_first:
    仅在 double_page=True 时生效: True 表示每张拼图里右半边代表的页码更小(应排在前面,
    如从右往左翻的漫画),False 表示左半边页码更小(如从左往右翻的漫画)。
    :param on_page_progress:
    页级转换进度回调,签名为 on_page_progress(book_number, book_total, page_done, page_total),
    在当前这本书渲染每一页时都会触发一次(通过 __page_progress_hook 挂到 __converted 内部循环上)。
    本函数只处理单本书,所以 book_number/book_total 恒为 1。默认不启用。
    :return: 本次转换生成的结果列表(见 __make_result),没有图片时为空列表
    '''
    book_pages = []
    results = []

    for parent, dirnames, filenames in os.walk(file_dir):

        # 只遍历最顶层
        if parent != file_dir :
            continue

        # 过滤文件中所有的图片
        for file_name in filenames:
            file_path = os.path.join(parent, file_name)
            # 是否图片
            if __isAllow_file(file_path) :
                book_pages.append(file_path)

        # 取当前目录的文件名为书名
        if save_name is None:
            pdf_save_name = os.path.join(file_dir, (os.path.basename(file_dir) + ".pdf"))
        else :
            pdf_save_name = os.path.join(file_dir, save_name)

        if len(book_pages) > 0 :
            convert_pages = book_pages
            convert_sort_fn = filename_sort_fn
            temp_dir = None
            global __page_progress_hook
            try:
                if double_page:
                    ordered_pages = __sort_pages(book_pages, filename_sort_fn)
                    convert_pages, temp_dir = __split_double_page_images(ordered_pages, right_page_first)
                    convert_sort_fn = None  # 展开后的临时文件名已经是最终顺序,不需要再排序

                if on_page_progress is not None:
                    __page_progress_hook = lambda page_done, page_total: on_page_progress(
                        1, 1, page_done, page_total)

                # 开始转换
                print("[*][转换PDF] : 开始. [保存路径] > [%s]" % (pdf_save_name))
                beginTime = time.perf_counter()
                __converted(pdf_save_name, convert_pages, convert_sort_fn)
                endTime = time.perf_counter()
                print("[*][转换PDF] : 结束. [保存路径] > [%s] , 耗时 %f s " % (pdf_save_name, (endTime - beginTime)))
                result = __make_result(pdf_save_name, file_dir, convert_pages, convert_sort_fn)
                results.append(result)
                if on_book_done is not None:
                    on_book_done(result, len(results), 1)
            finally:
                __page_progress_hook = None
                if temp_dir is not None:
                    shutil.rmtree(temp_dir, ignore_errors=True)
        else :
            print("该目录下没有找到任何图片文件.如果是多重目录,尝试使用 convert_images2PDF_more_dirs 函数")

    return results


def convert_images2PDF_more_dirs(dirPath, filename_sort_fn=None, on_book_done=None,
                                  double_page=False, right_page_first=True, on_page_progress=None):
    """
    转换一个目录文件夹下的图片至 PDF
    :param file_dir:
    :param filename_sort_fn:
    :param on_book_done:
    每转换完一本书后的回调函数,签名为 on_book_done(result, done_count, total_count),
    result 见 __make_result。供 Web 界面等调用方获取转换结果 / 展示进度使用,默认不启用。
    :param double_page: 见 convert_images2PDF_one_dir,对本次批量转换里的每一本书统一生效。
    :param right_page_first: 见 convert_images2PDF_one_dir。
    :param on_page_progress:
    页级转换进度回调,签名为 on_page_progress(book_number, book_total, page_done, page_total),
    在正在转换的这一本书渲染每一页时都会触发一次;book_number 是当前是第几本(1-based),
    book_total 是本次批量转换总共有几本。默认不启用。
    :return: 本次转换生成的结果列表(见 __make_result)
    """

    # 已经找到目录
    dirs = {}

    for parent, dirnames, filenames in os.walk(dirPath):
        # 查找有无图片
        for filename in filenames:
            real_filename = os.path.join(parent, filename)

            # 检查是否图片
            if __isAllow_file(real_filename) :
                # 将图片添加至书本
                dirs.setdefault(parent, []).append(real_filename)

    index = 1
    used_names = set()
    results = []
    for dir_path in sorted(dirs.keys()):

        pages = dirs[dir_path]
        dirName = os.path.basename(dir_path)
        save_name = __unique_pdf_name(dirPath, dir_path, used_names)

        convert_pages = pages
        convert_sort_fn = filename_sort_fn
        temp_dir = None
        global __page_progress_hook
        try:
            if double_page:
                ordered_pages = __sort_pages(pages, filename_sort_fn)
                convert_pages, temp_dir = __split_double_page_images(ordered_pages, right_page_first)
                convert_sort_fn = None

            if on_page_progress is not None:
                book_number = len(results) + 1
                book_total = len(dirs)
                __page_progress_hook = lambda page_done, page_total, _bn=book_number, _bt=book_total: (
                    on_page_progress(_bn, _bt, page_done, page_total))

            print("[*][转换PDF] : 开始. [名称] > [%s]" % (dirName))
            beginTime = time.perf_counter()
            __converted(save_name, convert_pages, convert_sort_fn)
            endTime = time.perf_counter()
            print("[*][转换PDF] : 结束. [名称] > [%s] , 耗时 %f s " % (dirName, (endTime - beginTime)))
            result = __make_result(save_name, dir_path, convert_pages, convert_sort_fn)
            results.append(result)
            if on_book_done is not None:
                on_book_done(result, len(results), len(dirs))
        finally:
            __page_progress_hook = None
            if temp_dir is not None:
                shutil.rmtree(temp_dir, ignore_errors=True)
        index += 1

    print("[*][所有转换完成] : 本次转换检索目录数 %d 个，共转换的PDF %d 本 " % (len(dirs), index - 1))

    return results


def convert_images2PDF_auto(dir_path, filename_sort_fn=None, on_book_done=None,
                             double_page=False, right_page_first=True, on_page_progress=None):
    """
    按 __main__ 使用的规则自动判断:
    根目录顶层本身有图片 -> 当作一本书,调用 convert_images2PDF_one_dir;
    根目录顶层没有图片,只有子目录(例如按册划分的漫画) -> 调用 convert_images2PDF_more_dirs,
    为每个含图片的子目录各生成一个PDF。
    :param dir_path:
    :param filename_sort_fn:
    :param on_book_done: 见 convert_images2PDF_one_dir / convert_images2PDF_more_dirs
    :param double_page: 见 convert_images2PDF_one_dir
    :param right_page_first: 见 convert_images2PDF_one_dir
    :param on_page_progress: 见 convert_images2PDF_one_dir / convert_images2PDF_more_dirs
    :return: (mode, results) , mode 为 "one_dir" 或 "more_dirs"
    """
    if __has_top_level_images(dir_path):
        return "one_dir", convert_images2PDF_one_dir(
            dir_path, save_name=None,
            filename_sort_fn=filename_sort_fn, on_book_done=on_book_done,
            double_page=double_page, right_page_first=right_page_first,
            on_page_progress=on_page_progress)

    return "more_dirs", convert_images2PDF_more_dirs(
        dir_path, filename_sort_fn=filename_sort_fn, on_book_done=on_book_done,
        double_page=double_page, right_page_first=right_page_first,
        on_page_progress=on_page_progress)


def __isAllow_file(filepath):
    """
    是否允许的文件
    :param file:
    :return:
    """
    if filepath and (os.path.splitext(filepath)[1].lower() in __allow_type):
        return True

    return False



def __unique_pdf_name(root_dir, image_dir, used_names):
    base_name = os.path.basename(image_dir) or os.path.basename(os.path.abspath(image_dir))
    pdf_name = base_name + ".pdf"

    if pdf_name in used_names:
        relative_name = os.path.relpath(image_dir, root_dir).replace(os.sep, "_")
        pdf_name = relative_name + ".pdf"

    stem, ext = os.path.splitext(pdf_name)
    suffix = 2
    while pdf_name in used_names:
        pdf_name = "%s_%d%s" % (stem, suffix, ext)
        suffix += 1

    used_names.add(pdf_name)
    return os.path.join(root_dir, pdf_name)


def __sort_pages(book_pages, filename_sort_fn=None):
    if filename_sort_fn is None:
        return sorted(book_pages)

    return sorted(book_pages, key=lambda name: int(filename_sort_fn(name)))


def __make_result(pdf_path, source_dir, pages, filename_sort_fn=None):
    """
    构造一次单本转换的结果描述,供调用方(如 Web 界面)使用,不影响 __converted 本身的行为。
    这里对 pages 重新排序一遍(和 __converted 内部排序逻辑一致),只是为了拿到"排序后的第一页",
    即将来会成为 PDF 第一页的那张源图,用作封面。
    """
    sorted_pages = __sort_pages(pages, filename_sort_fn)
    return {
        "pdf_path": pdf_path,
        "pdf_name": os.path.basename(pdf_path),
        "source_dir": source_dir,
        "page_count": len(sorted_pages),
        "first_page": sorted_pages[0] if sorted_pages else None,
    }


def __split_double_page_images(sorted_pages, right_page_first):
    """
    把已经按最终阅读顺序排好的整页图片列表,逐张沿垂直中线切成左右两半,存到一个
    临时目录里,并按 right_page_first 决定每一对里谁的页码更小、谁排在前面。

    临时文件名用零填充的序号前缀(00000_a.png / 00000_b.png / 00001_a.png ...),
    保证 __converted 内部再次执行的默认 sorted() 不会打乱这里已经确定好的最终顺序,
    因此调用方之后应该把 filename_sort_fn 传 None 给 __converted / __make_result。

    :param sorted_pages: 已经排好序的原始整页图片路径列表
    :param right_page_first: True=每张拼图右半边页码更小(排前面); False=左半边页码更小
    :return: (expanded_pages, temp_dir), expanded_pages 是展开后的临时文件路径列表(已是最终顺序),
             temp_dir 是存放这些临时文件的目录,调用方转换结束后必须自行删除。
    """
    temp_dir = tempfile.mkdtemp(prefix="image2pdf_split_")
    expanded = []

    for index, page in enumerate(sorted_pages):
        with pilImage.open(page) as img:
            width, height = img.size
            mid = width // 2
            left_half = img.crop((0, 0, mid, height))
            right_half = img.crop((mid, 0, width, height))
            left_half.load()
            right_half.load()

        if right_page_first:
            first_half, first_label = right_half, "右半"
            second_half, second_label = left_half, "左半"
        else:
            first_half, first_label = left_half, "左半"
            second_half, second_label = right_half, "右半"

        first_path = os.path.join(temp_dir, "%05d_a.png" % index)
        second_path = os.path.join(temp_dir, "%05d_b.png" % index)
        first_half.save(first_path)
        second_half.save(second_path)

        print("[*][拆分双页] : %s -> %s(page%d) + %s(page%d)" % (
            os.path.basename(page), first_label, index * 2 + 1, second_label, index * 2 + 2))

        expanded.append(first_path)
        expanded.append(second_path)

    return expanded, temp_dir


def __converted(save_book_name, book_pages=None, filename_sort_fn=None):
    """
    开始转换
    :param book_name: 保存的文件名(包含路径)
    :param book_pages: 图片数组
    :param filename_sort_fn: 文件名排序规则
    :return:
    """

    # 对数据进行排序
    book_pages = __sort_pages(book_pages or [], filename_sort_fn)
    total_pages = len(book_pages)

    # 使用Canvas来创建PDF，因为需要为每页单独设置大小
    c = canvas.Canvas(save_book_name)

    for index, page in enumerate(book_pages):
        with pilImage.open(page) as img:
            img_w, img_h = img.size

            # 为当前页面设置尺寸
            c.setPageSize((img_w, img_h))

            # 将图片添加到页面
            c.drawImage(page, 0, 0, width=img_w, height=img_h)
            c.showPage()  # 结束当前页并开始新的一页

        if __page_progress_hook is not None:
            __page_progress_hook(index + 1, total_pages)

    # 保存PDF文件
    c.save()

    print("[*][转换PDF] : 已保存. [路径] > [%s]" % save_book_name)



class ImageTools:
    def getImageSize(self, imagePath):
        with pilImage.open(imagePath) as img:
            return img.size

def __has_top_level_images(dir_path):
    return any(
        __isAllow_file(os.path.join(dir_path, name))
        for name in os.listdir(dir_path)
        if os.path.isfile(os.path.join(dir_path, name))
    )


def __build_arg_parser():
    parser = argparse.ArgumentParser(description="将文件夹里的图片批量转换为 PDF")
    parser.add_argument(
        "--double-page", action="store_true", dest="double_page",
        help="图片内容是双页拼图(一张图其实是左右拼在一起的两页),转换时会先把每张图沿垂直中线切成两页")

    order_group = parser.add_mutually_exclusive_group()
    order_group.add_argument(
        "--right-first", action="store_true", dest="right_first",
        help="配合 --double-page 使用: 每张拼图里右半边代表的页码更小,应排在前面(如从右往左翻的漫画)")
    order_group.add_argument(
        "--left-first", action="store_true", dest="left_first",
        help="配合 --double-page 使用: 每张拼图里左半边代表的页码更小,应排在前面(如从左往右翻的漫画)")

    return parser


def __validate_cli_args(parser, args):
    if args.double_page and not (args.right_first or args.left_first):
        parser.error("使用 --double-page 时必须同时指定 --right-first 或 --left-first 之一")


if __name__ == "__main__":
    cli_parser = __build_arg_parser()
    cli_args = cli_parser.parse_args()
    __validate_cli_args(cli_parser, cli_args)

    dir_path = input("请输入图片所在的文件夹路径: ").strip().strip('"')

    if not os.path.isdir(dir_path):
        print("[!][错误] 路径不存在或不是一个文件夹: %s" % dir_path)
    else:
        print("脚本开始执行...")
        convert_images2PDF_auto(
            dir_path,
            double_page=cli_args.double_page,
            right_page_first=cli_args.right_first,
        )
        print("脚本执行完成...")
