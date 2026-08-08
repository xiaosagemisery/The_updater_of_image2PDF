# CLAUDE.md

本文件为 Claude Code（claude.ai/code）在此仓库中工作时提供指导。

## 项目简介

一个小型 Python 工具，用于将目录中的图片（jpg/jpeg/bmp/png）批量转换为 PDF 文件，输出尺寸与每张源图片一致（因此在 Kindle/iPhone/iPad 等设备上显示效果更好）。核心转换逻辑在 `Image2PDF.py`，既可以直接以 CLI 方式运行（`input()` 提示输入文件夹路径），也可以通过 `webapp.py` 启动的本地网页界面使用（在页面里点选文件夹，转换完成后以 Gallery 形式查看每本书的封面）。依赖项列在 `requirements.txt` 中：`Pillow`（`PIL`）、`reportlab`、`Flask`，以及用于运行测试的 `pytest`。项目没有 pyproject.toml 或其他构建配置。

## 常用命令

安装依赖：

```
pip install -r requirements.txt
```

运行测试（pytest，默认发现机制，仓库根目录有一个空的 `conftest.py` 让裸 `pytest` 也能正确 import 顶层模块）：

```
pytest
```

运行单个测试：

```
pytest test/filename_sort_test.py::test_sort_pages_uses_callback_without_mutating_input
```

启动本地网页界面（默认监听 `http://127.0.0.1:5000`，只监听 127.0.0.1，不对外提供服务；可用 `PORT` 环境变量改端口，`IMAGE2PDF_DATA_DIR` 改 Gallery 数据存放目录）：

```
python webapp.py
```

CLI 方式运行（脚本内 `input()` 提示输入文件夹路径）：

```
python Image2PDF.py
```

CLI 方式运行，并开启双页拼图拆分（`--double-page` 必须搭配 `--right-first`/`--left-first` 之一使用，二者互斥，缺一会直接报错退出）：

```
python Image2PDF.py --double-page --right-first
```

再加上 `--split-jpeg`，用高质量 JPEG（而不是无损 PNG）存双页拆分出来的临时半页文件，高分辨率扫描页能明显更快（原理见下方架构说明），但会引入一次额外的有损压缩：

```
python Image2PDF.py --double-page --right-first --split-jpeg
```

该项目未配置构建/lint 步骤。

## 文档要求

仓库根目录的 `README.md` 必须用中文说明"如何使用这个项目"（安装依赖、CLI 用法、网页界面用法等面向使用者的操作步骤），保持与当前代码行为一致。每当 `Image2PDF.py`/`webapp.py` 等的用法（命令、参数、启动方式）发生变化时，必须同步更新 `README.md` 里对应的使用说明。

## 架构

### `Image2PDF.py` —— 核心转换逻辑

模块导入时会执行 `reportlab.rl_config.useA85 = 0`，全局关掉 reportlab 默认开启的 ASCII Base85 编码（`ASCII85Decode` filter）。这不是一个可选项，是一次性的、影响全局的性能修复：用真实高分辨率漫画扫描页做过一次严格对照实验——把同一批源图片分别放在用户的机械硬盘（`E:`，`WDC WD40EZRZ`）和固态硬盘（`D:`）上转换，换盘几乎测不出耗时差别，说明瓶颈根本不在磁盘 I/O 上。用 `cProfile` 定位后发现，真正吃掉 90% 以上耗时的是 `reportlab.lib.rl_accel._py_asciiBase85Encode`：reportlab 无论是 JPEG 直通路径（`PDFImageXObject.loadImageFromJPEG`）还是 PNG/raw 路径（`loadImageFromA85`/`loadImageFromSRC`），只要 `rl_config.useA85` 为真（默认值就是 `1`），都会把已经编码/压缩好的二进制流再套一层 ASCII Base85 编码——这是给某些只认文本、不支持二进制流的老旧/受限环境准备的兼容选项，现代 PDF 阅读器根本用不上，但 reportlab 内部这层编码是纯 Python 实现（没有 C 加速），逐字节 `divmod`/`chr`/拼接，真实测得一本 786 页的书仅这一步就吃掉了 58.22 秒里的 52.41 秒。关掉它之后同一本书降到 0.90 秒，约 **65 倍加速**，且不影响任何画质（这一层纯粹是编码转换，不涉及像素数据），生成的 PDF 反而更小（少了 base85 编码约 25% 的体积膨胀）；用 `pypdf` 验证过关闭后的 PDF 仍然合法、每页图片都能正常提取。`test/webapp_test.py` 里的 `test_use_a85_disabled_on_import`/`test_converted_jpeg_pdf_has_no_ascii85_filter`/`test_converted_png_pdf_has_no_ascii85_filter` 是这个修复的回归护栏（直接检查生成的 PDF 字节流里不再出现 `/ASCII85Decode`，同时 JPEG 直通路径的 `/DCTDecode` 依旧生效）。

