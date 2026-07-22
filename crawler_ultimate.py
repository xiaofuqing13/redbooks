# -*- coding: utf-8 -*-
"""
小红书爬虫终极版 v5.0
功能：视频下载、评论爬取、正文内容、标签提取、博主爬取、数据可视化、Cookie管理
优化：性能提升、稳定性增强、UI改进
"""

import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext, filedialog

# CustomTkinter 是界面的必需依赖，不再是可选美化项。
# 曾经的 "有则用 CTk、无则退回 tk" 双路径正是界面观感割裂的根源：
# 同一屏里 Win95 凹陷输入框与现代圆角按钮并存。统一为单一渲染体系后，
# 缺失依赖就明确报错，而不是静默降级成另一套长相。
try:
    import customtkinter as ctk
    ctk.set_appearance_mode("light")  # 本程序固定浅色，深色需另配图表/预览色
    HAS_CTK = True
except ImportError:
    HAS_CTK = False
    _root = tk.Tk()
    _root.withdraw()
    messagebox.showerror(
        "缺少依赖",
        "界面依赖 customtkinter，尚未安装。\n\n"
        "请在项目目录执行：\n    pip install customtkinter\n"
        "或：\n    pip install -r requirements.txt"
    )
    _root.destroy()
    raise SystemExit(1)
import threading
import queue
import json
import os
import time
import random
import re
import zipfile
import sqlite3
from typing import Optional, List, Dict, Any, Tuple, Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import quote
from datetime import datetime
from collections import Counter
from dataclasses import dataclass, field

import pandas as pd
import requests
from DrissionPage import ChromiumPage, ChromiumOptions

# 版本信息
VERSION = "5.4"
APP_NAME = f"小红书爬虫终极版 v{VERSION}"


def _enable_dpi_awareness():
    """声明进程 DPI 感知，必须在创建任何 tk 窗口之前调用。

    不声明时，高分屏（如 4K@175%）上 Windows 会对整个 Tk 界面做位图
    拉伸——字体发虚、控件比例失真，且 Tk 只能看到被虚拟化的低分辨率，
    导致保存的窗口尺寸下次启动时溢出屏幕。声明为 System-Aware 后界面
    清晰，且点号字体（如 14pt）会按真实 DPI 自动放大到正确物理尺寸。
    """
    try:
        import ctypes
        try:
            # PROCESS_SYSTEM_DPI_AWARE = 1（比 per-monitor 更稳，够用）
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            ctypes.windll.user32.SetProcessDPIAware()  # 老系统回退
    except Exception:
        pass  # 非 Windows 或无相关 API，忽略

# ============================================================
# 设计令牌 —— 全部 UI 颜色 / 字体 / 间距的单一来源
# ============================================================
# ⚠️ 新增界面代码一律从这里取值，不要再往控件上写 '#3b82f6' 这类
#    颜色字面量或 ('Microsoft YaHei UI', 14) 这类内联字体元组。
#    本文件历史上散落着近百处内联字体与 hex，换一次主题得全文替换。
#    配色方向：小红书品牌红为主色，中性灰承载信息，语义色仅用于状态。
C = {
    'brand':        '#FF2442',   # 品牌主色：主按钮 / 选中态 / 强调数字
    'brand_hover':  '#E01834',
    'brand_soft':   '#FFF0F2',   # 主色的极浅底：选中行、徽标背景
    'brand_border': '#FFD3DA',

    'danger':       '#E5484D',   # 停止 / 删除
    'danger_hover': '#C93B40',
    'success':      '#12864F',   # 成功日志 / 图文标记
    'warning':      '#B76E00',   # 警告日志 / 依赖缺失提示
    'info':         '#2563EB',   # 链接类信息

    'bg':           '#F2F3F5',   # 窗口底色（比卡片深一档，卡片才浮得起来）
    'card':         '#FFFFFF',   # 卡片 / 输入框 / 表格底
    'card_alt':     '#FAFAFB',   # 斑马纹、只读区底色
    'border':       '#E4E6EB',   # 常规描边
    'border_strong':'#D0D3D9',   # 输入框描边（需要更清晰的可点区域暗示）

    'text':         '#1A1A1A',   # 主文字
    'text_sub':     '#6B7280',   # 次要文字 / 标签
    'text_faint':   '#9CA3AF',   # 占位提示 / 禁用态
    'text_on_brand':'#FFFFFF',

    'row_video':    '#9A4A44',   # 表格中视频行的文字（低饱和暖褐，克制区分）
    'hover':        '#E9EAEE',   # 未选中标签页的悬停底
    'warn_soft':    '#FFF8EC',   # 警告提示的浅底

    'canvas':       '#F7F7F8',   # 预览画布底
    'viewer_bg':    '#1A1A1A',   # 图片查看器深色底
    'viewer_btn':   '#2E2E2E',   # 查看器按钮底
    'viewer_btn_h': '#3D3D3D',
    'viewer_text':  '#E8E8E8',
}

# 图表配色：与界面同源，生成的 PNG 才像同一个产品出来的
CHART_COLORS = [C['brand'], '#2D9C8F', '#E8A33D', '#6B7280', '#8B5CF6']

# 评论区头像占位色板 (底色, 字色)：按作者名 hash 取，低饱和不抢正文
AVATAR_PALETTE = [
    ('#FFE4E8', '#C2334D'),
    ('#E7F0FE', '#2563EB'),
    ('#E6F6EE', '#12864F'),
    ('#FFF3E0', '#B76E00'),
    ('#F1EAFE', '#7C3AED'),
    ('#E8F7F6', '#0E7C6B'),
]

FONT_FAMILY = 'Microsoft YaHei UI'
FONT_MONO = 'Consolas'

# 字号层级：正文 14 为基准（适中），靠 ±1~2 与字重拉开层次。
# 过大在 1080p/笔记本上会挤爆日志区；过小在 4K 上发虚。
FS_METRIC = 26   # 仪表盘大数字
FS_TITLE = 15    # 卡片标题 / 详情标题
FS_BASE = 14     # 正文、绝大多数控件
FS_SMALL = 13    # 辅助说明、表格内文字
FS_MONO = 13     # 日志等宽


def UI_FONT(size: int = FS_BASE, bold: bool = False) -> tuple:
    """构造界面字体元组。取代全文内联的 ('Microsoft YaHei UI', 14)。"""
    return (FONT_FAMILY, size, 'bold') if bold else (FONT_FAMILY, size)


# 间距刻度（像素）：统一节奏，避免各处 pady=2/5/8/10 随手写
SP_XS, SP_SM, SP_MD, SP_LG = 4, 8, 12, 18

# 控件默认尺寸：所有工厂方法与新代码应引用这里
CTRL_H = 34          # 输入框 / 下拉 / 次要按钮高度
BTN_H = 36           # 主操作按钮高度
CTRL_RADIUS = 8      # 输入/按钮圆角
CARD_RADIUS = 10     # 卡片圆角
ROW_H = 38           # Treeview 行高（与 FS_SMALL 匹配）
CHIP_H = 28          # 统计药丸高度
LABEL_W = 76         # 表单字段标签统一宽度
LOG_MIN_H = 200      # 运行日志最小高度，防止被上方卡片挤没

# 导出文件（xlsx/csv）的列名中译映射。
# ⚠️ 写盘用中文列头，但所有回读代码按英文键取列 —— 回读任何导出文件
# 前必须先经 normalize_df_columns() 反向归一化，否则统计恒为 0、
# 去重永不生效（曾是三处静默失效的根因）。
EXPORT_COLUMN_MAPPING = {
    'keyword': '搜索关键词',
    'title': '标题',
    'author': '作者',
    'content': '正文内容',
    'tags': '标签',
    'publish_time': '发布时间',
    'ip_region': 'IP地区',
    'like_count': '点赞数',
    'collect_count': '收藏数',
    'comment_count': '评论数',
    'comments': '评论内容',
    'note_type': '笔记类型',
    'note_link': '笔记链接',
    'note_id': '笔记ID',
    'video_url': '视频链接',
    'image_urls': '图片链接',
    'image_count': '图片数量',
    'local_images': '本地图片路径',
    'local_video': '本地视频路径',
    'local_dir': '本地目录',
}
EXPORT_COLUMN_MAPPING_REV = {v: k for k, v in EXPORT_COLUMN_MAPPING.items()}


def normalize_df_columns(df):
    """把导出文件的中文列头归一化回英文键（英文列头原样保留，幂等）"""
    return df.rename(columns=EXPORT_COLUMN_MAPPING_REV)

# 可选依赖
try:
    import matplotlib.pyplot as plt
    import matplotlib
    matplotlib.use('Agg')  # 非交互式后端
    HAS_MATPLOTLIB = True
except:
    HAS_MATPLOTLIB = False

try:
    from wordcloud import WordCloud
    import jieba
    HAS_WORDCLOUD = True
except:
    HAS_WORDCLOUD = False

try:
    from docx import Document
    from docx.shared import Inches
    HAS_DOCX = True
except:
    HAS_DOCX = False


@dataclass
class CrawlerConfig:
    """爬虫配置（使用dataclass提升可维护性）"""
    # 基础配置
    keyword: str = ""
    scroll_times: int = 10
    max_notes: int = 30
    parallel_downloads: int = 10
    retry_times: int = 2
    save_interval: int = 10
    
    # 爬取内容选项（默认全部开启）
    download_images: bool = True
    download_videos: bool = True
    get_all_images: bool = True
    get_content: bool = True
    get_tags: bool = True
    get_publish_time: bool = True
    get_comments: bool = True
    comments_count: int = 20
    get_interactions: bool = True
    
    # 爬取模式
    crawl_mode: str = "standard"  # standard/fast/turbo
    crawl_type: str = "keyword"   # keyword/blogger/hot
    blogger_url: str = ""
    
    # 筛选条件
    min_likes: int = 0
    max_likes: int = 999999
    note_type_filter: str = "全部"
    date_filter: str = "全部"
    # 跨运行去重：跳过数据库里已有的笔记（按 note_id），重复采集同一
    # 主题时不再重复打开详情页/下载媒体。默认关闭——重爬覆盖旧数据
    # 是既有语义（INSERT OR REPLACE），开启与否交给用户。
    skip_existing: bool = False
    
    # 导出选项
    export_format: str = "xlsx"
    export_to_db: bool = True
    db_path: str = "data/redbook.db"
    
    # 速度控制（元组默认值需要用field）
    click_delay: Tuple[float, float] = field(default_factory=lambda: (0.2, 0.4))
    scroll_delay: Tuple[float, float] = field(default_factory=lambda: (0.3, 0.5))
    
    # Cookie和日志
    save_cookies: bool = True
    cookies_file: str = "data/cookies.json"
    log_to_file: bool = True
    log_file: str = "data/crawler.log"
    
    # 配置文件路径
    config_file: str = "data/settings.json"
    
    # 窗口位置
    window_x: int = -1
    window_y: int = -1
    window_width: int = 1280
    window_height: int = 820
    
    def save_to_file(self):
        """保存配置到文件"""
        import json
        try:
            # 确保data目录存在
            os.makedirs("data", exist_ok=True)
            config_dict = {
                'keyword': self.keyword,
                'scroll_times': self.scroll_times,
                'max_notes': self.max_notes,
                'parallel_downloads': self.parallel_downloads,
                'retry_times': self.retry_times,
                'download_images': self.download_images,
                'download_videos': self.download_videos,
                'get_all_images': self.get_all_images,
                'get_content': self.get_content,
                'get_tags': self.get_tags,
                'get_publish_time': self.get_publish_time,
                'get_comments': self.get_comments,
                'comments_count': self.comments_count,
                'get_interactions': self.get_interactions,
                'crawl_mode': self.crawl_mode,
                'crawl_type': self.crawl_type,
                'blogger_url': self.blogger_url,
                'min_likes': self.min_likes,
                'max_likes': self.max_likes,
                'note_type_filter': self.note_type_filter,
                'date_filter': self.date_filter,
                'skip_existing': self.skip_existing,
                'export_format': self.export_format,
                'export_to_db': self.export_to_db,
                # 高级设置（此前缺失，导致整页高级设置退出即丢）
                'save_cookies': self.save_cookies,
                'log_to_file': self.log_to_file,
                'click_delay': list(self.click_delay),
                'scroll_delay': list(self.scroll_delay),
                'db_path': self.db_path,
                'window_x': self.window_x,
                'window_y': self.window_y,
                'window_width': self.window_width,
                'window_height': self.window_height,
            }
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(config_dict, f, ensure_ascii=False, indent=2)
            print(f"[配置] 已保存到 {self.config_file}")
        except Exception as e:
            print(f"[配置] 保存失败: {e}")
    
    def load_from_file(self):
        """从文件加载配置"""
        import json
        if not os.path.exists(self.config_file):
            print(f"[配置] 配置文件不存在，使用默认设置")
            return False
        try:
            with open(self.config_file, 'r', encoding='utf-8') as f:
                config_dict = json.load(f)
            # 更新配置
            for key, value in config_dict.items():
                if hasattr(self, key):
                    # JSON 无元组类型，延迟区间需转回 tuple
                    if key in ('click_delay', 'scroll_delay') and isinstance(value, list):
                        value = tuple(value)
                    setattr(self, key, value)
            print(f"[配置] 已加载上次设置 (max_notes={self.max_notes}, keyword={self.keyword})")
            return True
        except Exception as e:
            print(f"[配置] 加载失败: {e}")
            return False


class FileLogger:
    """文件日志记录器（线程安全）"""
    
    def __init__(self, log_file: str):
        self.log_file = log_file
        self._lock = threading.Lock()
        self._ensure_dir()
    
    def _ensure_dir(self):
        """确保日志目录存在"""
        log_dir = os.path.dirname(self.log_file)
        if log_dir:
            os.makedirs(log_dir, exist_ok=True)
        
    def log(self, message: str, level: str = "INFO"):
        """线程安全的日志写入"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_line = f"[{timestamp}] [{level}] {message}\n"
        with self._lock:
            try:
                with open(self.log_file, 'a', encoding='utf-8') as f:
                    f.write(log_line)
            except Exception:
                pass


class CookieManager:
    """Cookie管理器（支持过期检测）"""
    
    def __init__(self, cookies_file: str):
        self.cookies_file = cookies_file
        self._lock = threading.Lock()
    
    def _ensure_dir(self):
        """确保目录存在"""
        cookie_dir = os.path.dirname(self.cookies_file)
        if cookie_dir:
            os.makedirs(cookie_dir, exist_ok=True)
        
    def save(self, page) -> bool:
        """保存Cookie"""
        with self._lock:
            try:
                cookies = page.cookies()
                self._ensure_dir()
                # 添加保存时间戳
                data = {
                    'cookies': cookies,
                    'saved_at': datetime.now().isoformat(),
                    'version': VERSION
                }
                with open(self.cookies_file, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                return True
            except Exception:
                return False
    
    def load(self, page) -> bool:
        """加载Cookie"""
        with self._lock:
            try:
                if not os.path.exists(self.cookies_file):
                    return False
                    
                with open(self.cookies_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                # 兼容旧格式
                cookies = data.get('cookies', data) if isinstance(data, dict) else data
                
                loaded = 0
                for cookie in cookies:
                    try:
                        page.set.cookies(cookie)
                        loaded += 1
                    except Exception:
                        pass
                return loaded > 0
            except Exception:
                return False
    
    def exists(self) -> bool:
        """检查Cookie是否存在"""
        return os.path.exists(self.cookies_file)
    
    def get_saved_time(self) -> Optional[str]:
        """获取Cookie保存时间"""
        try:
            if not os.path.exists(self.cookies_file):
                return None
            with open(self.cookies_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return data.get('saved_at', '未知')
        except Exception:
            return None
    
    def clear(self):
        """清除Cookie"""
        if os.path.exists(self.cookies_file):
            os.remove(self.cookies_file)


class DatabaseManager:
    """数据库管理器"""
    def __init__(self, db_path):
        self.db_path = db_path
        self._init_db()
    
    def _init_db(self):
        """初始化数据库"""
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                note_id TEXT UNIQUE,
                title TEXT,
                author TEXT,
                content TEXT,
                tags TEXT,
                publish_time TEXT,
                ip_region TEXT,
                like_count INTEGER,
                collect_count INTEGER,
                comment_count INTEGER,
                note_type TEXT,
                note_link TEXT,
                image_urls TEXT,
                video_url TEXT,
                comments TEXT,
                keyword TEXT,
                crawl_time TEXT,
                local_dir TEXT
            )
        ''')

        # 迁移：为已有数据库补上 local_dir 列。
        # 该列存储笔记媒体目录的相对路径，是图片预览定位的唯一可靠依据；
        # 缺少它时代码只能靠 note_id 子串扫描 + crawl_time ±30 分钟模糊
        # 匹配，会把别的笔记的图片显示到当前行上。
        cursor.execute("PRAGMA table_info(notes)")
        existing_cols = {row[1] for row in cursor.fetchall()}
        if 'local_dir' not in existing_cols:
            cursor.execute('ALTER TABLE notes ADD COLUMN local_dir TEXT')

        conn.commit()
        conn.close()

    def insert_note(self, note_data):
        """插入笔记"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        try:
            cursor.execute('''
                INSERT OR REPLACE INTO notes
                (note_id, title, author, content, tags, publish_time, ip_region,
                 like_count, collect_count, comment_count, note_type, note_link,
                 image_urls, video_url, comments, keyword, crawl_time, local_dir)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                note_data.get('note_id', ''),
                note_data.get('title', ''),
                note_data.get('author', ''),
                note_data.get('content', ''),
                json.dumps(note_data.get('tags', []), ensure_ascii=False),
                note_data.get('publish_time', ''),
                note_data.get('ip_region', ''),
                note_data.get('like_count', 0),
                note_data.get('collect_count', 0),
                note_data.get('comment_count', 0),
                note_data.get('note_type', ''),
                note_data.get('note_link', ''),
                json.dumps(note_data.get('image_urls', []), ensure_ascii=False),
                note_data.get('video_url', ''),
                json.dumps(note_data.get('comments', []), ensure_ascii=False),
                note_data.get('keyword', ''),
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                note_data.get('local_dir', '')
            ))
            conn.commit()
            return True
        except Exception as e:
            # 入库失败此前完全静默，导致数据丢失无法察觉
            print(f"[DB] 写入笔记失败 note_id={note_data.get('note_id','')}: {e}")
            return False
        finally:
            conn.close()
    
    def get_existing_note_ids(self, keyword):
        """获取某关键词下已存在的笔记ID（历史遗留：keyword 列多为空串，
        按关键词过滤基本查不到东西，跨运行去重请用 get_all_note_ids）"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('SELECT note_id FROM notes WHERE keyword = ?', (keyword,))
        ids = set(row[0] for row in cursor.fetchall())
        conn.close()
        return ids

    def get_all_note_ids(self) -> set:
        """全库笔记ID集合，供"跳过已爬取"用。

        不按 keyword 过滤：现存数据的 keyword 列大多是空串（主页推荐/
        博主抓取不写该列），按关键词筛会漏掉几乎全部已有记录。
        全库 note_id 均为短字符串，十万条量级也只占几 MB，直接整表载入。
        """
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute('SELECT note_id FROM notes WHERE note_id IS NOT NULL')
            return set(row[0] for row in cursor.fetchall() if row[0])
        finally:
            conn.close()


class MediaDownloader:
    """高性能媒体下载器（支持图片和视频）"""
    
    # 常用User-Agent列表，随机选择以避免被封
    USER_AGENTS = [
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    ]
    
    def __init__(self, max_workers: int = 10, retry_times: int = 2, timeout: int = 15):
        self.max_workers = max_workers
        self.retry_times = retry_times
        self.timeout = timeout
        self._session = None
        self._stats = {'success': 0, 'failed': 0, 'bytes': 0}
        # 下载 worker 并发访问 Session 懒加载与统计计数，必须加锁：
        # 无锁的 += 是读-改-写竞态，统计会偏低；懒加载竞态会丢 Cookie
        self._lock = threading.Lock()

    @property
    def session(self) -> requests.Session:
        """懒加载Session，复用连接（加锁防止并发重复创建）"""
        if self._session is None:
            with self._lock:
                if self._session is None:
                    s = requests.Session()
                    s.headers.update({
                        'User-Agent': random.choice(self.USER_AGENTS),
                        'Referer': 'https://www.xiaohongshu.com/',
                        'Accept': 'image/webp,image/apng,image/*,video/*,*/*;q=0.8',
                        'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
                        'Origin': 'https://www.xiaohongshu.com',
                    })
                    self._session = s
        return self._session
    
    def set_cookies(self, cookies):
        """设置Cookie（用于需要认证的下载）"""
        if cookies:
            for cookie in cookies:
                self.session.cookies.set(
                    cookie.get('name', ''),
                    cookie.get('value', ''),
                    domain=cookie.get('domain', '.xiaohongshu.com')
                )
    
    def _normalize_url(self, url: str) -> str:
        """标准化URL；视频 CDN 强制 https，去掉尾部无用转义"""
        if not url:
            return ""
        url = str(url).strip().replace("\\u002F", "/").replace("\\/", "/")
        if url.startswith("//"):
            url = "https:" + url
        if not url.startswith("http"):
            url = "https://" + url
        # 小红书媒体 CDN 用 http 常被拦，统一升 https
        if url.startswith("http://") and ("xhscdn.com" in url or "xiaohongshu.com" in url):
            url = "https://" + url[len("http://"):]
        return url

    def download_file(self, url: str, local_path: str,
                      stop_flag: Optional[Callable] = None,
                      min_size: int = 1024,
                      is_video: bool = False) -> Optional[str]:
        """下载单个文件。视频加大超时/重试，并带更完整的防盗链头。"""
        url = self._normalize_url(url)
        if not url or url.startswith("blob:"):
            return None

        retries = max(self.retry_times, 4 if is_video else self.retry_times)
        timeout = max(self.timeout, 90 if is_video else self.timeout)
        headers = {
            "Referer": "https://www.xiaohongshu.com/",
            "Origin": "https://www.xiaohongshu.com",
            "User-Agent": random.choice(self.USER_AGENTS),
            "Accept": "*/*" if is_video else "image/webp,image/apng,image/*,*/*;q=0.8",
        }
        if is_video:
            headers["Accept-Encoding"] = "identity"

        last_err = ""
        for attempt in range(retries):
            if stop_flag and stop_flag():
                return None
            try:
                response = self.session.get(
                    url, timeout=timeout, stream=True, headers=headers,
                    allow_redirects=True)
                # 部分 CDN 对无 Cookie 返回 403/302 登录页
                if response.status_code >= 400:
                    last_err = f"HTTP {response.status_code}"
                    if attempt < retries - 1:
                        time.sleep(0.4 * (attempt + 1))
                        continue
                    break

                ctype = (response.headers.get("Content-Type") or "").lower()
                # m3u8 播放列表不是完整视频，记失败并换候选 URL
                if "mpegurl" in ctype or url.endswith(".m3u8"):
                    last_err = "m3u8 playlist"
                    break

                os.makedirs(os.path.dirname(local_path) or ".", exist_ok=True)
                total_size = 0
                with open(local_path, "wb") as f:
                    for chunk in response.iter_content(chunk_size=64 * 1024):
                        if stop_flag and stop_flag():
                            f.close()
                            if os.path.exists(local_path):
                                os.remove(local_path)
                            return None
                        if chunk:
                            f.write(chunk)
                            total_size += len(chunk)

                # 过小视为失败（防 HTML 错误页）
                need = min_size if not is_video else max(min_size, 30 * 1024)
                if total_size < need:
                    if os.path.exists(local_path):
                        os.remove(local_path)
                    last_err = f"too small {total_size}B"
                    if attempt < retries - 1:
                        time.sleep(0.3 * (attempt + 1))
                        continue
                    break

                # 视频文件头粗检：非 HTML
                try:
                    with open(local_path, "rb") as f:
                        head = f.read(16)
                    if head[:1] == b"<" or head[:15].lower().startswith(b"<!doctype"):
                        os.remove(local_path)
                        last_err = "got HTML"
                        continue
                except Exception:
                    pass

                with self._lock:
                    self._stats["success"] += 1
                    self._stats["bytes"] += total_size
                return local_path

            except requests.Timeout:
                last_err = "timeout"
                if attempt < retries - 1:
                    time.sleep(0.5 * (attempt + 1))
            except Exception as e:
                last_err = str(e)[:80]
                if attempt < retries - 1:
                    time.sleep(0.3 * (attempt + 1))

        with self._lock:
            self._stats["failed"] += 1
        self._last_error = last_err
        return None

    def download_video_candidates(self, urls: List[str], local_path: str,
                                  stop_flag: Optional[Callable] = None) -> Optional[str]:
        """依次尝试多个视频 URL（不同 CDN / backup），直到成功。"""
        seen = set()
        candidates = []
        for u in urls or []:
            nu = self._normalize_url(u)
            if not nu or nu in seen or nu.startswith("blob:"):
                continue
            seen.add(nu)
            candidates.append(nu)
            # originVideoKey 形态：尝试多 CDN 前缀
            for host in (
                "https://sns-video-bd.xhscdn.com/",
                "https://sns-video-al.xhscdn.com/",
                "https://sns-video-qc.xhscdn.com/",
                "https://sns-video-v3.xhscdn.com/",
            ):
                if "xhscdn.com/" in nu and "/stream/" in nu:
                    # 已是完整 stream URL，换 host 再试
                    try:
                        path = nu.split("xhscdn.com/", 1)[1]
                        alt = host + path
                        if alt not in seen:
                            seen.add(alt)
                            candidates.append(alt)
                    except Exception:
                        pass

        for u in candidates:
            if stop_flag and stop_flag():
                return None
            result = self.download_file(
                u, local_path, stop_flag=stop_flag, min_size=30 * 1024, is_video=True)
            if result:
                return result
        return None
    
    def download_batch(self, tasks: List[Tuple[str, str]], 
                       progress_callback: Optional[Callable] = None,
                       stop_flag: Optional[Callable] = None) -> Dict[str, Optional[str]]:
        """批量并行下载"""
        if not tasks:
            return {}
            
        results = {}
        completed = 0
        total = len(tasks)
        
        if stop_flag and stop_flag():
            return results
        
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_to_task = {}
            for url, path in tasks:
                if stop_flag and stop_flag():
                    break
                future = executor.submit(self.download_file, url, path, stop_flag)
                future_to_task[future] = (url, path)
            
            for future in as_completed(future_to_task):
                if stop_flag and stop_flag():
                    # 取消剩余任务
                    for f in future_to_task:
                        f.cancel()
                    break
                    
                url, path = future_to_task[future]
                try:
                    results[url] = future.result(timeout=self.timeout + 5)
                except Exception:
                    results[url] = None
                    
                completed += 1
                if progress_callback:
                    progress_callback(completed, total)
        
        return results
    
    def get_stats(self) -> Dict[str, int]:
        """获取下载统计"""
        with self._lock:
            return self._stats.copy()

    def reset_stats(self):
        """重置统计"""
        with self._lock:
            self._stats = {'success': 0, 'failed': 0, 'bytes': 0}
    
    def close(self):
        """关闭Session"""
        if self._session:
            self._session.close()
            self._session = None


class DataAnalyzer:
    """数据分析器"""
    
    @staticmethod
    def generate_stats(df):
        """生成统计数据"""
        stats = {
            'total_notes': len(df),
            'total_likes': df['like_count'].sum() if 'like_count' in df.columns else 0,
            'avg_likes': df['like_count'].mean() if 'like_count' in df.columns else 0,
            'max_likes': df['like_count'].max() if 'like_count' in df.columns else 0,
            'total_collects': df['collect_count'].sum() if 'collect_count' in df.columns else 0,
            'total_comments': df['comment_count'].sum() if 'comment_count' in df.columns else 0,
            'image_notes': len(df[df['note_type'] == '图文']) if 'note_type' in df.columns else 0,
            'video_notes': len(df[df['note_type'] == '视频']) if 'note_type' in df.columns else 0,
        }
        return stats
    
    @staticmethod
    def generate_charts(df, output_dir):
        """生成图表"""
        if not HAS_MATPLOTLIB:
            return []
        
        charts = []
        os.makedirs(output_dir, exist_ok=True)
        
        plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei']
        plt.rcParams['axes.unicode_minus'] = False
        
        try:
            # 点赞分布图
            if 'like_count' in df.columns:
                fig, ax = plt.subplots(figsize=(10, 6))
                df['like_count'].hist(bins=20, ax=ax, color=C['brand'], edgecolor='white')
                ax.set_title('点赞数分布', fontsize=14)
                ax.set_xlabel('点赞数')
                ax.set_ylabel('笔记数量')
                chart_path = os.path.join(output_dir, 'likes_distribution.png')
                plt.savefig(chart_path, dpi=100, bbox_inches='tight')
                plt.close()
                charts.append(chart_path)
            
            # 笔记类型饼图
            if 'note_type' in df.columns:
                fig, ax = plt.subplots(figsize=(8, 8))
                type_counts = df['note_type'].value_counts()
                ax.pie(type_counts.values, labels=type_counts.index, autopct='%1.1f%%',
                       colors=CHART_COLORS)
                ax.set_title('笔记类型分布', fontsize=14)
                chart_path = os.path.join(output_dir, 'type_distribution.png')
                plt.savefig(chart_path, dpi=100, bbox_inches='tight')
                plt.close()
                charts.append(chart_path)
            
            # Top10点赞笔记
            if 'like_count' in df.columns and 'title' in df.columns:
                fig, ax = plt.subplots(figsize=(12, 6))
                top10 = df.nlargest(10, 'like_count')
                titles = [t[:15] + '...' if len(t) > 15 else t for t in top10['title']]
                ax.barh(range(len(top10)), top10['like_count'], color=C['brand'])
                ax.set_yticks(range(len(top10)))
                ax.set_yticklabels(titles)
                ax.set_xlabel('点赞数')
                ax.set_title('Top10 热门笔记', fontsize=14)
                ax.invert_yaxis()
                chart_path = os.path.join(output_dir, 'top10_notes.png')
                plt.savefig(chart_path, dpi=100, bbox_inches='tight')
                plt.close()
                charts.append(chart_path)
                
        except Exception as e:
            pass
        
        return charts
    
    @staticmethod
    def generate_wordcloud(texts, output_path):
        """生成词云"""
        if not HAS_WORDCLOUD:
            return None
        
        try:
            # 合并文本并分词
            all_text = ' '.join(texts)
            words = jieba.cut(all_text)
            word_list = [w for w in words if len(w) > 1]
            word_freq = Counter(word_list)
            
            # 生成词云
            wc = WordCloud(
                font_path='C:/Windows/Fonts/simhei.ttf',
                width=800,
                height=400,
                background_color='white',
                max_words=100,
                colormap='viridis'
            )
            wc.generate_from_frequencies(word_freq)
            
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            wc.to_file(output_path)
            return output_path
        except:
            return None
    
    @staticmethod
    def generate_report(df, stats, charts, output_path, keyword):
        """生成Word分析报告"""
        if not HAS_DOCX:
            return None
        
        try:
            doc = Document()
            doc.add_heading(f'小红书数据分析报告 - {keyword}', 0)
            doc.add_paragraph(f'生成时间：{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
            
            # 统计概览
            doc.add_heading('数据概览', level=1)
            table = doc.add_table(rows=4, cols=2)
            table.style = 'Table Grid'
            
            stats_items = [
                ('总笔记数', stats.get('total_notes', 0)),
                ('总点赞数', stats.get('total_likes', 0)),
                ('平均点赞', f"{stats.get('avg_likes', 0):.1f}"),
                ('最高点赞', stats.get('max_likes', 0)),
            ]
            
            for i, (label, value) in enumerate(stats_items):
                table.rows[i].cells[0].text = label
                table.rows[i].cells[1].text = str(value)
            
            # 图表
            if charts:
                doc.add_heading('数据可视化', level=1)
                for chart in charts:
                    if os.path.exists(chart):
                        doc.add_picture(chart, width=Inches(6))
                        doc.add_paragraph('')
            
            # Top10列表
            doc.add_heading('热门笔记 Top10', level=1)
            if 'like_count' in df.columns:
                top10 = df.nlargest(10, 'like_count')
                for i, row in top10.iterrows():
                    title = row.get('title', '')[:50]
                    likes = row.get('like_count', 0)
                    doc.add_paragraph(f"• {title}... (点赞 {likes})")
            
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            doc.save(output_path)
            return output_path
        except:
            return None


class CrawlerApp:
    """爬虫GUI应用"""
    
    def __init__(self):
        # DPI 感知交由 CustomTkinter 统一处理，此处**不要**再调
        # _enable_dpi_awareness()：CTk 自带 per-monitor 缩放，手动叠加
        # SetProcessDpiAwareness 会双重放大（实测 4K@175% 下窗口被撑到
        # 近全屏 3844px）。该函数仅为无 CTk 的历史路径保留。
        self.root = ctk.CTk()
        self.root.configure(fg_color=C['bg'])
        self.root.title(APP_NAME)
        # DPI 缩放因子：DPI 感知后点号字体自动放大，最小尺寸也须同比放大，
        # 否则在 175% 屏上窗口相对字体过小、控件挤成一团
        self.ui_scale = self._detect_ui_scale()
        self.root.minsize(int(1000 * self.ui_scale), int(680 * self.ui_scale))
        
        self.config = CrawlerConfig()
        # 加载上次的配置
        self.config.load_from_file()
        
        self.downloader = MediaDownloader()
        self.cookie_mgr = CookieManager(self.config.cookies_file)
        self.file_logger = FileLogger(self.config.log_file)
        self.db_mgr = DatabaseManager(self.config.db_path)
        
        self.log_queue = queue.Queue()
        self.is_running = False
        self.should_stop = False
        self.all_notes_data = []
        self.current_crawl_dir = ""  # 当前爬取的目录
        self.batch_notes_data = []  # 批次笔记数据
        self.current_batch_folder = None  # 当前批次文件夹
        self.browser_page = None  # 保持浏览器实例，避免每次都重新登录
        
        self._setup_styles()
        self._create_ui()
        self._start_log_consumer()
        
        # 恢复上次的GUI设置
        self._restore_gui_settings()

        # 恢复窗口大小与位置——必须在 _create_ui 之后再设并锁定。
        # 若在建控件前设，DPI 放大后的控件自然尺寸会通过 pack 传播把
        # 窗口撑大到近全屏；此处 update_idletasks 后再 geometry 才生效。
        # 边界钳制见 _sane_window_geometry（防失效坐标溢出屏幕）。
        win_w, win_h, win_x, win_y = self._sane_window_geometry(
            self.config.window_width, self.config.window_height,
            self.config.window_x, self.config.window_y)
        self.root.update_idletasks()
        self.root.geometry(f"{win_w}x{win_h}+{win_x}+{win_y}")

        # 程序退出时关闭浏览器并保存配置
        self.root.protocol("WM_DELETE_WINDOW", self._on_closing)
    
    def _detect_ui_scale(self) -> float:
        """DPI 缩放因子（诊断用）。有 CTk 时 Tk 层为 DPI-unaware，
        winfo 坐标已是逻辑像素，本值多为 1.0；CTk 自行处理物理缩放。"""
        try:
            return max(1.0, self.root.winfo_fpixels('1i') / 96.0)
        except Exception:
            return 1.0

    def _sane_window_geometry(self, w, h, x, y) -> Tuple[int, int, int, int]:
        """把保存的窗口几何钳制到可见且合理的范围。

        全部计算都在 Tk 自身坐标系（winfo_screenwidth/height）内完成——
        有 CustomTkinter 时该坐标系是"逻辑像素"（如 4K@175% 下为 2194×1234），
        CTk 再按 1.75 渲染成物理像素。**切勿**在这里掺入 ctypes 的物理
        分辨率：逻辑/物理混用正是窗口跑出屏幕的根因（saved x 在物理系
        里合法、在逻辑系里却越界）。
        尺寸上限取屏幕 88%/86%，想占满请用系统最大化。
        位置：窗口需完整落在屏内，否则（含拔副屏后的失效坐标）居中偏上。
        """
        try:
            sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        except tk.TclError:
            return 1000, 700, 80, 60
        min_w, min_h = 1000, 680
        max_w, max_h = int(sw * 0.90), int(sh * 0.88)
        default_w, default_h = min(1280, max_w), min(820, max_h)
        # 保存值须在 [min, 屏宽] 内才采用，否则回落到默认
        w = int(w) if (w and min_w <= int(w) <= sw) else default_w
        h = int(h) if (h and min_h <= int(h) <= sh) else default_h
        w = max(min_w, min(w, max_w))
        h = max(min_h, min(h, max_h))
        # 位置：任一方向越界即视为失效坐标，居中偏上重置
        try:
            x, y = int(x), int(y)
        except (TypeError, ValueError):
            x = y = -99999
        if x < 0 or y < 0 or x + w > sw or y + h > sh:
            x = max(0, (sw - w) // 2)
            y = max(0, (sh - h) // 3)
        return w, h, x, y

    def _setup_styles(self):
        """建立全局视觉样式。取值一律来自模块级设计令牌 C / UI_FONT。

        界面由两套渲染体系拼成，本方法负责让它们看起来是同一个产品：
        - CustomTkinter 承担按钮/输入/勾选等交互控件 —— 改 ThemeManager
          全局默认色，各处就不必再重复写 fg_color，也杜绝了配色漂移。
        - ttk 只保留没有 CTk 对应实现的控件（Treeview / Notebook /
          Scrollbar / Combobox / Spinbox / PanedWindow）。Windows 默认的
          'vista' 主题会**忽略**大部分 configure 选项（背景、边框都改不动），
          因此必须先切到 'clam' 才能把它们拉到与 CTk 一致的观感。
        """
        self.colors = C  # 兼容旧引用；新代码直接用模块级 C

        # ---- CustomTkinter 全局主题 ----
        if HAS_CTK:
            self._setup_ctk_theme()

        # ---- ttk 主题 ----
        style = ttk.Style()
        try:
            style.theme_use('clam')  # 唯一能完整响应 configure 的内置主题
        except tk.TclError:
            pass  # 极少数环境无 clam，退回默认主题（观感降级但不影响功能）

        # 全局默认字体：覆盖 tk.Menu、messagebox 等无法逐个配置的控件
        self.root.option_add('*Font', UI_FONT())
        self.root.option_add('*TCombobox*Listbox.font', UI_FONT())
        self.root.option_add('*TCombobox*Listbox.background', C['card'])
        self.root.option_add('*TCombobox*Listbox.foreground', C['text'])
        self.root.option_add('*TCombobox*Listbox.selectBackground', C['brand_soft'])
        self.root.option_add('*TCombobox*Listbox.selectForeground', C['brand'])
        self.root.option_add('*Menu.background', C['card'])
        self.root.option_add('*Menu.foreground', C['text'])
        self.root.option_add('*Menu.activeBackground', C['brand_soft'])
        self.root.option_add('*Menu.activeForeground', C['brand'])
        self.root.option_add('*Menu.relief', 'flat')

        # ---- 容器与文字 ----
        style.configure("TFrame", background=C['bg'])
        style.configure("Card.TFrame", background=C['card'])
        style.configure("TLabel", background=C['bg'], foreground=C['text'], font=UI_FONT())
        style.configure("TPanedwindow", background=C['bg'])
        style.configure("TSeparator", background=C['border'])

        # ---- 表格 ----
        # 行高与字号绑定：ROW_H 随 FS_SMALL 同步调整
        style.configure("Treeview",
            background=C['card'],
            foreground=C['text'],
            fieldbackground=C['card'],
            rowheight=ROW_H,
            borderwidth=0,
            font=UI_FONT(FS_SMALL),
        )
        style.configure("Treeview.Heading",
            background=C['card_alt'],
            foreground=C['text_sub'],
            font=UI_FONT(FS_SMALL, bold=True),
            padding=(12, 12),
            relief="flat",
            borderwidth=0,
        )
        style.map("Treeview.Heading",
            background=[('active', C['brand_soft'])],
            foreground=[('active', C['brand'])],
        )
        # 选中态用品牌浅底 + 品牌字，不再用蓝色系（与主色冲突）
        style.map("Treeview",
            background=[('selected', C['brand_soft'])],
            foreground=[('selected', C['brand'])],
        )
        style.layout("Treeview", [('Treeview.treearea', {'sticky': 'nswe'})])  # 去掉外框

        # ---- 标签页 ----
        style.configure("TNotebook", background=C['bg'], borderwidth=0, tabmargins=(4, 4, 4, 0))
        style.configure("TNotebook.Tab",
            padding=(32, 16),
            font=UI_FONT(),
            background=C['bg'],
            foreground=C['text_sub'],
            borderwidth=0,
        )
        # 选中态：白底 + 品牌红加粗，与下方内容区连成一片
        style.map("TNotebook.Tab",
            background=[('selected', C['card']), ('active', C['hover'])],
            foreground=[('selected', C['brand']), ('active', C['text'])],
            font=[('selected', UI_FONT(bold=True))],
            expand=[('selected', (0, 0, 0, 0))],
        )

        # ---- 输入类 ----
        for name in ("TEntry", "TCombobox", "TSpinbox"):
            style.configure(name,
                font=UI_FONT(),
                fieldbackground=C['card'],
                background=C['card'],
                foreground=C['text'],
                bordercolor=C['border_strong'],
                lightcolor=C['border_strong'],
                darkcolor=C['border_strong'],
                arrowcolor=C['text_sub'],
                insertcolor=C['text'],
                borderwidth=1,
                padding=(10, 8),
            )
            style.map(name,
                bordercolor=[('focus', C['brand']), ('hover', C['border_strong'])],
                lightcolor=[('focus', C['brand'])],
                darkcolor=[('focus', C['brand'])],
                fieldbackground=[('disabled', C['card_alt']), ('readonly', C['card'])],
                foreground=[('disabled', C['text_faint'])],
                arrowcolor=[('disabled', C['text_faint'])],
            )

        # ---- 滚动条：略加宽便于点击，仍保持浅灰不抢视线 ----
        for orient in ("Vertical.TScrollbar", "Horizontal.TScrollbar"):
            style.configure(orient,
                background=C['border_strong'],
                troughcolor=C['bg'],
                bordercolor=C['bg'],
                arrowcolor=C['text_sub'],
                borderwidth=0,
                width=14,
            )
            style.map(orient, background=[('active', C['text_faint'])])

        # ---- 进度条 ----
        style.configure("TProgressbar",
            background=C['brand'],
            troughcolor=C['border'],
            bordercolor=C['border'],
            lightcolor=C['brand'],
            darkcolor=C['brand'],
            borderwidth=0,
            thickness=12,
        )

        # ---- ttk 按钮（仅弹窗等少数 CTk 未覆盖处使用）----
        style.configure("TButton",
            font=UI_FONT(),
            background=C['card'],
            foreground=C['text'],
            bordercolor=C['border_strong'],
            lightcolor=C['card'],
            darkcolor=C['card'],
            borderwidth=1,
            focusthickness=0,
            padding=(14, 9),
        )
        style.map("TButton",
            background=[('pressed', C['brand_soft']), ('active', C['card_alt'])],
            foreground=[('pressed', C['brand']), ('active', C['brand'])],
            bordercolor=[('active', C['brand'])],
        )

    def _setup_ctk_theme(self):
        """把 CustomTkinter 的全局默认色改成品牌配色。

        改 ThemeManager 而不是逐控件传 fg_color：控件数以百计，逐个传
        必然漂移。CTk 主题里每个颜色是 [浅色模式, 深色模式] 两元素列表，
        本程序固定浅色模式，两个位置填同值即可。
        """
        try:
            theme = ctk.ThemeManager.theme
        except Exception:
            return  # CTk 内部结构变化时静默降级，不阻断启动

        def dual(color):
            return [color, color]

        # 默认字体：不传 font 参数的 CTk 控件直接继承，省掉全文重复
        theme.setdefault("CTkFont", {})
        for platform in ("Windows", "macOS", "Linux"):
            theme["CTkFont"][platform] = {
                "family": FONT_FAMILY, "size": FS_BASE, "weight": "normal"}

        merges = {
            "CTk": {"fg_color": dual(C['bg'])},
            "CTkToplevel": {"fg_color": dual(C['bg'])},
            "CTkFrame": {
                "fg_color": dual(C['card']),
                "top_fg_color": dual(C['card']),
                "border_color": dual(C['border']),
                "corner_radius": CARD_RADIUS,
                "border_width": 0,
            },
            "CTkButton": {
                "fg_color": dual(C['brand']),
                "hover_color": dual(C['brand_hover']),
                "border_color": dual(C['border_strong']),
                "text_color": dual(C['text_on_brand']),
                "text_color_disabled": dual(C['text_faint']),
                "corner_radius": CTRL_RADIUS,
                "height": CTRL_H,
            },
            "CTkLabel": {
                "fg_color": "transparent",
                "text_color": dual(C['text']),
            },
            "CTkEntry": {
                "fg_color": dual(C['card']),
                "border_color": dual(C['border_strong']),
                "text_color": dual(C['text']),
                "placeholder_text_color": dual(C['text_faint']),
                "corner_radius": CTRL_RADIUS,
                "border_width": 1,
                "height": CTRL_H,
            },
            "CTkCheckBox": {
                "fg_color": dual(C['brand']),
                "hover_color": dual(C['brand_hover']),
                "border_color": dual(C['border_strong']),
                "checkmark_color": dual(C['text_on_brand']),
                "text_color": dual(C['text']),
                "text_color_disabled": dual(C['text_faint']),
                "corner_radius": 5,
                "border_width": 2,
            },
            "CTkRadioButton": {
                "fg_color": dual(C['brand']),
                "hover_color": dual(C['brand_hover']),
                "border_color": dual(C['border_strong']),
                "text_color": dual(C['text']),
                "text_color_disabled": dual(C['text_faint']),
            },
            "CTkProgressBar": {
                "fg_color": dual(C['border']),
                "progress_color": dual(C['brand']),
                "border_color": dual(C['border']),
                "height": 12,
            },
            "CTkTextbox": {
                "fg_color": dual(C['card']),
                "border_color": dual(C['border']),
                "text_color": dual(C['text']),
                "scrollbar_button_color": dual(C['border_strong']),
                "scrollbar_button_hover_color": dual(C['text_faint']),
                "corner_radius": CTRL_RADIUS,
            },
            "CTkComboBox": {
                "fg_color": dual(C['card']),
                "border_color": dual(C['border_strong']),
                # 箭头区用极淡灰，不能与输入区同色：CTkComboBox 的按钮区是
                # **无边框实心块**，涂成白色会让描边在文字区就收口，箭头看着
                # 像飘在控件外面。也不宜用深灰（默认值），那样色块比箭头还抢眼。
                "button_color": dual(C['bg']),
                "button_hover_color": dual(C['brand_soft']),
                "text_color": dual(C['text']),
                "text_color_disabled": dual(C['text_faint']),
                "corner_radius": CTRL_RADIUS,
                "border_width": 1,
                "height": CTRL_H,
                "dropdown_fg_color": dual(C['card']),
                "dropdown_hover_color": dual(C['brand_soft']),
                "dropdown_text_color": dual(C['text']),
            },
            "CTkOptionMenu": {
                "fg_color": dual(C['card']),
                "button_color": dual(C['card_alt']),
                "button_hover_color": dual(C['brand_soft']),
                "text_color": dual(C['text']),
                "text_color_disabled": dual(C['text_faint']),
                "corner_radius": CTRL_RADIUS,
                "dropdown_fg_color": dual(C['card']),
                "dropdown_hover_color": dual(C['brand_soft']),
                "dropdown_text_color": dual(C['text']),
            },
            "CTkScrollbar": {
                "fg_color": "transparent",
                "button_color": dual(C['border_strong']),
                "button_hover_color": dual(C['text_faint']),
            },
            "CTkSegmentedButton": {
                "fg_color": dual(C['bg']),
                "selected_color": dual(C['brand']),
                "selected_hover_color": dual(C['brand_hover']),
                "unselected_color": dual(C['card']),
                "unselected_hover_color": dual(C['brand_soft']),
                "text_color": dual(C['text_on_brand']),
                "text_color_disabled": dual(C['text_faint']),
                "corner_radius": CTRL_RADIUS,
                "border_width": 1,
                "border_color": dual(C['border']),
            },
        }
        for widget, options in merges.items():
            if widget in theme:
                theme[widget].update(options)
            else:
                theme[widget] = options

    # ---- 界面构件工厂 ----
    # 卡片是全界面唯一的分组容器，取代观感陈旧、边框几乎不可见的
    # ttk.LabelFrame。统一在这里造，各页面才不会各写一套分组样式。
    def _card(self, parent, title=None, expand=False, pady=(0, SP_MD)):
        """创建带标题的卡片，返回可直接放内容的内层容器。"""
        shell = ctk.CTkFrame(parent, fg_color=C['card'], corner_radius=CARD_RADIUS,
                             border_width=1, border_color=C['border'])
        shell.pack(fill=tk.BOTH if expand else tk.X, expand=expand, pady=pady)

        if title:
            head = ctk.CTkLabel(shell, text=title, font=UI_FONT(FS_TITLE, bold=True),
                                text_color=C['text'], anchor="w")
            head.pack(fill=tk.X, padx=SP_MD + 4, pady=(SP_MD + 2, SP_SM))

        body = ctk.CTkFrame(shell, fg_color="transparent")
        body.pack(fill=tk.BOTH, expand=True,
                  padx=SP_MD + 4, pady=(0, SP_MD + 2) if title else SP_MD + 2)
        return body

    def _row(self, parent, pady=0):
        """卡片内的一行。transparent 让它自动继承父容器底色。"""
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill=tk.X, pady=pady)
        return row

    def _label(self, parent, text, color=None, bold=False, size=FS_BASE,
               width=None, **pack_kw):
        """行内文字标签。默认次要灰——界面里大部分标签都是字段名。
        传入 width=LABEL_W 可让表单字段纵向对齐。"""
        kw = dict(text=text, font=UI_FONT(size, bold=bold),
                  text_color=color or C['text_sub'], anchor="w")
        if width is not None:
            kw["width"] = width
        lbl = ctk.CTkLabel(parent, **kw)
        lbl.pack(**{'side': tk.LEFT, **pack_kw})
        return lbl

    def _btn(self, parent, text, command, kind="secondary", width=120, **pack_kw):
        """统一按钮。kind: primary(品牌红) / danger(红) / secondary(白底描边)。"""
        styles = {
            "primary": dict(fg_color=C['brand'], hover_color=C['brand_hover'],
                            text_color=C['text_on_brand'], border_width=0),
            "danger": dict(fg_color=C['danger'], hover_color=C['danger_hover'],
                           text_color=C['text_on_brand'], border_width=0),
            "secondary": dict(fg_color=C['card'], hover_color=C['brand_soft'],
                              text_color=C['text'], border_width=1,
                              border_color=C['border_strong']),
        }
        h = BTN_H if kind == "primary" else CTRL_H
        btn = ctk.CTkButton(parent, text=text, command=command, width=width, height=h,
                            corner_radius=CTRL_RADIUS, font=UI_FONT(), **styles[kind])
        btn.pack(**{'side': tk.LEFT, **pack_kw})
        return btn

    def _paint_seg(self, seg, selected: str):
        """分段按钮：选中=品牌红底白字，未选中=白底灰字（CTk 默认字色不随选中切换）。"""
        buttons = getattr(seg, "_buttons_dict", None) or {}
        for value, btn in buttons.items():
            if value == selected:
                btn.configure(fg_color=C['brand'], hover_color=C['brand_hover'],
                              text_color=C['text_on_brand'])
            else:
                btn.configure(fg_color=C['card'], hover_color=C['brand_soft'],
                              text_color=C['text_sub'])

    def _seg(self, parent, variable, values, command=None, width=None, **pack_kw):
        """分段选择器（品牌红选中态），用于模式/数据源等互斥选项。"""
        values = list(values)

        def on_change(val):
            self._paint_seg(seg, val)
            if command is not None:
                command(val)

        seg = ctk.CTkSegmentedButton(
            parent, values=values, variable=variable, command=on_change,
            font=UI_FONT(), height=CTRL_H,
            selected_color=C['brand'], selected_hover_color=C['brand_hover'],
            unselected_color=C['card'], unselected_hover_color=C['brand_soft'],
            text_color=C['text_sub'],
            fg_color=C['border'], corner_radius=CTRL_RADIUS,
            border_width=0,
        )
        if width is not None:
            seg.configure(width=width)
        try:
            cur = variable.get()
            if cur in values:
                seg.set(cur)
            elif values:
                seg.set(values[0])
                variable.set(values[0])
        except Exception:
            pass
        self._paint_seg(seg, variable.get())

        # 程序化 variable.set() 不触发 command，CTk 只重涂底色不重涂
        # 文字色——旧选中段滞留白字，unselect 后成"白底白字"隐形段
        # （实测：切数据源后"当前爬取"整段消失）。挂 trace 兜底，
        # 使 set() / _restore_gui_settings 等所有赋值路径都自动补涂。
        def _repaint(*_args):
            try:
                self._paint_seg(seg, variable.get())
            except Exception:
                pass  # 控件已销毁（关窗时 trace 仍可能触发）
        variable.trace_add('write', _repaint)
        seg.pack(**{'side': tk.LEFT, **pack_kw})
        return seg

    def _combo(self, parent, variable, values, width=150, command=None, **pack_kw):
        """只读下拉框。

        注意回调约定与 ttk 不同：CTk 的 command 直接收到选中值字符串，
        而非 <<ComboboxSelected>> 事件对象。调用方若沿用旧的 handler(event)
        签名，需接受一个位置参数并忽略它。
        """
        box = ctk.CTkComboBox(parent, variable=variable, values=[str(v) for v in values],
                              width=width, height=CTRL_H, font=UI_FONT(),
                              dropdown_font=UI_FONT(), state="readonly", command=command)
        box.pack(**{'side': tk.LEFT, **pack_kw})
        return box

    def _num_entry(self, parent, variable, width=88, **pack_kw):
        """数字输入框。取代 ttk.Spinbox——步进箭头在本界面几乎无人点，
        却带来一个无法圆角化、高度也对不齐的方框控件。"""
        entry = ctk.CTkEntry(parent, textvariable=variable, width=width, height=CTRL_H,
                             font=UI_FONT(), justify="center")
        entry.pack(**{'side': tk.LEFT, **pack_kw})
        return entry

    def _metric(self, parent, caption, textvariable, color=None):
        """状态指标：小字说明在上、大字数值在下，靠字号差建立层次。"""
        cell = ctk.CTkFrame(parent, fg_color="transparent")
        cell.pack(side=tk.LEFT, padx=(0, 32))
        ctk.CTkLabel(cell, text=caption, font=UI_FONT(FS_SMALL),
                     text_color=C['text_sub'], anchor="w").pack(anchor="w")
        ctk.CTkLabel(cell, textvariable=textvariable, font=UI_FONT(FS_TITLE + 4, bold=True),
                     text_color=color or C['text'], anchor="w").pack(anchor="w")
        return cell

    def _create_ui(self):
        """创建界面骨架：标签页容器 + 五个功能页。

        每页外层是灰底（C['bg']），页内的白色卡片才浮得起来；内边距在
        这里统一给出，各页构建函数收到的 parent 已经留好边距。
        """
        main_container = ctk.CTkFrame(self.root, fg_color="transparent")
        main_container.pack(fill=tk.BOTH, expand=True, padx=SP_LG, pady=SP_MD)

        notebook = ttk.Notebook(main_container)
        notebook.pack(fill=tk.BOTH, expand=True)
        self.notebook = notebook

        pages = (
            ("搜索爬取", self._create_main_page),
            ("爬取结果", self._create_result_page),
            ("内容选项", self._create_content_page),
            ("数据分析", self._create_analysis_page),
            ("高级设置", self._create_settings_page),
        )
        for title, build in pages:
            page = ctk.CTkFrame(notebook, fg_color=C['bg'], corner_radius=0)
            notebook.add(page, text=title)
            inner = ctk.CTkFrame(page, fg_color="transparent")
            inner.pack(fill=tk.BOTH, expand=True, padx=SP_LG, pady=SP_LG)
            build(inner)

    def _create_main_page(self, parent):
        """创建主页面：紧凑单屏布局，无需拖分隔条即可看到配置+状态+日志。

        - 上区：采集/筛选/按钮/状态（尽量压扁、按模式隐藏无关行）
        - 下区：运行日志自动占满剩余高度
        """
        parent.grid_rowconfigure(1, weight=1, minsize=LOG_MIN_H)
        parent.grid_columnconfigure(0, weight=1)
        self._main_paned = None  # 不再用可拖分割条

        top = ctk.CTkFrame(parent, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew")

        # ================= 采集目标（紧凑：模式相关行按需显示）=================
        target = self._card(top, "采集目标", pady=(0, SP_SM))

        self._CRAWL_TYPE_LABELS = ("关键词搜索", "博主主页", "热门榜单")
        self._CRAWL_TYPE_TO_LABEL = {
            "keyword": "关键词搜索", "blogger": "博主主页", "hot": "热门榜单"}
        self._CRAWL_LABEL_TO_TYPE = {v: k for k, v in self._CRAWL_TYPE_TO_LABEL.items()}
        self.crawl_type_var = tk.StringVar(value="keyword")
        self.crawl_type_label_var = tk.StringVar(
            value=self._CRAWL_TYPE_TO_LABEL[self.crawl_type_var.get()])

        mode_row = self._row(target, pady=(0, SP_XS))
        self._label(mode_row, "采集模式", width=LABEL_W, padx=(0, SP_SM))
        self.crawl_type_seg = self._seg(
            mode_row, self.crawl_type_label_var, self._CRAWL_TYPE_LABELS,
            command=self._on_mode_seg_change, width=380)

        # 关键词行
        self._kw_row = self._row(target, pady=(0, SP_XS))
        self._label(self._kw_row, "搜索关键词", width=LABEL_W, padx=(0, SP_SM))
        self.keyword_var = tk.StringVar(value="鞋子")
        self.keyword_entry = ctk.CTkEntry(
            self._kw_row, textvariable=self.keyword_var, width=360,
            height=CTRL_H, font=UI_FONT(), placeholder_text="留空则采集主页推荐")
        self.keyword_entry.pack(side=tk.LEFT, padx=(0, SP_SM))
        self._label(self._kw_row, "多个用逗号分隔", color=C['text_faint'], size=FS_SMALL)

        # 博主行（默认隐藏）
        self._blogger_row = self._row(target, pady=(0, SP_XS))
        self._label(self._blogger_row, "博主主页URL", width=LABEL_W, padx=(0, SP_SM))
        self.blogger_url_var = tk.StringVar()
        self.blogger_entry = ctk.CTkEntry(
            self._blogger_row, textvariable=self.blogger_url_var, width=480,
            height=CTRL_H, font=UI_FONT(),
            placeholder_text="https://www.xiaohongshu.com/user/profile/...")
        self.blogger_entry.pack(side=tk.LEFT)

        # 热门分类行（默认隐藏）
        self._hot_row = self._row(target, pady=(0, SP_XS))
        self._label(self._hot_row, "热门分类", width=LABEL_W, padx=(0, SP_SM))
        self.hot_category_var = tk.StringVar(value="综合")
        self.hot_combo = self._combo(
            self._hot_row, self.hot_category_var,
            ["综合", "美食", "穿搭", "美妆", "旅行", "家居", "数码"], width=150)

        # 数量 + 速度同一行，省垂直空间（始终在模式相关输入之下）
        self._count_row = self._row(target, pady=(0, 0))
        self.scroll_var = tk.StringVar(value="10")
        self._label(self._count_row, "最多笔记", width=LABEL_W, padx=(0, SP_SM))
        self.max_notes_var = tk.StringVar(value="30")
        self._num_entry(self._count_row, self.max_notes_var, width=80, padx=(0, SP_MD))
        self._label(self._count_row, "并行", padx=(0, SP_XS))
        self.parallel_var = tk.StringVar(value="10")
        self._num_entry(self._count_row, self.parallel_var, width=80, padx=(0, SP_LG))

        self.crawl_mode_var = tk.StringVar(value="standard")
        self._CRAWL_MODE_LABELS = ("标准模式（完整数据）", "极速模式（仅列表）")
        self._CRAWL_MODE_TO_LABEL = {
            "standard": "标准模式（完整数据）", "turbo": "极速模式（仅列表）"}
        self._CRAWL_LABEL_TO_MODE = {v: k for k, v in self._CRAWL_MODE_TO_LABEL.items()}
        self.crawl_mode_label_var = tk.StringVar(
            value=self._CRAWL_MODE_TO_LABEL[self.crawl_mode_var.get()])
        self._label(self._count_row, "速度", padx=(0, SP_SM))
        self.crawl_mode_seg = self._seg(
            self._count_row, self.crawl_mode_label_var, self._CRAWL_MODE_LABELS,
            command=self._on_speed_seg_change, width=340)

        # ================= 筛选 + 操作同一卡片 =================
        refine = self._card(top, "筛选与操作", pady=(0, SP_SM))

        filter_row = self._row(refine, pady=(0, SP_XS))
        self._label(filter_row, "点赞", width=LABEL_W, padx=(0, SP_SM))
        self.min_likes_var = tk.StringVar(value="0")
        ctk.CTkEntry(filter_row, textvariable=self.min_likes_var, width=90, height=CTRL_H,
                     font=UI_FONT()).pack(side=tk.LEFT, padx=(0, SP_XS))
        self._label(filter_row, "~", padx=(0, SP_XS))
        self.max_likes_var = tk.StringVar(value="999999")
        ctk.CTkEntry(filter_row, textvariable=self.max_likes_var, width=100, height=CTRL_H,
                     font=UI_FONT()).pack(side=tk.LEFT, padx=(0, SP_MD))

        self._label(filter_row, "类型", padx=(0, SP_XS))
        self.note_type_var = tk.StringVar(value="全部")
        self._combo(filter_row, self.note_type_var, ["全部", "图文", "视频"],
                    width=100, padx=(0, SP_MD))

        self._label(filter_row, "时间", padx=(0, SP_XS))
        self.date_filter_var = tk.StringVar(value="全部")
        self._combo(filter_row, self.date_filter_var, ["全部", "今天", "本周", "本月"],
                    width=100, padx=(0, SP_MD))

        # 跨运行去重开关：默认关。开着时重复采集同一主题，库里已有的
        # 笔记直接跳过，不再重复打开详情页/下载媒体
        self.skip_existing_var = tk.BooleanVar(value=False)
        self._check(filter_row, "跳过已爬取", self.skip_existing_var)

        # 快捷预设：一键改写内容选项+速度，是最常用的配置入口，
        # 必须在主页可达（原先只在"内容选项"页，首次配置要跨页找）
        preset_row = self._row(refine, pady=(SP_XS, 0))
        self._label(preset_row, "快捷预设", width=LABEL_W, padx=(0, SP_SM))
        for text, cmd in (("极速采集", self._preset_turbo), ("完整数据", self._preset_complete),
                          ("只下图片", self._preset_images), ("只下视频", self._preset_videos),
                          ("只要文本", self._preset_text)):
            self._btn(preset_row, text, cmd, width=96, padx=(0, SP_XS))

        btn_frame = self._row(refine, pady=(SP_XS, 0))
        self.start_btn = ctk.CTkButton(
            btn_frame, text="开始爬取", command=self._start_crawl,
            width=140, height=BTN_H, corner_radius=CTRL_RADIUS,
            font=UI_FONT(bold=True))
        self.start_btn.pack(side=tk.LEFT, padx=(0, SP_SM))
        self.stop_btn = self._btn(btn_frame, "停止", self._stop_crawl, width=90,
                                  padx=(0, SP_SM))
        self.stop_btn.configure(state="disabled")
        self._btn(btn_frame, "Cookie详情", self._use_saved_cookies, width=110,
                  padx=(0, SP_SM))
        # 登录状态前置：原先藏在"高级设置"页，用户开爬前根本不知道
        # 会不会又要扫码。变量在这里创建，高级设置页复用同一实例。
        self.cookie_status_var = tk.StringVar(value="未检测到Cookie")
        ctk.CTkLabel(btn_frame, textvariable=self.cookie_status_var,
                     font=UI_FONT(FS_SMALL), text_color=C['text_sub']
                     ).pack(side=tk.LEFT, padx=(0, SP_SM))
        self._btn(btn_frame, "打开数据", self._open_data_dir, width=100, side=tk.RIGHT)
        self._btn(btn_frame, "打包图片", self._zip_images, width=100, side=tk.RIGHT,
                  padx=(0, SP_SM))

        # ================= 运行状态：进度+指标一行 =================
        status_card = self._card(top, "运行状态", pady=(0, SP_SM))
        prog_row = self._row(status_card, pady=(0, SP_XS))
        self.total_progress = ctk.CTkProgressBar(prog_row, height=10, corner_radius=0)
        self.total_progress.set(0)
        self.total_progress.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, SP_SM))
        self.progress_label = ctk.CTkLabel(
            prog_row, text="0%", font=UI_FONT(bold=True),
            text_color=C['brand'], width=48, anchor="e")
        self.progress_label.pack(side=tk.LEFT)

        stat_row = self._row(status_card)
        self.status_var = tk.StringVar(value="就绪")
        self.notes_var = tk.StringVar(value="0")
        self.images_var = tk.StringVar(value="0")
        self.videos_var = tk.StringVar(value="0")
        self.time_var = tk.StringVar(value="0秒")
        self._metric(stat_row, "状态", self.status_var, color=C['brand'])
        self._metric(stat_row, "笔记", self.notes_var)
        self._metric(stat_row, "图片", self.images_var)
        self._metric(stat_row, "视频", self.videos_var)
        self._metric(stat_row, "用时", self.time_var)

        # 按当前模式显示/隐藏输入行
        self._apply_mode_row_visibility()

        # ================= 运行日志（自动占满剩余空间，无需拖拽）=================
        log_shell = ctk.CTkFrame(
            parent, fg_color=C['card'], corner_radius=CARD_RADIUS,
            border_width=1, border_color=C['border'])
        log_shell.grid(row=1, column=0, sticky="nsew", pady=(0, 0))
        self._log_shell = log_shell

        log_head = ctk.CTkFrame(log_shell, fg_color="transparent")
        log_head.pack(fill=tk.X, padx=SP_MD, pady=(SP_SM, SP_XS))
        ctk.CTkLabel(
            log_head, text="运行日志", font=UI_FONT(FS_TITLE, bold=True),
            text_color=C['text'], anchor="w"
        ).pack(side=tk.LEFT)
        ctk.CTkLabel(
            log_head, text="实时输出",
            font=UI_FONT(FS_SMALL - 1), text_color=C['text_faint']
        ).pack(side=tk.LEFT, padx=(SP_SM, 0))

        self.log_text = ctk.CTkTextbox(
            log_shell, height=LOG_MIN_H, corner_radius=CTRL_RADIUS,
            font=(FONT_MONO, FS_MONO), fg_color=C['card_alt'],
            text_color=C['text'], border_width=0, wrap="word")
        self.log_text.pack(fill=tk.BOTH, expand=True, padx=SP_MD, pady=(0, SP_SM))

        self._ctk_log_tags = False
        self._log_inner = None
        try:
            tb = getattr(self.log_text, "_textbox", None)
            self._log_inner = tb
            target = tb or self.log_text
            for name, color in (
                ("INFO", C['text']), ("SUCCESS", C['success']),
                ("WARNING", C['warning']), ("ERROR", C['danger']),
                ("DEBUG", C['text_sub']),
            ):
                target.tag_config(name, foreground=color)
            self._ctk_log_tags = True
        except Exception:
            self._ctk_log_tags = False
        try:
            self.log_text.configure(state="disabled")
        except Exception:
            pass

    def _create_result_page(self, parent):
        """创建爬取结果展示页面。

        布局层次：
        1. 工具栏卡片（数据源分段 + 批次 + 检索）
        2. 统计药丸条
        3. 左表格 / 右详情+媒体 分栏
        详情区全部收进白卡片，避免标题/指标/正文各自悬浮。
        """
        toolbar = self._card(parent, pady=(0, SP_SM))

        # ---- 上行：数据源分段 + 批次 + 主操作 ----
        # 数据源是**唯一**的视图入口：当前爬取（内存）/ 历史数据库（SQLite）/
        # 本地批次（images/ 文件夹）。批次下拉只在"本地批次"下可用——
        # 此前它与数据源两轴互不协调，组合出 4 种隐式状态，切换后经常
        # 分不清表格里到底是什么。
        top = self._row(toolbar, pady=(0, SP_MD))
        self._label(top, "数据源", width=LABEL_W, padx=(0, SP_SM))
        self.data_source_var = tk.StringVar(value="当前爬取")
        # 分段控件 command 收到选中值字符串（与旧 combo 约定一致）
        self.data_source_seg = self._seg(
            top, self.data_source_var, ["当前爬取", "历史数据库", "本地批次"],
            command=self._on_data_source_change, width=420, padx=(0, SP_LG))
        # 兼容旧代码里对 data_source_combo 的引用（若有）
        self.data_source_combo = self.data_source_seg

        self._label(top, "批次", padx=(0, SP_SM))
        self.crawl_batch_var = tk.StringVar(value="全部")
        self.crawl_batch_combo = self._combo(top, self.crawl_batch_var, ["全部"], width=250,
                                             command=self._on_batch_select, padx=(0, SP_SM))
        self._batch_refresh_btn = self._btn(top, "刷新批次", self._refresh_crawl_batches,
                                            width=100, padx=(0, SP_XS))
        self._batch_open_btn = self._btn(top, "打开目录", self._open_batch_folder,
                                         width=100, padx=(0, SP_XS))
        self._batch_del_btn = self._btn(top, "删除批次", self._delete_batch_folder, width=100)
        self._batch_del_btn.configure(text_color=C['danger'])

        # 主操作靠右：导出用 primary，其余 secondary
        self._btn(top, "导出Excel", self._export_results, kind="primary",
                  width=120, side=tk.RIGHT)
        self._btn(top, "复制全部", self._copy_all_data, width=110, side=tk.RIGHT, padx=(0, SP_XS))
        self._btn(top, "刷新", self._refresh_results, width=90, side=tk.RIGHT, padx=(0, SP_XS))

        # ---- 下行：本批内的检索 ----
        bottom = self._row(toolbar)
        self._label(bottom, "搜索", width=LABEL_W, padx=(0, SP_SM))
        self.search_var = tk.StringVar()
        # 与历史查询共用同一输入：原先"搜索"（表内筛选）和"关键词"
        # （SQL 过滤）两个框语义重叠，都匹配标题/作者/正文/关键词，
        # 用户根本分不清该填哪个
        self.filter_keyword_var = self.search_var
        self.search_entry = ctk.CTkEntry(bottom, textvariable=self.search_var, width=300,
                                         height=CTRL_H, font=UI_FONT(),
                                         placeholder_text="标题 / 作者 / 正文 / 关键词")
        self.search_entry.pack(side=tk.LEFT, padx=(0, SP_SM))
        self.search_entry.bind("<Return>", lambda e: self._filter_results())
        self._btn(bottom, "筛选", self._filter_results, width=90, padx=(0, SP_XS))
        self._btn(bottom, "重置", self._reset_filter, width=90, padx=(0, SP_LG))

        self._label(bottom, "类型", padx=(0, SP_SM))
        self.type_filter_var = tk.StringVar(value="全部")
        self._combo(bottom, self.type_filter_var, ["全部", "图文", "视频"], width=120,
                    command=lambda _v: self._filter_results(), padx=(0, SP_LG))

        clear_btn = self._btn(bottom, "清空当前", self._clear_results, width=120, side=tk.RIGHT)
        clear_btn.configure(text_color=C['danger'])
        del_btn = self._btn(bottom, "删除选中", self._delete_selected, width=120,
                            side=tk.RIGHT, padx=(0, SP_XS))
        del_btn.configure(text_color=C['danger'])

        self._refresh_crawl_batches()
        self._update_batch_controls_state()

        # === 统计条（卡片底 + 药丸）===
        stats_card = ctk.CTkFrame(parent, fg_color=C['card'], corner_radius=CARD_RADIUS,
                                  border_width=1, border_color=C['border'])
        stats_card.pack(fill=tk.X, pady=(0, SP_SM))
        stats_frame = ctk.CTkFrame(stats_card, fg_color="transparent")
        stats_frame.pack(fill=tk.X, padx=SP_MD, pady=SP_SM)

        def chip(text, fg, bg, bordered=False):
            if bordered:
                shell = ctk.CTkFrame(stats_frame, fg_color=bg, corner_radius=CHIP_H // 2,
                                     border_width=1, border_color=C['border'], height=CHIP_H)
                shell.pack(side=tk.LEFT, padx=(0, SP_SM))
                lbl = ctk.CTkLabel(shell, text=text, font=UI_FONT(FS_BASE, bold=True),
                                   text_color=fg, fg_color="transparent",
                                   height=CHIP_H - 2, padx=18)
                lbl.pack(padx=1, pady=1)
                return lbl
            lbl = ctk.CTkLabel(stats_frame, text=text, font=UI_FONT(FS_BASE, bold=True),
                               text_color=fg, fg_color=bg, corner_radius=CHIP_H // 2,
                               height=CHIP_H, padx=18)
            lbl.pack(side=tk.LEFT, padx=(0, SP_SM))
            return lbl

        self.result_count_label = chip("总计: 0 条", C['brand'], C['brand_soft'])
        self.stats_image_label = chip("图文: 0", C['text_sub'], C['card_alt'], bordered=True)
        self.stats_video_label = chip("视频: 0", C['text_sub'], C['card_alt'], bordered=True)
        self.stats_likes_label = chip("总点赞: 0", C['text_sub'], C['card_alt'], bordered=True)

        # === 主区域：左边表格，右边详情 ===
        main_paned = ttk.PanedWindow(parent, orient=tk.HORIZONTAL)
        main_paned.pack(fill=tk.BOTH, expand=True)

        left_frame = ctk.CTkFrame(main_paned, fg_color=C['card'], corner_radius=CARD_RADIUS,
                                  border_width=1, border_color=C['border'])
        main_paned.add(left_frame, weight=3)

        columns = ("序号", "类型", "标题", "作者", "点赞", "收藏", "评论")
        self.result_tree = ttk.Treeview(left_frame, columns=columns, show="headings", height=22)

        # 行样式：斑马纹 + 克制的类型区分（tag 只能整行上色，勿再染整行高饱和色）
        self.result_tree.tag_configure('oddrow', background=C['card_alt'])
        self.result_tree.tag_configure('evenrow', background=C['card'])
        self.result_tree.tag_configure('video', foreground=C['row_video'])
        self.result_tree.tag_configure('image', foreground=C['text'])

        for col in columns:
            self.result_tree.heading(col, text=col, command=lambda c=col: self._sort_by_column(c))

        self.result_tree.column("序号", width=72, minwidth=56, anchor="center", stretch=False)
        self.result_tree.column("类型", width=80, minwidth=64, anchor="center", stretch=False)
        self.result_tree.column("标题", width=400, minwidth=220, anchor="w", stretch=True)
        self.result_tree.column("作者", width=140, minwidth=100, anchor="w", stretch=False)
        self.result_tree.column("点赞", width=96, minwidth=80, anchor="e", stretch=False)
        self.result_tree.column("收藏", width=96, minwidth=80, anchor="e", stretch=False)
        self.result_tree.column("评论", width=96, minwidth=80, anchor="e", stretch=False)

        scrollbar_y = ttk.Scrollbar(left_frame, orient=tk.VERTICAL, command=self.result_tree.yview)
        self.result_tree.configure(yscrollcommand=scrollbar_y.set)

        self.result_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(SP_SM, 0), pady=SP_SM)
        scrollbar_y.pack(side=tk.RIGHT, fill=tk.Y, pady=SP_SM)

        self.tree_context_menu = tk.Menu(self.result_tree, tearoff=0)
        self.tree_context_menu.add_command(label="复制标题", command=self._copy_title)
        self.tree_context_menu.add_command(label="复制作者", command=self._copy_author)
        self.tree_context_menu.add_command(label="复制链接", command=self._copy_link)
        self.tree_context_menu.add_separator()
        self.tree_context_menu.add_command(label="打开原文", command=self._open_note_link)
        self.tree_context_menu.add_command(label="打开文件夹", command=self._open_images_folder)
        self.tree_context_menu.add_separator()
        self.tree_context_menu.add_command(label="删除此条", command=self._delete_single_note)
        self.result_tree.bind("<Button-3>", self._show_tree_context_menu)

        # 右侧：小红书式详情 —— 上媒体 / 下标题互动与正文评论
        right_frame = ctk.CTkFrame(main_paned, fg_color="transparent")
        main_paned.add(right_frame, weight=2)

        # ---- 媒体区（置顶，仿笔记大图）----
        preview_shell = ctk.CTkFrame(right_frame, fg_color=C['card'], corner_radius=CARD_RADIUS,
                                     border_width=1, border_color=C['border'])
        preview_shell.pack(fill=tk.BOTH, expand=True, padx=(SP_SM, 0), pady=(0, SP_SM))
        preview_frame = ctk.CTkFrame(preview_shell, fg_color="transparent")
        preview_frame.pack(fill=tk.BOTH, expand=True, padx=SP_SM, pady=SP_SM)

        preview_nav = ctk.CTkFrame(preview_frame, fg_color="transparent")
        preview_nav.pack(fill=tk.X, pady=(0, SP_XS))

        ctk.CTkLabel(preview_nav, text="笔记媒体", font=UI_FONT(FS_SMALL, bold=True),
                     text_color=C['text']).pack(side=tk.LEFT, padx=(0, SP_SM))
        self.preview_page_label = ctk.CTkLabel(preview_nav, text="", font=UI_FONT(FS_SMALL),
                                               text_color=C['text_sub'])
        self.preview_page_label.pack(side=tk.LEFT)

        for icon, cmd in (("▶", self._next_preview_page), ("◀", self._prev_preview_page)):
            ctk.CTkButton(preview_nav, text=icon, command=cmd, width=32, height=28,
                          corner_radius=CTRL_RADIUS, fg_color=C['card_alt'],
                          hover_color=C['brand_soft'], text_color=C['text_sub'],
                          border_width=1, border_color=C['border'],
                          font=UI_FONT(FS_SMALL)).pack(side=tk.RIGHT, padx=2)
        self._btn(preview_nav, "查看大图", self._view_current_media, width=88,
                  side=tk.RIGHT, padx=(0, SP_XS))

        # 评论图说明（有评论图时更新文案）
        self.preview_hint_label = ctk.CTkLabel(
            preview_frame,
            text="点击表格行打开详情卡片 · 评论图在卡片内原样展示",
            font=UI_FONT(FS_SMALL - 1), text_color=C['text_faint'], anchor="w")
        self.preview_hint_label.pack(fill=tk.X, pady=(0, SP_XS))

        self.preview_canvas = tk.Canvas(preview_frame, height=280, bg=C['canvas'],
                                        highlightthickness=0)
        self.preview_canvas.pack(fill=tk.BOTH, expand=True)

        # ---- 信息区：标题 / 互动 / 正文评论 ----
        detail_card = ctk.CTkFrame(right_frame, fg_color=C['card'], corner_radius=CARD_RADIUS,
                                   border_width=1, border_color=C['border'])
        detail_card.pack(fill=tk.BOTH, expand=True, padx=(SP_SM, 0))
        detail_inner = ctk.CTkFrame(detail_card, fg_color="transparent")
        detail_inner.pack(fill=tk.BOTH, expand=True, padx=SP_MD, pady=SP_SM)

        detail_header = ctk.CTkFrame(detail_inner, fg_color="transparent")
        detail_header.pack(fill=tk.X, pady=(0, SP_XS))

        self.detail_title_label = ctk.CTkLabel(detail_header, text="选择笔记查看详情",
                                               font=UI_FONT(FS_TITLE, bold=True),
                                               text_color=C['text'], anchor="w",
                                               wraplength=420, justify="left")
        self.detail_title_label.pack(side=tk.LEFT, fill=tk.X, expand=True)

        btn_frame = ctk.CTkFrame(detail_header, fg_color="transparent")
        btn_frame.pack(side=tk.RIGHT)
        self._btn(btn_frame, "详情卡片", self._open_current_note_card, width=88,
                  kind="primary", padx=(0, SP_XS))
        for icon, cmd, tip in (("📂", self._open_images_folder, "打开文件夹"),
                               ("▶", self._play_video, "播放视频"),
                               ("🔗", self._open_note_link, "打开原文"),
                               ("📋", self._copy_note_content, "复制正文")):
            ctk.CTkButton(btn_frame, text=icon, command=cmd, width=34, height=30,
                          corner_radius=CTRL_RADIUS, fg_color=C['card_alt'],
                          hover_color=C['brand_soft'], text_color=C['text_sub'],
                          border_width=1, border_color=C['border'],
                          font=UI_FONT(FS_SMALL)).pack(side=tk.LEFT, padx=2)

        # 作者 + 互动（仿小红书详情顶栏）
        info_cards = ctk.CTkFrame(detail_inner, fg_color="transparent")
        info_cards.pack(fill=tk.X, pady=(0, SP_XS))

        self.detail_author = ctk.CTkLabel(info_cards, text="", text_color=C['text'],
                                          font=UI_FONT(FS_BASE, bold=True), anchor="w")
        self.detail_author.pack(side=tk.LEFT, padx=(0, SP_MD))

        self.detail_likes = ctk.CTkLabel(info_cards, text="❤ 0", text_color=C['brand'],
                                         font=UI_FONT(bold=True))
        self.detail_likes.pack(side=tk.LEFT, padx=(0, SP_MD))
        self.detail_collects = ctk.CTkLabel(info_cards, text="⭐ 0", text_color=C['warning'],
                                            font=UI_FONT(bold=True))
        self.detail_collects.pack(side=tk.LEFT, padx=(0, SP_MD))
        self.detail_comments = ctk.CTkLabel(info_cards, text="💬 0", text_color=C['info'],
                                            font=UI_FONT(bold=True))
        self.detail_comments.pack(side=tk.LEFT)

        # 正文 + 评论
        text_shell = ctk.CTkFrame(detail_inner, fg_color=C['card_alt'],
                                  corner_radius=CTRL_RADIUS, border_width=0)
        text_shell.pack(fill=tk.BOTH, expand=True)
        self.detail_text = scrolledtext.ScrolledText(
            text_shell, height=10, state=tk.DISABLED, wrap=tk.WORD,
            font=UI_FONT(FS_SMALL), bg=C['card_alt'], fg=C['text'],
            relief="flat", borderwidth=0, padx=SP_SM, pady=SP_SM,
            insertbackground=C['text'], selectbackground=C['brand_soft'],
            selectforeground=C['brand'])
        self.detail_text.tag_configure('field', foreground=C['text_sub'],
                                       font=UI_FONT(FS_SMALL))
        self.detail_text.tag_configure('value', foreground=C['text'],
                                       font=UI_FONT(FS_SMALL))
        self.detail_text.tag_configure('body', foreground=C['text'],
                                       font=UI_FONT(FS_SMALL), spacing1=3, spacing3=3)
        self.detail_text.tag_configure('section', foreground=C['brand'],
                                       font=UI_FONT(FS_SMALL, bold=True),
                                       spacing1=12, spacing3=4)
        self.detail_text.tag_configure('meta', foreground=C['text_faint'],
                                       font=UI_FONT(FS_SMALL - 1), spacing1=6)
        self.detail_text.tag_configure('quote', foreground=C['text'],
                                       font=UI_FONT(FS_SMALL), lmargin1=16,
                                       lmargin2=16, spacing3=6)
        self.detail_text.vbar.configure(
            bg=C['border_strong'], troughcolor=C['card_alt'],
            activebackground=C['text_faint'], borderwidth=0,
            highlightthickness=0, width=12, relief="flat", elementborderwidth=0)
        self.detail_text.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)
        # 注意：不要再绑 <Double-Button-1> 开查看器——单击已经打开，
        # 双击会先后触发两次（Button-1 + Double-Button-1）叠出两个窗口
        # 画布尺寸变化时按新网格重排（防抖），使缩略图始终铺满可用空间
        self.preview_canvas.bind("<Configure>", self._on_preview_canvas_resize)
        self._preview_resize_job = None
        self._preview_last_grid = (0, 0)
        
        # 存储当前选中的笔记数据
        self.current_selected_note = None
        self.preview_image_paths = []
        self.preview_comment_images = []  # 评论图片路径
        self.preview_images = []  # 保持图片引用
        self.current_video_path = None  # 当前预览的视频路径
        self.preview_page = 0  # 预览分页
        # 注：每页数量已改为按画布尺寸自适应（见 _preview_grid），
        # preview_page_size 不再使用，保留仅为兼容外部引用
        self.preview_page_size = 3
        self.sort_column = None  # 排序列
        self.sort_reverse = False  # 排序方向
        self.filtered_notes = []  # 筛选后的数据
        self.displayed_notes = []  # 当前表格实际显示的序列（行号→数据的权威映射）

        # 绑定事件
        self.result_tree.bind("<<TreeviewSelect>>", self._on_result_select)
        self.result_tree.bind("<Double-Button-1>", self._on_result_double_click)
    
    def _refresh_crawl_batches(self):
        """刷新爬取批次列表"""
        import glob
        batches = ["全部"]
        
        # 扫描images目录下的所有文件夹
        if os.path.exists("images"):
            folders = []
            for folder in os.listdir("images"):
                folder_path = os.path.join("images", folder)
                if os.path.isdir(folder_path):
                    # 获取文件夹信息
                    try:
                        mtime = os.path.getmtime(folder_path)
                        # 计算文件夹内的图片数量
                        img_count = len(glob.glob(f"{folder_path}/**/*.jpg", recursive=True))
                        img_count += len(glob.glob(f"{folder_path}/**/*.png", recursive=True))
                        folders.append((folder, mtime, img_count))
                    except:
                        folders.append((folder, 0, 0))
            
            # 按修改时间排序（最新的在前）
            folders.sort(key=lambda x: x[1], reverse=True)
            
            # 格式化显示
            from datetime import datetime
            for folder, mtime, count in folders:
                if mtime > 0:
                    time_str = datetime.fromtimestamp(mtime).strftime("%m-%d %H:%M")
                    batches.append(f"{folder} ({count}张) [{time_str}]")
                else:
                    batches.append(f"{folder} ({count}张)")
        
        # CTkComboBox 没有 ttk 的 ['values'] 索引赋值与 .current()，
        # 一律走 configure/set
        self.crawl_batch_combo.configure(values=batches)
        # 保留用户当前选择：按**文件夹名**匹配而非整串标签。此前用整串
        # 比较，一旦批次图片数变化（标签里的"N张"变了），旧标签失配就把
        # 用户踢回"全部"进汇总视图。
        current = self.crawl_batch_var.get()
        current_folder = self._batch_label_to_folder(current)
        match = next((b for b in batches if self._batch_label_to_folder(b) == current_folder), None)
        if current == "全部":
            self.crawl_batch_combo.set("全部")
        elif match:
            self.crawl_batch_combo.set(match)  # 标签可能已更新，用新标签
        elif batches:
            self.crawl_batch_combo.set(batches[0])
            if current and current != "全部":
                self._on_batch_select()  # 之前选中的批次已被删除，回退到汇总视图

    @staticmethod
    def _batch_label_to_folder(label: str) -> str:
        """从下拉标签反解文件夹名。

        标签格式是我们自己拼的 "{folder} ({count}张) [{time}]"（或无时间段）。
        用正则只剥掉这段固定后缀，因此**文件夹名本身含空格或括号**（如
        关键词"美食 (推荐)"）也能正确还原——不能用 split(" (")[0]，那会
        在文件夹名的括号处提前截断。
        """
        if not label or label == "全部":
            return label
        return re.sub(r' \(\d+张\)( \[[^\]]*\])?$', '', label)

    def _update_batch_controls_state(self):
        """批次下拉与配套按钮只在"本地批次"数据源下可用。

        灰掉而不是隐藏：让用户知道有这组功能、去哪里启用。
        "刷新批次"保持常可用——它只重扫文件夹列表，不切视图。
        """
        is_batch_mode = self.data_source_var.get() == "本地批次"
        state = "readonly" if is_batch_mode else "disabled"
        btn_state = "normal" if is_batch_mode else "disabled"
        try:
            self.crawl_batch_combo.configure(state=state)
            self._batch_open_btn.configure(state=btn_state)
            self._batch_del_btn.configure(state=btn_state)
        except Exception:
            pass  # 构建早期控件未就绪

    def _on_batch_select(self, _choice=None):
        """选择爬取批次。参数是 CTkComboBox 回传的选中值字符串，此处不用。

        只在"本地批次"数据源下生效——其余模式下批次下拉是禁用的，
        这里再加一道守卫，防止程序化 set() 触发误切视图。
        """
        if self.data_source_var.get() != "本地批次":
            return
        selected = self.crawl_batch_var.get()
        if selected == "全部":
            self._load_all_batch_images()
        else:
            self._load_batch_images(self._batch_label_to_folder(selected))
    
    def _filter_results(self):
        """筛选结果"""
        search_text = self.search_var.get().strip().lower()
        type_filter = self.type_filter_var.get()

        # 获取数据源。批次明细模式下也允许筛选（笔记 dict 同样有
        # title/author 字段）；批次汇总模式（文件夹列表）无可筛字段，
        # 此前会静默清空表格，现在直接提示
        if self.current_batch_folder and self.batch_notes_data:
            source_notes = self.batch_notes_data
        elif self.batch_notes_data and not self.current_batch_folder:
            self.log("批次汇总视图不支持筛选，请先选择具体批次", "WARNING")
            return
        elif self.data_source_var.get() == "历史数据库":
            # 历史模式：搜索词下推到 SQL（LIKE 标题/作者/正文/关键词），
            # 避免只在已加载的前 1000 条里搜漏掉更早的记录；
            # 载入后下面的内存筛选再叠加类型过滤
            self._load_history_data()
            source_notes = getattr(self, 'history_notes_data', [])
        else:
            source_notes = self.all_notes_data
        
        # 筛选
        filtered = []
        for note in source_notes:
            # 类型筛选
            note_type = note.get('note_type', '图文')
            if type_filter != "全部":
                if type_filter == "视频" and note_type != "视频":
                    continue
                if type_filter == "图文" and note_type == "视频":
                    continue
            
            # 文本搜索（四列与历史 SQL 的 LIKE 保持一致，
            # 否则 SQL 按 keyword 列命中的行会被这里滤掉）
            if search_text:
                haystack = ' '.join((
                    note.get('title', '') or '',
                    note.get('author', '') or '',
                    note.get('content', '') or '',
                    note.get('keyword', '') or '',
                )).lower()
                if search_text not in haystack:
                    continue
            
            filtered.append(note)
        
        self.filtered_notes = filtered
        self._refresh_table_with_notes(filtered)
    
    def _reset_filter(self):
        """重置筛选——留在当前视图，不切换数据源/踢出批次。

        此前无条件调 _on_data_source_change 会清空批次状态、把批次下拉
        复位"全部"，用户在某批次里点"重置"会莫名跳回当前爬取/历史视图。
        """
        self.search_var.set("")
        self.type_filter_var.set("全部")
        self.filtered_notes = []
        # 按当前视图重新渲染未筛选数据
        if self.current_batch_folder and self.batch_notes_data:
            self._refresh_table_with_notes(self.batch_notes_data)   # 批次明细
        elif self.batch_notes_data and not self.current_batch_folder:
            self._load_all_batch_images()                            # 批次汇总
        elif self.data_source_var.get() == "历史数据库":
            self._load_history_data()
        else:
            self._refresh_table_with_notes(
                self.all_notes_data,
                count_label=f"共 {len(self.all_notes_data)} 条记录")
    
    def _refresh_table_with_notes(self, notes, count_label=None):
        """用指定数据刷新表格（全仓唯一的结果表渲染入口）

        所有模式都应经由此方法渲染，以保证列语义、斑马纹、类型着色和
        统计口径一致。notes 同时会被登记为当前显示序列，供选中/预览按
        行号反查——排序后必须传入排序结果，否则行号与数据会错位。
        """
        for item in self.result_tree.get_children():
            self.result_tree.delete(item)

        # 登记当前显示序列：行号 → 数据 的唯一依据
        self.displayed_notes = list(notes)

        total_likes = 0
        image_count = 0
        video_count = 0

        for i, note in enumerate(notes):
            note_type = "视频" if note.get('note_type') == "视频" else "图文"
            like_count = note.get('like_count', 0) or 0
            collect_count = note.get('collect_count', 0) or 0
            comment_count = note.get('comment_count', 0) or 0
            
            # 斑马纹和类型颜色
            tags = ('oddrow',) if i % 2 else ('evenrow',)
            if note_type == "视频":
                tags = tags + ('video',)
                video_count += 1
            else:
                tags = tags + ('image',)
                image_count += 1
            
            try:
                total_likes += int(like_count)
            except (TypeError, ValueError):
                pass

            self.result_tree.insert("", tk.END, values=(
                i + 1, note_type,
                (note.get('title', '') or '')[:28],
                (note.get('author', '') or '')[:12],
                like_count, collect_count, comment_count
            ), tags=tags)

        # 更新统计
        self.result_count_label.configure(text=count_label or f"总计: {len(notes)} 条")
        self.stats_image_label.configure(text=f"图文: {image_count}")
        self.stats_video_label.configure(text=f"视频: {video_count}")
        self.stats_likes_label.configure(text=f"总点赞: {total_likes:,}")
    
    def _sort_by_column(self, col):
        """点击表头排序"""
        # 批次视图（汇总/明细）不支持表头排序：其后备列表结构不同，
        # 排序会打穿视图并使 displayed_notes 与 batch 数据错位
        if self.current_batch_folder or self.batch_notes_data:
            self.log("批次视图暂不支持排序", "INFO")
            return

        # 获取当前数据
        if self.filtered_notes:
            notes = self.filtered_notes
        elif self.data_source_var.get() == "历史数据库":
            notes = getattr(self, 'history_notes_data', [])
        else:
            notes = self.all_notes_data

        if not notes:
            return
        
        # 切换排序方向
        if self.sort_column == col:
            self.sort_reverse = not self.sort_reverse
        else:
            self.sort_column = col
            self.sort_reverse = False
        
        # 排序映射
        key_map = {
            "序号": lambda x: x.get('idx', 0) or 0,
            "类型": lambda x: x.get('note_type', ''),
            "标题": lambda x: x.get('title', '') or '',
            "作者": lambda x: x.get('author', '') or '',
            "点赞": lambda x: int(x.get('like_count', 0) or 0),
            "收藏": lambda x: int(x.get('collect_count', 0) or 0),
            "评论": lambda x: int(x.get('comment_count', 0) or 0),
        }
        
        key_func = key_map.get(col)
        if key_func:
            try:
                notes_sorted = sorted(notes, key=key_func, reverse=self.sort_reverse)
            except (TypeError, ValueError) as e:
                self.log(f"排序失败: {e}", "WARNING")
                return
            # 必须把排序结果写回后备列表：选中/预览/删除都按行号反查，
            # 否则排序后点任意一行都会取到错位的数据
            self.filtered_notes = notes_sorted
            self._refresh_table_with_notes(notes_sorted)
    
    def _show_tree_context_menu(self, event):
        """显示右键菜单"""
        item = self.result_tree.identify_row(event.y)
        if item:
            self.result_tree.selection_set(item)
            self.tree_context_menu.post(event.x_root, event.y_root)
    
    def _copy_to_clipboard(self, text: str, what: str):
        """写剪贴板。空内容不再静默清空剪贴板，而是明确提示。

        批次汇总行/旧数据行没有 title/author/note_id，此前会 clipboard_clear
        后 append 空串——用户以为复制成功，实际剪贴板被清空。
        """
        if not text:
            messagebox.showinfo("提示", f"当前选中项没有可复制的{what}")
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.log(f"已复制{what}", "INFO")

    def _copy_title(self):
        """复制标题"""
        if self.current_selected_note:
            self._copy_to_clipboard(self.current_selected_note.get('title', ''), "标题")

    def _copy_author(self):
        """复制作者"""
        if self.current_selected_note:
            self._copy_to_clipboard(self.current_selected_note.get('author', ''), "作者")

    def _copy_link(self):
        """复制链接"""
        if self.current_selected_note:
            note = self.current_selected_note
            link = note.get('note_link', '')
            if not link and note.get('note_id'):
                link = f"https://www.xiaohongshu.com/explore/{note['note_id']}"
            self._copy_to_clipboard(link, "链接")

    def _copy_note_content(self):
        """复制笔记内容"""
        if self.current_selected_note:
            note = self.current_selected_note
            if not (note.get('title') or note.get('content')):
                messagebox.showinfo("提示", "当前选中项没有可复制的内容")
                return
            content = f"{note.get('title', '')}\n\n作者: {note.get('author', '')}\n\n{note.get('content', '')}"
            self._copy_to_clipboard(content, "内容")
    
    def _copy_all_data(self):
        """复制全部数据为文本"""
        items = self.result_tree.get_children()
        if not items:
            return
        
        lines = ["序号\t类型\t标题\t作者\t点赞\t收藏\t评论"]
        for item in items:
            values = self.result_tree.item(item)['values']
            lines.append("\t".join(str(v) for v in values))
        
        self.root.clipboard_clear()
        self.root.clipboard_append("\n".join(lines))
        messagebox.showinfo("成功", f"已复制 {len(items)} 条数据到剪贴板")
    
    def _delete_single_note(self):
        """右键"删除此条"——按当前视图分派，确认文案与实际删除范围一致。

        历史教训：此前统一取 current_selected_note 的 folder_path/path 直接
        rmtree，批次汇总模式下该字段是**整个批次目录**，弹窗却说"删除这条
        笔记"，一次误点丢几十条笔记；当前爬取/历史模式则因无该字段静默
        no-op 还把视图跳到批次汇总。判别必须用视图状态，不能用多态字段。
        """
        note = self.current_selected_note
        if not note:
            return

        in_batch_detail = bool(getattr(self, 'current_batch_folder', None))
        in_batch_summary = (not in_batch_detail
                            and bool(getattr(self, 'batch_notes_data', []))
                            and 'path' in (self.batch_notes_data[0] or {})
                            and 'note_id' not in (self.batch_notes_data[0] or {}))

        if in_batch_summary:
            # 批次汇总行：删除对象是整个批次目录——如实告知并走批次删除
            folder = note.get('folder_path') or note.get('path') or ''
            name = os.path.basename(folder.rstrip('/\\')) if folder else '?'
            if not folder or not os.path.exists(folder):
                messagebox.showinfo("提示", "批次文件夹不存在")
                return
            if not messagebox.askyesno(
                    "确认删除整个批次",
                    f"当前选中的是一个批次（不是单条笔记）！\n\n"
                    f"将删除整个批次文件夹及其中全部笔记媒体：\n{name}\n\n"
                    f"此操作不可恢复，确定继续吗？"):
                return
            try:
                import shutil
                shutil.rmtree(folder)
                self._refresh_crawl_batches()
                self._load_all_batch_images()
                self.log(f"已删除批次: {name}", "WARNING")
            except OSError as e:
                messagebox.showerror("错误", f"删除失败: {e}")
            return

        if in_batch_detail:
            # 单批次明细行：删磁盘目录 + 同步删除 DB 行（否则历史视图残留
            # 指向已删目录的孤儿记录）
            if not messagebox.askyesno("确认", "确定要删除这条笔记吗？\n（同时删除本地文件和数据库记录）"):
                return
            try:
                folder = note.get('path') or note.get('local_dir') or ''
                if folder and os.path.exists(folder):
                    import shutil
                    shutil.rmtree(folder)
                note_id = note.get('note_id', '')
                if note_id:
                    try:
                        conn = sqlite3.connect(self.config.db_path)
                        conn.execute("DELETE FROM notes WHERE note_id = ?", (note_id,))
                        conn.commit()
                        conn.close()
                    except sqlite3.Error as e:
                        self.log(f"删除数据库记录失败: {e}", "WARNING")
                self._on_batch_select()  # 重扫当前批次
            except OSError as e:
                messagebox.showerror("错误", f"删除失败: {e}")
            return

        # 当前爬取 / 历史数据库：复用 _delete_selected 的成熟路径
        # （右键弹菜单前已 selection_set 当前行，DB/媒体/列表三方同步）
        self._delete_selected()
    
    def _reset_preview_state(self, message: str = ""):
        """预览状态的唯一重置入口。

        四项状态（图片列表/评论图/视频路径/页码）必须一起清：任何一项
        残留都会让 _maybe_reflow_preview 在窗口缩放时把上一条笔记的媒体
        重绘到当前视图（曾出现批次汇总里画出上一条笔记的视频缩略图）。
        """
        self.preview_image_paths = []
        self.preview_comment_images = []
        self.current_video_path = None
        self.preview_page = 0
        self.preview_images = []
        try:
            self.preview_canvas.delete("all")
            self.preview_page_label.configure(text="")
            if message:
                cw = max(self.preview_canvas.winfo_width(), 200)
                self.preview_canvas.create_text(cw // 2, 60, text=message, fill="#888")
        except tk.TclError:
            pass

    def _prev_preview_page(self):
        """上一页预览"""
        if self.preview_page > 0:
            self.preview_page -= 1
            self._render_preview_page()
    
    # 预览网格布局常量
    PREVIEW_GAP = 16          # 缩略图间距
    PREVIEW_PAD = 16          # 画布内边距
    PREVIEW_TARGET_CELL = 220 # 目标缩略图边长（据此定列数，再回算实际cell撑满宽度）

    def _preview_total_slots(self) -> int:
        """预览槽位总数：视频缩略图 + 笔记图片 + 评论图片（都参与网格分页）"""
        n = len(self.preview_image_paths)
        if self.current_video_path:
            n += 1
        n += len(getattr(self, 'preview_comment_images', []))
        return n

    def _preview_grid(self, canvas_w: int, canvas_h: int):
        """据画布尺寸算网格：返回 (列数, 行数, 单元宽, 单元高)。

        列数由目标边长定，单元宽回算以铺满整行宽度；行数按可用高度填充。
        画布尚未完成布局（尺寸≈1）时给出合理兜底，避免除零/挤成一列。
        """
        if canvas_w <= 1:
            canvas_w = 720
        if canvas_h <= 1:
            canvas_h = 300
        gap, pad = self.PREVIEW_GAP, self.PREVIEW_PAD
        avail_w = max(1, canvas_w - pad * 2)
        cols = max(1, round((avail_w + gap) / (self.PREVIEW_TARGET_CELL + gap)))
        cell_w = (avail_w - (cols - 1) * gap) / cols
        cell_h = cell_w  # 方形单元，缩略图按原比例居中放入
        avail_h = max(1, canvas_h - pad * 2)
        rows = max(1, int((avail_h + gap) // (cell_h + gap)))
        return cols, rows, cell_w, cell_h

    def _preview_items_per_page(self) -> int:
        cols, rows, _, _ = self._preview_grid(
            self.preview_canvas.winfo_width(), self.preview_canvas.winfo_height())
        return max(1, cols * rows)

    def _preview_max_page(self) -> int:
        """预览总页数（基于自适应网格每页容量）"""
        total = self._preview_total_slots()
        ipp = self._preview_items_per_page()
        return max(1, (total + ipp - 1) // ipp)

    def _next_preview_page(self):
        """下一页预览"""
        if self.preview_page < self._preview_max_page() - 1:
            self.preview_page += 1
            self._render_preview_page()

    def _on_preview_canvas_resize(self, event):
        """画布尺寸变化 → 防抖后按新网格重排（仅当每页容量真的变了）"""
        if self._preview_resize_job is not None:
            try:
                self.root.after_cancel(self._preview_resize_job)
            except Exception:
                pass
        self._preview_resize_job = self.root.after(120, self._maybe_reflow_preview)

    def _maybe_reflow_preview(self):
        self._preview_resize_job = None
        if not self.preview_image_paths and not self.current_video_path \
                and not getattr(self, 'preview_comment_images', []):
            return
        cols, rows, _, _ = self._preview_grid(
            self.preview_canvas.winfo_width(), self.preview_canvas.winfo_height())
        if (cols, rows) != self._preview_last_grid:
            self.preview_page = min(self.preview_page, self._preview_max_page() - 1)
            self._render_preview_page()
    
    # 注：此处原有一个无参版 _open_image_viewer（仅 os.startfile 第一张图），
    # 与 2600+ 行的完整查看器同名互相覆盖，已删除；统一使用带
    # start_index 参数的完整实现（默认参数兼容无参调用点）。

    def _load_batch_images(self, folder_name):
        """加载指定批次的图片，并从数据库获取笔记详情"""
        import glob
        
        folder_path = os.path.abspath(os.path.join("images", folder_name))
        if not os.path.exists(folder_path):
            return
        
        # 清空表格
        for item in self.result_tree.get_children():
            self.result_tree.delete(item)
        
        # 从数据库获取批次相关的笔记数据。
        # 匹配优先级（见下方使用处）：
        #   ① local_dir 精确路径配对（全库，无误配可能）——权威方式
        #   ② 文件夹名里的 note_id
        #   ③ crawl_time 窗口 + 位置回退（仅旧格式数据的最后手段）
        def _dir_key(p):
            return os.path.normcase(os.path.normpath(os.path.abspath(p)))

        db_notes = {}
        db_by_dir = {}
        db_notes_by_order = []  # 时间窗口内按爬取顺序（仅供位置回退）
        try:
            conn = sqlite3.connect(self.config.db_path)
            cursor = conn.cursor()

            # ① 全库 local_dir 映射（行数有限，代价可忽略）
            cursor.execute("SELECT * FROM notes WHERE local_dir IS NOT NULL AND local_dir != ''")
            columns = [desc[0] for desc in cursor.description]
            for row in cursor.fetchall():
                note = dict(zip(columns, row))
                db_by_dir[_dir_key(note['local_dir'])] = note
                if note.get('note_id'):
                    db_notes[note['note_id']] = note

            # ③ 时间窗口（供旧数据位置回退）。
            # 起点收紧为 批次时间-1分钟：此前 -5 分钟会把上一批次的尾部
            # 拉进窗口，位置回退随即整体串位（B 批显示 A 批的标题点赞）。
            parts = folder_name.split("_")
            if len(parts) >= 3:
                try:
                    date_str, time_str = parts[-2], parts[-1]
                    from datetime import datetime, timedelta
                    batch_time = datetime.strptime(f"{date_str}_{time_str}", "%Y%m%d_%H%M%S")
                    start_time = (batch_time - timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M:%S")
                    end_time = (batch_time + timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S")
                    cursor.execute(
                        "SELECT * FROM notes WHERE crawl_time >= ? AND crawl_time <= ? ORDER BY crawl_time ASC",
                        (start_time, end_time))
                    columns = [desc[0] for desc in cursor.description]
                    for row in cursor.fetchall():
                        note = dict(zip(columns, row))
                        db_notes_by_order.append(note)
                        if note.get('note_id') and note['note_id'] not in db_notes:
                            db_notes[note['note_id']] = note
                except (ValueError, sqlite3.Error):
                    # 文件夹名无法解析时间 → 不做位置回退（乱序全库列表
                    # 上按位置索引纯属随机匹配，宁缺毋滥）
                    pass
            conn.close()
        except Exception as e:
            print(f"[数据库] 查询失败: {e}")
        
        # 扫描文件夹下的所有笔记
        note_folders = []
        for note_folder in os.listdir(folder_path):
            note_path = os.path.abspath(os.path.join(folder_path, note_folder))
            if os.path.isdir(note_path) and note_folder.startswith("note_"):
                # 使用绝对路径查找图片和视频
                images = [os.path.abspath(f) for f in glob.glob(os.path.join(note_path, "*.jpg"))]
                images += [os.path.abspath(f) for f in glob.glob(os.path.join(note_path, "*.png"))]
                images += [os.path.abspath(f) for f in glob.glob(os.path.join(note_path, "*.webp"))]
                videos = [os.path.abspath(f) for f in glob.glob(os.path.join(note_path, "*.mp4"))]
                if images or videos:
                    # 提取序号和note_id
                    parts = note_folder.split("_")
                    try:
                        idx = int(parts[1])
                    except:
                        idx = 0
                    
                    # 提取note_id (格式: note_1_noteId 或 note_1_timestamp)
                    # note_id是24位字母数字，timestamp是10位数字
                    potential_id = parts[2] if len(parts) > 2 else ""
                    # 如果是24位且包含字母，则是note_id；否则是时间戳
                    if len(potential_id) >= 20 and any(c.isalpha() for c in potential_id):
                        note_id = potential_id
                    else:
                        note_id = ""

                    # 匹配 DB 详情：① local_dir 精确路径 → ② note_id → ③ 位置回退
                    db_note = db_by_dir.get(_dir_key(note_path), {})
                    if not db_note and note_id:
                        db_note = db_notes.get(note_id, {})
                    if not db_note and db_notes_by_order and 0 <= idx - 1 < len(db_notes_by_order):
                        # 仅当窗口内数量与磁盘笔记数相近时才敢按位置回退，
                        # 否则宁可留空也不冒串位风险
                        db_note = db_notes_by_order[idx - 1]
                    if db_note.get('note_id'):
                        note_id = db_note['note_id']
                    
                    note_folders.append({
                        'folder': note_folder,
                        'path': note_path,
                        'idx': idx,
                        'note_id': note_id,
                        'images': images,
                        'videos': videos,
                        'image_count': len(images),
                        'has_video': len(videos) > 0,
                        # 从数据库获取的数据
                        'title': db_note.get('title', ''),
                        'author': db_note.get('author', ''),
                        'like_count': db_note.get('like_count', 0),
                        'collect_count': db_note.get('collect_count', 0),
                        'comment_count': db_note.get('comment_count', 0),
                        'content': db_note.get('content', ''),
                        'tags': db_note.get('tags', ''),
                        'note_type': db_note.get('note_type', '视频' if len(videos) > 0 else '图文'),
                        'note_link': db_note.get('note_link', ''),
                    })
        
        # 按序号排序
        note_folders.sort(key=lambda x: x['idx'])
        
        # 存储当前批次数据
        self.batch_notes_data = note_folders
        self.current_batch_folder = folder_path
        
        # 填充表格
        total_likes = 0
        image_count = 0
        video_count = 0
        
        for i, note in enumerate(note_folders):
            note_type = "视频" if note['has_video'] else "图文"
            title = note.get('title', '') or f"笔记{note['idx']}"
            author = note.get('author', '') or f"{note['image_count']}张"
            like_count = note.get('like_count', 0) or 0
            collect_count = note.get('collect_count', 0) or 0
            comment_count = note.get('comment_count', 0) or 0
            
            # 统计
            if note_type == "视频":
                video_count += 1
            else:
                image_count += 1
            try:
                total_likes += int(like_count)
            except:
                pass
            
            # 斑马纹
            tags = ('oddrow',) if i % 2 else ('evenrow',)
            if note_type == "视频":
                tags = tags + ('video',)
            else:
                tags = tags + ('image',)
            
            self.result_tree.insert("", tk.END, values=(
                note['idx'],
                note_type,
                title[:28] if title else f"笔记{note['idx']}",
                author[:12] if author else "-",
                like_count if like_count else "-",
                collect_count if collect_count else "-",
                comment_count if comment_count else "-"
            ), tags=tags)
        
        # 登记显示序列（行位置 → 数据），与表格渲染顺序严格一致
        self.displayed_notes = list(note_folders)

        # 更新统计
        self.result_count_label.configure(text=f"共 {len(note_folders)} 个笔记")
        self.stats_image_label.configure(text=f"图文: {image_count}")
        self.stats_video_label.configure(text=f"视频: {video_count}")
        self.stats_likes_label.configure(text=f"总点赞: {total_likes:,}")
    
    @staticmethod
    def _scan_batch_summary(folder_path):
        """统计一个批次目录：返回 (笔记数, 图片数, 视频数)。

        口径与批次明细视图严格一致——只数各 note_ 子目录**顶层**的正图，
        不含 comments/ 里的评论图；笔记数只算含顶层媒体的目录。此前用
        递归 glob 把评论图和空目录都算进来，汇总数比明细多、对不上。
        """
        import glob
        note_count = img_count = video_count = 0
        try:
            for d in os.listdir(folder_path):
                note_path = os.path.join(folder_path, d)
                if not (os.path.isdir(note_path) and d.startswith("note_")):
                    continue
                imgs = (glob.glob(os.path.join(note_path, "*.jpg"))
                        + glob.glob(os.path.join(note_path, "*.png"))
                        + glob.glob(os.path.join(note_path, "*.webp")))
                vids = glob.glob(os.path.join(note_path, "*.mp4"))
                if imgs or vids:
                    note_count += 1
                    img_count += len(imgs)
                    video_count += len(vids)
        except OSError:
            pass
        return note_count, img_count, video_count

    def _load_all_batch_images(self):
        """加载所有批次的摘要"""
        # 清空表格
        for item in self.result_tree.get_children():
            self.result_tree.delete(item)

        self.batch_notes_data = []
        self.current_batch_folder = None
        self._reset_preview_state()  # 防止上一视图的预览媒体残留

        if not os.path.exists("images"):
            return

        folders = []
        for folder in os.listdir("images"):
            folder_path = os.path.join("images", folder)
            if os.path.isdir(folder_path):
                try:
                    mtime = os.path.getmtime(folder_path)
                    note_count, img_count, video_count = self._scan_batch_summary(folder_path)
                    folders.append({
                        'name': folder,
                        'path': folder_path,
                        'mtime': mtime,
                        'images': img_count,
                        'videos': video_count,
                        'notes': note_count
                    })
                except OSError:
                    pass
        
        # 按时间排序
        folders.sort(key=lambda x: x['mtime'], reverse=True)
        
        from datetime import datetime
        for i, f in enumerate(folders):
            time_str = datetime.fromtimestamp(f['mtime']).strftime("%m-%d %H:%M")
            # 解析关键词
            keyword = f['name'].split("_")[0] if "_" in f['name'] else f['name']
            self.result_tree.insert("", tk.END, values=(
                i + 1,
                "批次",
                f"{keyword} ({time_str})",
                f"{f['notes']}笔记",
                f"{f['images']}图",
                f"{f['videos']}视频",
                "-"
            ))
        
        self.batch_notes_data = folders
        self.displayed_notes = list(folders)
        self.result_count_label.configure(text=f"共 {len(folders)} 个爬取批次")
        self._reset_result_stats()  # 汇总视图无图文/视频/点赞概念，清零避免残留
    
    def _delete_batch_folder(self):
        """删除选中的批次文件夹"""
        selected = self.crawl_batch_var.get()
        if selected == "全部":
            messagebox.showinfo("提示", "请先选择一个具体的爬取批次")
            return
        
        folder_name = self._batch_label_to_folder(selected)
        folder_path = os.path.join("images", folder_name)

        if not os.path.exists(folder_path):
            messagebox.showinfo("提示", "文件夹不存在")
            return

        # 计算内容
        import glob
        img_count = len(glob.glob(f"{folder_path}/**/*.jpg", recursive=True))
        img_count += len(glob.glob(f"{folder_path}/**/*.png", recursive=True))
        
        if not messagebox.askyesno("确认删除", 
            f"确定要删除整个爬取批次吗？\n\n文件夹: {folder_name}\n图片数量: {img_count}\n\n此操作不可恢复！"):
            return
        
        try:
            import shutil
            shutil.rmtree(folder_path)
            messagebox.showinfo("完成", f"已删除: {folder_name}")
            self._refresh_crawl_batches()
            self._load_all_batch_images()
        except Exception as e:
            messagebox.showerror("错误", f"删除失败: {e}")
    
    def _open_batch_folder(self):
        """打开批次文件夹"""
        selected = self.crawl_batch_var.get()
        if selected == "全部":
            if os.path.exists("images"):
                os.startfile(os.path.abspath("images"))
            return
        
        folder_name = self._batch_label_to_folder(selected)
        folder_path = os.path.join("images", folder_name)

        if os.path.exists(folder_path):
            os.startfile(os.path.abspath(folder_path))
        else:
            messagebox.showinfo("提示", "文件夹不存在")
    
    def _on_data_source_change(self, _choice=None):
        """切换数据源（三选一：当前爬取 / 历史数据库 / 本地批次）。

        参数是分段控件回传的选中值字符串，此处不用。
        """
        source = self.data_source_var.get()

        # 清空批次相关数据，避免影响其他视图
        self.batch_notes_data = []
        self.current_batch_folder = None
        self._reset_preview_state()
        # 批次下拉框必须同步回"全部"：否则它仍显示某个文件夹名，
        # 而表格已切到数据库内容，_on_result_select 会走错分支
        try:
            if self.crawl_batch_var.get() != "全部":
                self.crawl_batch_var.set("全部")
        except Exception:
            pass
        # 搜索/类型筛选属于上一视图的状态，切数据源后清空以保持自洽
        try:
            self.search_var.set("")
            self.type_filter_var.set("全部")
        except Exception:
            pass
        self.filtered_notes = []
        self._update_batch_controls_state()

        if source == "历史数据库":
            self._load_history_data()
        elif source == "本地批次":
            # 进入批次浏览：重扫文件夹并按当前批次值载入
            # （默认"全部"→汇总视图，_refresh 可能已恢复上次所选批次）
            self._refresh_crawl_batches()
            selected = self.crawl_batch_var.get()
            if selected == "全部":
                self._load_all_batch_images()
            else:
                self._load_batch_images(self._batch_label_to_folder(selected))
        else:
            self._show_current_data()
    
    def _get_date_filter(self):
        """获取日期过滤范围"""
        from datetime import datetime, timedelta
        
        date_filter = self.date_filter_var.get() if hasattr(self, 'date_filter_var') else "全部"
        
        if date_filter == "全部":
            return None, None
        
        now = datetime.now()
        
        if date_filter == "今天":
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            end = start + timedelta(days=1)
        elif date_filter == "本周":
            start = now - timedelta(days=now.weekday())
            start = start.replace(hour=0, minute=0, second=0, microsecond=0)
            end = start + timedelta(days=7)
        elif date_filter == "本月":
            start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            if now.month == 12:
                end = start.replace(year=now.year + 1, month=1)
            else:
                end = start.replace(month=now.month + 1)
        else:
            return None, None
        
        return start.strftime("%Y-%m-%d %H:%M:%S"), end.strftime("%Y-%m-%d %H:%M:%S")
    
    def _load_history_data(self):
        """从数据库加载历史数据"""
        try:
            keyword_filter = self.filter_keyword_var.get().strip()
            start_date, end_date = self._get_date_filter()
            
            conn = sqlite3.connect(self.config.db_path)
            cursor = conn.cursor()
            
            # 构建SQL查询
            conditions = []
            params = []

            if keyword_filter:
                # 搜索框的直觉是"按内容搜"，故匹配 标题/作者/正文/搜索词
                # 四列（此前只匹配 keyword 列，而主页推荐/博主抓取该列恒为
                # 空串，输入标题词必然搜不到，用户误判"筛选坏了"）
                conditions.append("(title LIKE ? OR author LIKE ? OR content LIKE ? OR keyword LIKE ?)")
                like = f"%{keyword_filter}%"
                params.extend([like, like, like, like])

            if start_date and end_date:
                conditions.append("crawl_time >= ? AND crawl_time < ?")
                params.extend([start_date, end_date])

            # 统一加 LIMIT 上限并多取 1 条用于判断是否被截断
            HISTORY_LIMIT = 1000
            where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
            cursor.execute(
                f"SELECT * FROM notes {where} ORDER BY crawl_time DESC LIMIT ?",
                params + [HISTORY_LIMIT + 1])

            rows = cursor.fetchall()
            truncated = len(rows) > HISTORY_LIMIT
            if truncated:
                rows = rows[:HISTORY_LIMIT]
            columns = [desc[0] for desc in cursor.description]
            conn.close()
            
            # 清空表格
            for item in self.result_tree.get_children():
                self.result_tree.delete(item)
            
            # 临时存储历史数据
            self.history_notes_data = []
            
            # 预先扫描images文件夹
            import glob
            from datetime import datetime
            
            # 建立note_id到文件夹的映射（新格式）
            note_id_to_folder = {}
            # 建立批次时间到批次文件夹的映射（旧格式）
            batch_folders_by_time = {}
            
            if os.path.exists("images"):
                for batch_folder in os.listdir("images"):
                    batch_path = os.path.join("images", batch_folder)
                    if os.path.isdir(batch_path):
                        # 提取批次时间（格式: 主页推荐_20260202_164319）
                        parts = batch_folder.split("_")
                        if len(parts) >= 3:
                            try:
                                date_str = parts[-2]  # 20260202
                                time_str = parts[-1]  # 164319
                                batch_time = datetime.strptime(f"{date_str}_{time_str}", "%Y%m%d_%H%M%S")
                                batch_folders_by_time[batch_time] = batch_path
                            except:
                                pass
                        
                        for note_folder in os.listdir(batch_path):
                            if note_folder.startswith("note_"):
                                parts = note_folder.split("_")
                                if len(parts) >= 3:
                                    potential_id = parts[2]
                                    if len(potential_id) >= 20 and any(c.isalpha() for c in potential_id):
                                        note_id_to_folder[potential_id] = os.path.abspath(os.path.join(batch_path, note_folder))
            
            for row in rows:
                note = dict(zip(columns, row))
                # 解析JSON字段
                try:
                    note['image_urls'] = json.loads(note.get('image_urls', '[]'))
                except:
                    note['image_urls'] = []
                try:
                    note['comments'] = json.loads(note.get('comments', '[]'))
                except:
                    note['comments'] = []
                
                # 尝试找到本地图片文件夹
                note_id = note.get('note_id', '')
                folder_path = None

                # 方法0（首选）: 数据库记录的 local_dir，精确无歧义
                stored_dir = note.get('local_dir') or ''
                if stored_dir:
                    abs_stored = os.path.abspath(stored_dir)
                    if os.path.isdir(abs_stored):
                        folder_path = abs_stored

                # 方法1: 通过note_id匹配（新格式）
                if not folder_path and note_id and note_id in note_id_to_folder:
                    folder_path = note_id_to_folder[note_id]
                
                # 方法2: 通过crawl_time找批次，再搜索note_id（旧格式）
                if not folder_path and note_id:
                    crawl_time_str = note.get('crawl_time', '')
                    if crawl_time_str:
                        try:
                            crawl_time = datetime.strptime(crawl_time_str, "%Y-%m-%d %H:%M:%S")
                            # 找到最接近的批次文件夹
                            for batch_time, batch_path in batch_folders_by_time.items():
                                # 在批次时间前后30分钟内
                                diff = abs((crawl_time - batch_time).total_seconds())
                                if diff < 1800:  # 30分钟
                                    # 在这个批次中搜索包含note_id的文件夹
                                    for note_folder in os.listdir(batch_path):
                                        if note_folder.startswith("note_") and note_id in note_folder:
                                            folder_path = os.path.abspath(os.path.join(batch_path, note_folder))
                                            break
                                    if folder_path:
                                        break
                        except:
                            pass
                
                # 如果找到了文件夹，加载图片和视频
                if folder_path and os.path.exists(folder_path):
                    local_images = []
                    for ext in ['*.jpg', '*.png', '*.webp']:
                        local_images.extend(glob.glob(os.path.join(folder_path, ext)))
                    note['local_images'] = [os.path.abspath(p) for p in local_images]
                    video_path = os.path.join(folder_path, 'video.mp4')
                    if os.path.exists(video_path):
                        note['local_video'] = os.path.abspath(video_path)
                
                self.history_notes_data.append(note)
            
            # 统一走唯一渲染入口，保证斑马纹/类型着色/统计口径一致
            # 非批次视图必须清空批次状态（排序/删除守卫依赖此信号）
            self.batch_notes_data = []
            self.current_batch_folder = None
            self.filtered_notes = []
            n = len(self.history_notes_data)
            label = (f"仅显示最近 {n} 条（已达上限，请用关键词/时间筛选缩小范围）"
                     if truncated else f"共 {n} 条历史记录")
            self._refresh_table_with_notes(self.history_notes_data, count_label=label)

        except Exception as e:
            messagebox.showerror("错误", f"加载历史数据失败: {e}")
    
    def _show_current_data(self):
        """显示当前爬取的数据"""
        # 此前这里把 keyword/时间 塞进"收藏""评论"两列，导致刷新后
        # 列含义与爬取过程中实时追加的行不一致；现统一走唯一渲染入口
        # 非批次视图必须清空批次状态，否则排序/删除的批次守卫会误触发
        self.batch_notes_data = []
        self.current_batch_folder = None
        self.filtered_notes = []
        self._refresh_table_with_notes(
            self.all_notes_data,
            count_label=f"共 {len(self.all_notes_data)} 条记录")
    
    def _refresh_results(self):
        """刷新结果"""
        self._on_data_source_change()
    
    def _add_result_to_table(self, note_data: dict, index: int):
        """添加一条结果到表格"""
        try:
            # 只在"当前爬取"全量视图追加实时行。
            # 追加条件三选一都不满足则只刷统计、不动表格：
            #  - 数据源非"当前爬取"（用户切到历史/批次）
            #  - 正处于某个批次视图（current_batch_folder 非空）——此前只判
            #    data_source 不判批次，爬取中选批次会把 live 行灌进批次表
            #  - 有筛选/排序（filtered_notes 激活）——末尾插未排序行会错位
            if (self.data_source_var.get() != "当前爬取"
                    or getattr(self, 'current_batch_folder', None)
                    or self.filtered_notes):
                # 冻结态：统计卡描述"当前所见"（displayed_notes），
                # 而非仍在增长的 all_notes_data，避免表格/总计/卡片三方打架
                self._update_result_stats_from_notes(
                    getattr(self, 'displayed_notes', None) or self.all_notes_data)
                return

            note_type = "视频" if note_data.get('note_type') == "视频" else "图文"
            like_count = note_data.get('like_count', 0)
            collect_count = note_data.get('collect_count', 0)
            comment_count = note_data.get('comment_count', 0)

            # 与 _refresh_table_with_notes 保持一致的斑马纹+类型着色
            row_tags = ('oddrow',) if index % 2 else ('evenrow',)
            row_tags += ('video',) if note_type == "视频" else ('image',)

            self.result_tree.insert("", tk.END, values=(
                index + 1,
                note_type,
                note_data.get('title', '')[:28],
                note_data.get('author', '')[:12],
                like_count,
                collect_count,
                comment_count
            ), tags=row_tags)

            # 保持行号→数据映射同步，使爬取过程中即可正确点选
            self.displayed_notes = list(self.all_notes_data)

            count = len(self.result_tree.get_children())
            self.result_count_label.configure(text=f"共 {count} 条记录")
            self._update_result_stats_from_notes(self.all_notes_data)
            self.result_tree.see(self.result_tree.get_children()[-1])
        except Exception as e:
            self.log(f"添加结果行失败: {e}", "WARNING")

    def _update_result_stats_from_notes(self, notes):
        """按笔记列表刷新统计卡片"""
        image_count = sum(1 for n in notes if n.get('note_type') != "视频")
        video_count = sum(1 for n in notes if n.get('note_type') == "视频")
        total_likes = 0
        for n in notes:
            try:
                total_likes += int(n.get('like_count', 0) or 0)
            except (TypeError, ValueError):
                pass
        self.stats_image_label.configure(text=f"图文: {image_count}")
        self.stats_video_label.configure(text=f"视频: {video_count}")
        self.stats_likes_label.configure(text=f"总点赞: {total_likes:,}")

    def _reset_result_stats(self):
        """把三张统计卡清零。批次汇总/清空/重新爬取时用，避免残留上一视图数字。"""
        self.stats_image_label.configure(text="图文: 0")
        self.stats_video_label.configure(text="视频: 0")
        self.stats_likes_label.configure(text="总点赞: 0")

    def _render_detail(self, blocks):
        """把结构化内容渲染进详情面板。

        blocks 是 (kind, text) 序列：
          ('kv', (键, 值))  字段行，键灰值黑
          ('section', 标题) 分节标题，品牌色加粗且自带段前距
          ('body', 文本)    正文段落
          ('meta', 文本)    评论头等次要信息
          ('quote', 文本)   缩进引用（评论正文）
        取代原先用 '='*40 和 '>>> <<<' 拼分隔线的做法——那只有在等宽字体
        下才对得齐，而这里是比例字体，画出来永远是歪的。
        """
        self.detail_text.configure(state=tk.NORMAL)
        self.detail_text.delete(1.0, tk.END)
        for kind, text in blocks:
            if kind == 'kv':
                key, val = text
                if val in (None, ''):
                    continue
                self.detail_text.insert(tk.END, f"{key}   ", 'field')
                self.detail_text.insert(tk.END, f"{val}\n", 'value')
            elif text:
                self.detail_text.insert(tk.END, f"{text}\n", kind)
        self.detail_text.configure(state=tk.DISABLED)

    def _on_result_select(self, event):
        """点击表格行显示详情"""
        try:
            selected = self.result_tree.selection()
            if not selected:
                return
            
            item = self.result_tree.item(selected[0])
            values = item['values']
            
            # 视图判别只看批次状态本身：batch_notes_data / current_batch_folder
            # 在所有切换点（数据源切换、批次选择、爬取启动）都被一致清理，
            # 旧版按 data_source 二次猜测的补丁逻辑会误杀合法的批次视图
            batch_notes = getattr(self, 'batch_notes_data', [])
            batch_folder = getattr(self, 'current_batch_folder', None)
            
            # 行位置是行→数据的唯一可靠键：批次明细的"序号"列显示的是
            # 文件夹编号（可能有空洞），筛选/排序后更与列表位置无关
            row_pos = self.result_tree.index(selected[0])

            if batch_folder and batch_notes:
                # 批次内的笔记视图（displayed_notes 已含筛选后的顺序）
                shown = self.displayed_notes if self.displayed_notes else batch_notes
                for note in ([shown[row_pos]] if 0 <= row_pos < len(shown) else []):
                    idx = note.get('idx', row_pos + 1)
                    if True:
                        self.current_selected_note = note
                        
                        # 获取数据库中的详细信息
                        title = note.get('title', '') or f"笔记 {idx}"
                        author = note.get('author', '')
                        like_count = note.get('like_count', 0) or 0
                        collect_count = note.get('collect_count', 0) or 0
                        comment_count = note.get('comment_count', 0) or 0
                        content = note.get('content', '')
                        tags = note.get('tags', '')
                        note_type = note.get('note_type', '图文')
                        
                        # 更新顶部信息
                        self.detail_title_label.configure(
                            text=title if len(title) <= 60 else title[:60] + '...')
                        self.detail_likes.configure(text=f"❤ {like_count}")
                        self.detail_collects.configure(text=f"⭐ {collect_count}")
                        self.detail_comments.configure(text=f"💬 {comment_count}")
                        self.detail_author.configure(
                            text=f"@{author}" if author else f"{note.get('image_count', 0)}张图片")
                        
                        # 构建详情
                        blocks = []
                        if title and title != f"笔记 {idx}":
                            blocks.append(('kv', ("标题", title)))
                        if author:
                            blocks.append(('kv', ("作者", author)))
                        blocks.append(('kv', ("类型", note_type)))
                        blocks.append(('kv', ("图片", f"{note.get('image_count', 0)} 张")))
                        blocks.append(('kv', ("视频", "有" if note.get('has_video') else "无")))

                        if tags:
                            try:
                                tag_list = json.loads(tags) if isinstance(tags, str) else tags
                                if tag_list:
                                    blocks.append(('kv', ("标签", '、'.join(tag_list[:10]))))
                            except (ValueError, TypeError):
                                pass

                        if content:
                            blocks.append(('section', "正文"))
                            blocks.append(('body', content[:500]))

                        images = note.get('images', [])[:10]
                        if images:
                            blocks.append(('section', f"本地文件（{note.get('image_count', 0)} 张）"))
                            for img in images:
                                blocks.append(('meta', f"· {os.path.basename(img)}"))

                        self._render_detail(blocks)

                        # 加载图片预览
                        self._load_batch_note_previews(note)
                        # 点击即弹出小红书式详情卡片
                        self._open_note_card(note)
                        return
                return
            
            elif batch_notes and not batch_folder:
                # 全部批次视图（行位置直接对应 batch_notes 顺序）
                index = row_pos
                if 0 <= index < len(batch_notes):
                    folder = batch_notes[index]
                    self.current_selected_note = {'folder_path': folder['path'], 'keyword': folder['name'].split("_")[0]}
                    
                    # 更新顶部信息
                    self.detail_title_label.configure(text=folder['name'])
                    self.detail_likes.configure(text=f"❤ -")
                    self.detail_collects.configure(text=f"⭐ -")
                    self.detail_comments.configure(text=f"💬 -")
                    self.detail_author.configure(text=f"{folder.get('notes', 0)}个笔记")
                    
                    blocks = [
                        ('kv', ("笔记数量", folder.get('notes', 0))),
                        ('kv', ("图片数量", folder.get('images', 0))),
                        ('kv', ("视频数量", folder.get('videos', 0))),
                    ]
                    from datetime import datetime
                    mtime = folder.get('mtime', 0)
                    if mtime:
                        blocks.append(('kv', ("创建时间", datetime.fromtimestamp(mtime)
                                              .strftime('%Y-%m-%d %H:%M:%S'))))
                    blocks.append(('meta', "双击进入查看该批次的详细内容"))
                    self._render_detail(blocks)

                    # 清空预览（四项状态一起清，防 resize 重绘上一条笔记媒体）
                    self._reset_preview_state("双击批次行查看笔记与图片")
                    return
            
            # 原有逻辑：数据库或当前爬取
            index = row_pos

            # displayed_notes 由 _refresh_table_with_notes 在每次渲染时登记，
            # 是行位置→数据的唯一权威映射（已含排序/筛选结果）；
            # 其余分支仅作为兜底，防止极早期调用时尚未渲染
            notes = getattr(self, 'displayed_notes', None)
            if not notes:
                if self.filtered_notes:
                    notes = self.filtered_notes
                elif self.data_source_var.get() == "历史数据库":
                    notes = getattr(self, 'history_notes_data', [])
                else:
                    notes = self.all_notes_data

            if 0 <= index < len(notes):
                note = notes[index]
                self.current_selected_note = note
                
                # 更新顶部信息卡片（仿小红书：标题完整、作者突出）
                title = note.get('title', '') or '无标题'
                self.detail_title_label.configure(
                    text=title if len(title) <= 60 else title[:60] + '...')
                self.detail_likes.configure(text=f"❤ {note.get('like_count', 0)}")
                self.detail_collects.configure(text=f"⭐ {note.get('collect_count', 0)}")
                self.detail_comments.configure(text=f"💬 {note.get('comment_count', 0)}")
                author = note.get('author', '') or ''
                self.detail_author.configure(text=f"@{author}" if author else "")

                # 构建详情（主要互动数已在上方指标行显示，这里只补充元信息）
                blocks = [
                    ('kv', ("类型", note.get('note_type', '图文'))),
                    ('kv', ("发布时间", note.get('publish_time', ''))),
                    ('kv', ("IP地区", note.get('ip_region', ''))),
                ]
                # tags 在 DB 里是 JSON 字符串，直接显示会带 ["…"] 括号引号
                tags_val = note.get('tags', '')
                if isinstance(tags_val, str) and tags_val.startswith('['):
                    try:
                        tags_val = json.loads(tags_val)
                    except (ValueError, TypeError):
                        pass
                if isinstance(tags_val, list):
                    tags_val = '、'.join(str(t) for t in tags_val)
                blocks.append(('kv', ("标签", tags_val)))
                if note.get('keyword'):
                    blocks.append(('kv', ("关键词", note.get('keyword', ''))))

                if note.get('content'):
                    blocks.append(('section', "正文"))
                    blocks.append(('body', note.get('content', '')))

                comments = note.get('comments', [])
                if isinstance(comments, str):
                    try:
                        comments = json.loads(comments) if comments else []
                    except (ValueError, TypeError):
                        comments = []
                if comments:
                    blocks.append(('section', f"热门评论（{len(comments)} 条）"))
                    for i, c in enumerate(comments[:15], 1):
                        if isinstance(c, dict):
                            c_author = c.get('author', '') or c.get('user', '') or '匿名'
                            parts = [f"{i}. @{c_author}"]
                            for extra in (c.get('ip', ''), c.get('time', '')):
                                if extra:
                                    parts.append(str(extra))
                            if c.get('likes', 0):
                                parts.append(f"❤{c.get('likes')}")
                            n_imgs = len(c.get('images') or [])
                            if c.get('has_image') or n_imgs:
                                parts.append(f"🖼{n_imgs or 1}图（上方蓝框可点）")
                            blocks.append(('meta', "  ·  ".join(parts)))
                            blocks.append(('quote', c.get('content', '') or ''))
                        else:
                            blocks.append(('quote', f"{i}. {c}"))

                self._render_detail(blocks)

                # 加载图片/视频/评论图预览
                self._load_image_previews(note)
                # 点击即弹出小红书式详情卡片（左图右文+完整评论）
                self._open_note_card(note)

        except Exception as e:
            print(f"选择错误: {e}")
    
    def _load_batch_note_previews(self, note):
        """加载批次笔记的图片预览（支持分页）"""
        self.preview_canvas.delete("all")
        self.preview_images = []
        
        # 获取所有图片路径（确保绝对路径）
        all_images = []
        for img_path in note.get('images', []):
            abs_path = os.path.abspath(img_path)
            if os.path.exists(abs_path):
                all_images.append(abs_path)
        
        # 检查视频
        videos = note.get('videos', [])
        self.current_video_path = None
        if videos:
            for v in videos:
                abs_v = os.path.abspath(v)
                if os.path.exists(abs_v):
                    self.current_video_path = abs_v
                    break
        
        # 批次目录下 comments/ 子文件夹中的评论图
        comment_images = []
        note_dir = ""
        if all_images:
            note_dir = os.path.dirname(all_images[0])
        elif self.current_video_path:
            note_dir = os.path.dirname(self.current_video_path)
        if note_dir:
            cdir = os.path.join(note_dir, 'comments')
            if os.path.isdir(cdir):
                comment_images = [
                    os.path.abspath(f) for f in glob.glob(os.path.join(cdir, '*.*'))
                    if f.lower().endswith(('.jpg', '.jpeg', '.png', '.webp'))
                ]
        self.preview_image_paths = all_images
        self.preview_comment_images = comment_images
        self.preview_page = 0

        if not all_images and not self.current_video_path and not comment_images:
            self.preview_canvas.create_text(200, 75, text="暂无媒体文件", fill="#888")
            self.preview_page_label.configure(text="")
            return
        
        # 使用通用的分页渲染
        self._render_preview_page()
    
    def _load_image_previews(self, note):
        """加载图片预览 - 只显示当前笔记的图片"""
        self.preview_canvas.delete("all")
        self.preview_images = []
        self.preview_image_paths = []
        
        import glob
        
        # 获取本地图片路径 - 优先使用存储的路径
        local_images = note.get('local_images', [])
        
        # 如果是字符串格式，转换为列表
        if isinstance(local_images, str):
            local_images = [p.strip() for p in local_images.split('|') if p.strip()]
        
        # 转换为绝对路径并验证
        valid_stored = []
        for p in local_images:
            if p:
                abs_p = os.path.abspath(p)
                if os.path.exists(abs_p):
                    valid_stored.append(abs_p)
        
        if valid_stored:
            local_images = valid_stored
        else:
            # 没有有效的存储路径，尝试多种方法查找
            local_images = []
            batch_dir = note.get('batch_dir', '')
            note_id = note.get('note_id', '')

            # 方法0（首选）: 数据库中记录的 local_dir，精确且无歧义。
            # 新爬取的数据都有此字段；仅历史遗留数据才会落到下面的模糊回退
            local_dir = note.get('local_dir', '')
            if local_dir:
                abs_dir = os.path.abspath(local_dir)
                if os.path.isdir(abs_dir):
                    for ext in ('*.jpg', '*.png', '*.webp'):
                        local_images.extend(
                            os.path.abspath(p) for p in glob.glob(os.path.join(abs_dir, ext)))

            # 方法1: 使用batch_dir + 序号查找
            idx = None
            try:
                selected = self.result_tree.selection()
                if selected:
                    item = self.result_tree.item(selected[0])
                    idx = int(item['values'][0])
            except (ValueError, IndexError, tk.TclError):
                pass

            if not local_images and batch_dir and idx:
                abs_batch = os.path.abspath(batch_dir)
                pattern = f"{abs_batch}/note_{idx}_*/*.*"
                local_images = [os.path.abspath(f) for f in glob.glob(pattern) 
                               if f.lower().endswith(('.jpg', '.png', '.webp'))]
            
            # 方法2: 根据note_id在所有文件夹中搜索（新格式文件夹）
            if not local_images and note_id and os.path.exists("images"):
                for batch_folder in os.listdir("images"):
                    batch_path = os.path.join("images", batch_folder)
                    if os.path.isdir(batch_path):
                        for note_folder in os.listdir(batch_path):
                            if note_folder.startswith("note_") and note_id in note_folder:
                                folder_path = os.path.abspath(os.path.join(batch_path, note_folder))
                                for ext in ['*.jpg', '*.png', '*.webp']:
                                    local_images.extend(glob.glob(os.path.join(folder_path, ext)))
                                if local_images:
                                    break
                    if local_images:
                        break
            
            # 方法3: 根据crawl_time找批次，用序号匹配（旧格式文件夹）
            # 门禁：仅当既无 local_dir 记录、又非视频笔记时才允许模糊匹配。
            # 视频笔记本可能没有任何图片，模糊匹配必然把别的笔记的图
            # 显示出来（曾是"视频行显示别人拖鞋图"的直接原因）；
            # 行号 idx 在排序/筛选后与磁盘序号也不再对应
            # 仅当 local_dir 确实不指向有效目录时才允许模糊回退；
            # 视频笔记始终禁用模糊（可能本就无图，乱配会张冠李戴）
            local_dir_valid = bool(local_dir) and os.path.isdir(os.path.abspath(local_dir))
            allow_fuzzy = (not local_dir_valid) and note.get('note_type') != '视频'
            if not local_images and allow_fuzzy and os.path.exists("images"):
                crawl_time_str = note.get('crawl_time', '')
                if crawl_time_str and idx:
                    try:
                        from datetime import datetime, timedelta
                        crawl_time = datetime.strptime(crawl_time_str, "%Y-%m-%d %H:%M:%S")
                        
                        # 遍历所有批次文件夹，找到时间匹配的
                        for batch_folder in os.listdir("images"):
                            batch_path = os.path.join("images", batch_folder)
                            if os.path.isdir(batch_path):
                                # 从文件夹名提取时间
                                parts = batch_folder.split("_")
                                if len(parts) >= 3:
                                    try:
                                        date_str = parts[-2]
                                        time_str = parts[-1]
                                        batch_time = datetime.strptime(f"{date_str}_{time_str}", "%Y%m%d_%H%M%S")
                                        # 在批次时间前后30分钟内
                                        diff = abs((crawl_time - batch_time).total_seconds())
                                        if diff < 1800:
                                            # 在这个批次中查找 note_{idx}_ 开头的文件夹
                                            for note_folder in os.listdir(batch_path):
                                                if note_folder.startswith(f"note_{idx}_"):
                                                    folder_path = os.path.abspath(os.path.join(batch_path, note_folder))
                                                    for ext in ['*.jpg', '*.png', '*.webp']:
                                                        local_images.extend(glob.glob(os.path.join(folder_path, ext)))
                                                    break
                                            if local_images:
                                                break
                                    except:
                                        pass
                    except:
                        pass
        
        # 过滤有效路径（排除 comments 子目录里的图，评论图单独列）
        valid_images = []
        for p in local_images:
            if not p or not os.path.exists(p):
                continue
            # 跳过评论目录里的图，避免和笔记图混在一起
            parts = os.path.normpath(p).split(os.sep)
            if 'comments' in parts:
                continue
            valid_images.append(p)

        # 笔记媒体目录：local_dir 优先，其次图片/视频所在目录
        note_dir = ""
        local_dir = note.get('local_dir', '') or ''
        if local_dir and os.path.isdir(os.path.abspath(local_dir)):
            note_dir = os.path.abspath(local_dir)
        elif valid_images:
            note_dir = os.path.dirname(os.path.abspath(valid_images[0]))

        # 查找视频文件
        local_video = note.get('local_video', '') or ''
        if local_video:
            abs_video = os.path.abspath(local_video)
            local_video = abs_video if os.path.exists(abs_video) else ""

        if not local_video and note_dir:
            video_path = os.path.join(note_dir, 'video.mp4')
            if os.path.exists(video_path):
                local_video = video_path

        if not local_video:
            batch_dir = note.get('batch_dir', '')
            idx = None
            try:
                selected = self.result_tree.selection()
                if selected:
                    item = self.result_tree.item(selected[0])
                    idx = int(item['values'][0])
            except Exception:
                pass
            if batch_dir and idx:
                abs_batch = os.path.abspath(batch_dir)
                videos = glob.glob(f"{abs_batch}/note_{idx}_*/video.mp4")
                if videos:
                    local_video = os.path.abspath(videos[0])
                    if not note_dir:
                        note_dir = os.path.dirname(local_video)

        self.current_video_path = local_video if local_video and os.path.exists(local_video) else None

        # 评论图片：始终从 note_dir/comments 读取（视频笔记也可能有评论图）
        comment_images = []
        if note_dir:
            comments_dir = os.path.join(note_dir, 'comments')
            if os.path.isdir(comments_dir):
                comment_images = [
                    os.path.abspath(f) for f in glob.glob(os.path.join(comments_dir, '*.*'))
                    if f.lower().endswith(('.jpg', '.jpeg', '.png', '.webp'))
                ]
        if not comment_images:
            batch_dir = note.get('batch_dir', '')
            try:
                selected = self.result_tree.selection()
                idx = int(self.result_tree.item(selected[0])['values'][0]) if selected else None
            except Exception:
                idx = None
            if batch_dir and idx:
                abs_batch = os.path.abspath(batch_dir)
                comment_images = [
                    os.path.abspath(f) for f in glob.glob(f"{abs_batch}/note_{idx}_*/comments/*.*")
                    if f.lower().endswith(('.jpg', '.jpeg', '.png', '.webp'))
                ]

        self.preview_comment_images = comment_images

        try:
            if hasattr(self, 'preview_hint_label'):
                if comment_images:
                    self.preview_hint_label.configure(
                        text=f"含 {len(comment_images)} 张评论图（蓝框）· 点击可打开")
                else:
                    self.preview_hint_label.configure(
                        text="蓝框 = 评论图片 · 点击缩略图可打开")
        except Exception:
            pass

        if not valid_images and not self.current_video_path and not comment_images:
            self.preview_canvas.delete("all")
            self.preview_canvas.create_text(200, 90, text="暂无本地媒体", fill="#888")
            self.preview_page_label.configure(text="")
            self.preview_image_paths = []
            return

        self.preview_image_paths = valid_images
        self.preview_page = 0
        self._render_preview_page()
    
    def _build_preview_slots(self):
        """把视频/笔记图/评论图统一成有序槽位列表，供网格分页与点击命中。

        每个槽位: (kind, path, click_tag)。click_tag 与 _on_preview_click_with_video
        约定一致：video_thumb / img_{全局索引} / comment_img_{索引}。
        """
        slots = []
        if self.current_video_path:
            slots.append(('video', self.current_video_path, 'video_thumb'))
        for i, p in enumerate(self.preview_image_paths):
            slots.append(('image', p, f'img_{i}'))
        for i, p in enumerate(getattr(self, 'preview_comment_images', [])):
            slots.append(('comment', p, f'comment_img_{i}'))
        return slots

    def _render_preview_page(self):
        """渲染当前预览页——自适应网格铺满画布，多行多列显示。"""
        self.preview_canvas.delete("all")
        self.preview_images = []

        slots = self._build_preview_slots()
        total_imgs = len(self.preview_image_paths)
        has_video = self.current_video_path is not None
        comment_count = len(getattr(self, 'preview_comment_images', []))

        if not slots:
            self.preview_page_label.configure(text="")
            cw = max(self.preview_canvas.winfo_width(), 200)
            self.preview_canvas.create_text(cw // 2, 90, text="暂无媒体文件", fill="#888")
            return

        canvas_w = self.preview_canvas.winfo_width()
        canvas_h = self.preview_canvas.winfo_height()
        cols, rows, cell_w, cell_h = self._preview_grid(canvas_w, canvas_h)
        self._preview_last_grid = (cols, rows)
        ipp = max(1, cols * rows)

        max_page = max(1, (len(slots) + ipp - 1) // ipp)
        self.preview_page = max(0, min(self.preview_page, max_page - 1))
        page_slots = slots[self.preview_page * ipp:(self.preview_page + 1) * ipp]

        # 分页标签
        media_info = f"{total_imgs}张图片"
        if has_video:
            media_info += " + 视频"
        if comment_count > 0:
            media_info += f" + {comment_count}张评论图"
        self.preview_page_label.configure(text=f"第{self.preview_page + 1}/{max_page}页 ({media_info})")

        try:
            from PIL import Image, ImageTk, ImageDraw
            gap, pad = self.PREVIEW_GAP, self.PREVIEW_PAD
            cw_i, ch_i = int(cell_w), int(cell_h)
            inner = max(24, min(cw_i, ch_i) - 8)  # 缩略图最大边长（留边）

            for k, (kind, path, tag) in enumerate(page_slots):
                r, c = divmod(k, cols)
                cell_x = pad + c * (cell_w + gap)
                cell_y = pad + r * (cell_h + gap)
                try:
                    if kind == 'video':
                        thumb = Image.new('RGB', (inner, inner), color=(35, 35, 35))
                        draw = ImageDraw.Draw(thumb)
                        cx, cy = inner // 2, inner // 2 - 6
                        rr = max(14, inner // 7)
                        draw.polygon([(cx - rr//2, cy - rr), (cx - rr//2, cy + rr),
                                      (cx + rr, cy)], fill=(255, 255, 255))
                        draw.text((inner//2 - 20, inner - 22), "VIDEO", fill=(180, 180, 180))
                        photo = ImageTk.PhotoImage(thumb)
                    else:
                        img = Image.open(path)
                        if kind == 'comment':
                            img.thumbnail((inner - 6, inner - 6))
                            bordered = Image.new('RGB', (img.width + 6, img.height + 6),
                                                 color=(33, 150, 243))  # 蓝框标记评论图
                            bordered.paste(img, (3, 3))
                            img = bordered
                        else:
                            img.thumbnail((inner, inner))
                        photo = ImageTk.PhotoImage(img)

                    self.preview_images.append(photo)
                    # 缩略图在单元格内居中
                    px = cell_x + (cell_w - photo.width()) / 2
                    py = cell_y + (cell_h - photo.height()) / 2
                    self.preview_canvas.create_image(px, py, anchor="nw", image=photo,
                                                     tags=("preview_item", tag))
                except Exception:
                    continue

            self.preview_canvas.bind("<Button-1>", self._on_preview_click_with_video)
            if not self.preview_images:
                self.preview_canvas.create_text(canvas_w // 2 if canvas_w > 1 else 200,
                                                90, text="媒体加载失败", fill="#888")
        except ImportError:
            self.preview_canvas.create_text(200, 90, text="需要安装Pillow: pip install Pillow", fill="#888")
        except Exception as e:
            self.preview_canvas.create_text(200, 90, text=f"加载预览失败: {e}", fill="#888")
    
    def _on_preview_click(self, event):
        """点击预览图（旧绑定入口，统一走 tag 命中检测）"""
        self._on_preview_click_with_video(event)

    def _on_preview_click_with_video(self, event):
        """点击预览区：通过 Canvas tag 精确命中被点的元素。

        渲染时每个缩略图都带有全局索引 tag（img_{全局索引} /
        comment_img_{i} / video_thumb），因此无论分页、有无视频占位、
        缩略图尺寸如何变化，命中判定始终准确。
        （旧实现按 x//140 做坐标除法，而实际步长是 250，点 A 开 B。）
        """
        hit = self.preview_canvas.find_withtag('current')
        if not hit:
            return
        tags = self.preview_canvas.gettags(hit[0])

        for tag in tags:
            if tag == 'video_thumb':
                try:
                    abs_path = os.path.abspath(self.current_video_path)
                    if os.path.exists(abs_path):
                        os.startfile(abs_path)
                    else:
                        messagebox.showerror("错误", f"视频文件不存在: {abs_path}")
                except Exception as e:
                    messagebox.showerror("错误", f"无法播放视频: {e}")
                return
            if tag.startswith('comment_img_'):
                try:
                    idx = int(tag[len('comment_img_'):])
                    comment_images = getattr(self, 'preview_comment_images', [])
                    if 0 <= idx < len(comment_images):
                        os.startfile(os.path.abspath(comment_images[idx]))
                except (ValueError, OSError) as e:
                    self.log(f"打开评论图片失败: {e}", "WARNING")
                return
            if tag.startswith('img_'):
                try:
                    idx = int(tag[len('img_'):])
                except ValueError:
                    continue
                if 0 <= idx < len(self.preview_image_paths):
                    self._open_image_viewer(idx)
                return
    
    def _open_image_viewer(self, start_index=0):
        """打开图片查看器"""
        if not self.preview_image_paths:
            return
        
        from PIL import Image, ImageTk

        # 按首图长宽比计算窗口尺寸：小红书图多为 3:4 竖图，
        # 固定 900x700 横框会把竖图缩成中间一小条。
        # 所有坐标用 Tk 自身坐标系（winfo_*），与主窗口一致，
        # 不掺 ctypes 物理分辨率（逻辑/物理混用会让窗口跑出屏幕）。
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        CHROME_H = 110  # 顶部信息栏 + 底部按钮栏的额外高度
        try:
            with Image.open(self.preview_image_paths[start_index]) as _im:
                img_w, img_h = _im.size
        except Exception:
            img_w, img_h = 3, 4  # 打不开时按典型竖图比例
        fit = min((sw * 0.66) / img_w, (sh * 0.82 - CHROME_H) / img_h)
        view_w = max(480, min(int(img_w * fit) + 40, int(sw * 0.9)))
        view_h = max(560, min(int(img_h * fit) + CHROME_H, int(sh * 0.9)))

        # 居中于主窗口，再整体钳回屏内（主窗口贴边时不跑出屏幕）
        try:
            mx, my = self.root.winfo_x(), self.root.winfo_y()
            mw, mh = self.root.winfo_width(), self.root.winfo_height()
        except tk.TclError:
            mx = my = 0; mw, mh = sw, sh
        pos_x = max(0, min(mx + (mw - view_w) // 2, sw - view_w))
        pos_y = max(0, min(my + (mh - view_h) // 2, sh - view_h))

        # 创建查看器窗口
        viewer = tk.Toplevel(self.root)
        viewer.title("图片查看器")
        viewer.geometry(f"{view_w}x{view_h}+{pos_x}+{pos_y}")
        viewer.minsize(460, 520)
        viewer.transient(self.root)  # 保持在主窗口之上，随主窗口最小化
        viewer.configure(bg=C['viewer_bg'])

        # 当前图片索引
        current_index = [start_index]
        photo_ref = [None]  # 保持图片引用

        # 顶部信息栏
        info_frame = tk.Frame(viewer, bg=C['viewer_bg'])
        info_frame.pack(fill=tk.X, pady=SP_SM)

        info_label = tk.Label(info_frame, text="", fg=C['viewer_text'], bg=C['viewer_bg'],
                              font=UI_FONT(FS_SMALL))
        info_label.pack()

        # 图片显示区域
        canvas = tk.Canvas(viewer, bg=C['viewer_bg'], highlightthickness=0)
        canvas.pack(fill=tk.BOTH, expand=True, padx=SP_MD, pady=SP_XS)

        # 底部按钮栏
        btn_frame = tk.Frame(viewer, bg=C['viewer_bg'])
        btn_frame.pack(fill=tk.X, pady=SP_MD)
        
        def update_image():
            idx = current_index[0]
            if 0 <= idx < len(self.preview_image_paths):
                img_path = self.preview_image_paths[idx]
                try:
                    img = Image.open(img_path)

                    # 计算缩放尺寸（保持比例，适应窗口）。
                    # winfo 未布局时返回 1（真值），"or 默认值"永不生效，
                    # 曾导致首帧按 1px 渲染闪空白——必须显式判 <=1
                    canvas_w = canvas.winfo_width()
                    canvas_h = canvas.winfo_height()
                    if canvas_w <= 1:
                        canvas_w = view_w - 30
                    if canvas_h <= 1:
                        canvas_h = view_h - CHROME_H - 20
                    
                    img_w, img_h = img.size
                    # 允许适度放大（≤2x）填满画布：此前上限1.0，小图在
                    # 深色大窗口里只有中间一小块
                    ratio = min(canvas_w / img_w, canvas_h / img_h, 2.0)
                    new_w = max(1, int(img_w * ratio))
                    new_h = max(1, int(img_h * ratio))

                    if ratio != 1.0:
                        img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
                    
                    photo_ref[0] = ImageTk.PhotoImage(img)
                    
                    canvas.delete("all")
                    canvas.create_image(canvas_w // 2, canvas_h // 2, anchor="center", image=photo_ref[0])
                    
                    # 更新信息
                    filename = os.path.basename(img_path)
                    info_label.configure(text=f"{idx + 1} / {len(self.preview_image_paths)}  |  {filename}  |  {img_w}x{img_h}")
                    
                except Exception as e:
                    canvas.delete("all")
                    canvas.create_text(440, 275, text=f"加载失败: {e}", fill="white")
        
        def prev_image():
            if current_index[0] > 0:
                current_index[0] -= 1
                update_image()
        
        def next_image():
            if current_index[0] < len(self.preview_image_paths) - 1:
                current_index[0] += 1
                update_image()
        
        def open_in_explorer():
            if 0 <= current_index[0] < len(self.preview_image_paths):
                path = self.preview_image_paths[current_index[0]]
                folder = os.path.dirname(os.path.abspath(path))
                os.startfile(folder)
        
        # 按钮：深色底上用半透明灰块 + 浅字，白底描边按钮在这里会刺眼
        def dark_btn(text, command, side, padx):
            ctk.CTkButton(btn_frame, text=text, command=command, width=120, height=CTRL_H,
                          corner_radius=CTRL_RADIUS, font=UI_FONT(),
                          fg_color=C['viewer_btn'], hover_color=C['viewer_btn_h'],
                          text_color=C['viewer_text']).pack(side=side, padx=padx)

        dark_btn("← 上一张", prev_image, tk.LEFT, (SP_LG, SP_SM))
        dark_btn("打开文件夹", open_in_explorer, tk.LEFT, SP_SM)
        dark_btn("下一张 →", next_image, tk.LEFT, SP_SM)
        dark_btn("关闭", viewer.destroy, tk.RIGHT, (SP_SM, SP_LG))
        
        # 键盘绑定：ESC/Q/点击空白处 均可关闭（多一条退路更好退出）
        def _close_viewer(_e=None):
            try:
                viewer.destroy()
            except Exception:
                pass
        viewer.bind("<Left>", lambda e: prev_image())
        viewer.bind("<Right>", lambda e: next_image())
        viewer.bind("<Escape>", _close_viewer)
        viewer.bind("<q>", _close_viewer)
        viewer.bind("<space>", lambda e: next_image())
        canvas.bind("<Double-Button-1>", _close_viewer)  # 双击图片区退出
        viewer.protocol("WM_DELETE_WINDOW", _close_viewer)

        # 窗口大小变化时重新加载图片
        def on_resize(event):
            if event.widget == canvas:
                viewer.after(100, update_image)
        canvas.bind("<Configure>", on_resize)

        # 初始显示（窗口几何已在创建时按图片比例设定并钳制在屏内）
        viewer.after(50, update_image)
        # 强制把键盘焦点抢到查看器上，否则 ESC 会被发到主窗口、看似"退不出"
        viewer.transient(self.root)
        viewer.after(60, lambda: (viewer.lift(), viewer.focus_force()))
    
    def _view_current_media(self):
        """"查看大图"按钮：从当前页第一张图打开查看器。

        纯视频/纯评论图笔记不再静默无反应：视频→直接播放，
        评论图→打开第一张评论图。
        """
        if self.preview_image_paths:
            # 当前页第一个"笔记图片"槽位的全局索引
            slots = self._build_preview_slots()
            ipp = self._preview_items_per_page()
            page_slots = slots[self.preview_page * ipp:(self.preview_page + 1) * ipp]
            start_idx = 0
            for kind, _path, tag in page_slots:
                if kind == 'image':
                    try:
                        start_idx = int(tag[len('img_'):])
                    except ValueError:
                        start_idx = 0
                    break
            self._open_image_viewer(start_idx)
        elif self.current_video_path:
            self._play_video_file(self.current_video_path)
        elif getattr(self, 'preview_comment_images', []):
            try:
                os.startfile(os.path.abspath(self.preview_comment_images[0]))
            except OSError as e:
                messagebox.showerror("错误", f"无法打开评论图片: {e}")
        else:
            messagebox.showinfo("提示", "当前没有可查看的媒体")

    @staticmethod
    def _play_video_file(path: str):
        """用系统播放器打开本地视频文件"""
        abs_path = os.path.abspath(path)
        if os.path.exists(abs_path):
            try:
                os.startfile(abs_path)
            except OSError as e:
                messagebox.showerror("错误", f"无法播放视频: {e}")
        else:
            messagebox.showerror("错误", f"视频文件不存在: {abs_path}")
    
    def _on_result_double_click(self, event):
        """双击表格行：批次汇总→进入批次；笔记行→打开小红书式详情卡片"""
        batch_notes = getattr(self, 'batch_notes_data', [])
        batch_folder = getattr(self, 'current_batch_folder', None)

        if batch_notes and not batch_folder:
            # 全部批次视图，双击进入。按**行位置**从 displayed_notes 反查
            selected = self.result_tree.selection()
            if selected:
                row_pos = self.result_tree.index(selected[0])
                folders = getattr(self, 'displayed_notes', None) or batch_notes
                if 0 <= row_pos < len(folders):
                    folder = folders[row_pos]
                    folder_name = folder['name']
                    for val in self.crawl_batch_combo.cget('values'):
                        if self._batch_label_to_folder(val) == folder_name:
                            self.crawl_batch_var.set(val)
                            break
                    self._load_batch_images(folder_name)
        else:
            # 笔记视图：弹出仿小红书详情卡片
            note = getattr(self, 'current_selected_note', None)
            if note and not (note.get('folder_path') and 'note_id' not in note and 'title' not in note):
                self._open_note_card(note)
            else:
                self._open_current_note_card()

    def _open_current_note_card(self):
        """打开当前选中笔记的小红书式详情卡片"""
        note = getattr(self, 'current_selected_note', None)
        if not note:
            messagebox.showinfo("提示", "请先在表格中选择一条笔记")
            return
        # 批次汇总行不是笔记
        if note.get('folder_path') and not note.get('note_id') and not note.get('title') and not note.get('path'):
            messagebox.showinfo("提示", "请双击进入具体批次后再查看笔记详情")
            return
        self._open_note_card(note)

    def _parse_note_comments(self, note) -> list:
        """把笔记 comments 字段归一化为 list[dict]（兼容 JSON 字符串）"""
        comments = note.get('comments', []) if note else []
        if isinstance(comments, str):
            try:
                comments = json.loads(comments) if comments.strip() else []
            except (ValueError, TypeError):
                comments = []
        if not isinstance(comments, list):
            return []
        out = []
        for c in comments:
            if isinstance(c, dict):
                out.append(dict(c))
            elif c:
                out.append({'author': '匿名', 'content': str(c), 'images': [], 'local_images': []})
        return out

    def _collect_note_media(self, note) -> dict:
        """收集一条笔记的本地媒体：封面图、视频、评论图、笔记目录。"""
        import glob
        images, comment_images = [], []
        video = None
        note_dir = ""

        for key in ('local_dir', 'path'):
            d = note.get(key) or ''
            if d and os.path.isdir(os.path.abspath(d)):
                note_dir = os.path.abspath(d)
                break

        for p in (note.get('local_images') or note.get('images') or []):
            ap = os.path.abspath(p)
            if os.path.isfile(ap) and 'comments' not in ap.replace('\\', '/').split('/'):
                images.append(ap)
                if not note_dir:
                    note_dir = os.path.dirname(ap)

        if note_dir:
            for ext in ('*.jpg', '*.jpeg', '*.png', '*.webp'):
                for p in glob.glob(os.path.join(note_dir, ext)):
                    ap = os.path.abspath(p)
                    if ap not in images:
                        images.append(ap)

        for cand in (
            note.get('local_video'),
            *(note.get('videos') or []),
            os.path.join(note_dir, 'video.mp4') if note_dir else '',
        ):
            if cand and os.path.isfile(os.path.abspath(cand)):
                video = os.path.abspath(cand)
                if not note_dir:
                    note_dir = os.path.dirname(video)
                break

        cdir = os.path.join(note_dir, 'comments') if note_dir else ''
        disk_comment_imgs = []
        if cdir and os.path.isdir(cdir):
            disk_comment_imgs = sorted(
                os.path.abspath(f) for f in glob.glob(os.path.join(cdir, '*.*'))
                if f.lower().endswith(('.jpg', '.jpeg', '.png', '.webp'))
            )
            comment_images = list(disk_comment_imgs)

        comments = self._parse_note_comments(note)
        used = set()
        for c in comments:
            locs = []
            for p in (c.get('local_images') or []):
                ap = os.path.abspath(p)
                if os.path.isfile(ap):
                    locs.append(ap)
                    used.add(ap)
            # 历史数据无 local_images：按 has_image 顺序从磁盘评论图里贴 1 张
            if not locs and (c.get('has_image') or c.get('images')):
                for p in disk_comment_imgs:
                    if p not in used:
                        locs.append(p)
                        used.add(p)
                        break
            c['local_images'] = locs
            for p in locs:
                if p not in comment_images:
                    comment_images.append(p)
        for p in disk_comment_imgs:
            if p not in comment_images:
                comment_images.append(p)

        return {
            'images': images,
            'video': video,
            'comment_images': comment_images,
            'note_dir': note_dir,
            'comments': comments,
        }

    def _open_note_card(self, note: dict):
        """弹出仿小红书笔记详情卡片：左大图轮播 + 右作者/正文/评论（含评论图）。"""
        if not note:
            return
        try:
            from PIL import Image, ImageTk, ImageFilter, ImageEnhance, ImageDraw
        except ImportError:
            messagebox.showerror("错误", "需要 Pillow：pip install Pillow")
            return

        def _round_img(im, radius=14):
            """给 PIL 图片加圆角（返回带 alpha 的 RGBA）"""
            im = im.convert("RGBA")
            mask = Image.new("L", im.size, 0)
            ImageDraw.Draw(mask).rounded_rectangle(
                (0, 0, im.width - 1, im.height - 1), radius=radius, fill=255)
            im.putalpha(mask)
            return im

        old = getattr(self, '_note_card_win', None)
        if old is not None:
            try:
                old.destroy()
            except Exception:
                pass
            self._note_card_win = None

        media = self._collect_note_media(note)
        images = media['images']
        video = media['video']
        comments = media['comments']
        slots = []
        if video:
            slots.append(('video', video))
        for p in images:
            slots.append(('image', p))
        if not slots and media['comment_images']:
            for p in media['comment_images']:
                slots.append(('image', p))

        title = (note.get('title') or '无标题').strip()
        author = (note.get('author') or '未知作者').strip()
        content = (note.get('content') or '').strip()
        tags_val = note.get('tags', '')
        if isinstance(tags_val, str) and tags_val.startswith('['):
            try:
                tags_val = json.loads(tags_val)
            except (ValueError, TypeError):
                pass
        if isinstance(tags_val, list):
            tags_val = '  '.join(f'#{t}' for t in tags_val if t)
        elif tags_val:
            tags_val = '  '.join(
                f'#{t.strip()}' for t in str(tags_val).replace('、', ',').split(',') if t.strip())
        else:
            tags_val = ''

        likes = note.get('like_count', 0) or 0
        collects = note.get('collect_count', 0) or 0
        n_comments = note.get('comment_count', 0) or len(comments)
        pub = note.get('publish_time') or ''
        ipr = note.get('ip_region') or ''

        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        win_w = min(1180, int(sw * 0.88))
        win_h = min(760, int(sh * 0.88))
        try:
            mx, my = self.root.winfo_x(), self.root.winfo_y()
            mw, mh = self.root.winfo_width(), self.root.winfo_height()
            pos_x = max(0, min(mx + (mw - win_w) // 2, sw - win_w))
            pos_y = max(0, min(my + (mh - win_h) // 2, sh - win_h))
        except tk.TclError:
            pos_x, pos_y = 60, 40

        win = ctk.CTkToplevel(self.root)
        self._note_card_win = win
        win.title(f"笔记详情 · {title[:40]}")
        win.geometry(f"{win_w}x{win_h}+{pos_x}+{pos_y}")
        win.minsize(900, 560)
        # 深色底模拟小红书弹窗后的暗遮罩，中央浮一张一体白卡
        win.configure(fg_color="#161616")
        try:
            win.transient(self.root)
            win.grab_set()
        except Exception:
            pass

        def _close_card(_e=None):
            try:
                win.grab_release()
            except Exception:
                pass
            self._note_card_win = None
            try:
                win.destroy()
            except Exception:
                pass

        # 一体式圆角白卡：左媒体右信息无缝相接、四周对称留边。
        # 原先"内部标题栏 + 左右两张独立圆角卡 + 中缝"工具感重，
        # 小红书原版就是暗遮罩上一张单卡、卡内两分区。
        # 关闭入口 = 系统标题栏 ✕ + 媒体区左上角悬浮圆钮 + Esc。
        body = ctk.CTkFrame(win, fg_color=C['card'], corner_radius=16)
        body.pack(fill=tk.BOTH, expand=True, padx=26, pady=22)
        body.grid_columnconfigure(0, weight=5, uniform="card")
        body.grid_columnconfigure(1, weight=4, uniform="card")
        body.grid_rowconfigure(0, weight=1)

        # 左：媒体（图片用自身模糊放大版填充留白，而非黑边；
        # 悬浮圆钮 关闭/‹/› + 底部圆点指示）
        left = ctk.CTkFrame(body, fg_color=C['card'], corner_radius=0)
        left.grid(row=0, column=0, sticky="nsew", padx=(2, 0), pady=2)
        left.grid_propagate(False)
        # 画布底 = 窗口遮罩色：圆角磨掉的角落透出它，与卡片外无缝衔接
        canvas = tk.Canvas(left, bg="#161616", highlightthickness=0, bd=0)
        canvas.pack(fill=tk.BOTH, expand=True)
        idx_var = tk.IntVar(value=0)
        photo_hold = []  # 同时持有 bg + fg 的 PhotoImage 引用，防 GC
        MEDIA_R = 14  # 与外层卡片 16px 圆角对齐（内缩 2px 边距）

        def _round_left(im, radius=MEDIA_R):
            """把图片左上/左下两角磨圆，右侧贴着信息栏保持直角。

            tk.Canvas 无法被 CTkFrame 的圆角裁剪——画布方角会盖住卡片
            圆角、在左上/左下露出白色台阶。只能反过来让画布**内容**带
            圆角，缺口处透出与窗口遮罩同色的画布底。
            """
            mask = Image.new("L", im.size, 255)
            dr = ImageDraw.Draw(mask)
            h, d = im.height, radius * 2
            dr.rectangle((0, 0, radius, radius), fill=0)
            dr.pieslice((0, 0, d, d), 180, 270, fill=255)
            dr.rectangle((0, h - radius, radius, h), fill=0)
            dr.pieslice((0, h - d, d, h), 90, 180, fill=255)
            out = Image.new("RGBA", im.size, (0, 0, 0, 0))
            out.paste(im, (0, 0), mask)
            return out

        def show_slot(i=None):
            canvas.delete("all")
            photo_hold.clear()
            cw = canvas.winfo_width()
            ch = canvas.winfo_height()
            if cw <= 1:
                cw = 520
            if ch <= 1:
                ch = 640
            # 白色圆角底：无图/加载失败时兜底，有图时被模糊背景盖住
            backdrop = ImageTk.PhotoImage(
                _round_left(Image.new("RGB", (cw, ch), C['card'])))
            photo_hold.append(backdrop)
            canvas.create_image(cw // 2, ch // 2, image=backdrop)
            if not slots:
                canvas.create_text(cw // 2, ch // 2, text="暂无媒体",
                                   fill=C['text_faint'], font=UI_FONT(FS_TITLE))
                _sync_arrows(0)
                return
            if i is None:
                i = idx_var.get()
            i = max(0, min(i, len(slots) - 1))
            idx_var.set(i)
            kind, path = slots[i]
            src = path if kind == 'image' else (images[0] if images else None)
            try:
                if src and os.path.isfile(src):
                    base = Image.open(src).convert("RGB")
                    bw, bh = base.size
                    # 背景：放大到覆盖整块画布 → 居中裁剪 → 高斯模糊 + 压暗
                    scale = max(cw / bw, ch / bh)
                    bg = base.resize((max(1, int(bw * scale)), max(1, int(bh * scale))),
                                     Image.Resampling.LANCZOS)
                    lft = max(0, (bg.width - cw) // 2)
                    top = max(0, (bg.height - ch) // 2)
                    bg = bg.crop((lft, top, lft + cw, top + ch))
                    bg = bg.filter(ImageFilter.GaussianBlur(30))
                    bg = ImageEnhance.Brightness(bg).enhance(0.78)
                    bgph = ImageTk.PhotoImage(_round_left(bg))
                    photo_hold.append(bgph)
                    canvas.create_image(cw // 2, ch // 2, image=bgph)
                    # 前景：等比缩到 fit（留边），加圆角
                    fg = base.copy()
                    fg.thumbnail((cw - 48, ch - 64), Image.Resampling.LANCZOS)
                    fgph = ImageTk.PhotoImage(_round_img(fg, 14))
                    photo_hold.append(fgph)
                    canvas.create_image(cw // 2, ch // 2, image=fgph)
                else:
                    canvas.create_text(cw // 2, ch // 2, text="无封面",
                                       fill=C['text_faint'], font=UI_FONT(FS_TITLE))
            except Exception:
                canvas.create_text(cw // 2, ch // 2, text="图片加载失败",
                                   fill=C['text_faint'], font=UI_FONT(FS_SMALL))
            # 视频：中心半透明圆 + 播放三角
            if kind == 'video':
                r = 36
                canvas.create_oval(cw // 2 - r, ch // 2 - r, cw // 2 + r, ch // 2 + r,
                                   fill="#000000", outline="", stipple="gray50")
                canvas.create_polygon(cw // 2 - 11, ch // 2 - 17, cw // 2 - 11, ch // 2 + 17,
                                      cw // 2 + 19, ch // 2, fill="white")
            # 底部圆点指示（多图才显示；当前点用品牌色拉长）
            if len(slots) > 1:
                gap = 15
                x0 = cw // 2 - (len(slots) - 1) * gap // 2
                y = ch - 20
                for k in range(len(slots)):
                    x = x0 + k * gap
                    if k == i:
                        canvas.create_oval(x - 6, y - 3, x + 6, y + 3,
                                           fill=C['brand'], outline="")
                    else:
                        canvas.create_oval(x - 3, y - 3, x + 3, y + 3,
                                           fill="#FFFFFF", outline="#C9C9C9")
            _sync_arrows(i)

        def prev_slot():
            if slots:
                show_slot(idx_var.get() - 1)

        def next_slot():
            if slots:
                show_slot(idx_var.get() + 1)

        def on_canvas_click(_e=None):
            if not slots:
                return
            kind, path = slots[idx_var.get()]
            if kind == 'video' and path and os.path.isfile(path):
                try:
                    os.startfile(path)
                except OSError as ex:
                    messagebox.showerror("错误", f"无法播放: {ex}", parent=win)

        # 悬浮翻页箭头：直接绘制在 canvas 上。
        # 不用 CTkButton——它的圆角**四角永远填父容器底色**，place 到图片
        # 上就是一块 40px 白方板（旧观感生硬的根因），任何 tk 组件库都有
        # 此局限。改为带 alpha 的半透明白圆 + Lucide 图标库的 chevron
        # 矢量路径（ISC 许可），Pillow 4x 超采样抗锯齿，真悬浮在图上。
        AR_D = 44   # 圆钮直径
        AR_SS = 4   # 超采样倍数

        def _arrow_img(direction, style):
            fill_a = {'normal': 214, 'hover': 255, 'disabled': 92}[style]
            stroke = {'normal': '#3A3A3A', 'hover': C['brand'],
                      'disabled': '#B9B9B9'}[style]
            S = AR_D * AR_SS
            im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
            dr = ImageDraw.Draw(im)
            dr.ellipse((0, 0, S - 1, S - 1), fill=(255, 255, 255, fill_a))
            # Lucide chevron-left 折线 (15,18)-(9,12)-(15,6)，24 视窗
            pts = [(15.0, 18.0), (9.0, 12.0), (15.0, 6.0)]
            if direction == 'next':
                pts = [(24.0 - x, y) for x, y in pts]
            k = S / 24.0
            pts = [(x * k, y * k) for x, y in pts]
            w = max(2, round(2.2 * AR_SS))
            dr.line(pts, fill=stroke, width=w, joint="curve")
            r = w / 2 - 0.5
            for x, y in (pts[0], pts[-1]):  # 手动补圆头线帽（PIL line 无 linecap）
                dr.ellipse((x - r, y - r, x + r, y + r), fill=stroke)
            im = im.resize((AR_D, AR_D), Image.Resampling.LANCZOS)
            return ImageTk.PhotoImage(im)

        arrow_imgs = {(d, s): _arrow_img(d, s)
                      for d in ('prev', 'next') for s in ('normal', 'hover', 'disabled')}
        arrow_state = {'prev': 'normal', 'next': 'normal'}

        X_D = 36  # 关闭圆钮直径（小红书式：媒体图左上角深色半透明圆+白✕）

        def _x_img(style):
            fill_a = {'normal': 140, 'hover': 205}[style]
            S = X_D * AR_SS
            im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
            dr = ImageDraw.Draw(im)
            dr.ellipse((0, 0, S - 1, S - 1), fill=(20, 20, 20, fill_a))
            # Lucide x：两条对角线 (6,6)-(18,18) / (18,6)-(6,18)，24 视窗
            k = S / 24.0
            w = max(2, round(2.0 * AR_SS))
            r = w / 2 - 0.5
            for x1, y1, x2, y2 in ((6, 6, 18, 18), (18, 6, 6, 18)):
                dr.line((x1 * k, y1 * k, x2 * k, y2 * k), fill="#FFFFFF", width=w)
                for x, y in ((x1 * k, y1 * k), (x2 * k, y2 * k)):
                    dr.ellipse((x - r, y - r, x + r, y + r), fill="#FFFFFF")
            im = im.resize((X_D, X_D), Image.Resampling.LANCZOS)
            return ImageTk.PhotoImage(im)

        x_imgs = {s: _x_img(s) for s in ('normal', 'hover')}

        def _sync_arrows(i):
            """按当前页重画悬浮控件（show_slot 每次 delete all 后调用）。"""
            canvas.delete("nav")
            cw = canvas.winfo_width() or 520
            ch = canvas.winfo_height() or 640
            # 关闭钮常驻（单图也要能关）
            canvas.create_image(18 + X_D // 2, 18 + X_D // 2,
                                image=x_imgs['normal'], tags=("nav", "nav_close"))
            if len(slots) <= 1:
                return
            for d, x, enabled in (('prev', 24 + AR_D // 2, i > 0),
                                  ('next', cw - 24 - AR_D // 2, i < len(slots) - 1)):
                arrow_state[d] = 'normal' if enabled else 'disabled'
                canvas.create_image(x, ch // 2, image=arrow_imgs[(d, arrow_state[d])],
                                    tags=("nav", f"nav_{d}"))

        def _arrow_enter(d):
            if arrow_state[d] == 'normal':
                canvas.itemconfig(f"nav_{d}", image=arrow_imgs[(d, 'hover')])
                canvas.configure(cursor="hand2")

        def _arrow_leave(d):
            canvas.itemconfig(f"nav_{d}", image=arrow_imgs[(d, arrow_state[d])])
            canvas.configure(cursor="")

        def _arrow_click(d):
            if arrow_state[d] != 'disabled':
                (prev_slot if d == 'prev' else next_slot)()
            return "break"  # 阻断 canvas 全局点击（避免误触视频播放）

        for _d in ('prev', 'next'):
            canvas.tag_bind(f"nav_{_d}", "<Enter>", lambda e, d=_d: _arrow_enter(d))
            canvas.tag_bind(f"nav_{_d}", "<Leave>", lambda e, d=_d: _arrow_leave(d))
            canvas.tag_bind(f"nav_{_d}", "<Button-1>", lambda e, d=_d: _arrow_click(d))

        def _close_enter(_e=None):
            canvas.itemconfig("nav_close", image=x_imgs['hover'])
            canvas.configure(cursor="hand2")

        def _close_leave(_e=None):
            canvas.itemconfig("nav_close", image=x_imgs['normal'])
            canvas.configure(cursor="")

        canvas.tag_bind("nav_close", "<Enter>", _close_enter)
        canvas.tag_bind("nav_close", "<Leave>", _close_leave)
        # return "break" 阻断 canvas 全局点击，避免关闭时误触视频播放
        canvas.tag_bind("nav_close", "<Button-1>",
                        lambda e: (_close_card(), "break")[1])

        def _close_enter(_e=None):
            canvas.itemconfig("nav_close", image=x_imgs['hover'])
            canvas.configure(cursor="hand2")

        def _close_leave(_e=None):
            canvas.itemconfig("nav_close", image=x_imgs['normal'])
            canvas.configure(cursor="")

        canvas.tag_bind("nav_close", "<Enter>", _close_enter)
        canvas.tag_bind("nav_close", "<Leave>", _close_leave)
        # return "break" 阻断 canvas 全局点击，否则视频笔记会被误播放
        canvas.tag_bind("nav_close", "<Button-1>",
                        lambda e: (_close_card(), "break")[1])

        canvas.bind("<Button-1>", on_canvas_click)
        canvas.bind("<Configure>", lambda e: show_slot())
        # 键盘操作：←/→ 翻页，Esc 关闭
        win.bind("<Left>", lambda e: prev_slot())
        win.bind("<Right>", lambda e: next_slot())
        win.bind("<Escape>", lambda e: _close_card())

        # 右：信息 + 评论。顶部作者条固定，底部互动栏固定，中间评论可滚动
        # （transparent 融入一体白卡，不再自带圆角描边）
        right = ctk.CTkFrame(body, fg_color="transparent", corner_radius=0)
        right.grid(row=0, column=1, sticky="nsew", padx=(0, 2), pady=2)
        wrap_w = max(320, win_w // 2 - 80)

        # —— 顶部：作者条（头像 + 昵称 + 关注按钮），下带分隔线 ——
        author_row = ctk.CTkFrame(right, fg_color="transparent", height=56)
        author_row.pack(fill=tk.X, padx=SP_MD, pady=(SP_MD, SP_SM))
        author_row.pack_propagate(False)
        av_bg0, av_fg0 = (AVATAR_PALETTE[sum(ord(c) for c in (author or '作'))
                                         % len(AVATAR_PALETTE)])
        ctk.CTkLabel(author_row, text=(author[:1] if author else "作"),
                     width=40, height=40, corner_radius=20,
                     fg_color=av_bg0, text_color=av_fg0,
                     font=UI_FONT(FS_TITLE, bold=True)).pack(side=tk.LEFT, padx=(0, SP_SM))
        name_col = ctk.CTkFrame(author_row, fg_color="transparent")
        name_col.pack(side=tk.LEFT, fill=tk.X, expand=True, anchor="w")
        # 小红书作者条只有昵称一行（发布时间/属地在正文尾部，见 meta_row）
        ctk.CTkLabel(name_col, text=author, font=UI_FONT(FS_BASE, bold=True),
                     text_color=C['text'], anchor="w").pack(fill=tk.X)
        # 关注按钮：纯视觉对齐小红书（本地数据无法真正关注，点击提示）
        ctk.CTkButton(author_row, text="关注", width=64, height=30, corner_radius=15,
                      fg_color=C['brand'], hover_color=C['brand_hover'],
                      text_color=C['text_on_brand'], font=UI_FONT(FS_SMALL, bold=True),
                      command=lambda: messagebox.showinfo(
                          "提示", "本地离线数据，仅供浏览", parent=win)).pack(side=tk.RIGHT)
        ctk.CTkFrame(right, fg_color=C['border'], height=1).pack(fill=tk.X, padx=SP_MD)

        # 计算当前笔记在列表中的位置，供"上一条/下一条"翻页
        siblings = [n for n in (getattr(self, 'displayed_notes', None) or [])
                    if isinstance(n, dict) and n.get('note_id')]
        cur_id = note.get('note_id')
        cur_idx = next((k for k, n in enumerate(siblings)
                        if n.get('note_id') == cur_id), -1)

        def _open_sibling(delta):
            if cur_idx < 0:
                return
            j = cur_idx + delta
            if 0 <= j < len(siblings):
                self.current_selected_note = siblings[j]
                self._open_note_card(siblings[j])  # 会销毁当前卡片并重开

        # —— 底部：互动栏。左"上一条/下一条"翻页，右 点赞/收藏/评论 ——
        engage = ctk.CTkFrame(right, fg_color=C['card'], height=58)
        engage.pack(side=tk.BOTTOM, fill=tk.X)
        engage.pack_propagate(False)
        ctk.CTkFrame(right, fg_color=C['border'], height=1).pack(side=tk.BOTTOM, fill=tk.X)
        # 左：上一条 / 下一条（到头自动禁用；无兄弟笔记则整体隐藏）
        nav_l = ctk.CTkFrame(engage, fg_color="transparent")
        nav_l.pack(side=tk.LEFT, padx=(SP_MD, 0), pady=SP_SM)
        if cur_idx >= 0 and len(siblings) > 1:
            prev_btn = ctk.CTkButton(
                nav_l, text="‹ 上一条", width=88, height=34, corner_radius=17,
                command=lambda: _open_sibling(-1), font=UI_FONT(FS_SMALL),
                fg_color=C['card_alt'], hover_color=C['brand_soft'],
                text_color=C['text'], border_width=1, border_color=C['border'],
                state=("normal" if cur_idx > 0 else "disabled"))
            prev_btn.pack(side=tk.LEFT, padx=(0, SP_SM))
            next_btn = ctk.CTkButton(
                nav_l, text="下一条 ›", width=88, height=34, corner_radius=17,
                command=lambda: _open_sibling(1), font=UI_FONT(FS_SMALL, bold=True),
                fg_color=C['brand'], hover_color=C['brand_hover'],
                text_color=C['text_on_brand'],
                state=("normal" if cur_idx < len(siblings) - 1 else "disabled"))
            next_btn.pack(side=tk.LEFT)
            # 键盘：PageUp/PageDown 翻笔记（不占用图片轮播的 ←/→）
            win.bind("<Next>", lambda e: _open_sibling(1))
            win.bind("<Prior>", lambda e: _open_sibling(-1))
            # 位置提示
            ctk.CTkLabel(nav_l, text=f"{cur_idx + 1}/{len(siblings)}",
                         font=UI_FONT(FS_SMALL - 1), text_color=C['text_faint']).pack(
                side=tk.LEFT, padx=(SP_SM, 0))
        # 右：点赞/收藏/评论
        eng_right = ctk.CTkFrame(engage, fg_color="transparent")
        eng_right.pack(side=tk.RIGHT, padx=(0, SP_MD))
        for icon, num, col in (("♥", likes, C['brand']),
                               ("★", collects, C['warning']),
                               ("💬", n_comments, C['text_sub'])):
            cell = ctk.CTkFrame(eng_right, fg_color="transparent")
            cell.pack(side=tk.LEFT, padx=(SP_SM, 0))
            ctk.CTkLabel(cell, text=icon, font=UI_FONT(FS_TITLE),
                         text_color=col).pack(side=tk.LEFT, padx=(0, 3))
            ctk.CTkLabel(cell, text=self._fmt_count(num), font=UI_FONT(FS_SMALL),
                         text_color=C['text_sub']).pack(side=tk.LEFT)

        # —— 中间：可滚动内容（正文/标签/操作/评论）——
        scroll = ctk.CTkScrollableFrame(right, fg_color="transparent")
        scroll.pack(fill=tk.BOTH, expand=True, padx=SP_MD, pady=(SP_SM, 0))

        ctk.CTkLabel(scroll, text=title, font=UI_FONT(FS_TITLE, bold=True),
                     text_color=C['text'], anchor="w", justify="left",
                     wraplength=wrap_w).pack(fill=tk.X, pady=(0, SP_XS))
        if content:
            ctk.CTkLabel(scroll, text=content, font=UI_FONT(FS_SMALL),
                         text_color=C['text'], anchor="w", justify="left",
                         wraplength=wrap_w).pack(fill=tk.X, pady=(0, SP_SM))
        if tags_val:
            ctk.CTkLabel(scroll, text=tags_val, font=UI_FONT(FS_SMALL),
                         text_color=C['info'], anchor="w", justify="left",
                         wraplength=wrap_w).pack(fill=tk.X, pady=(0, SP_SM))

        # 发布时间/属地行（小红书正文尾部的"编辑于"形态），右侧挂本应用
        # 的工具入口——灰字链接 hover 变红，不再是三颗大按钮抢戏
        meta_row = ctk.CTkFrame(scroll, fg_color="transparent")
        meta_row.pack(fill=tk.X, pady=(SP_XS, SP_MD))
        stamp = "  ".join(x for x in (pub, ipr) if x)
        if stamp:
            ctk.CTkLabel(meta_row, text=stamp, font=UI_FONT(FS_SMALL - 1),
                         text_color=C['text_faint'], anchor="w").pack(side=tk.LEFT)

        # 注意 side=RIGHT 是右→左依次排布：间距必须加在**右**侧
        # （padx 左值只会把它推离更左的邻居，两个链接仍会贴死）
        def _tool_link(text, cmd, gap=SP_MD):
            lb = ctk.CTkLabel(meta_row, text=text, font=UI_FONT(FS_SMALL - 1),
                              text_color=C['text_sub'], cursor="hand2")
            lb.pack(side=tk.RIGHT, padx=(0, gap))
            lb.bind("<Button-1>", lambda e: cmd())
            lb.bind("<Enter>", lambda e: lb.configure(text_color=C['brand']))
            lb.bind("<Leave>", lambda e: lb.configure(text_color=C['text_sub']))
            return lb

        _tool_link("打开原文", self._open_note_link, gap=0)  # 最右，不留外边距
        _tool_link("打开文件夹", self._open_images_folder)
        if video:
            _tool_link("播放视频",
                       lambda p=video: os.startfile(p) if os.path.isfile(p) else None)

        ctk.CTkLabel(scroll, text=f"共 {n_comments} 条评论  ·  已抓取 {len(comments)} 条",
                     font=UI_FONT(FS_SMALL), text_color=C['text_sub'],
                     anchor="w").pack(fill=tk.X, pady=(SP_SM, SP_SM))
        ctk.CTkFrame(scroll, fg_color=C['border'], height=1).pack(fill=tk.X, pady=(0, SP_SM))

        comment_photos = []

        def rounded_thumb(path, max_side=100, radius=10):
            """圆角缩略图（替代原来生硬的2px蓝色描边）"""
            from PIL import ImageDraw
            im = Image.open(path).convert("RGB")
            im.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
            mask = Image.new("L", im.size, 0)
            ImageDraw.Draw(mask).rounded_rectangle(
                (0, 0, im.width - 1, im.height - 1), radius=radius, fill=255)
            out = Image.new("RGBA", im.size, (0, 0, 0, 0))
            out.paste(im, (0, 0), mask)
            return ImageTk.PhotoImage(out)

        def avatar_colors(name: str):
            return AVATAR_PALETTE[sum(ord(ch) for ch in (name or '匿'))
                                  % len(AVATAR_PALETTE)]

        if not comments:
            ctk.CTkLabel(
                scroll, text="暂无评论数据（爬取时请开启「获取热门评论」并重新爬取）",
                font=UI_FONT(FS_SMALL), text_color=C['text_faint'],
                anchor="w").pack(fill=tk.X)
        else:
            # 流式评论：彩色圆头像 + 内容列 + 细分隔线。
            # 原先每条一整块灰底卡片，几十条排下来沉闷且层级混乱
            for ci, c in enumerate(comments):
                row = ctk.CTkFrame(scroll, fg_color="transparent")
                row.pack(fill=tk.X, pady=(0, 2))
                c_author = c.get('author') or c.get('user') or '匿名'
                av_bg, av_fg = avatar_colors(c_author)
                ctk.CTkLabel(row, text=(c_author[:1] or '匿'),
                             width=32, height=32, corner_radius=16,
                             fg_color=av_bg, text_color=av_fg,
                             font=UI_FONT(FS_SMALL, bold=True)).pack(
                    side=tk.LEFT, anchor="n", pady=(2, 0))
                col = ctk.CTkFrame(row, fg_color="transparent")
                col.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(SP_SM, 0))

                # 昵称（灰、小）
                ctk.CTkLabel(col, text=c_author, font=UI_FONT(FS_SMALL),
                             text_color=C['text_sub'], anchor="w").pack(fill=tk.X)

                # 正文（黑）
                c_body = (c.get('content') or '').strip()
                if c_body:
                    ctk.CTkLabel(col, text=c_body, font=UI_FONT(FS_SMALL),
                                 text_color=C['text'], anchor="w", justify="left",
                                 wraplength=max(280, wrap_w - 60)).pack(
                        fill=tk.X, pady=(1, 0))

                # 评论配图（圆角）
                locs = list(c.get('local_images') or [])
                if locs:
                    img_row = ctk.CTkFrame(col, fg_color="transparent")
                    img_row.pack(fill=tk.X, pady=(SP_XS, 0))
                    for lp in locs[:6]:
                        try:
                            ph = rounded_thumb(lp)
                            comment_photos.append(ph)
                            lbl = ctk.CTkLabel(img_row, image=ph, text="")
                            lbl.image = ph
                            lbl.pack(side=tk.LEFT, padx=(0, SP_XS))
                            lbl.bind("<Button-1>",
                                     lambda e, p=lp: os.startfile(p) if os.path.isfile(p) else None)
                        except Exception:
                            continue

                # 底部一行：左 时间·地区，右 ♡赞数 + 回复（小红书式）
                foot = ctk.CTkFrame(col, fg_color="transparent")
                foot.pack(fill=tk.X, pady=(2, 0))
                meta_bits2 = "  ".join(
                    str(x) for x in (c.get('time'), c.get('ip')) if x)
                if meta_bits2:
                    ctk.CTkLabel(foot, text=meta_bits2, font=UI_FONT(FS_SMALL - 1),
                                 text_color=C['text_faint'], anchor="w").pack(side=tk.LEFT)
                ctk.CTkLabel(foot, text="回复", font=UI_FONT(FS_SMALL - 1),
                             text_color=C['text_faint']).pack(side=tk.RIGHT)
                likes_txt = self._fmt_count(c.get('likes', 0)) if c.get('likes') else ""
                ctk.CTkLabel(foot, text=f"♥ {likes_txt}".strip(),
                             font=UI_FONT(FS_SMALL - 1),
                             text_color=C['text_faint']).pack(side=tk.RIGHT, padx=(0, SP_MD))

                if ci < len(comments) - 1:
                    ctk.CTkFrame(scroll, fg_color=C['border'], height=1).pack(
                        fill=tk.X, pady=(SP_SM, SP_SM), padx=(40, 0))
                else:
                    ctk.CTkFrame(scroll, fg_color="transparent", height=SP_SM).pack(fill=tk.X)

        orphan = [p for p in media['comment_images']
                  if not any(p in (c.get('local_images') or []) for c in comments)]
        if orphan:
            ctk.CTkLabel(scroll, text=f"其它评论配图（{len(orphan)}）",
                         font=UI_FONT(FS_SMALL, bold=True),
                         text_color=C['text_sub'], anchor="w").pack(
                fill=tk.X, pady=(SP_SM, SP_XS))
            row = ctk.CTkFrame(scroll, fg_color="transparent")
            row.pack(fill=tk.X)
            for lp in orphan[:12]:
                try:
                    ph = rounded_thumb(lp, max_side=88)
                    comment_photos.append(ph)
                    lbl = ctk.CTkLabel(row, image=ph, text="")
                    lbl.image = ph
                    lbl.pack(side=tk.LEFT, padx=(0, SP_XS), pady=2)
                    lbl.bind("<Button-1>",
                             lambda e, p=lp: os.startfile(p) if os.path.isfile(p) else None)
                except Exception:
                    continue

        win._comment_photos = comment_photos

        # 加快评论区滚轮：CTk 默认每格只滚 delta/6 单位，偏慢。给滚动区
        # 及其全部子控件绑更大步长的处理器并 return "break"，抢在 CTk 的
        # bind_all 之前生效（内容是静态的，一次性递归绑定即可覆盖）。
        _pcanvas = getattr(scroll, '_parent_canvas', None)

        def _fast_wheel(event):
            # CTk 默认 delta/6（≈20单位/格）；这里 delta/2（≈60单位/格）约 3 倍
            if _pcanvas is not None and _pcanvas.yview() != (0.0, 1.0):
                _pcanvas.yview_scroll(int(-1 * (event.delta / 2)), "units")
            return "break"

        def _bind_wheel(widget):
            try:
                widget.bind("<MouseWheel>", _fast_wheel)
            except Exception:
                pass
            for ch in widget.winfo_children():
                _bind_wheel(ch)
        if _pcanvas is not None:
            _bind_wheel(scroll)
            _pcanvas.bind("<MouseWheel>", _fast_wheel)

        win.after(80, show_slot)
        win.protocol("WM_DELETE_WINDOW", _close_card)
        # 强制把键盘焦点抢到卡片上，确保 ESC 立即可退（否则焦点常留在
        # 主窗口，按 ESC 像"没反应"）。ESC 已绑定见上方 win.bind
        win.after(120, lambda: (win.lift(), win.focus_force()))
        win.bind("<q>", _close_card)  # 多一个退出键

    def _open_images_folder(self):
        """打开图片文件夹。

        四种视图的 current_selected_note 字段不同：当前爬取/历史有
        local_dir/local_images；批次明细是 {path, images, videos, ...}；
        批次汇总是 {folder_path, ...}。按优先级逐一取，全部兼容。
        （此前只认 local_images→keyword，批次视图会打开错误的根目录。）
        """
        note = self.current_selected_note
        if not note:
            return

        candidates = []
        if note.get('local_dir'):
            candidates.append(note['local_dir'])
        if note.get('path'):                      # 批次明细：笔记子目录
            candidates.append(note['path'])
        if note.get('folder_path'):               # 批次汇总：批次目录
            candidates.append(note['folder_path'])
        local_images = note.get('local_images') or []
        if local_images:
            candidates.append(os.path.dirname(local_images[0]))
        if note.get('keyword'):
            candidates.append(f"images/{note['keyword']}")

        for folder in candidates:
            abs_folder = os.path.abspath(folder)
            if os.path.isdir(abs_folder):
                os.startfile(abs_folder)
                return
        messagebox.showinfo("提示", "未找到本地图片文件夹")

    def _play_video(self):
        """播放视频（兼容批次明细的 videos 列表字段）"""
        note = self.current_selected_note
        if not note:
            return

        # 各视图的视频字段：local_video(当前/历史) / videos[0](批次明细)
        local_video = note.get('local_video') or ''
        if not local_video:
            videos = note.get('videos') or []
            if videos:
                local_video = videos[0]

        if local_video:
            abs_path = os.path.abspath(local_video)
            if os.path.exists(abs_path):
                try:
                    os.startfile(abs_path)
                except OSError as e:
                    messagebox.showerror("错误", f"无法播放视频: {e}")
            else:
                messagebox.showinfo("提示", f"视频文件不存在: {abs_path}")
        else:
            video_url = note.get('video_url', '')
            if video_url:
                import webbrowser
                webbrowser.open(video_url)
            else:
                messagebox.showinfo("提示", "该笔记没有视频")

    def _open_note_link(self):
        """打开笔记链接（无 note_link 时用 note_id 拼接）"""
        note = self.current_selected_note
        if not note:
            return

        link = note.get('note_link', '')
        if not link and note.get('note_id'):
            link = f"https://www.xiaohongshu.com/explore/{note['note_id']}"
        if link:
            import webbrowser
            webbrowser.open(link)
        else:
            messagebox.showinfo("提示", "没有笔记链接")
    
    def _clear_results(self):
        """清空当前结果"""
        # 爬取进行中禁止清空内存列表：工作线程正以递增 success 计数作为
        # 行号写表，清空后新行会以远大于列表长度的 index 插入，序号与
        # displayed_notes 长度错位，后续点选/删除按行反查越界
        if self.is_running and self.data_source_var.get() == "当前爬取":
            messagebox.showinfo("提示", "爬取进行中，请先停止再清空")
            return
        if self.data_source_var.get() == "当前爬取":
            self.all_notes_data = []

        for item in self.result_tree.get_children():
            self.result_tree.delete(item)
        self.result_count_label.configure(text="共 0 条记录")
        self._reset_result_stats()
        self.detail_text.configure(state=tk.NORMAL)
        self.detail_text.delete(1.0, tk.END)
        self.detail_text.configure(state=tk.DISABLED)
        self._reset_preview_state()
        self.current_selected_note = None
        # 重置所有后备序列，避免残留映射导致后续点选/删除错位
        self.displayed_notes = []
        self.filtered_notes = []
        self.batch_notes_data = []
        self.current_batch_folder = None

    def _delete_note_media(self, note):
        """删除单条笔记的本地媒体目录/文件，优先用 local_dir 精确定位"""
        import shutil
        local_dir = note.get('local_dir', '')
        if local_dir and os.path.isdir(os.path.abspath(local_dir)):
            try:
                shutil.rmtree(os.path.abspath(local_dir))
                return
            except OSError as e:
                self.log(f"删除目录失败 {local_dir}: {e}", "WARNING")
        # 回退：从已知图片路径推断所在文件夹。
        # 安全护栏：只删名字形如 note_* 的笔记级目录，绝不 rmtree 其父级
        # 批次目录——若 local_images 异常指向批次根，误删会连带几十条笔记
        local_images = note.get('local_images', [])
        if isinstance(local_images, str):
            local_images = [p.strip() for p in local_images.split('|') if p.strip()]
        for img_path in local_images:
            folder = os.path.dirname(img_path) if img_path else ''
            if folder and os.path.isdir(folder) and os.path.basename(folder).startswith('note_'):
                try:
                    shutil.rmtree(folder)
                    return
                except OSError:
                    pass
        local_video = note.get('local_video', '')
        if local_video and os.path.exists(local_video):
            try:
                os.remove(local_video)
            except OSError:
                pass

    def _delete_selected(self):
        """删除选中的记录（数据库行 + 本地媒体）"""
        selected = self.result_tree.selection()
        if not selected:
            messagebox.showinfo("提示", "请先选择要删除的记录")
            return

        # 批次视图下"选中项"是文件夹/批次笔记，不应走 DB 删除逻辑
        if self.current_batch_folder or (self.batch_notes_data and not self.filtered_notes):
            messagebox.showinfo("提示", "批次视图请使用上方【删除批次】按钮，或切换到"
                                        "\"历史数据库/当前爬取\"数据源后再删除单条")
            return

        count = len(selected)
        if not messagebox.askyesno("确认删除", f"确定要删除选中的 {count} 条记录吗？\n\n这将同时删除：\n• 数据库中的记录\n• 对应的本地图片/视频文件"):
            return

        # 关键：先按行位置从 displayed_notes 收集目标笔记，再统一删除。
        # 删行会改变 index()，必须在删任何行之前把目标全部取出，
        # 且用 displayed_notes（已含排序/筛选后的真实顺序）而非原始列表。
        notes_map = getattr(self, 'displayed_notes', None) or self.all_notes_data
        targets = []
        for item_id in selected:
            pos = self.result_tree.index(item_id)
            if 0 <= pos < len(notes_map):
                targets.append(notes_map[pos])

        deleted_count = 0
        for note in targets:
            note_id = note.get('note_id', '')
            note_link = note.get('note_link', '')
            if note_id or note_link:
                try:
                    conn = sqlite3.connect(self.config.db_path)
                    cursor = conn.cursor()
                    if note_id:
                        cursor.execute("DELETE FROM notes WHERE note_id = ?", (note_id,))
                    elif note_link:
                        cursor.execute("DELETE FROM notes WHERE note_link = ?", (note_link,))
                    conn.commit()
                    conn.close()
                except Exception as e:
                    self.log(f"数据库删除失败: {e}", "WARNING")
            self._delete_note_media(note)
            deleted_count += 1

        # 从各后备列表中按对象身份移除，再走唯一入口重渲染（保持映射同步）
        target_ids = {id(n) for n in targets}
        self.all_notes_data = [n for n in self.all_notes_data if id(n) not in target_ids]
        if self.data_source_var.get() == "历史数据库":
            # 历史模式重新查库最稳妥（DB 已删，local_dir 也随之失效）
            self._load_history_data()
        else:
            self.filtered_notes = [n for n in self.filtered_notes if id(n) not in target_ids] if self.filtered_notes else []
            # 筛选/排序视图下删除后应停留在该视图，而不是跳回全量列表
            self._refresh_table_with_notes(self.filtered_notes or self.all_notes_data)

        messagebox.showinfo("完成", f"已删除 {deleted_count} 条记录")
    
    def _export_results(self):
        """导出结果到Excel——导出的是**用户当前看到的表格内容**。

        此前只按 data_source_var 二选一取全量列表：批次视图下导出的是
        无关的内存数据、筛选/排序后仍导出全量，且列名走英文另一套 schema。
        现统一：displayed_notes（含筛选/排序/批次明细结果）+ 中文列头。
        """
        # 批次汇总视图的行是文件夹摘要，不是笔记，无法按笔记 schema 导出
        data = list(getattr(self, 'displayed_notes', []) or [])
        if data and 'note_id' not in data[0] and 'path' in data[0] and 'mtime' in data[0]:
            messagebox.showinfo(
                "提示", "当前是批次汇总视图（文件夹列表）。\n"
                       "请双击进入某个批次，或切换数据源后再导出。")
            return
        if not data:
            messagebox.showwarning("提示", "没有数据可导出")
            return
        try:
            filepath = filedialog.asksaveasfilename(
                defaultextension=".xlsx",
                filetypes=[("Excel文件", "*.xlsx")],
                initialfile=f"爬取结果_{int(time.time())}.xlsx"
            )
            if filepath:
                df = self._notes_to_export_df(data)
                df.to_excel(filepath, index=False)
                messagebox.showinfo("成功", f"已导出 {len(data)} 条到:\n{filepath}")
        except Exception as e:
            messagebox.showerror("错误", f"导出失败: {e}")
    
    def _check(self, parent, text, variable, **pack_kw):
        """统一勾选项。"""
        box = ctk.CTkCheckBox(parent, text=text, variable=variable, font=UI_FONT(),
                              checkbox_width=22, checkbox_height=22)
        box.pack(**{'side': tk.LEFT, **pack_kw})
        return box

    def _create_content_page(self, parent):
        """创建内容选项页面。

        快捷预设移到最上方：它是"一键设好下面所有开关"的入口，放在被它
        改写的选项之后不合逻辑。
        """
        # === 快捷预设 ===
        preset = self._card(parent, "快捷预设")
        preset_row = self._row(preset)
        for text, cmd in (("极速采集", self._preset_turbo), ("完整数据", self._preset_complete),
                          ("只下图片", self._preset_images), ("只下视频", self._preset_videos),
                          ("只要文本", self._preset_text)):
            self._btn(preset_row, text, cmd, width=120, padx=(0, SP_SM))

        # === 基础内容 ===
        basic = self._card(parent, "基础内容")
        row1 = self._row(basic, pady=(0, SP_SM))
        self.get_content_var = tk.BooleanVar(value=True)
        self._check(row1, "获取笔记正文内容", self.get_content_var, padx=(0, 26))
        self.get_tags_var = tk.BooleanVar(value=True)
        self._check(row1, "提取话题标签 (#xxx)", self.get_tags_var, padx=(0, 26))
        self.get_time_var = tk.BooleanVar(value=True)
        self._check(row1, "获取发布时间", self.get_time_var)

        row2 = self._row(basic)
        self.get_interactions_var = tk.BooleanVar(value=True)
        self._check(row2, "获取互动数据（点赞 / 收藏 / 评论数）", self.get_interactions_var)

        # === 图片视频 ===
        media = self._card(parent, "图片 / 视频")
        row3 = self._row(media)
        self.download_images_var = tk.BooleanVar(value=True)
        self._check(row3, "下载图片", self.download_images_var, padx=(0, 26))
        self.get_all_images_var = tk.BooleanVar(value=True)
        self._check(row3, "获取全部图片（切换轮播）", self.get_all_images_var, padx=(0, 26))
        self.download_videos_var = tk.BooleanVar(value=True)
        self._check(row3, "下载视频", self.download_videos_var)

        # === 评论 ===
        comment = self._card(parent, "评论爬取")
        row4 = self._row(comment)
        self.get_comments_var = tk.BooleanVar(value=True)
        self._check(row4, "获取热门评论", self.get_comments_var, padx=(0, 26))
        self._label(row4, "评论数量", padx=(0, SP_SM))
        self.comments_count_var = tk.StringVar(value="10")
        self._num_entry(row4, self.comments_count_var)

        # === 导出设置 ===
        export = self._card(parent, "导出设置")
        row5 = self._row(export)
        self._label(row5, "导出格式", padx=(0, SP_SM))
        self.export_format_var = tk.StringVar(value="xlsx")
        self._combo(row5, self.export_format_var, ["xlsx", "csv", "json"],
                    width=120, padx=(0, 26))
        self.export_db_var = tk.BooleanVar(value=True)
        self._check(row5, "同时保存到 SQLite 数据库", self.export_db_var)

    def _create_analysis_page(self, parent):
        """创建数据分析页面。

        仪表盘从"1px 方框 + 与标签同号的数字"改成真正的指标卡：数值用
        26 号加粗，说明用 13 号灰字，靠字号差建立层次，扫一眼就抓得到数。
        """
        # === 分析工具 ===
        tools = self._card(parent, "分析工具")
        row1 = self._row(tools)
        self._btn(row1, "刷新统计", self._refresh_dashboard_from_db, width=120, padx=(0, SP_SM))
        for text, cmd in (("生成统计图表", self._generate_charts),
                          ("生成词云", self._generate_wordcloud),
                          ("生成分析报告", self._generate_report),
                          ("合并所有数据", self._merge_data)):
            self._btn(row1, text, cmd, width=132, padx=(0, SP_SM))

        # 依赖缺失提示（可选依赖未装时按钮点了只弹框，先在此显式告知）
        missing = []
        if not HAS_MATPLOTLIB: missing.append("matplotlib(图表)")
        if not HAS_WORDCLOUD: missing.append("wordcloud+jieba(词云)")
        if not HAS_DOCX: missing.append("python-docx(报告)")
        if missing:
            warn = self._row(tools, pady=(SP_SM, 0))
            ctk.CTkLabel(warn, text="⚠  未安装：" + "、".join(missing) + "，相关功能不可用",
                         font=UI_FONT(FS_SMALL), text_color=C['warning'],
                         fg_color=C['warn_soft'], corner_radius=6, height=30,
                         padx=12).pack(side=tk.LEFT)

        # === 统计仪表盘 ===
        dashboard = self._card(parent, "统计仪表盘")
        stats_grid = ctk.CTkFrame(dashboard, fg_color="transparent")
        stats_grid.pack(fill=tk.X)

        self.dashboard_labels = {}
        stats_items = [
            ("total_notes", "总笔记", "0"),
            ("total_likes", "总点赞", "0"),
            ("avg_likes", "平均点赞", "0"),
            ("max_likes", "最高点赞", "0"),
            ("total_collects", "总收藏", "0"),
            ("total_comments", "总评论", "0"),
            ("image_notes", "图文笔记", "0"),
            ("video_notes", "视频笔记", "0"),
        ]
        for i, (key, label, default) in enumerate(stats_items):
            tile = ctk.CTkFrame(stats_grid, fg_color=C['card_alt'], corner_radius=CARD_RADIUS,
                                border_width=1, border_color=C['border'])
            tile.grid(row=i // 4, column=i % 4,
                      padx=(0 if i % 4 == 0 else SP_MD, 0),
                      pady=(0 if i < 4 else SP_MD, 0), sticky="nsew")
            self.dashboard_labels[key] = ctk.CTkLabel(
                tile, text=default, font=UI_FONT(FS_METRIC, bold=True),
                text_color=C['brand'], anchor="w")
            self.dashboard_labels[key].pack(anchor="w", padx=SP_LG, pady=(SP_MD + 4, 0))
            ctk.CTkLabel(tile, text=label, font=UI_FONT(FS_SMALL),
                         text_color=C['text_sub'], anchor="w").pack(
                anchor="w", padx=SP_LG, pady=(SP_XS, SP_MD + 4))

        for i in range(4):
            stats_grid.columnconfigure(i, weight=1, uniform="metric")

        # === 历史记录 ===
        history = self._card(parent, "历史记录", expand=True, pady=0)
        columns = ("时间", "关键词", "笔记数", "图片数", "文件")
        self.history_tree = ttk.Treeview(history, columns=columns, show="headings", height=8)

        widths = {"时间": 170, "关键词": 150, "笔记数": 100, "图片数": 100, "文件": 360}
        for col in columns:
            self.history_tree.heading(col, text=col)
            self.history_tree.column(col, width=widths[col],
                                     anchor="e" if col.endswith("数") else "w",
                                     stretch=(col == "文件"))

        scrollbar = ttk.Scrollbar(history, orient=tk.VERTICAL, command=self.history_tree.yview)
        self.history_tree.configure(yscrollcommand=scrollbar.set)

        self.history_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # 刷新历史 + 用数据库现有数据初始化仪表盘（此前恒为 0）
        self._refresh_history()
        self._refresh_dashboard_from_db()

    def _refresh_dashboard_from_db(self):
        """用数据库全部笔记刷新统计仪表盘"""
        records = self._load_notes_from_db()
        if not records:
            return
        try:
            df = pd.DataFrame(records)
            stats = DataAnalyzer.generate_stats(df)
            self._update_dashboard(stats)
        except Exception as e:
            self.log(f"刷新统计失败: {e}", "WARNING")

    def _create_settings_page(self, parent):
        """创建高级设置页面。"""
        # === Cookie 管理 ===
        cookie = self._card(parent, "Cookie 管理")
        row1 = self._row(cookie)
        self.save_cookies_var = tk.BooleanVar(value=True)
        self._check(row1, "登录后自动保存 Cookie", self.save_cookies_var, padx=(0, 26))
        # cookie_status_var 在主页创建（那里也要显示登录状态），此处复用
        ctk.CTkLabel(row1, textvariable=self.cookie_status_var, font=UI_FONT(FS_SMALL),
                     text_color=C['text_sub']).pack(side=tk.LEFT, padx=(0, SP_MD))
        clear_cookie = self._btn(row1, "清除Cookie", self._clear_cookies, width=104)
        clear_cookie.configure(text_color=C['danger'])

        self._check_cookie_status()

        # === 日志设置 ===
        log = self._card(parent, "日志设置")
        row2 = self._row(log)
        self.log_to_file_var = tk.BooleanVar(value=True)
        self._check(row2, "保存日志到文件", self.log_to_file_var, padx=(0, 26))
        self._btn(row2, "打开日志文件", self._open_log_file, width=116, padx=(0, SP_SM))
        clear_log = self._btn(row2, "清空日志", self._clear_log_file, width=96)
        clear_log.configure(text_color=C['danger'])

        # === 速度控制 ===
        speed = self._card(parent, "速度控制")
        row3 = self._row(speed)
        self._label(row3, "点击延迟(秒)", padx=(0, SP_SM))
        self.click_min_var = tk.StringVar(value="0.3")
        self._num_entry(row3, self.click_min_var, width=72, padx=(0, SP_XS))
        self._label(row3, "-", padx=(0, SP_XS))
        self.click_max_var = tk.StringVar(value="0.5")
        self._num_entry(row3, self.click_max_var, width=72, padx=(0, 26))

        self._label(row3, "滚动延迟(秒)", padx=(0, SP_SM))
        self.scroll_min_var = tk.StringVar(value="0.4")
        self._num_entry(row3, self.scroll_min_var, width=72, padx=(0, SP_XS))
        self._label(row3, "-", padx=(0, SP_XS))
        self.scroll_max_var = tk.StringVar(value="0.6")
        self._num_entry(row3, self.scroll_max_var, width=72)

        # === 反爬设置 ===
        anti = self._card(parent, "反爬虫设置")
        row4 = self._row(anti)
        self.random_delay_var = tk.BooleanVar(value=True)
        self._check(row4, "随机延迟（模拟人类行为）", self.random_delay_var, padx=(0, 26))
        self.random_scroll_var = tk.BooleanVar(value=True)
        self._check(row4, "随机滚动距离", self.random_scroll_var)

        # === 数据库设置 ===
        db = self._card(parent, "数据库设置")
        row5 = self._row(db)
        self._label(row5, "数据库路径", padx=(0, SP_SM))
        self.db_path_var = tk.StringVar(value="data/redbook.db")
        ctk.CTkEntry(row5, textvariable=self.db_path_var, width=440, height=CTRL_H,
                     font=UI_FONT()).pack(side=tk.LEFT, padx=(0, SP_SM))
        self._btn(row5, "浏览", self._browse_db_path, width=80)
        self._label(row5, "改动后需重启生效", color=C['text_faint'], size=FS_SMALL,
                    padx=(SP_MD, 0))

    # === 事件处理 ===
    def _on_mode_seg_change(self, label: str):
        """分段控件切换采集类型（中文标签 → 内部值）"""
        mode = self._CRAWL_LABEL_TO_TYPE.get(label, "keyword")
        self.crawl_type_var.set(mode)
        self._on_mode_change()

    def _on_speed_seg_change(self, label: str):
        """分段控件切换采集速度"""
        self.crawl_mode_var.set(self._CRAWL_LABEL_TO_MODE.get(label, "standard"))

    def _sync_mode_segs(self):
        """crawl_type / crawl_mode 变更后同步分段控件外观（恢复设置、预设时用）"""
        try:
            t = self.crawl_type_var.get()
            label = self._CRAWL_TYPE_TO_LABEL.get(t, "关键词搜索")
            self.crawl_type_label_var.set(label)
            if hasattr(self, "crawl_type_seg"):
                self.crawl_type_seg.set(label)
                self._paint_seg(self.crawl_type_seg, label)
        except Exception:
            pass
        try:
            m = self.crawl_mode_var.get()
            if m == "fast":
                m = "standard"
                self.crawl_mode_var.set(m)
            label = self._CRAWL_MODE_TO_LABEL.get(m, "标准模式（完整数据）")
            self.crawl_mode_label_var.set(label)
            if hasattr(self, "crawl_mode_seg"):
                self.crawl_mode_seg.set(label)
                self._paint_seg(self.crawl_mode_seg, label)
        except Exception:
            pass

    def _apply_mode_row_visibility(self):
        """按采集模式只显示相关输入行，隐藏无关行以压缩主页高度。"""
        mode = self.crawl_type_var.get()
        for row in (getattr(self, "_kw_row", None),
                    getattr(self, "_blogger_row", None),
                    getattr(self, "_hot_row", None)):
            if row is not None:
                try:
                    row.pack_forget()
                except Exception:
                    pass

        # 插在「最多笔记」行之前，保证顺序：模式 → 输入 → 数量/速度
        before = getattr(self, "_count_row", None)
        pack_kw = dict(fill=tk.X, pady=(0, SP_XS))
        if before is not None:
            pack_kw["before"] = before

        if mode == "keyword" and getattr(self, "_kw_row", None) is not None:
            self._kw_row.pack(**pack_kw)
            try:
                self.keyword_entry.configure(state=tk.NORMAL)
            except Exception:
                pass
        elif mode == "blogger" and getattr(self, "_blogger_row", None) is not None:
            self._blogger_row.pack(**pack_kw)
            try:
                self.blogger_entry.configure(state=tk.NORMAL)
            except Exception:
                pass
        elif mode == "hot" and getattr(self, "_hot_row", None) is not None:
            self._hot_row.pack(**pack_kw)
            try:
                self.hot_combo.configure(state="readonly")
            except Exception:
                pass

        try:
            if mode != "keyword":
                self.keyword_entry.configure(state=tk.DISABLED)
            if mode != "blogger":
                self.blogger_entry.configure(state=tk.DISABLED)
            if mode != "hot":
                self.hot_combo.configure(state=tk.DISABLED)
        except Exception:
            pass

    def _on_mode_change(self):
        """切换爬取模式：显隐对应输入行 + 启用状态"""
        self._apply_mode_row_visibility()
    
    def _check_cookie_status(self):
        """检查Cookie状态"""
        if self.cookie_mgr.exists():
            saved_time = self.cookie_mgr.get_saved_time()
            if saved_time and saved_time != '未知':
                try:
                    dt = datetime.fromisoformat(saved_time)
                    time_str = dt.strftime("%m-%d %H:%M")
                    self.cookie_status_var.set(f"[已保存] Cookie ({time_str})")
                except Exception:
                    self.cookie_status_var.set("[已保存] Cookie")
            else:
                self.cookie_status_var.set("[已保存] Cookie")
        else:
            self.cookie_status_var.set("[未保存] 未检测到Cookie")
    
    def _use_saved_cookies(self):
        """使用已保存的Cookie"""
        if self.cookie_mgr.exists():
            saved_time = self.cookie_mgr.get_saved_time()
            msg = "将在爬取时自动加载Cookie，可跳过登录"
            if saved_time and saved_time != '未知':
                msg += f"\n\n保存时间: {saved_time}"
            messagebox.showinfo("Cookie信息", msg)
        else:
            messagebox.showwarning("提示", "未找到保存的Cookie\n请先完成一次登录，系统会自动保存")
    
    def _clear_cookies(self):
        """清除已保存的Cookie"""
        if self.cookie_mgr.exists():
            if messagebox.askyesno("确认", "确定要清除已保存的Cookie吗？\n清除后下次需要重新登录"):
                self.cookie_mgr.clear()
                self._check_cookie_status()
                self.log("Cookie已清除", "INFO")
        else:
            messagebox.showinfo("提示", "没有保存的Cookie")
    
    # === 预设 ===
    def _preset_turbo(self):
        self.crawl_mode_var.set("turbo")
        self._sync_mode_segs()
        self.download_images_var.set(True)
        self.get_all_images_var.set(False)
        self.download_videos_var.set(False)
        self.get_content_var.set(False)
        self.get_comments_var.set(False)
        self.log("已应用极速采集预设", "SUCCESS")
    
    def _preset_complete(self):
        self.crawl_mode_var.set("standard")
        self._sync_mode_segs()
        self.download_images_var.set(True)
        self.get_all_images_var.set(True)
        self.download_videos_var.set(True)
        self.get_content_var.set(True)
        self.get_tags_var.set(True)
        self.get_comments_var.set(True)
        self.log("已应用完整数据预设", "SUCCESS")
    
    def _preset_images(self):
        self.download_images_var.set(True)
        self.get_all_images_var.set(True)
        self.download_videos_var.set(False)
        self.get_content_var.set(False)
        self.get_comments_var.set(False)
        self.log("已应用只下图片预设", "SUCCESS")
    
    def _preset_videos(self):
        self.download_images_var.set(False)
        self.download_videos_var.set(True)
        self.note_type_var.set("视频")
        self.log("已应用只下视频预设", "SUCCESS")
    
    def _preset_text(self):
        self.download_images_var.set(False)
        self.download_videos_var.set(False)
        self.get_content_var.set(True)
        self.get_tags_var.set(True)
        self.get_comments_var.set(True)
        self.log("已应用只要文本预设", "SUCCESS")
    
    # === 日志 ===
    def _ensure_log_panel_size(self):
        """兼容旧调用：主页已改为 grid 自动分配日志高度，无需再调 sash。"""
        return

    def log(self, message, level="INFO"):
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_queue.put((f"[{timestamp}] {message}\n", level))
        
        if getattr(self, "config", None) and self.config.log_to_file:
            self.file_logger.log(message, level)
    
    def _append_log_line(self, msg: str, level: str = "INFO"):
        """主线程写入日志框（consumer / 直接调用都走这里）。"""
        box = getattr(self, "log_text", None)
        if box is None:
            return
        try:
            # 优先写内部 tk.Text，避免 CTk 封装层 insert/tag 异常静默失败
            inner = getattr(self, "_log_inner", None) or getattr(box, "_textbox", None)
            tag = level if getattr(self, "_ctk_log_tags", False) else None
            if inner is not None:
                try:
                    inner.configure(state="normal")
                except Exception:
                    pass
                if tag:
                    try:
                        inner.insert(tk.END, msg, tag)
                    except Exception:
                        inner.insert(tk.END, msg)
                else:
                    inner.insert(tk.END, msg)
                inner.see(tk.END)
                try:
                    inner.configure(state="disabled")
                except Exception:
                    pass
            else:
                box.configure(state="normal")
                if tag:
                    box.insert(tk.END, msg, tag)
                else:
                    box.insert(tk.END, msg)
                box.see(tk.END)
                box.configure(state="disabled")
        except Exception:
            # 窗口销毁或控件未就绪时忽略，避免刷栈
            pass

    def _start_log_consumer(self):
        def consume():
            try:
                # 批量排空，避免高频 after 堆积
                n = 0
                while n < 200:
                    msg, level = self.log_queue.get_nowait()
                    self._append_log_line(msg, level)
                    n += 1
            except queue.Empty:
                pass
            try:
                self.root.after(80, consume)
            except Exception:
                pass
        try:
            self.root.after(80, consume)
        except Exception:
            pass
    
    def _safe_after(self, func):
        """从工作线程安全地把回调派发到主线程。

        窗口关闭/销毁后 root.after 会抛 RuntimeError/TclError
        （"main thread is not in main loop"）；此处统一吞掉，
        使"爬取中途关窗"不再刷栈。
        """
        try:
            self.root.after(0, func)
        except (tk.TclError, RuntimeError):
            pass

    def _update_ui(self, **kwargs):
        """线程安全的状态更新：非主线程调用时统一派发到主线程执行。

        tkinter 控件只能在主线程操作；爬取线程直接调用本方法曾是
        偶发 Tcl 错误的隐患，现在统一经 root.after(0, ...) 派发。
        """
        if threading.current_thread() is threading.main_thread():
            self._apply_ui_update(**kwargs)
        else:
            self._safe_after(lambda: self._apply_ui_update(**kwargs))

    def _apply_ui_update(self, **kwargs):
        if "status" in kwargs:
            self.status_var.set(kwargs["status"])
        if "notes" in kwargs:
            # 支持旧格式 "笔记: X" 和新格式纯数字
            val = kwargs["notes"]
            if isinstance(val, str) and ":" in val:
                val = val.split(":")[-1].strip()
            self.notes_var.set(str(val))
        if "images" in kwargs:
            val = kwargs["images"]
            if isinstance(val, str) and ":" in val:
                val = val.split(":")[-1].strip()
            self.images_var.set(str(val))
        if "videos" in kwargs:
            val = kwargs["videos"]
            if isinstance(val, str) and ":" in val:
                val = val.split(":")[-1].strip()
            self.videos_var.set(str(val))
        if "time" in kwargs:
            val = kwargs["time"]
            if isinstance(val, str) and ":" in val:
                val = val.split(":")[-1].strip()
            self.time_var.set(str(val))
        if "progress" in kwargs:
            # CTkProgressBar 取 0.0~1.0，而调用方全部按百分比传入
            pct = max(0.0, min(100.0, float(kwargs["progress"])))
            self.total_progress.set(pct / 100.0)
            self.progress_label.configure(text=f"{int(pct)}%")

    def _set_crawl_buttons(self, running: bool):
        """按运行态切换主操作按钮的可用性与配色。

        停止按钮只在爬取中才是红色实心；空闲时退回描边灰。原先它常驻
        纯红，静止界面上一个禁用按钮比主操作还抢眼。
        """
        self.start_btn.configure(state="disabled" if running else "normal")
        self.stop_btn.configure(state="normal" if running else "disabled")
        if running:
            self.stop_btn.configure(fg_color=C['danger'], hover_color=C['danger_hover'],
                                    text_color=C['text_on_brand'], border_width=0)
        else:
            self.stop_btn.configure(fg_color=C['card'], hover_color=C['brand_soft'],
                                    text_color=C['text'], border_width=1,
                                    border_color=C['border_strong'])


    def _update_dashboard(self, stats):
        for key, value in stats.items():
            if key in self.dashboard_labels:
                self.dashboard_labels[key].configure(text=str(int(value) if isinstance(value, float) else value))
    
    # === 爬取控制 ===
    def _start_crawl(self):
        if self.is_running:
            return
        
        # 检查输入
        crawl_type = self.crawl_type_var.get()
        if crawl_type == "keyword":
            # 空关键词表示爬取主页推荐
            pass
        elif crawl_type == "blogger":
            blogger_url = self.blogger_url_var.get().strip()
            if not blogger_url:
                messagebox.showwarning("提示", "请输入博主主页URL")
                return
        
        self._get_config()
        # 切回「搜索爬取」页，保证用户能看到运行日志
        try:
            self.notebook.select(0)
        except Exception:
            pass
        self._run_crawl()
    
    def _stop_crawl(self):
        self.should_stop = True
        # 立即禁用停止键防连点，并给出反馈——停止是协作式的，最坏要等
        # 当前笔记的 ~6 秒固定 sleep 走完，没有反馈用户会以为没点上
        try:
            self.stop_btn.configure(state="disabled")
        except Exception:
            pass
        self.log("正在停止...（等待当前笔记处理完毕）", "WARNING")
        self._update_ui(status="正在停止...")
        # update_idletasks 只刷新渲染，不重入事件回调（root.update 会）
        self.root.update_idletasks()
    
    def _restore_gui_settings(self):
        """从配置恢复GUI设置"""
        try:
            # 基础设置
            self.keyword_var.set(self.config.keyword or "")
            self.scroll_var.set(str(self.config.scroll_times))
            self.max_notes_var.set(str(self.config.max_notes))
            self.parallel_var.set(str(self.config.parallel_downloads))
            self.crawl_mode_var.set(self.config.crawl_mode)
            self.crawl_type_var.set(self.config.crawl_type)
            self.blogger_url_var.set(self.config.blogger_url or "")
            
            # 筛选条件
            self.min_likes_var.set(str(self.config.min_likes))
            self.max_likes_var.set(str(self.config.max_likes))
            self.note_type_var.set(self.config.note_type_filter)
            self.skip_existing_var.set(self.config.skip_existing)
            
            # 内容选项
            self.get_content_var.set(self.config.get_content)
            self.get_tags_var.set(self.config.get_tags)
            self.get_time_var.set(self.config.get_publish_time)
            self.get_interactions_var.set(self.config.get_interactions)
            self.download_images_var.set(self.config.download_images)
            self.get_all_images_var.set(self.config.get_all_images)
            self.download_videos_var.set(self.config.download_videos)
            self.get_comments_var.set(self.config.get_comments)
            self.comments_count_var.set(str(self.config.comments_count))
            
            # 导出选项
            self.export_format_var.set(self.config.export_format)
            self.export_db_var.set(self.config.export_to_db)

            # 高级设置（配套新增的持久化字段）
            self.save_cookies_var.set(self.config.save_cookies)
            self.log_to_file_var.set(self.config.log_to_file)
            self.click_min_var.set(str(self.config.click_delay[0]))
            self.click_max_var.set(str(self.config.click_delay[1]))
            self.scroll_min_var.set(str(self.config.scroll_delay[0]))
            self.scroll_max_var.set(str(self.config.scroll_delay[1]))
            self.db_path_var.set(self.config.db_path)

            # 兼容旧配置：fast 模式已并入 standard（引擎从未区分二者）
            if self.crawl_mode_var.get() == "fast":
                self.crawl_mode_var.set("standard")
            # 恢复 crawl_type 后必须手动联动控件状态：
            # 直接 set() 变量不会触发分段控件 command
            self._sync_mode_segs()
            self._on_mode_change()

            self.log("已恢复上次的设置", "SUCCESS")
        except Exception as e:
            self.log(f"恢复设置失败: {e}", "WARNING")
    
    @staticmethod
    def _safe_int(var, default):
        """从 tk 变量安全取整数；单个字段非法不影响其它字段"""
        try:
            return int(str(var.get()).strip() or default)
        except (ValueError, tk.TclError):
            return default

    @staticmethod
    def _safe_float(var, default):
        try:
            return float(str(var.get()).strip() or default)
        except (ValueError, tk.TclError):
            return default

    def _save_gui_settings(self):
        """保存GUI设置到配置。

        每个字段独立安全解析：此前整体包在 except:pass 里，
        任何一个输入框内容非法都会导致全部设置静默丢失。
        """
        self.config.keyword = self.keyword_var.get().strip()
        self.config.scroll_times = self._safe_int(self.scroll_var, 10)
        self.config.max_notes = self._safe_int(self.max_notes_var, 30)
        self.config.parallel_downloads = self._safe_int(self.parallel_var, 10)
        self.config.crawl_mode = self.crawl_mode_var.get()
        self.config.crawl_type = self.crawl_type_var.get()
        self.config.blogger_url = self.blogger_url_var.get().strip()

        # 筛选条件
        self.config.min_likes = self._safe_int(self.min_likes_var, 0)
        self.config.max_likes = self._safe_int(self.max_likes_var, 999999)
        self.config.note_type_filter = self.note_type_var.get()
        self.config.skip_existing = self.skip_existing_var.get()

        # 内容选项
        self.config.get_content = self.get_content_var.get()
        self.config.get_tags = self.get_tags_var.get()
        self.config.get_publish_time = self.get_time_var.get()
        self.config.get_interactions = self.get_interactions_var.get()
        self.config.download_images = self.download_images_var.get()
        self.config.get_all_images = self.get_all_images_var.get()
        self.config.download_videos = self.download_videos_var.get()
        self.config.get_comments = self.get_comments_var.get()
        self.config.comments_count = self._safe_int(self.comments_count_var, 20)

        # 导出选项
        self.config.export_format = self.export_format_var.get()
        self.config.export_to_db = self.export_db_var.get()

        # 高级设置（此前从不持久化，整页设置退出即丢）
        self.config.save_cookies = self.save_cookies_var.get()
        self.config.log_to_file = self.log_to_file_var.get()
        self.config.click_delay = (self._safe_float(self.click_min_var, 0.2),
                                   self._safe_float(self.click_max_var, 0.4))
        self.config.scroll_delay = (self._safe_float(self.scroll_min_var, 0.3),
                                    self._safe_float(self.scroll_max_var, 0.5))
        db_path = self.db_path_var.get().strip()
        if db_path:
            self.config.db_path = db_path
    
    def _get_config(self):
        """爬取启动前收集配置。

        与 _save_gui_settings 曾是两份 90% 重复、又各有遗漏的映射
        （新增设置项经常只改其一导致半失效），现在合并为单一来源。
        """
        self._save_gui_settings()
        self.downloader.max_workers = self.config.parallel_downloads
        # 每次爬取启动即持久化：此前配置只在正常点 X 关闭时保存，
        # 崩溃/强杀会丢失全部设置
        self.config.save_to_file()
    
    def _run_crawl(self):
        self.is_running = True
        self.should_stop = False
        self.all_notes_data = []
        
        # 清空表格UI
        for item in self.result_tree.get_children():
            self.result_tree.delete(item)
        self.result_count_label.configure(text="共 0 条记录")
        self._reset_result_stats()  # 三张统计卡同步清零，避免残留上轮数字

        # 清空预览区域（含评论图/页码，防 resize 重绘旧媒体）
        self._reset_preview_state()
        self.current_selected_note = None
        
        # 清空详情区域
        self.detail_text.configure(state=tk.NORMAL)
        self.detail_text.delete(1.0, tk.END)
        self.detail_text.configure(state=tk.DISABLED)
        
        # 清空批次数据与显示序列
        self.batch_notes_data = []
        self.current_batch_folder = None
        self.displayed_notes = []
        self.filtered_notes = []

        # 确保数据源是"当前爬取"（同步分段控件外观与批次控件禁用态）
        self.data_source_var.set("当前爬取")
        try:
            if hasattr(self, "data_source_seg"):
                self.data_source_seg.set("当前爬取")
                self._paint_seg(self.data_source_seg, "当前爬取")
        except Exception:
            pass
        self._update_batch_controls_state()

        self._set_crawl_buttons(running=True)

        thread = threading.Thread(target=self._crawl_thread, daemon=True)
        thread.start()
    
    @staticmethod
    def _build_search_url(keyword: str) -> str:
        """构造搜索页 URL。

        注意：这里是历史遗留的双重百分号编码（quote 两次，gb2312 一步对
        纯 ASCII 实为空操作）。线上搜索对此编码可正常返回结果，
        未经实测前请勿"顺手修正"为单次编码。
        """
        keyword_code = quote(quote(keyword.encode('utf-8')).encode('gb2312'))
        return f'https://www.xiaohongshu.com/search_result?keyword={keyword_code}&source=web_search_result_notes'

    @staticmethod
    def _is_note_detail_url(url: str) -> bool:
        """是否笔记详情（弹窗/独立页）：/explore/{noteId}，排除主页推荐 /explore"""
        if not url:
            return False
        return bool(re.search(r'/explore/[a-zA-Z0-9]{10,}', url))

    def _is_on_entry_list_page(self, page, base_url: str) -> bool:
        """当前是否仍在本轮爬取的「列表入口」页（搜索/博主/主页推荐）。

        关键词模式必须停在 search_result；history.back 过冲会退到登录前
        打开的主页 /explore，再继续爬就会变成主页推荐流——这是
        「关键词检索却一直爬主页」的根因。
        """
        try:
            url = page.url or ""
        except Exception:
            return False
        if not url or 'website-login' in url:
            return False
        if self._is_note_detail_url(url):
            return False

        base = base_url or ""
        if 'search_result' in base:
            # 必须在搜索结果页；仅有 /explore 主页不算
            if 'search_result' not in url:
                return False
            # 若入口带 keyword 参数，尽量校验仍是同一关键词（防跳到空搜）
            try:
                from urllib.parse import urlparse, parse_qs, unquote
                bq = parse_qs(urlparse(base).query)
                uq = parse_qs(urlparse(url).query)
                want = (bq.get('keyword') or [''])[0]
                got = (uq.get('keyword') or [''])[0]
                if want and got:
                    # 双重编码后 compare 用 unquote 两次尽量对齐
                    def _norm(k):
                        k = unquote(unquote(k))
                        return k
                    if _norm(want) and _norm(got) and _norm(want) != _norm(got):
                        return False
            except Exception:
                pass
            return True
        if 'user/profile' in base:
            return 'user/profile' in url
        # 主页推荐 / 热门
        if 'search_result' not in url and (
                '/explore' in url or url.rstrip('/').endswith('xiaohongshu.com')):
            return not self._is_note_detail_url(url)
        return False

    def _return_to_list_page(self, page, base_url: str, reason: str = "") -> bool:
        """从笔记详情回到列表；若 history.back 掉到主页/错页则强制重进入口。

        返回是否最终落在正确列表页。
        """
        if not base_url:
            return False
        try:
            url = page.url or ""
        except Exception:
            url = ""

        # 详情弹窗：先 back 一次
        if self._is_note_detail_url(url):
            try:
                page.run_js("history.back()")
                time.sleep(0.55)
            except Exception:
                try:
                    page.actions.key_down('Escape').key_up('Escape')
                    time.sleep(0.35)
                except Exception:
                    pass
            try:
                url = page.url or ""
            except Exception:
                url = ""
            # 仍卡在详情：再 back 一次或硬跳
            if self._is_note_detail_url(url):
                try:
                    page.run_js("history.back()")
                    time.sleep(0.45)
                except Exception:
                    pass

        if self._is_on_entry_list_page(page, base_url):
            return True

        # 过冲到主页 / 其它页：硬导航回入口（关键词场景关键）
        tip = reason or "页面已离开入口列表"
        try:
            cur = page.url or ""
        except Exception:
            cur = ""
        self.log(f"{tip}，重新进入列表页… (当前: {cur[:80]})", "WARNING")
        try:
            page.get(base_url)
            time.sleep(1.6)
            # 搜索页偶发登录遮罩
            if not self._check_login(page):
                try:
                    close_btn = page.ele('css:.close-icon, [class*="close"]', timeout=0.4)
                    if close_btn:
                        close_btn.click()
                        time.sleep(0.3)
                except Exception:
                    pass
            if self._is_on_entry_list_page(page, base_url):
                return True
            # 再试一次
            page.get(base_url)
            time.sleep(1.2)
            return self._is_on_entry_list_page(page, base_url)
        except Exception as e:
            self.log(f"重新进入列表页失败: {e}", "ERROR")
            return False

    def _crawl_thread(self):
        """爬取主线程（优化版，增强错误恢复）"""
        start_time = time.time()
        page = None
        total_notes = 0
        total_images = 0
        total_videos = 0
        error_count = 0
        MAX_ERRORS = 5  # 连续错误上限
        
        try:
            # 处理多关键词（空关键词表示爬取主页）
            # 仅关键词搜索才按逗号分多词循环；博主主页/热门榜单是单一入口，
            # 否则会用残留在关键词框里的旧值把同一页面重复爬多趟
            if self.config.crawl_type in ("hot", "blogger"):
                keywords = [""]
            else:
                keywords = [k.strip() for k in self.config.keyword.split(',') if k.strip()]
                if not keywords:
                    keywords = [""]  # 空字符串表示主页

            for kw_idx, keyword in enumerate(keywords):
                if self.should_stop:
                    self.log("用户停止爬取", "WARNING")
                    break
                
                if error_count >= MAX_ERRORS:
                    self.log(f"连续错误超过{MAX_ERRORS}次，停止爬取", "ERROR")
                    break
                
                display_keyword = keyword if keyword else "主页推荐"
                self.log(f"开始爬取 [{kw_idx+1}/{len(keywords)}]: {display_keyword}", "INFO")
                
                # 复用浏览器实例（保持登录状态）
                if page is None:
                    if self.browser_page is not None:
                        # 复用已有的浏览器；若实例已死（被手动关闭/崩溃）则自动重建
                        page = self.browser_page
                        self.log("复用已打开的浏览器", "INFO")
                        try:
                            page.get('https://www.xiaohongshu.com')
                            time.sleep(1.5)
                        except Exception as e:
                            self.log(f"浏览器实例已失效，重新启动 ({e})", "WARNING")
                            try:
                                page.quit()
                            except Exception:
                                pass
                            self.browser_page = None
                            page = None
                        else:
                            risk = self._check_risk_page(page)
                            if risk:
                                self.log(f"访问被小红书拦截：{risk}", "ERROR")
                                self.log("请更换网络环境（如切换 IP/关闭代理）后重试", "ERROR")
                                self.should_stop = True
                                break
                            if not self._check_login(page):
                                self.log("需要重新登录", "WARNING")
                                self._wait_for_login(page)
                                if self.should_stop:
                                    break
                            # 复用分支也必须同步 Cookie：上一轮结束时
                            # downloader.close() 已丢弃 Session 及其 Cookie
                            self._sync_browser_cookies(page)

                    if page is None:
                        # 首次启动浏览器（或复用失败后重建）
                        try:
                            user_data_dir = os.path.abspath("data/browser_profile")
                            os.makedirs(user_data_dir, exist_ok=True)

                            co = ChromiumOptions()
                            co.set_user_data_path(user_data_dir)
                            co.set_argument('--no-first-run')
                            co.set_argument('--no-default-browser-check')

                            page = ChromiumPage(co)
                            self.browser_page = page  # 保存实例以便复用
                            self.log("浏览器启动成功", "SUCCESS")
                        except Exception as e:
                            self.log(f"浏览器启动失败: {e}", "ERROR")
                            return

                        # 访问小红书并检查登录状态
                        page.get('https://www.xiaohongshu.com')
                        time.sleep(2)

                        # 若存在已保存的 Cookie 且当前未登录，先尝试注入恢复会话
                        if not self._check_login(page) and self.cookie_mgr.exists():
                            self.log("尝试使用已保存的 Cookie 恢复登录...", "INFO")
                            if self.cookie_mgr.load(page):
                                page.get('https://www.xiaohongshu.com')
                                time.sleep(1.5)

                        risk = self._check_risk_page(page)
                        if risk:
                            # 风控/IP 拦截：等待登录也没用，直接明确告知并停止
                            self.log(f"访问被小红书拦截：{risk}", "ERROR")
                            self.log("请更换网络环境（如切换 IP/关闭代理）后重试", "ERROR")
                            self.should_stop = True
                            break
                        if self._check_login(page):
                            self.log("登录状态有效", "SUCCESS")
                            # 获取Cookie传递给下载器
                            self._sync_browser_cookies(page)
                        else:
                            self.log("需要登录", "WARNING")
                            self._wait_for_login(page)
                            if self.should_stop:
                                break
                            # 登录后获取Cookie
                            self._sync_browser_cookies(page)
                
                if self.should_stop:
                    break
                
                try:
                    # 按爬取类型决定入口页面（此前引擎忽略 crawl_type，
                    # 博主主页/热门榜单只是摆设，现在真正接线）
                    crawl_type = self.config.crawl_type
                    if crawl_type == "blogger" and self.config.blogger_url:
                        target_url = self.config.blogger_url.strip()
                        self.log(f"访问博主主页...", "INFO")
                        self._update_ui(status="爬取博主主页")
                    elif crawl_type == "hot":
                        # 热门榜单 = 主页推荐流，忽略关键词框内容
                        target_url = 'https://www.xiaohongshu.com/explore'
                        self.log(f"访问主页推荐...", "INFO")
                        self._update_ui(status="爬取主页")
                    elif keyword:
                        target_url = self._build_search_url(keyword)
                        self.log(f"访问搜索页面...", "INFO")
                        self._update_ui(status=f"搜索: {keyword}")
                    else:
                        target_url = 'https://www.xiaohongshu.com/explore'
                        self.log(f"访问主页推荐...", "INFO")
                        self._update_ui(status="爬取主页")
                    
                    self._current_entry_url = target_url  # 供 _standard_crawl 恢复页面用
                    page.get(target_url)
                    time.sleep(1.5)

                    # 导航后也可能才触发风控（如 IP 风险），先明确判定再谈登录
                    risk = self._check_risk_page(page)
                    if risk:
                        self.log(f"访问被小红书拦截：{risk}", "ERROR")
                        self.log("请更换网络环境（如切换 IP/关闭代理）后重试", "ERROR")
                        self.should_stop = True
                        break

                    # 再次检查登录状态（搜索页可能弹出登录框）
                    if not self._check_login(page):
                        self.log("搜索页需要登录", "WARNING")
                        # 尝试关闭登录弹窗
                        try:
                            close_btn = page.ele('css:.close-icon, [class*="close"]', timeout=0.5)
                            if close_btn:
                                close_btn.click()
                                time.sleep(0.3)
                        except Exception:
                            pass
                        # 如果还是没登录，等待用户登录
                        if not self._check_login(page):
                            self._wait_for_login(page)
                            page.get(target_url)
                            time.sleep(1.5)

                    # 登录/风控恢复后常被踢回主页：关键词模式必须确认仍在 search_result
                    if not self._is_on_entry_list_page(page, target_url):
                        self.log("入口页被重定向，强制回到目标列表…", "WARNING")
                        try:
                            cur = page.url or ""
                        except Exception:
                            cur = ""
                        self.log(f"  当前URL: {cur[:100]}", "DEBUG")
                        page.get(target_url)
                        time.sleep(1.8)
                        if not self._is_on_entry_list_page(page, target_url):
                            self.log(
                                "无法停留在目标列表页（可能被风控跳到主页），本关键词跳过",
                                "ERROR")
                            error_count += 1
                            continue
                    
                    # 自动滚动加载笔记（直到达到目标数量或无法加载更多）
                    prev_count = 0
                    no_change_count = 0
                    target_notes = self.config.max_notes
                    scroll_count = 0
                    max_scrolls = 100  # 最大滚动次数，防止无限循环
                    
                    self.log(f"自动加载笔记，目标: {target_notes} 个", "INFO")
                    
                    while scroll_count < max_scrolls:
                        if self.should_stop:
                            break
                        
                        scroll_count += 1
                        self._update_ui(status=f"加载中...")
                        
                        # 多种滚动方式组合
                        try:
                            # 方式1: 滚动到最后一个笔记
                            notes = page.eles("css:section.note-item")
                            if notes:
                                notes[-1].scroll.to_see()
                                time.sleep(0.3)
                            
                            # 方式2: 滚动整个页面
                            page.run_js("window.scrollBy(0, window.innerHeight)")
                            time.sleep(0.3)
                            
                            # 方式3: 滚动到页面底部
                            page.run_js("window.scrollTo(0, document.body.scrollHeight)")
                        except Exception:
                            page.scroll.to_bottom()
                        
                        # 等待内容加载
                        time.sleep(random.uniform(0.6, 1.0))
                        
                        # 检测当前笔记数量
                        curr_count = len(page.eles("css:section.note-item", timeout=0.5))
                        
                        if curr_count >= target_notes:
                            self.log(f"已加载足够笔记 ({curr_count}/{target_notes})", "SUCCESS")
                            break
                        
                        if curr_count == prev_count:
                            no_change_count += 1
                            if no_change_count >= 5:
                                self.log(f"加载完成，共 {curr_count} 个笔记 (页面无更多内容)", "INFO")
                                break
                        else:
                            no_change_count = 0
                            if scroll_count % 5 == 0:  # 每5次滚动输出一次进度
                                self.log(f"已加载 {curr_count} 个笔记...", "INFO")
                        
                        prev_count = curr_count
                    
                    if self.should_stop:
                        break
                    
                    # 回到顶部，确保排序从第一个笔记开始
                    page.scroll.to_top()
                    time.sleep(0.3)
                    
                    # 获取笔记列表
                    note_elements = page.eles("css:section.note-item")[:self.config.max_notes]
                    note_count = len(note_elements)
                    
                    if note_count == 0:
                        self.log(f"未找到笔记，跳过关键词: {keyword}", "WARNING")
                        error_count += 1
                        continue
                    
                    self.log(f"找到 {note_count} 个笔记", "SUCCESS")
                    error_count = 0  # 重置错误计数
                    
                    # 根据模式选择爬取方法
                    if self.config.crawl_mode == "turbo":
                        notes, imgs, vids = self._fast_crawl(page, note_elements, keyword, start_time)
                    else:
                        notes, imgs, vids = self._standard_crawl(page, note_elements, keyword, start_time)
                    
                    total_notes += notes
                    total_images += imgs
                    total_videos += vids
                    
                except Exception as e:
                    self.log(f"爬取关键词 '{keyword}' 时出错: {e}", "ERROR")
                    error_count += 1
                    continue
            
            # 保存数据
            if self.all_notes_data:
                try:
                    save_name = keywords[0] if keywords[0] else "主页推荐"
                    if len(keywords) > 1:
                        save_name = "多关键词"
                    filename = self._save_data(self.all_notes_data, save_name)
                    self.log(f"数据已保存: {filename}", "SUCCESS")
                    
                    # 更新仪表盘
                    df = pd.DataFrame(self.all_notes_data)
                    stats = DataAnalyzer.generate_stats(df)
                    self._safe_after(lambda s=stats: self._update_dashboard(s))
                except Exception as e:
                    self.log(f"保存数据失败: {e}", "ERROR")
            
            # 保存Cookie
            if page and self.config.save_cookies:
                try:
                    if self.cookie_mgr.save(page):
                        self.log("Cookie已保存，下次可自动登录", "SUCCESS")
                        self._safe_after(self._check_cookie_status)
                except Exception:
                    pass
            
            elapsed = int(time.time() - start_time)
            status = "已停止" if self.should_stop else "完成"
            self._update_ui(
                status=status,
                notes=f"笔记: {total_notes}",
                images=f"图片: {total_images}",
                videos=f"视频: {total_videos}",
                time=f"用时: {elapsed}秒",
                progress=100
            )
            
            # 显示下载统计
            dl_stats = self.downloader.get_stats()
            if dl_stats['success'] > 0:
                mb = dl_stats['bytes'] / (1024 * 1024)
                self.log(f"下载统计: 成功 {dl_stats['success']}, 失败 {dl_stats['failed']}, 总计 {mb:.1f}MB", "INFO")
            
            self.log(f"爬取{status}！笔记: {total_notes}, 图片: {total_images}, 视频: {total_videos}", "SUCCESS")
            self._safe_after(self._refresh_history)
            # 爬完刷新"爬取批次"下拉框，使新批次立即可选（此前需手动点刷新）
            self._safe_after(self._refresh_crawl_batches)
            
        except InterruptedError:
            self.log("爬取已取消", "WARNING")
        except Exception as e:
            self.log(f"严重错误: {str(e)}", "ERROR")
            import traceback
            self.file_logger.log(traceback.format_exc(), "ERROR")
        finally:
            # 不关闭浏览器，保持登录状态
            # 浏览器会在程序退出时关闭
            
            # 重置下载器状态
            self.downloader.close()
            self.downloader.reset_stats()
            
            self.is_running = False
            self._safe_after(lambda: self._set_crawl_buttons(running=False))

            # 爬完自动切到结果页——仅当用户还停留在主页（tab 0）且本轮
            # 真的有数据时才切，避免打断正在别的页操作的用户
            def _jump_to_results():
                try:
                    if (self.all_notes_data
                            and self.notebook.index(self.notebook.select()) == 0):
                        self.notebook.select(1)
                except Exception:
                    pass  # 窗口关闭中 / notebook 已销毁
            self._safe_after(_jump_to_results)
    
    def _sync_browser_cookies(self, page):
        """将浏览器Cookie同步到下载器"""
        try:
            cookies = page.cookies()
            if cookies:
                self.downloader.set_cookies(cookies)
                self.log(f"  已同步 {len(cookies)} 个Cookie到下载器", "INFO")
        except Exception as e:
            self.log(f"  同步Cookie失败: {e}", "WARNING")
    
    def _check_risk_page(self, page) -> str:
        """检测风控/错误页，返回可读原因（无则返回空串）。

        典型：IP 风险时服务器 302 到 website-login/error?error_code=300012
        &error_msg=IP存在风险…。此前这类页面被当成"未登录"，用户会
        永远卡在登录框，得不到真实原因。
        """
        try:
            url = page.url or ""
        except Exception:
            return ""
        # 仅匹配明确的登录错误页，避免误伤恰好带 error_code 参数的正常 URL
        if 'website-login/error' in url:
            from urllib.parse import urlparse, parse_qs, unquote
            try:
                qs = parse_qs(urlparse(url).query)
                msg = unquote(qs.get('error_msg', [''])[0])
                code = qs.get('error_code', [''])[0]
                return f"{msg}（error_code={code}）" if msg else f"访问被拦截（error_code={code}）"
            except Exception:
                return "访问被拦截（登录错误页）"
        return ""

    def _check_login(self, page) -> bool:
        """检查是否已登录（优先检测登录弹窗）"""
        try:
            # ===== 第0优先级：风控/错误页 =====
            # 命中则明确不算登录，由调用方据此给出可读提示而非死等登录
            if self._check_risk_page(page):
                return False

            # ===== 第一优先级：检查是否有登录弹窗（未登录标志）=====
            # 登录弹窗存在时，底层页面元素仍可能存在，所以必须先检查弹窗

            # 检查二维码登录弹窗
            qrcode = page.ele('xpath://img[contains(@src, "qrcode")]', timeout=0.3)
            if qrcode:
                return False
            
            # 检查"登录后查看搜索结果"按钮
            login_hint = page.ele('xpath://span[contains(text(), "登录后查看") or contains(text(), "扫码登录") or contains(text(), "手机号登录")]', timeout=0.3)
            if login_hint:
                return False
            
            # 检查登录弹窗的关闭按钮（登录弹窗特有的close-icon）
            close_icon = page.ele('css:.close-icon', timeout=0.2)
            if close_icon:
                # 如果有关闭按钮，检查附近是否有登录相关文字
                try:
                    parent = close_icon.parent()
                    if parent:
                        parent_text = parent.text or ""
                        if "登录" in parent_text or "扫码" in parent_text:
                            return False
                except Exception:
                    pass
            
            # 检查红色登录按钮
            login_btn = page.ele('css:.login-btn, button.login-btn', timeout=0.2)
            if login_btn:
                # 确认是侧边栏的登录按钮（未登录状态）
                btn_text = login_btn.text or ""
                if "登录" in btn_text:
                    return False
            
            # ===== 第二优先级：检查已登录标志 =====
            
            # 检查侧边栏"我"区域是否有用户主页链接
            user_profile = page.ele('css:.user.side-bar-component a[href*="/user/profile/"]', timeout=0.3)
            if user_profile:
                return True
            
            # 检查侧边栏是否有用户头像
            avatar = page.ele('css:.side-bar .reds-avatar', timeout=0.2)
            if avatar:
                return True
            
            # 检查侧边栏文本
            try:
                sidebar = page.ele('css:.side-bar', timeout=0.2)
                if sidebar:
                    text = sidebar.text or ""
                    # 已登录时有"发现、发布、通知、我"且没有"登录"按钮文字
                    if "我" in text and "发现" in text and "登录" not in text:
                        return True
                    # 未登录时有"登录"按钮
                    if "登录" in text:
                        return False
            except Exception:
                pass
            
            # 默认认为未登录（更安全，让用户确认）
            return False
            
        except Exception:
            return False
    
    def _wait_for_login(self, page):
        """等待登录"""
        self.log("请在浏览器中完成登录", "WARNING")
        self._update_ui(status="等待登录...")
        
        login_event = threading.Event()
        cancelled = [False]
        
        def show_dialog():
            result = messagebox.askokcancel(
                "等待登录",
                "请在浏览器中完成登录\n\n登录完成后点击【确定】\n点击【取消】停止爬取"
            )
            if not result:
                cancelled[0] = True
                self.should_stop = True
            login_event.set()

        try:
            self.root.after(0, show_dialog)
        except (tk.TclError, RuntimeError):
            # 窗口已关闭，无法弹登录框，视为取消
            self.should_stop = True
            return
        login_event.wait()
        
        if cancelled[0]:
            raise InterruptedError("用户取消")
        
        # 登录完成后立即保存Cookie
        if self.config.save_cookies:
            try:
                time.sleep(1)  # 等待Cookie完全写入
                if self.cookie_mgr.save(page):
                    self.log("Cookie已保存，下次可自动登录", "SUCCESS")
                    self._safe_after(self._check_cookie_status)
            except Exception as e:
                self.log(f"Cookie保存失败: {e}", "WARNING")
    
    def _get_sorted_note_indices(self, page) -> List[int]:
        """获取按位置排序的笔记索引（从上到下、从左到右）
        
        按行分组排序：
        1. 先按top排序
        2. 识别行（top差距<80px的视为同一行）
        3. 每行内按left排序
        """
        try:
            script = """
            return (() => {
                const notes = document.querySelectorAll('section.note-item');
                if (notes.length === 0) return [];
                
                const positions = [];
                notes.forEach((n, i) => {
                    const rect = n.getBoundingClientRect();
                    positions.push({
                        domIndex: i,
                        left: Math.round(rect.left),
                        top: Math.round(rect.top)
                    });
                });
                
                // 按行分组排序
                positions.sort((a, b) => a.top - b.top);
                
                const rows = [];
                let currentRow = [positions[0]];
                let rowTop = positions[0].top;
                
                for (let i = 1; i < positions.length; i++) {
                    if (positions[i].top - rowTop < 80) {
                        currentRow.push(positions[i]);
                    } else {
                        rows.push(currentRow);
                        currentRow = [positions[i]];
                        rowTop = positions[i].top;
                    }
                }
                rows.push(currentRow);
                
                // 每行按left排序，合并结果
                const result = [];
                rows.forEach(row => {
                    row.sort((a, b) => a.left - b.left);
                    row.forEach(p => result.push(p.domIndex));
                });
                
                return result;
            })()
            """
            result = page.run_js(script)
            if result and isinstance(result, list):
                self.log(f"[排序] 结果: {result[:10]}...", "DEBUG") if len(result) > 10 else None
                return result
        except Exception as e:
            self.log(f"[排序] 失败: {e}", "WARNING")
        # 失败时返回默认顺序
        return list(range(len(page.eles("css:section.note-item", timeout=0.5))))
    
    def _load_preexisting_ids(self) -> set:
        """去重开启时载入全库 note_id；关闭或失败返回空集（等价于不去重）。"""
        if not self.config.skip_existing:
            return set()
        try:
            ids = self.db_mgr.get_all_note_ids()
            if ids:
                self.log(f"去重已启用：数据库已有 {len(ids)} 条笔记，遇到重复将跳过", "INFO")
            return ids
        except Exception as e:
            self.log(f"加载去重清单失败，本轮不去重: {e}", "WARNING")
            return set()

    def _standard_crawl(self, page, note_elements, keyword: str, start_time: float) -> Tuple[int, int, int]:
        """标准模式爬取（按DOM顺序，稳定可靠）"""
        success = 0
        images = 0
        videos = 0
        from datetime import datetime
        timestamp = int(time.time())
        # 每次爬取创建独立文件夹（关键词_日期_时间）
        time_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        folder_name = keyword if keyword else "主页推荐"
        images_dir = f"images/{folder_name}_{time_str}"
        self.current_crawl_dir = images_dir  # 保存当前爬取目录
        consecutive_fails = 0
        MAX_CONSECUTIVE_FAILS = 3
        
        # 已爬取的笔记URL去重
        crawled_urls = set()
        # 每条笔记的尝试次数：允许瞬时失败（弹窗未加载/网络抖动）重试，
        # 达到上限才永久登记进 crawled_urls，避免"点一次失败即永久跳过"少爬
        note_attempts = {}
        MAX_NOTE_RETRY = 2

        # 跨运行去重：候选筛选阶段直接跳过库里已有的 note_id，
        # 省掉整套"点开详情→等加载→下载媒体"的 ~6 秒/条
        preexisting_ids = self._load_preexisting_ids()
        skipped_existing = 0

        # 保存页面URL用于恢复：优先使用本轮实际入口（含博主主页等类型）
        base_url = getattr(self, '_current_entry_url', None)
        if not base_url:
            if keyword:
                base_url = self._build_search_url(keyword)
            else:
                base_url = 'https://www.xiaohongshu.com/explore'
        
        # 按顺序爬取（每次从头遍历找未爬取的笔记，更稳定）
        target_notes = self.config.max_notes
        self.log(f"开始爬取，目标 {target_notes} 个笔记", "INFO")
        
        max_attempts = target_notes * 3  # 最大尝试次数
        attempt = 0
        
        while success < target_notes and attempt < max_attempts:
            if self.should_stop:
                break
            
            attempt += 1
            elapsed = int(time.time() - start_time)
            progress = (success / target_notes) * 100 if target_notes > 0 else 0
            self._update_ui(
                status=f"爬取 {success}/{target_notes}",
                notes=f"笔记: {success}",
                images=f"图片: {images}",
                videos=f"视频: {videos}",
                time=f"用时: {elapsed}秒",
                progress=progress
            )
            
            # 连续失败时重新加载入口列表（关键词=搜索页，禁止落在主页）
            if consecutive_fails >= MAX_CONSECUTIVE_FAILS:
                self.log("连续失败，重新加载列表页", "WARNING")
                if not self._return_to_list_page(page, base_url, "连续失败恢复"):
                    break
                try:
                    for _ in range(5):
                        page.scroll.to_bottom()
                        time.sleep(0.5)
                except Exception:
                    pass
                consecutive_fails = 0

            try:
                # 每轮先确保在入口列表页（防 history.back 退回主页后继续爬推荐流）
                if not self._is_on_entry_list_page(page, base_url):
                    if not self._return_to_list_page(page, base_url, "不在入口列表"):
                        consecutive_fails += 1
                        continue

                # 获取所有笔记元素
                elements = page.eles("css:section.note-item", timeout=1)
                if not elements:
                    self.log("未找到笔记元素，尝试滚动加载", "WARNING")
                    # 若其实在主页误当搜索，上面守卫应已拦；此处再确认一次
                    if not self._is_on_entry_list_page(page, base_url):
                        self._return_to_list_page(page, base_url, "无笔记且页面偏离")
                    page.scroll.to_bottom()
                    time.sleep(1)
                    consecutive_fails += 1
                    continue

                # 从头遍历，找到第一个未爬取的笔记
                found_note = False
                for i, elem in enumerate(elements):
                    # 获取封面链接
                    cover_link = elem.ele('css:a.cover', timeout=0.1)
                    if not cover_link:
                        continue  # 跳过没有封面的（推荐卡片）

                    # 检测推荐搜索卡片
                    if self._is_search_recommend_card(elem):
                        continue

                    # 获取笔记URL并提取笔记ID用于去重（去掉token等变化的参数）
                    note_href = cover_link.attr('href') or ""
                    # 提取笔记ID（/explore/id 或 /search_result/id）
                    note_id = ""
                    for marker in ('/explore/', '/search_result/'):
                        if marker in note_href:
                            try:
                                note_id = note_href.split(marker)[1].split('?')[0].split('/')[0]
                            except Exception:
                                note_id = note_href
                            break
                    if not note_id:
                        note_id = note_href

                    # 去重键：note_id 优先，退回 href，再退回位置
                    dedup_key = note_id or note_href or f"__pos_{i}"
                    if dedup_key in crawled_urls:
                        continue  # 已爬取过或已放弃

                    # 跨运行去重：库里已有则跳过（仅首次遇到时记日志，
                    # 之后每轮重扫列表都会再遇到，不能刷屏）
                    if note_id and note_id in preexisting_ids:
                        if dedup_key not in note_attempts:
                            note_attempts[dedup_key] = 0
                            skipped_existing += 1
                            self.log(f"  跳过已爬取: {note_id}", "DEBUG")
                        continue

                    # 找到了未爬取的笔记
                    found_note = True
                    note_attempts[dedup_key] = note_attempts.get(dedup_key, 0) + 1
                    give_up = note_attempts[dedup_key] >= MAX_NOTE_RETRY

                    # 获取卡片标题
                    try:
                        card_title = elem.ele('css:.title, .note-title', timeout=0.1)
                        card_title_text = (card_title.text if card_title else "")[:20]
                    except Exception:
                        card_title_text = ""

                    self.log(f"[{success+1}/{target_notes}] 位置{i+1}, 标题={card_title_text}", "INFO")

                    # 点击笔记打开弹窗（必须 a.cover）
                    elem.scroll.to_see()
                    time.sleep(0.1)
                    cover_link.click()

                    time.sleep(random.uniform(*self.config.click_delay))

                    # 等待弹窗内容加载
                    popup_loaded = False
                    for _ in range(10):
                        try:
                            if page.ele('css:.note-content, .note-text, .author-wrapper', timeout=0.1):
                                popup_loaded = True
                                break
                        except Exception:
                            pass
                        time.sleep(0.2)

                    # 额外等待互动数据和图片轮播加载
                    if popup_loaded:
                        for _ in range(5):
                            try:
                                if page.ele('css:.like-wrapper .count, .engage-bar .count', timeout=0.1):
                                    break
                            except Exception:
                                pass
                            time.sleep(0.2)

                        for _ in range(5):
                            try:
                                if page.ele('css:.swiper-slide img, .carousel img, [class*="slider"] img', timeout=0.2):
                                    break
                            except Exception:
                                pass
                            time.sleep(0.3)

                    # 检查是否无法浏览
                    try:
                        unavailable = page.ele('xpath://div[contains(text(), "暂时无法浏览")]', timeout=0.2)
                        if unavailable:
                            self.log("笔记无法浏览，跳过", "WARNING")
                            crawled_urls.add(dedup_key)
                            self._return_to_list_page(page, base_url, "笔记不可浏览后返回")
                            break
                    except Exception:
                        pass

                    # 确保URL已更新（验证当前笔记）
                    current_url = page.url or ""
                    if note_id and note_id not in current_url:
                        self.log("  URL未更新，等待跳转...", "DEBUG")
                        for _ in range(10):
                            time.sleep(0.3)
                            current_url = page.url or ""
                            if note_id in current_url:
                                break

                    # 提取数据
                    time.sleep(0.5)
                    note_data = self._extract_full_note(page, success, images_dir, timestamp, keyword)

                    # 应用主页面筛选条件
                    filtered_out = False
                    if note_data and not self._note_passes_filter(note_data):
                        self.log(f"  不满足筛选条件，跳过: {note_data.get('title','')[:20]}", "INFO")
                        note_data = None
                        filtered_out = True

                    if note_data and note_data.get('title'):
                        crawled_urls.add(dedup_key)
                        self.all_notes_data.append(note_data)
                        success += 1
                        images += note_data.get('image_count', 0)
                        videos += 1 if note_data.get('video_url') else 0
                        consecutive_fails = 0

                        self._safe_after(lambda d=note_data, n=success: self._add_result_to_table(d, n-1))

                        if self.config.export_to_db:
                            self.db_mgr.insert_note(note_data)

                        title = note_data.get('title', '')[:25]
                        likes = note_data.get('like_count', 0)
                        self.log(f"[{success}] {title}... ❤️{likes}", "SUCCESS")
                    elif filtered_out:
                        crawled_urls.add(dedup_key)
                    else:
                        consecutive_fails += 1
                        if give_up:
                            crawled_urls.add(dedup_key)
                            self.log("  提取失败已达重试上限，跳过", "WARNING")
                        else:
                            self.log("  提取失败，稍后重试", "DEBUG")

                    # 返回列表页（失败则硬跳搜索入口，避免落到主页）
                    self._return_to_list_page(page, base_url, "单条处理完毕返回")
                    break  # 处理一个笔记后退出内层，外层重新扫列表

                # 如果没找到未爬取的笔记，尝试滚动加载更多
                if not found_note:
                    # 再次确认仍在入口页
                    if not self._is_on_entry_list_page(page, base_url):
                        self._return_to_list_page(page, base_url, "加载更多前页面偏离")
                        continue

                    prev_count = len(elements)
                    self.log(f"当前页面 {prev_count} 个笔记已全部处理，尝试加载更多...", "INFO")

                    loaded_more = False
                    for scroll_try in range(3):
                        page.scroll.to_bottom()
                        time.sleep(1)
                        if not self._is_on_entry_list_page(page, base_url):
                            self._return_to_list_page(page, base_url, "滚动后页面偏离")
                            break
                        new_elements = page.eles("css:section.note-item", timeout=0.5)
                        if len(new_elements) > prev_count:
                            self.log(f"加载了 {len(new_elements) - prev_count} 个新笔记", "INFO")
                            loaded_more = True
                            break

                    if not loaded_more:
                        self.log(f"页面无法加载更多笔记，共爬取 {success} 个", "WARNING")
                        break

            except Exception as e:
                consecutive_fails += 1
                error_msg = str(e)[:50] if str(e) else "未知错误"
                self.log(f"爬取失败: {error_msg}", "ERROR")
                self._return_to_list_page(page, base_url, "异常后返回列表")

        done_msg = f"爬取完成：成功 {success} 个笔记"
        if skipped_existing:
            done_msg += f"（去重跳过 {skipped_existing} 条已有笔记）"
        self.log(done_msg, "SUCCESS")
        return success, images, videos

    def _fast_crawl(self, page, note_elements, keyword, start_time):
        """极速模式爬取"""
        from datetime import datetime
        records = []
        timestamp = int(time.time())
        # 每次爬取创建独立文件夹（关键词_日期_时间）
        time_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        folder_name = keyword if keyword else "主页推荐"
        images_dir = f"images/{folder_name}_{time_str}"
        self.current_crawl_dir = images_dir  # 保存当前爬取目录
        total = len(note_elements)

        download_tasks = []
        preexisting_ids = self._load_preexisting_ids()
        skipped_existing = 0

        for idx in range(total):
            if self.should_stop:
                break
            
            self._update_ui(
                status=f"扫描 {idx+1}/{total}",
                progress=(idx / total) * 50
            )
            
            try:
                elements = page.eles("css:section.note-item")
                if idx >= len(elements):
                    continue
                
                elem = elements[idx]
                
                title = ""
                try:
                    t = elem.ele('xpath:.//span[contains(@class, "title")]', timeout=0.2)
                    if t:
                        title = t.text or ""
                except:
                    pass
                
                if not title:
                    try:
                        lines = (elem.text or "").split('\n')
                        title = next((l for l in lines if 5 < len(l) < 100), f"笔记{idx+1}")
                    except:
                        title = f"笔记{idx+1}"
                
                author = ""
                try:
                    a = elem.ele('xpath:.//span[contains(@class, "name")]', timeout=0.2)
                    if a:
                        author = a.text or ""
                except:
                    pass
                
                img_url = ""
                try:
                    img = elem.ele('xpath:.//img', timeout=0.2)
                    if img:
                        img_url = img.attr('src') or ""
                except:
                    pass
                
                note_link = ""
                try:
                    link = elem.ele('xpath:.//a[contains(@href, "/explore/")]', timeout=0.2)
                    if link:
                        href = link.attr('href') or ""
                        note_link = 'https://www.xiaohongshu.com' + href if href.startswith('/') else href
                except:
                    pass
                
                # 跨运行去重：从链接提取 note_id，库里已有则整条跳过
                if preexisting_ids and note_link:
                    m = re.search(r'/explore/([a-zA-Z0-9]+)', note_link)
                    if m and m.group(1) in preexisting_ids:
                        skipped_existing += 1
                        continue

                # 极速模式仅有列表页字段，无互动数据 ⇒ 点赞/类型筛选不适用
                # （筛选仅标准模式生效）。note_folder 同时写入 local_dir 供预览精确定位
                note_folder = f"{images_dir}/note_{idx+1}_{timestamp}"
                record = {
                    'title': title[:100],
                    'author': author or "未知",
                    'note_link': note_link,
                    'note_type': '图文',
                    'keyword': keyword,
                    'image_urls': [img_url] if img_url else [],
                    'image_count': 1 if img_url else 0,
                    'batch_dir': images_dir,  # 保存批次目录
                    'local_dir': note_folder,
                }

                if img_url and self.config.download_images:
                    # 过滤表情包
                    if not self._is_emoji_image(img_url):
                        ext = '.webp' if '.webp' in img_url else '.jpg'
                        path = f"{note_folder}/img_1{ext}"
                        download_tasks.append((img_url, path, len(records)))
                
                records.append(record)
                
            except:
                continue
        
        # 批量下载
        if download_tasks and self.config.download_images:
            self.log(f"下载 {len(download_tasks)} 张图片...", "INFO")
            
            def prog(done, total):
                self._update_ui(status=f"下载 {done}/{total}", progress=50 + (done/total)*50)
            
            results = self.downloader.download_batch(
                [(u, p) for u, p, _ in download_tasks],
                prog,
                lambda: self.should_stop
            )
            
            for url, path, rec_idx in download_tasks:
                if results.get(url):
                    # 存储绝对路径
                    abs_path = os.path.abspath(results[url])
                    records[rec_idx]['local_images'] = [abs_path]
        
        self.all_notes_data.extend(records)

        if skipped_existing:
            self.log(f"去重跳过 {skipped_existing} 条已有笔记", "INFO")
        img_count = sum(1 for r in records if r.get('local_images'))
        return len(records), img_count, 0
    
    def _extract_full_note(self, page, idx: int, images_dir: str, timestamp: int, keyword: str) -> Optional[Dict]:
        """提取完整笔记数据（基于实际页面结构优化）"""
        try:
            # 调试：显示当前弹窗URL
            current_url = page.url or ""
            self.log(f"[DEBUG] 提取笔记 idx={idx}, URL={current_url[:80]}", "INFO")
            
            data = {'keyword': keyword, 'image_count': 0, 'batch_dir': images_dir}
            
            FAST_TIMEOUT = 0.2
            
            # 标题 - 从当前弹窗URL获取note_id，然后精确获取当前笔记的标题
            title = ""
            
            # 从URL获取当前笔记ID
            url_note_id = None
            if '/explore/' in current_url:
                url_note_id = current_url.split('/explore/')[-1].split('?')[0].split('/')[0]
            
            # 方法1: JavaScript获取标题。
            # 顺序必须是 __INITIAL_STATE__ 优先、弹窗DOM兜底（核心不变量#1）。
            # 曾因DOM优先 + [class*="title"] 宽泛匹配，把弹窗里"猜你想搜"
            # 推荐组件的文本当成了笔记标题。
            try:
                js_title = page.run_js("""
                    return (() => {
                        // 1) __INITIAL_STATE__ + URL推导的noteId（最可靠）
                        try {
                            const state = window.__INITIAL_STATE__;
                            if (state && state.note) {
                                const urlMatch = window.location.href.match(/explore\\/([a-zA-Z0-9]+)/);
                                const noteId = urlMatch ? urlMatch[1] : state.note.currentNoteId;

                                if (noteId && state.note.noteDetailMap && state.note.noteDetailMap[noteId]) {
                                    const noteData = state.note.noteDetailMap[noteId];
                                    if (noteData.note && noteData.note.title) {
                                        return noteData.note.title;
                                    }
                                }
                            }
                        } catch(e) {}

                        // 2) 弹窗DOM兜底：只取笔记内容区的精确标题节点，
                        //    不用 [class*="title"]（会命中"猜你想搜"等UI组件）
                        const modal = document.querySelector('.note-detail-mask, [class*="noteContainer"], .note-container');
                        if (modal) {
                            const titleEl = modal.querySelector('.note-content .title, #detail-title');
                            if (titleEl && titleEl.textContent.trim().length > 2) {
                                return titleEl.textContent.trim();
                            }
                        }
                        return '';
                    })()
                """)
                if js_title and len(js_title.strip()) > 2:
                    title = js_title.strip()
                    self.log(f"[DEBUG] JS获取标题: {title[:30]}", "INFO")
            except Exception as e:
                self.log(f"[DEBUG] JS获取标题失败: {e}", "WARNING")

            # 已知的页面UI组件文本，绝不可能是笔记标题；命中即视为无效
            UI_TEXT_BLACKLIST = {"猜你想搜", "相关搜索", "大家都在搜", "你可能感兴趣", "热门搜索"}
            if title.strip() in UI_TEXT_BLACKLIST:
                self.log(f"[DEBUG] 标题命中UI组件黑名单({title.strip()})，废弃", "WARNING")
                title = ""
            
            # 方法2: CSS选择器备用（更精确的选择器）
            if not title:
                title_selectors = [
                    'css:.note-detail-mask .title',       # 弹窗内的标题
                    'css:[class*="noteContainer"] .title',
                    'css:.note-content .title',           # 图文笔记标题
                    'css:#detail-title',                  # 旧版选择器
                ]
                for sel in title_selectors:
                    try:
                        e = page.ele(sel, timeout=FAST_TIMEOUT)
                        if (e and e.text and len(e.text.strip()) > 2
                                and e.text.strip() not in UI_TEXT_BLACKLIST):
                            title = e.text.strip()
                            self.log(f"[DEBUG] CSS找到标题: {title[:30]}", "INFO")
                            break
                    except Exception:
                        continue
            
            # 方法3: 如果没有标题（视频笔记），用内容第一行作为标题
            if not title:
                try:
                    content_el = page.ele('css:.note-detail-mask .note-text, [class*="noteContainer"] .note-text, .note-text', timeout=FAST_TIMEOUT)
                    if content_el and content_el.text:
                        first_line = content_el.text.strip().split('\n')[0]
                        if len(first_line) > 2:
                            title = first_line[:50]
                            self.log(f"[DEBUG] 视频笔记，用内容作标题: {title[:30]}", "INFO")
                except Exception:
                    pass
            
            data['title'] = title[:200] if title else f"笔记{idx+1}"
            
            # 作者 - 优先从弹窗内获取
            author = ""
            
            # 方法1: JavaScript从弹窗或__INITIAL_STATE__获取
            try:
                js_author = page.run_js("""
                    return (() => {
                        // 从弹窗内获取
                        const modal = document.querySelector('.note-detail-mask, [class*="noteContainer"], .note-container');
                        if (modal) {
                            const authorEl = modal.querySelector('.username, .author-wrapper .name, .user-info .name');
                            if (authorEl && authorEl.textContent.trim().length > 0 && authorEl.textContent.trim().length < 50) {
                                return authorEl.textContent.trim();
                            }
                        }
                        
                        // 从 __INITIAL_STATE__ 获取
                        try {
                            const state = window.__INITIAL_STATE__;
                            if (state && state.note) {
                                const urlMatch = window.location.href.match(/explore\\/([a-zA-Z0-9]+)/);
                                const noteId = urlMatch ? urlMatch[1] : state.note.currentNoteId;
                                if (noteId && state.note.noteDetailMap && state.note.noteDetailMap[noteId]) {
                                    const noteData = state.note.noteDetailMap[noteId];
                                    if (noteData.note && noteData.note.user && noteData.note.user.nickname) {
                                        return noteData.note.user.nickname;
                                    }
                                }
                            }
                        } catch(e) {}
                        return '';
                    })()
                """)
                if js_author and len(js_author.strip()) > 0:
                    author = js_author.strip()
            except Exception:
                pass
            
            # 方法2: CSS选择器备用（更精确）
            if not author:
                author_selectors = [
                    'css:.note-detail-mask .username',
                    'css:[class*="noteContainer"] .username',
                    'css:.author-wrapper .username',
                    'css:.author-wrapper .name',
                    'css:.user-info .name',
                ]
                for sel in author_selectors:
                    try:
                        e = page.ele(sel, timeout=FAST_TIMEOUT)
                        if e and e.text:
                            txt = e.text.strip()
                            if txt and len(txt) < 50:
                                author = txt
                                break
                    except Exception:
                        continue
            data['author'] = author or "未知"
            
            # 正文内容 - 优先从弹窗内获取
            if self.config.get_content:
                content = ""
                content_selectors = [
                    'css:.note-detail-mask .note-text',
                    'css:[class*="noteContainer"] .note-text',
                    'css:.note-text',
                    'css:.desc',
                    'css:#detail-desc',
                ]
                for sel in content_selectors:
                    try:
                        e = page.ele(sel, timeout=FAST_TIMEOUT)
                        if e and e.text:
                            txt = e.text.strip()
                            if len(txt) > len(content):  # 取最长的内容
                                content = txt
                    except Exception:
                        continue
                if content:
                    self.log(f"[DEBUG] 找到内容: {content[:50]}...", "INFO")
                data['content'] = content
                
                # 提取标签
                if self.config.get_tags and content:
                    tags = re.findall(r'#([^\s#]+)', content)
                    data['tags'] = list(set(tags))[:20]
            
            # 发布时间和IP地区 - 使用.date
            # 实际格式多样："01-24 江西" / "4天前 辽宁" / "编辑于 4天前 四川"
            # / "今天 12:30 上海" / "2025-12-04"。
            # 必须从右侧切分：地区永远是最后一段且不含数字/冒号；
            # 首切("split(' ',1)")遇到"编辑于"前缀会把时间挤进地区字段。
            if self.config.get_publish_time:
                pub_time, ip_region = self._parse_date_region(
                    self._ele_text(page, 'css:.date', FAST_TIMEOUT))
                data['publish_time'] = pub_time
                data['ip_region'] = ip_region
            
            # 互动数据 - 从当前弹窗获取（使用URL中的noteId确保准确）
            if self.config.get_interactions:
                data['like_count'] = 0
                data['collect_count'] = 0
                data['comment_count'] = 0
                try:
                    # 方法1: 从__INITIAL_STATE__获取当前笔记的互动数据（最可靠）
                    try:
                        interact_result = page.run_js("""
                            return (() => {
                                const parseNum = (text) => {
                                    if (!text) return 0;
                                    text = String(text).trim().toLowerCase();
                                    if (text.includes('万')) return Math.floor(parseFloat(text.replace('万', '')) * 10000);
                                    if (text.includes('k')) return Math.floor(parseFloat(text.replace('k', '')) * 1000);
                                    const num = parseInt(text.replace(/[^0-9]/g, ''));
                                    return isNaN(num) ? 0 : num;
                                };
                                
                                // 方法1: 从__INITIAL_STATE__获取（使用URL中的noteId）
                                try {
                                    const state = window.__INITIAL_STATE__;
                                    if (state && state.note) {
                                        const urlMatch = window.location.href.match(/explore\\/([a-zA-Z0-9]+)/);
                                        const noteId = urlMatch ? urlMatch[1] : state.note.currentNoteId;
                                        
                                        if (noteId && state.note.noteDetailMap && state.note.noteDetailMap[noteId]) {
                                            const noteData = state.note.noteDetailMap[noteId].note;
                                            if (noteData && noteData.interactInfo) {
                                                return JSON.stringify({
                                                    likes: parseNum(noteData.interactInfo.likedCount),
                                                    collects: parseNum(noteData.interactInfo.collectedCount),
                                                    comments: parseNum(noteData.interactInfo.commentCount)
                                                });
                                            }
                                        }
                                    }
                                } catch(e) {}
                                
                                // 方法2: 从当前弹窗的DOM获取
                                const modal = document.querySelector('.note-detail-mask, [class*="noteContainer"], .note-container');
                                const searchRoot = modal || document;
                                const bar = searchRoot.querySelector('.buttons.engage-bar-style, .engage-bar, .interact-container');
                                
                                if (bar) {
                                    const likeEl = bar.querySelector('.like-wrapper .count');
                                    const collectEl = bar.querySelector('.collect-wrapper .count');
                                    const chatEl = bar.querySelector('.chat-wrapper .count');
                                    
                                    return JSON.stringify({
                                        likes: parseNum(likeEl?.textContent),
                                        collects: parseNum(collectEl?.textContent),
                                        comments: parseNum(chatEl?.textContent)
                                    });
                                }
                                
                                return '';
                            })()
                        """)
                        if interact_result:
                            import json
                            interact_data = json.loads(interact_result)
                            if interact_data.get('likes', 0) > 0:
                                data['like_count'] = int(interact_data['likes'])
                            if interact_data.get('collects', 0) > 0:
                                data['collect_count'] = int(interact_data['collects'])
                            if interact_data.get('comments', 0) > 0:
                                data['comment_count'] = int(interact_data['comments'])
                    except Exception as e:
                        self.log(f"  JS获取互动数据失败: {e}", "WARNING")
                    
                    # 方法2: CSS选择器备用（限定在弹窗内）
                    if data['like_count'] == 0:
                        like_selectors = [
                            'css:.note-detail-mask .like-wrapper .count',
                            'css:[class*="noteContainer"] .like-wrapper .count',
                            'css:.engage-bar-style .like-wrapper .count',
                        ]
                        for sel in like_selectors:
                            try:
                                e = page.ele(sel, timeout=0.3)
                                if e and e.text:
                                    num = self._parse_num(e.text)
                                    if num > 0:
                                        data['like_count'] = num
                                        break
                            except:
                                pass
                    
                    if data['collect_count'] == 0:
                        collect_selectors = [
                            'css:.note-detail-mask .collect-wrapper .count',
                            'css:[class*="noteContainer"] .collect-wrapper .count',
                        ]
                        for sel in collect_selectors:
                            try:
                                e = page.ele(sel, timeout=0.3)
                                if e and e.text:
                                    num = self._parse_num(e.text)
                                    if num > 0:
                                        data['collect_count'] = num
                                        break
                            except:
                                pass
                    
                    if data['comment_count'] == 0:
                        comment_selectors = [
                            'css:.note-detail-mask .chat-wrapper .count',
                            'css:[class*="noteContainer"] .chat-wrapper .count',
                        ]
                        for sel in comment_selectors:
                            try:
                                e = page.ele(sel, timeout=0.3)
                                if e and e.text:
                                    num = self._parse_num(e.text)
                                    if num > 0:
                                        data['comment_count'] = num
                                        break
                            except:
                                pass
                    
                    # 记录获取到的数据
                    if data['like_count'] > 0 or data['collect_count'] > 0:
                        self.log(f"  互动: ❤️{data['like_count']} ⭐{data['collect_count']} 💬{data['comment_count']}", "INFO")
                    
                except Exception as e:
                    self.log(f"  获取互动数据失败: {e}", "WARNING")
            
            # 链接和ID
            current_url = page.url
            data['note_link'] = current_url if '/explore/' in current_url else ""
            note_id = ""
            if '/explore/' in current_url:
                # 提取ID：/explore/xxxxx?token=xxx
                note_id = current_url.split('/explore/')[-1].split('?')[0]
            data['note_id'] = note_id
            
            # 检测笔记类型并收集视频 URL 候选（多源，下载时依次尝试）
            note_type = "图文"
            video_url = ""
            video_candidates: List[str] = []
            try:
                is_video_note = self._detect_is_video_note(page)
                if is_video_note:
                    note_type = "视频"
                    self.log("  检测到视频笔记", "INFO")
                    # 点播放触发拉流，再从 performance/state 收集直链
                    video_candidates = self._extract_video_url_candidates(page, trigger_play=True)
                    if video_candidates:
                        video_url = video_candidates[0]
                        self.log(f"  视频候选 {len(video_candidates)} 个: {video_url[:70]}...", "SUCCESS")
                    else:
                        self.log("  视频笔记暂无直链（将保留封面，稍后仍尝试 performance 二次采集）", "WARNING")
                        # 再等一会儿二次采集
                        time.sleep(0.8)
                        video_candidates = self._extract_video_url_candidates(page, trigger_play=False)
                        if video_candidates:
                            video_url = video_candidates[0]
                            self.log(f"  二次采集到视频URL: {video_url[:70]}...", "SUCCESS")
            except Exception as e:
                self.log(f"  视频检测异常: {e}", "WARNING")

            data['note_type'] = note_type
            data['video_url'] = video_url
            data['_video_candidates'] = video_candidates
            
            # 获取图片URL - 优先使用JavaScript从页面状态获取
            preview_images = []
            try:
                # 方法1: 从当前弹窗的DOM直接获取图片（最可靠）
                # 先等待图片加载
                time.sleep(0.5)
                
                try:
                    # 从当前URL获取note_id
                    current_url = page.url
                    url_note_id = None
                    if '/explore/' in current_url:
                        url_note_id = current_url.split('/explore/')[-1].split('?')[0].split('/')[0]
                    
                    js_images = page.run_js("""
                        return (() => {
                            const images = [];
                            
                            // 方法1: 从当前可见的弹窗/详情页获取图片
                            // 查找笔记详情弹窗
                            const noteModal = document.querySelector('.note-detail-mask, .note-container, [class*="noteContainer"], [class*="note-detail"]');
                            const searchRoot = noteModal || document.body;
                            
                            // 获取所有图片轮播中的图片
                            const carouselImgs = searchRoot.querySelectorAll('.swiper-slide img, .carousel img, [class*="slider"] img, [class*="carousel"] img');
                            for (let img of carouselImgs) {
                                const src = img.src || img.getAttribute('data-src') || '';
                                if (src.length > 50 && (src.includes('xhscdn') || src.includes('sns-')) && 
                                    !src.includes('avatar') && !src.includes('emoji') && !src.includes('icon')) {
                                    images.push(src);
                                }
                            }
                            
                            // 如果轮播没找到，获取所有大图
                            if (images.length === 0) {
                                const allImgs = searchRoot.querySelectorAll('img');
                                for (let img of allImgs) {
                                    const src = img.src || '';
                                    // 只获取内容图片（大于一定尺寸或特定域名）
                                    if (src.length > 80 && (src.includes('xhscdn') || src.includes('sns-img') || src.includes('sns-webpic'))) {
                                        if (!src.includes('avatar') && !src.includes('emoji') && !src.includes('icon') && !src.includes('loading')) {
                                            // 检查图片尺寸
                                            if (img.naturalWidth > 100 || img.width > 100) {
                                                images.push(src);
                                            } else if (img.naturalWidth === 0) {
                                                // 图片可能还没加载，也加入
                                                images.push(src);
                                            }
                                        }
                                    }
                                }
                            }
                            
                            // 方法2: 尝试从 __INITIAL_STATE__ 获取（作为补充）
                            if (images.length === 0) {
                                try {
                                    const state = window.__INITIAL_STATE__;
                                    if (state && state.note && state.note.noteDetailMap) {
                                        // 从URL获取当前笔记ID
                                        const urlMatch = window.location.href.match(/explore\\/([a-zA-Z0-9]+)/);
                                        const noteId = urlMatch ? urlMatch[1] : state.note.currentNoteId;
                                        
                                        if (noteId && state.note.noteDetailMap[noteId]) {
                                            const noteData = state.note.noteDetailMap[noteId];
                                            if (noteData.note && noteData.note.imageList) {
                                                for (let img of noteData.note.imageList) {
                                                    const url = img.urlDefault || img.url;
                                                    if (url) images.push(url);
                                                }
                                            }
                                        }
                                    }
                                } catch(e) {}
                            }
                            
                            return JSON.stringify([...new Set(images)].slice(0, 20));
                        })()
                    """)
                    if js_images:
                        import json
                        preview_images = json.loads(js_images)
                        self.log(f"  JS获取到 {len(preview_images)} 张图片", "INFO")
                except Exception as e:
                    self.log(f"  JS获取图片失败: {e}", "WARNING")
                
                # 方法2: CSS选择器备用 - 更精确的选择器
                def get_current_images():
                    urls = []
                    # 优先从弹窗内的轮播获取
                    selectors = [
                        'css:.note-detail-mask .swiper-slide img',
                        'css:.note-container .swiper-slide img',
                        'css:[class*="noteContainer"] img',
                        'css:.swiper-wrapper img',
                        'css:.note-slider-img img',
                        'css:.carousel-img img',
                    ]
                    for sel in selectors:
                        try:
                            imgs = page.eles(sel, timeout=0.2)
                            if imgs:
                                for img in imgs[:20]:
                                    src = img.attr('src') or ""
                                    if src and len(src) > 50:
                                        src_lower = src.lower()
                                        if 'avatar' not in src_lower and 'icon' not in src_lower and 'emoji' not in src_lower:
                                            if not self._is_emoji_image(src):
                                                if src not in urls:
                                                    urls.append(src)
                                if urls:  # 找到就停止
                                    break
                        except:
                            pass
                    return urls
                
                # 如果JS没获取到，使用CSS选择器
                if not preview_images:
                    preview_images = get_current_images()
                
                # 如果开启了获取全部图片，尝试切换轮播获取更多
                if self.config.get_all_images and note_type != "视频":
                    # 尝试多种方式切换轮播
                    max_clicks = 15  # 最多点击15次
                    for click_idx in range(max_clicks):
                        if self.should_stop:
                            break
                        
                        # 尝试点击下一张按钮
                        next_clicked = False
                        next_selectors = [
                            'css:.next-btn',
                            'css:.swiper-button-next',
                            'css:.carousel-next',
                            'css:[class*="next"]',
                            'xpath://div[contains(@class, "arrow") and contains(@class, "right")]',
                            'xpath://button[contains(@class, "next")]',
                        ]
                        
                        for sel in next_selectors:
                            try:
                                next_btn = page.ele(sel, timeout=0.2)
                                if next_btn:
                                    next_btn.click()
                                    next_clicked = True
                                    time.sleep(0.3)
                                    break
                            except:
                                pass
                        
                        # 如果没找到按钮，尝试用键盘右箭头
                        if not next_clicked:
                            try:
                                page.actions.key_down('RIGHT').key_up('RIGHT')
                                time.sleep(0.3)
                            except:
                                pass
                        
                        # 获取新图片
                        new_images = get_current_images()
                        old_count = len(preview_images)
                        for img in new_images:
                            if img not in preview_images:
                                preview_images.append(img)
                        
                        # 如果没有新图片，说明已经到最后一张
                        if len(preview_images) == old_count:
                            break
                    
                    if len(preview_images) > 1:
                        self.log(f"  轮播获取到 {len(preview_images)} 张图片", "INFO")
                
            except Exception as e:
                self.log(f"  获取图片异常: {e}", "WARNING")
            
            # 过滤重复和Live图（Live图只保留一张）
            filtered_images = self._filter_live_images(preview_images)
            data['image_urls'] = filtered_images[:20]  # 最多保存20张
            self.log(f"  共获取到 {len(data['image_urls'])} 张图片URL", "INFO")
            
            # 本笔记的媒体目录：图片/视频/评论图三处共用同一路径，
            # 并写入 data['local_dir'] 落库，供预览精确定位
            note_folder = (f"{images_dir}/note_{idx+1}_{note_id}" if note_id
                           else f"{images_dir}/note_{idx+1}_{timestamp}")
            data['local_dir'] = note_folder

            # 批量下载图片：
            # - 图文：全部下载
            # - 视频：至少留 1 张封面，方便预览；视频 URL 失败时也能看到内容
            if self.config.download_images and data['image_urls']:
                folder = note_folder
                urls = data['image_urls']
                if note_type == "视频":
                    urls = urls[:1]
                    self.log("  视频笔记保留封面图", "INFO")
                tasks = []
                for i, url in enumerate(urls, 1):
                    ext = '.webp' if '.webp' in url else '.jpg'
                    tasks.append((url, f"{folder}/img_{i}{ext}"))

                if tasks:
                    results = self.downloader.download_batch(tasks, None, lambda: self.should_stop)
                    data['local_images'] = [os.path.abspath(r) for r in results.values() if r]
                    data['image_count'] = len(data['local_images'])
                    self.log(
                        f"  下载成功 {data['image_count']}/{len(tasks)} 张图片",
                        "SUCCESS" if data['image_count'] > 0 else "WARNING")
            elif not data['image_urls']:
                self.log("  未获取到图片URL", "WARNING")

            # 下载视频：多候选 URL + 多 CDN 前缀轮询
            cands = list(data.get('_video_candidates') or [])
            if video_url and video_url not in cands:
                cands.insert(0, video_url)
            data.pop('_video_candidates', None)

            if self.config.download_videos and cands:
                self.log(f"  开始下载视频（{len(cands)} 个候选）...", "INFO")
                folder = note_folder
                os.makedirs(folder, exist_ok=True)
                video_path = f"{folder}/video.mp4"
                # 同步最新浏览器 Cookie，视频 CDN 常校验会话
                try:
                    self._sync_browser_cookies(page)
                except Exception:
                    pass
                result = self.downloader.download_video_candidates(
                    cands, video_path, stop_flag=lambda: self.should_stop)
                if result:
                    data['local_video'] = result
                    data['video_url'] = cands[0]
                    file_size = os.path.getsize(result) if os.path.exists(result) else 0
                    self.log(f"  视频下载成功: {file_size/1024/1024:.1f}MB", "SUCCESS")
                else:
                    err = getattr(self.downloader, '_last_error', '') or 'unknown'
                    self.log(f"  视频下载失败（{err}）", "WARNING")
            elif note_type == "视频" and not cands:
                self.log("  视频笔记无可用下载地址", "WARNING")

            # 评论：文字 + 图片完整打包
            if self.config.get_comments:
                # 先滚到评论区，触发懒加载
                try:
                    page.run_js("""
                        (() => {
                          const el = document.querySelector(
                            '.comments-container, .comments-el, .note-scroller, [class*="comments"], .list-container');
                          if (el) { el.scrollTop = el.scrollHeight; }
                          else { window.scrollBy(0, 400); }
                        })()
                    """)
                    time.sleep(0.6)
                except Exception:
                    pass

                comments = self._extract_comments(page)
                data['comments'] = comments
                if comments:
                    img_n = sum(len(c.get('images') or []) for c in comments)
                    self.log(f"  获取到 {len(comments)} 条评论（含 {img_n} 张配图URL）", "INFO")

                    # 只要开启下载图片，或评论里有图，就尝试落盘
                    if self.config.download_images or img_n:
                        comments_dir = os.path.join(note_folder, 'comments')
                        comment_tasks = []
                        for ci, comment in enumerate(comments):
                            urls = list(comment.get('images') or [])
                            comment.setdefault('local_images', [])
                            for ii, img_url in enumerate(urls[:6]):
                                if not img_url or len(str(img_url)) < 20:
                                    continue
                                ext = '.jpg'
                                low = str(img_url).lower()
                                if '.png' in low:
                                    ext = '.png'
                                elif '.webp' in low:
                                    ext = '.webp'
                                filepath = os.path.join(
                                    comments_dir, f"c{ci+1}_{ii+1}{ext}")
                                comment_tasks.append((img_url, filepath, ci))

                        if comment_tasks:
                            os.makedirs(comments_dir, exist_ok=True)
                            batch = [(u, p) for u, p, _ in comment_tasks]
                            results = self.downloader.download_batch(
                                batch, stop_flag=lambda: self.should_stop)
                            ok = 0
                            for url, path, ci in comment_tasks:
                                saved = results.get(url)
                                if saved and os.path.isfile(str(saved)):
                                    abs_p = os.path.abspath(str(saved))
                                    comments[ci].setdefault('local_images', []).append(abs_p)
                                    ok += 1
                                elif path and os.path.isfile(path):
                                    abs_p = os.path.abspath(path)
                                    comments[ci].setdefault('local_images', []).append(abs_p)
                                    ok += 1
                            data['comments'] = comments
                            data['comment_images_count'] = ok
                            if ok:
                                self.log(
                                    f"  评论图片: {ok}/{len(comment_tasks)} 张已保存", "SUCCESS")
                            else:
                                self.log(
                                    f"  评论图片下载失败 ({len(comment_tasks)} 张)", "WARNING")
                else:
                    self.log("  未获取到评论（可能未加载或被折叠）", "WARNING")

            return data

        except Exception as e:
            self.log(f"提取数据失败: {e}", "ERROR")
            return None

    def _detect_is_video_note(self, page) -> bool:
        """判断当前详情是否为视频笔记（避免把普通图文误判成视频）。"""
        try:
            flag = page.run_js(r"""
            return (() => {
                try {
                    const m = location.href.match(/explore\/([a-zA-Z0-9]+)/);
                    const state = window.__INITIAL_STATE__ || {};
                    const id = m ? m[1] : state.note?.currentNoteId;
                    const note = state.note?.noteDetailMap?.[id]?.note;
                    if (note) {
                        if (note.type === 'video' || note.type === 'videos') return true;
                        if (note.video || note.videoInfo) return true;
                    }
                } catch (e) {}
                // 有 video 标签且非空宽高
                const v = document.querySelector('video');
                if (v && (v.src || v.currentSrc || v.querySelector('source'))) return true;
                // xgplayer 容器
                if (document.querySelector('.xgplayer, [class*="xgplayer"], .player-container video')) return true;
                return false;
            })()
            """)
            return bool(flag)
        except Exception:
            try:
                return bool(page.ele('xpath://video', timeout=0.3))
            except Exception:
                return False

    def _extract_video_url_candidates(self, page, trigger_play: bool = True) -> List[str]:
        """从页面状态 / performance 网络 / script / video 标签收集视频直链。

        返回 JSON 字符串再解析：DrissionPage 对 JS Array 回传不稳定。
        """
        if trigger_play:
            try:
                page.run_js(r"""
                (() => {
                    const sels = [
                      'video', '.xgplayer-start', '.play-icon', '.play-btn',
                      '[class*="play-icon"]', '[class*="xgplayer"] .xgplayer-icon-play',
                      'button[aria-label*="播放"]'
                    ];
                    for (const s of sels) {
                      const el = document.querySelector(s);
                      if (!el) continue;
                      try { el.click(); } catch (e) {}
                      try { if (el.play) el.play(); } catch (e) {}
                    }
                    // 静音尝试播放，触发拉流
                    document.querySelectorAll('video').forEach(v => {
                      try { v.muted = true; v.play(); } catch (e) {}
                    });
                })()
                """)
                time.sleep(0.7)
            except Exception:
                pass

        script = r"""
        return (() => {
            const urls = [];
            const push = (u) => {
                if (!u || typeof u !== 'string') return;
                u = String(u).replace(/\\u002F/g, '/').replace(/\\\//g, '/').trim();
                if (u.startsWith('//')) u = 'https:' + u;
                if (u.startsWith('http://')) u = 'https://' + u.slice(7);
                if (u.startsWith('blob:') || u.length < 24) return;
                // 排除明显图片
                if (/\.(jpg|jpeg|png|webp|gif)(\?|$)/i.test(u) && u.indexOf('/stream/') < 0) return;
                if (urls.indexOf(u) < 0) urls.push(u);
            };
            const fromStream = (stream) => {
                if (!stream || typeof stream !== 'object') return;
                const keys = Object.keys(stream);
                for (let i = 0; i < keys.length; i++) {
                    const arr = stream[keys[i]];
                    if (Array.isArray(arr)) {
                        for (let j = 0; j < arr.length; j++) {
                            const s = arr[j];
                            if (!s) continue;
                            push(s.masterUrl);
                            push(s.backupUrl);
                            push(s.url);
                            if (Array.isArray(s.backupUrls)) {
                                for (let k = 0; k < s.backupUrls.length; k++) push(s.backupUrls[k]);
                            }
                        }
                    } else if (arr && typeof arr === 'object') {
                        push(arr.masterUrl); push(arr.url);
                    }
                }
                push(stream.masterUrl); push(stream.url);
            };
            const fromVideo = (video) => {
                if (!video) return;
                const key = (video.consumer && video.consumer.originVideoKey)
                    || video.originVideoKey
                    || (video.consumer && video.consumer.videoKey)
                    || video.videoKey;
                if (key && String(key).length > 6) {
                    const hosts = [
                        'https://sns-video-bd.xhscdn.com/',
                        'https://sns-video-al.xhscdn.com/',
                        'https://sns-video-qc.xhscdn.com/',
                        'https://sns-video-v3.xhscdn.com/',
                    ];
                    for (let i = 0; i < hosts.length; i++) push(hosts[i] + key);
                }
                push(video.url); push(video.videoUrl);
                if (video.consumer) push(video.consumer.url);
                const media = video.media || video.videoMedia || {};
                fromStream(media.stream || media);
                if (video.stream) fromStream(video.stream);
            };

            // A) __INITIAL_STATE__
            try {
                const state = window.__INITIAL_STATE__ || {};
                if (state.note) {
                    const m = location.href.match(/explore\/([a-zA-Z0-9]+)/);
                    const noteId = m ? m[1] : state.note.currentNoteId;
                    const entry = state.note.noteDetailMap && state.note.noteDetailMap[noteId];
                    const note = entry && (entry.note || entry);
                    if (note) {
                        fromVideo(note.video);
                        fromVideo(note.videoInfo);
                        fromVideo(note.videoData);
                    }
                    if (entry && entry.video) fromVideo(entry.video);
                }
            } catch (e) {}

            // B) performance 资源（播放后最可靠）
            try {
                const entries = performance.getEntriesByType('resource') || [];
                for (let i = 0; i < entries.length; i++) {
                    const n = entries[i].name || '';
                    if (!n) continue;
                    if (n.indexOf('xhscdn') >= 0 && (
                        n.indexOf('/stream/') >= 0 || n.indexOf('.mp4') >= 0
                        || n.indexOf('video') >= 0 || n.indexOf('sns-video') >= 0
                    )) {
                        push(n);
                    }
                }
            } catch (e) {}

            // C) script 文本兜底
            try {
                const scripts = document.querySelectorAll('script');
                for (let i = 0; i < scripts.length; i++) {
                    const t = scripts[i].textContent || '';
                    if (t.length < 80) continue;
                    let m = t.match(/"originVideoKey"\s*:\s*"([^"]+)"/);
                    if (m && m[1].length > 6) {
                        push('https://sns-video-bd.xhscdn.com/' + m[1]);
                        push('https://sns-video-v3.xhscdn.com/' + m[1]);
                        push('https://sns-video-qc.xhscdn.com/' + m[1]);
                    }
                    const masterRe = /"masterUrl"\s*:\s*"(https?:[^"]+)"/g;
                    let mm;
                    while ((mm = masterRe.exec(t)) !== null) push(mm[1]);
                    const streamRe = /(https?:\/\/[^"'\s]*xhscdn\.com[^"'\s]*\/stream[^"'\s]*)/g;
                    let sm;
                    while ((sm = streamRe.exec(t)) !== null) push(sm[1]);
                }
            } catch (e) {}

            // D) video 标签
            try {
                const vs = document.querySelectorAll('video');
                for (let i = 0; i < vs.length; i++) {
                    const el = vs[i];
                    push(el.currentSrc || el.src);
                    const source = el.querySelector('source');
                    if (source) push(source.src);
                }
            } catch (e) {}

            return JSON.stringify(urls);
        })()
        """
        out: List[str] = []
        try:
            result = page.run_js(script)
            parsed = None
            if isinstance(result, str):
                try:
                    parsed = json.loads(result)
                except Exception:
                    if result.startswith("http"):
                        parsed = [result]
            elif isinstance(result, list):
                parsed = result
            if isinstance(parsed, list):
                for u in parsed:
                    nu = self.downloader._normalize_url(str(u))
                    if nu and nu not in out and not nu.startswith("blob:"):
                        out.append(nu)
        except Exception as e:
            self.log(f"  收集视频候选失败: {e}", "WARNING")
        return out

    def _extract_single_comment(self, item, existing_contents: set) -> Optional[Dict]:
        """提取单条评论（文字可短；纯图评论也保留）"""
        exclude_words = {
            '关注', '点赞', '收藏', '分享', '复制', '举报', '回复', '查看', '展开',
            '赞', '条评论', '说点什么', '取消', '发送', '评论', '作者',
        }

        try:
            name_el = item.ele(
                'css:.name, .user-name, .author-name, .nickname, [class*="name"]',
                timeout=0.1)
            name = (name_el.text if name_el else "").strip()

            content_el = item.ele(
                'css:.content, .comment-content, .note-text, [class*="content"]',
                timeout=0.1)
            content = (content_el.text if content_el else "").strip()

            # 图片（允许纯图评论）
            comment_images = []
            try:
                imgs = item.eles(
                    'css:img.comment-img, .comment-image img, .comment-pic img, '
                    '.comment-picture img, [class*="picture"] img, [class*="comment"] img, '
                    'img[src*="xhscdn"], img[src*="sns-webpic"], img[src*="ci.xiaohongshu"]',
                    timeout=0.15) or []
                for img in imgs[:6]:
                    src = (img.attr('src') or img.attr('data-src') or "").strip()
                    if not src or len(src) < 30:
                        continue
                    low = src.lower()
                    if any(x in low for x in (
                            'avatar', 'emoji', 'icon', 'loading', 'head', 'logo')):
                        continue
                    if any(x in low for x in (
                            'xhscdn', 'sns-webpic', 'sns-img', 'ci.xiaohongshu', 'sns-')):
                        if src.startswith('//'):
                            src = 'https:' + src
                        if src.startswith('http://'):
                            src = 'https://' + src[7:]
                        comment_images.append(src)
                comment_images = list(dict.fromkeys(comment_images))
            except Exception:
                pass

            # 无效：既无有效文字又无图
            if content:
                if content in existing_contents:
                    return None
                if content in exclude_words or content.isdigit():
                    content = ""
                if len(content) >= 800:
                    content = content[:800]
            if not content and not comment_images:
                return None

            time_el = item.ele(
                'css:.date, .time, .info .date, .comment-time, [class*="time"]',
                timeout=0.1)
            time_text = (time_el.text if time_el else "").strip()

            ip_text = ""
            try:
                ip_el = item.ele('css:.ip, .location, .region, .area', timeout=0.1)
                if ip_el:
                    ip_text = ip_el.text.strip()
                elif time_text and " " in time_text:
                    parts = time_text.split()
                    if len(parts) >= 2:
                        last_part = parts[-1]
                        if not any(c in last_part for c in (
                                '前', '天', '小时', '分钟', '秒', '月', '年', ':')):
                            ip_text = last_part
                            time_text = " ".join(parts[:-1])
            except Exception:
                pass

            like_count = 0
            try:
                like_el = item.ele(
                    'css:.like-count, .likes, .like-num, .zan-count, [class*="like"] span',
                    timeout=0.1)
                if like_el:
                    like_text = (like_el.text or "").strip()
                    if like_text:
                        if '万' in like_text:
                            like_count = int(float(like_text.replace('万', '')) * 10000)
                        else:
                            digits = re.sub(r'[^0-9]', '', like_text)
                            if digits:
                                like_count = int(digits)
            except Exception:
                pass

            # 纯图评论用占位文案，避免入库后被当成空
            if not content and comment_images:
                content = "[图片评论]"

            return {
                'author': name or "匿名用户",
                'content': content,
                'time': time_text,
                'ip': ip_text,
                'likes': like_count,
                'has_image': bool(comment_images),
                'images': comment_images,
                'local_images': [],
            }
        except Exception:
            return None

    def _extract_comments(self, page) -> List[Dict]:
        """提取评论文字+配图：状态树优先，DOM 兜底，滚动加载更多。"""
        comments: List[Dict] = []
        max_count = max(1, int(self.config.comments_count or 10))
        existing_contents: set = set()

        def _norm_likes(v) -> int:
            try:
                if isinstance(v, (int, float)):
                    return int(v)
                s = str(v or '').strip()
                if not s:
                    return 0
                if '万' in s:
                    return int(float(s.replace('万', '')) * 10000)
                digits = re.sub(r'[^0-9]', '', s)
                return int(digits) if digits else 0
            except Exception:
                return 0

        def _add(c: dict):
            if len(comments) >= max_count:
                return False
            content = (c.get('content') or '').strip()
            images = list(c.get('images') or [])[:6]
            if not content and not images:
                return True
            key = content or ('|'.join(images[:2]))
            if key in existing_contents:
                return True
            if content and content in {
                    '关注', '点赞', '收藏', '分享', '回复', '说点什么', '评论'}:
                if not images:
                    return True
                content = "[图片评论]"
            existing_contents.add(key)
            # 时间戳毫秒 → 可读
            t = c.get('time') or ''
            if isinstance(t, (int, float)) or (isinstance(t, str) and t.isdigit()):
                try:
                    ts = int(t)
                    if ts > 1e12:
                        ts //= 1000
                    t = datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M')
                except Exception:
                    t = str(t)
            comments.append({
                'author': c.get('author') or '匿名用户',
                'content': content or ('[图片评论]' if images else ''),
                'time': str(t or ''),
                'ip': str(c.get('ip') or ''),
                'likes': _norm_likes(c.get('likes')),
                'has_image': bool(images),
                'images': images,
                'local_images': [],
            })
            return len(comments) < max_count

        # 1) 深度扫描 __INITIAL_STATE__
        try:
            state_comments = page.run_js(r"""
            return (() => {
                const out = [];
                const seen = new Set();
                const pushPic = (pics, p) => {
                    if (!p) return;
                    if (typeof p === 'string') {
                        let u = p;
                        if (u.startsWith('//')) u = 'https:' + u;
                        if (u.length > 30) pics.push(u);
                        return;
                    }
                    const cands = [
                        p.url, p.urlDefault, p.original, p.picUrl,
                        p?.infoList?.[0]?.url, p?.infoList?.[0]?.urlDefault,
                    ];
                    for (const u0 of cands) {
                        if (u0 && String(u0).length > 30) {
                            let u = String(u0);
                            if (u.startsWith('//')) u = 'https:' + u;
                            pics.push(u);
                            break;
                        }
                    }
                };
                const take = (c) => {
                    if (!c || typeof c !== 'object') return;
                    const content = (c.content || c.note || c.commentContent || '').trim();
                    const pics = [];
                    for (const arr of [c.pictures, c.images, c.imageList, c.picList, c.pictureList]) {
                        if (Array.isArray(arr)) arr.forEach(p => pushPic(pics, p));
                    }
                    if (!content && pics.length === 0) return;
                    const key = content + '|' + (pics[0] || '');
                    if (seen.has(key)) return;
                    seen.add(key);
                    out.push({
                        author: c.userInfo?.nickname || c.user?.nickname || c.nickname
                            || c.userName || '匿名',
                        content,
                        time: c.createTime || c.time || c.timestamp || '',
                        ip: c.ipLocation || c.ip || c.ip_location || '',
                        likes: c.likeCount || c.likedCount || c.likes || 0,
                        has_image: pics.length > 0,
                        images: [...new Set(pics)].slice(0, 6),
                    });
                };
                const walk = (node, depth) => {
                    if (!node || depth > 8) return;
                    if (Array.isArray(node)) {
                        // 评论数组特征：元素含 content/userInfo
                        if (node.length && node[0] && typeof node[0] === 'object'
                            && (node[0].content !== undefined || node[0].userInfo
                                || node[0].pictures || node[0].commentId || node[0].id)) {
                            node.forEach(take);
                        } else {
                            node.forEach(x => walk(x, depth + 1));
                        }
                        return;
                    }
                    if (typeof node === 'object') {
                        if (node.content !== undefined && (node.userInfo || node.user || node.pictures)) {
                            take(node);
                        }
                        for (const k of Object.keys(node)) {
                            // 常见评论挂载点
                            if (/comment/i.test(k) || k === 'list' || k === 'comments') {
                                walk(node[k], depth + 1);
                            } else if (depth < 4) {
                                walk(node[k], depth + 1);
                            }
                        }
                    }
                };
                try {
                    const state = window.__INITIAL_STATE__ || {};
                    const m = location.href.match(/explore\/([a-zA-Z0-9]+)/);
                    const id = m ? m[1] : state.note?.currentNoteId;
                    const entry = state.note?.noteDetailMap?.[id];
                    if (entry) walk(entry, 0);
                    if (state.comment) walk(state.comment, 0);
                    if (state.note) walk(state.note, 0);
                } catch (e) {}
                return out.slice(0, 40);
            })()
            """) or []
            if isinstance(state_comments, list):
                for c in state_comments:
                    if isinstance(c, dict) and not _add(c):
                        break
        except Exception as e:
            self.log(f"  状态树评论提取失败: {e}", "DEBUG")

        # 2) DOM + 滚动加载
        try:
            for scroll_i in range(4):
                if len(comments) >= max_count:
                    break
                comment_items = page.eles(
                    'css:.comment-item, .parent-comment, .comment-inner, '
                    '.list-container .comment-item, [class*="comment-item"], '
                    '[class*="CommentItem"]',
                    timeout=0.5) or []
                for item in comment_items:
                    if len(comments) >= max_count:
                        break
                    c = self._extract_single_comment(item, existing_contents)
                    if c:
                        _add(c)

                # 滚动评论容器加载更多
                try:
                    page.run_js("""
                        (() => {
                          const sels = ['.comments-container','.comments-el','.note-scroller',
                            '.list-container','[class*="comments"]','[class*="comment-list"]'];
                          for (const s of sels) {
                            const el = document.querySelector(s);
                            if (el && el.scrollHeight > el.clientHeight + 20) {
                              el.scrollTop = el.scrollHeight;
                              return true;
                            }
                          }
                          window.scrollBy(0, 500);
                          return false;
                        })()
                    """)
                    time.sleep(0.45)
                except Exception:
                    break
                if scroll_i == 0 and not comment_items and not comments:
                    time.sleep(0.4)
        except Exception:
            pass

        return comments[:max_count]
    
    def _filter_live_images(self, image_urls: list) -> list:
        """过滤Live图（动态图片），只保留一张静态版本
        
        Live图特征：
        1. URL中包含 'live' 关键字
        2. 同一张图片有静态和动态两个版本
        3. URL结构相似，只是路径或参数不同
        """
        import re
        
        if not image_urls:
            return []
        
        # 去重
        unique_urls = list(dict.fromkeys(image_urls))
        
        def extract_image_id(url):
            """提取图片的核心ID（去掉所有变体标记）"""
            # 移除查询参数
            base = url.split('?')[0]
            # 移除处理参数如 !nd_dft_wlteh_webp_3
            base = re.sub(r'![^/]+$', '', base)
            
            # 提取文件名部分
            filename = base.split('/')[-1]
            
            # 移除扩展名
            filename = re.sub(r'\.(jpg|jpeg|png|webp|gif|heic)$', '', filename, flags=re.IGNORECASE)
            
            # 移除live相关标记
            # 例如: spectrum/1040g0k031fat0rfh5g6g5p4sk5ohqo95i4stbh0_live.jpg -> spectrum/1040g0k031fat0rfh5g6g5p4sk5ohqo95i4stbh0
            filename = re.sub(r'_live\d*$', '', filename)
            filename = re.sub(r'-live\d*$', '', filename)
            
            # 提取核心ID（通常是长字符串）
            # 匹配类似 1040g0k031fat0rfh5g6g5p4sk5ohqo95i4stbh0 的ID
            id_match = re.search(r'([a-z0-9]{20,})', filename, re.IGNORECASE)
            if id_match:
                return id_match.group(1).lower()
            
            return filename.lower()
        
        def is_live_url(url):
            """判断是否是Live图URL"""
            url_lower = url.lower()
            return 'live' in url_lower or '/live/' in url_lower
        
        # 按图片ID分组
        url_groups = {}
        for url in unique_urls:
            img_id = extract_image_id(url)
            if img_id not in url_groups:
                url_groups[img_id] = []
            url_groups[img_id].append(url)
        
        # 每组只保留一张（优先非live的静态图）
        filtered = []
        for img_id, urls in url_groups.items():
            if len(urls) == 1:
                filtered.append(urls[0])
            else:
                # 多张相似图片，选择最优的一张
                # 优先级：不含live > 含jpg/png > 其他
                best = None
                for url in urls:
                    if not is_live_url(url):
                        # 优先选择静态图
                        url_lower = url.lower()
                        if best is None:
                            best = url
                        elif '.jpg' in url_lower or '.png' in url_lower:
                            best = url
                
                # 如果全是live图，取第一张
                if best is None:
                    best = urls[0]
                
                filtered.append(best)
                self.log(f"  Live图过滤: {len(urls)}张相似图 -> 保留1张", "DEBUG")
        
        return filtered
    
    def _is_emoji_image(self, url: str) -> bool:
        """检测是否是表情包图片"""
        if not url:
            return False
        url_lower = url.lower()
        
        import re
        
        # 1. URL关键词检测
        # 注意：'spectrum' 不是表情特征！实测 12% 的真实笔记图片位于
        # sns-webpic-qc.xhscdn.com/.../spectrum/ 路径下（Live图静态版），
        # 曾因此被误删，切勿加回
        emoji_keywords = [
            'emoji', 'sticker', 'emote', 'emoticon', 'expression',
            'meme', 'gif', 'animated',
            '/e/', '/em/', '/stk/', '/stick/'
        ]
        for kw in emoji_keywords:
            if kw in url_lower:
                return True
        
        # 2. 小红书表情包特征：通常是小尺寸图片
        # 检测URL中的尺寸参数，如 /w/120 或 imageView2/2/w/200 或 !nd_
        size_patterns = [
            r'/w/(\d+)',
            r'/h/(\d+)', 
            r'imageview2/\d/w/(\d+)',
            r'!nd_dft_wlteh_webp_(\d+)',
            r'_(\d+)x(\d+)\.',
        ]
        for pattern in size_patterns:
            match = re.search(pattern, url_lower)
            if match:
                try:
                    size = int(match.group(1))
                    if size <= 300:  # 宽度小于300像素，可能是表情
                        return True
                except:
                    pass
        
        # 3. 检测表情包CDN特征（spectrum 相关模式已移除，见上方注释）
        emoji_cdn_patterns = [
            'fe-static',
            '/emoji/',
            'sticker.xhscdn',
        ]
        for pattern in emoji_cdn_patterns:
            if pattern in url_lower:
                return True

        # 4. 检测非常短的图片URL（通常是内联表情）
        # 实测合法笔记图片URL均 >= 150 字符；阈值从100收紧到60，
        # 避免误杀短链接的真实图片
        if len(url) < 60:
            return True
        
        # 5. 检测URL中没有常规图片路径特征（正常笔记图片通常有特定路径）
        normal_patterns = ['sns-img', 'sns-webpic', 'note', 'traceId']
        has_normal_pattern = any(p in url_lower for p in normal_patterns)
        if not has_normal_pattern and 'xhscdn' in url_lower:
            # 小红书CDN但不是常规图片路径，可能是表情
            return True
            
        return False
    
    def _is_search_recommend_card(self, elem):
        """检测是否是'大家都在搜'推荐卡片"""
        try:
            # 获取卡片的文本内容
            text = elem.text or ""
            
            # 检测推荐搜索卡片的特征
            if "大家都在搜" in text:
                return True
            if "热门搜索" in text:
                return True
            
            # 检测卡片内是否有推荐搜索相关的class
            html = elem.html or ""
            if "search-recommend" in html.lower():
                return True
            if "hot-search" in html.lower():
                return True
            
            # 检测是否有多个搜索关键词链接（推荐卡片的特征）
            try:
                links = elem.eles('css:a')
                # 推荐卡片通常有多个链接，且没有封面图片
                cover = elem.ele('css:a.cover, .cover', timeout=0.1)
                if len(links) > 3 and not cover:
                    return True
            except:
                pass
                
        except Exception:
            pass
        return False
    
    def _note_passes_filter(self, note_data: Dict) -> bool:
        """主页面"筛选条件"（点赞区间 / 笔记类型）是否放行该笔记"""
        try:
            likes = int(note_data.get('like_count', 0) or 0)
        except (TypeError, ValueError):
            likes = 0
        if likes < self.config.min_likes or likes > self.config.max_likes:
            return False
        type_filter = self.config.note_type_filter
        if type_filter and type_filter != "全部":
            if note_data.get('note_type', '图文') != type_filter:
                return False
        return True

    @staticmethod
    def _ele_text(page, selector: str, timeout: float) -> str:
        """安全读取元素文本，找不到返回空串"""
        try:
            e = page.ele(selector, timeout=timeout)
            return (e.text or "").strip() if e else ""
        except Exception:
            return ""

    @staticmethod
    def _parse_date_region(full_text: str) -> Tuple[str, str]:
        """把 .date 文本拆成 (发布时间, IP地区)。

        样例："01-24 江西" / "4天前 辽宁" / "编辑于 4天前 四川" /
        "今天 12:30 上海" / "2025-12-04"（无地区）。
        规则：剥掉"编辑于/发布于"前缀后，从右取最后一段作为地区，
        但该段含数字或冒号时视为时间的一部分（如 "今天 12:30"）。
        """
        text = (full_text or "").strip()
        for prefix in ("编辑于", "发布于"):
            if text.startswith(prefix):
                text = text[len(prefix):].strip()
        if not text:
            return "", ""
        if " " in text:
            head, tail = text.rsplit(" ", 1)
            if tail and not any(c.isdigit() for c in tail) and ":" not in tail:
                return head.strip(), tail.strip()
        return text, ""

    @staticmethod
    def _fmt_count(n) -> str:
        """数字按小红书习惯缩写：>=10000 显示 x.x万"""
        try:
            n = int(n)
        except (TypeError, ValueError):
            return "0"
        if n >= 10000:
            return f"{n / 10000:.1f}".rstrip('0').rstrip('.') + "万"
        return str(n)

    def _parse_num(self, text) -> int:
        """解析数字（支持万/k单位）"""
        if not text:
            return 0
        text = str(text).strip().lower()
        try:
            if '万' in text:
                return int(float(text.replace('万', '')) * 10000)
            if 'k' in text:
                return int(float(text.replace('k', '')) * 1000)
            return int(re.sub(r'[^\d]', '', text) or 0)
        except Exception:
            return 0
    
    @staticmethod
    def _notes_to_export_df(data) -> "pd.DataFrame":
        """笔记 dict 列表 → 可落盘的 DataFrame（唯一的导出扁平化入口）。

        评论转多行文本、tags/图片/路径列表转分隔串，最后统一 rename 成
        EXPORT_COLUMN_MAPPING 中文列头。_save_data 与 _export_results 共用，
        保证全仓只有一套导出 schema（回读侧配套 normalize_df_columns）。
        """
        processed_data = []
        for item in data:
            processed_item = item.copy()

            # 评论: dict 列表 → "[序号] @作者 | IP | 时间 | ❤️赞 | [含图]: 内容"
            if isinstance(processed_item.get('comments'), list):
                comments = processed_item['comments']
                if comments and isinstance(comments[0], dict):
                    comment_strs = []
                    for i, c in enumerate(comments, 1):
                        author = c.get('author', '') or '匿名'
                        content = c.get('content', '')
                        if not content:
                            continue
                        info_parts = [f"@{author}"]
                        if c.get('ip'):
                            info_parts.append(c['ip'])
                        if c.get('time'):
                            info_parts.append(c['time'])
                        if c.get('likes', 0) > 0:
                            info_parts.append(f"❤️{c['likes']}")
                        if c.get('has_image'):
                            info_parts.append("[含图]")
                        comment_strs.append(f"[{i}] {' | '.join(info_parts)}: {content}")
                    processed_item['comments'] = '\n'.join(comment_strs)
                else:
                    processed_item['comments'] = '\n'.join(str(c) for c in comments)

            if isinstance(processed_item.get('tags'), list):
                processed_item['tags'] = ', '.join(processed_item['tags'])
            if isinstance(processed_item.get('image_urls'), list):
                processed_item['image_urls'] = ' | '.join(processed_item['image_urls'])
            if isinstance(processed_item.get('local_images'), list):
                processed_item['local_images'] = ' | '.join(processed_item['local_images'])

            processed_data.append(processed_item)

        df = pd.DataFrame(processed_data)
        return df.rename(columns=EXPORT_COLUMN_MAPPING)

    def _save_data(self, data, keyword):
        """保存数据"""
        os.makedirs("data", exist_ok=True)
        timestamp = int(time.time())

        df = self._notes_to_export_df(data)
        
        ext = self.config.export_format
        filename = f"data/搜索结果_{keyword}_{timestamp}.{ext}"
        
        if ext == "xlsx":
            df.to_excel(filename, index=False)
        elif ext == "csv":
            df.to_csv(filename, index=False, encoding='utf-8-sig')
        elif ext == "json":
            # JSON格式保留原始结构
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        
        # 同时保存一份到当前爬取目录
        if hasattr(self, 'current_crawl_dir') and self.current_crawl_dir:
            try:
                os.makedirs(self.current_crawl_dir, exist_ok=True)
                crawl_file = f"{self.current_crawl_dir}/搜索结果.{ext}"
                if ext == "xlsx":
                    df.to_excel(crawl_file, index=False)
                elif ext == "csv":
                    df.to_csv(crawl_file, index=False, encoding='utf-8-sig')
                elif ext == "json":
                    with open(crawl_file, 'w', encoding='utf-8') as f:
                        json.dump(data, f, ensure_ascii=False, indent=2)
            except Exception:
                pass
        
        return filename
    
    # === 分析功能 ===
    def _get_analysis_records(self):
        """分析数据源：优先内存中本次爬取，否则回退数据库（不再依赖易损的导出文件）"""
        if self.all_notes_data:
            return list(self.all_notes_data)
        return self._load_notes_from_db()

    def _load_notes_from_db(self):
        """从 SQLite 读取全部笔记，JSON 字段反序列化为 Python 对象"""
        records = []
        try:
            conn = sqlite3.connect(self.config.db_path)
            conn.row_factory = sqlite3.Row
            for row in conn.execute("SELECT * FROM notes ORDER BY crawl_time DESC"):
                note = dict(row)
                for col in ('tags', 'image_urls', 'comments'):
                    try:
                        note[col] = json.loads(note.get(col) or '[]')
                    except (ValueError, TypeError):
                        note[col] = []
                records.append(note)
            conn.close()
        except Exception as e:
            self.log(f"读取数据库失败: {e}", "WARNING")
        return records

    def _generate_charts(self):
        """生成图表"""
        if not HAS_MATPLOTLIB:
            messagebox.showwarning("提示", "需要安装matplotlib库")
            return

        records = self._get_analysis_records()
        if not records:
            messagebox.showinfo("提示", "没有数据可分析")
            return

        df = pd.DataFrame(records)
        charts = DataAnalyzer.generate_charts(df, "data/charts")
        
        if charts:
            messagebox.showinfo("完成", f"已生成 {len(charts)} 个图表\n保存到: data/charts/")
            os.startfile("data/charts")
        else:
            messagebox.showwarning("提示", "图表生成失败")
    
    def _generate_wordcloud(self):
        """生成词云"""
        if not HAS_WORDCLOUD:
            messagebox.showwarning("提示", "需要安装wordcloud和jieba库")
            return
        
        records = self._get_analysis_records()
        if not records:
            messagebox.showinfo("提示", "没有数据可分析")
            return

        texts = [d.get('title', '') + ' ' + d.get('content', '') for d in records]
        output = "data/wordcloud.png"
        
        result = DataAnalyzer.generate_wordcloud(texts, output)
        if result:
            messagebox.showinfo("完成", f"词云已生成: {output}")
            os.startfile(output)
        else:
            messagebox.showwarning("提示", "词云生成失败")
    
    def _generate_report(self):
        """生成分析报告"""
        if not HAS_DOCX:
            messagebox.showwarning("提示", "需要安装python-docx库")
            return
        
        records = self._get_analysis_records()
        if not records:
            messagebox.showinfo("提示", "没有数据可分析")
            return

        df = pd.DataFrame(records)
        stats = DataAnalyzer.generate_stats(df)

        # 先生成图表
        charts = []
        if HAS_MATPLOTLIB:
            charts = DataAnalyzer.generate_charts(df, "data/charts")

        keyword = records[0].get('keyword', '未知') or '未知'
        output = f"data/分析报告_{keyword}_{int(time.time())}.docx"
        
        result = DataAnalyzer.generate_report(df, stats, charts, output, keyword)
        if result:
            messagebox.showinfo("完成", f"报告已生成: {output}")
            os.startfile(output)
        else:
            messagebox.showwarning("提示", "报告生成失败")
    
    def _merge_data(self):
        """合并所有数据"""
        if not os.path.exists("data"):
            messagebox.showinfo("提示", "没有数据文件")
            return
        
        all_dfs = []
        for f in os.listdir("data"):
            if f.startswith("搜索结果_") and f.endswith(".xlsx"):
                try:
                    # 归一化列名，否则中文列头下 note_link 去重永不生效
                    df = normalize_df_columns(pd.read_excel(os.path.join("data", f)))
                    all_dfs.append(df)
                except Exception:
                    continue
        
        if not all_dfs:
            messagebox.showinfo("提示", "没有可合并的数据")
            return
        
        merged = pd.concat(all_dfs, ignore_index=True)
        if 'note_link' in merged.columns:
            merged = merged.drop_duplicates(subset=['note_link'])
        
        output = f"data/合并数据_{int(time.time())}.xlsx"
        # 落盘时恢复中文列头，与"搜索结果_*"导出格式保持一致
        merged.rename(columns=EXPORT_COLUMN_MAPPING).to_excel(output, index=False)
        
        messagebox.showinfo("完成", f"已合并 {len(merged)} 条数据\n保存到: {output}")
    
    def _refresh_history(self):
        """刷新历史"""
        for item in self.history_tree.get_children():
            self.history_tree.delete(item)
        
        if not os.path.exists("data"):
            return
        
        files = []
        for f in os.listdir("data"):
            if f.startswith("搜索结果_") and f.endswith((".xlsx", ".csv", ".json")):
                path = os.path.join("data", f)
                files.append((f, os.path.getmtime(path), path))
        
        files.sort(key=lambda x: x[1], reverse=True)
        
        for f, mtime, path in files[:20]:
            try:
                keyword = f.replace("搜索结果_", "").rsplit("_", 1)[0]
                time_str = datetime.fromtimestamp(mtime).strftime("%m-%d %H:%M")
                
                if f.endswith(".xlsx"):
                    df = pd.read_excel(path)
                elif f.endswith(".csv"):
                    df = pd.read_csv(path)
                else:
                    df = pd.read_json(path)
                df = normalize_df_columns(df)

                notes = len(df)
                images = int(df['image_count'].sum()) if 'image_count' in df.columns else 0
                
                self.history_tree.insert("", tk.END, values=(time_str, keyword, notes, images, f))
            except:
                continue
    
    # === 工具方法 ===
    def _zip_images(self):
        """打包图片"""
        if not os.path.exists("images"):
            messagebox.showinfo("提示", "没有图片目录")
            return
        
        output = f"data/图片打包_{int(time.time())}.zip"
        os.makedirs("data", exist_ok=True)
        
        with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as zf:
            for root, dirs, files in os.walk("images"):
                for file in files:
                    filepath = os.path.join(root, file)
                    arcname = os.path.relpath(filepath, "images")
                    zf.write(filepath, arcname)
        
        messagebox.showinfo("完成", f"图片已打包: {output}")
    
    def _open_data_dir(self):
        os.makedirs("data", exist_ok=True)
        os.startfile(os.path.abspath("data"))
    
    def _open_log_file(self):
        if os.path.exists(self.config.log_file):
            os.startfile(self.config.log_file)
        else:
            messagebox.showinfo("提示", "日志文件不存在")
    
    def _clear_log_file(self):
        if os.path.exists(self.config.log_file):
            os.remove(self.config.log_file)
            messagebox.showinfo("完成", "日志已清空")
    
    def _browse_db_path(self):
        path = filedialog.asksaveasfilename(
            defaultextension=".db",
            filetypes=[("SQLite数据库", "*.db")]
        )
        if path:
            self.db_path_var.set(path)
            self.log("数据库路径已修改，重启程序后生效", "WARNING")
    
    def _on_closing(self):
        """程序退出时的处理"""
        # 保存窗口位置与大小。
        # 仅在普通(normal)状态下保存：最大化时 winfo 返回的是全屏尺寸
        # (如 2560x1225)，存下来会在下次启动恢复成"伪全屏"浮窗——
        # settings 里那组坏几何正是这么来的。
        try:
            if self.root.state() == 'normal':
                self.config.window_x = self.root.winfo_x()
                self.config.window_y = self.root.winfo_y()
                self.config.window_width = self.root.winfo_width()
                self.config.window_height = self.root.winfo_height()
        except tk.TclError:
            pass
        
        # 保存当前配置
        self._save_gui_settings()
        self.config.save_to_file()
        
        if self.is_running:
            if messagebox.askyesno("确认", "爬取正在进行中，确定要退出吗？"):
                self.should_stop = True
                # 等待一下让爬取线程有机会停止
                self.root.after(500, self._force_close)
            return
        self._force_close()
    
    def _force_close(self):
        """强制关闭程序"""
        # 关闭浏览器
        if self.browser_page:
            try:
                self.browser_page.quit()
            except Exception:
                pass
        # 关闭下载器
        try:
            self.downloader.close()
        except Exception:
            pass
        # 退出程序
        self.root.destroy()
    
    def run(self):
        self.root.mainloop()


if __name__ == '__main__':
    app = CrawlerApp()
    app.run()
