import os
import time
from PIL import Image as pilImage
from reportlab.pdfgen import canvas

# 支持的图片类型
__allow_type = {".jpg", ".jpeg", ".bmp", ".png"}

__rootDir = ""

def convert_images2PDF_one_dir(file_dir, save_name=None, filename_sort_fn=None):
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
    '''
    book_pages = []

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
            # 开始转换
            print("[*][转换PDF] : 开始. [保存路径] > [%s]" % (pdf_save_name))
            beginTime = time.perf_counter()
            __converted(pdf_save_name, book_pages, filename_sort_fn)
            endTime = time.perf_counter()
            print("[*][转换PDF] : 结束. [保存路径] > [%s] , 耗时 %f s " % (pdf_save_name, (endTime - beginTime)))
        else :
            print("该目录下没有找到任何图片文件.如果是多重目录,尝试使用 convert_images2PDF_more_dirs 函数")


def convert_images2PDF_more_dirs(dirPath, filename_sort_fn=None):
    """
    转换一个目录文件夹下的图片至 PDF
    :param file_dir:
    :param filename_sort_fn:
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
    for dir_path in sorted(dirs.keys()):

        pages = dirs[dir_path]
        dirName = os.path.basename(dir_path)
        save_name = __unique_pdf_name(dirPath, dir_path, used_names)

        print("[*][转换PDF] : 开始. [名称] > [%s]" % (dirName))
        beginTime = time.perf_counter()
        __converted(save_name, pages, filename_sort_fn)
        endTime = time.perf_counter()
        print("[*][转换PDF] : 结束. [名称] > [%s] , 耗时 %f s " % (dirName, (endTime - beginTime)))
        index += 1

    print("[*][所有转换完成] : 本次转换检索目录数 %d 个，共转换的PDF %d 本 " % (len(dirs), index - 1))


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

    # 使用Canvas来创建PDF，因为需要为每页单独设置大小
    c = canvas.Canvas(save_book_name)

    for page in book_pages:
        with pilImage.open(page) as img:
            img_w, img_h = img.size

            # 为当前页面设置尺寸
            c.setPageSize((img_w, img_h))

            # 将图片添加到页面
            c.drawImage(page, 0, 0, width=img_w, height=img_h)
            c.showPage()  # 结束当前页并开始新的一页

    # 保存PDF文件
    c.save()

    print("[*][转换PDF] : 已保存. [路径] > [%s]" % save_book_name)



class ImageTools:
    def getImageSize(self, imagePath):
        with pilImage.open(imagePath) as img:
            return img.size

if __name__ == "__main__":
    comic_path = r'Y:\Library\comic\龙珠'
    print("脚本开始执行...")
    convert_images2PDF_more_dirs(comic_path)
    print("脚本执行完成...")