**曾经短暂存在过、后来又移除的功能：`more_dirs` 批量场景的多线程并发（`max_workers` 参数）。** 在发现并修复 `useA85` 之前，曾经实现过这个功能——`convert_images2PDF_more_dirs`/`convert_images2PDF_auto` 加了一个 `max_workers` 参数（默认 `1`），大于 1 时用 `concurrent.futures.ThreadPoolExecutor` 并发转换多本书，CLI 有对应的 `--workers N`，网页界面有"并发数"输入框；当时的实测（PNG 路径下 `zlib.compress` 4 线程加速比 3.88x，JPEG 路径下 PIL 编码只有 1.10x）加上"机械硬盘可能不擅长并发随机读"的理论，得出结论是该不该开、开多大因瓶颈和存储介质而异，所以做成默认关闭、用户自己判断的开关。修复 `useA85` 之后，用同一批真实数据在用户的机械硬盘和固态硬盘上重新对照测过 `max_workers=1` vs `3`（预热缓存后交替测 3 轮取平均）：机械硬盘上快约 7%，固态硬盘上快约 16%，说明并发确实是有真实效果的（此前测不出效果，是因为 `useA85` 那个纯 Python 编码步骤把 CPU 死死钉在 GIL 上，多线程根本没有意义；修复之后瓶颈转移到磁盘 I/O，多线程才开始有点用）。但这个提升幅度在用户实际测试的样本规模下只值几百毫秒，用户权衡后认为不值得为了 7%~16% 的收益维护线程池、锁（`used_names_lock`/`results_lock`）、`threading.local()` 的页级进度钩子、CLI 参数、网页界面输入框和一整套并发测试这些复杂度，因此**这一整个功能连同它的代码、CLI 参数、网页控件、测试一起被完整移除**，`Image2PDF.py`/`webapp.py` 现在都不再有 `max_workers` 相关的任何痕迹。如果未来又想重新引入,完整的实现和上面这两组真实对照数据都能在 git 历史里找到,不需要从头重新做一遍这些实验。

包含三个公开入口函数：

- `convert_images2PDF_one_dir(file_dir, save_name=None, filename_sort_fn=None, on_book_done=None, double_page=False, right_page_first=True, on_page_progress=None, split_as_jpeg=False)` —— 将单个目录中的图片（仅顶层，不递归）转换为一个 PDF，PDF 保存在 `file_dir` **的上一级、和 `file_dir` 本身同级**（不会塞进 `file_dir` 内部、混在源图片中间），文件名以目录名命名（或使用 `save_name`）。这和 `convert_images2PDF_more_dirs` 的摆放习惯保持一致（每本书的 PDF 都和它对应的图片子目录同级）。`file_dir` 已经是盘符根（例如 `"C:\\"`）这种没有上一级的特殊情况会退化成 PDF 落在 `file_dir` 内部（`os.path.dirname` 在盘符根上是不动点，和 `web_fs.parent_of` 判断"是否已到盘符根"用的是同一个机制，不需要额外处理）。返回本次转换的结果列表（见下方 `__make_result`）。
- `convert_images2PDF_more_dirs(dirPath, filename_sort_fn=None, on_book_done=None, double_page=False, right_page_first=True, on_page_progress=None, split_as_jpeg=False)` —— 递归遍历 `dirPath`，将每个直接包含图片的目录视为一"本书"，按目录路径排序后逐个顺序转换为一个 PDF，保存在根目录 `dirPath` 下。重名目录（例如两个都叫 `same/` 的文件夹）会通过 `__unique_pdf_name` 消除歧义，该函数会先回退到基于路径生成的名称，再回退到添加数字后缀。返回结果列表。
- `convert_images2PDF_auto(dir_path, filename_sort_fn=None, on_book_done=None, double_page=False, right_page_first=True, on_page_progress=None, split_as_jpeg=False)` —— CLI（`__main__`）和 `webapp.py` 共用的自动分派规则：若 `dir_path` 顶层本身有图片，当作一本书调用 `convert_images2PDF_one_dir`；若顶层没有图片、只有含图片的子目录（例如总目录=漫画名，子目录=每一册），改用 `convert_images2PDF_more_dirs`。返回 `(mode, results)`，`mode` 为 `"one_dir"` 或 `"more_dirs"`。**这是分派逻辑的唯一实现，`webapp.py` 不会重复这套判断，避免两边行为漂移。**

