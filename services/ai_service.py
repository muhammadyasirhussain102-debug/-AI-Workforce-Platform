import os
import json
import urllib.request

def load_env_key(key_name: str) -> str:
    val = os.getenv(key_name, "")
    if val and "PASTE_" not in val:
        return val
    if os.path.exists(".env"):
        with open(".env", "r", encoding="utf-8") as f:
            for line in f:
                if line.strip().startswith(key_name + "="):
                    v = line.strip().split("=", 1)[1].strip()
                    if "PASTE_" not in v:
                        return v
    return ""

def call_groq_llama(system_prompt: str, user_message: str, api_key: str = "") -> str:
    key = api_key or load_env_key("GROQ_API_KEY")
    if not key:
        raise ValueError("Groq API key not configured")
    url = "https://api.groq.com/openai/v1/chat/completions"
    payload = {
        "model": "llama-3.3-70b-versatile",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message}
        ],
        "temperature": 0.2
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}",
            "User-Agent": "EnterpriseWorkforceOS/1.0"
        }
    )
    with urllib.request.urlopen(req, timeout=10) as res:
        data = json.loads(res.read().decode("utf-8"))
        return data["choices"][0]["message"]["content"]

def call_gemini_flash(system_prompt: str, user_message: str, api_key: str = "") -> str:
    key = api_key or load_env_key("GEMINI_API_KEY")
    if not key:
        raise ValueError("Gemini API key not configured")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={key}"
    payload = {
        "contents": [{"parts": [{"text": f"{system_prompt}\n\nUser Input: {user_message}"}]}],
        "generationConfig": {"temperature": 0.2}
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=10) as res:
        data = json.loads(res.read().decode("utf-8"))
        return data["candidates"][0]["content"]["parts"][0]["text"]