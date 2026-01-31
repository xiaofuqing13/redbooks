# -*- coding: utf-8 -*-
"""
小红书爬虫终极版 v5.0
功能：视频下载、评论爬取、正文内容、标签提取、博主爬取、数据可视化、Cookie管理
优化：性能提升、稳定性增强、UI改进
"""

import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext, filedialog
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
from DrissionPage import ChromiumPage

# 版本信息
VERSION = "5.0"
APP_NAME = f"小红书爬虫终极版 v{VERSION}"

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
    
    # 爬取内容选项
    download_images: bool = True
    download_videos: bool = False
    get_all_images: bool = False
    get_content: bool = True
    get_tags: bool = True
    get_publish_time: bool = True
    get_comments: bool = False
    comments_count: int = 10
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
    
    # 导出选项
    export_format: str = "xlsx"
    export_to_db: bool = False
    db_path: str = "data/redbook.db"
    
    # 速度控制（元组默认值需要用field）
    click_delay: Tuple[float, float] = field(default_factory=lambda: (0.2, 0.4))
    scroll_delay: Tuple[float, float] = field(default_factory=lambda: (0.3, 0.5))
    
    # Cookie和日志
    save_cookies: bool = True
    cookies_file: str = "data/cookies.json"
    log_to_file: bool = True
    log_file: str = "data/crawler.log"


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
                like_count INTEGER,
                collect_count INTEGER,
                comment_count INTEGER,
                note_type TEXT,
                note_link TEXT,
                image_urls TEXT,
                video_url TEXT,
                comments TEXT,
                keyword TEXT,
                crawl_time TEXT
            )
        ''')
        
        conn.commit()
        conn.close()
    
    def insert_note(self, note_data):
        """插入笔记"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                INSERT OR REPLACE INTO notes 
                (note_id, title, author, content, tags, publish_time, 
                 like_count, collect_count, comment_count, note_type, note_link,
                 image_urls, video_url, comments, keyword, crawl_time)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                note_data.get('note_id', ''),
                note_data.get('title', ''),
                note_data.get('author', ''),
                note_data.get('content', ''),
                json.dumps(note_data.get('tags', []), ensure_ascii=False),
                note_data.get('publish_time', ''),
                note_data.get('like_count', 0),
                note_data.get('collect_count', 0),
                note_data.get('comment_count', 0),
                note_data.get('note_type', ''),
                note_data.get('note_link', ''),
                json.dumps(note_data.get('image_urls', []), ensure_ascii=False),
                note_data.get('video_url', ''),
                json.dumps(note_data.get('comments', []), ensure_ascii=False),
                note_data.get('keyword', ''),
                datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            ))
            conn.commit()
            return True
        except Exception as e:
            return False
        finally:
            conn.close()
    
    def get_existing_note_ids(self, keyword):
        """获取已存在的笔记ID（用于增量更新）"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('SELECT note_id FROM notes WHERE keyword = ?', (keyword,))
        ids = set(row[0] for row in cursor.fetchall())
        conn.close()
        return ids


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
    
    @property
    def session(self) -> requests.Session:
        """懒加载Session，复用连接"""
        if self._session is None:
            self._session = requests.Session()
            self._session.headers.update({
                'User-Agent': random.choice(self.USER_AGENTS),
                'Referer': 'https://www.xiaohongshu.com/',
                'Accept': 'image/webp,image/apng,image/*,*/*;q=0.8',
            })
        return self._session
    
    def _normalize_url(self, url: str) -> str:
        """标准化URL"""
        if not url:
            return ""
        if url.startswith('//'):
            return 'https:' + url
        if not url.startswith('http'):
            return 'https://' + url
        return url
    
    def download_file(self, url: str, local_path: str, 
                      stop_flag: Optional[Callable] = None,
                      min_size: int = 1024) -> Optional[str]:
        """下载单个文件"""
        url = self._normalize_url(url)
        if not url:
            return None
            
        for attempt in range(self.retry_times):
            if stop_flag and stop_flag():
                return None
            try:
                response = self.session.get(url, timeout=self.timeout, stream=True)
                response.raise_for_status()
                
                # 确保目录存在
                os.makedirs(os.path.dirname(local_path), exist_ok=True)
                
                # 流式写入
                total_size = 0
                with open(local_path, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=16384):
                        if stop_flag and stop_flag():
                            f.close()
                            if os.path.exists(local_path):
                                os.remove(local_path)
                            return None
                        if chunk:
                            f.write(chunk)
                            total_size += len(chunk)
                
                # 检查文件大小
                if total_size < min_size:
                    os.remove(local_path)
                    return None
                
                self._stats['success'] += 1
                self._stats['bytes'] += total_size
                return local_path
                
            except requests.Timeout:
                if attempt < self.retry_times - 1:
                    time.sleep(0.2 * (attempt + 1))
            except Exception:
                if attempt < self.retry_times - 1:
                    time.sleep(0.1)
        
        self._stats['failed'] += 1
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
        return self._stats.copy()
    
    def reset_stats(self):
        """重置统计"""
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
                df['like_count'].hist(bins=20, ax=ax, color='#ff6b6b', edgecolor='white')
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
                       colors=['#4ecdc4', '#ff6b6b', '#ffe66d'])
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
                ax.barh(range(len(top10)), top10['like_count'], color='#667eea')
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
                    doc.add_paragraph(f"• {title}... (👍 {likes})")
            
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            doc.save(output_path)
            return output_path
        except:
            return None


class CrawlerApp:
    """爬虫GUI应用"""
    
    def __init__(self):
        self.root = tk.Tk()
        self.root.title(APP_NAME)
        self.root.geometry("980x850")
        self.root.minsize(800, 600)
        
        self.config = CrawlerConfig()
        self.downloader = MediaDownloader()
        self.cookie_mgr = CookieManager(self.config.cookies_file)
        self.file_logger = FileLogger(self.config.log_file)
        self.db_mgr = DatabaseManager(self.config.db_path)
        
        self.log_queue = queue.Queue()
        self.is_running = False
        self.should_stop = False
        self.all_notes_data = []
        
        self._create_ui()
        self._start_log_consumer()
    
    def _create_ui(self):
        """创建界面"""
        notebook = ttk.Notebook(self.root)
        notebook.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # 创建各标签页
        main_page = ttk.Frame(notebook, padding="10")
        content_page = ttk.Frame(notebook, padding="10")
        analysis_page = ttk.Frame(notebook, padding="10")
        settings_page = ttk.Frame(notebook, padding="10")
        
        notebook.add(main_page, text="🔍 搜索爬取")
        notebook.add(content_page, text="📝 内容选项")
        notebook.add(analysis_page, text="📊 数据分析")
        notebook.add(settings_page, text="⚙️ 高级设置")
        
        self._create_main_page(main_page)
        self._create_content_page(content_page)
        self._create_analysis_page(analysis_page)
        self._create_settings_page(settings_page)
    
    def _create_main_page(self, parent):
        """创建主页面"""
        # === 爬取模式选择 ===
        mode_frame = ttk.LabelFrame(parent, text="爬取模式", padding="10")
        mode_frame.pack(fill=tk.X, pady=(0, 10))
        
        self.crawl_type_var = tk.StringVar(value="keyword")
        
        mode_row = ttk.Frame(mode_frame)
        mode_row.pack(fill=tk.X)
        
        ttk.Radiobutton(mode_row, text="🔍 关键词搜索", variable=self.crawl_type_var, 
                       value="keyword", command=self._on_mode_change).pack(side=tk.LEFT, padx=(0, 15))
        ttk.Radiobutton(mode_row, text="👤 博主主页", variable=self.crawl_type_var, 
                       value="blogger", command=self._on_mode_change).pack(side=tk.LEFT, padx=(0, 15))
        ttk.Radiobutton(mode_row, text="🔥 热门榜单", variable=self.crawl_type_var, 
                       value="hot", command=self._on_mode_change).pack(side=tk.LEFT)
        
        # === 搜索配置 ===
        self.search_frame = ttk.LabelFrame(parent, text="搜索配置", padding="10")
        self.search_frame.pack(fill=tk.X, pady=(0, 10))
        
        # 关键词输入
        row1 = ttk.Frame(self.search_frame)
        row1.pack(fill=tk.X, pady=2)
        
        ttk.Label(row1, text="搜索关键词:").pack(side=tk.LEFT)
        self.keyword_var = tk.StringVar()
        self.keyword_entry = ttk.Entry(row1, textvariable=self.keyword_var, width=40)
        self.keyword_entry.pack(side=tk.LEFT, padx=5)
        
        ttk.Label(row1, text="(多个用逗号分隔)", foreground="gray").pack(side=tk.LEFT)
        
        # 博主URL输入
        row1b = ttk.Frame(self.search_frame)
        row1b.pack(fill=tk.X, pady=2)
        
        ttk.Label(row1b, text="博主主页URL:").pack(side=tk.LEFT)
        self.blogger_url_var = tk.StringVar()
        self.blogger_entry = ttk.Entry(row1b, textvariable=self.blogger_url_var, width=50)
        self.blogger_entry.pack(side=tk.LEFT, padx=5)
        self.blogger_entry.config(state=tk.DISABLED)
        
        # 热门分类
        row1c = ttk.Frame(self.search_frame)
        row1c.pack(fill=tk.X, pady=2)
        
        ttk.Label(row1c, text="热门分类:").pack(side=tk.LEFT)
        self.hot_category_var = tk.StringVar(value="综合")
        self.hot_combo = ttk.Combobox(row1c, textvariable=self.hot_category_var,
                                      values=["综合", "美食", "穿搭", "美妆", "旅行", "家居", "数码"], 
                                      width=15, state="readonly")
        self.hot_combo.pack(side=tk.LEFT, padx=5)
        self.hot_combo.config(state=tk.DISABLED)
        
        # 数量配置
        row2 = ttk.Frame(self.search_frame)
        row2.pack(fill=tk.X, pady=5)
        
        ttk.Label(row2, text="滚动次数:").pack(side=tk.LEFT)
        self.scroll_var = tk.StringVar(value="10")
        ttk.Spinbox(row2, from_=1, to=100, textvariable=self.scroll_var, width=6).pack(side=tk.LEFT, padx=(2, 15))
        
        ttk.Label(row2, text="最多笔记:").pack(side=tk.LEFT)
        self.max_notes_var = tk.StringVar(value="30")
        ttk.Spinbox(row2, from_=1, to=500, textvariable=self.max_notes_var, width=6).pack(side=tk.LEFT, padx=(2, 15))
        
        ttk.Label(row2, text="并行下载:").pack(side=tk.LEFT)
        self.parallel_var = tk.StringVar(value="10")
        ttk.Spinbox(row2, from_=1, to=20, textvariable=self.parallel_var, width=6).pack(side=tk.LEFT)
        
        # === 筛选条件 ===
        filter_frame = ttk.LabelFrame(parent, text="筛选条件", padding="10")
        filter_frame.pack(fill=tk.X, pady=(0, 10))
        
        filter_row = ttk.Frame(filter_frame)
        filter_row.pack(fill=tk.X)
        
        ttk.Label(filter_row, text="点赞范围:").pack(side=tk.LEFT)
        self.min_likes_var = tk.StringVar(value="0")
        ttk.Entry(filter_row, textvariable=self.min_likes_var, width=8).pack(side=tk.LEFT, padx=2)
        ttk.Label(filter_row, text="-").pack(side=tk.LEFT)
        self.max_likes_var = tk.StringVar(value="999999")
        ttk.Entry(filter_row, textvariable=self.max_likes_var, width=8).pack(side=tk.LEFT, padx=(2, 15))
        
        ttk.Label(filter_row, text="笔记类型:").pack(side=tk.LEFT)
        self.note_type_var = tk.StringVar(value="全部")
        ttk.Combobox(filter_row, textvariable=self.note_type_var,
                    values=["全部", "图文", "视频"], width=8, state="readonly").pack(side=tk.LEFT, padx=(2, 15))
        
        ttk.Label(filter_row, text="时间范围:").pack(side=tk.LEFT)
        self.date_filter_var = tk.StringVar(value="全部")
        ttk.Combobox(filter_row, textvariable=self.date_filter_var,
                    values=["全部", "今天", "本周", "本月"], width=8, state="readonly").pack(side=tk.LEFT)
        
        # === 速度模式 ===
        speed_frame = ttk.LabelFrame(parent, text="速度模式", padding="10")
        speed_frame.pack(fill=tk.X, pady=(0, 10))
        
        self.crawl_mode_var = tk.StringVar(value="standard")
        speed_row = ttk.Frame(speed_frame)
        speed_row.pack(fill=tk.X)
        
        ttk.Radiobutton(speed_row, text="🐢 标准模式（完整数据）", variable=self.crawl_mode_var, 
                       value="standard").pack(side=tk.LEFT, padx=(0, 15))
        ttk.Radiobutton(speed_row, text="🐇 快速模式（减少等待）", variable=self.crawl_mode_var, 
                       value="fast").pack(side=tk.LEFT, padx=(0, 15))
        ttk.Radiobutton(speed_row, text="🚀 极速模式（列表直取）", variable=self.crawl_mode_var, 
                       value="turbo").pack(side=tk.LEFT)
        
        # === 控制按钮 ===
        btn_frame = ttk.Frame(parent)
        btn_frame.pack(fill=tk.X, pady=(0, 10))
        
        self.start_btn = ttk.Button(btn_frame, text="▶ 开始爬取", command=self._start_crawl, width=12)
        self.start_btn.pack(side=tk.LEFT, padx=(0, 5))
        
        self.stop_btn = ttk.Button(btn_frame, text="⏹ 停止", command=self._stop_crawl, state=tk.DISABLED, width=10)
        self.stop_btn.pack(side=tk.LEFT, padx=(0, 5))
        
        ttk.Button(btn_frame, text="🍪 使用已保存Cookie", command=self._use_saved_cookies, width=18).pack(side=tk.LEFT, padx=(0, 5))
        
        ttk.Button(btn_frame, text="📂 打开数据", command=self._open_data_dir, width=10).pack(side=tk.RIGHT)
        ttk.Button(btn_frame, text="📦 打包图片", command=self._zip_images, width=10).pack(side=tk.RIGHT, padx=(0, 5))
        
        # === 进度区域 ===
        progress_frame = ttk.LabelFrame(parent, text="运行状态", padding="10")
        progress_frame.pack(fill=tk.X, pady=(0, 10))
        
        prog_row = ttk.Frame(progress_frame)
        prog_row.pack(fill=tk.X)
        self.total_progress = ttk.Progressbar(prog_row, length=400, mode='determinate')
        self.total_progress.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10))
        self.progress_label = ttk.Label(prog_row, text="0%")
        self.progress_label.pack(side=tk.LEFT)
        
        stat_row = ttk.Frame(progress_frame)
        stat_row.pack(fill=tk.X, pady=5)
        
        self.status_var = tk.StringVar(value="就绪")
        ttk.Label(stat_row, text="状态:").pack(side=tk.LEFT)
        ttk.Label(stat_row, textvariable=self.status_var, foreground="blue").pack(side=tk.LEFT, padx=(5, 20))
        
        self.notes_var = tk.StringVar(value="笔记: 0")
        ttk.Label(stat_row, textvariable=self.notes_var).pack(side=tk.LEFT, padx=(0, 15))
        
        self.images_var = tk.StringVar(value="图片: 0")
        ttk.Label(stat_row, textvariable=self.images_var).pack(side=tk.LEFT, padx=(0, 15))
        
        self.videos_var = tk.StringVar(value="视频: 0")
        ttk.Label(stat_row, textvariable=self.videos_var).pack(side=tk.LEFT, padx=(0, 15))
        
        self.time_var = tk.StringVar(value="用时: 0秒")
        ttk.Label(stat_row, textvariable=self.time_var).pack(side=tk.LEFT)
        
        # === 日志区域 ===
        log_frame = ttk.LabelFrame(parent, text="运行日志", padding="5")
        log_frame.pack(fill=tk.BOTH, expand=True)
        
        self.log_text = scrolledtext.ScrolledText(log_frame, height=8, state=tk.DISABLED)
        self.log_text.pack(fill=tk.BOTH, expand=True)
        
        self.log_text.tag_config("INFO", foreground="black")
        self.log_text.tag_config("SUCCESS", foreground="green")
        self.log_text.tag_config("WARNING", foreground="orange")
        self.log_text.tag_config("ERROR", foreground="red")
    
    def _create_content_page(self, parent):
        """创建内容选项页面"""
        # === 基础内容 ===
        basic_frame = ttk.LabelFrame(parent, text="基础内容", padding="10")
        basic_frame.pack(fill=tk.X, pady=(0, 10))
        
        row1 = ttk.Frame(basic_frame)
        row1.pack(fill=tk.X, pady=2)
        
        self.get_content_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(row1, text="📝 获取笔记正文内容", variable=self.get_content_var).pack(side=tk.LEFT, padx=(0, 20))
        
        self.get_tags_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(row1, text="🏷️ 提取话题标签 (#xxx)", variable=self.get_tags_var).pack(side=tk.LEFT, padx=(0, 20))
        
        self.get_time_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(row1, text="📅 获取发布时间", variable=self.get_time_var).pack(side=tk.LEFT)
        
        row2 = ttk.Frame(basic_frame)
        row2.pack(fill=tk.X, pady=2)
        
        self.get_interactions_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(row2, text="💝 获取互动数据（点赞/收藏/评论数）", variable=self.get_interactions_var).pack(side=tk.LEFT)
        
        # === 图片视频 ===
        media_frame = ttk.LabelFrame(parent, text="图片/视频", padding="10")
        media_frame.pack(fill=tk.X, pady=(0, 10))
        
        row3 = ttk.Frame(media_frame)
        row3.pack(fill=tk.X, pady=2)
        
        self.download_images_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(row3, text="🖼️ 下载图片", variable=self.download_images_var).pack(side=tk.LEFT, padx=(0, 20))
        
        self.get_all_images_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(row3, text="📸 获取全部图片（切换轮播）", variable=self.get_all_images_var).pack(side=tk.LEFT, padx=(0, 20))
        
        self.download_videos_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(row3, text="🎬 下载视频", variable=self.download_videos_var).pack(side=tk.LEFT)
        
        # === 评论 ===
        comment_frame = ttk.LabelFrame(parent, text="评论爬取", padding="10")
        comment_frame.pack(fill=tk.X, pady=(0, 10))
        
        row4 = ttk.Frame(comment_frame)
        row4.pack(fill=tk.X, pady=2)
        
        self.get_comments_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(row4, text="💬 获取热门评论", variable=self.get_comments_var).pack(side=tk.LEFT, padx=(0, 20))
        
        ttk.Label(row4, text="评论数量:").pack(side=tk.LEFT)
        self.comments_count_var = tk.StringVar(value="10")
        ttk.Spinbox(row4, from_=1, to=50, textvariable=self.comments_count_var, width=6).pack(side=tk.LEFT, padx=5)
        
        # === 导出格式 ===
        export_frame = ttk.LabelFrame(parent, text="导出设置", padding="10")
        export_frame.pack(fill=tk.X, pady=(0, 10))
        
        row5 = ttk.Frame(export_frame)
        row5.pack(fill=tk.X, pady=2)
        
        ttk.Label(row5, text="导出格式:").pack(side=tk.LEFT)
        self.export_format_var = tk.StringVar(value="xlsx")
        ttk.Combobox(row5, textvariable=self.export_format_var,
                    values=["xlsx", "csv", "json"], width=10, state="readonly").pack(side=tk.LEFT, padx=(5, 20))
        
        self.export_db_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(row5, text="💾 同时保存到SQLite数据库", variable=self.export_db_var).pack(side=tk.LEFT)
        
        # === 快捷预设 ===
        preset_frame = ttk.LabelFrame(parent, text="快捷预设", padding="10")
        preset_frame.pack(fill=tk.X, pady=(0, 10))
        
        preset_row = ttk.Frame(preset_frame)
        preset_row.pack(fill=tk.X)
        
        ttk.Button(preset_row, text="🚀 极速采集", command=self._preset_turbo, width=12).pack(side=tk.LEFT, padx=(0, 10))
        ttk.Button(preset_row, text="📊 完整数据", command=self._preset_complete, width=12).pack(side=tk.LEFT, padx=(0, 10))
        ttk.Button(preset_row, text="📸 只下图片", command=self._preset_images, width=12).pack(side=tk.LEFT, padx=(0, 10))
        ttk.Button(preset_row, text="🎬 只下视频", command=self._preset_videos, width=12).pack(side=tk.LEFT, padx=(0, 10))
        ttk.Button(preset_row, text="📝 只要文本", command=self._preset_text, width=12).pack(side=tk.LEFT)
    
    def _create_analysis_page(self, parent):
        """创建数据分析页面"""
        # === 分析工具 ===
        tools_frame = ttk.LabelFrame(parent, text="分析工具", padding="10")
        tools_frame.pack(fill=tk.X, pady=(0, 10))
        
        row1 = ttk.Frame(tools_frame)
        row1.pack(fill=tk.X, pady=5)
        
        ttk.Button(row1, text="📊 生成统计图表", command=self._generate_charts, width=16).pack(side=tk.LEFT, padx=(0, 10))
        ttk.Button(row1, text="☁️ 生成词云", command=self._generate_wordcloud, width=16).pack(side=tk.LEFT, padx=(0, 10))
        ttk.Button(row1, text="📄 生成分析报告", command=self._generate_report, width=16).pack(side=tk.LEFT, padx=(0, 10))
        ttk.Button(row1, text="🔄 合并所有数据", command=self._merge_data, width=16).pack(side=tk.LEFT)
        
        # === 统计仪表盘 ===
        dashboard_frame = ttk.LabelFrame(parent, text="统计仪表盘", padding="10")
        dashboard_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        
        # 统计卡片网格
        stats_grid = ttk.Frame(dashboard_frame)
        stats_grid.pack(fill=tk.X, pady=10)
        
        self.dashboard_labels = {}
        stats_items = [
            ("total_notes", "📝 总笔记", "0"),
            ("total_likes", "👍 总点赞", "0"),
            ("avg_likes", "📊 平均点赞", "0"),
            ("max_likes", "🔥 最高点赞", "0"),
            ("total_collects", "💾 总收藏", "0"),
            ("total_comments", "💬 总评论", "0"),
            ("image_notes", "🖼️ 图文笔记", "0"),
            ("video_notes", "🎬 视频笔记", "0"),
        ]
        
        for i, (key, label, default) in enumerate(stats_items):
            row = i // 4
            col = i % 4
            
            card = ttk.Frame(stats_grid, relief="solid", borderwidth=1)
            card.grid(row=row, column=col, padx=10, pady=5, sticky="nsew")
            
            ttk.Label(card, text=label, font=("", 9)).pack(pady=(5, 0))
            self.dashboard_labels[key] = ttk.Label(card, text=default, font=("", 14, "bold"), foreground="#667eea")
            self.dashboard_labels[key].pack(pady=(0, 5))
        
        for i in range(4):
            stats_grid.columnconfigure(i, weight=1)
        
        # === 历史记录 ===
        history_frame = ttk.LabelFrame(parent, text="历史记录", padding="10")
        history_frame.pack(fill=tk.BOTH, expand=True)
        
        columns = ("时间", "关键词", "笔记数", "图片数", "文件")
        self.history_tree = ttk.Treeview(history_frame, columns=columns, show="headings", height=8)
        
        for col in columns:
            self.history_tree.heading(col, text=col)
            self.history_tree.column(col, width=100)
        
        scrollbar = ttk.Scrollbar(history_frame, orient=tk.VERTICAL, command=self.history_tree.yview)
        self.history_tree.configure(yscrollcommand=scrollbar.set)
        
        self.history_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # 刷新历史
        self._refresh_history()
    
    def _create_settings_page(self, parent):
        """创建设置页面"""
        # === Cookie管理 ===
        cookie_frame = ttk.LabelFrame(parent, text="Cookie管理", padding="10")
        cookie_frame.pack(fill=tk.X, pady=(0, 10))
        
        row1 = ttk.Frame(cookie_frame)
        row1.pack(fill=tk.X, pady=2)
        
        self.save_cookies_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(row1, text="登录后自动保存Cookie", variable=self.save_cookies_var).pack(side=tk.LEFT, padx=(0, 20))
        
        self.cookie_status_var = tk.StringVar(value="未检测到Cookie")
        ttk.Label(row1, textvariable=self.cookie_status_var, foreground="gray").pack(side=tk.LEFT, padx=(0, 10))
        
        ttk.Button(row1, text="清除Cookie", command=self._clear_cookies, width=10).pack(side=tk.LEFT)
        
        self._check_cookie_status()
        
        # === 日志设置 ===
        log_frame = ttk.LabelFrame(parent, text="日志设置", padding="10")
        log_frame.pack(fill=tk.X, pady=(0, 10))
        
        row2 = ttk.Frame(log_frame)
        row2.pack(fill=tk.X, pady=2)
        
        self.log_to_file_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(row2, text="保存日志到文件", variable=self.log_to_file_var).pack(side=tk.LEFT, padx=(0, 20))
        
        ttk.Button(row2, text="打开日志文件", command=self._open_log_file).pack(side=tk.LEFT, padx=(0, 10))
        ttk.Button(row2, text="清空日志", command=self._clear_log_file).pack(side=tk.LEFT)
        
        # === 速度控制 ===
        speed_frame = ttk.LabelFrame(parent, text="速度控制", padding="10")
        speed_frame.pack(fill=tk.X, pady=(0, 10))
        
        row3 = ttk.Frame(speed_frame)
        row3.pack(fill=tk.X, pady=2)
        
        ttk.Label(row3, text="点击延迟(秒):").pack(side=tk.LEFT)
        self.click_min_var = tk.StringVar(value="0.3")
        ttk.Entry(row3, textvariable=self.click_min_var, width=5).pack(side=tk.LEFT, padx=2)
        ttk.Label(row3, text="-").pack(side=tk.LEFT)
        self.click_max_var = tk.StringVar(value="0.5")
        ttk.Entry(row3, textvariable=self.click_max_var, width=5).pack(side=tk.LEFT, padx=(2, 20))
        
        ttk.Label(row3, text="滚动延迟(秒):").pack(side=tk.LEFT)
        self.scroll_min_var = tk.StringVar(value="0.4")
        ttk.Entry(row3, textvariable=self.scroll_min_var, width=5).pack(side=tk.LEFT, padx=2)
        ttk.Label(row3, text="-").pack(side=tk.LEFT)
        self.scroll_max_var = tk.StringVar(value="0.6")
        ttk.Entry(row3, textvariable=self.scroll_max_var, width=5).pack(side=tk.LEFT)
        
        # === 反爬设置 ===
        anti_frame = ttk.LabelFrame(parent, text="反爬虫设置", padding="10")
        anti_frame.pack(fill=tk.X, pady=(0, 10))
        
        row4 = ttk.Frame(anti_frame)
        row4.pack(fill=tk.X, pady=2)
        
        self.random_delay_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(row4, text="随机延迟（模拟人类行为）", variable=self.random_delay_var).pack(side=tk.LEFT, padx=(0, 20))
        
        self.random_scroll_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(row4, text="随机滚动距离", variable=self.random_scroll_var).pack(side=tk.LEFT)
        
        # === 数据库设置 ===
        db_frame = ttk.LabelFrame(parent, text="数据库设置", padding="10")
        db_frame.pack(fill=tk.X, pady=(0, 10))
        
        row5 = ttk.Frame(db_frame)
        row5.pack(fill=tk.X, pady=2)
        
        ttk.Label(row5, text="数据库路径:").pack(side=tk.LEFT)
        self.db_path_var = tk.StringVar(value="data/redbook.db")
        ttk.Entry(row5, textvariable=self.db_path_var, width=40).pack(side=tk.LEFT, padx=5)
        
        ttk.Button(row5, text="浏览", command=self._browse_db_path).pack(side=tk.LEFT)
    
    # === 事件处理 ===
    def _on_mode_change(self):
        """切换爬取模式"""
        mode = self.crawl_type_var.get()
        
        # 禁用/启用相应输入框
        self.keyword_entry.config(state=tk.NORMAL if mode == "keyword" else tk.DISABLED)
        self.blogger_entry.config(state=tk.NORMAL if mode == "blogger" else tk.DISABLED)
        self.hot_combo.config(state="readonly" if mode == "hot" else tk.DISABLED)
    
    def _check_cookie_status(self):
        """检查Cookie状态"""
        if self.cookie_mgr.exists():
            saved_time = self.cookie_mgr.get_saved_time()
            if saved_time and saved_time != '未知':
                try:
                    dt = datetime.fromisoformat(saved_time)
                    time_str = dt.strftime("%m-%d %H:%M")
                    self.cookie_status_var.set(f"✅ Cookie已保存 ({time_str})")
                except Exception:
                    self.cookie_status_var.set("✅ 已保存Cookie")
            else:
                self.cookie_status_var.set("✅ 已保存Cookie")
        else:
            self.cookie_status_var.set("❌ 未检测到Cookie")
    
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
        self.download_images_var.set(True)
        self.get_all_images_var.set(False)
        self.download_videos_var.set(False)
        self.get_content_var.set(False)
        self.get_comments_var.set(False)
        self.log("已应用极速采集预设", "SUCCESS")
    
    def _preset_complete(self):
        self.crawl_mode_var.set("standard")
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
    def log(self, message, level="INFO"):
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_queue.put((f"[{timestamp}] {message}\n", level))
        
        if self.config.log_to_file:
            self.file_logger.log(message, level)
    
    def _start_log_consumer(self):
        def consume():
            try:
                while True:
                    msg, level = self.log_queue.get_nowait()
                    self.log_text.config(state=tk.NORMAL)
                    self.log_text.insert(tk.END, msg, level)
                    self.log_text.see(tk.END)
                    self.log_text.config(state=tk.DISABLED)
            except queue.Empty:
                pass
            self.root.after(100, consume)
        self.root.after(100, consume)
    
    def _update_ui(self, **kwargs):
        if "status" in kwargs:
            self.status_var.set(kwargs["status"])
        if "notes" in kwargs:
            self.notes_var.set(kwargs["notes"])
        if "images" in kwargs:
            self.images_var.set(kwargs["images"])
        if "videos" in kwargs:
            self.videos_var.set(kwargs["videos"])
        if "time" in kwargs:
            self.time_var.set(kwargs["time"])
        if "progress" in kwargs:
            self.total_progress["value"] = kwargs["progress"]
            self.progress_label.config(text=f"{int(kwargs['progress'])}%")
    
    def _update_dashboard(self, stats):
        for key, value in stats.items():
            if key in self.dashboard_labels:
                self.dashboard_labels[key].config(text=str(int(value) if isinstance(value, float) else value))
    
    # === 爬取控制 ===
    def _start_crawl(self):
        if self.is_running:
            return
        
        # 检查输入
        crawl_type = self.crawl_type_var.get()
        if crawl_type == "keyword":
            keyword = self.keyword_var.get().strip()
            if not keyword:
                messagebox.showwarning("提示", "请输入搜索关键词")
                return
        elif crawl_type == "blogger":
            blogger_url = self.blogger_url_var.get().strip()
            if not blogger_url:
                messagebox.showwarning("提示", "请输入博主主页URL")
                return
        
        self._get_config()
        self._run_crawl()
    
    def _stop_crawl(self):
        self.should_stop = True
        self.log("正在停止...", "WARNING")
        self._update_ui(status="正在停止...")
        self.root.update()
    
    def _get_config(self):
        """获取配置"""
        self.config.keyword = self.keyword_var.get().strip()
        self.config.crawl_type = self.crawl_type_var.get()
        self.config.blogger_url = self.blogger_url_var.get().strip()
        self.config.scroll_times = int(self.scroll_var.get())
        self.config.max_notes = int(self.max_notes_var.get())
        self.config.parallel_downloads = int(self.parallel_var.get())
        self.config.crawl_mode = self.crawl_mode_var.get()
        
        self.config.download_images = self.download_images_var.get()
        self.config.download_videos = self.download_videos_var.get()
        self.config.get_all_images = self.get_all_images_var.get()
        self.config.get_content = self.get_content_var.get()
        self.config.get_tags = self.get_tags_var.get()
        self.config.get_publish_time = self.get_time_var.get()
        self.config.get_comments = self.get_comments_var.get()
        self.config.comments_count = int(self.comments_count_var.get())
        self.config.get_interactions = self.get_interactions_var.get()
        
        self.config.min_likes = int(self.min_likes_var.get() or 0)
        self.config.max_likes = int(self.max_likes_var.get() or 999999)
        self.config.note_type_filter = self.note_type_var.get()
        
        self.config.export_format = self.export_format_var.get()
        self.config.export_to_db = self.export_db_var.get()
        self.config.save_cookies = self.save_cookies_var.get()
        self.config.log_to_file = self.log_to_file_var.get()
        
        self.config.click_delay = (float(self.click_min_var.get()), float(self.click_max_var.get()))
        self.config.scroll_delay = (float(self.scroll_min_var.get()), float(self.scroll_max_var.get()))
        
        self.downloader.max_workers = self.config.parallel_downloads
    
    def _run_crawl(self):
        self.is_running = True
        self.should_stop = False
        self.all_notes_data = []
        
        self.start_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.NORMAL)
        
        thread = threading.Thread(target=self._crawl_thread, daemon=True)
        thread.start()
    
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
            # 处理多关键词
            keywords = [k.strip() for k in self.config.keyword.split(',') if k.strip()]
            if not keywords:
                keywords = [self.config.keyword] if self.config.keyword else []
            
            if not keywords and self.config.crawl_type == "keyword":
                self.log("请输入搜索关键词", "ERROR")
                return
            
            for kw_idx, keyword in enumerate(keywords):
                if self.should_stop:
                    self.log("用户停止爬取", "WARNING")
                    break
                
                if error_count >= MAX_ERRORS:
                    self.log(f"连续错误超过{MAX_ERRORS}次，停止爬取", "ERROR")
                    break
                
                self.log(f"开始爬取关键词 [{kw_idx+1}/{len(keywords)}]: {keyword}", "INFO")
                
                # 初始化浏览器
                if page is None:
                    try:
                        page = ChromiumPage()
                        self.log("浏览器启动成功", "SUCCESS")
                    except Exception as e:
                        self.log(f"浏览器启动失败: {e}", "ERROR")
                        return
                    
                    # 尝试加载Cookie
                    if self.cookie_mgr.exists():
                        self.log("加载已保存的Cookie...", "INFO")
                        saved_time = self.cookie_mgr.get_saved_time()
                        if saved_time:
                            self.log(f"Cookie保存时间: {saved_time}", "INFO")
                        
                        page.get('https://www.xiaohongshu.com')
                        self.cookie_mgr.load(page)
                        time.sleep(1.5)
                        page.refresh()
                        time.sleep(1.5)
                        
                        if self._check_login(page):
                            self.log("Cookie有效，自动登录成功", "SUCCESS")
                        else:
                            self.log("Cookie已过期，需要重新登录", "WARNING")
                            self._wait_for_login(page)
                    else:
                        page.get('https://www.xiaohongshu.com')
                        time.sleep(1.5)
                        self._wait_for_login(page)
                
                if self.should_stop:
                    break
                
                try:
                    # 访问搜索页
                    keyword_code = quote(quote(keyword.encode('utf-8')).encode('gb2312'))
                    search_url = f'https://www.xiaohongshu.com/search_result?keyword={keyword_code}&source=web_search_result_notes'
                    
                    self.log(f"访问搜索页面...", "INFO")
                    self._update_ui(status=f"搜索: {keyword}")
                    page.get(search_url)
                    time.sleep(1.5)
                    
                    # 智能滚动加载
                    prev_count = 0
                    for i in range(self.config.scroll_times):
                        if self.should_stop:
                            break
                        self._update_ui(status=f"加载中 {i+1}/{self.config.scroll_times}")
                        
                        # 随机滚动距离，模拟人类行为
                        page.scroll.to_bottom()
                        time.sleep(random.uniform(*self.config.scroll_delay))
                        
                        # 检测是否加载了新内容
                        curr_count = len(page.eles("xpath://section", timeout=0.5))
                        if curr_count >= self.config.max_notes:
                            self.log(f"已加载足够笔记 ({curr_count})", "INFO")
                            break
                        if curr_count == prev_count and i > 3:
                            # 连续两次没有新内容，可能到底了
                            break
                        prev_count = curr_count
                    
                    if self.should_stop:
                        break
                    
                    # 获取笔记列表
                    note_elements = page.eles("xpath://section")[:self.config.max_notes]
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
                    filename = self._save_data(self.all_notes_data, keywords[0] if len(keywords) == 1 else "多关键词")
                    self.log(f"数据已保存: {filename}", "SUCCESS")
                    
                    # 更新仪表盘
                    df = pd.DataFrame(self.all_notes_data)
                    stats = DataAnalyzer.generate_stats(df)
                    self.root.after(0, lambda s=stats: self._update_dashboard(s))
                except Exception as e:
                    self.log(f"保存数据失败: {e}", "ERROR")
            
            # 保存Cookie
            if page and self.config.save_cookies:
                try:
                    if self.cookie_mgr.save(page):
                        self.log("Cookie已保存，下次可自动登录", "SUCCESS")
                        self.root.after(0, self._check_cookie_status)
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
            self.root.after(0, self._refresh_history)
            
        except InterruptedError:
            self.log("爬取已取消", "WARNING")
        except Exception as e:
            self.log(f"严重错误: {str(e)}", "ERROR")
            import traceback
            self.file_logger.log(traceback.format_exc(), "ERROR")
        finally:
            # 清理资源
            if page:
                try:
                    page.quit()
                except Exception:
                    pass
            
            # 关闭下载器
            self.downloader.close()
            self.downloader.reset_stats()
            
            self.is_running = False
            self.root.after(0, lambda: self.start_btn.config(state=tk.NORMAL))
            self.root.after(0, lambda: self.stop_btn.config(state=tk.DISABLED))
    
    def _check_login(self, page):
        """检查是否已登录"""
        try:
            # 检查是否有登录弹窗
            login_popup = page.ele('xpath://div[contains(@class, "login")]', timeout=1)
            return login_popup is None
        except:
            return True
    
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
        
        self.root.after(0, show_dialog)
        login_event.wait()
        
        if cancelled[0]:
            raise InterruptedError("用户取消")
    
    def _standard_crawl(self, page, note_elements, keyword: str, start_time: float) -> Tuple[int, int, int]:
        """标准模式爬取（优化版，增强页面状态检查）"""
        success = 0
        images = 0
        videos = 0
        total = len(note_elements)
        images_dir = f"images/{keyword}"
        timestamp = int(time.time())
        consecutive_fails = 0
        MAX_CONSECUTIVE_FAILS = 3
        
        # 保存搜索页URL用于恢复
        keyword_code = quote(quote(keyword.encode('utf-8')).encode('gb2312'))
        search_url = f'https://www.xiaohongshu.com/search_result?keyword={keyword_code}&source=web_search_result_notes'
        
        for idx in range(total):
            if self.should_stop:
                break
            
            # 检查是否还在小红书页面
            current_url = page.url or ""
            if 'xiaohongshu.com' not in current_url:
                self.log("检测到页面跳转，正在恢复...", "WARNING")
                try:
                    page.get(search_url)
                    time.sleep(2)
                    # 重新滚动加载
                    for _ in range(3):
                        page.scroll.to_bottom()
                        time.sleep(0.5)
                except Exception as e:
                    self.log(f"恢复失败: {e}", "ERROR")
                    break
            
            # 连续失败检查 - 改进恢复逻辑
            if consecutive_fails >= MAX_CONSECUTIVE_FAILS:
                self.log(f"连续{MAX_CONSECUTIVE_FAILS}次失败，重新加载页面", "WARNING")
                try:
                    # 先尝试关闭可能的弹窗
                    page.actions.key_down('Escape').key_up('Escape')
                    time.sleep(0.3)
                    
                    # 检查是否需要重新加载搜索页
                    if 'search_result' not in (page.url or ""):
                        page.get(search_url)
                        time.sleep(2)
                        for _ in range(3):
                            page.scroll.to_bottom()
                            time.sleep(0.5)
                except Exception:
                    pass
                consecutive_fails = 0
            
            elapsed = int(time.time() - start_time)
            progress = (idx / total) * 100
            self._update_ui(
                status=f"爬取 {idx+1}/{total}",
                notes=f"笔记: {success}",
                images=f"图片: {images}",
                videos=f"视频: {videos}",
                time=f"用时: {elapsed}秒",
                progress=progress
            )
            
            try:
                # 确保在搜索结果页
                if 'search_result' not in (page.url or ""):
                    self.log("不在搜索页，跳过", "WARNING")
                    consecutive_fails += 1
                    continue
                
                # 重新获取元素列表（页面可能有变化）
                elements = page.eles("xpath://section", timeout=1)
                if not elements or idx >= len(elements):
                    self.log(f"笔记 {idx+1} 不存在，跳过", "WARNING")
                    consecutive_fails += 1
                    continue
                
                # 滚动到可见并点击
                elem = elements[idx]
                elem.scroll.to_see()
                time.sleep(0.05)
                
                # 记录点击前的URL
                url_before = page.url
                elem.click()
                time.sleep(random.uniform(*self.config.click_delay))
                
                # 检查点击后是否打开了详情弹窗（URL应该变成/explore/xxx）
                url_after = page.url or ""
                if '/explore/' not in url_after and url_after == url_before:
                    # 弹窗可能没打开，等待一下
                    time.sleep(0.3)
                
                # 提取数据
                note_data = self._extract_full_note(page, idx, images_dir, timestamp, keyword)
                
                if note_data and note_data.get('title'):
                    self.all_notes_data.append(note_data)
                    success += 1
                    images += note_data.get('image_count', 0)
                    videos += 1 if note_data.get('video_url') else 0
                    consecutive_fails = 0
                    
                    # 保存到数据库
                    if self.config.export_to_db:
                        self.db_mgr.insert_note(note_data)
                    
                    # 显示简短日志
                    title = note_data.get('title', '')[:25]
                    likes = note_data.get('like_count', 0)
                    self.log(f"[{idx+1}] {title}... 👍{likes}", "SUCCESS")
                else:
                    consecutive_fails += 1
                
                # 关闭详情页 - 多次尝试确保关闭
                for _ in range(2):
                    try:
                        page.actions.key_down('Escape').key_up('Escape')
                        time.sleep(0.1)
                        # 检查是否回到搜索页
                        if 'search_result' in (page.url or ""):
                            break
                    except Exception:
                        pass
                
            except Exception as e:
                consecutive_fails += 1
                error_msg = str(e)[:50] if str(e) else "未知错误"
                self.log(f"笔记 {idx+1} 失败: {error_msg}", "ERROR")
                
                # 尝试恢复
                try:
                    page.actions.key_down('Escape').key_up('Escape')
                    time.sleep(0.2)
                except Exception:
                    pass
        
        return success, images, videos
    
    def _fast_crawl(self, page, note_elements, keyword, start_time):
        """极速模式爬取"""
        records = []
        images_dir = f"images/{keyword}"
        timestamp = int(time.time())
        total = len(note_elements)
        
        download_tasks = []
        
        for idx in range(total):
            if self.should_stop:
                break
            
            self._update_ui(
                status=f"扫描 {idx+1}/{total}",
                progress=(idx / total) * 50
            )
            
            try:
                elements = page.eles("xpath://section")
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
                
                record = {
                    'title': title[:100],
                    'author': author or "未知",
                    'note_link': note_link,
                    'note_type': '图文',
                    'keyword': keyword,
                    'image_urls': [img_url] if img_url else [],
                    'image_count': 1 if img_url else 0,
                }
                
                if img_url and self.config.download_images:
                    folder = f"{images_dir}/note_{idx+1}_{timestamp}"
                    ext = '.webp' if '.webp' in img_url else '.jpg'
                    path = f"{folder}/img_1{ext}"
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
            
            for url, path, idx in download_tasks:
                if results.get(url):
                    records[idx]['local_images'] = [results[url]]
        
        self.all_notes_data.extend(records)
        
        img_count = sum(1 for r in records if r.get('local_images'))
        return len(records), img_count, 0
    
    def _extract_full_note(self, page, idx: int, images_dir: str, timestamp: int, keyword: str) -> Optional[Dict]:
        """提取完整笔记数据（优化版）"""
        try:
            data = {'keyword': keyword, 'image_count': 0}
            
            # 使用更快的超时和更精确的选择器
            FAST_TIMEOUT = 0.15
            
            # 标题 - 优化选择器顺序
            title = ""
            title_selectors = [
                'xpath://div[@id="detail-title"]',
                'xpath://div[contains(@id, "detail-title")]',
                'xpath://div[contains(@class, "note-content")]//div[contains(@class, "title")]'
            ]
            for sel in title_selectors:
                try:
                    e = page.ele(sel, timeout=FAST_TIMEOUT)
                    if e and e.text:
                        title = e.text.strip()
                        break
                except Exception:
                    continue
            data['title'] = title[:200] if title else f"笔记{idx+1}"
            
            # 作者 - 简化选择器
            author = ""
            try:
                e = page.ele('xpath://a[contains(@class, "author")]//span[@class="name"]', timeout=FAST_TIMEOUT)
                if e:
                    author = e.text or ""
            except Exception:
                pass
            data['author'] = author.strip() or "未知"
            
            # 正文内容
            if self.config.get_content:
                content = ""
                try:
                    e = page.ele('xpath://div[@id="detail-desc"]', timeout=FAST_TIMEOUT)
                    if e:
                        content = e.text or ""
                except Exception:
                    pass
                data['content'] = content.strip()
                
                # 提取标签
                if self.config.get_tags and content:
                    # 提取#标签和话题
                    tags = re.findall(r'#([^\s#]+)', content)
                    data['tags'] = list(set(tags))[:20]  # 限制标签数量
            
            # 发布时间
            if self.config.get_publish_time:
                pub_time = ""
                try:
                    e = page.ele('xpath://span[contains(@class, "date")]', timeout=FAST_TIMEOUT)
                    if e:
                        pub_time = e.text or ""
                except Exception:
                    pass
                data['publish_time'] = pub_time.strip()
            
            # 互动数据 - 优化获取方式
            if self.config.get_interactions:
                data['like_count'] = 0
                data['collect_count'] = 0
                data['comment_count'] = 0
                try:
                    counts = page.eles('xpath://span[contains(@class, "count")]', timeout=FAST_TIMEOUT)
                    if counts:
                        data['like_count'] = self._parse_num(counts[0].text if len(counts) > 0 else "0")
                        data['collect_count'] = self._parse_num(counts[1].text if len(counts) > 1 else "0")
                        data['comment_count'] = self._parse_num(counts[2].text if len(counts) > 2 else "0")
                except Exception:
                    pass
            
            # 链接和ID
            current_url = page.url
            data['note_link'] = current_url if '/explore/' in current_url else ""
            data['note_id'] = current_url.split('/')[-1].split('?')[0] if '/explore/' in current_url else ""
            
            # 检测笔记类型
            note_type = "图文"
            video_url = ""
            try:
                v = page.ele('xpath://video', timeout=FAST_TIMEOUT)
                if v:
                    note_type = "视频"
                    video_url = v.attr('src') or ""
            except Exception:
                pass
            data['note_type'] = note_type
            data['video_url'] = video_url
            
            # 获取图片URL
            preview_images = []
            try:
                imgs = page.eles('xpath://div[contains(@class, "swiper")]//img | //div[contains(@class, "carousel")]//img')
                if not imgs:
                    imgs = page.eles('xpath://div[5]//img')
                    
                for img in imgs[:15]:  # 限制数量
                    src = img.attr('src') or ""
                    # 过滤头像和小图标
                    if src and len(src) > 50:
                        if 'avatar' not in src.lower() and '.png' not in src.lower():
                            preview_images.append(src)
            except Exception:
                pass
            
            data['image_urls'] = list(dict.fromkeys(preview_images))[:10]  # 去重并限制
            
            # 批量下载图片
            if self.config.download_images and preview_images:
                folder = f"{images_dir}/note_{idx+1}_{timestamp}"
                tasks = []
                for i, url in enumerate(data['image_urls'], 1):
                    ext = '.webp' if '.webp' in url else '.jpg'
                    tasks.append((url, f"{folder}/img_{i}{ext}"))
                
                if tasks:
                    results = self.downloader.download_batch(tasks, None, lambda: self.should_stop)
                    data['local_images'] = [r for r in results.values() if r]
                    data['image_count'] = len(data['local_images'])
            
            # 下载视频
            if self.config.download_videos and video_url:
                folder = f"{images_dir}/note_{idx+1}_{timestamp}"
                video_path = f"{folder}/video.mp4"
                result = self.downloader.download_file(video_url, video_path, lambda: self.should_stop, min_size=10240)
                if result:
                    data['local_video'] = result
            
            # 评论爬取（优化版）
            if self.config.get_comments:
                comments = self._extract_comments(page)
                data['comments'] = comments
                if comments:
                    self.log(f"  获取到 {len(comments)} 条评论", "INFO")
            
            return data
            
        except Exception as e:
            self.log(f"提取数据失败: {e}", "ERROR")
            return None
    
    def _extract_comments(self, page) -> List[str]:
        """智能提取评论内容"""
        comments = []
        max_count = self.config.comments_count
        
        # 评论选择器优先级列表
        comment_selectors = [
            'xpath://div[contains(@class, "comment-item")]//span[contains(@class, "content")]',
            'xpath://div[contains(@class, "comments-container")]//div[contains(@class, "content")]',
            'xpath://div[contains(@class, "comment")]//div[@class="content"]',
            'xpath://div[contains(@class, "note-comment")]//span[contains(@class, "note")]',
        ]
        
        # 排除词列表
        exclude_words = {'关注', '点赞', '收藏', '分享', '复制', '举报', '回复', '查看', '展开'}
        
        for selector in comment_selectors:
            if len(comments) >= max_count:
                break
            try:
                elements = page.eles(selector, timeout=0.2)
                for elem in elements:
                    if len(comments) >= max_count:
                        break
                    text = (elem.text or "").strip()
                    # 智能过滤
                    if (5 < len(text) < 500 and 
                        text not in comments and
                        not any(w in text for w in exclude_words)):
                        comments.append(text)
            except Exception:
                continue
        
        # 备用方案：滚动后获取
        if not comments:
            try:
                page.scroll.to_bottom()
                time.sleep(0.2)
                
                spans = page.eles('xpath://div[contains(@class, "comment")]//span', timeout=0.2)
                for span in spans:
                    if len(comments) >= max_count:
                        break
                    text = (span.text or "").strip()
                    if (10 < len(text) < 300 and 
                        text not in comments and
                        not any(w in text for w in exclude_words)):
                        comments.append(text)
            except Exception:
                pass
        
        return comments
    
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
    
    def _save_data(self, data, keyword):
        """保存数据"""
        os.makedirs("data", exist_ok=True)
        timestamp = int(time.time())
        
        # 转换为DataFrame
        df = pd.DataFrame(data)
        
        ext = self.config.export_format
        filename = f"data/搜索结果_{keyword}_{timestamp}.{ext}"
        
        if ext == "xlsx":
            df.to_excel(filename, index=False)
        elif ext == "csv":
            df.to_csv(filename, index=False, encoding='utf-8-sig')
        elif ext == "json":
            df.to_json(filename, orient='records', force_ascii=False, indent=2)
        
        return filename
    
    # === 分析功能 ===
    def _generate_charts(self):
        """生成图表"""
        if not HAS_MATPLOTLIB:
            messagebox.showwarning("提示", "需要安装matplotlib库")
            return
        
        if not self.all_notes_data:
            # 从最新文件加载
            self._load_latest_data()
        
        if not self.all_notes_data:
            messagebox.showinfo("提示", "没有数据可分析")
            return
        
        df = pd.DataFrame(self.all_notes_data)
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
        
        if not self.all_notes_data:
            self._load_latest_data()
        
        if not self.all_notes_data:
            messagebox.showinfo("提示", "没有数据可分析")
            return
        
        texts = [d.get('title', '') + ' ' + d.get('content', '') for d in self.all_notes_data]
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
        
        if not self.all_notes_data:
            self._load_latest_data()
        
        if not self.all_notes_data:
            messagebox.showinfo("提示", "没有数据可分析")
            return
        
        df = pd.DataFrame(self.all_notes_data)
        stats = DataAnalyzer.generate_stats(df)
        
        # 先生成图表
        charts = []
        if HAS_MATPLOTLIB:
            charts = DataAnalyzer.generate_charts(df, "data/charts")
        
        keyword = self.all_notes_data[0].get('keyword', '未知') if self.all_notes_data else '未知'
        output = f"data/分析报告_{keyword}_{int(time.time())}.docx"
        
        result = DataAnalyzer.generate_report(df, stats, charts, output, keyword)
        if result:
            messagebox.showinfo("完成", f"报告已生成: {output}")
            os.startfile(output)
        else:
            messagebox.showwarning("提示", "报告生成失败")
    
    def _load_latest_data(self):
        """加载最新数据文件"""
        if not os.path.exists("data"):
            return
        
        files = [f for f in os.listdir("data") if f.startswith("搜索结果_") and f.endswith(".xlsx")]
        if not files:
            return
        
        files.sort(key=lambda x: os.path.getmtime(os.path.join("data", x)), reverse=True)
        latest = os.path.join("data", files[0])
        
        try:
            df = pd.read_excel(latest)
            self.all_notes_data = df.to_dict('records')
        except:
            pass
    
    def _merge_data(self):
        """合并所有数据"""
        if not os.path.exists("data"):
            messagebox.showinfo("提示", "没有数据文件")
            return
        
        all_dfs = []
        for f in os.listdir("data"):
            if f.startswith("搜索结果_") and f.endswith(".xlsx"):
                try:
                    df = pd.read_excel(os.path.join("data", f))
                    all_dfs.append(df)
                except:
                    continue
        
        if not all_dfs:
            messagebox.showinfo("提示", "没有可合并的数据")
            return
        
        merged = pd.concat(all_dfs, ignore_index=True)
        if 'note_link' in merged.columns:
            merged = merged.drop_duplicates(subset=['note_link'])
        
        output = f"data/合并数据_{int(time.time())}.xlsx"
        merged.to_excel(output, index=False)
        
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
                
                notes = len(df)
                images = df['image_count'].sum() if 'image_count' in df.columns else 0
                
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
    
    def run(self):
        self.root.mainloop()


if __name__ == '__main__':
    app = CrawlerApp()
    app.run()