三个函数都接受可选的 `on_book_done(result, done_count, total_count)` 回调，每转换完一本书后触发一次，默认为 `None`（不影响原有 CLI 行为），供 `webapp.py` 用来展示进度和实时更新 Gallery。

三个函数还都接受可选的 `on_page_progress(book_number, book_total, page_done, page_total)` 回调，在**当前正在转换的这本书**每渲染完一页时都会触发一次（`book_number` 是 1-based 的当前书序号，`convert_images2PDF_one_dir` 恒为 `(1, 1)`，`convert_images2PDF_more_dirs` 按目录遍历/转换顺序递增）。这是为了解决"网页界面只生成 1 个 PDF 时进度条永远是不确定的灰色滚动条，看不到真实百分比"的问题——`on_book_done` 只在一整本书转换完时才触发一次，单本模式下中途完全没有信号；页级回调把粒度细化到"页"，才能算出随时间平滑递增的真实百分比。实现方式见下面 `__converted`/`__page_progress_hook` 的说明。

三个函数还都接受 `double_page`/`right_page_first` 这一对参数，对本次转换任务里的**每一张图片**统一生效（是一个全局开关，不按图片宽高比自动判断）：`double_page=True` 表示每张图其实是拼版的跨页图，需要沿垂直中线左右各切成一页；`right_page_first` 决定切开后哪一半页码更小、应该排在前面（`True`=右半边页码小，如从右往左翻的日式漫画；`False`=左半边页码小，如从左往右翻的西式漫画）。`double_page=False`（默认）时这两个参数完全不生效，代码路径与引入该功能之前完全一致。

三个函数还都接受可选的 `split_as_jpeg`（默认 `False`），仅在 `double_page=True` 时才有意义，控制双页拆分出来的临时半页文件存成无损 PNG（默认）还是高质量 JPEG（`quality=95`）。这不只是格式选择，背后有一个关键机制（详见下面 `__split_double_page_images` 的说明）：reportlab 对 `.jpg` 文件名是零重新编码的直通嵌入，对 PNG 则是完整解码+重新压缩，真实的高分辨率扫描页（比如 7000 万像素的双页扫描）在这两条路径上的耗时差距非常大。默认保持 PNG 无损是因为 JPEG 会引入一次额外的有损压缩（原始扫描 JPEG → 解码裁剪 → 重新编码），这个取舍必须由用户自己选，不能替用户决定。

内部辅助函数（均为模块级私有函数，双下划线前缀——由于不在 class 定义体内，**不会被 Python 的名称改编（name mangling）影响**，测试和 `web_fs.py` 都直接通过 `image2pdf.__name` 访问它们，因为使用的是 `import Image2PDF as image2pdf`）：

