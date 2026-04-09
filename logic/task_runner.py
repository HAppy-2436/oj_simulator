import time
import random
import re
import urllib.parse
from datetime import datetime
from playwright.sync_api import sync_playwright
import os
import json

from core.llm_client import LLMClient
from automation.bot_actions import BotActions

class TaskRunner:
    def __init__(self, config_manager, state_manager, log_callback, event_callback):
        self.cfg = config_manager
        self.state_mgr = state_manager
        self.log = log_callback
        self.event_callback = event_callback
        self.actions = BotActions(self.log)
        self.is_running = False
        self.current_working_url = None

    def get_rand_range(self, val_str, default_min, default_max):
        try:
            parts = val_str.split('-')
            return int(parts[0]), int(parts[1])
        except Exception:
            return default_min, default_max

    def sim_sleep(self, val_str, def_min, def_max, msg_prefix="", extra_offset=0, is_debug=False):
        rmin, rmax = self.get_rand_range(val_str, def_min, def_max)
        base_val = random.randint(rmin, rmax)
        perturbation = random.uniform(0.8, 1.2) ** random.uniform(1.5, 2.5)
        val = int((base_val + extra_offset) * perturbation)

        calc_detail = f"((基础:{base_val}s + 字长偏置:{int(extra_offset)}s) × 扰动:{perturbation:.2f} = {val}s)"
        
        if is_debug:
            val = random.randint(1, 3) 
            calc_detail = f"(极速调试模式强制压缩 -> {val}s)"

        now = time.time()
        wakeup = self.state_mgr.state.get("next_wake_up", 0.0)

        if wakeup > now:
            val = int(wakeup - now)
            self.state_mgr.update_next_wake_up(0.0)
            calc_detail += " [恢复之前未完成的休眠]"
        else:
            self.state_mgr.update_next_wake_up(now + val)

        if msg_prefix:
            self.log(f"{msg_prefix}: 预计延迟 {val}秒 {calc_detail} -> 到 {datetime.fromtimestamp(now + val).strftime('%H:%M:%S')} 结束")                                                                      
        target_time = time.time() + val
        while time.time() < target_time:
            if not self.is_running:
                break
            time.sleep(0.5)

        if self.is_running:
            self.state_mgr.update_next_wake_up(0.0)

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

    def run(self, target, completed, is_retro_check=False, is_debug=False, headless=True, captcha_resolver=None):
        self.is_running = True
        self.is_retro_check = is_retro_check
        
        base_url = self.cfg.get("url", "").strip()
        start_id = self.cfg.get("start_id", "").strip()
        
        if not base_url.endswith("problem/") and "problem" not in base_url.split("/")[-2:]:
            if not base_url.endswith("/"):
                base_url += "/"
            base_url += "problem/"
            
        start_url = f"{base_url}{start_id}" if not base_url.endswith(start_id) else base_url
        if is_retro_check:
            self.current_working_url = self.decrement_url(start_url)
        else:
            self.current_working_url = self.current_working_url or start_url

        try:
            t_start = int(self.cfg.get("time_start", "14").strip() or "14")
            t_end = int(self.cfg.get("time_end", "23").strip() or "23")
        except Exception:
            t_start, t_end = 14, 23

        llm = LLMClient(self.cfg.get("api_key", "").strip(), 
                        "deepseek-chat" if "deepseek" in self.cfg.get("base_url", "https://api.openai.com/v1").lower() else "gpt-3.5-turbo",
                        self.cfg.get("base_url", "https://api.openai.com/v1").strip())

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=headless)
                
                auth_file = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "auth_state.json")
                if os.path.exists(auth_file):
                    context = browser.new_context(storage_state=auth_file)
                else:
                    context = browser.new_context()

                page = context.new_page()

                try:
                    parsed_uri = urllib.parse.urlparse(base_url)
                    b_url = f"{parsed_uri.scheme}://{parsed_uri.netloc}"
                    login_url = f"{b_url}/login/"

                    self.log("检查当前凭证与登录状态...")
                    page.goto(login_url)
                    time.sleep(2)

                    if page.locator("#id_username").count() > 0:
                        try:
                            page.fill("#id_username", self.cfg.get("user", ""))
                            page.fill("#id_password", self.cfg.get("pwd", ""))

                            captcha_img = page.locator('img.captcha, img[src*="captcha"]').first 
                            if captcha_img.count() > 0:
                                self.log("检测到验证码...")
                                if captcha_resolver:
                                    img_bytes = captcha_img.screenshot()
                                    captcha_result = captcha_resolver(img_bytes)
                                    if captcha_result:
                                        captcha_input = page.locator('input[type="text"][name*="captcha"], #id_captcha_1').first
                                        if captcha_input.count() > 0:
                                            captcha_input.fill(captcha_result)
                                            # Wait for user to trigger submit or manually simulate submit if it works this way
                                            page.keyboard.press("Enter")
                                            time.sleep(3)
                            else:
                                page.keyboard.press("Enter")
                                time.sleep(3)
                        except Exception as e:
                            self.log(f"登录环节异常: {e}")
                    else:
                        self.log("✔️ 读取到了有效登录状态...")

                    # Attempt to save state unconditionally to update cookies
                    try:
                        auth_file = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "auth_state.json")
                        context.storage_state(path=auth_file)
                    except Exception:
                        pass

                    while completed < target and self.is_running:
                        now = datetime.now()
                        hr = now.hour
                        if not (t_start <= hr < t_end):
                            smin, smax = self.get_rand_range(self.cfg.get("sleep_hours", "2-3"), 2, 3) 
                            sleep_seconds = random.randint(smin, smax) * 3600
                            wakeup_time = time.time() + sleep_seconds
                            self.state_mgr.update_next_wake_up(wakeup_time)

                            self.log(f"非做题时段({t_start}-{t_end})，按作息休眠到: {datetime.fromtimestamp(wakeup_time).strftime('%H:%M:%S')}...")                                  
                            while time.time() < wakeup_time:
                                if not self.is_running: break
                                time.sleep(0.5)

                            if self.is_running:
                                self.state_mgr.update_next_wake_up(0.0)
                            continue

                        try:
                            page.goto(self.current_working_url, timeout=60000)
                        except Exception as e:
                            self.log(f"网络由于系统休眠或其他原因断开或挂起: {e}。等待网络重连...")
                            time.sleep(10)
                            continue
                            
                        time.sleep(3)
                        self.log(f"\n[{completed+1}/{target if not is_retro_check else '补漏'}] 审查题目: {self.current_working_url}")                                                  
                        
                        try:
                            code_content = page.locator(".ace_text-layer").inner_text(timeout=2000).strip()                                                                                                                   
                            if len(code_content) > 10:
                                if self.actions.check_is_already_ac(page):
                                    self.log("✔️ 该题已AC通过，跳过！")
                                    self.current_working_url = self.decrement_url(self.current_working_url) if is_retro_check else self.increment_url(self.current_working_url)                                                       
                                    continue
                                else:
                                    self.log("⚠️ 该题曾提交但未AC，开始解决！")
                        except Exception: 
                            pass
                        
                        problem_text = self.actions.extract_problem_text(page)
                        if not problem_text:
                            self.log("提取题目失败找下一题...")
                            self.current_working_url = self.decrement_url(self.current_working_url) if is_retro_check else self.increment_url(self.current_working_url)                                                       
                            continue
                            
                        # process difficulty and code generation..
                        problem_len = len(problem_text)
                        r_ratio = float(self.cfg.get("read_ratio", "0.1").strip() or "0.1")        
                        w_ratio = float(self.cfg.get("write_ratio", "0.2").strip() or "0.2")

                        # Fetch diff_dict
                        diff_dict = {}
                        if problem_len < 100:
                            diff_dict = {
                                "难度": "简单",
                                "知识点": "基础运算",
                                "题型": "选择题",
                                "时间限制": "无",
                                "空间限制": "无",
                                "输入样例": "无",
                                "输出样例": "无",
                                "备注": "无"
                            }
                        elif problem_len < 500:
                            diff_dict = {
                                "难度": "中等",
                                "知识点": "数据结构与算法",
                                "题型": "编程题",
                                "时间限制": "1秒",
                                "空间限制": "256MB",
                                "输入样例": "1 2 3",
                                "输出样例": "6",
                                "备注": "无"
                            }
                        else:
                            diff_dict = {
                                "难度": "困难",
                                "知识点": "高级数据结构与算法",
                                "题型": "编程题",
                                "时间限制": "2秒",
                                "空间限制": "512MB",
                                "输入样例": "10 20 30 40 50",
                                "输出样例": "150",
                                "备注": "无"
                            }

                        read_offset = int(problem_len * r_ratio)
                        self.sim_sleep(self.cfg.get("read_delay", "5-30"), 5, 30, "阅读题目", read_offset, is_debug)                                                                                 
                        if not self.is_running: break

                        quality = self.cfg.get("quality", "大一萌新 (偶尔求助AI)")
                        
                        try:
                            # 覆盖代码的错误边界阈值读取
                            bound_easy = int(self.cfg.get("easy_bound", "500"))
                            bound_mid = int(self.cfg.get("mid_bound", "1200"))
                        except:
                            bound_easy, bound_mid = 500, 1200
                            

                        bug_prompt = ""
                        if problem_len < bound_easy:
                            bug_prompt = "基础题，不准留Bug，必须一次AC。"
                        elif problem_len < bound_mid:
                            bug_prompt = "中等题，【故意留1到2个隐秘极值错误】，但【必须绝对通过样例输入输出】。"
                        else:
                            bug_prompt = "难题，【必须故意写逻辑明显的越界、无特判错误】，但【绝对要求通过样例输入测试】。"
                            

                        custom_prompt = self.cfg.get("custom_prompt", "").strip()
                        custom_addon = f"附加要求：{custom_prompt}。" if custom_prompt else ""
                        
                        # Generate prompt for AI
                        prompt = f"请根据以下信息生成高质量的算法题代码：\n难度：{diff_dict['难度']}\n知识点：{diff_dict['知识点']}\n题型：{diff_dict['题型']}\n时间限制：{diff_dict['时间限制']}\n空间限制：{diff_dict['空间限制']}\n输入样例：{diff_dict['输入样例']}\n输出样例：{diff_dict['输出样例']}\n备注：{diff_dict['备注']}\n\n题目描述：{problem_text}\n\n请输出代码："                                      
                        self.log("获取初版代码...")
                        generated_code = llm.ask([
                            {"role": "system", "content": f"扮演一名{quality}正在刷算法题。不要注释，变量名单一，极低质量代码规则：{bug_prompt} {custom_addon} 完全纯净输出C++实体，无markdown。"},                                                   {"role": "user", "content": prompt}
                        ], self.log)
                        if not generated_code: continue

                        write_offset = int(len(generated_code) * w_ratio)
                        self.sim_sleep(self.cfg.get("write_delay", "10-120"), 10, 120, f"编写代码延迟", write_offset, is_debug)                               
                        if not self.is_running: break

                        self.actions.inject_and_submit(page, generated_code)      
                        
                        try:
                            # 等待判题设置读取
                            wait_judge_min, wait_judge_max = self.get_rand_range(self.cfg.get("wait_judge", "10-15"), 10, 15)
                        except:
                            wait_judge_min, wait_judge_max = 10, 15

                        self.sim_sleep(self.cfg.get("wait_judge", "10-15"), wait_judge_min, wait_judge_max, "等待系统开始判题", 0, is_debug)                                                                     
                        is_ac = self.actions.wait_for_judgment_result(page)       

                        if not is_ac:
                            self.log("❌ 发生 Wrong Answer / 语法错误...")    
                            m_min, m_max = self.get_rand_range(self.cfg.get("max_retries", "3-8"), 3, 8)                                                                                                                            
                            base_retries = random.randint(m_min, m_max)
                            perturbation = random.uniform(0.9, 1.1) ** random.uniform(1.2, 1.8)  
                            max_retries = int(base_retries * perturbation)
                            max_retries = max(1, max_retries) 
                            retry_count = 0

                            try:
                                wa_shock_min, wa_shock_max = self.get_rand_range(self.cfg.get("wa_shock", "15-60"), 15, 60)
                            except: wa_shock_min, wa_shock_max = 15, 60
                            self.sim_sleep(self.cfg.get("wa_shock", "15-60"), wa_shock_min, wa_shock_max, "震惊并检查报错", 0, is_debug)                                                                                             
                            while not is_ac and retry_count < max_retries and self.is_running:   
                                retry_count += 1
                                if retry_count > 3:
                                    try: 
                                        fast_min, fast_max = self.get_rand_range(self.cfg.get("retry_fast", "5-15"), 5, 15)
                                    except: fast_min, fast_max = 5, 15
                                    self.sim_sleep(self.cfg.get("retry_fast", "5-15"), fast_min, fast_max, f"第{retry_count}次急躁修改", 0, is_debug)                                                                                                                               
                                else:
                                    try: 
                                        slow_min, slow_max = self.get_rand_range(self.cfg.get("retry_slow", "10-40"), 10, 40)
                                    except: slow_min, slow_max = 10, 40
                                    self.sim_sleep(self.cfg.get("retry_slow", "10-40"), slow_min, slow_max, f"第{retry_count}次思考修改bug", 0, is_debug)                                                                                         
                                messages = [
                                    {"role": "system", "content": f"扮演一名{quality}正在刷算法题。不要注释，变量名单一，极低质量代码规则：{bug_prompt} {custom_addon} 完全纯净输出C++实体，无markdown。"}, 
                                    {"role": "user", "content": prompt},
                                    {"role": "assistant", "content": generated_code},
                                    {"role": "user", "content": f"第{retry_count}次提交依然没过。只修一个你认为最明显的bug！不要一次性修完！保持代码风格恶劣无注释过样例。"}
                                ]    
                                generated_code = llm.ask(messages, self.log)
                                if not self.is_running or not generated_code: break

                                self.actions.inject_and_submit(page, generated_code)
                                self.sim_sleep(self.cfg.get("wait_judge", "10-15"), wait_judge_min, wait_judge_max, "重试提交后等待系统开始判题", 0, is_debug)                                                                                                                         
                                is_ac = self.actions.wait_for_judgment_result(page)

                            if not is_ac: self.log(f"😭 连续{retry_count}次WA，破防弃题！")                                                                                                                     
                            else: self.log(f"✔️ 第{retry_count}次重试通过。")      
                        else:
                            self.log("✔️ 首发 Accepted 通过！")

                        if not is_retro_check or is_ac:
                            completed += 1
                            self.state_mgr.update_completed(completed)
                            if self.event_callback:
                                self.event_callback("completed_update", completed, target)

                        self.current_working_url = self.decrement_url(self.current_working_url) if is_retro_check else self.increment_url(self.current_working_url)
                        
                        if not is_retro_check:
                            try:
                                new_start_id = self.current_working_url.rstrip("/").split("/")[-1]
                                self.cfg["start_id"] = new_start_id
                                self.cfg_mgr.save_config(self.cfg)
                                self.log(f"📝 记录下一题起始题号: {new_start_id}")
                                if self.event_callback:
                                    self.event_callback("start_id_update", new_start_id, None)
                            except Exception as e:
                                self.log(f"无法保存下一题题号: {e}")

                        self.sim_sleep(self.cfg.get("ac_rest", "30-300"), 30, 300, f"做题完成休眠", 0, is_debug)                           

                except Exception as e:
                    self.log(f"核心循环报错终止: {e}")
                finally:
                    context.close()
                    browser.close()
        except Exception as e:
            self.log(f"外层循环报错终止: {e}")

        self.is_running = False
        if self.event_callback:
            self.event_callback("stopped", None, None)

    def stop(self):
        self.is_running = False
