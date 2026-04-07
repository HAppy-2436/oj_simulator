import tkinter as tk
from tkinter import ttk, messagebox
import threading
import time
import random
import os
import json
import requests
import re
from datetime import datetime, timedelta
from playwright.sync_api import sync_playwright
import urllib.parse

try:
    import pystray
    from pystray import MenuItem as item
    from PIL import Image, ImageDraw
    HAS_TRAY = True
except ImportError:
    HAS_TRAY = False

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")
DIFFICULTY_FILE = os.path.join(BASE_DIR, "difficulty.json")
AUTH_STATE_FILE = os.path.join(BASE_DIR, "auth_state.json")

class SimulatorGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("OJ 鎷熶汉鍖栧埛棰樻ā鎷熷櫒")
        self.root.geometry("700x850")

        # 1. 涓绘帶鍖猴紙濮嬬粓鍙锛?
        self.frame_main_ctrl = ttk.Frame(self.root, padding=8)
        self.frame_main_ctrl.pack(fill='x', side='top')
        
        self.btn_open_settings = ttk.Button(self.frame_main_ctrl, text="鈿欙笍 璁剧疆", command=self.show_settings)
        self.btn_open_settings.pack(side='left', padx=6)

        self.var_headless = tk.BooleanVar(value=True)
        self.chk_headless = ttk.Checkbutton(self.frame_main_ctrl, text="馃懟 鏃犲ご妯″紡", variable=self.var_headless)
        self.chk_headless.pack(side='left', padx=6)

        self.var_debug = tk.BooleanVar(value=False)
        self.chk_debug = ttk.Checkbutton(self.frame_main_ctrl, text="馃殌 鏋侀€熻皟璇?, variable=self.var_debug)
        self.chk_debug.pack(side='left')

        self.var_log_llm = tk.BooleanVar(value=False)
        self.chk_log_llm = ttk.Checkbutton(self.frame_main_ctrl, text="馃挰 灞曞紑LLM鏃ュ織", variable=self.var_log_llm)
        self.chk_log_llm.pack(side='left', padx=6)

        self.var_tray = tk.BooleanVar(value=HAS_TRAY)
        self.chk_tray = ttk.Checkbutton(self.frame_main_ctrl, text="猬囷笍 鎵樼洏妯″紡", variable=self.var_tray)
        self.chk_tray.pack(side='left')
        if not HAS_TRAY:
            self.chk_tray.config(state='disabled')
            self.var_tray.set(False)

        self.btn_reset = ttk.Button(self.frame_main_ctrl, text="馃攧 閲嶇疆", command=lambda: self.reset_daily_state(force=False))
        self.btn_reset.pack(side='left', padx=6)

        self.btn_start = ttk.Button(self.frame_main_ctrl, text="鈻?寮€濮?, command=self.start_simulation)
        self.btn_start.pack(side='right', padx=6)
        
        self.btn_stop = ttk.Button(self.frame_main_ctrl, text="鈴?鍋滄", command=self.stop_simulation, state='disabled')
        self.btn_stop.pack(side='right')

        self.btn_debug_check = ttk.Button(self.frame_main_ctrl, text="馃攳 琛ユ紡妫€鏌?, command=self.start_retro_check)
        self.btn_debug_check.pack(side='right', padx=6)

        # 2. 璁剧疆闈㈡澘瀹瑰櫒锛堥粯璁ら殣钘忥紝鎸夐渶鎸傝浇锛?
        self.container_settings = ttk.Frame(self.root)
        
        # 鍐呴儴鏋勫缓鍚勪釜閰嶇疆妯″潡
        self._build_settings()

        # 3. 鏃ュ織鍖?
        frame_log = ttk.LabelFrame(self.root, text="杩愯鏃ュ織")
        frame_log.pack(fill='both', expand=True, padx=8, pady=8)
        self.text_log = tk.Text(frame_log, bg='white', fg='black', state='disabled')
        self.text_log.pack(fill='both', expand=True)

        self.is_running = False
        self.worker = None
        self.current_working_url = None
        self.state = {}
        self.tray_icon = None
        
        self.captcha_result = ""
        self.captcha_event = threading.Event()

        self.root.bind("<Unmap>", self._on_window_unmap)
        
        self.load_config()
        if not HAS_TRAY:
            self.log_msg("鈩癸笍 鎵樼洏妯″潡 (pystray, Pillow) 鏈畨瑁呫€傚闇€鏈€灏忓寲鍒版墭鐩樺姛鑳斤紝璇峰湪缁堢鎵ц: pip install pystray Pillow")

        # 鍒濆鍖栧悗鍙扮洃鎺у拰鍚姩鑷
        self.last_logical_day = self.get_logical_day()
        self.schedule_next_reset()
        self._check_initial_reset()

    def _check_initial_reset(self):
        state_file = os.path.join(BASE_DIR, "state.json")
        saved_day = None
        if os.path.exists(state_file):
            try:
                with open(state_file, "r", encoding="utf-8") as f:
                    st = json.load(f)
                    saved_day = st.get("date_str")
            except: pass
        if saved_day and saved_day != self.last_logical_day:
            self.log_msg("馃挕 妫€娴嬪埌涓婃淇濆瓨杩涘害骞堕潪浠婃棩(鏃ユ湡鎸佷箙鍖?锛岀涓€鏃堕棿鑷姩鎵ц璺ㄦ棩閲嶇疆涓庡惎鍔?..")
            self.root.after(2000, self._auto_reset_and_start)

    def schedule_next_reset(self):
        now = datetime.now()
        # 瀵绘壘涓嬩竴涓?4:00 AM
        if now.hour < 4:
            next_4am = now.replace(hour=4, minute=0, second=0, microsecond=0)
        else:
            next_4am = (now + timedelta(days=1)).replace(hour=4, minute=0, second=0, microsecond=0)
            
        # 鏀惧純 while True 姝诲惊鐜紝灏嗕簨浠跺噯纭帹鍏?Tk 涓诲惊鐜潵鍋氬欢杩?
        delay_ms = max(0, int((next_4am - now).total_seconds() * 1000))
        
        if hasattr(self, '_reset_timer'):
            self.root.after_cancel(self._reset_timer)
        self._reset_timer = self.root.after(delay_ms, self._on_scheduled_reset)

    def _on_scheduled_reset(self):
        current_day = self.get_logical_day()
        if current_day != self.last_logical_day:
            self.log_msg("鈴?宸插埌杈惧噷鏅?鐐?璁＄畻寰楀嚭鐨勭洰鏍囨椂闂寸偣)锛岃Е鍙戣法鏃ヨ嚜鍔ㄩ噸鍚祦绋?..")
            self.last_logical_day = current_day
            self._auto_reset_and_start()
        # 閲嶆柊鎺掓湡涓嬩竴涓?4AM
        self.schedule_next_reset()

    def _auto_reset_and_start(self):
        self.log_msg("鈴?鍑屾櫒4鐐?鏂扮殑涓€澶╁凡鍒拌揪锛佹鍦ㄦ墽琛岋細鍋滄 -> 閲嶇疆 -> 寮€濮?)
        if self.is_running:
            self.stop_simulation()
            time.sleep(2)
        self.reset_daily_state(force=True)
        time.sleep(1)
        self.start_simulation()

    def start_retro_check(self):
        if not self.entry_url.get() or not self.entry_api.get():
            messagebox.showwarning("璀﹀憡", "璇峰～鍐欏畬鏁寸殑缃戝潃鍜孉PI Key锛?)
            return

        self.is_running = True
        self.btn_start.config(state="disabled")
        self.btn_stop.config(state="normal")
        self.btn_open_settings.config(state="disabled")
        self.btn_debug_check.config(state="disabled")

        self.hide_settings()
        self.log_msg("--- 鍚姩鍚戝悗琛ユ紡妫€鏌ユā寮?---")

        # In check mode, we just override target logic
        self.worker = threading.Thread(target=self.run_bot, args=(9999, self.state.get("completed", 0), True), daemon=True)
        self.worker.start()

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
            self.is_running = False
            self.root.after(0, self.root.destroy)

        menu = (item('鎭㈠绐楀彛', on_show), item('寮哄埗鍋滄骞堕€€鍑?, on_exit))
        
        c = self.state.get('completed', 0) if self.state else 0
        t = self.state.get('target_count', '?') if self.state else '?'
        status_text = f"OJ 妯℃嫙鍣?| 杩涘害: {c}/{t}"
        
        self.tray_icon = pystray.Icon("OJ_Sim", image, status_text, menu)
        threading.Thread(target=self.tray_icon.run, daemon=True).start()

    def update_tray_title(self, completed, target):
        if self.tray_icon is not None:
            self.tray_icon.title = f"OJ 妯℃嫙鍣?| 杩涘害: {completed}/{target}"

    def _show_captcha_dialog(self, img_bytes):
        try:
            from PIL import Image, ImageTk
            import io
            
            top = tk.Toplevel(self.root)
            top.title("璇疯緭鍏ラ獙璇佺爜")
            top.geometry("350x200")
            top.attributes('-topmost', True)
            top.transient(self.root)
            top.grab_set()
            
            img = Image.open(io.BytesIO(img_bytes))
            photo = ImageTk.PhotoImage(img)
            
            lbl_img = tk.Label(top, image=photo)
            lbl_img.image = photo  # 淇濇寔寮曠敤
            lbl_img.pack(pady=15)
            
            frame_inp = ttk.Frame(top)
            frame_inp.pack(pady=5)
            ttk.Label(frame_inp, text="缁撴瀯(濡傜畻寮忕洿鎺ヨ緭鍏ョ粨鏋?:").pack(side='left')
            
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
            ttk.Button(top, text="纭畾", command=submit).pack(pady=10)
            top.protocol("WM_DELETE_WINDOW", on_close)
        except Exception as e:
            self.log_msg(f"楠岃瘉鐮佸脊绐楀紓甯? {e}")
            self.captcha_result = ""
            self.captcha_event.set()

    def get_logical_day(self):
        now = datetime.now()
        if now.hour < 4:
            return (now.date() - timedelta(days=1)).strftime("%Y-%m-%d")
        return now.strftime("%Y-%m-%d")

    def load_or_init_daily_state(self, expected_target, fluct):
        state_file = os.path.join(BASE_DIR, "state.json")
        logical_day = self.get_logical_day()
        state = {}
        if os.path.exists(state_file):
            try:
                with open(state_file, "r", encoding="utf-8") as f:
                    state = json.load(f)
            except: pass
            
        if state.get("date_str") != logical_day:
            # Add nonlinear perturbation to the daily target calculation
            perturbation = random.uniform(0.9, 1.1) ** random.uniform(1.2, 1.8)
            base_target = random.randint(max(1, expected_target - fluct), expected_target + fluct)
            target = int(base_target * perturbation)
            # Make sure it's at least 1
            target = max(1, target)
            
            state = {
                "date": logical_day,
                "date_str": logical_day,
                "completed": 0,
                "target_count": target,
                "next_wake_up": 0.0
            }
            self.save_daily_state(state)
        return state

    def save_daily_state(self, state=None):
        if state is None:
            state = self.state
        state_file = os.path.join(BASE_DIR, "state.json")
        try:
            with open(state_file, "w", encoding="utf-8") as f:
                json.dump(state, f, ensure_ascii=False, indent=4)
        except: pass

    def reset_daily_state(self, force=False):
        if self.is_running and not force:
            messagebox.showwarning("璀﹀憡", "璇峰厛鍋滄妯℃嫙鍣ㄥ啀閲嶇疆鐘舵€侊紒")
            return
        if force or messagebox.askyesno("纭", "纭畾瑕佹竻绌轰粖澶╃殑鍋氶杩涘害鍜屼紤鐪犲€掕鏃跺悧锛焅n(娓呴櫎鍚庡皢閲嶆柊鍒嗛厤鐩爣骞朵粠闆跺紑濮?"):
            self.state = {}
            state_file = os.path.join(BASE_DIR, "state.json")
            if os.path.exists(state_file):
                try:
                    os.remove(state_file)
                except Exception as e:
                    self.log_msg(f"鍒犻櫎鐘舵€佹枃浠跺け璐? {e}")
            self.log_msg("鈾伙笍 宸插交搴曟竻绌轰粖鏃ョ姸鎬佺紦瀛橈紒" + ("" if force else "涓嬫鐐瑰嚮銆愬紑濮嬨€戝皢閲嶆柊寮€濮嬨€?))

    def _build_settings(self):
        # 鍩虹閰嶇疆
        frame_base = ttk.LabelFrame(self.container_settings, text="鍩虹閰嶇疆", padding=10)
        frame_base.pack(fill="x", padx=10, pady=5)

        ttk.Label(frame_base, text="OJ 缃戝潃:").grid(row=0, column=0, sticky="e", pady=2)
        self.entry_url = ttk.Entry(frame_base, width=40)
        self.entry_url.grid(row=0, column=1, sticky="w", pady=2)

        ttk.Label(frame_base, text="璐﹀彿:").grid(row=1, column=0, sticky="e", pady=2)
        self.entry_user = ttk.Entry(frame_base, width=30)
        self.entry_user.grid(row=1, column=1, sticky="w", pady=2)

        ttk.Label(frame_base, text="瀵嗙爜:").grid(row=2, column=0, sticky="e", pady=2)
        self.entry_pwd = ttk.Entry(frame_base, width=30, show="*")
        self.entry_pwd.grid(row=2, column=1, sticky="w", pady=2)

        # 澶фā鍨嬮厤缃?
        frame_llm = ttk.LabelFrame(self.container_settings, text="LLM API 閰嶇疆", padding=10)
        frame_llm.pack(fill="x", padx=10, pady=5)

        ttk.Label(frame_llm, text="API Key:").grid(row=0, column=0, sticky="e", pady=2)
        self.entry_api = ttk.Entry(frame_llm, width=40)
        self.entry_api.grid(row=0, column=1, sticky="w", pady=2)
        
        ttk.Label(frame_llm, text="Base URL:").grid(row=1, column=0, sticky="e", pady=2)
        self.entry_base_url = ttk.Entry(frame_llm, width=40)
        self.entry_base_url.grid(row=1, column=1, sticky="w", pady=2)
        self.entry_base_url.insert(0, "https://api.openai.com/v1")

        # 绛栫暐閰嶇疆
        frame_policy = ttk.LabelFrame(self.container_settings, text="绛栫暐涓庨殢鏈鸿涓洪厤缃?, padding=10)
        frame_policy.pack(fill="x", padx=10, pady=5)

        ttk.Label(frame_policy, text="璧峰棰樺彿(濡?025):").grid(row=0, column=0, sticky="e", pady=2)
        self.entry_start_id = ttk.Entry(frame_policy, width=10)
        self.entry_start_id.grid(row=0, column=1, sticky="w", pady=2)

        ttk.Label(frame_policy, text="鏃ラ鏁板強娉㈠姩:").grid(row=1, column=0, sticky="e", pady=2)
        fc = ttk.Frame(frame_policy)
        fc.grid(row=1, column=1, sticky="w", pady=2)
        self.spin_count = ttk.Spinbox(fc, from_=1, to=100, width=5)
        self.spin_count.pack(side="left")
        self.spin_count.set(5)
        ttk.Label(fc, text=" 娉㈠姩(卤): ").pack(side="left")
        self.spin_fluctuation = ttk.Spinbox(fc, from_=0, to=50, width=5)
        self.spin_fluctuation.pack(side="left")
        self.spin_fluctuation.set(2)

        ttk.Label(frame_policy, text="鍋氶鏃舵(鏃?:").grid(row=2, column=0, sticky="e", pady=2)
        ft = ttk.Frame(frame_policy)
        ft.grid(row=2, column=1, sticky="w", pady=2)
        self.entry_time_start = ttk.Entry(ft, width=5); self.entry_time_start.pack(side="left"); self.entry_time_start.insert(0, "14")
        ttk.Label(ft, text=" 鍒?").pack(side="left")
        self.entry_time_end = ttk.Entry(ft, width=5); self.entry_time_end.pack(side="left"); self.entry_time_end.insert(0, "23")

        ttk.Label(frame_policy, text="闈炲仛棰樹紤鐪?鏃?:").grid(row=2, column=2, sticky="e", pady=2)
        self.entry_sleep_hours = ttk.Entry(frame_policy, width=15); self.entry_sleep_hours.insert(0, "2-3")
        self.entry_sleep_hours.grid(row=2, column=3, sticky="w", pady=2)

        ttk.Label(frame_policy, text="璇婚/鏁茬爜鍩虹寤惰繜:").grid(row=3, column=0, sticky="e", pady=2)
        f_delay = ttk.Frame(frame_policy)
        f_delay.grid(row=3, column=1, sticky="w", pady=2)
        self.entry_read_delay = ttk.Entry(f_delay, width=6); self.entry_read_delay.insert(0, "5-30")
        self.entry_read_delay.pack(side="left")
        ttk.Label(f_delay, text=" / ").pack(side="left")
        self.entry_write_delay = ttk.Entry(f_delay, width=6); self.entry_write_delay.insert(0, "10-120")
        self.entry_write_delay.pack(side="left")

        ttk.Label(frame_policy, text="璇?鍐欏瓧闀跨郴鏁?").grid(row=3, column=2, sticky="e", pady=2)
        f_ratio = ttk.Frame(frame_policy)
        f_ratio.grid(row=3, column=3, sticky="w", pady=2)
        self.entry_read_ratio = ttk.Entry(f_ratio, width=6); self.entry_read_ratio.insert(0, "0.1")
        self.entry_read_ratio.pack(side="left")
        ttk.Label(f_ratio, text=" / ").pack(side="left")
        self.entry_write_ratio = ttk.Entry(f_ratio, width=6); self.entry_write_ratio.insert(0, "0.2")
        self.entry_write_ratio.pack(side="left")

        ttk.Label(frame_policy, text="AC鍚庡紑蹇冧紤鎭?min-max):").grid(row=4, column=0, sticky="e", pady=2)
        self.entry_ac_rest = ttk.Entry(frame_policy, width=15); self.entry_ac_rest.insert(0, "30-300")
        self.entry_ac_rest.grid(row=4, column=1, sticky="w", pady=2)

        ttk.Label(frame_policy, text="鐪媁A闇囨儕鍋滈】(min-max):").grid(row=4, column=2, sticky="e", pady=2)
        self.entry_wa_shock = ttk.Entry(frame_policy, width=15); self.entry_wa_shock.insert(0, "15-60")
        self.entry_wa_shock.grid(row=4, column=3, sticky="w", pady=2)

        ttk.Label(frame_policy, text="閲嶈瘯鏋侀檺娆℃暟(min-max):").grid(row=5, column=0, sticky="e", pady=2)
        self.entry_max_retries = ttk.Entry(frame_policy, width=15); self.entry_max_retries.insert(0, "3-8")
        self.entry_max_retries.grid(row=5, column=1, sticky="w", pady=2)

        ttk.Label(frame_policy, text="浠ｇ爜璐ㄩ噺:").grid(row=6, column=0, sticky="e", pady=2)
        self.combo_quality = ttk.Combobox(frame_policy, values=["澶т竴钀屾柊 (鍋跺皵姹傚姪AI)", "澶т簩鐔熸墜 (浠ｇ爜瑙勮寖)", "绔炶禌鐢?(鏋佺畝绮剧偧)"], width=25, state="readonly")
        self.combo_quality.grid(row=6, column=1, columnspan=3, sticky="w", pady=2)
        self.combo_quality.set("澶т竴钀屾柊 (鍋跺皵姹傚姪AI)")

        ttk.Label(frame_policy, text="闄勫姞鎻愮ず璇?").grid(row=7, column=0, sticky="e", pady=2)
        self.entry_custom_prompt = ttk.Entry(frame_policy, width=40)
        self.entry_custom_prompt.grid(row=7, column=1, columnspan=3, sticky="w", pady=2)

        ttk.Label(frame_policy, text="闅鹃瑙勫垯(瀛楁暟):").grid(row=8, column=0, sticky="e", pady=2)
        f_hard = ttk.Frame(frame_policy)
        f_hard.grid(row=8, column=1, columnspan=3, sticky="w", pady=2)
        self.entry_hard_length = ttk.Entry(f_hard, width=5); self.entry_hard_length.insert(0, "1500")
        self.entry_hard_length.pack(side="left")
        
        ttk.Label(f_hard, text=" Hard:").pack(side="left")
        self.combo_hard_strategy = ttk.Combobox(f_hard, values=["姝ｅ父鍋?, "寤舵椂2鍊?, "寤舵椂3鍊?, "鑷姩璺宠繃"], width=7, state="readonly")
        self.combo_hard_strategy.pack(side="left")
        self.combo_hard_strategy.set("寤舵椂2鍊?)

        ttk.Label(f_hard, text=" Super:").pack(side="left")
        self.combo_super_strategy = ttk.Combobox(f_hard, values=["姝ｅ父鍋?, "寤舵椂3鍊?, "鑷姩璺宠繃"], width=7, state="readonly")
        self.combo_super_strategy.pack(side="left")
        self.combo_super_strategy.set("鑷姩璺宠繃")
        
        ttk.Button(f_hard, text="鑾峰彇棰樼洰闆嗛毦搴﹀瓧鍏?, command=self.fetch_difficulty_map).pack(side="left", padx=5)

        # 闈㈡澘鎺у埗
        fbtn = ttk.Frame(self.container_settings)
        fbtn.pack(fill="x", padx=10, pady=5)
        ttk.Button(fbtn, text="馃捑 淇濆瓨閰嶇疆", command=self.save_config).pack(side="left")
        ttk.Button(fbtn, text="鉁?鍏抽棴闈㈡澘", command=self.hide_settings).pack(side="right")

    def show_settings(self):
        try:
            self.container_settings.pack(fill='x', padx=6, pady=2, before=self.root.winfo_children()[-1])
            self.btn_open_settings.config(state='disabled')
        except Exception as e:
            self.log_msg(f"鎵撳紑璁剧疆寮傚父: {e}")

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
            "sleep_hours": self.entry_sleep_hours.get(),
            "read_delay": self.entry_read_delay.get(), "write_delay": self.entry_write_delay.get(),
            "wa_shock": self.entry_wa_shock.get(),
            "ac_rest": self.entry_ac_rest.get(), "max_retries": self.entry_max_retries.get(),
            "custom_prompt": self.entry_custom_prompt.get(),
            "read_ratio": self.entry_read_ratio.get(),
            "write_ratio": self.entry_write_ratio.get(),
            "hard_length": self.entry_hard_length.get(),
            "hard_strategy": self.combo_hard_strategy.get(),
            "super_strategy": self.combo_super_strategy.get()
        }
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=4)
        self.log_msg("閰嶇疆宸蹭繚瀛樺埌 config.json")
        messagebox.showinfo("鎴愬姛", "閰嶇疆宸蹭繚瀛?)

    def fetch_difficulty_map(self):
        url = self.entry_url.get()
        if "/contest/" not in url:
            messagebox.showwarning("璀﹀憡", "璇峰湪 OJ 缃戝潃涓～鍏?Contest 椤甸潰閾炬帴\n渚嬪: https://acm.ecnu.edu.cn/contest/43/")
            return
            
        def _scrape():
            self.log_msg("姝ｅ湪鍚庡彴鐖彇棰樼洰闆嗛毦搴︽槧灏勶紝璇风◢鍊?..")
            try:
                with sync_playwright() as p:
                    browser = p.chromium.launch(headless=True)
                    page = browser.new_page()
                    page.goto(url, timeout=30000)
                    time.sleep(2)
                    
                    mapping = {}
                    # 灏濊瘯鏌ユ壘鍖呭惈棰樺彿鍜屾爣绛剧殑琛?
                    rows = page.locator("table tr")
                    count = rows.count()
                    for i in range(count):
                        row = rows.nth(i)
                        try:
                            # 鎻愬彇甯︽湁閾炬帴鐨勫厓绱犻€氬父鏄噸鐐?
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
                    self.log_msg(f"鉁?鎴愬姛鐖彇 {len(mapping)} 鏉￠毦搴︽暟鎹苟淇濆瓨鑷?difficulty.json")
                else:
                    self.log_msg("鈿狅笍 鏈埇鍙栧埌闅惧害鏁版嵁锛岃纭椤甸潰鏄惁闇€瑕佺櫥褰曟垨缁撴瀯鏄惁鍖归厤銆?)
            except Exception as e:
                self.log_msg(f"鐖彇闅惧害寮傚父: {e}")
                
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
                try: self.entry_sleep_hours.delete(0, "end"); self.entry_sleep_hours.insert(0, config.get("sleep_hours", "2-3"))
                except: pass
                self.combo_quality.set(config.get("quality", "澶т竴钀屾柊 (鍋跺皵姹傚姪AI)"))
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
                try: self.combo_hard_strategy.set(config.get("hard_strategy", "寤舵椂2鍊?))
                except: pass
                try: self.combo_super_strategy.set(config.get("super_strategy", "鑷姩璺宠繃"))
                except: pass
                self.log_msg("宸插姞杞藉巻鍙查厤缃€?)
            except Exception as e:
                self.log_msg(f"鍔犺浇閰嶇疆澶辫触: {e}")

    def get_rand_range(self, val_str, default_min, default_max):
        try:
            parts = val_str.split('-')
            return int(parts[0]), int(parts[1])
        except:
            return default_min, default_max

    def sim_sleep(self, val_str, def_min, def_max, msg_prefix="", extra_offset=0):
        rmin, rmax = self.get_rand_range(val_str, def_min, def_max)
        base_val = random.randint(rmin, rmax)
        
        # 澧炲姞闈炵嚎鎬ф壈鍔紝寮曞叆瀵规暟姝ｆ€佸垎甯冩垨鍗曠函鐨勫箓娆″彉鎹㈡墦鐮村潎鍖€鍒嗗竷鐨勬湡鏈?
        perturbation = random.uniform(0.8, 1.2) ** random.uniform(1.5, 2.5)
        val = int(base_val * perturbation) + int(extra_offset)
        
        if self.var_debug.get():
            val = random.randint(1, 3) # 璋冭瘯妯″紡鏋侀€熻烦杩?
            
        now = time.time()
        wakeup = self.state.get("next_wake_up", 0.0)
        
        # 鍚告敹鎸佷箙鍖栦笅鏉ョ殑鍓╀綑浼戠湢鏃堕棿
        if wakeup > now:
            val = int(wakeup - now)
            self.state["next_wake_up"] = 0.0
            self.save_daily_state()
        else:
            # 鍒╃敤 datetime 璁＄畻鍑轰竴涓‘瀹氱殑鍞ら啋鏃跺埢骞舵寔涔呭寲淇濆瓨
            self.state["next_wake_up"] = now + val
            self.save_daily_state()

        if msg_prefix:
            self.log_msg(f"{msg_prefix}: 棰勮灏嗗湪 {datetime.fromtimestamp(now + val).strftime('%H:%M:%S')} 缁撴潫浼戠湢")
            
        # 浣跨敤鍩轰簬妫€娴嬬郴缁熸椂闂存祦閫濈殑鏂规硶鏇夸唬寰幆姝荤瓑 time.sleep(1) 瑙ｅ喅寰呮満鍋滄粸闂
        target_time = time.time() + val
        while time.time() < target_time:
            if not self.is_running: 
                break
            time.sleep(0.5)
            
        # 鎵ц瀹屾瘯涓旀病琚腑姝紝娓呯┖鐫＄湢鏍囪
        if self.is_running:
            self.state["next_wake_up"] = 0.0
            self.save_daily_state()

    def start_simulation(self):
        if not self.entry_url.get() or not self.entry_api.get():
            messagebox.showwarning("璀﹀憡", "璇峰～鍐欏畬鏁寸殑缃戝潃鍜?API Key锛?)
            return
            
        expected_target = int(self.spin_count.get() or 5)
        fluct = int(self.spin_fluctuation.get() or 2)
        self.state = self.load_or_init_daily_state(expected_target, fluct)
            
        self.is_running = True
        self.btn_start.config(state="disabled")
        self.btn_stop.config(state="normal")
        self.btn_open_settings.config(state="disabled")
        
        self.hide_settings()
        self.log_msg(f"--- 鍚姩鎷熶汉鍖栧埛棰樺紩鎿?[{self.state['date_str']}] ---")
        
        actual_target = self.state["target_count"]
        completed = self.state["completed"]
        
        self.worker = threading.Thread(target=self.run_bot, args=(actual_target, completed), daemon=True)
        self.worker.start()

    def stop_simulation(self):
        self.is_running = False
        self.btn_start.config(state="normal")
        self.btn_stop.config(state="disabled")
        self.btn_open_settings.config(state="normal")
        
        if getattr(self, 'current_working_url', None):
            self.save_start_id(self.current_working_url)
            
        self.log_msg("鏀跺埌鍋滄鎸囦护锛屾鍦ㄩ€€鍑烘ā鎷?..")

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
        
        if self.var_log_llm.get():
            try:
                log_prompt = "\n".join([f"[{m['role']}]: {m['content']}" for m in messages])
                self.log_msg(f"馃挰 [LLM璇锋眰]:\n{log_prompt}\n" + "-"*35)
            except: pass
            
        try:
            response = requests.post(f"{base_url}/chat/completions", headers=headers, json=data, timeout=60)
            res_json = response.json()
            code = res_json['choices'][0]['message']['content'].strip()
            
            if self.var_log_llm.get():
                self.log_msg(f"馃挰 [LLM鍝嶅簲]:\n{code}\n" + "-"*35)
                
            code = re.sub(r"^```[a-zA-Z+]*\n", "", code)
            return re.sub(r"\n```$", "", code)
        except Exception as e:
            self.log_msg(f"澶фā鍨?API 璇锋眰寮傚父: {e}")
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
                # Ensure we capture page navigation or status changes if any after click
                with page.expect_response("**/submit**", timeout=5000) as response_info:
                    try:
                        submit_btn.first.click()
                    except:
                        pass
            else:
                page.keyboard.press(f"{modifier}+Enter")
            # Extra wait for safety to let result load
            time.sleep(2)
        except:
            self.log_msg("娉ㄥ叆鎴栨彁浜ゆ搷浣滃厓绱犳湭灏辩华鎴栨湭鎹曡幏鍒板搷搴?..")

    def wait_for_judgment_result(self, page):
        """寰幆绛夊緟锛岀洿鍒版秷闄?In queue 鐘舵€侊紝骞惰繑鍥炴槸鍚C"""
        max_wait = 20 # 鏈€澶х瓑寰?0娆?绾?0绉?锛岄伩鍏嶆寰幆
        for i in range(max_wait):
            try:
                # 妫€鏌ユ槸鍚﹀寘鍚?in queue (鎺掗槦涓? 鎴?judge (鍒ら涓?
                status_span = page.locator(".ui.header.status-span, .status").first
                if status_span.count() > 0:
                    status_text = status_span.inner_text().lower()
                    if "queue" in status_text or "judging" in status_text or "compiling" in status_text:
                        self.log_msg("绋嬪簭浠嶅湪鎺掗槦鎴栧垽棰樹腑锛岀瓑寰?..")
                        time.sleep(2)
                        continue
                    
                    # 鍙栨渶鍚庝竴涓崟璇嶇洿鎺ュ垽鏂鏋滄槸 green 鎴栬€?accepted 鍒?AC
                    classes = status_span.evaluate("el => el.className").lower()
                    if "green" in classes or "accepted" in status_text:
                        return True
                    if "red" in classes or "grey" in status_text:
                        return False
            except Exception:
                pass

            # 鍏煎妫€娴? 鍙鏈?green message 鐩存帴鍒ゆ柇绛夊悓浜嶢C
            try:
                ac_element = page.locator(".ui.green.message, .status.accepted, td:has-text('Accepted')").first
                is_ac = ac_element.count() > 0 or ("accepted" in page.locator(".ui.message").inner_text().lower())
                if is_ac:
                    return True
            except:
                page_text = page.inner_text("body").lower()
                # 淇濆畧鎵弿
                if ("accepted" in page_text) or ("绛旀姝ｇ‘" in page_text):
                    return True
            time.sleep(2)

        return False

    def increment_url(self, url):
        match = re.search(r'(\d+)(/?)$', url)
        if match:
            current_id = int(match.group(1))
            return url[:match.start(1)] + str(current_id + 1) + match.group(2)
        return url

    def decrement_url(self, url):
        match = re.search(r'(\d+)(/?)$', url)
        if match:
            current_id = int(match.group(1))
            return url[:match.start(1)] + str(current_id - 1) + match.group(2)
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

    def run_bot(self, target, completed, is_retro_check=False):
        headless = self.var_headless.get()
        # Initialize working url based on retro check mode
        if is_retro_check:
            base_url = self.entry_url.get().strip()
            start_id = self.entry_start_id.get().strip()
            self.current_working_url = f"{base_url}{start_id}" if not base_url.endswith(start_id) else base_url
            self.current_working_url = self.decrement_url(self.current_working_url)
        else:
            if not self.current_working_url:
                base_url = self.entry_url.get().strip()
                start_id = self.entry_start_id.get().strip()
                self.current_working_url = f"{base_url}{start_id}" if not base_url.endswith(start_id) else base_url

        try:
            t_start = int(self.entry_time_start.get().strip() or "14")
            t_end = int(self.entry_time_end.get().strip() or "23")
        except:
            t_start, t_end = 14, 23

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=headless)
                context = browser.new_context()
                page = context.new_page()

                try:
                    input_url = self.entry_url.get()
                    parsed_uri = urllib.parse.urlparse(input_url)
                    base_url = f"{parsed_uri.scheme}://{parsed_uri.netloc}"
                    login_url = f"{base_url}/login/"
                    
                    self.log_msg("妫€鏌ュ綋鍓嶅嚟璇佷笌鐧诲綍鐘舵€?..")
                    page.goto(login_url)
                    time.sleep(2)
                    
                    if page.locator("#id_username").count() > 0:
                        try:
                            page.fill("#id_username", self.entry_user.get())
                            page.fill("#id_password", self.entry_pwd.get())
                            
                            captcha_img = page.locator('img.captcha, img[src*="captcha"]').first
                            if captcha_img.count() > 0:
                                self.log_msg("妫€娴嬪埌楠岃瘉鐮侊紝姝ｅ湪鎴彇骞剁瓑寰呰緭鍏?..")
                                img_bytes = captcha_img.screenshot()
                                
                                self.captcha_event.clear()
                                self.root.after(0, self._show_captcha_dialog, img_bytes)
                                self.captcha_event.wait()

                                if self.captcha_result:
                                    # Ensure we specifically select the visible text input field for captcha, 
                                    # avoiding hidden fields like id_captcha_0
                                    captcha_input = page.locator('input[type="text"][name*="captcha"], #id_captcha_1').first
                                    if captcha_input.count() > 0:
                                        captcha_input.fill(self.captcha_result)

                        except Exception as e:
                            self.log_msg(f"鐧诲綍鐜妭寮傚父: {e}")
                    else:
                        self.log_msg("鉁?璇诲彇鍒颁簡鏈夋晥鐨勬湰鍦扮櫥褰曞嚟璇佺紦瀛橈紝鍏嶉獙璇佺爜鐩存帴杩涘叆绯荤粺锛?)

                    completed = 0
                    
                    while completed < target and self.is_running:
                        # 瀵逛簬甯歌琛ユ紡妯″紡锛屽鏋滄病鏈夋槑纭殑鐩爣棰樺彿锛屽垯鍙互鏃犻檺鍚戝悗鏌ワ紝鐩村埌鍙戠敓閫€鍑烘潯浠?
                        
                        now = datetime.now()
                        hr = now.hour
                        if not (t_start <= hr < t_end):
                            smin, smax = self.get_rand_range(self.entry_sleep_hours.get(), 2, 3)
                            sleep_hours = random.randint(smin, smax)
                            sleep_seconds = sleep_hours * 3600
                            wakeup_time = time.time() + sleep_seconds
                            self.state["next_wake_up"] = wakeup_time
                            self.save_daily_state()
                            
                            self.log_msg(f"闈炲仛棰樻椂娈?{t_start}-{t_end})锛屾寜浣滄伅浼戠湢鍒?{datetime.fromtimestamp(wakeup_time).strftime('%H:%M:%S')}...")
                            
                            # 鍏煎绯荤粺寰呮満鐨勬椂闂村樊琛ュ伩
                            while time.time() < wakeup_time:
                                if not self.is_running: break
                                time.sleep(0.5)
                                
                            if self.is_running:
                                self.state["next_wake_up"] = 0.0
                                self.save_daily_state()
                            continue

                        page.goto(self.current_working_url)
                        time.sleep(3)
                        self.log_msg(f"\n[{completed+1}/{target if not is_retro_check else '琛ユ紡'}] 瀹℃煡棰樼洰: {self.current_working_url}")

                        try:
                            code_content = page.locator(".ace_text-layer").inner_text(timeout=2000).strip()
                            if len(code_content) > 10:
                                # 宸叉湁浠ｇ爜鎻愪氦锛屽垽瀹氭槸鍚C
                                is_ac_already = False
                                
                                # 妫€鏌ユ槸鍚︽湁缁胯壊鐨勫凡閫氳繃鏍囧織鎴朅ccepted鏂囧瓧
                                try:
                                    status_span = page.locator(".ui.header.status-span, .status").first
                                    if status_span.count() > 0:
                                        classes = status_span.evaluate("el => el.className").lower()
                                        status_text = status_span.inner_text().lower()
                                        if "green" in classes or "accepted" in status_text:
                                            is_ac_already = True
                                        elif "red" in classes or "grey" in status_text:
                                            is_ac_already = False
                                    
                                    if not is_ac_already:
                                        ac_element = page.locator(".ui.green.message, .status.accepted, td:has-text('Accepted')").first
                                        if ac_element.count() > 0 or ("accepted" in page.locator(".ui.message").inner_text().lower()):
                                            is_ac_already = True
                                except:
                                    pass

                                if is_ac_already:
                                    self.log_msg("鉁旓笍 璇ラ宸睞C閫氳繃锛岃烦杩囷紒")
                                    self.current_working_url = self.decrement_url(self.current_working_url) if is_retro_check else self.increment_url(self.current_working_url)
                                    continue
                                else:
                                    self.log_msg("鈿狅笍 璇ラ鏇炬彁浜や絾鏈狝C锛岀幇鍦ㄥ紑濮嬭В鍐筹紒")
                        except: pass

                        try:
                            problem_text = page.locator(".twelve.wide.column").inner_text(timeout=5000).strip()
                        except:
                            self.log_msg("鎻愬彇棰樼洰澶辫触鎵句笅涓€棰?..")
                            self.current_working_url = self.decrement_url(self.current_working_url) if is_retro_check else self.increment_url(self.current_working_url)
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
                        
                        # 棣栧厛灏濊瘯浠庡瓧鍏镐腑鍒ゆ柇
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
                        is_super = False
                        if mapped_diff:
                            self.log_msg(f"馃彿锔?鏈瀛楀吀鏍囩: [{mapped_diff}]")
                            if "Super" in mapped_diff or "鏋侀毦" in mapped_diff:
                                is_super = True
                            elif "Hard" in mapped_diff or "鍥伴毦" in mapped_diff:
                                is_hard = True
                        else:
                            if (problem_len >= hard_threshold * 1.5) or ("鏋侀毦" in problem_text) or ("super" in problem_text.lower()):
                                is_super = True
                            elif (problem_len >= hard_threshold) or ("鍥伴毦" in problem_text) or ("hard" in problem_text.lower()):
                                is_hard = True
                        
                        hard_strgy = self.combo_hard_strategy.get()
                        super_strgy = self.combo_super_strategy.get()
                        
                        applied_strategy = "姝ｅ父鍋?
                        if is_super:
                            applied_strategy = super_strgy
                            self.log_msg(f"鈿狅笍 妫€娴嬪埌鏈闅惧害鏋侀珮銆愭瀬闅?Super銆戯紒")
                        elif is_hard:
                            applied_strategy = hard_strgy
                            self.log_msg(f"鈿狅笍 妫€娴嬪埌鏈闅惧害杈冮珮銆愬洶闅?Hard銆?瀛楁暟{problem_len}鎴栧惈鏍囩)锛?)
                            
                        if applied_strategy == "鑷姩璺宠繃":
                            self.log_msg("鈴?绛栫暐涓鸿嚜鍔ㄨ烦杩囪棰樸€?)
                            self.current_working_url = self.decrement_url(self.current_working_url) if is_retro_check else self.increment_url(self.current_working_url)
                            continue
                        elif applied_strategy == "寤舵椂2鍊?:
                            self.log_msg("鈴?绛栫暐瑙﹀彂锛屾椂闂村€嶇巼鏀惧ぇ2鍊嶃€?)
                            r_ratio *= 2.0
                            w_ratio *= 2.0
                        elif applied_strategy == "寤舵椂3鍊?:
                            self.log_msg("鈴?绛栫暐瑙﹀彂锛屾椂闂村€嶇巼鏀惧ぇ3鍊嶃€?)
                            r_ratio *= 3.0
                            w_ratio *= 3.0

                        # 涓烘寜瀛楁暟/浠ｇ爜閲忕殑绯绘暟涔熷姞鍏ヂ?0%~30%鐨勯潪绾挎€ф壈鍔紝鎵撶牬缁濆姣斾緥
                        r_ratio *= random.uniform(0.7, 1.3) ** random.uniform(1.2, 1.5)
                        read_offset = int(problem_len * r_ratio)
                        self.sim_sleep(self.entry_read_delay.get(), 5, 30, f"闃呰棰樼洰({problem_len}瀛? +{read_offset}s)", read_offset)
                        if not self.is_running: break

                        quality = self.combo_quality.get()
                        if problem_len < 500:
                            bug_prompt = "鍩虹棰橈紝涓嶅噯鐣橞ug锛屽繀椤讳竴鍙慉C銆?
                        elif problem_len < 1200:
                            bug_prompt = "涓瓑棰橈紝銆愭晠鎰忕暀1鍒?涓殣绉樻瀬鍊奸敊璇€戯紝浣嗐€愬繀椤荤粷瀵归€氳繃鏍蜂緥杈撳叆杈撳嚭銆戙€?
                        else:
                            bug_prompt = "闅鹃锛屻€愬繀椤绘晠鎰忓啓閫昏緫鏄庢樉鐨勮秺鐣屻€佹棤鐗瑰垽閿欒銆戯紝浣嗐€愮粷瀵硅姹傞€氳繃鏍蜂緥杈撳叆娴嬭瘯銆戙€?
                            
                        custom_prompt = self.entry_custom_prompt.get().strip()
                        custom_addon = f"闄勫姞瑕佹眰锛歿custom_prompt}銆? if custom_prompt else ""
                            
                        messages = [
                            {"role": "system", "content": f"鎵紨涓€鍚峽quality}姝ｅ湪鍒风畻娉曢銆備笉瑕佹敞閲婏紝鍙橀噺鍚嶅崟涓€锛屾瀬浣庤川閲忎唬鐮佽鍒欙細{bug_prompt} {custom_addon} 瀹屽叏绾噣杈撳嚭C++瀹炰綋锛屾棤markdown銆?},
                            {"role": "user", "content": f"棰樼洰鍙婃牱渚嬶細\n{problem_text}"}
                        ]
                        
                        self.log_msg("鑾峰彇鍒濈増浠ｇ爜...")
                        generated_code = self.call_llm_api(messages)
                        if not generated_code: continue

                        code_len = len(generated_code)
                        w_ratio *= random.uniform(0.7, 1.3) ** random.uniform(1.2, 1.5)
                        write_offset = int(code_len * w_ratio)
                        self.sim_sleep(self.entry_write_delay.get(), 10, 120, f"缂栧啓浠ｇ爜寤舵椂({code_len}瀛? +{write_offset}s)", write_offset)
                        if not self.is_running: break
                        
                        self.inject_and_submit(page, generated_code)

                        self.sim_sleep("10-15", 10, 15, "绛夊緟绯荤粺寮€濮嬪垽棰?)
                        
                        is_ac = self.wait_for_judgment_result(page)

                        if not is_ac:
                            self.log_msg("鉂?鍙戠敓 Wrong Answer / 璇硶閿欒...")
                            m_min, m_max = self.get_rand_range(self.entry_max_retries.get(), 3, 8)
                            base_retries = random.randint(m_min, m_max)
                            perturbation = random.uniform(0.9, 1.1) ** random.uniform(1.2, 1.8)
                            max_retries = int(base_retries * perturbation)
                            max_retries = max(1, max_retries) # Ensure at least 1 retry
                            retry_count = 0
                            
                            self.sim_sleep(self.entry_wa_shock.get(), 15, 60, "闇囨儕骞舵鏌ユ姤閿?)
                            
                            while not is_ac and retry_count < max_retries and self.is_running:
                                retry_count += 1
                                if retry_count > 3:
                                    self.sim_sleep("5-15", 5, 15, f"绗瑊retry_count}娆℃€ヨ簛淇敼")
                                else:
                                    self.sim_sleep("10-40", 10, 40, f"绗瑊retry_count}娆℃€濊€冧慨鏀筨ug")

                                messages.append({"role": "assistant", "content": generated_code})
                                messages.append({"role": "user", "content": f"绗瑊retry_count}娆℃彁浜や緷鐒舵病杩囥€傚彧淇竴涓綘璁や负鏈€鏄庢樉鐨刡ug锛佷笉瑕佷竴娆℃€т慨瀹岋紒淇濇寔浠ｇ爜椋庢牸鎭跺姡鏃犳敞閲婅繃鏍蜂緥銆?})
                                generated_code = self.call_llm_api(messages)
                                if not self.is_running or not generated_code: break

                                self.inject_and_submit(page, generated_code)
                                self.sim_sleep("10-15", 10, 15, "閲嶈瘯鎻愪氦鍚庣瓑寰呯郴缁熷紑濮嬪垽棰?)
                                is_ac = self.wait_for_judgment_result(page)

                            if not is_ac: self.log_msg(f"馃槶 杩炵画{retry_count}娆A锛岀牬闃插純棰橈紒")
                            else: self.log_msg(f"鉁旓笍 绗瑊retry_count}娆￠噸璇曢€氳繃銆?)
                        else:
                            self.log_msg("鉁旓笍 棣栧彂 Accepted 閫氳繃锛?)

                        if not is_retro_check or is_ac:
                            completed += 1
                            self.state["completed"] = completed
                            self.save_daily_state()

                        self.current_working_url = self.decrement_url(self.current_working_url) if is_retro_check else self.increment_url(self.current_working_url)

                        if not is_retro_check:
                            self.update_tray_title(completed, target)
                        
                        self.sim_sleep(self.entry_ac_rest.get(), 30, 300, f"鍋氶瀹屾垚浼戠湢(褰撳墠 {'琛ユ紡妯″紡' if is_retro_check else f'{completed}/{target}'})")

                except Exception as e:
                    self.log_msg(f"鏍稿績寰幆鎶ラ敊缁堟: {e}")
                finally:
                    context.close()
                    browser.close()

        except Exception as e:
            self.log_msg(f"澶栧眰寰幆鎶ラ敊缁堟: {e}")

        self.stop_simulation()
        if hasattr(self, 'btn_debug_check'):
            self.btn_debug_check.config(state="normal")

if __name__ == '__main__':
    root = tk.Tk()
    app = SimulatorGUI(root)
    root.protocol('WM_DELETE_WINDOW', lambda: (setattr(app, 'is_running', False), root.destroy()))
    root.mainloop()