- `__isAllow_file(filepath)` —— 扩展名白名单检查（`.jpg/.jpeg/.bmp/.png`，大小写不敏感）。
- `__sort_pages(book_pages, filename_sort_fn=None)` —— 对页面列表的副本进行排序。普通的 `sorted()` 会把数字后缀的文件名排错序（例如 `doc_2` 排在 `doc_11` 之后），因此调用方可以传入 `filename_sort_fn(full_path) -> 可转换为整数的值`，以按数值而非字典序排序。
- `__make_result(pdf_path, source_dir, pages, filename_sort_fn=None)` —— 构造一次单本转换的结果 dict（`pdf_path`/`pdf_name`/`source_dir`/`page_count`/`first_page`），供 Web 层生成 Gallery 封面使用。它复用 `__sort_pages` 单独重新排序一遍 `pages`，而不是改动 `__converted` 的契约或返回值——这样做是为了不破坏 `test/filename_sort_test.py` 里 `monkeypatch.setattr(image2pdf, "__converted", fake_convert)` 这种返回 `None` 的 fake 用法。
- `__converted(save_book_name, book_pages, filename_sort_fn=None)` —— 实际执行 PDF 生成，使用 `reportlab.pdfgen.canvas.Canvas`，并通过 `PIL` 为每张图片单独设置页面尺寸，使每一页都与源图片的尺寸完全一致（这也是为什么复用同一个 `Canvas` 并在每页调用 `setPageSize`，而不是使用固定页面尺寸的原因）。**它的调用签名和返回值（`None`）是一条硬约束，不能改动**——任何重构都必须通过额外调用 `__sort_pages`/`__make_result` 之类的方式获取信息，而不是给 `__converted` 加参数。双页拆分同样遵守这条约束：`double_page=True` 时不会给 `__converted` 传第 4 个参数，而是在调用它之前就把 `book_pages` 换成 `__split_double_page_images` 展开好的临时半页文件列表。页级进度同样不违反这条约束：`__converted` 内部循环每 `c.showPage()` 一次，就检查模块级变量 `__page_progress_hook`（和 `__allow_type` 放在一起，默认 `None`），非空则调用 `__page_progress_hook(index + 1, total_pages)` 上报进度——这是纯粹读一个全局变量，不涉及函数签名，`test/filename_sort_test.py` 里把 `__converted` 整个 monkeypatch 成 fake 函数时，这段读钩子的代码根本不会被执行到，所以不影响任何现有测试。`convert_images2PDF_one_dir`/`convert_images2PDF_more_dirs` 在调用 `__converted` 前用 `global __page_progress_hook` 设置好这次调用要用的钩子（包一层闭包把 `book_number`/`book_total` 补齐），并在已有的 `try/finally`（原本只是为了清理 double_page 的临时目录）的 `finally` 分支里把钩子重置回 `None`。**性能上的一个反直觉的坑，踩过一次不要再踩**：循环体内故意直接把 `page`（文件名字符串）传给 `pilImage.open()` 和 `c.drawImage()`，不要"优化"成先构造一个 `reportlab.lib.utils.ImageReader(page)` 对象、用它同时取尺寸和画图来"避免重复解码"——这个改动实测反而更慢。原因是 reportlab 的 `Canvas.drawImage` 在给定字符串文件名时，只用文件名本身算一个便宜的去重 hash；但如果给的是 `ImageReader` 对象，它会先调用 `image.getRGBData()` 算去重 hash，这一步会强制把整张图完整解码成 RGB 像素，等于多做一次全量解码。PIL 的 `Image.open()` 本身是惰性的（只读文件头拿 size，不解码像素），所以原来的写法并没有"重复解码"的问题，是一开始的假设就错了；用几十张真实体积的 JPEG 测过，`ImageReader` 版本比原版慢了将近一倍，已经改回来了。
- `__has_top_level_images(dir_path)` —— 判断目录顶层（不递归）是否直接含有图片文件，供 `convert_images2PDF_auto`、`web_fs.preview` 和 `webapp.api_convert` 做判断。
- `__split_double_page_images(sorted_pages, right_page_first, split_as_jpeg=False)` —— 把已排好序的整页图片列表逐张沿垂直中线切成左右两半，存到一个临时目录（`tempfile.mkdtemp(prefix="image2pdf_split_")`）里，文件名用零填充序号前缀（如 `00000_a.png`/`00000_b.png`，`split_as_jpeg=True` 时后缀是 `.jpg`）保证展开后已经是最终 PDF 顺序，因此调用方之后会把 `filename_sort_fn` 传 `None` 给 `__converted`/`__make_result`，让它们内部的默认 `sorted()` 是无操作。`split_as_jpeg=False`（默认）时存盘用 `compress_level=0` 关掉 PNG 压缩——这两个临时文件转换完就会被删除、从不会被用户打开，压缩它们纯粹是浪费 CPU；用真实体积、带噪点纹理的图片（更接近扫描/照片来源的漫画页，而不是纯色测试图）测过，跳过压缩能让这一步快 2 倍左右（纯色测试图上反而会更慢，因为纯色数据本来压缩就极快、极小，这时不压缩换来的是更大的磁盘 I/O，所以判断快慢一定要用有真实纹理噪点的图片测，不能用纯色块）。

  **`split_as_jpeg=True` 存在的关键原因**（读了 `reportlab/pdfbase/pdfdoc.py` 的 `PDFImageXObject` 源码才发现）：`__converted` 里 `c.drawImage(page, ...)` 收到一个以 `.jpg`/`.jpeg` 结尾的文件名时，reportlab 的 `loadImageFromJPEG` 只读 JPEG 文件头拿宽高，然后把**原始 JPEG 压缩字节流原封不动塞进 PDF**（`DCTDecode` filter）——完全不解码、不重新编码，这正是 `img2pdf` 主打的"JPEG 直通"优化，reportlab 对 JPEG 文件名输入早就在做，所以不需要专门再引入 `img2pdf` 这个依赖。但如果文件名是 PNG（或任何非 `.jpg`/`.jpeg`），走的是 `loadImageFromRaw`/`loadImageFromSRC`，会做完整的 RGB 解码 + `zlib.compress()` 重新压缩——双页模式下拆出来的半页图默认是 PNG，即使源图本来是 JPEG，也会被这条贵路径拖慢，而且真实漫画扫描页的分辨率动辄 3000万-7000万像素，这个差距会被放大。`split_as_jpeg=True` 让拆分出来的半页图存成 `.jpg`（`quality=95`），重新走上 reportlab 的直通路径。用真实的高分辨率漫画扫描页（不是合成测试图）验证过提速效果，具体数字见 git log。JPEG 没有透明通道，裁出来的半张图如果带 alpha（RGBA/LA/带透明度的 P 模式）要先在白底上合成（`__save_split_half_as_jpeg` 辅助函数），逻辑和 `web_gallery.make_cover` 生成封面缩略图时处理 RGBA 源图完全一样，没有重新发明一遍。

  返回 `(expanded_pages, temp_dir)`；`convert_images2PDF_one_dir`/`convert_images2PDF_more_dirs` 用 `try/finally` 包住"分割→转换→构造结果→触发 `on_book_done`"这一整段，确保 `on_book_done`（例如 Web 层在回调里同步读取 `first_page` 生成封面缩略图）消费完临时文件之后，`finally` 里的 `shutil.rmtree` 才删除临时目录。

