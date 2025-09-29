import os
from dotenv import load_dotenv

# comment the below line in production
# load_dotenv()

TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')

OAUTH_FILE = os.getenv('OAUTH_FILE')
SHEET_ID = os.getenv('SHEET_ID')
DRIVE_FOLDER_ID = os.getenv('DRIVE_FOLDER_ID')

UNIVERSAL_KEY = os.getenv('UNIVERSAL_KEY')
SESSION_TTL_SECONDS = int(os.getenv('SESSION_TTL_SECONDS', 1800))
HTTPS_COOKIES = int(os.getenv('HTTPS_COOKIES', 0))
REDIS_URL = os.getenv('REDIS_URL', 'redis://127.0.0.1:6379/0')
API_RATE_LIMIT = int(os.getenv('API_RATE_LIMIT', 8))

# to start the redis-server in the background, run `sudo systemctl start redis-server` and then `sudo systemctl enable redis-server`
