import tkinter as tk
from tkinter import ttk, messagebox
import threading
import time
import os
import re
from datetime import datetime, timedelta

from core.config_manager import ConfigManager
from core.state_manager import StateManager
from logic.task_runner import TaskRunner

try:
    import pystray
    from pystray import MenuItem as item
    from PIL import Image, ImageDraw
    HAS_TRAY = True
except ImportError:
    HAS_TRAY = False

class MainWindow:
    def __init__(self, root):
        self.root = root
        self.root.title("OJ 拟人化刷题模拟器")
        self.root.geometry("700x850")

        self.cfg = ConfigManager()
        self.state_mgr = StateManager()

        self.captcha_result = ""
        self.captcha_event = threading.Event()

        self.is_running = False
        self.tray_icon = None
        self.worker_thread = None
        self.task_runner = None

        self.setup_ui()
        self.load_settings()

        self.root.bind("<Unmap>", self._on_window_unmap)
        if not HAS_TRAY:
            self.log_msg("ℹ️ 托盘模块 (pystray, Pillow) 未安装。")

        self.schedule_next_reset()
        self._check_initial_reset()

    def setup_ui(self):
        self.frame_main_ctrl = ttk.Frame(self.root, padding=8)
        self.frame_main_ctrl.pack(fill='x', side='top')
        
        self.btn_open_settings = ttk.Button(self.frame_main_ctrl, text="⚙️ 设置", command=self.show_settings)
        self.btn_open_settings.pack(side='left', padx=6)

        self.var_headless = tk.BooleanVar(value=True)
        self.chk_headless = ttk.Checkbutton(self.frame_main_ctrl, text="👻 无头模式", variable=self.var_headless)
        self.chk_headless.pack(side='left', padx=6)

        self.var_debug = tk.BooleanVar(value=False)
        self.chk_debug = ttk.Checkbutton(self.frame_main_ctrl, text="🚀 极速调试", variable=self.var_debug)
        self.chk_debug.pack(side='left')

        self.var_log_llm = tk.BooleanVar(value=False)
        self.chk_log_llm = ttk.Checkbutton(self.frame_main_ctrl, text="💬 展开LLM日志", variable=self.var_log_llm)
        self.chk_log_llm.pack(side='left', padx=6)

        self.var_tray = tk.BooleanVar(value=HAS_TRAY)
        self.chk_tray = ttk.Checkbutton(self.frame_main_ctrl, text="⬇️ 托盘模式", variable=self.var_tray)
        self.chk_tray.pack(side='left')
        if not HAS_TRAY:
            self.chk_tray.config(state='disabled')
            self.var_tray.set(False)

        self.btn_reset = ttk.Button(self.frame_main_ctrl, text="🔄 重置", command=self.reset_daily_state)
        self.btn_reset.pack(side='left', padx=6)

        self.btn_start = ttk.Button(self.frame_main_ctrl, text="▶ 开始", command=self.start_simulation)
        self.btn_start.pack(side='right', padx=6)
        
        self.btn_stop = ttk.Button(self.frame_main_ctrl, text="🛑 停止", command=self.stop_simulation, state='disabled')
        self.btn_stop.pack(side='right')

        self.btn_debug_check = ttk.Button(self.frame_main_ctrl, text="🔍 补漏检查", command=self.start_retro_check)
        self.btn_debug_check.pack(side='right', padx=6)

        self.container_settings = ttk.Frame(self.root)
        self._build_settings()

        frame_log = ttk.LabelFrame(self.root, text="运行日志")
        frame_log.pack(fill='both', expand=True, padx=8, pady=8)
        self.text_log = tk.Text(frame_log, bg='white', fg='black', state='disabled')
        self.text_log.pack(fill='both', expand=True)

    def _build_settings(self):
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

        frame_llm = ttk.LabelFrame(self.container_settings, text="LLM API 配置", padding=10)   
        frame_llm.pack(fill="x", padx=10, pady=5)

        ttk.Label(frame_llm, text="API Key:").grid(row=0, column=0, sticky="e", pady=2)
        self.entry_api = ttk.Entry(frame_llm, width=40)
        self.entry_api.grid(row=0, column=1, sticky="w", pady=2)

        ttk.Label(frame_llm, text="Base URL:").grid(row=1, column=0, sticky="e", pady=2)
        self.entry_base_url = ttk.Entry(frame_llm, width=40)
        self.entry_base_url.grid(row=1, column=1, sticky="w", pady=2)
        self.entry_base_url.insert(0, "https://api.openai.com/v1")

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
        self.entry_time_start = ttk.Entry(ft, width=5)
        self.entry_time_start.pack(side="left")
        ttk.Label(ft, text=" 到 ").pack(side="left")
        self.entry_time_end = ttk.Entry(ft, width=5)
        self.entry_time_end.pack(side="left")

        ttk.Label(frame_policy, text="非做题休眠(时):").grid(row=2, column=2, sticky="e", pady=2)
        self.entry_sleep_hours = ttk.Entry(frame_policy, width=15)
        self.entry_sleep_hours.grid(row=2, column=3, sticky="w", pady=2)

        ttk.Label(frame_policy, text="读题/敲码基础延迟:").grid(row=3, column=0, sticky="e", pady=2)
        f_delay = ttk.Frame(frame_policy)
        f_delay.grid(row=3, column=1, sticky="w", pady=2)
        self.entry_read_delay = ttk.Entry(f_delay, width=6)
        self.entry_read_delay.pack(side="left")
        ttk.Label(f_delay, text=" / ").pack(side="left")
        self.entry_write_delay = ttk.Entry(f_delay, width=6)
        self.entry_write_delay.pack(side="left")

        ttk.Label(frame_policy, text="读/写字长系数:").grid(row=3, column=2, sticky="e", pady=2)
        f_ratio = ttk.Frame(frame_policy)
        f_ratio.grid(row=3, column=3, sticky="w", pady=2)
        self.entry_read_ratio = ttk.Entry(f_ratio, width=6)
        self.entry_read_ratio.pack(side="left")
        ttk.Label(f_ratio, text=" / ").pack(side="left")
        self.entry_write_ratio = ttk.Entry(f_ratio, width=6)
        self.entry_write_ratio.pack(side="left")

        ttk.Label(frame_policy, text="AC后开心休息(min-max):").grid(row=4, column=0, sticky="e", pady=2)
        self.entry_ac_rest = ttk.Entry(frame_policy, width=15)
        self.entry_ac_rest.grid(row=4, column=1, sticky="w", pady=2)

        ttk.Label(frame_policy, text="见WA震惊停顿(min-max):").grid(row=4, column=2, sticky="e", pady=2)
        self.entry_wa_shock = ttk.Entry(frame_policy, width=15)
        self.entry_wa_shock.grid(row=4, column=3, sticky="w", pady=2)

        ttk.Label(frame_policy, text="重试极限次数(min-max):").grid(row=5, column=0, sticky="e", pady=2)
        self.entry_max_retries = ttk.Entry(frame_policy, width=15)
        self.entry_max_retries.grid(row=5, column=1, sticky="w", pady=2)

        ttk.Label(frame_policy, text="代码质量:").grid(row=6, column=0, sticky="e", pady=2)
        self.combo_quality = ttk.Combobox(frame_policy, values=["大一萌新 (偶尔求助AI)", "大二熟手 (代码规范)", "竞赛生 (极简精炼)"], width=25, state="readonly")
        self.combo_quality.grid(row=6, column=1, columnspan=3, sticky="w", pady=2)

        ttk.Label(frame_policy, text="附加提示词:").grid(row=7, column=0, sticky="e", pady=2)
        self.entry_custom_prompt = ttk.Entry(frame_policy, width=40)
        self.entry_custom_prompt.grid(row=7, column=1, columnspan=3, sticky="w", pady=2)

        f_adv = ttk.Frame(frame_policy)
        f_adv.grid(row=8, column=0, columnspan=4, sticky="w", pady=2)

        ttk.Label(f_adv, text="初/中难度边界:").pack(side="left")
        self.entry_easy_bound = ttk.Entry(f_adv, width=5)
        self.entry_easy_bound.pack(side="left", padx=2)
        ttk.Label(f_adv, text="中/高边界:").pack(side="left")
        self.entry_mid_bound = ttk.Entry(f_adv, width=5)
        self.entry_mid_bound.pack(side="left", padx=2)

        ttk.Label(f_adv, text="等待判题(s):").pack(side="left", padx=2)
        self.entry_wait_judge = ttk.Entry(f_adv, width=6)
        self.entry_wait_judge.pack(side="left")

        f_adv2 = ttk.Frame(frame_policy)
        f_adv2.grid(row=9, column=0, columnspan=4, sticky="w", pady=2)

        ttk.Label(f_adv2, text="深度思考WA(s):").pack(side="left")
        self.entry_retry_slow = ttk.Entry(f_adv2, width=7)
        self.entry_retry_slow.pack(side="left", padx=2)

        ttk.Label(f_adv2, text="急躁修复WA(s):").pack(side="left", padx=2)
        self.entry_retry_fast = ttk.Entry(f_adv2, width=7)
        self.entry_retry_fast.pack(side="left")

        ttk.Label(frame_policy, text="难题规则(字数):").grid(row=10, column=0, sticky="e", pady=2)
        f_hard = ttk.Frame(frame_policy)
        f_hard.grid(row=10, column=1, columnspan=3, sticky="w", pady=2)
        self.entry_hard_length = ttk.Entry(f_hard, width=5)
        self.entry_hard_length.pack(side="left")

        ttk.Label(f_hard, text=" Hard:").pack(side="left")
        self.combo_hard_strategy = ttk.Combobox(f_hard, values=["正常做", "延时2倍", "延时3倍", "自动跳过"], width=7, state="readonly")
        self.combo_hard_strategy.pack(side="left")

        ttk.Label(f_hard, text=" Super:").pack(side="left")
        self.combo_super_strategy = ttk.Combobox(f_hard, values=["正常做", "延时3倍", "自动跳过"], width=7, state="readonly")
        self.combo_super_strategy.pack(side="left")

        ttk.Button(f_hard, text="获取题目集字典", command=self.fetch_difficulty_map).pack(side="left", padx=5)

        fbtn = ttk.Frame(self.container_settings)
        fbtn.pack(fill="x", padx=10, pady=5)
        ttk.Button(fbtn, text="💾 保存配置", command=self.save_settings).pack(side="left")   
        ttk.Button(fbtn, text="❌ 关闭面板", command=self.hide_settings).pack(side="right")

    def load_settings(self):
        c = self.cfg.config
        self.entry_url.insert(0, c.get("url", ""))
        self.entry_user.insert(0, c.get("user", ""))
        self.entry_pwd.insert(0, c.get("pwd", ""))
        self.entry_api.insert(0, c.get("api_key", ""))
        self.entry_base_url.delete(0, "end")
        self.entry_base_url.insert(0, c.get("base_url", "https://api.openai.com/v1"))
        self.entry_start_id.insert(0, c.get("start_id", ""))
        self.spin_count.set(c.get("daily_target", "5"))
        self.spin_fluctuation.set(c.get("fluctuation", "2"))
        
        self.entry_time_start.insert(0, c.get("time_start", "14"))
        self.entry_time_end.insert(0, c.get("time_end", "23"))
        self.entry_sleep_hours.insert(0, c.get("sleep_hours", "2-3"))
        self.entry_read_delay.insert(0, c.get("read_delay", "5-30"))
        self.entry_write_delay.insert(0, c.get("write_delay", "10-120"))
        self.entry_read_ratio.insert(0, c.get("read_ratio", "0.1"))
        self.entry_write_ratio.insert(0, c.get("write_ratio", "0.2"))
        self.entry_ac_rest.insert(0, c.get("ac_rest", "30-300"))
        self.entry_wa_shock.insert(0, c.get("wa_shock", "15-60"))
        self.entry_max_retries.insert(0, c.get("max_retries", "3-8"))
        self.combo_quality.set(c.get("quality", "大一萌新 (偶尔求助AI)"))
        self.entry_custom_prompt.insert(0, c.get("custom_prompt", ""))
        self.entry_easy_bound.insert(0, c.get("easy_bound", "500"))
        self.entry_mid_bound.insert(0, c.get("mid_bound", "1200"))
        self.entry_wait_judge.insert(0, c.get("wait_judge", "10-15"))
        self.entry_retry_slow.insert(0, c.get("retry_slow", "10-40"))
        self.entry_retry_fast.insert(0, c.get("retry_fast", "5-15"))
        self.entry_hard_length.insert(0, c.get("hard_length", "1500"))
        self.combo_hard_strategy.set(c.get("hard_strategy", "延时2倍"))
        self.combo_super_strategy.set(c.get("super_strategy", "自动跳过"))

    def save_settings(self):
        self.cfg.set("url", self.entry_url.get())
        self.cfg.set("user", self.entry_user.get())
        self.cfg.set("pwd", self.entry_pwd.get())
        self.cfg.set("api_key", self.entry_api.get())
        self.cfg.set("base_url", self.entry_base_url.get())
        self.cfg.set("start_id", self.entry_start_id.get())
        self.cfg.set("daily_target", self.spin_count.get())
        self.cfg.set("fluctuation", self.spin_fluctuation.get())
        self.cfg.set("time_start", self.entry_time_start.get())
        self.cfg.set("time_end", self.entry_time_end.get())
        self.cfg.set("sleep_hours", self.entry_sleep_hours.get())
        self.cfg.set("read_delay", self.entry_read_delay.get())
        self.cfg.set("write_delay", self.entry_write_delay.get())
        self.cfg.set("read_ratio", self.entry_read_ratio.get())
        self.cfg.set("write_ratio", self.entry_write_ratio.get())
        self.cfg.set("ac_rest", self.entry_ac_rest.get())
        self.cfg.set("wa_shock", self.entry_wa_shock.get())
        self.cfg.set("max_retries", self.entry_max_retries.get())
        self.cfg.set("quality", self.combo_quality.get())
        self.cfg.set("custom_prompt", self.entry_custom_prompt.get())
        self.cfg.set("easy_bound", self.entry_easy_bound.get())
        self.cfg.set("mid_bound", self.entry_mid_bound.get())
        self.cfg.set("wait_judge", self.entry_wait_judge.get())
        self.cfg.set("retry_slow", self.entry_retry_slow.get())
        self.cfg.set("retry_fast", self.entry_retry_fast.get())
        self.cfg.set("hard_length", self.entry_hard_length.get())
        self.cfg.set("hard_strategy", self.combo_hard_strategy.get())
        self.cfg.set("super_strategy", self.combo_super_strategy.get())
        self.log_msg("配置已保存到 config.json")
        messagebox.showinfo("成功", "配置已保存")

    def fetch_difficulty_map(self):
        import re, json
        from playwright.sync_api import sync_playwright
        url = self.entry_url.get()
        if "/contest/" not in url:
            messagebox.showwarning("警告", "请在 OJ 网址中填入 Contest 页面链接")
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
                    rows = page.locator("table tr")
                    for i in range(rows.count()):
                        row = rows.nth(i)
                        try:
                            links = row.locator("a")
                            if links.count() > 0:
                                href = links.first.get_attribute("href") or ""
                                match = re.search(r'problem/([A-Za-z0-9]+)', href)
                                if match:
                                    pid = match.group(1)
                                    label_elem = row.locator(".ui.label")
                                    if label_elem.count() > 0:
                                        mapping[pid] = label_elem.first.inner_text().strip()
                        except: pass
                    browser.close()
                if mapping:
                    with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "difficulty.json"), "w", encoding="utf-8") as f:
                        json.dump(mapping, f, ensure_ascii=False, indent=4)
                    self.log_msg(f"✔️ 成功爬取 {len(mapping)} 条难度数据并保存")
                else:
                    self.log_msg("⚠️ 未爬取到难度数据")
            except Exception as e:
                self.log_msg(f"爬取难度异常: {e}")
        threading.Thread(target=_scrape, daemon=True).start()

    def show_settings(self):
        self.container_settings.pack(fill='x', padx=6, pady=2, before=self.root.winfo_children()[-1])                                                                                                     
        self.btn_open_settings.config(state='disabled')

    def hide_settings(self):
        self.container_settings.pack_forget()
        self.btn_open_settings.config(state='normal')

    def log_msg(self, msg):
        def _log():
            try:
                self.text_log.config(state="normal")
                self.text_log.insert("end", f"[{time.strftime('%H:%M:%S')}] {msg}\n")
                self.text_log.see("end")
                self.text_log.config(state="disabled")
            except Exception:
                pass
        self.root.after(0, _log)

    def _check_initial_reset(self):
        if self.state_mgr.state.get("date_str") and self.state_mgr.state.get("date_str") != self.state_mgr.last_logical_day:
            self.log_msg("🔄 检测到上次保存进度并非今日，自动执行跨日重置与启动...")
            self.root.after(2000, self._auto_reset_and_start)

    def schedule_next_reset(self):
        now = datetime.now()
        if now.hour < 4:
            next_4am = now.replace(hour=4, minute=0, second=0, microsecond=0)
        else:
            next_4am = (now + timedelta(days=1)).replace(hour=4, minute=0, second=0, microsecond=0)
            
        delay_ms = max(0, int((next_4am - now).total_seconds() * 1000))
        
        if hasattr(self, '_reset_timer'):
            self.root.after_cancel(self._reset_timer)
        self._reset_timer = self.root.after(delay_ms, self._on_scheduled_reset)

    def _on_scheduled_reset(self):
        current_day = self.state_mgr.get_logical_day()
        if current_day != self.state_mgr.last_logical_day:
            self.log_msg("🛑 已到达凌晨4点，触发跨日自动重启流程...")
            self.state_mgr.last_logical_day = current_day
            self._auto_reset_and_start()
        self.schedule_next_reset()

    def _auto_reset_and_start(self):
        self.log_msg("🛑 开始凌晨重启...")
        if self.is_running:
            self.stop_simulation()
            time.sleep(2)
        self.reset_daily_state(force=True)
        time.sleep(1)
        self.start_simulation()

    def reset_daily_state(self, force=False):
        if self.is_running and not force:
            messagebox.showwarning("警告", "请先停止模拟器再重置状态！")
            return
        if force or messagebox.askyesno("确认", "确定要清空今天的做题进度和休眠倒计时吗？"):
            self.state_mgr.reset_daily_state()
            self.log_msg("♻️ 已彻底清空今日状态缓存！")
            
    def _show_captcha_dialog_async(self, img_bytes):
        self.root.after(0, self._show_captcha_dialog, img_bytes)
        self.captcha_event.wait()
        res = self.captcha_result
        self.captcha_event.clear()
        return res

    def _show_captcha_dialog(self, img_bytes):
        try:
            from PIL import Image, ImageTk
            import io
            
            top = tk.Toplevel(self.root)
            top.title("请输入验证码")
            top.geometry("350x200")
            top.attributes('-topmost', True)
            top.transient(self.root)
            top.grab_set()
            
            img = Image.open(io.BytesIO(img_bytes))
            photo = ImageTk.PhotoImage(img)
            
            lbl_img = tk.Label(top, image=photo)
            lbl_img.image = photo 
            lbl_img.pack(pady=15)
            
            frame_inp = ttk.Frame(top)
            frame_inp.pack(pady=5)
            ttk.Label(frame_inp, text="验证码:").pack(side='left')
            
            entry = ttk.Entry(frame_inp, font=("Arial", 14), width=10)
            entry.pack(side='left', padx=5)
            entry.focus_set()
            
            def submit(event=None):
                self.captcha_result = entry.get().strip()
                top.destroy()
                self.captcha_event.set()
                
            def on_close():
                self.captcha_result = ""
                top.destroy()
                self.captcha_event.set()
                
            entry.bind("<Return>", submit)
            ttk.Button(top, text="确定", command=submit).pack(pady=10)
            top.protocol("WM_DELETE_WINDOW", on_close)
        except Exception as e:
            self.log_msg(f"验证码弹窗异常: {e}")
            self.captcha_result = ""
            self.captcha_event.set()

    def event_cb(self, event_type, val1=None, val2=None):
        def _handle():
            if event_type == "completed_update":
                self.update_tray_title(val1, val2)
            elif event_type == "stopped":
                self.is_running = False
                self.btn_start.config(state="normal")
                self.btn_stop.config(state="disabled")
                self.btn_open_settings.config(state="normal")
                self.btn_debug_check.config(state="normal")
                self.log_msg("任务执行已停止...")
        self.root.after(0, _handle)

    def _start_runner(self, is_retro=False):
        self.is_running = True
        self.btn_start.config(state="disabled")
        self.btn_stop.config(state="normal")
        self.btn_open_settings.config(state="disabled")
        self.btn_debug_check.config(state="disabled")
        self.hide_settings()
        
        target = int(self.spin_count.get() or 5)
        fluct = int(self.spin_fluctuation.get() or 2)
        state = self.state_mgr.load_or_init_daily_state(target, fluct)
        
        dir_str = "向后检查" if is_retro else "正向"
        self.log_msg(f"--- 启动拟人化刷题引擎[{state['date_str']}] ({dir_str}) ---")

        self.task_runner = TaskRunner(self.cfg, self.state_mgr, self.log_msg, self.event_cb)
        
        target_override = 9999 if is_retro else state["target_count"]
        completed = state["completed"]

        self.worker = threading.Thread(target=self.task_runner.run, args=(target_override, completed, is_retro, self.var_debug.get(), self.var_headless.get(), self._show_captcha_dialog_async), daemon=True)
        self.worker.start()

    def start_simulation(self):
        if not self.entry_url.get() or not self.entry_api.get():
            messagebox.showwarning("警告", "请填写完整的网址和API Key！")
            return
        self._start_runner(is_retro=False)

    def start_retro_check(self):
        if not self.entry_url.get() or not self.entry_api.get():
            messagebox.showwarning("警告", "请填写完整的网址和API Key！")
            return
        self._start_runner(is_retro=True)

    def stop_simulation(self):
        self.is_running = False
        if self.task_runner:
            self.task_runner.stop()
        self.log_msg("收到停止指令，正在退出模拟...")
        if self.task_runner and self.task_runner.current_working_url:
            if not getattr(self.task_runner, 'is_retro_check', False):
                match = re.search(r'(\d+)(/?)$', self.task_runner.current_working_url)
                if match:
                    self.cfg.set("start_id", match.group(1))

    def on_close(self):
        self.stop_simulation()
        if self.tray_icon is not None:
            try:
                self.tray_icon.stop()
            except:
                pass
        self.root.destroy()
        import os
        os._exit(0)

    def _on_window_unmap(self, event):
        if event.widget == self.root and self.root.state() == 'iconic':
            if self.var_tray.get() and HAS_TRAY:
                self.root.withdraw()
                self.show_tray_icon()

    def show_tray_icon(self):
        if self.tray_icon is not None:
            return
            
        image = Image.new('RGB', (64, 64), color=(0, 0, 0))
        d = ImageDraw.Draw(image)
        d.rectangle((16, 16, 48, 48), fill=(100, 200, 100))

        def on_show(icon, item):
            icon.stop()
            self.root.after(0, self.root.deiconify)
            self.tray_icon = None

        def on_exit(icon, item):
            icon.stop()
            self.stop_simulation()
            self.root.after(0, self.root.destroy)

        menu = (item('恢复窗口', on_show), item('强制停止并退出', on_exit))
        
        c = self.state_mgr.state.get('completed', 0) if self.state_mgr.state else 0
        t = self.state_mgr.state.get('target_count', '?') if self.state_mgr.state else '?'
        status_text = f"OJ 模拟器 | 进度: {c}/{t}"
        
        self.tray_icon = pystray.Icon("OJ_Sim", image, status_text, menu)
        threading.Thread(target=self.tray_icon.run, daemon=True).start()

    def update_tray_title(self, completed, target):
        if self.tray_icon is not None:
            self.tray_icon.title = f"OJ 模拟器 | 进度: {completed}/{target}"