`__main__` 用 `argparse` 解析双页相关的命令行参数（`__build_arg_parser()` 构造 parser，`__validate_cli_args(parser, args)` 做"开启 `--double-page` 时必须同时给 `--right-first`/`--left-first` 之一"的校验，不满足时调用 `parser.error(...)` 直接以退出码 2 结束）；文件夹路径本身仍然是运行后 `input()` 交互式输入，没有做成位置参数。`--split-jpeg` 是配合 `--double-page` 使用的第三个 flag（对应 `split_as_jpeg`），有安全默认值（不给就是无损 PNG），不需要像 `--right-first`/`--left-first` 那样强制校验。这几个函数是模块级的，测试里同样通过 `image2pdf.__dict__["__build_arg_parser"]` 这种方式直接调用来验证参数校验逻辑，不需要真的 fork 子进程。

已知的小瑕疵：开启 `double_page` 时，`__make_result` 里的 `first_page` 会指向 `__split_double_page_images` 生成的临时切割文件，而这个临时目录在同一次转换结束后就会被删除，所以持久化进 `webdata/gallery.json` 的 `first_page` 字段在双页模式下必然是一个之后不存在的路径。这不影响封面图（封面在临时目录删除前就已经从正确的那一半图片生成并保存成 JPEG 了），纯粹是这一个 JSON 字段本身失去参考意义，目前视为可接受的已知行为，未做额外处理。

文件名排序问题（对形如 `test_01_doc_0.png`、`..._1.png`、`..._11.png`、`..._2.png` 这样的图片文件名进行自然数字排序）是本代码库中最棘手的部分，README 中有说明，并由 `test/filename_sort_test.py` 覆盖测试；对 `__sort_pages` 或排序回调约定的任何改动都应确保该测试仍然通过。

