# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

---

## 项目概览

小红书笔记爬虫，**单文件应用**：[crawler_ultimate.py](crawler_ultimate.py)（约 6100 行）。
技术栈：tkinter GUI + DrissionPage（Chromium 自动化）+ SQLite + pandas。

> **v5.3 大修说明**：本文档下方"已知未接线/已失效"等章节多数问题已修复。
> 每条已修项就地标注 ✅；仍需注意的不变量保持原样。行号为近似值，改动前请以 grep 复核。

```bash
pip install -r requirements.txt
python crawler_ultimate.py        # 必须在仓库根目录启动，见下方"相对路径依赖"
```

**本仓库没有任何测试、linter 或构建配置**，没有 `pytest`/`ruff`/`black` 设置。验证方式只有手动运行 GUI。新增测试前先与用户确认，不要自行引入测试框架并假定它属于本项目约定。

可选依赖（matplotlib / wordcloud / jieba / python-docx）在 `requirements.txt:14-16` 中被**注释掉**，默认不安装；缺失时"数据分析"页三个按钮全部不可用。

---

## 架构总览

单文件、单类承担全部职责。`CrawlerApp`（687-5759）同时是 GUI、爬取引擎和持久化协调者。分层只体现在行号区间：

| 行号区间 | 职责 |
|---|---|
| 68-182 | `CrawlerConfig` dataclass + JSON 持久化白名单 |
| 185-284 | `FileLogger`（带锁）、`CookieManager`（带锁） |
| 287-370 | `DatabaseManager` — 单表 `notes` |
| 373-527 | `MediaDownloader` — 线程池 + 共享 requests.Session |
| 530-684 | `DataAnalyzer` — 图表/词云/报告，全部受可选依赖门控 |
| 844-3350 | GUI 五个页面构建 + 结果页交互 |
| 3410-3573 | 爬取启动 / 配置收集 / 线程派发 |
| 3573-3833 | `_crawl_thread` 主循环 |
| 3843-3946 | 登录检测与 Cookie |
| 4007-4374 | `_standard_crawl` / `_fast_crawl` 两条采集路径 |
| 4374-5081 | `_extract_full_note` — **单方法 709 行**，全文最复杂处 |
| 5406-5518 | `_save_data` — 扁平化 + 列名中译 + 落盘 |

`docs/` 三份文档是**选择器与页面结构的权威参考**，改动任何采集逻辑前必读：

- [docs/小红书页面结构分析.md](docs/小红书页面结构分析.md) — 全部 CSS/XPath 选择器、`__INITIAL_STATE__` 结构、瀑布流布局、Live 图特征
- [docs/爬取流程模拟分析.md](docs/爬取流程模拟分析.md) — 点击/关闭弹窗的正确做法及踩坑记录
- [docs/功能说明文档.md](docs/功能说明文档.md) — 字段提取优先级、预设模式对照表

---

## 爬取引擎的核心不变量

违反以下任何一条都会导致**静默的错误数据**，而非报错。

### 1. 真正的数据源是 `window.__INITIAL_STATE__`，DOM 选择器只是降级备份

标题（4408）、作者（4482）、互动数（4592）、视频（4733）、图片列表（4880）均优先走 JS 读取 `state.note.noteDetailMap[noteId]`。**新增字段应沿用这条路径**，而不是再加一个 CSS 选择器。

### 2. `noteId` 必须从 URL 推导，绝不能信任 `currentNoteId`

每处 JS 都重复这一行（4412、4485、4595、4736、4884）：

```js
const urlMatch = window.location.href.match(/explore\/([a-zA-Z0-9]+)/);
const noteId = urlMatch ? urlMatch[1] : state.note.currentNoteId;
```

小红书是 SPA，`currentNoteId` 会滞后于当前弹窗，直接使用会抽到**上一条笔记的数据**。这是防数据串位的核心防线，历史上所有"标题/点赞/图片都一样"的 bug 都源于此。

### 3. `_standard_crawl` 每轮从头重新 `page.eles()` 是刻意设计，不是低效

4081 + 4091：每次外层迭代重新抓取元素列表，线性扫到第一个未爬 noteId 就处理并 `break`。这是 O(n²)，但开关详情弹窗会让 DOM 重渲染，**任何跨迭代持有的元素句柄都会失效**。把它"优化"成缓存列表会直接引入 stale element 崩溃。

### 4. 必须点 `a.cover`，关闭必须用 `history.back()`

`section.note-item` 是容器、无点击事件；点其它 `a` 会跳 404。关闭弹窗时 `Escape` 与关闭按钮都不稳定，统一 `page.run_js("history.back()")`（4075、4172、4213、4248）。

