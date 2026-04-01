import google.generativeai as genai
import json
from config import settings

class LLMEngine:
    def __init__(self):
        genai.configure(api_key=settings.GEMINI_API_KEY)
        self.model = genai.GenerativeModel('gemini-pro')
        self.system_prompt = """
        Ты - ассистент тайм-менеджмента. Верни ответ строго в JSON:
        {"intent": "create_event"|"create_task", "title": "...", "date": "...", "time": "..."}
        """

    async def analyze_text(self, text: str) -> dict:
        try:
            prompt = f"{self.system_prompt}\nUser message: {text}"
            response = await self.model.generate_content_async(prompt)
            clean_json = response.text.replace('```json', '').replace('```', '')
            return json.loads(clean_json)
        except Exception as e:
            print(f"LLM Error: {e}")
            return None