测试通过 monkeypatch 替换 `__converted` 来避免真实的图片/PDF I/O，从而只针对目录遍历与命名逻辑进行断言。

### `webapp.py` / `web_fs.py` / `web_gallery.py` —— 本地网页界面

- `webapp.py` —— Flask 应用，只监听 `127.0.0.1`。路由包括 `/api/drives`（列盘符）、`/api/browse`（列子目录，支持面包屑/上一级）、`/api/preview`（预览某目录会生成几个 PDF，供用户点"使用此目录"时看一眼）、`/api/convert`（POST，请求体为 `{"path", "double_page", "right_page_first", "split_as_jpeg"}`，启动后台线程执行 `Image2PDF.convert_images2PDF_auto`，同一时间只允许一个任务，返回 `job_id`；`double_page=true` 但请求体里完全没带 `right_page_first` 字段时返回 400，要求前端必须显式带上这个字段而不是依赖服务端默认值；`split_as_jpeg` 有安全默认值 `False`，不需要这种强制校验）、`/api/jobs/<id>`（轮询任务进度，job 字典里除了 `done`/`total`（本级）还有 `page_done`/`page_total`（当前书的页级进度）和一个综合的 `percent`（0-100 整数，见下方 `_compute_percent`））、`/api/gallery`（GET 列表 / DELETE 删除单条记录）、`/covers/<file>`（通过 `send_from_directory` 提供封面图片，不接受用户传入的绝对路径，避免路径穿越）。`@app.errorhandler(Exception)` 统一把异常转成 JSON，但会保留 `HTTPException`（如 404）原本的状态码，不能笼统地都转成 500。`_compute_percent(book_number, book_total, page_done, page_total)` 是一个纯函数（`(book_number - 1 + page_done/page_total) / book_total`，四舍五入取整并封顶 100），单本模式（`book_total=1`）和多本模式（`book_total>1`）用的是同一套公式，因此进度条在两种模式下都能平滑递增，不再是"只生成 1 个 PDF 时永远是不确定的灰色滚动条"。`_run_conversion` 里的 `on_page_progress` 回调调用它更新 `page_done`/`page_total`/`percent`；`on_book_done` 每完成一本书也会用 `done/total` 把 `percent` 对齐一次，避免逐页累积的浮点误差卡在 99%。**`/api/convert` 故意不调用 `web_fs.preview(path)`**：那是一次递归的全树 `os.walk`，而它在旧版本里是在持锁、阻塞 HTTP 响应的情况下同步跑的，加上用户点"使用此目录"时 `/api/preview` 已经走过一次、后台线程里 `convert_images2PDF_auto` 真正转换时自己还要再走一次，等于同一棵目录树被完整遍历三次，是"点了开始转换迟迟没反应"的主因。现在改成只用廉价的 `web_fs._has_top_level_images(path)`（只看顶层，不递归）猜一下 `mode` 存进 job，`total` 先给占位值 `1`；真实的 `total`/`mode` 由后台线程里 `on_book_done`/`on_page_progress` 回调在拿到真实数据后自动纠正（已有逻辑本来就会用真实值覆盖，不需要新代码）。目录里完全没有图片的情况也相应地从"提前同步返回 400"改成后台线程跑完发现 `len(results) == 0` 时把 `job["status"]` 置为 `"error"`，前端已有的 `job.error` 展示逻辑直接复用。
- `web_fs.py` —— 目录浏览与路径校验。`list_drives()` 用 `ctypes.windll.kernel32.GetLogicalDrives()` 位掩码枚举盘符（不要逐个 `os.path.exists("A:\\")`，会在空光驱/断开的网络盘上卡住）。`normalize_dir(raw)` 规范化用户输入的路径：拒绝相对路径、特判裸盘符（`"C:"` 需要手动补 `os.sep`，因为 `os.path.abspath("C:")` 在 Windows 上返回的是**服务器进程的当前工作目录**而不是 `"C:\\"`，是一个容易踩的坑）。`parent_of(path)` 通过检测 `os.path.dirname` 的不动点（`dirname("C:\\") == "C:\\"`）判断是否已经到达盘符根。`preview(path)` 镜像 `convert_images2PDF_auto` 的判断规则，只应该在用户点击"使用此目录"时调用一次，不要接入 `/api/browse`（会在大目录树上卡住界面）。
- `web_gallery.py` —— Gallery 的持久化。索引存在 `webdata/gallery.json`（可用环境变量 `IMAGE2PDF_DATA_DIR` 改路径，默认在仓库下的 `webdata/`，已加入 `.gitignore`），封面缩略图存在 `webdata/covers/<id>.jpg`。`item_id(pdf_path)` 用 PDF **完整绝对路径**的 SHA1 前 16 位作为 id，保证两个同名但不同目录的书（如两个都叫 `same.pdf`）不会共用同一张封面。`make_cover(src_image, id_)` 用 `PIL` 生成缩略图：先做 `ImageOps.exif_transpose`（否则手机竖拍照片会缩成横的），再处理 RGBA/带透明度的 P 模式（先在白底上合成，直接 `.convert("RGB")` 会把透明区域变黑），最后用临时文件 + `os.replace` 原子写入。`upsert_result(result, batch_id=None)` 按 `id` 原地更新已存在的记录（保留 `created_at` 和排列位置，只刷新 `updated_at`/`page_count`/`cover_file` 等），不存在则追加到末尾——因为重复转换同一个目录覆盖的是磁盘上同一个 PDF 文件，两条记录共享一张封面会导致删除时产生孤儿文件。`/api/gallery` 返回的 `cover_url` 带 `?v=<updated_at>` 查询参数用于让浏览器在重新转换后刷新缩略图缓存。`delete_item(id)` 只删 JSON 记录和封面文件，**绝不删除 PDF 本身**。

