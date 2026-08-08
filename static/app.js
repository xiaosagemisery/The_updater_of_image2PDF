(function () {
  "use strict";

  const driveChips = document.getElementById("drive-chips");
  const breadcrumbsEl = document.getElementById("breadcrumbs");
  const browseErrorEl = document.getElementById("browse-error");
  const upBtn = document.getElementById("up-btn");
  const dirListEl = document.getElementById("dir-list");
  const currentPathEl = document.getElementById("current-path");
  const useDirBtn = document.getElementById("use-dir-btn");
  const previewBox = document.getElementById("preview-box");
  const pathInput = document.getElementById("path-input");
  const pathGoBtn = document.getElementById("path-go-btn");

  const doublePageCheckbox = document.getElementById("double-page-checkbox");
  const pageOrderRow = document.getElementById("page-order-row");
  const pageOrderRight = document.getElementById("page-order-right");
  const pageOrderLeft = document.getElementById("page-order-left");
  const splitJpegCheckbox = document.getElementById("split-jpeg-checkbox");

  const jobPanel = document.getElementById("job-panel");
  const progressBar = document.getElementById("progress-bar");
  const progressText = document.getElementById("progress-text");
  const jobErrorEl = document.getElementById("job-error");

  const galleryEl = document.getElementById("gallery");
  const galleryEmptyEl = document.getElementById("gallery-empty");

  let state = {
    path: null,      // 当前浏览的目录路径; null 表示正显示盘符列表
    parent: null,
    atRoot: true,
    isDriveList: true,
  };

  let pollTimer = null;

  // ---- 工具函数 ------------------------------------------------------

  function clearChildren(el) {
    while (el.firstChild) el.removeChild(el.firstChild);
  }

  function apiGet(url) {
    return fetch(url).then(async (resp) => {
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok) {
        const err = new Error(data.error || ("请求失败: " + resp.status));
        err.status = resp.status;
        err.data = data;
        throw err;
      }
      return data;
    });
  }

  function apiSend(url, method, body) {
    return fetch(url, {
      method: method,
      headers: { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    }).then(async (resp) => {
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok) {
        const err = new Error(data.error || ("请求失败: " + resp.status));
        err.status = resp.status;
        err.data = data;
        throw err;
      }
      return data;
    });
  }

  // ---- 目录浏览 --------------------------------------------------------

  function loadDriveChips() {
    apiGet("/api/drives").then((data) => {
      clearChildren(driveChips);
      data.drives.forEach((d) => {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.textContent = d.name;
        btn.addEventListener("click", () => browse(d.path));
        driveChips.appendChild(btn);
      });
    }).catch(() => {});
  }

  function renderBreadcrumbs(crumbs) {
    clearChildren(breadcrumbsEl);
    if (!crumbs || crumbs.length === 0) {
      const span = document.createElement("span");
      span.textContent = "此电脑";
      breadcrumbsEl.appendChild(span);
      return;
    }
    crumbs.forEach((c, i) => {
      if (i > 0) {
        const sep = document.createElement("span");
        sep.className = "sep";
        sep.textContent = " / ";
        breadcrumbsEl.appendChild(sep);
      }
      const btn = document.createElement("button");
      btn.type = "button";
      btn.textContent = c.name;
      btn.addEventListener("click", () => browse(c.path));
      breadcrumbsEl.appendChild(btn);
    });
  }

  function renderDirs(dirs) {
    clearChildren(dirListEl);
    if (!dirs || dirs.length === 0) {
      const li = document.createElement("li");
      li.className = "empty-hint";
      li.textContent = "(没有子文件夹)";
      dirListEl.appendChild(li);
      return;
    }
    dirs.forEach((d) => {
      const li = document.createElement("li");
      li.textContent = "📁 " + d.name; // 📁
      li.addEventListener("click", () => browse(d.path));
      dirListEl.appendChild(li);
    });
  }

  function showBrowseError(msg) {
    browseErrorEl.textContent = msg;
    browseErrorEl.hidden = false;
  }

  function hideBrowseError() {
    browseErrorEl.hidden = true;
    browseErrorEl.textContent = "";
  }

  function browse(path) {
    hideBrowseError();
    previewBox.hidden = true;
    clearChildren(previewBox);

    const url = path ? ("/api/browse?path=" + encodeURIComponent(path)) : "/api/browse";
    apiGet(url).then((data) => {
      state.path = data.path;
      state.parent = data.parent;
      state.atRoot = data.at_root;
      state.isDriveList = data.is_drive_list;

      renderBreadcrumbs(data.breadcrumbs);
      renderDirs(data.dirs);
      upBtn.hidden = data.is_drive_list;

      if (data.errors && data.errors.length > 0) {
        showBrowseError(data.errors.join("; "));
      }

      if (data.is_drive_list) {
        currentPathEl.textContent = "";
        useDirBtn.disabled = true;
        pathInput.value = "";
      } else {
        currentPathEl.textContent = data.path;
        useDirBtn.disabled = false;
        pathInput.value = data.path;
      }
    }).catch((err) => {
      if (err.status === 403 && err.data) {
        showBrowseError(err.data.error || "没有权限读取该目录");
        // 403 时保持在原来的列表,不跳转过去
        if (err.data.parent !== undefined) {
          state.parent = err.data.parent;
        }
      } else {
        showBrowseError(err.message);
      }
    });
  }

  upBtn.addEventListener("click", () => {
    if (state.parent) {
      browse(state.parent);
    } else {
      browse(null); // 回到盘符列表
    }
  });

  pathGoBtn.addEventListener("click", () => browse(pathInput.value));
  pathInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") browse(pathInput.value);
  });

  doublePageCheckbox.addEventListener("change", () => {
    pageOrderRow.hidden = !doublePageCheckbox.checked;
    // "拆分优先速度"和"双页模式"在 UI 上是两个独立的选项(不嵌套在双页设置区域里),
    // 但它只在双页模式下才有实际效果(只有双页拆分才会产生临时半页文件),
    // 所以双页模式关闭时把它禁用,而不是隐藏它。
    splitJpegCheckbox.disabled = !doublePageCheckbox.checked;
  });

  // ---- 预览 + 开始转换 --------------------------------------------------

  useDirBtn.addEventListener("click", () => {
    if (!state.path) return;
    apiGet("/api/preview?path=" + encodeURIComponent(state.path)).then((data) => {
      renderPreview(data);
    }).catch((err) => {
      showBrowseError(err.message);
    });
  });

  function renderPreview(data) {
    clearChildren(previewBox);
    previewBox.hidden = false;

    const text = document.createElement("p");
    if (data.mode === "one_dir") {
      text.textContent = "将把该目录下的图片合并生成 1 个 PDF。";
    } else if (data.mode === "more_dirs") {
      text.textContent = "该目录顶层没有图片,将为其下 " + data.book_count + " 个含图片的子目录各生成 1 个 PDF。";
    } else {
      text.textContent = "该目录及其子目录下没有找到任何图片文件。";
    }
    previewBox.appendChild(text);

    if (data.truncated) {
      const warn = document.createElement("p");
      warn.textContent = "(子目录数量较多,以上统计已截断)";
      previewBox.appendChild(warn);
    }

    if (data.book_count > 0) {
      const startBtn = document.createElement("button");
      startBtn.type = "button";
      startBtn.className = "primary";
      startBtn.textContent = "开始转换";
      startBtn.addEventListener("click", () => startConvert(data.path));
      previewBox.appendChild(startBtn);
    }
  }

  // ---- 转换任务 --------------------------------------------------------

  function startConvert(path) {
    if (doublePageCheckbox.checked && !pageOrderRight.checked && !pageOrderLeft.checked) {
      // 两个单选项默认都不选中,强制用户明确选一边,不能悄悄套用一个默认方向
      showBrowseError("请先选择双页拼图里哪边页码小");
      return;
    }

    useDirBtn.disabled = true;
    const body = {
      path: path,
      double_page: doublePageCheckbox.checked,
      right_page_first: pageOrderRight.checked,
      split_as_jpeg: splitJpegCheckbox.checked,
    };
    apiSend("/api/convert", "POST", body).then((data) => {
      localStorage.setItem("image2pdf_last_job", data.job_id);
      openJobPanel();
      pollJob(data.job_id);
    }).catch((err) => {
      useDirBtn.disabled = false;
      showBrowseError(err.message);
    });
  }

  function openJobPanel() {
    jobPanel.hidden = false;
    jobErrorEl.hidden = true;
    jobErrorEl.textContent = "";
    progressBar.classList.remove("indeterminate");
    progressBar.style.width = "0%";
    progressText.textContent = "正在准备...";
  }

  function pollJob(jobId) {
    if (pollTimer) clearInterval(pollTimer);
    pollTimer = setInterval(() => tick(jobId), 800);
    tick(jobId);
  }

  function tick(jobId) {
    apiGet("/api/jobs/" + encodeURIComponent(jobId)).then((job) => {
      renderJob(job);
      if (job.status === "done" || job.status === "error") {
        clearInterval(pollTimer);
        pollTimer = null;
        useDirBtn.disabled = false;
        loadGallery();
        if (job.status === "done") {
          setTimeout(() => { jobPanel.hidden = true; }, 2000);
        }
      } else {
        // 运行中也随着 done 增长逐张刷新 Gallery
        loadGallery();
      }
    }).catch(() => {
      clearInterval(pollTimer);
      pollTimer = null;
      useDirBtn.disabled = false;
    });
  }

  function renderJob(job) {
    // page_total 有值说明后端已经上报过至少一次真实的页级进度(__page_progress_hook),
    // 在此之前(比如 more_dirs 模式还在遍历目录树找图片)没有任何真实数据可用,
    // 用滚动条表示"在跑但还没有数字",避免一开始长时间卡在 0% 看起来像卡死。
    const hasRealProgress = job.page_total != null;

    if (hasRealProgress) {
      progressBar.classList.remove("indeterminate");
      progressBar.style.width = job.percent + "%";
    } else {
      progressBar.classList.add("indeterminate");
    }

    const parts = [];
    if (job.total > 1) {
      parts.push("第 " + job.done + "/" + job.total + " 本");
    }
    if (job.current) {
      parts.push(job.current);
    }
    if (job.page_total) {
      parts.push("第 " + job.page_done + "/" + job.page_total + " 页");
    }

    if (hasRealProgress) {
      progressText.textContent = job.percent + "%  " + parts.join("  ");
    } else {
      progressText.textContent = parts.length > 0 ? parts.join("  ") : "正在准备...";
    }

    if (job.status === "done") {
      progressBar.classList.remove("indeterminate");
      progressBar.style.width = "100%";
      progressText.textContent = "完成 (" + job.done + " 个 PDF)";
    } else if (job.status === "error") {
      jobErrorEl.hidden = false;
      jobErrorEl.textContent = job.error || "转换失败";
    }
  }

  // 页面刷新后,如果之前的任务还在跑,重新接上轮询
  (function resumeJob() {
    const jobId = localStorage.getItem("image2pdf_last_job");
    if (!jobId) return;
    apiGet("/api/jobs/" + encodeURIComponent(jobId)).then((job) => {
      if (job.status === "running") {
        openJobPanel();
        pollJob(jobId);
      }
    }).catch(() => {});
  })();

  // ---- Gallery --------------------------------------------------------

  function loadGallery() {
    apiGet("/api/gallery").then((data) => {
      renderGallery(data.items);
    }).catch(() => {});
  }

  function renderGallery(items) {
    clearChildren(galleryEl);
    galleryEmptyEl.hidden = items.length > 0;

    items.forEach((item) => {
      const card = document.createElement("div");
      card.className = "card" + (item.missing ? " missing" : "");

      const coverBox = document.createElement("div");
      coverBox.className = "cover-box";
      if (item.cover_url) {
        const img = document.createElement("img");
        img.src = item.cover_url;
        img.alt = item.title;
        img.loading = "lazy";
        coverBox.appendChild(img);
      } else {
        const ph = document.createElement("span");
        ph.className = "cover-placeholder";
        ph.textContent = "无封面";
        coverBox.appendChild(ph);
      }
      card.appendChild(coverBox);

      const body = document.createElement("div");
      body.className = "card-body";

      const title = document.createElement("div");
      title.className = "card-title";
      title.textContent = item.title;
      title.title = item.pdf_path;
      body.appendChild(title);

      const meta = document.createElement("div");
      meta.className = "card-meta";
      meta.textContent = item.page_count + " 页" + (item.missing ? " · 文件已不存在" : "");
      body.appendChild(meta);

      const actions = document.createElement("div");
      actions.className = "card-actions";
      const delBtn = document.createElement("button");
      delBtn.type = "button";
      delBtn.textContent = "删除";
      delBtn.addEventListener("click", () => {
        apiSend("/api/gallery/" + encodeURIComponent(item.id), "DELETE").then(loadGallery);
      });
      actions.appendChild(delBtn);
      body.appendChild(actions);

      card.appendChild(body);
      galleryEl.appendChild(card);
    });
  }

  // ---- 初始化 -----------------------------------------------------------

  loadDriveChips();
  browse(null);
  loadGallery();
})();