### 5. `css:section.note-item` 是单点依赖

出现在 3700、3718、3744、4005、4081、4231、4280 及 JS 内 3957。它一变，预加载、扫描、两种模式同时静默失效（表现为"未找到笔记"）。**全部选择器都是内联字面量，没有常量模块** — 若要重构，抽常量是收益最高的一步。

### 6. 登录检测是"否定优先"且 fail-closed

`_check_login:3843` 必须先查未登录标志（二维码、"扫码登录"文案）再查已登录标志，因为登录弹窗浮层存在时底层的用户头像/链接**仍在 DOM 中**。默认返回 `False`（3907）。

### 7. 登录态的真实载体是 Chromium profile 目录，不是 cookies.json

`data/browser_profile/`（3617）。`ChromiumPage` 未指定端口，走默认 9222 — **本机已开的 Chrome 调试实例会被直接接管**。

---

## 线程模型

一个 daemon 工作线程，每次爬取新建（3570）；`is_running`(717) 防重入。

- **日志走队列**：`log()`(3347) → `log_queue` → `_start_log_consumer`(3354) 的 `root.after(100,…)` 轮询排空。
- **控件变更走 `root.after(0, …)`**：表格插行(4200)、仪表盘(3782)、按钮恢复(3830)、登录弹窗(3930)。
- **停止是协作式布尔量** `should_stop`(718)，非 `Event`；轮询点 3590/3646/3691/3736/4040/4271/4948，并以 `lambda: self.should_stop` 传入下载器实现可中断下载。
- `_wait_for_login:3912` 是全文唯一正确的双向同步：worker 阻塞在 `threading.Event`，弹窗经 `root.after(0,…)` 派发到主线程。

✅ **v5.3：`_update_ui` 已自带线程派发**——非主线程调用时自动经 `root.after(0,…)` 转到主线程；worker 线程里其余 `root.after` 调用统一改用 `_safe_after`（窗口销毁后吞掉 RuntimeError）。**新增工作线程侧的 UI 更新，用 `_safe_after(...)` 或 `_update_ui(...)`，不要直接碰控件或裸调 `root.after`。**

---

## 数据与存储

### SQLite：单表 `notes`（293-323）

`note_id TEXT UNIQUE` + `INSERT OR REPLACE`(332) ⇒ 重爬是**整行覆盖**，不保留历史，无法做时序对比。
`tags` / `image_urls` / `comments` 三列是 `json.dumps` 后的 TEXT，读取侧需 `json.loads`（1944-1950）。

✅ **v5.3：已加 `local_dir TEXT` 列**（`_init_db` 内含 `ALTER TABLE` 自动迁移），入库时写入笔记媒体目录相对路径，历史数据已按 mtime 对齐回填。媒体反查现以此列为准。仍无 `local_images`/`local_video`/`batch_dir` 独立列（无必要）。

### 图片目录约定

```
images/{关键词|主页推荐}_{YYYYMMDD}_{HHMMSS}/     ← 批次层 (4017 / 4264)
    note_{idx+1}_{note_id | unix_timestamp}/      ← 笔记层 (5006 标准 / 4340 极速)
        img_{N}.jpg|.webp                          (5010)
        video.mp4                                  (5028)
        comments/comment_img_{N}.jpg               (5053)
```

`idx` 是**成功计数器**（4189 传入 `success`），不是页面位置 — 失败不占号。
笔记层后缀有**两种语义**：note_id（新，仅最新 commit e19478a 引入）或 unix 时间戳（旧/极速模式）。现存磁盘数据全是后者，因此**目录名无法反查 note_id**。

✅ **v5.3：两条反查路径（`_load_history_data`、`_load_image_previews`）均已优先读 `local_dir` 精确定位**；仅历史遗留数据才落到模糊回退，且视频笔记禁用模糊回退（避免张冠李戴）。**不要新增第三份实现**，也不要移除对 `local_dir` 的优先判断。

### Excel 导出：列名中译是单向的

`_save_data` 把英文键 rename 成中文列头再落盘（现用模块级 `EXPORT_COLUMN_MAPPING`）。

✅ **v5.3：回读侧（`_load_latest_data`、`_merge_data`、`_refresh_history`）已统一先 `normalize_df_columns(df)` 反向归一化**，统计/去重恢复正常。**任何"回读导出文件再处理"的新代码，必须先 `normalize_df_columns`。** 全仓仍有多套导出列名场景，勿再加新方案。

### 配置持久化：三处映射必须同步修改

