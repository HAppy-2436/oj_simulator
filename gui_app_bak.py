import tkinter as tk
from tkinter import ttk, messagebox
import threading
import time
import random
import os
import json
import requests
import re
from datetime import datetime
from playwright.sync_api import sync_playwright
import urllib.parse

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")
DIFFICULTY_FILE = os.path.join(BASE_DIR, "difficulty.json")

class SimulatorGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("OJ 拟人化刷题模拟器")
        self.root.geometry("700x850")

        # 1. 主控区（始终可见）
        self.frame_main_ctrl = ttk.Frame(self.root, padding=8)
        self.frame_main_ctrl.pack(fill='x', side='top')
        
        self.btn_open_settings = ttk.Button(self.frame_main_ctrl, text="⚙️ 设置", command=self.show_settings)
        self.btn_open_settings.pack(side='left', padx=6)

        self.var_debug = tk.BooleanVar(value=False)
        self.chk_debug = ttk.Checkbutton(self.frame_main_ctrl, text="🚀 极速调试", variable=self.var_debug)
        self.chk_debug.pack(side='left')

        self.btn_start = ttk.Button(self.frame_main_ctrl, text="▶ 开始", command=self.start_simulation)
        self.btn_start.pack(side='right', padx=6)
        
        self.btn_stop = ttk.Button(self.frame_main_ctrl, text="⏹ 停止", command=self.stop_simulation, state='disabled')
        self.btn_stop.pack(side='right')

        # 2. 设置面板容器（默认隐藏，按需挂载）
        self.container_settings = ttk.Frame(self.root)
        
        # 内部构建各个配置模块
        self._build_settings()

        # 3. 日志区
        frame_log = ttk.LabelFrame(self.root, text="运行日志")
        frame_log.pack(fill='both', expand=True, padx=8, pady=8)
        self.text_log = tk.Text(frame_log, bg='black', fg='green', state='disabled')
        self.text_log.pack(fill='both', expand=True)

        self.is_running = False
        self.worker = None
        self.current_working_url = None

        self.load_config()

    def _build_settings(self):
        # 基础配置
        frame_base = ttk.LabelFrame(self.container_settings, text="基础配置", padding=10)
        frame_base.pack(fill="x", padx=10, pady=5)

        ttk.Label(frame_base, text="OJ 网址:").grid(row=0, column=0, sticky="e", pady=2)
        self.entry_url = ttk.Entry(frame_base, width=40)
        self.entry_url.grid(row=0, column=1, sticky="w", pady=2)

        ttk.Label(frame_base, text="账号:").grid(row=1, column=0, sticky="e", pady=2)
        self.entry_user = ttk.Entry(frame_base, width=30)
        self.entry_user.grid(row=1, column=1, sticky="w", pady=2)

        ttk.Label(frame_base, text="密码:").grid(row=2, column=0, sticky="e", pady=2)
        self.entry_pwd = ttk.Entry(frame_base, width=30, show="*")
        self.entry_pwd.grid(row=2, column=1, sticky="w", pady=2)

        # 大模型配置
        frame_llm = ttk.LabelFrame(self.container_settings, text="LLM API 配置", padding=10)
        frame_llm.pack(fill="x", padx=10, pady=5)

        ttk.Label(frame_llm, text="API Key:").grid(row=0, column=0, sticky="e", pady=2)
        self.entry_api = ttk.Entry(frame_llm, width=40)
        self.entry_api.grid(row=0, column=1, sticky="w", pady=2)
        
        ttk.Label(frame_llm, text="Base URL:").grid(row=1, column=0, sticky="e", pady=2)
        self.entry_base_url = ttk.Entry(frame_llm, width=40)
        self.entry_base_url.grid(row=1, column=1, sticky="w", pady=2)
        self.entry_base_url.insert(0, "https://api.openai.com/v1")

        # 策略配置
        frame_policy = ttk.LabelFrame(self.container_settings, text="策略与随机行为配置", padding=10)
        frame_policy.pack(fill="x", padx=10, pady=5)

        ttk.Label(frame_policy, text="起始题号(如1025):").grid(row=0, column=0, sticky="e", pady=2)
        self.entry_start_id = ttk.Entry(frame_policy, width=10)
        self.entry_start_id.grid(row=0, column=1, sticky="w", pady=2)

        ttk.Label(frame_policy, text="日题数及波动:").grid(row=1, column=0, sticky="e", pady=2)
        fc = ttk.Frame(frame_policy)
        fc.grid(row=1, column=1, sticky="w", pady=2)
        self.spin_count = ttk.Spinbox(fc, from_=1, to=100, width=5)
        self.spin_count.pack(side="left")
        self.spin_count.set(5)
        ttk.Label(fc, text=" 波动(±): ").pack(side="left")
        self.spin_fluctuation = ttk.Spinbox(fc, from_=0, to=50, width=5)
        self.spin_fluctuation.pack(side="left")
        self.spin_fluctuation.set(2)

        ttk.Label(frame_policy, text="做题时段(时):").grid(row=2, column=0, sticky="e", pady=2)
        ft = ttk.Frame(frame_policy)
        ft.grid(row=2, column=1, sticky="w", pady=2)
        self.entry_time_start = ttk.Entry(ft, width=5); self.entry_time_start.pack(side="left"); self.entry_time_start.insert(0, "14")
        ttk.Label(ft, text=" 到 ").pack(side="left")
        self.entry_time_end = ttk.Entry(ft, width=5); self.entry_time_end.pack(side="left"); self.entry_time_end.insert(0, "23")

        ttk.Label(frame_policy, text="读题/敲码基础延迟:").grid(row=3, column=0, sticky="e", pady=2)
        f_delay = ttk.Frame(frame_policy)
        f_delay.grid(row=3, column=1, sticky="w", pady=2)
        self.entry_read_delay = ttk.Entry(f_delay, width=6); self.entry_read_delay.insert(0, "5-30")
        self.entry_read_delay.pack(side="left")
        ttk.Label(f_delay, text=" / ").pack(side="left")
        self.entry_write_delay = ttk.Entry(f_delay, width=6); self.entry_write_delay.insert(0, "10-120")
        self.entry_write_delay.pack(side="left")

        ttk.Label(frame_policy, text="读/写字长系数:").grid(row=3, column=2, sticky="e", pady=2)
        f_ratio = ttk.Frame(frame_policy)
        f_ratio.grid(row=3, column=3, sticky="w", pady=2)
        self.entry_read_ratio = ttk.Entry(f_ratio, width=6); self.entry_read_ratio.insert(0, "0.1")
        self.entry_read_ratio.pack(side="left")
        ttk.Label(f_ratio, text=" / ").pack(side="left")
        self.entry_write_ratio = ttk.Entry(f_ratio, width=6); self.entry_write_ratio.insert(0, "0.2")
        self.entry_write_ratio.pack(side="left")

        ttk.Label(frame_policy, text="AC后开心休息(min-max):").grid(row=4, column=0, sticky="e", pady=2)
        self.entry_ac_rest = ttk.Entry(frame_policy, width=15); self.entry_ac_rest.insert(0, "30-300")
        self.entry_ac_rest.grid(row=4, column=1, sticky="w", pady=2)

        ttk.Label(frame_policy, text="看WA震惊停顿(min-max):").grid(row=4, column=2, sticky="e", pady=2)
        self.entry_wa_shock = ttk.Entry(frame_policy, width=15); self.entry_wa_shock.insert(0, "15-60")
        self.entry_wa_shock.grid(row=4, column=3, sticky="w", pady=2)

        ttk.Label(frame_policy, text="重试极限次数(min-max):").grid(row=5, column=0, sticky="e", pady=2)
        self.entry_max_retries = ttk.Entry(frame_policy, width=15); self.entry_max_retries.insert(0, "3-8")
        self.entry_max_retries.grid(row=5, column=1, sticky="w", pady=2)

        ttk.Label(frame_policy, text="代码质量:").grid(row=6, column=0, sticky="e", pady=2)
        self.combo_quality = ttk.Combobox(frame_policy, values=["大一萌新 (偶尔求助AI)", "大二熟手 (代码规范)", "竞赛生 (极简精炼)"], width=25, state="readonly")
        self.combo_quality.grid(row=6, column=1, columnspan=3, sticky="w", pady=2)
        self.combo_quality.set("大一萌新 (偶尔求助AI)")

        ttk.Label(frame_policy, text="附加提示词:").grid(row=7, column=0, sticky="e", pady=2)
        self.entry_custom_prompt = ttk.Entry(frame_policy, width=40)
        self.entry_custom_prompt.grid(row=7, column=1, columnspan=3, sticky="w", pady=2)

        ttk.Label(frame_policy, text="难题(标签或超长):").grid(row=8, column=0, sticky="e", pady=2)
        f_hard = ttk.Frame(frame_policy)
        f_hard.grid(row=8, column=1, columnspan=3, sticky="w", pady=2)
        self.entry_hard_length = ttk.Entry(f_hard, width=6); self.entry_hard_length.insert(0, "1500")
        self.entry_hard_length.pack(side="left")
        ttk.Label(f_hard, text="字 策略:").pack(side="left")
        self.combo_hard_strategy = ttk.Combobox(f_hard, values=["正常做", "延时3倍", "自动跳过"], width=10, state="readonly")
        self.combo_hard_strategy.pack(side="left")
        self.combo_hard_strategy.set("正常做")
        
        ttk.Button(f_hard, text="获取题目集难度字典", command=self.fetch_difficulty_map).pack(side="left", padx=8)

        # 面板控制
        fbtn = ttk.Frame(self.container_settings)
        fbtn.pack(fill="x", padx=10, pady=5)
        ttk.Button(fbtn, text="💾 保存配置", command=self.save_config).pack(side="left")
        ttk.Button(fbtn, text="✖ 关闭面板", command=self.hide_settings).pack(side="right")

    def show_settings(self):
        try:
            self.container_settings.pack(fill='x', padx=6, pady=2, before=self.root.winfo_children()[-1])
            self.btn_open_settings.config(state='disabled')
        except Exception as e:
            self.log_msg(f"打开设置异常: {e}")

    def hide_settings(self):
        try:
            self.container_settings.pack_forget()
            self.btn_open_settings.config(state='normal')
        except Exception:
            pass

    def log_msg(self, msg):
        self.text_log.config(state="normal")
        self.text_log.insert("end", f"[{time.strftime('%H:%M:%S')}] {msg}\n")
        self.text_log.see("end")
        self.text_log.config(state="disabled")

    def save_config(self):
        config = {
            "url": self.entry_url.get(), "user": self.entry_user.get(), "pwd": self.entry_pwd.get(),
            "api_key": self.entry_api.get(), "base_url": self.entry_base_url.get(),
            "start_id": self.entry_start_id.get(), "daily_target": self.spin_count.get(),
            "fluctuation": self.spin_fluctuation.get(), "time_start": self.entry_time_start.get(),
            "time_end": self.entry_time_end.get(), "quality": self.combo_quality.get(),
            "read_delay": self.entry_read_delay.get(), "write_delay": self.entry_write_delay.get(),
            "wa_shock": self.entry_wa_shock.get(),
            "ac_rest": self.entry_ac_rest.get(), "max_retries": self.entry_max_retries.get(),
            "custom_prompt": self.entry_custom_prompt.get(),
            "read_ratio": self.entry_read_ratio.get(),
            "write_ratio": self.entry_write_ratio.get(),
            "hard_length": self.entry_hard_length.get(),
            "hard_strategy": self.combo_hard_strategy.get()
        }
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=4)
        self.log_msg("配置已保存到 config.json")
        messagebox.showinfo("成功", "配置已保存")

    def fetch_difficulty_map(self):
        url = self.entry_url.get()
        if "/contest/" not in url:
            messagebox.showwarning("警告", "请在 OJ 网址中填入 Contest 页面链接\n例如: https://acm.ecnu.edu.cn/contest/43/")
            return
            
        def _scrape():
            self.log_msg("正在后台爬取题目集难度映射，请稍候...")
            try:
                with sync_playwright() as p:
                    browser = p.chromium.launch(headless=True)
                    page = browser.new_page()
                    page.goto(url, timeout=30000)
                    time.sleep(2)
                    
                    mapping = {}
                    # 尝试查找包含题号和标签的行
                    rows = page.locator("table tr")
                    count = rows.count()
                    for i in range(count):
                        row = rows.nth(i)
                        try:
                            # 提取带有链接的元素通常是重点
                            links = row.locator("a")
                            if links.count() > 0:
                                href = links.first.get_attribute("href") or ""
                                match = re.search(r'problem/([A-Za-z0-9]+)', href)
                                if match:
                                    pid = match.group(1)
                                    label_elem = row.locator(".ui.label")
                                    if label_elem.count() > 0:
                                        label_text = label_elem.first.inner_text().strip()
                                        mapping[pid] = label_text
                        except: pass
                    browser.close()
                    
                if mapping:
                    with open(DIFFICULTY_FILE, "w", encoding="utf-8") as f:
                        json.dump(mapping, f, ensure_ascii=False, indent=4)
                    self.log_msg(f"✅ 成功爬取 {len(mapping)} 条难度数据并保存至 difficulty.json")
                else:
                    self.log_msg("⚠️ 未爬取到难度数据，请确认页面是否需要登录或结构是否匹配。")
            except Exception as e:
                self.log_msg(f"爬取难度异常: {e}")
                
        threading.Thread(target=_scrape, daemon=True).start()

    def load_config(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    config = json.load(f)
                self.entry_url.insert(0, config.get("url", "")); self.entry_user.insert(0, config.get("user", ""))
                self.entry_pwd.insert(0, config.get("pwd", "")); self.entry_api.insert(0, config.get("api_key", ""))
                self.entry_base_url.delete(0, "end"); self.entry_base_url.insert(0, config.get("base_url", "https://api.openai.com/v1"))
                self.entry_start_id.delete(0, "end"); self.entry_start_id.insert(0, config.get("start_id", ""))
                self.spin_count.set(config.get("daily_target", "5"))
                try: self.spin_fluctuation.set(config.get("fluctuation", "2"))
                except: pass
                self.entry_time_start.delete(0, "end"); self.entry_time_start.insert(0, config.get("time_start", "14"))
                self.entry_time_end.delete(0, "end"); self.entry_time_end.insert(0, config.get("time_end", "23"))
                self.combo_quality.set(config.get("quality", "大一萌新 (偶尔求助AI)"))
                try: self.entry_read_delay.delete(0, "end"); self.entry_read_delay.insert(0, config.get("read_delay", "5-30"))
                except: pass
                try: self.entry_write_delay.delete(0, "end"); self.entry_write_delay.insert(0, config.get("write_delay", "10-120"))
                except: pass
                self.entry_wa_shock.delete(0, "end"); self.entry_wa_shock.insert(0, config.get("wa_shock", "15-60"))
                self.entry_ac_rest.delete(0, "end"); self.entry_ac_rest.insert(0, config.get("ac_rest", "30-300"))
                self.entry_max_retries.delete(0, "end"); self.entry_max_retries.insert(0, config.get("max_retries", "3-8"))
                self.entry_custom_prompt.delete(0, "end"); self.entry_custom_prompt.insert(0, config.get("custom_prompt", ""))
                try: self.entry_read_ratio.delete(0, "end"); self.entry_read_ratio.insert(0, config.get("read_ratio", "0.1"))
                except: pass
                try: self.entry_write_ratio.delete(0, "end"); self.entry_write_ratio.insert(0, config.get("write_ratio", "0.2"))
                except: pass
                try: self.entry_hard_length.delete(0, "end"); self.entry_hard_length.insert(0, config.get("hard_length", "1500"))
                except: pass
                try: self.combo_hard_strategy.set(config.get("hard_strategy", "正常做"))
                except: pass
                self.log_msg("已加载历史配置。")
            except Exception as e:
                self.log_msg(f"加载配置失败: {e}")

    def get_rand_range(self, val_str, default_min, default_max):
        try:
            parts = val_str.split('-')
            return int(parts[0]), int(parts[1])
        except:
            return default_min, default_max

    def sim_sleep(self, val_str, def_min, def_max, msg_prefix="", extra_offset=0):
        rmin, rmax = self.get_rand_range(val_str, def_min, def_max)
        val = random.randint(rmin, rmax) + int(extra_offset)
        if self.var_debug.get():
            val = random.randint(1, 3) # 调试模式极速跳过
        if msg_prefix:
            self.log_msg(f"{msg_prefix}: {val} 秒...")
        for _ in range(val):
            if not self.is_running: break
            time.sleep(1)

    def start_simulation(self):
        if not self.entry_url.get() or not self.entry_api.get():
            messagebox.showwarning("警告", "请填写完整的网址和 API Key！")
            return
            
        self.is_running = True
        self.btn_start.config(state="disabled")
        self.btn_stop.config(state="normal")
        self.btn_open_settings.config(state="disabled")
        
        self.hide_settings()
        self.log_msg("--- 启动拟人化刷题引擎 ---")
        
        expected_target = int(self.spin_count.get() or 5)
        fluct = int(self.spin_fluctuation.get() or 2)
        actual_target = random.randint(max(1, expected_target - fluct), expected_target + fluct)
        
        self.worker = threading.Thread(target=self.run_bot, args=(actual_target,), daemon=True)
        self.worker.start()

    def stop_simulation(self):
        self.is_running = False
        self.btn_start.config(state="normal")
        self.btn_stop.config(state="disabled")
        self.btn_open_settings.config(state="normal")
        
        if getattr(self, 'current_working_url', None):
            self.save_start_id(self.current_working_url)
            
        self.log_msg("收到停止指令，正在退出模拟...")

    def call_llm_api(self, messages):
        api_key = self.entry_api.get().strip()
        base_url = self.entry_base_url.get().strip()
        if not api_key: return ""
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        data = {
            "model": "deepseek-chat" if "deepseek" in base_url.lower() else "gpt-3.5-turbo",
            "messages": messages,
            "temperature": 0.8
        }
        try:
            response = requests.post(f"{base_url}/chat/completions", headers=headers, json=data, timeout=60)
            res_json = response.json()
            code = res_json['choices'][0]['message']['content'].strip()
            code = re.sub(r"^```[a-zA-Z+]*\n", "", code)
            return re.sub(r"\n```$", "", code)
        except Exception as e:
            self.log_msg(f"大模型 API 请求异常: {e}")
            return ""

    def inject_and_submit(self, page, code):
        try:
            page.click(".ace_content")
            time.sleep(0.5)
            modifier = "Meta" if "Mac" in page.evaluate("navigator.platform") else "Control"
            page.keyboard.press(f"{modifier}+a")
            time.sleep(0.3)
            page.keyboard.press("Backspace")
            time.sleep(0.5)
            page.keyboard.insert_text(code)
            
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            time.sleep(1)
            submit_btn = page.locator(".ui.right.labeled.icon.green.button, button[type='submit']")
            if submit_btn.count() > 0:
                submit_btn.first.scroll_into_view_if_needed()
                time.sleep(0.5)
                submit_btn.first.click()
            else:
                page.keyboard.press(f"{modifier}+Enter")
        except:
            self.log_msg("注入或提交操作元素未就绪...")

    def increment_url(self, url):
        match = re.search(r'(\d+)(/?)$', url)
        if match:
            current_id = int(match.group(1))
            return url[:match.start(1)] + str(current_id + 1) + match.group(2)
        return url

    def save_start_id(self, next_url):
        match = re.search(r'(\d+)(/?)$', next_url)
        if match:
            new_id = match.group(1)
            try:
                self.entry_start_id.delete(0, 'end')
                self.entry_start_id.insert(0, new_id)
                self.save_config()
            except:
                pass

    def run_bot(self, target):
        self.log_msg(f"今日随机目标题数波动为: {target} 题")
        start_id = self.entry_start_id.get().strip()
        t_start = int(self.entry_time_start.get() or 0)
        t_end = int(self.entry_time_end.get() or 24)
        
        self.log_msg("初始化 Playwright 浏览器 [Headless=False]...")
        
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=False)
                context = browser.new_context(viewport={'width': 1920, 'height': 1080})
                page = context.new_page()

                input_url = self.entry_url.get()
                parsed_uri = urllib.parse.urlparse(input_url)
                base_url = f"{parsed_uri.scheme}://{parsed_uri.netloc}"
                login_url = f"{base_url}/login/"
                
                self.log_msg("访问登录页...")
                page.goto(login_url)
                try:
                    page.fill("#id_username", self.entry_user.get())
                    page.fill("#id_password", self.entry_pwd.get())
                    self.log_msg("★ 请在弹出的浏览器中手动计算验证码并确认登录！")
                    page.wait_for_url(lambda url: "login" not in url.lower(), timeout=0)
                    self.log_msg("✅ 登录成功！可在后台挂机运行。")
                except Exception as e:
                    self.log_msg(f"登录环节异常: {e}")

                self.current_working_url = f"{base_url}/problem/{start_id}/" if start_id else input_url

                completed = 0
                while completed < target and self.is_running:
                    hr = datetime.now().hour
                    if not (t_start <= hr < t_end):
                        self.log_msg(f"非做题时段({t_start}-{t_end})，休眠10分钟...")
                        time.sleep(600)
                        continue

                    page.goto(self.current_working_url)
                    time.sleep(3)
                    self.log_msg(f"\n[{completed+1}/{target}] 审查题目: {self.current_working_url}")
                    
                    try:
                        code_content = page.locator(".ace_text-layer").inner_text(timeout=2000).strip()
                        if len(code_content) > 10:
                            self.log_msg("⚠️ 该题已做过，跳过！")
                            self.current_working_url = self.increment_url(self.current_working_url)
                            continue
                    except: pass

                    try:
                        problem_text = page.inner_text(".ui.main.container")
                    except:
                        self.log_msg("提取题目失败找下一题...")
                        self.current_working_url = self.increment_url(self.current_working_url)
                        continue

                    problem_len = len(problem_text)
                    try:
                        r_ratio = float(self.entry_read_ratio.get().strip() or "0.1")
                        w_ratio = float(self.entry_write_ratio.get().strip() or "0.2")
                    except:
                        r_ratio, w_ratio = 0.1, 0.2
                    
                    try:
                        hard_threshold = int(self.entry_hard_length.get().strip() or "1500")
                    except:
                        hard_threshold = 1500
                    
                    # 首先尝试从字典中判断
                    diff_dict = {}
                    if os.path.exists(DIFFICULTY_FILE):
                        try:
                            with open(DIFFICULTY_FILE, "r", encoding="utf-8") as f:
                                diff_dict = json.load(f)
                        except: pass
                        
                    current_pid = ""
                    url_match = re.search(r'problem/([A-Za-z0-9]+)', self.current_working_url)
                    if url_match:
                        current_pid = url_match.group(1)
                        
                    mapped_diff = diff_dict.get(current_pid, "")
                    
                    is_hard = False
                    if mapped_diff:
                        self.log_msg(f"🏷️ 本题字典标签: [{mapped_diff}]")
                        if "Hard" in mapped_diff or "困难" in mapped_diff or "极难" in mapped_diff:
                            is_hard = True
                    else:
                        is_hard = (problem_len >= hard_threshold) or ("困难" in problem_text) or ("hard" in problem_text.lower()) or ("极难" in problem_text)
                        
                    hard_strgy = self.combo_hard_strategy.get()
                    
                    if is_hard:
                        self.log_msg(f"⚠️ 检测到本题为难题(长达{problem_len}字或含困难标签)！")
                        if hard_strgy == "自动跳过":
                            self.log_msg("⏭️ 策略为自动跳过该题。")
                            self.current_working_url = self.increment_url(self.current_working_url)
                            continue
                        elif hard_strgy == "延时3倍":
                            self.log_msg("⏳ 策略为延时3倍，此题时间将大幅延长。")
                            r_ratio *= 3.0
                            w_ratio *= 3.0

                    read_offset = int(problem_len * r_ratio)
                    self.sim_sleep(self.entry_read_delay.get(), 5, 30, f"阅读题目({problem_len}字, +{read_offset}s)", read_offset)
                    if not self.is_running: break

                    quality = self.combo_quality.get()
                    if problem_len < 500:
                        bug_prompt = "基础题，不准留Bug，必须一发AC。"
                    elif problem_len < 1200:
                        bug_prompt = "中等题，【故意留1到2个隐秘极值错误】，但【必须绝对通过样例输入输出】。"
                    else:
                        bug_prompt = "难题，【必须故意写逻辑明显的越界、无特判错误】，但【绝对要求通过样例输入测试】。"
                        
                    custom_prompt = self.entry_custom_prompt.get().strip()
                    custom_addon = f"附加要求：{custom_prompt}。" if custom_prompt else ""
                        
                    messages = [
                        {"role": "system", "content": f"扮演一名{quality}正在刷算法题。不要注释，变量名单一，极低质量代码规则：{bug_prompt} {custom_addon} 完全纯净输出C++实体，无markdown。"},
                        {"role": "user", "content": f"题目及样例：\n{problem_text}"}
                    ]
                    
                    self.log_msg("获取初版代码...")
                    generated_code = self.call_llm_api(messages)
                    if not generated_code: continue

                    code_len = len(generated_code)
                    write_offset = int(code_len * w_ratio)
                    self.sim_sleep(self.entry_write_delay.get(), 10, 120, f"编写代码延时({code_len}字, +{write_offset}s)", write_offset)
                    if not self.is_running: break
                    
                    self.inject_and_submit(page, generated_code)
                    
                    self.sim_sleep("10-10", 10, 10, "等待系统判题判定")
                    page_text = page.inner_text("body").lower()
                    is_ac = ("accepted" in page_text) or ("正确" in page_text) or ("答案正确" in page_text)
                    
                    if not is_ac:
                        self.log_msg("❌ 发生 Wrong Answer / 语法错误...")
                        m_min, m_max = self.get_rand_range(self.entry_max_retries.get(), 3, 8)
                        max_retries = random.randint(m_min, m_max)
                        retry_count = 0
                        
                        self.sim_sleep(self.entry_wa_shock.get(), 15, 60, "震惊并检查报错")
                        
                        while not is_ac and retry_count < max_retries and self.is_running:
                            retry_count += 1
                            if retry_count > 3:
                                self.sim_sleep("5-15", 5, 15, f"第{retry_count}次急躁修改")
                            else:
                                self.sim_sleep("10-40", 10, 40, f"第{retry_count}次思考修复Bug")
                                
                            messages.append({"role": "assistant", "content": generated_code})
                            messages.append({"role": "user", "content": f"第{retry_count}次提交依然没过。只修一个你认为最明显的bug！不要一次性修完！保持代码风格恶劣无注释过样例。"})
                            generated_code = self.call_llm_api(messages)
                            if not self.is_running or not generated_code: break
                            
                            self.inject_and_submit(page, generated_code)
                            self.sim_sleep("10-10", 10, 10, "重试提交后等待判题")
                            page_text = page.inner_text("body").lower()
                            is_ac = ("accepted" in page_text) or ("正确" in page_text) or ("答案正确" in page_text)
                            
                        if not is_ac: self.log_msg(f"🤬 连续{retry_count}次WA，破防弃题！")
                        else: self.log_msg(f"✅ 第{retry_count}次重试通过。")
                    else:
                        self.log_msg("✅ 首发 Accepted 通过！")

                    completed += 1
                    self.current_working_url = self.increment_url(self.current_working_url)
                    
                    self.sim_sleep(self.entry_ac_rest.get(), 30, 300, "做题完成休闲")
                        
                context.close()
                browser.close()
        except Exception as e:
            self.log_msg(f"核心循环报错终止: {e}")
            
        self.stop_simulation()

if __name__ == '__main__':
    root = tk.Tk()
    app = SimulatorGUI(root)
    root.protocol('WM_DELETE_WINDOW', lambda: (setattr(app, 'is_running', False), root.destroy()))
    root.mainloop()
