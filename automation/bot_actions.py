from playwright.sync_api import Page
import time
import re

class BotActions:
    def __init__(self, log_callback=None):
        self.log_callback = log_callback

    def log(self, msg):
        if self.log_callback:
            self.log_callback(msg)

    def inject_and_submit(self, page: Page, code: str):
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
                with page.expect_response("**/submit**", timeout=5000):
                    try:
                        submit_btn.first.click()
                    except Exception:
                        pass
            else:
                page.keyboard.press(f"{modifier}+Enter")
            time.sleep(2)
        except Exception as e:
            self.log(f"注入或提交操作元素未就绪或未捕获到响应: {e}")

    def wait_for_judgment_result(self, page: Page):
        max_wait = 20 
        for _ in range(max_wait):
            try:
                status_span = page.locator(".ui.header.status-span, .status").first
                if status_span.count() > 0:
                    status_text = status_span.inner_text().lower()
                    if "queue" in status_text or "judging" in status_text or "compiling" in status_text:
                        self.log("程序仍在排队或判题中，等待...")
                        time.sleep(2)
                        continue

                    classes = status_span.evaluate("el => el.className").lower()
                    if "green" in classes or "accepted" in status_text:
                        return True
                    if "red" in classes or "grey" in status_text:
                        return False
            except Exception:
                pass

            try:
                ac_element = page.locator(".ui.green.message, .status.accepted, td:has-text('Accepted')").first                                                                                                   
                is_ac = ac_element.count() > 0 or ("accepted" in page.locator(".ui.message").inner_text().lower())                                                                                                
                if is_ac:
                    return True
            except Exception:
                page_text = page.inner_text("body").lower()
                if ("accepted" in page_text) or ("答案正确" in page_text):
                    return True
            time.sleep(2)

        return False

    def check_is_already_ac(self, page: Page):
        try:
            status_span = page.locator(".ui.header.status-span, .status").first                                                                                                                               
            if status_span.count() > 0:
                classes = status_span.evaluate("el => el.className").lower()                                                                                                                                      
                status_text = status_span.inner_text().lower()
                if "green" in classes or "accepted" in status_text:      
                    return True
                elif "red" in classes or "grey" in status_text:
                    return False

            ac_element = page.locator(".ui.green.message, .status.accepted, td:has-text('Accepted')").first                                                                                                   
            if ac_element.count() > 0 or ("accepted" in page.locator(".ui.message").inner_text().lower()):                                                                                                        
                return True
        except Exception:
            pass
        return False

    def extract_problem_text(self, page: Page):
        try:
            return page.locator(".twelve.wide.column").inner_text(timeout=5000).strip()
        except Exception:
            return None
