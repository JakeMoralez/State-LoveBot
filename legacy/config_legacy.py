# config.py
import os
from dotenv import load_dotenv

load_dotenv()

# ВК
VK_GROUP_ID = int(os.getenv('VK_GROUP_ID'))

VK_GROUP_TOKEN = os.getenv('VK_GROUP_TOKEN')
VK_USER_TOKEN = os.getenv('VK_USER_TOKEN')

# Форум
FORUM_USER_AGENT = os.getenv('FORUM_USER_AGENT')
FORUM_COOKIES = {
    'xf_user': os.getenv('FORUM_XF_USER'),
    'xf_session': os.getenv('FORUM_XF_SESSION'),
    'xf_tfa_trust': os.getenv('FORUM_XF_TFA_TRUST')
}

# Главный администратор (твой ID и username ВК)
MAIN_ADMIN_ID = int(os.getenv('MAIN_ADMIN_ID', 0))
MAIN_ADMIN_USERNAME = os.getenv('MAIN_ADMIN_USERNAME', '')

# Беседа для логов
LOG_CHAT_ID = int(os.getenv('LOG_CHAT_ID', 0))

# Беседа следящих правика
# ADMIN_CHAT_ID = int(os.getenv('ADMIN_CHAT_ID', 0))

# Беседа судей
# JUDGE_CHAT_ID = int(os.getenv('JUDGE_CHAT_ID', 0))

# Беседа передачи постановлений
# MJ_CHAT_ID = int(os.getenv('MJ_CHAT_ID', 0))

# Дела атторнеев
ATTORNEY_FORUM_ID = 3287  # ID раздела для атторнеев

# Разделы МЮ
LEADER_ALLOWED_FORUMS = [2935, 2936, 2937, 2938, 2939, 2940, 2941, 2942, 2943, 2944, 2945] 

TECH_CHAT_ID = 2000000007  # беседа техов

# ID бесед для автоматического снятия ролей (заполняются через команды)
LEADER_CHAT_ID = None
JUDGE_CHAT_ID = None
ATTORNEY_CHAT_ID = None
ADMIN_CHAT_ID = None

MOVE_THREAD_CATEGORIES = [
    {"id": 2908, "name": "Гос.структуры"},
    {"id": 2926, "name": "Government || Правительство"},
    {"id": 2927, "name": "Правительство(фракция)"},
    {"id": 3173, "name": "Сенат"},
    {"id": 2928, "name": "Кабинет губернатора"},
    {"id": 2929, "name": "Политические партии"},
    {"id": 2930, "name": "Законодательная база"},
    {"id": 2931, "name": "Офис Генерального прокурора"},
    {"id": 3286, "name": "Адвокатская Коллегия"},
    {"id": 2932, "name": "Ministry of Social Services || Мин. Соц. Служб"},
    {"id": 2934, "name": "Licensing Center"},
    {"id": 3204, "name": "Radiocentre Los-Santos"},
    {"id": 2946, "name": "Medical Centers"},
    {"id": 2947, "name": "Los-Santos Medical Center"},
    {"id": 2948, "name": "Las-Venturas Medical Center"},
    {"id": 3658, "name": "Пожарный департамент"},
    {"id": 2935, "name": "Ministry of Justice || Мин. Юстиции "},
    {"id": 2936, "name": "Federal Bureau of Investigation"},
    {"id": 2942, "name": "Los-Santos Police Department"},
    {"id": 2943, "name": "San-Fierro Police Department"},
    {"id": 2944, "name": "Special Weapons And Tactics"},
    {"id": 2945, "name": "Red Country Sheriff Department"},
    {"id": 2984, "name": "Ministry of Defence || Мин. Обороны"},
    {"id": 2985, "name": "Los-Santos Army"},
    {"id": 2986, "name": "San-Fierro Army"},
    {"id": 2987, "name": "Federal Prison Las-Venturas"},
    {"id": 3419, "name": "Судебные иски"},
    {"id": 2288, "name": "Корзина"},
    {"id": 2977, "name": "Админ раздел"},
]