✅ **v5.3：`_get_config` 已合并为直接调用 `_save_gui_settings`**（单一来源，不再是两份易漂移的映射）。新增设置项只需改**两处**：`_save_gui_settings`（写 tk 变量→config）和 `CrawlerConfig.save_to_file` 白名单。`_restore_gui_settings` 负责反向恢复到 UI。

- `_save_gui_settings` 现**逐字段**用 `_safe_int/_safe_float` 解析，单个非法值不再拖垮整批（原先整体 `except:pass`）。
- 高级设置（`click_delay`/`scroll_delay`/`save_cookies`/`log_to_file`/`db_path`）与 `window_width/height` **均已纳入持久化并在启动时恢复**。
- ✅ **配置在每次开始爬取时（`_get_config` 末尾 `save_to_file`）及正常关窗时都会保存**，崩溃不再丢失已开始过爬取的设置。

---

## GUI 结果页的数据源模型

结果页由**两个互不协调的下拉框**驱动四种显示模式，全部写入同一个 `result_tree`：

| 模式 | 触发 | 后备列表 | `current_batch_folder` |
|---|---|---|---|
| 当前爬取 | `_show_current_data:2011` | `all_notes_data`（内存） | `None` |
| 历史数据库 | `_load_history_data:1870` | `history_notes_data`（SQLite） | `None` |
| 批次汇总 | `_load_all_batch_images:1724` | `batch_notes_data` = **文件夹摘要 dict** | `None` |
| 单批次明细 | `_load_batch_images:1561` | `batch_notes_data` = **笔记 dict** | 绝对路径 |

**真正的判别式是 `current_batch_folder`，不是下拉框。** `_on_result_select:2062` 靠它区分后两种模式（2087、2146）。`batch_notes_data` 被刻意复用于两种记录结构 —— 这是全文件最易误读之处。

**行标识是位置性的，从不使用 key**：所有选中/删除/预览都靠 `int(values[0]) - 1`（2148、2183）反查后备列表。改动"序号"列内容，或做了排序却没把排序结果写回后备列表，会**同时**破坏选中、删除和预览。

**PhotoImage 引用保持**：`ImageTk.PhotoImage` 一旦失去 Python 引用即被 GC，画布变空白。代码统一存进 `self.preview_images`，该列表在每次渲染开头重置（2467）。**新增任何 `create_image` 调用，必须在同一处 append 到 `self.preview_images`。** 独立查看器用 `photo_ref = [None]` 闭包（2630）达到同样目的。

✅ **v5.3：`_open_image_viewer` 的重复定义已删除**，只保留带 `start_index` 的完整实现。预览点击改用 **canvas tag 命中检测**（`find_withtag('current')` + `img_{全局索引}` 标签），不再用坐标除法；分页数 `_preview_max_page()` 已把视频缩略图占的槽位计入。

---

## 已知未接线 / 已失效的功能

本节多数历史问题已在 v5.3 修复。**遇到相关 bug 报告时，先看本表状态列。**

| 功能 | 实况 |
|---|---|
| 爬取类型 博主主页 / 热门榜单 | ✅ 已接线。`_crawl_thread` 现按 `config.crawl_type` 分支：`blogger` 用 `blogger_url`、`hot` 走推荐流、`keyword` 走搜索。入口 URL 存于 `self._current_entry_url` |
| 速度模式"快速模式" | ✅ 已从 UI 移除（引擎中 fast≡standard）。现只有"标准/极速(turbo)"两项 |
| 点赞区间 / 笔记类型筛选 | ✅ 已生效。`_note_passes_filter` 在 `_standard_crawl` 提取后应用；不满足的笔记跳过且不计入连续失败。**已知权衡**：媒体在提取阶段已下载，被筛掉的笔记会在 images/ 留下孤儿目录——有意为之，因为准确的点赞数/类型只有打开详情页后才可靠，预筛会误杀 |
| 评论图片下载 | ✅ 已修。改用 `downloader.download_batch(...)`（原 `download_with_session` 不存在） |
| `CookieManager.load()` | ✅ 已接线。首次启动若未登录且存在 cookies.json，会尝试 `load()` 恢复会话（仍以 browser_profile 为主） |
| `_get_sorted_note_indices` | 仍是死代码（瀑布流视觉序排序无调用点）。**爬取顺序 = 裸 DOM 顺序 ≠ 视觉顺序**，未改 |
| `_browse_db_path` | ✅ 已回写 `config.db_path`（经 `_save_gui_settings`），改路径后重启生效 |
| `save_interval` | 仍是零引用死字段，未清理（避免无谓改动） |
| 跨运行去重 | `get_existing_note_ids` 仍未被调用；现存数据 `keyword` 列多为空串。未改（属功能增强而非 bug） |

