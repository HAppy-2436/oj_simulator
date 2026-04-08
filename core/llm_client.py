import requests
import json

class LLMClient:
    def __init__(self, api_key, model_name, api_base="https://api.deepseek.com"):
        self.api_key = api_key
        self.model_name = model_name
        self.api_base = api_base
        self.headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }

    def update_config(self, api_key, model_name, api_base="https://api.deepseek.com"):
        self.api_key = api_key
        self.model_name = model_name
        self.api_base = api_base
        self.headers["Authorization"] = f"Bearer {self.api_key}"

    def ask(self, messages, log_callback=None):
        if log_callback:
            log_callback(f"[LLM] Prepared request payload length: {len(str(messages))}")
            
        # Support both raw string prompt or pre-formatted messages array
        formatted_messages = messages if isinstance(messages, list) else [{"role": "user", "content": messages}]
        
        payload = {
            "model": self.model_name,
            "messages": formatted_messages,
            "temperature": 0.8
        }
        
        url = self.api_base
        if not url.endswith("/chat/completions"):
            url = url.rstrip('/') + "/chat/completions"

        try:
            resp = requests.post(url, headers=self.headers, json=payload, timeout=60)
            resp.raise_for_status()
            result = resp.json()
            reply = result["choices"][0]["message"]["content"]
            
            if log_callback:
                log_callback(f"[LLM Response] Tokens used: {result.get('usage', {}).get('total_tokens', '?')} Tokens.")
            
            return reply
        except Exception as e:
            if log_callback:
                log_callback(f"[LLM Error] API requesting error: {str(e)}")
            return None