Web 层新增的测试在 `test/webapp_test.py`，覆盖：`convert_images2PDF_*` 返回值契约、`__converted` 被 monkeypatch 成返回 `None` 时结果列表仍然完整（回归护栏，对应上面 `__converted` 的硬约束）、`convert_images2PDF_auto` 分派规则、`web_fs.normalize_dir`/`parent_of` 的边界情况、`/api/browse` 权限错误返回 403、`web_gallery` 的封面生成（RGBA→RGB）与原地更新/删除逻辑、`__split_double_page_images` 按 `right_page_first` 正确决定左右半图顺序（用左右两色拼图 + 像素采样断言）、`double_page=False`（默认）时完全不触发拆分逻辑、拆分产生的临时目录在转换结束后被清理、`__build_arg_parser`/`__validate_cli_args` 的双页参数校验、`/api/convert` 在 `double_page=true` 却缺 `right_page_first` 时返回 400、`on_page_progress` 在 `one_dir`/`more_dirs`/双页模式下上报的 `(book_number, book_total, page_done, page_total)` 序列是否正确、`webapp._compute_percent` 这个纯函数在单本/多本/尚无页级数据几种输入下的取值、`webapp._run_conversion` 端到端跑一次真实转换后 job 字典里 `percent`/`page_done`/`page_total` 是否正确演进到 100、空目录转换后 `job["status"]` 变成 `"error"` 而不是抛异常、`/api/convert` 请求路径完全不调用 `web_fs.preview`（monkeypatch 成一调用就报错来断言）且能立刻返回 `202`、`split_as_jpeg=False`（默认）时拆分出来的临时文件还是 `.png`（回归护栏）、`split_as_jpeg=True` 时是 `.jpg` 且 `right_page_first` 的左右顺序依然正确（JPEG 有损，断言改成"某个颜色分量明显更高"而不是像素精确相等）、带透明通道的半页图在 `split_as_jpeg=True` 时会先合成到白底、`/api/convert` 请求体带 `split_as_jpeg` 时能正确存进 `_new_job` 并透传到实际转换、`convert_images2PDF_one_dir`（含 `save_name` 自定义文件名的情况）和 `convert_images2PDF_auto` 的 `one_dir` 分派生成的 PDF 都落在 `file_dir` 的上一级而不是内部、`reportlab.rl_config.useA85` 导入 `Image2PDF` 后确实是 `0`、JPEG 直通和 PNG/raw 两条路径生成的 PDF 字节流里都不再出现 `/ASCII85Decode`（JPEG 路径额外断言 `/DCTDecode` 仍然存在，确认直通优化没有被误伤）。