### 本次新增的关键不变量（务必遵守）

- **`self.displayed_notes` 是结果表"行位置 → 数据"的唯一权威映射**。任何渲染表格的路径都必须
  同步写它（`_refresh_table_with_notes` 已统一处理；`_add_result_to_table`、批次两个加载器单独写）。
  `_on_result_select` 用 `result_tree.index(item)`（行位置）反查，**不要再退回 `int(values[0])-1`**
  （"序号"列在批次明细里有空洞、排序后与位置无关）。
- **工作线程更新 UI 一律用 `_safe_after(...)` 或 `_update_ui(...)`**，不要直接调 `root.after` 或碰控件
  （窗口关闭后 `root.after` 会抛 RuntimeError）。
- **回读任何导出文件（xlsx/csv）前必须先 `normalize_df_columns(df)`**，把中文列头转回英文键；
  落盘时用 `EXPORT_COLUMN_MAPPING` 转中文。二者是模块级单一来源，勿再造第四套列名方案。
- **媒体目录优先用 DB 的 `local_dir` 列定位**，别再依赖三级模糊反查（视频笔记已禁用模糊回退）。

---

## 编辑本仓库时的约定

**相对路径依赖** — `"images"` 和 `"data"` 全程作为裸相对路径使用（1273、1735、1917、2342、5600）。程序**只有以仓库根目录为 CWD 启动才能工作**。

**裸 `except: pass` 仍有残留**（早期类里的 207、358 等）。v5.3 已把新代码与热点路径的裸捕获改为具名异常 + `self.log(...)`。**新代码禁止沿用裸 `except:`**；至少要 `self.log(..., "ERROR")` 或打印。

**魔法数字与硬编码等待** — 单条笔记最坏约 6 秒固定 sleep，全部内联无常量。预览画布 `thumb_size=240`；画布宽度已改为运行时 `winfo_width()` 读取（不再硬编码 700）。

✅ **URL 双重编码** — 已收拢到 `_build_search_url()` 单一方法（原在两处重复的 `quote(quote(...))`）。仍是历史遗留的 cargo-cult 编码，未经实测勿改为单次编码。

**函数/文件体量** — 全局规范要求函数 <50 行、文件 <800 行。本文件约 6100 行、`_extract_full_note` 700+ 行，已严重超标。**不要为了"符合规范"发起大范围重构**；按最小单元逐步改，拆分时优先 `_extract_full_note`。

**改动后如何验证**（本仓库无测试框架，只能手动+脚本）：GUI 逻辑可用无头脚本驱动——
`CrawlerApp()` 起实例后直接调方法、断言 `displayed_notes`/统计标签，用 `PIL.ImageGrab` 截图核验；
真实爬取需已登录的 `browser_profile`，且当前网络不能被小红书 IP 风控拦截。

**提交信息用中文**，沿用现有前缀风格：`修复: xxx` / `优化: xxx` / `配置: xxx` / `v5.3: xxx`。

**可安全复用的组件**：`FileLogger:185`、`CookieManager:211`、`MediaDownloader.download_batch:474`（协作式取消模型）设计合理。

---

## ⚠️ data/ 与 images/ 中的非爬虫产物

`data/` 与三个 `images/` 批次目录中存在 **4 份字节相同的 `~$cache1`**（771584 B，头部 `4D 5A 50` = Delphi PE 可执行文件）。它们**不是** Office 临时文件（真锁文件名为 `~$<原名>.xlsx` 且仅数百字节）。

同时 `data/*.xlsm` 内含的是一份无关的 33 表《环境质量指标》工作簿，**不是爬取数据** —— 而 `_save_data:5494-5500` 只会写 `.xlsx`/`.csv`/`.json`，**代码不可能产出 `.xlsm`**。

对开发的影响：
- ✅ **`.gitignore` 已补上 `~$*` 与 `*.xlsm`**（本次修改），`git add .` 不会再误提交这些文件。
- ✅ 图表/词云/报告/历史统计已改为**从 SQLite 读取**，不再受这些损坏文件影响（不再恒为空）。
- ⚠️ `_zip_images` 仍会把 images/ 下的 `~$cache1` 一并打进分发 zip（gitignore 不影响 zip 打包）。

⚠️ **这些文件本身仍在磁盘上，未删除**（删除不可逆且样本可能需送检）。建议用户杀毒扫描后再自行清理；不要在未确认时替用户删除或打包。
