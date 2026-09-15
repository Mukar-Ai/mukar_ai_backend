import os
from pathlib import Path
from dotenv import load_dotenv


# Charger le fichier .env
env_path = Path('.') / '.env'
load_dotenv(dotenv_path=env_path)


class LLM:
    models = {
            "google": {
                "model": os.getenv('GEMINI_MODEL'),
                "api_key": os.getenv('GEMINI_API_KEY')
            },
            "openAi": {
                "model": "",
                "api_key": ""
            }
        }

    def get_api_key(self, institution='google') -> str:
        return self.models[institution]['api_key']

    def get_model_name(self, institution='google') -> str:
        return self.models[institution]['model']


MAX_RETRIES = 3

POLL_INTERVAL_SECONDS = 1.0

POLL_TIMEOUT_SECONDS = 60.0

BASE_DIR = Path(__file__).resolve().parents[2]

INITIAL_PROMPT_PATH = BASE_DIR / "datas" / "predefined" / "initial_prompt.txt"

UPDATE_PROMPT_PATH = BASE_DIR / "datas" / "predefined" / "update_prompt.txt"

SYSTEM_INSTRUCTIONS_PATH = BASE_DIR / "datas" / "predefined" / "interpretation_system_instructions.txt"

DICTIONARY_PATH = BASE_DIR / "datas" / "predefined" / "data_dictionary.txt"

SCHEMA_PATH = BASE_DIR / "datas" / "predefined" / "analysis_input_schema.txt"

CLIENT_INFO_PATH = BASE_DIR / "datas" / "uploaded"

UPLOAD_DIR = BASE_DIR / "datas" / "uploaded"

llm = LLM()
