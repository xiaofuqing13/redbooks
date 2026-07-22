# 小红书爬虫工具

![Python](https://img.shields.io/badge/Python-3.8%2B-3776AB?logo=python&logoColor=white) ![DrissionPage](https://img.shields.io/badge/DrissionPage-Chromium%20automation-2EAD33) ![CustomTkinter](https://img.shields.io/badge/UI-CustomTkinter-FF2442) ![License](https://img.shields.io/badge/License-MIT-green)


一个功能完整的小红书笔记爬虫工具，支持关键词搜索、主页推荐、博主主页爬取，具有图形化界面。

## 界面预览

> 以下均为应用真实运行截图（v5.4）。

| 搜索爬取 | 爬取结果 |
|:---:|:---:|
| ![搜索爬取](docs/screenshots/main.png) | ![爬取结果](docs/screenshots/results.png) |

| 笔记详情卡片 | 数据分析 |
|:---:|:---:|
| ![笔记详情卡片](docs/screenshots/note_card.png) | ![数据分析](docs/screenshots/analysis.png) |

## 功能特点

- **多种爬取模式**：标准模式（完整数据）、极速模式（快速采集）
- **多种爬取类型**：关键词搜索、主页推荐、博主主页
- **完整数据采集**：标题、作者、正文、标签、发布时间、IP地区、互动数据
- **媒体下载**：图片批量下载、视频下载、评论图片单独存储
- **智能过滤**：表情包过滤、Live图去重（只保留一张）
- **数据导出**：Excel导出、SQLite数据库存储
- **图形化界面**：斑马纹表格、搜索筛选、排序、数据统计、图片预览
- **配置持久化**：自动保存上次设置

## 环境要求

- Python 3.8+
- Windows 10/11

## 安装依赖

```bash
pip install -r requirements.txt
```

主要依赖：
- DrissionPage - 浏览器自动化
- pandas - 数据处理
- openpyxl - Excel导出
- Pillow - 图片处理
- jieba - 中文分词（词云）

## 使用方法

```bash
python crawler_ultimate.py
```

## 目录结构

```
redbooks/
├── crawler_ultimate.py    # 主程序
├── requirements.txt       # 依赖列表
├── README.md             # 说明文档
├── data/                 # 数据目录
│   ├── settings.json     # 配置文件
│   ├── redbook.db        # SQLite数据库
│   ├── cookies.json      # Cookie（隐私，已 gitignore）
│   └── browser_profile/  # Chromium 登录态目录（登录态的真实载体）
├── images/               # 图片保存目录
│   └── {关键词|主页推荐}_{YYYYMMDD}_{HHMMSS}/   # 批次层
│       └── note_{序号}_{noteId}/                 # 笔记层
│           ├── img_1.jpg
│           ├── video.mp4          # 视频类型笔记不再保存封面图
│           └── comments/
│               └── comment_img_1.jpg
└── docs/                 # 文档目录
    ├── 功能说明文档.md
    ├── 小红书页面结构分析.md
    └── 爬取流程模拟分析.md
```

## 功能说明

### 速度模式

| 模式 | 说明 | 适用场景 |
|------|------|----------|
| 标准模式 | 点击笔记进入详情页提取完整数据 | 需要完整内容、评论、互动数据 |
| 极速模式 | 仅从列表页提取基础信息 | 快速批量采集封面图 |

> v5.3 起移除了原“快速模式”——它与标准模式在引擎中完全等价，是误导性选项。

### 爬取类型

- **关键词搜索**：搜索指定关键词的笔记（关键词框支持逗号分隔多词）
- **热门榜单 / 主页推荐**：爬取首页推荐内容（忽略关键词）
- **博主主页**：填写博主主页 URL，爬取该博主的笔记

### 数据字段（SQLite `notes` 表）

| 字段 | 说明 |
|------|------|
| note_id | 笔记唯一 ID（去重键） |
| title / author / content | 标题 / 作者 / 正文 |
| tags | 标签（JSON 数组） |
| publish_time / ip_region | 发布时间 / IP地区 |
| like_count / collect_count / comment_count | 点赞 / 收藏 / 评论数 |
| note_type / note_link | 类型（图文/视频）/ 原文链接 |
| image_urls / video_url / comments | 图片链接 / 视频链接 / 评论（JSON） |
| keyword / crawl_time | 搜索关键词 / 爬取时间 |
| local_dir | 本地媒体目录（图片预览定位用） |

### GUI功能

- 小红书品牌红主题（v5.4 全界面统一 CustomTkinter 渲染）
- 结果页数据源三选一：当前爬取 / 历史数据库 / 本地批次
- 斑马纹表格、点击表头排序、搜索筛选（标题/作者/正文/关键词四列）
- 统计药丸（总计、图文数、视频数、总点赞）与数据分析仪表盘
- 右键菜单（复制、打开原文、删除）
- 小红书式笔记详情卡片：暗遮罩一体弹窗、模糊填充轮播、悬浮翻页圆钮、
  流式评论区、上一条/下一条翻页
- 跨运行去重开关：重复采集同一主题时自动跳过库里已有笔记

## 配置说明

配置保存在 `data/settings.json`，在**每次开始爬取时**以及**正常关闭窗口时**自动保存
（v5.3 起：不再仅依赖点 X 关闭，崩溃也不丢已开始过爬取的设置）。高级设置页
（Cookie/日志/延迟/数据库路径）现已一并持久化。修改数据库路径后需重启程序生效。

## 数据分析

“数据分析”页的统计仪表盘、图表、词云、报告均直接读取 SQLite 数据库
（不再依赖易损的导出文件）。图表/词云/报告为**可选功能**，需额外安装依赖：

```bash
pip install matplotlib wordcloud jieba python-docx
```

未安装时对应按钮会给出明确提示。

## 注意事项

1. 首次使用需要登录小红书账号（扫码），登录态保存在 `data/browser_profile/`
2. 若日志提示“IP 存在风险/访问被拦截”，请更换网络环境（切换 IP、关闭代理）后重试
3. 建议适当设置爬取间隔，避免被限制
4. 遵守小红书的服务条款和 robots.txt，仅供学习研究使用

## 更新日志

### v5.4
- 全界面重做为小红书品牌红主题：设计令牌单一来源、CustomTkinter 统一渲染、
  卡片化布局、指标化仪表盘
- 结果页视图理顺为数据源三选一（当前爬取/历史数据库/本地批次），批次控件
  仅在批次模式可用；合并重复的"搜索/关键词"筛选框
- 主页一站式：快捷预设/Cookie 状态前置、停止键即时反馈、爬完自动切结果页
- 新增跨运行去重（默认关）：库里已有的笔记直接跳过，不再重复下载
- 笔记详情重做为小红书式一体弹窗：暗遮罩、模糊填充轮播、悬浮翻页/关闭圆钮
  （Lucide 图标）、流式评论区、上一条/下一条翻页、ESC 关闭

### v5.3（大修）
- 修复评论图片下载（此前调用不存在的方法，100% 静默失效）
- 接线“博主主页/热门榜单”爬取类型与“点赞区间/笔记类型”筛选（此前引擎从不读取）
- 数据库新增 `local_dir` 列，彻底解决图片预览张冠李戴（含历史数据回填）
- 修复排序后选中/预览错位、结果表列语义不一致、历史模式统计恒为 0
- 修复预览点击命中错位、分页漏最后一张、评论图无法点开
- 修复导出文件回读列名错配（统计恒为 0、去重不生效）
- 线程安全加固、配置逐字段安全解析、下载器并发计数加锁
- 移除误导性死选项“快速模式”；识别 IP 风控页并明确提示
- 修复标题提取误抓弹窗“猜你想搜”组件文本（改为 `__INITIAL_STATE__` 优先 + UI 文本黑名单）

### 2026-02-02
- 修复数据缓存问题（使用URL中的noteId）
- 添加Live图过滤（只保留一张）
- 优化GUI界面（斑马纹、排序、筛选、统计卡片）



## License

MIT License
