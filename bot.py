import asyncio
import logging
import sqlite3
import aiohttp
import json
import random
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import string
from aiogram import Bot, Dispatcher, types, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (InlineKeyboardMarkup, InlineKeyboardButton,
                           ReplyKeyboardMarkup, KeyboardButton, LabeledPrice,
                           PreCheckoutQuery)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from flyerapi import Flyer

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)



BOT_TOKEN = "8549867531:AAF77BOw-35G3cUG9k65joK1gnyUgUpGgHg"
ADMIN_IDS = [8478884644]
CRYPTOBOT_TOKEN = "458446:AAwxMGcTu3IzA54r8frx2Fg4WS18epuZ9Et"
FLYER_TOKEN = "FL-qIbttb-BkoELi-ImdtUe-KkAjoX"
flyer = Flyer(FLYER_TOKEN)

API_SERVICES = {
    "vexboost": {
        "api_key": "kSNAYl7ZKZts2m09m7KkxBq1N5cEZvaqhpyQBTQHU67VeGswoNRjdiTrBnpK",
        "url": "https://vexboost.ru/api/v2",
    }
}

CRYPTO_PRICES = {
    'points': {1500: 1.5, 7500: 7.5, 15000: 15, 38000: 38},
    'elite': 25
}

PRICES = {
    'telegram_members': 21, 'telegram_reactions': 8, 'telegram_views': 1.5,
    'vk_post_views': 1.5, 'vk_video_views': 16.5, 'vk_likes': 215,
    'tiktok_views': 3, 'tiktok_likes': 30, 'instagram_likes': 190,
    'instagram_views': 2.5, 'youtube_subscribers': 150, 'youtube_likes': 55,
    'youtube_views': 450, 'telegram_members_elite': 300
}

DEFAULT_REQUIRED_TASKS = [
    {"name": "Основной канал", "username": "@boostyprojectchannel", "reward": 500},
    {"name": "Новостной канал", "username": "@nakrutkaeverydaynews", "reward": 500}
]

TITLES = {
    'Новичок': {'threshold': 0, 'reward': 0}, 'Бывалый': {'threshold': 10000, 'reward': 1000},
    'Опытный': {'threshold': 50000, 'reward': 5000}, 'Мастер': {'threshold': 100000, 'reward': 10000},
    'Легенда': {'threshold': 250000, 'reward': 25000}, 'Властелин Раскрутки': {'threshold': 500000, 'reward': 50000}
}

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
dildo = Router()

class Database:
    def __init__(self, db_file='bot.db'):
        self.conn = sqlite3.connect(db_file, check_same_thread=False)
        # ИСПРАВЛЕНИЕ: Включаем WAL режим для лучшей конкурентности
        self.conn.execute('PRAGMA journal_mode=WAL')
        self.create_tables()
        self.migrate_tables()

    def create_tables(self):
        cursor = self.conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY, username TEXT, balance INTEGER DEFAULT 0, referrals INTEGER DEFAULT 0,
                registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, referred_by INTEGER DEFAULT NULL,
                last_bonus_claim TIMESTAMP, total_spent INTEGER DEFAULT 0, title TEXT DEFAULT 'Новичок',
                has_elite_sub INTEGER DEFAULT 0, elite_sub_expires TIMESTAMP,
                referral_reward_claimed INTEGER DEFAULT 0
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS crypto_invoices (
                invoice_id TEXT PRIMARY KEY,
                user_id INTEGER,
                points INTEGER DEFAULT 0,
                elite INTEGER DEFAULT 0,
                status TEXT DEFAULT "pending"
            )
        ''')
        cursor.execute(
            'CREATE TABLE IF NOT EXISTS tasks (task_id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, task_type TEXT, social_network TEXT, target_url TEXT, count INTEGER, price INTEGER, api_order_id TEXT, status TEXT DEFAULT "active", created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)')
        cursor.execute(
            'CREATE TABLE IF NOT EXISTS promocodes (code TEXT PRIMARY KEY, reward INTEGER, max_uses INTEGER DEFAULT 1, current_uses INTEGER DEFAULT 0, is_active INTEGER DEFAULT 1)')
        cursor.execute(
            'CREATE TABLE IF NOT EXISTS promocode_usage (user_id INTEGER, code TEXT, used_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY (user_id, code))')
        cursor.execute(
            'CREATE TABLE IF NOT EXISTS required_tasks (user_id INTEGER, channel_username TEXT, PRIMARY KEY (user_id, channel_username))')
        cursor.execute(
            'CREATE TABLE IF NOT EXISTS required_channels (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, username TEXT NOT NULL UNIQUE, reward INTEGER NOT NULL)')
        cursor.execute(
            'CREATE TABLE IF NOT EXISTS user_title_rewards (user_id INTEGER, title TEXT, PRIMARY KEY (user_id, title))')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS purchases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                purchase_type TEXT,
                amount INTEGER,
                points_or_elite INTEGER,
                purchased_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        # ИСПРАВЛЕНИЕ: Новая таблица для отслеживания обработки кб
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS callback_locks (
                user_id INTEGER,
                callback_data TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (user_id, callback_data)
            )
        ''')
        self.conn.commit()

    def migrate_tables(self):
        cursor = self.conn.cursor()
        cursor.execute("PRAGMA table_info(users)")
        columns = [c[1] for c in cursor.fetchall()]
        if 'last_bonus_claim' not in columns: cursor.execute("ALTER TABLE users ADD COLUMN last_bonus_claim TIMESTAMP")
        if 'total_spent' not in columns: cursor.execute("ALTER TABLE users ADD COLUMN total_spent INTEGER DEFAULT 0")
        if 'title' not in columns: cursor.execute("ALTER TABLE users ADD COLUMN title TEXT DEFAULT 'Новичок'")
        if 'has_elite_sub' not in columns: cursor.execute(
            "ALTER TABLE users ADD COLUMN has_elite_sub INTEGER DEFAULT 0")
        if 'elite_sub_expires' not in columns: cursor.execute(
            "ALTER TABLE users ADD COLUMN elite_sub_expires TIMESTAMP")
        # ИСПРАВЛЕНИЕ: флаг для отслеживания выплаты реферального бонуса
        if 'referral_reward_claimed' not in columns:
            cursor.execute("ALTER TABLE users ADD COLUMN referral_reward_claimed INTEGER DEFAULT 0")
        
        cursor.execute("PRAGMA table_info(promocode_usage)")
        pu_columns = [c[1] for c in cursor.fetchall()]
        if 'used_at' not in pu_columns:
            cursor.execute("ALTER TABLE promocode_usage ADD COLUMN used_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
        self.conn.commit()
    
    # ИСПРАВЛЕНИЕ: Метод для безопасной транзакции
    def execute_transaction(self, func):
        cursor = self.conn.cursor()
        try:
            cursor.execute('BEGIN IMMEDIATE')
            result = func(cursor)
            self.conn.commit()
            return result
        except Exception as e:
            self.conn.rollback()
            logger.error(f"Transaction error: {e}")
            raise


db = Database()



class BoostAPI:
    def __init__(self):
        self.session = None
        self.services_cache: Dict[str, List[Dict]] = {}

    async def create_session(self):
        if not self.session: self.session = aiohttp.ClientSession()

    async def close_session(self):
        if self.session: await self.session.close()

    async def _api_post(self, data: Dict) -> Dict:
        try:
            await self.create_session()
            async with self.session.post(API_SERVICES["vexboost"]["url"], data=data) as response:
                text = await response.text()
                try:
                    return json.loads(text)
                except json.JSONDecodeError:
                    logger.error(f"JSON decode error: {text[:500]}"); return {"error": "Invalid API response"}
        except Exception as e:
            logger.error(f"API post error: {e}"); return {"error": str(e)}

    async def get_services(self) -> List[Dict]:
        if "services" not in self.services_cache:
            result = await self._api_post({"key": API_SERVICES["vexboost"]["api_key"], "action": "services"})
            if "error" in result: raise ValueError(result["error"])
            self.services_cache["services"] = result
        return self.services_cache["services"]

    async def find_service_by_name(self, service_name: str) -> Optional[Dict]:
        services = await self.get_services()
        service_name_lower = service_name.lower()
        matching_services = []
        social_network = service_name_lower.split('_')[0]
        task_type = '_'.join(service_name_lower.split('_')[1:])

        for s in services:
            name = s.get("name", "").lower()
            rate = float(s.get("rate", 999999))
            is_correct_network = False

            if social_network == "telegram" and ("telegram" in name or "телеграм" in name or "tg" in name):
                is_correct_network = True
            elif social_network == "vk" and ("vk" in name or "вк" in name or "вконтакте" in name):
                is_correct_network = True
            elif social_network == "tiktok" and ("tiktok" in name or "тикток" in name):
                is_correct_network = True
            elif social_network == "instagram" and ("instagram" in name or "инстаграм" in name or "inst" in name):
                is_correct_network = True
            elif social_network == "youtube" and ("youtube" in name or "ютуб" in name or "yt" in name):
                is_correct_network = True

            if is_correct_network:
                if task_type == "members" and ("members" in name or "участник" in name or "подписчик" in name):
                    matching_services.append((s, rate))
                elif task_type == "reactions" and ("реакции поз" in name or "reaction" in name):
                    matching_services.append((s, rate))
                elif task_type == "likes" and ("like" in name or "лайк" in name):
                    matching_services.append((s, rate))
                elif task_type == "views" and ("views" in name or "просмотр" in name):
                    matching_services.append((s, rate))
                elif task_type == "post_views" and ("пост" in name or "post" in name) and (
                        "просмотр" in name or "views" in name):
                    matching_services.append((s, rate))
                elif task_type == "video_views" and ("видео" in name or "video" in name) and (
                        "просмотр" in name or "views" in name):
                    matching_services.append((s, rate))
                elif task_type == "likes" and ("лайки" in name or "likes" in name):
                    matching_services.append((s, rate))
                elif task_type == "subscribers" and ("subscribers" in name or "подписчик" in name):
                    matching_services.append((s, rate))

        if matching_services:
            cheapest = min(matching_services, key=lambda x: x[1])
            return cheapest[0]
        return None

    async def find_elite_service(self) -> Optional[Dict]:
        services = await self.get_services()
        matching_services = []
        for s in services:
            name, rate = s.get("name", "").lower(), float(s.get("rate", 999999))
            is_tg_subs = ("telegram" in name or "тг" in name) and ("подписчики","без списаний" in name or "members" in name)
            has_guarantee = any(kw in name for kw in ["без списаний"])
            is_correct_rate = 46 < rate < 50
            if is_tg_subs and has_guarantee and is_correct_rate:
                matching_services.append((s, rate))
        return min(matching_services, key=lambda x: x[1])[0] if matching_services else None

    async def create_order(self, s_id: str, target: str, qty: int):
        return await self._api_post(
            {'key': API_SERVICES['vexboost']['api_key'], 'action': 'add', 'service': s_id, 'link': target,
             'quantity': qty})

    async def get_balance(self):
        result = await self._api_post({'key': API_SERVICES['vexboost']['api_key'], 'action': 'balance'}); return float(
            result.get('balance', 0)) if "error" not in result else 0.0

    async def get_order_status(self, o_id: str):
        return await self._api_post({"key": API_SERVICES["vexboost"]["api_key"], "action": "status", "order": o_id})


boost_api = BoostAPI()


async def create_crypto_invoice(user_id: int, amount_rub: float, points: int = 0, is_elite: bool = False) -> dict:
    url = "https://pay.crypt.bot/api/createInvoice"
    payload = f"crypto_{'elite' if is_elite else 'points'}_{user_id}"
    
    headers = {
        "Content-Type": "application/json", 
        "Crypto-Pay-API-Token": CRYPTOBOT_TOKEN
    }
    
    data = {
        "asset": "USDT",
        "amount": str(amount_rub / 100),
        "description": f"{'Пополнение баланса на ' + str(points) + ' баллов' if points else 'Покупка Elite подписки (30 дней)'}",
        "payload": payload
    }
    
    await boost_api.create_session()
    try:
        async with boost_api.session.post(url, json=data, headers=headers) as response:
            raw_response = await response.text()
            
            if response.status != 200:
                logger.error(f"CryptoBot error {response.status}: {raw_response}")
                return {}
            
            result = await response.json()
            
            if result.get('ok') and result.get('result'):
                invoice_data = result['result']
                cursor = db.conn.cursor()
                cursor.execute(
                    'INSERT INTO crypto_invoices (invoice_id, user_id, points, elite) VALUES (?, ?, ?, ?)',
                    (invoice_data['invoice_id'], user_id, points, 1 if is_elite else 0)
                )
                db.conn.commit()
                return invoice_data
            else:
                logger.error(f"API error: {result.get('error', {}).get('name', 'Unknown')}: {result.get('error', {}).get('code', '')}")
                return {}
    except Exception as e:
        logger.error(f"Failed to create crypto invoice: {e}")
        return {}


async def check_crypto_invoices():
    while True:
        await asyncio.sleep(60)
        cursor = db.conn.cursor()
        cursor.execute("SELECT invoice_id, user_id, points, elite FROM crypto_invoices WHERE status = 'pending'")
        invoices = cursor.fetchall()
        if not invoices:
            continue
            
        headers = {
            "Crypto-Pay-API-Token": CRYPTOBOT_TOKEN
        }
        
        for invoice_id, user_id, points, is_elite in invoices:
            url = f"https://pay.crypt.bot/api/getInvoices" 
            params = {"invoice_ids": invoice_id}
            
            await boost_api.create_session()
            try:
                async with boost_api.session.get(url, headers=headers, params=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        if data.get('ok') and data.get('result'):
                            for inv in data['result']['items']:
                                if inv['status'] == 'paid':
                                    cursor.execute("UPDATE crypto_invoices SET status = 'paid' WHERE invoice_id = ?", (invoice_id,))
                                    
                                    if is_elite:
                                        expires_at = datetime.now() + timedelta(days=30)
                                        cursor.execute('UPDATE users SET has_elite_sub = 1, elite_sub_expires = ? WHERE user_id = ?',
                                                     (expires_at.isoformat(), user_id))
                                        cursor.execute('INSERT INTO purchases (user_id, purchase_type, amount, points_or_elite) VALUES (?, ?, ?, ?)',
                                                       (user_id, 'crypto_elite', CRYPTO_PRICES['elite'], 1))
                                        try:
                                            await bot.send_message(user_id, f"✅ **Elite подписка успешно активирована крипто-оплатой!**\nСрок действия: до {expires_at.strftime('%d.%m.%Y')}")
                                        except:
                                            pass
                                    else:
                                        cursor.execute('UPDATE users SET balance = balance + ? WHERE user_id = ?', (points, user_id))
                                        cursor.execute('INSERT INTO purchases (user_id, purchase_type, amount, points_or_elite) VALUES (?, ?, ?, ?)',
                                                       (user_id, 'crypto_points', CRYPTO_PRICES['points'][points], points))
                                        try:
                                            await bot.send_message(user_id, f"✅ Успешно! На ваш баланс зачислено {points} баллов через крипто-оплату!")
                                        except:
                                            pass
                                    
                                    db.conn.commit()
                    else:
                        logger.error(f"Error checking invoice {invoice_id}: status {response.status}")
            except Exception as e:
                logger.error(f"Exception checking invoice {invoice_id}: {e}")


class Form(StatesGroup):
    waiting_for_social = State();
    waiting_for_task_count = State();
    waiting_for_target_url = State()
    waiting_for_promo_code = State();
    waiting_for_admin_user_id = State();
    waiting_for_admin_amount = State()
    waiting_for_channel_name = State();
    waiting_for_channel_username = State();
    waiting_for_channel_reward = State()
    waiting_for_channel_delete = State();
    waiting_for_bet = State();
    waiting_for_recipient_id = State()
    waiting_for_transfer_amount = State();
    waiting_for_subscriber_mode = State()
    waiting_for_admin_user_info_id = State()

class UserState(StatesGroup):
	captcha = State()
	main_menu = State()

def load_channels_from_db():
    cursor = db.conn.cursor()
    cursor.execute('SELECT name, username, reward FROM required_channels')
    channels = cursor.fetchall()
    if channels: return [{"name": n, "username": u, "reward": r} for n, u, r in channels]
    cursor.executemany('INSERT OR IGNORE INTO required_channels (name, username, reward) VALUES (?, ?, ?)',
                       [(ch['name'], ch['username'], ch['reward']) for ch in DEFAULT_REQUIRED_TASKS]);
    db.conn.commit();
    return DEFAULT_REQUIRED_TASKS


async def update_user_title(user_id: int, price: int):
    cursor = db.conn.cursor()
    cursor.execute('UPDATE users SET total_spent = total_spent + ? WHERE user_id = ?', (price, user_id))
    cursor.execute('SELECT total_spent, title FROM users WHERE user_id = ?', (user_id,));
    total_spent, current_title = cursor.fetchone()
    new_title = current_title
    for title, data in sorted(TITLES.items(), key=lambda i: i[1]['threshold']):
        if total_spent >= data['threshold']: new_title = title
    if new_title != current_title:
        cursor.execute('UPDATE users SET title = ? WHERE user_id = ?', (new_title, user_id));
        db.conn.commit()
        try:
            await bot.send_message(user_id,
                                   f"🎉 Поздравляем! Вы достигли нового титула: **{new_title}**!\n\nПерейдите в '🏆 Рейтинг', чтобы забрать награду в **{TITLES[new_title]['reward']}** баллов!")
        except:
            pass
    else:
        db.conn.commit()


def main_keyboard(user_id=None):
    buttons = [
        [KeyboardButton(text="📊 Профиль"), KeyboardButton(text="➕ Создать задание")],
        [KeyboardButton(text="💰 Пополнить баланс"), KeyboardButton(text="👑 Elite Sub")],
        [KeyboardButton(text="💼 Мои задания"), KeyboardButton(text="🎁 Бонусы")],
        [KeyboardButton(text="⚡ Меню"), KeyboardButton(text="📢 Поддержка")]
    ]
    if user_id in ADMIN_IDS: 
        buttons.append([KeyboardButton(text="🔧 Админ панель")])
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)


def social_keyboard(): return InlineKeyboardMarkup(
    inline_keyboard=[[InlineKeyboardButton(text="📱 Telegram", callback_data="social_telegram")],
                     [InlineKeyboardButton(text="🎭 VK", callback_data="social_vk")],
                     [InlineKeyboardButton(text="🎵 TikTok", callback_data="social_tiktok")],
                     [InlineKeyboardButton(text="📷 Instagram", callback_data="social_instagram")],
                     [InlineKeyboardButton(text="📺 YouTube", callback_data="social_youtube")],
                     [InlineKeyboardButton(text="🔙 Назад в меню", callback_data="back_to_main")]])


def tasks_keyboard(social_prefix, tasks, back_callback="back_to_social"):
    builder = InlineKeyboardBuilder();
    [builder.button(text=text, callback_data=f"task_{social_prefix}_{data}") for text, data in tasks.items()];
    builder.button(text="🔙 Назад", callback_data=back_callback);
    builder.adjust(2);
    return builder.as_markup()


def required_tasks_keyboard():
    builder = InlineKeyboardBuilder();
    [builder.row(InlineKeyboardButton(text=f"📱 {task['name']}", url=f"https://t.me/{task['username'].lstrip('@')}")) for
     task in load_channels_from_db()];
    return builder.as_markup()


def stars_keyboard(): return InlineKeyboardMarkup(
    inline_keyboard=[[InlineKeyboardButton(text="⭐ 1000 баллов (1 ⭐)", callback_data="buy_stars_1")],
                     [InlineKeyboardButton(text="⭐ 5500 баллов (5 ⭐)", callback_data="buy_stars_5")],
                     [InlineKeyboardButton(text="⭐ 12000 баллов (10 ⭐)", callback_data="buy_stars_10")],
                     [InlineKeyboardButton(text="⭐ 30000 баллов (25 ⭐)", callback_data="buy_stars_25")],
                     [InlineKeyboardButton(text="⭐ 65000 баллов (50 ⭐)", callback_data="buy_stars_50")],
                     [InlineKeyboardButton(text="⭐ 105000 баллов (75 ⭐)", callback_data="buy_stars_75")],
                     [InlineKeyboardButton(text="⭐ 140000 баллов (100 ⭐)", callback_data="buy_stars_100")],
                     [InlineKeyboardButton(text="🔙 Назад в меню", callback_data="back_to_hui")]])


def rating_keyboard(): return InlineKeyboardMarkup(
    inline_keyboard=[[InlineKeyboardButton(text="🏆 Топ по рефералам", callback_data="rating_referrals")],
                     [InlineKeyboardButton(text="💰 Топ по тратам", callback_data="rating_spent")],
                     [InlineKeyboardButton(text="👑 Мой титул и награды", callback_data="rating_titles")],
                     [InlineKeyboardButton(text="🔙 Назад в меню", callback_data="back_to_main")]])


def admin_panel_keyboard(): 
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💰 Пополнить баланс", callback_data="admin_add_balance")],
            [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")],
            [InlineKeyboardButton(text="💎 Создать промокод", callback_data="admin_create_promo")],
            [InlineKeyboardButton(text="💎 Статистика промокодов", callback_data="admin_promo_stats")],
            [InlineKeyboardButton(text="🎁 Статистика рефералов", callback_data="admin_referral_stats")],
            [InlineKeyboardButton(text="👤 Инфо о пользователе", callback_data="admin_user_info")],
            [InlineKeyboardButton(text="📺 Управление каналами", callback_data="admin_manage_channels")],
            [InlineKeyboardButton(text="📊 Статистика подписок", callback_data="admin_subscription_stats")],
            [InlineKeyboardButton(text="🍺 Рассылка", callback_data="admin_rasilka")],
            [InlineKeyboardButton(text="🔙 Назад в меню", callback_data="back_to_main")]
        ]
    )


def channels_management_keyboard(): return InlineKeyboardMarkup(
    inline_keyboard=[[InlineKeyboardButton(text="📋 Показать каналы", callback_data="admin_show_channels")],
                     [InlineKeyboardButton(text="➕ Добавить канал", callback_data="admin_add_channel")],
                     [InlineKeyboardButton(text="🗑 Удалить канал", callback_data="admin_delete_channel")],
                     [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_panel")]])


def casino_start_keyboard(): return InlineKeyboardMarkup(
    inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад в меню", callback_data="back_to_main")]])


def casino_result_keyboard(): return InlineKeyboardMarkup(
    inline_keyboard=[[InlineKeyboardButton(text="🎲 Сыграть еще раз", callback_data="casino_play_again")],
                     [InlineKeyboardButton(text="🔙 Назад в меню", callback_data="back_to_main")]])


def support_keyboard(): return InlineKeyboardMarkup(
    inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад в меню", callback_data="back_to_main")]])


def elite_sub_keyboard(): return InlineKeyboardMarkup(
    inline_keyboard=[[InlineKeyboardButton(text="Купить за 25,000 баллов", callback_data="buy_elite_balance")],
                     [InlineKeyboardButton(text="Купить за 20 ⭐", callback_data="buy_elite_stars")],
                     [InlineKeyboardButton(text="🔙 Назад в меню", callback_data="back_to_main")]])


def subscriber_mode_keyboard(): return InlineKeyboardMarkup(
    inline_keyboard=[[InlineKeyboardButton(text="Default (без гарантии)", callback_data="sub_mode_default")],
                     [InlineKeyboardButton(text="Elite (гарантия 365 дней)", callback_data="sub_mode_elite")]])



def payment_choice_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⭐ Telegram Stars", callback_data="pay_stars_points")],
            [InlineKeyboardButton(text="🔙 Назад в меню", callback_data="back_to_main")]
        ]
    )

def crypto_points_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"1500 баллов ({CRYPTO_PRICES['points'][1500]} RUB)", callback_data="crypto_points_1500")],
            [InlineKeyboardButton(text=f"7500 баллов ({CRYPTO_PRICES['points'][7500]} RUB)", callback_data="crypto_points_7500")],
            [InlineKeyboardButton(text=f"15000 баллов ({CRYPTO_PRICES['points'][15000]} RUB)", callback_data="crypto_points_15000")],
            [InlineKeyboardButton(text=f"38000 баллов ({CRYPTO_PRICES['points'][38000]} RUB)", callback_data="crypto_points_38000")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="pay_crypto_back")]
        ]
    )
    
CAPTCHA_LENGTH = 5

def generate_numeric_captcha(length=CAPTCHA_LENGTH):
    captcha_code = ''.join(random.choices(string.digits, k=length))
    captcha_text = f"Пожалуйста, введите следующие цифры: `{captcha_code}`"
    return captcha_code, captcha_text
captcha_answers = {}

def prevent_callback_spam(callback_data_prefix):
    def decorator(func):
        async def wrapper(callback: types.CallbackQuery, *args, **kwargs):
            user_id = callback.from_user.id
            callback_data = callback.data
            
            cursor = db.conn.cursor()
            try:
                cursor.execute(
                    'INSERT INTO callback_locks (user_id, callback_data, created_at) VALUES (?, ?, ?)',
                    (user_id, callback_data, datetime.now().isoformat())
                )
                db.conn.commit()
            except sqlite3.IntegrityError:
                await callback.answer("⏳ Подождите, предыдущая операция еще обрабатывается...", show_alert=True)
                return
            
            try:
                result = await func(callback, *args, **kwargs)
                return result
            finally:
                cursor.execute(
                    'DELETE FROM callback_locks WHERE user_id = ? AND callback_data = ?',
                    (user_id, callback_data)
                )
                cursor.execute(
                    "DELETE FROM callback_locks WHERE created_at < datetime('now', '-30 seconds')"
                )
                db.conn.commit()
        
        return wrapper
    return decorator

@dp.message(Command("cancel"), StateFilter("*"))
async def cancel_handler(message: types.Message, state: FSMContext):
    if await state.get_state() is None: return
    await state.clear();
    await message.answer("Действие отменено.", reply_markup=main_keyboard(message.from_user.id))


@dp.message(Command("start"), StateFilter("*"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    user_id, username = message.from_user.id, message.from_user.username;
    cursor = db.conn.cursor();
    args = message.text.split();
    deep_link_param = args[1] if len(args) > 1 else None
    cursor.execute('SELECT user_id FROM users WHERE user_id = ?', (user_id,))
    if not cursor.fetchone():
        referred_by = None
        if deep_link_param and deep_link_param.startswith('ref'):
            try:
                ref_id = int(deep_link_param[3:])
                if ref_id != user_id:
                    cursor.execute('SELECT user_id FROM users WHERE user_id = ?', (ref_id,))
                    if cursor.fetchone(): referred_by = ref_id; cursor.execute(
                        'UPDATE users SET referrals = referrals + 1 WHERE user_id = ?', (ref_id,))
            except (ValueError, IndexError):
                pass
        captcha_code, captcha_text = generate_numeric_captcha()
        await state.update_data(captcha_code=captcha_code)
        await state.update_data(captcha_code=captcha_code)
        await state.set_state(UserState.captcha)
        await message.reply(f"{captcha_text}", parse_mode="Markdown")
        cursor.execute('INSERT INTO users (user_id, username, referred_by, balance) VALUES (?, ?, ?, ?)',
                       (user_id, username, referred_by, 1000 if referred_by else 0));
        db.conn.commit()
    else:
    	welcome_text = f"👋 Добро пожаловать в Раскрутка соц сетей[Бесплатно] Bot!\n\n🤖 Бот для раскрутки подписчиков, лайков, просмотров\n\n✨ Доступные соцсети:\n• 📱 Telegram - подписчики, реакции, просмотры\n• 🎭 VK - просмотры на пост, просмотры на видео, лайки\n• 🎵 TikTok - просмотры, лайки\n• 📷 Instagram - лайки, просмотры\n• 📺 YouTube - подписчики, лайки, просмотры\n\n� ***Elite Sub*** - подписчики с гарантией 365 дней!\n�💰 Ваш реферальный код: REF{user_id}\n🎁 Бонусы при регистрации - выполните обязательные подписки!"
    	await message.answer(welcome_text, reply_markup=main_keyboard(user_id), parse_mode="Markdown")
    
@dp.message(F.text, UserState.captcha)
async def check_answer(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    user_input = message.text.strip()
    data = await state.get_data()
    correct_code = data.get('captcha_code')
    if user_input == correct_code:
        def process_referral_reward(cursor):
            cursor.execute('SELECT referred_by, referral_reward_claimed FROM users WHERE user_id = ?', (user_id,))
            result = cursor.fetchone()
            
            if result and result[0] and not result[1]:
                referred_by = result[0]
                cursor.execute(
                    'UPDATE users SET referral_reward_claimed = 1 WHERE user_id = ? AND referral_reward_claimed = 0',
                    (user_id,)
                )
                
                if cursor.rowcount > 0:
                    cursor.execute('UPDATE users SET balance = balance + 7500 WHERE user_id = ?', (referred_by,))
                    return referred_by
            return None
        
        try:
            referrer_id = db.execute_transaction(process_referral_reward)
            
            if referrer_id:
                try:
                    await bot.send_message(referrer_id, "🎉 Ваш реферал выполнил все задания! Вы получили 7500 баллов!")
                except:
                    pass
        except Exception as e:
            logger.error(f"Error processing referral reward: {e}")
        
        welcome_text = f"👋 Добро пожаловать в Раскрутка соц сетей[Бесплатно] Bot!\n\n🤖 Бот для раскрутки подписчиков, лайков, просмотров\n\n✨ Доступные соцсети:\n• 📱 Telegram - подписчики, реакции, просмотры\n• 🎭 VK - просмотры на пост, просмотры на видео, лайки\n• 🎵 TikTok - просмотры, лайки\n• 📷 Instagram - лайки, просмотры\n• 📺 YouTube - подписчики, лайки, просмотры\n\n� ***Elite Sub*** - подписчики с гарантией 365 дней!\n�💰 Ваш реферальный код: REF{user_id}\n🎁 Бонусы при регистрации - выполните обязательные подписки!"
        await message.answer(welcome_text, reply_markup=main_keyboard(user_id), parse_mode="Markdown")
        await message.reply("✅ Вы успешно выполнили все задания!")
        await state.clear()
    else:
        return


@dp.message(F.text == "📊 Профиль", StateFilter("*"))
async def profile_handler(message: types.Message, state: FSMContext):
    await state.clear()
    user_id, cursor = message.from_user.id, db.conn.cursor();
    cursor.execute(
        'SELECT balance, referrals, title, total_spent, referred_by, registered_at, has_elite_sub, elite_sub_expires FROM users WHERE user_id = ?',
        (user_id,))
    user_data = cursor.fetchone()
    if user_data:
        balance, referrals, title, total_spent, referred_by, registered_at, has_elite, expires_at_str = user_data;
        bot_username = (await bot.get_me()).username
        profile_text = (f"👤 ***Ваш профиль***\n\n🆔 ID: `{user_id}`\n👑 Титул: ***{title}***\n")
        if has_elite and expires_at_str and datetime.fromisoformat(expires_at_str) > datetime.now():
            profile_text += f"💎 Статус Elite: **Активен до {datetime.fromisoformat(expires_at_str).strftime('%d.%m.%Y')}**\n"
        else:
            profile_text += f"💎 Статус Elite: ❌ Неактивен\n💡 *Активируйте Elite для доступа к подписчикам с гарантией!*\n"
        profile_text += (
            f"💰 Баланс: ***{balance}*** баллов\n💸 Всего потрачено: ***{total_spent}*** баллов\n👥 Рефералов: ***{referrals}***\n📅 Регистрация: {registered_at.split(' ')[0]}\n")
        if referred_by: profile_text += f"👨‍💼 Пригласил: {referred_by}\n"
        profile_text += f"\n🔗 Реферальная ссылка:\n`https://t.me/{bot_username}?start=ref{user_id}`"
        
        builder = InlineKeyboardBuilder()
        if not (has_elite and expires_at_str and datetime.fromisoformat(expires_at_str) > datetime.now()):
            builder.button(text="👑 Купить Elite Sub", callback_data="buy_elite_from_profile")
        builder.button(text="💰 Пополнить баланс", callback_data="buy_balance_from_profile")
        builder.adjust(1)
        
        await message.answer(profile_text, parse_mode="Markdown", reply_markup=builder.as_markup())
    else:
        await message.answer("❌ Профиль не найден. Нажмите /start")


@dp.message(F.text == "💼 Мои задания", StateFilter("*"))
async def tasks_handler(message: types.Message, state: FSMContext):
    await state.clear();
    user_id, cursor = message.from_user.id, db.conn.cursor()
    cursor.execute(
        'SELECT task_type, social_network, count, price, status, api_order_id FROM tasks WHERE user_id = ? ORDER BY task_id DESC LIMIT 10',
        (user_id,));
    tasks = cursor.fetchall()
    if tasks:
        tasks_text = "📋 ***Ваши последние 10 заданий:***\n\n";
        status_map = {"active": "⏳ В процессе", "completed": "✅ Выполнено", "partial": "🟠 Частично",
                      "canceled": "❌ Отменено"}
        for t_type, social, count, price, status, order_id in tasks: tasks_text += (
            f"***{social.upper()}*** - {t_type.replace('_', ' ').capitalize()}\n   - Статус: {status_map.get(status, '🤔 Неизвестно')}\n   - Количество: ***{count}*** | Стоимость: ***{price}*** баллов\n   - ID заказа: `{order_id}`\n\n")
    else:
        tasks_text = "📋 У вас пока нет заданий."
    await message.answer(tasks_text, parse_mode="Markdown")


@dp.message(F.text == "📢 Поддержка", StateFilter("*"))
async def support_handler(message: types.Message, state: FSMContext):
    await state.clear()

    photo_path = "assets/Поддержка.png"

    caption = (
        "📢 *Техническая поддержка*\n\n"
        "💬 *Способы связи:*\n"
        "• Telegram: @cryptoxmaple / @linsizze\n"
        "⏰ *Время работы:* с 12:00 до 24:00\n\n"
        "❓ *Частые вопросы:*\n"
        "• Как пополнить баланс?\n"
        "• Сколько времени выполняется заказ?\n"
        "• Что делать, если заказ не выполнился?\n\n"
        "🆘 При возникновении проблем — опишите ситуацию детально."
    )

    await message.answer_photo(
        photo=types.FSInputFile(photo_path), 
        caption=caption,
        parse_mode="Markdown",
        reply_markup=support_keyboard()
    )


@dp.message(F.text == "✅ Проверить выполнение", StateFilter("*"))
async def check_tasks_button_handler(message: types.Message, state: FSMContext):
    await state.clear();
    user_id, cursor = message.from_user.id, db.conn.cursor();
    uncompleted_tasks = []
    for task in load_channels_from_db():
        cursor.execute('SELECT user_id FROM required_tasks WHERE user_id = ? AND channel_username = ?',
                       (user_id, task['username']));
        if not cursor.fetchone(): uncompleted_tasks.append(task)
    if uncompleted_tasks:
        text = "⚠️ Сделайте задание для продолжения работы:\n\n"
        for task in uncompleted_tasks: text += f"📱 {task['name']} - подпишитесь\n"
        text += "\n💡 После подписки нажмите 'Проверить выполнение'";
        await message.answer(text, reply_markup=required_tasks_keyboard())
    else:
        await message.answer("✅ Все задания выполнены! Можете создавать новые.")




@dp.callback_query(F.data == "admin_promo_stats")
async def admin_promo_stats_handler(callback: types.CallbackQuery):
    await show_promo_stats_page(callback, page=0)

@dp.callback_query(F.data.startswith("promo_stats_page_"))
async def promo_stats_page_handler(callback: types.CallbackQuery):
    page = int(callback.data.split("_")[-1])
    await show_promo_stats_page(callback, page)

async def show_promo_stats_page(callback: types.CallbackQuery, page: int):
    cursor = db.conn.cursor()
    cursor.execute('SELECT code, reward, max_uses, current_uses, is_active FROM promocodes')
    promos = cursor.fetchall()
    
    per_page = 10
    total_pages = (len(promos) + per_page - 1) // per_page if promos else 1
    page = max(0, min(page, total_pages - 1))
    
    start_idx = page * per_page
    end_idx = start_idx + per_page
    page_promos = promos[start_idx:end_idx]
    
    text = f"💎 ***Статистика промокодов*** (стр. {page + 1}/{total_pages}):\n\n"
    
    if not page_promos:
        text += "Нет промокодов."
    else:
        for code, reward, max_uses, current_uses, is_active in page_promos:
            cursor.execute("""
                SELECT COUNT(*) FROM promocode_usage 
                WHERE code = ? AND used_at >= datetime('now', '-1 day')
            """, (code,))
            daily_uses = cursor.fetchone()[0]
            status = "Активен" if is_active else "Неактивен"
            text += f"***{code}*** ({reward} баллов, макс {max_uses}):\n   - Использований: {current_uses}\n   - За день: {daily_uses}\n   - Статус: {status}\n\n"
    
    builder = InlineKeyboardBuilder()
    nav_buttons = []
    
    if page > 0:
        nav_buttons.append(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"promo_stats_page_{page - 1}"))
    
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton(text="Вперёд ➡️", callback_data=f"promo_stats_page_{page + 1}"))
    
    if nav_buttons:
        builder.row(*nav_buttons)
    
    builder.row(InlineKeyboardButton(text="🔙 В админ панель", callback_data="admin_panel"))
    
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="Markdown")


@dp.callback_query(F.data == "admin_referral_stats")
async def admin_referral_stats_handler(callback: types.CallbackQuery):
    cursor = db.conn.cursor()
    cursor.execute('SELECT SUM(referrals) FROM users')
    total_referrals = cursor.fetchone()[0] or 0
    cursor.execute("""
        SELECT COUNT(*) FROM users 
        WHERE referred_by IS NOT NULL AND registered_at >= datetime('now', '-1 day')
    """)
    daily_referrals = cursor.fetchone()[0]
    cursor.execute('SELECT user_id, username, referrals FROM users ORDER BY referrals DESC LIMIT 10')
    top = cursor.fetchall()
    text = f"🎁 Статистика рефералов:\n\nОбщее: {total_referrals}\nЗа день: {daily_referrals}\n\nТоп-10:\n"
    for i, (uid, uname, refs) in enumerate(top, 1):
        cursor.execute("""
            SELECT COUNT(*) FROM users 
            WHERE referred_by = ? AND registered_at >= datetime('now', '-1 day')
        """, (uid,))
        daily = cursor.fetchone()[0]
        text += f"{i}. @{uname or uid} - {refs} (за день: {daily})\n"
    await callback.message.edit_text(text, reply_markup=admin_panel_keyboard())


@dp.callback_query(F.data == "admin_user_info")
async def admin_user_info_handler(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_text("👤 Введите ID пользователя для просмотра инфы:")
    await state.set_state(Form.waiting_for_admin_user_info_id)


@dp.message(Form.waiting_for_admin_user_info_id)
async def process_admin_user_info_id(message: types.Message, state: FSMContext):
    try:
        user_id = int(message.text)
    except ValueError:
        await message.answer("❌ Неверный ID.")
        return
    cursor = db.conn.cursor()
    cursor.execute("""
        SELECT username, balance, referrals, registered_at, referred_by, total_spent, title, has_elite_sub, elite_sub_expires
        FROM users WHERE user_id = ?
    """, (user_id,))
    user = cursor.fetchone()
    if not user:
        await message.answer("❌ Пользователь не найден.")
        await state.clear()
        return
    username, balance, referrals, registered_at, referred_by, total_spent, title, has_elite, elite_expires = user
    text = f"👤 Инфо о пользователе {user_id} (@{username}):\n\nБаланс: {balance}\nРефералы: {referrals}\nРегистрация: {registered_at}\nПригласил: {referred_by or 'Нет'}\nПотрачено: {total_spent}\nТитул: {title}\nElite: {'Да' if has_elite else 'Нет'} (до {elite_expires or 'N/A'})\n\n"
    
    cursor.execute("""
        SELECT task_type, social_network, count, price, status, created_at
        FROM tasks WHERE user_id = ? ORDER BY created_at DESC LIMIT 10
    """, (user_id,))
    orders = cursor.fetchall()
    text += "История заказов (последние 10):\n"
    if not orders:
        text += "Нет заказов.\n"
    for t_type, social, count, price, status, created in orders:
        text += f"{social} {t_type}: {count} шт, {price} баллов, статус {status} ({created})\n"
    
    cursor.execute("""
        SELECT purchase_type, amount, points_or_elite, purchased_at
        FROM purchases WHERE user_id = ? ORDER BY purchased_at DESC
    """, (user_id,))
    purchases = cursor.fetchall()
    text += "\nПокупки:\n"
    if not purchases:
        text += "Нет покупок.\n"
    total_stars = 0
    for p_type, amount, points_elite, date in purchases:
        if p_type.startswith('stars_'):
            total_stars += amount
        text += f"{p_type}: {amount} (получено {points_elite}), {date}\n"
    text += f"\nВсего куплено звёзд: {total_stars}\n"
    
    await message.answer(text)
    await state.clear()




@dp.callback_query(F.data == "back_to_main", StateFilter("*"))
async def back_to_main_handler(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    try:
        await callback.message.delete()
    except TelegramBadRequest:
        await callback.answer()


@dp.message(F.text == "➕ Создать задание", StateFilter("*"))
async def create_task_handler(msg: types.Message, state: FSMContext):
    me = await bot.get_me()
    origin_link = f"https://t.me/{me.username}?start=1"

    lang_code = (msg.from_user.language_code or "ru")

    message22 = {
        'rows': 2,
        'text': '<b>$name, Чтобы пользоваться услугами бота, подпишитесь на этот канал:</b>', 

        'button_bot': 'Запустить',
        'button_channel': 'Подписаться',
        'button_url': 'Перейти',
        'button_boost': 'Голосовать',
        'button_fp': 'Выполнить',
    }

    if flyer and (not await flyer.check(msg.from_user.id, language_code=lang_code, message=message22)):
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Проверить подписку", url=origin_link)]
        ])
        return

    photo_path = "assets/Создать задание.png"
    caption = "📱 Выберите социальную сеть:"

    await msg.answer_photo(
        photo=types.FSInputFile(photo_path),
        caption=caption,
        reply_markup=social_keyboard()
    )
    	

@dp.callback_query(F.data == "check_required_tasks")
@prevent_callback_spam("check_required_tasks")
async def check_required_tasks_handler(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    
    def process_tasks_check(cursor):
        total_reward = 0
        all_completed = True
        
        cursor.execute('SELECT COUNT(*) FROM required_tasks WHERE user_id = ?', (user_id,))
        was_already_completed_once = cursor.fetchone()[0] > 0
        
        tasks_to_add = []
        for task in load_channels_from_db():
            cursor.execute('SELECT 1 FROM required_tasks WHERE user_id = ? AND channel_username = ?',
                         (user_id, task['username']))
            if not cursor.fetchone():
                tasks_to_add.append(task)
                all_completed = False
        
        if not all_completed:
            return {"success": False, "completed": False}
        
        if was_already_completed_once:
            return {"success": True, "completed": True, "reward": 0, "referrer_rewarded": False}
        
        for task in load_channels_from_db():
            cursor.execute(
                'INSERT OR IGNORE INTO required_tasks (user_id, channel_username) VALUES (?, ?)',
                (user_id, task['username'])
            )
            if cursor.rowcount > 0:
                cursor.execute('UPDATE users SET balance = balance + ? WHERE user_id = ?',
                             (task['reward'], user_id))
                total_reward += task['reward']
        
        cursor.execute('SELECT referred_by, referral_reward_claimed FROM users WHERE user_id = ?', (user_id,))
        result = cursor.fetchone()
        referrer_id = None
        
        if result and result[0] and not result[1]:
            cursor.execute(
                'UPDATE users SET referral_reward_claimed = 1 WHERE user_id = ? AND referral_reward_claimed = 0',
                (user_id,)
            )
            
            if cursor.rowcount > 0:
                cursor.execute('UPDATE users SET balance = balance + 5000 WHERE user_id = ?', (result[0],))
                referrer_id = result[0]
        
        return {
            "success": True,
            "completed": True,
            "reward": total_reward,
            "referrer_id": referrer_id,
            "referrer_rewarded": referrer_id is not None
        }
    
    uncompleted_tasks = []
    for task in load_channels_from_db():
        try:
            member = await bot.get_chat_member(task['username'], user_id)
            if member.status not in ['member', 'administrator', 'creator']:
                uncompleted_tasks.append(task)
        except:
            uncompleted_tasks.append(task)
    
    if uncompleted_tasks:
        await callback.answer("❌ Вы подписались не на все каналы. Попробуйте снова.", show_alert=True)
        return

    try:
        result = db.execute_transaction(process_tasks_check)
        
        if not result["success"] or not result["completed"]:
            await callback.answer("❌ Вы подписались не на все каналы. Попробуйте снова.", show_alert=True)
            return
        
        if result.get("referrer_rewarded") and result.get("referrer_id"):
            try:
                await bot.send_message(
                    result["referrer_id"],
                    "🎉 Ваш реферал выполнил все задания! Вы получили ***7500*** баллов!",
                    parse_mode="Markdown"
                )
            except:
                pass

        text = "✅ Отлично! Все задания выполнены."
        if result["reward"] > 0:
            text += f" Вам начислено ***{result['reward']}*** баллов."
        
        await callback.message.edit_text(text + "\n\nТеперь вы можете создавать заказы.", parse_mode="Markdown")
        await asyncio.sleep(2)
        await callback.message.answer("📱 Выберите социальную сеть:", reply_markup=social_keyboard())
        
    except Exception as e:
        logger.error(f"Error in check_required_tasks: {e}")
        await callback.answer("❌ Произошла ошибка. Попробуйте еще раз.", show_alert=True)


@dp.callback_query(F.data.startswith("social_"))
async def social_handler(callback: types.CallbackQuery, state: FSMContext):
    social = callback.data.split("_")[1]
    keyboards_map = {
        "telegram": ("📱 Telegram", {"👥 Подписчики": "members", "❤️ Реакции": "reactions", "👀 Просмотры": "views"}),
        "vk": ("🎭 VK",
               {"👀 Просмотры на пост": "post_views", "🎬 Просмотры на видео": "video_views", "❤️ Лайки": "likes"}),
        "tiktok": ("🎵 TikTok", {"👀 Просмотры": "views", "❤️ Лайки": "likes"}),
        "instagram": ("📷 Instagram", {"❤️ Лайки": "likes", "👀 Просмотры": "views"}),
        "youtube": ("📺 YouTube", {"👥 Подписчики": "subscribers", "❤️ Лайки": "likes", "👀 Просмотры": "views"})}
    if social in keyboards_map:
        title, tasks = keyboards_map[social];
        await callback.message.edit_caption(
            caption=f"{title}: выберите тип задания:",
            reply_markup=tasks_keyboard(social, tasks)
        )


@dp.callback_query(F.data == "back_to_social")
async def back_to_social_handler(callback: types.CallbackQuery):
    if callback.message.photo:
        await callback.message.edit_caption(
            caption="📱 Выберите социальную сеть:",
            reply_markup=social_keyboard()
        )
    else:
        await callback.message.edit_text(
            "📱 Выберите социальную сеть:",
            reply_markup=social_keyboard()
        )


@dp.callback_query(F.data.startswith("task_"))
async def task_type_handler(callback: types.CallbackQuery, state: FSMContext):
    _, social, task_type = callback.data.split("_", 2)
    await state.update_data(social=social, task_type=task_type)
    
    if social == 'telegram' and task_type in ['members', 'reactions']:
        guide_text = "📖 ***Важно!*** Перед заказом ознакомьтесь с гайдом:\n🔗 https://t.me/boostyprojectchannel/49\n\n"
        await callback.message.answer(guide_text, parse_mode="Markdown")

    if social == 'telegram' and task_type == 'members':
        cursor = db.conn.cursor();
        cursor.execute('SELECT has_elite_sub, elite_sub_expires FROM users WHERE user_id = ?',
                       (callback.from_user.id,));
        has_elite, expires_at_str = cursor.fetchone()
        if has_elite and expires_at_str and datetime.fromisoformat(expires_at_str) > datetime.now():
            await bot.delete_message(chat_id=callback.message.chat.id, message_id=callback.message.message_id)
            await callback.message.answer(
                f"💎 У вас активна Elite подписка!\n\nВыберите режим раскрутки подписчиков:\n\n🔹 ***Default*** - обычные подписчики без гарантии.\nЦена: ***{PRICES['telegram_members']}*** баллов/шт.\n\n⭐ ***Elite*** - подписчики с гарантией 365 дней.\nЦена: ***{PRICES['telegram_members_elite']}*** баллов/шт.",
                reply_markup=subscriber_mode_keyboard(), parse_mode="Markdown");
            await state.set_state(Form.waiting_for_subscriber_mode);
            return

    service = await boost_api.find_service_by_name(f"{social}_{task_type}")
    if not service: return await callback.message.edit_text("❌ Услуга временно недоступна.",
                                                            reply_markup=social_keyboard())

    min_q, max_q = 10, 20000
    if not (social == 'telegram' and task_type == 'members'):
        min_q, max_q = int(service.get('min', 10)), int(service.get('max', 5000))

    await state.update_data(service=service, min_q=min_q, max_q=max_q)
    if callback.message.photo:
        await callback.message.edit_caption(
            caption=f"🔢 Введите желаемое количество (мин: {min_q}, макс: {max_q}):"
        )
    else:
        await callback.message.edit_text(
            f"🔢 Введите желаемое количество (мин: {min_q}, макс: {max_q}):"
        )
    await state.set_state(Form.waiting_for_task_count)


@dp.callback_query(F.data.startswith("sub_mode_"), Form.waiting_for_subscriber_mode)
async def process_subscriber_mode(callback: types.CallbackQuery, state: FSMContext):
    mode = callback.data.split("_")[2];
    await state.update_data(subscriber_mode=mode);
    is_elite = mode == 'elite'

    if is_elite:
        service = await boost_api.find_elite_service()
    else:
        service = await boost_api.find_service_by_name("telegram_members")

    if not service: return await callback.message.edit_text("❌ Услуга временно недоступна.",
                                                            reply_markup=social_keyboard())

    min_q, max_q = (10, 20000) if not is_elite else (int(service.get('min', 500)), int(service.get('max', 250000)))

    await state.update_data(service=service, min_q=min_q, max_q=max_q)
    await callback.message.edit_text(f"🔢 Введите желаемое количество (мин: {min_q}, макс: {max_q}):");
    await state.set_state(Form.waiting_for_task_count)


@dp.message(Form.waiting_for_task_count)
async def process_task_count(message: types.Message, state: FSMContext):
    user_data = await state.get_data();
    min_q, max_q = user_data.get('min_q', 10), user_data.get('max_q', 5000)
    try:
        count = int(message.text)
        if not (min_q <= count <= max_q): return await message.answer(
            f"❌ Количество должно быть от {min_q} до {max_q}.")
        await state.update_data(count=count);
        await message.answer("🔗 Отправьте ссылку на ваш канал, пост, видео или профиль.");
        await state.set_state(Form.waiting_for_target_url)
    except ValueError:
        await message.answer("❌ Пожалуйста, введите число.")


@dp.message(Form.waiting_for_target_url)
async def process_task_target(message: types.Message, state: FSMContext):
    target, user_data = message.text, await state.get_data()
    social, task_type, count, service = user_data['social'], user_data['task_type'], user_data['count'], user_data[
        'service']
    subscriber_mode = user_data.get('subscriber_mode', 'default')
    is_elite_task = social == 'telegram' and task_type == 'members' and subscriber_mode == 'elite'
    price_key = f"telegram_members_elite" if is_elite_task else f"{social}_{task_type}"
    price = int(PRICES[price_key] * count)

    await state.clear()

    def create_order_transaction(cursor):
        cursor.execute('SELECT balance FROM users WHERE user_id = ?', (message.from_user.id,))
        user_balance = cursor.fetchone()
        
        if not user_balance or user_balance[0] < price:
            return {"error": f"Недостаточно средств. Нужно: {price} баллов.", "balance": user_balance[0] if user_balance else 0}

        new_balance = user_balance[0] - price
        if new_balance < 0:
            return {"error": f"Недостаточно средств. Нужно: {price} баллов.", "balance": user_balance[0]}
        
        # Списываем средства
        cursor.execute('UPDATE users SET balance = balance - ? WHERE user_id = ? AND balance >= ?',
                      (price, message.from_user.id, price))
        
        if cursor.rowcount == 0:
            return {"error": "Недостаточно средств или произошла ошибка.", "balance": user_balance[0]}
        
        return {"success": True}
    
    try:
        result = db.execute_transaction(create_order_transaction)
        
        if "error" in result:
            return await message.answer(f"❌ {result['error']}")
        
        api_result = await boost_api.create_order(str(service['service']), target, count)
        
        if api_result and "order" in api_result:
            order_id = str(api_result["order"])
            cursor = db.conn.cursor()
            cursor.execute(
                'INSERT INTO tasks (user_id, task_type, social_network, target_url, count, price, api_order_id) VALUES (?, ?, ?, ?, ?, ?, ?)',
                (message.from_user.id, task_type, social, target, count, price, order_id))
            db.conn.commit()
            
            await update_user_title(message.from_user.id, price)
            await message.answer(
                f"✅ ***Заказ создан успешно!**\n\n**ID заказа:*** `{order_id}`\n***Услуга:*** {social.upper()} - {task_type.replace('_', ' ').capitalize()} {'(Elite)' if is_elite_task else ''}\n***Количество:*** {count}\n***Списано:*** {price} баллов\n\n⏳ Ожидайте выполнения в течение 24 часов.",
                parse_mode="Markdown")
        else:
            cursor = db.conn.cursor()
            cursor.execute('UPDATE users SET balance = balance + ? WHERE user_id = ?',
                         (price, message.from_user.id))
            db.conn.commit()
            
            await message.answer(f"❌ Ошибка при создании заказа: {api_result.get('error', 'Неизвестная ошибка API')}. Средства возвращены на ваш баланс.")
    
    except Exception as e:
        logger.error(f"Error creating order: {e}")
        try:
            cursor = db.conn.cursor()
            cursor.execute('UPDATE users SET balance = balance + ? WHERE user_id = ?',
                         (price, message.from_user.id))
            db.conn.commit()
            await message.answer("❌ Произошла ошибка. Средства возвращены на ваш баланс.")
        except:
            await message.answer("❌ Произошла критическая ошибка. Обратитесь в поддержку.")


@dp.message(Form.waiting_for_promo_code)
async def process_promocode(message: types.Message, state: FSMContext):
    code, user_id = message.text.strip().upper(), message.from_user.id
    
    def activate_promocode(cursor):
        cursor.execute('SELECT reward, max_uses, current_uses, is_active FROM promocodes WHERE code = ?', (code,))
        promo = cursor.fetchone()
        
        if not promo or not promo[3]:
            return {"error": "Промокод не найден или неактивен."}
        
        reward, max_uses, current_uses, _ = promo
        
        if current_uses >= max_uses:
            return {"error": "Лимит этого промокода исчерпан."}
        
        cursor.execute('SELECT 1 FROM promocode_usage WHERE user_id = ? AND code = ?', (user_id, code))
        if cursor.fetchone():
            return {"error": "Вы уже использовали этот промокод."}
        
        cursor.execute('UPDATE users SET balance = balance + ? WHERE user_id = ?', (reward, user_id))
        cursor.execute('UPDATE promocodes SET current_uses = current_uses + 1 WHERE code = ?', (code,))
        cursor.execute('INSERT INTO promocode_usage (user_id, code) VALUES (?, ?)', (user_id, code))
        
        return {"success": True, "reward": reward}
    
    try:
        result = db.execute_transaction(activate_promocode)
        
        if "error" in result:
            await message.answer(f"❌ {result['error']}")
        else:
            await message.answer(f"✅ Промокод успешно активирован! Вам начислено ***{result['reward']}*** баллов!", parse_mode="Markdown")
        
        await state.clear()
    except Exception as e:
        logger.error(f"Error activating promocode: {e}")
        await message.answer("❌ Произошла ошибка при активации промокода.")
        await state.clear()


@dp.message(F.text == "💰 Пополнить баланс", StateFilter("*"))
async def buy_stars_handler(message: types.Message, state: FSMContext):
    await state.clear()
    
    cursor = db.conn.cursor()
    cursor.execute('SELECT has_elite_sub, elite_sub_expires FROM users WHERE user_id = ?', (message.from_user.id,))
    has_elite, expires_at_str = cursor.fetchone()
    
    photo_path = "assets/Купить Звезды.png" 
    
    caption = "💳 Выберите способ пополнения баланса:"
    
    if not (has_elite and expires_at_str and datetime.fromisoformat(expires_at_str) > datetime.now()):
        caption += "\n\n💡 *Совет: Активируйте Elite Sub для доступа к подписчикам с гарантией 365 дней!*"

    await message.answer_photo(
        photo=types.FSInputFile(photo_path), 
        caption=caption,
        parse_mode="Markdown",
        reply_markup=payment_choice_keyboard()
    )


@dp.callback_query(F.data.startswith("buy_stars_"))
async def process_stars_purchase(callback: types.CallbackQuery):
    stars = int(callback.data.split("_")[2]);
    points_map = {1: 1000, 5: 5500, 10: 12000, 25: 30000, 50: 65000, 75: 105000, 100: 140000};
    points = points_map[stars];
    prices = [LabeledPrice(label=f"{points} баллов", amount=stars)]
    await bot.send_invoice(chat_id=callback.from_user.id, title=f"Покупка {points} баллов",
                           description=f"Пополнение баланса на {points} баллов за {stars} звезд",
                           payload=f"stars_{points}_{callback.from_user.id}", provider_token="", currency="XTR",
                           prices=prices)


@dp.callback_query(F.data == "pay_stars_points")
async def pay_stars_points_handler(callback: types.CallbackQuery):
    await bot.delete_message(chat_id=callback.message.chat.id, message_id=callback.message.message_id)
    await callback.message.answer("⭐ Выберите количество баллов для покупки:", reply_markup=stars_keyboard())

@dp.callback_query(F.data == "pay_crypto_points")
async def pay_crypto_points_handler(callback: types.CallbackQuery):
    await bot.delete_message(chat_id=callback.message.chat.id, message_id=callback.message.message_id)
    await callback.message.answer("💎 Выберите пакет баллов для оплаты криптовалютой (через @CryptoBot):", reply_markup=crypto_points_keyboard())

@dp.callback_query(F.data == "pay_crypto_back")
async def pay_crypto_back_handler(callback: types.CallbackQuery):
    photo_path = "assets/Купить Звезды.png" 

    caption = "💳 Выберите способ пополнения баланса:"

    await callback.message.answer_photo(
        photo=types.FSInputFile(photo_path), 
        caption=caption,
        reply_markup=payment_choice_keyboard()
    )
    
@dp.callback_query(F.data == "back_to_hui")
async def back_to_hui_handler(callback: types.CallbackQuery):
    
    photo_path = "assets/Купить Звезды.png" 

    caption = "💳 Выберите способ пополнения баланса:"

    await callback.message.answer_photo(
        photo=types.FSInputFile(photo_path), 
        caption=caption,
        reply_markup=payment_choice_keyboard()
    )

@dp.callback_query(F.data.startswith("crypto_points_"))
async def process_crypto_points_purchase(callback: types.CallbackQuery):
    points = int(callback.data.split("_")[2])
    amount_rub = CRYPTO_PRICES['points'][points]
    result = await create_crypto_invoice(callback.from_user.id, amount_rub, points=points)
    if 'pay_url' in result:
        message_text = (
            f"✅ Счет создан! Оплатите {amount_rub} RUB по ссылке:\n"
            f"{result['pay_url']}\n\n"
            "После оплаты баллы будут начислены автоматически в течение 5-10 мин."
        )
        await callback.message.edit_text(
            text=message_text,
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="pay_crypto_points")]]
            )
        )
    else:
        error_text = (
            "❌ Не удалось создать счет. "
            "Попробуйте позже или обратитесь в поддержку (@KPTkdv)."
        )
        await callback.message.edit_text(
            text=error_text,
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="pay_crypto_points")]]
            )
        )
        await callback.answer(
            "⚠️ Ошибка API CryptoBot. Подробности в логах.",
            show_alert=True
        )

@dp.pre_checkout_query()
async def pre_checkout_handler(pre_checkout_query: PreCheckoutQuery):
    await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)


@dp.message(F.successful_payment)
async def successful_payment_handler(message: types.Message):
    payload, user_id, cursor = message.successful_payment.invoice_payload, message.from_user.id, db.conn.cursor()
    if payload.startswith("stars_"):
        points = int(payload.split("_")[1])
        stars_amount = message.successful_payment.total_amount
        cursor.execute('UPDATE users SET balance = balance + ? WHERE user_id = ?', (points, user_id))
        cursor.execute('INSERT INTO purchases (user_id, purchase_type, amount, points_or_elite) VALUES (?, ?, ?, ?)',
                       (user_id, 'stars_points', stars_amount, points))
        db.conn.commit()
        await message.answer(f"✅ Успешно! На ваш баланс зачислено {points} баллов!")
    elif payload.startswith("elite_sub_"):
        expires_at = datetime.now() + timedelta(days=30)
        cursor.execute('UPDATE users SET has_elite_sub = 1, elite_sub_expires = ? WHERE user_id = ?',
                       (expires_at.isoformat(), user_id))
        cursor.execute('INSERT INTO purchases (user_id, purchase_type, amount, points_or_elite) VALUES (?, ?, ?, ?)',
                       (user_id, 'stars_elite', 20, 1))
        db.conn.commit()
        await message.answer(
            f"✅ ***Elite подписка успешно активирована!***\nСрок действия: до {expires_at.strftime('%d.%m.%Y')}",
            parse_mode="Markdown")


@dp.message(F.text == "👑 Elite Sub", StateFilter("*"))
async def elite_sub_handler(message: types.Message, state: FSMContext):
    await state.clear()

    photo_path = "assets/Элита.jpg"
    caption = (
        "💎 ***Elite Подписка (30 дней)***\n\n"
        "Получите доступ к эксклюзивным возможностям!\n\n"
        "***Преимущества:***\n"
        "⭐ Доступ к раскрутке ***Telegram подписчиков с гарантией 365 дней*** от отписок.\n\n"
        "***Стоимость:***\n"
        "- `25,000` внутриигровых баллов\n"
        "- `20` Telegram Stars (⭐)"
    )

    await message.answer_photo(
        photo=types.FSInputFile(photo_path), 
        caption=caption,
        parse_mode="Markdown",
        reply_markup=elite_sub_keyboard()
    )


@dp.callback_query(F.data == "buy_elite_balance")
@prevent_callback_spam("buy_elite_balance")
async def buy_elite_with_balance(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    
    def buy_elite_transaction(cursor):
        cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
        balance = cursor.fetchone()[0]
        
        if balance < 25000:
            return {"error": "Недостаточно баллов для покупки."}
        
        expires_at = datetime.now() + timedelta(days=30)
        cursor.execute(
            'UPDATE users SET balance = balance - 25000, has_elite_sub = 1, elite_sub_expires = ? WHERE user_id = ? AND balance >= 25000',
            (expires_at.isoformat(), user_id)
        )
        
        if cursor.rowcount == 0:
            return {"error": "Недостаточно баллов или произошла ошибка."}
        
        return {"success": True, "expires_at": expires_at}
    
    try:
        result = db.execute_transaction(buy_elite_transaction)
        
        if "error" in result:
            await callback.answer(f"❌ {result['error']}", show_alert=True)
        else:
            await bot.delete_message(chat_id=callback.message.chat.id, message_id=callback.message.message_id)
            await callback.message.answer(
                f"✅ ***Elite подписка успешно активирована!***\nСрок действия: до {result['expires_at'].strftime('%d.%m.%Y')}",
                parse_mode="Markdown"
            )
    except Exception as e:
        logger.error(f"Error buying elite: {e}")
        await callback.answer("❌ Произошла ошибка при покупке.", show_alert=True)


@dp.callback_query(F.data == "buy_elite_stars")
async def buy_elite_with_stars(callback: types.CallbackQuery):
    prices = [LabeledPrice(label=f"Elite Подписка (30 дней)", amount=20)];
    await bot.send_invoice(chat_id=callback.from_user.id, title="Покупка Elite Подписки",
                           description="Доступ к эксклюзивным услугам на 30 дней",
                           payload=f"elite_sub_{callback.from_user.id}", provider_token="", currency="XTR",
                           prices=prices)


@dp.callback_query(F.data == "buy_elite_crypto")
async def buy_elite_crypto_handler(callback: types.CallbackQuery):
    amount_rub = CRYPTO_PRICES['elite']
    result = await create_crypto_invoice(callback.from_user.id, amount_rub, is_elite=True)
    if 'pay_url' in result:
        await bot.delete_message(chat_id=callback.message.chat.id, message_id=callback.message.message_id)
        await callback.message.answer(
            f"✅ Счет создан! Оплатите {amount_rub} RUB по ссылке:\n{result['pay_url']}\n\nПосле оплаты Elite будет активирована автоматически в течение 5-10 мин.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main")]]),
            parse_mode="Markdown"
        )
    else:
        await callback.message.edit_text(
            "❌ Не удалось создать счет. Попробуйте позже или обратитесь в поддержку (@KPTkdv).",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main")]]),
            parse_mode="Markdown"
        )
        await callback.answer("⚠️ Ошибка API CryptoBot. Подробности в логах.", show_alert=True)



@dp.callback_query(F.data == "casino_play_again", StateFilter("*"))
async def casino_play_again_handler(callback: types.CallbackQuery, state: FSMContext):
    await state.clear();
    cursor = db.conn.cursor();
    cursor.execute('SELECT balance FROM users WHERE user_id = ?', (callback.from_user.id,));
    balance = cursor.fetchone()[0]
    await callback.message.edit_text(
        f"🎰 Снова в игре!\nВаш баланс: **{balance}** баллов.\n\n*'*Возможные множители:**\n`x0` | `x1` | `x2` | `x2.5`\n\nВведите сумму ставки:",
        parse_mode="Markdown", reply_markup=casino_start_keyboard());
    await state.set_state(Form.waiting_for_bet)


@dp.message(Form.waiting_for_bet)
async def process_bet(message: types.Message, state: FSMContext):
    try:
        bet = int(message.text)
    except ValueError:
        return await message.answer("❌ Введите число.")
    if bet <= 0: return await message.answer("❌ Ставка должна быть больше нуля.")
    
    user_id = message.from_user.id
    
    def casino_bet_transaction(cursor):
        cursor.execute('SELECT balance FROM users WHERE user_id = ?', (user_id,))
        balance = cursor.fetchone()[0]
        
        if bet > balance:
            return {"error": "Недостаточно средств."}
        
        # Списываем ставку
        cursor.execute('UPDATE users SET balance = balance - ? WHERE user_id = ? AND balance >= ?',
                      (bet, user_id, bet))
        
        if cursor.rowcount == 0:
            return {"error": "Недостаточно средств или произошла ошибка."}
        
        return {"success": True}
    
    try:
        result = db.execute_transaction(casino_bet_transaction)
        
        if "error" in result:
            await state.clear()
            return await message.answer(f"❌ {result['error']}")
        
        await state.clear()
        
        msg = await message.answer("🎰 Вращаем барабаны...")
        await asyncio.sleep(1.5)
        
        multiplier = random.choices([0, 1, 2, 2.5], weights=[30, 55, 10, 5], k=1)[0]
        winnings = int(bet * multiplier)
        
        if winnings > 0:
            cursor = db.conn.cursor()
            cursor.execute('UPDATE users SET balance = balance + ? WHERE user_id = ?', (winnings, user_id))
            db.conn.commit()
        
        cursor = db.conn.cursor()
        cursor.execute('SELECT balance FROM users WHERE user_id = ?', (user_id,))
        new_balance = cursor.fetchone()[0]
        
        text = f"🎉 Поздравляем! Ваш множитель ***x{multiplier}***, выигрыш ***{winnings}*** баллов!" if winnings > bet else f"😐 Ничья. Ваш множитель ***x{multiplier}***, ставка возвращена." if winnings == bet else f"😔 Увы, вы проиграли. Ваш множитель ***x{multiplier}***."
        await msg.edit_text(f"{text}\n\n💰 Ваш новый баланс: ***{new_balance}*** баллов.", parse_mode="Markdown",
                          reply_markup=casino_result_keyboard())
    
    except Exception as e:
        logger.error(f"Error in casino: {e}")
        await message.answer("❌ Произошла ошибка. Обратитесь в поддержку.")
        await state.clear()


@dp.message(Form.waiting_for_recipient_id)
async def process_recipient_id(message: types.Message, state: FSMContext):
    try:
        recipient_id = int(message.text)
    except ValueError:
        return await message.answer("❌ ID должен быть числом.")
    if recipient_id == message.from_user.id: await state.clear(); return await message.answer(
        "❌ Нельзя перевести баллы самому себе.")
    cursor = db.conn.cursor();
    cursor.execute('SELECT 1 FROM users WHERE user_id = ?', (recipient_id,))
    if not cursor.fetchone(): await state.clear(); return await message.answer("❌ Пользователь не найден.")
    await state.update_data(recipient_id=recipient_id);
    await message.answer("Введите сумму для перевода:");
    await state.set_state(Form.waiting_for_transfer_amount)


@dp.message(Form.waiting_for_transfer_amount)
async def process_transfer_amount(message: types.Message, state: FSMContext):
    try:
        amount = int(message.text);
    except ValueError:
        return await message.answer("❌ Введите число.")
    if amount <= 0: return await message.answer("❌ Сумма должна быть больше нуля.")
    
    sender_id = message.from_user.id
    recipient_id = (await state.get_data())['recipient_id']

    def transfer_transaction(cursor):
        cursor.execute('SELECT balance FROM users WHERE user_id = ?', (sender_id,))
        balance = cursor.fetchone()[0]
        
        if amount > balance:
            return {"error": "Недостаточно средств."}

        cursor.execute('UPDATE users SET balance = balance - ? WHERE user_id = ? AND balance >= ?',
                      (amount, sender_id, amount))
        
        if cursor.rowcount == 0:
            return {"error": "Недостаточно средств или произошла ошибка."}

        cursor.execute('UPDATE users SET balance = balance + ? WHERE user_id = ?', (amount, recipient_id))
        
        return {"success": True}
    
    try:
        result = db.execute_transaction(transfer_transaction)
        
        if "error" in result:
            await state.clear()
            return await message.answer(f"❌ {result['error']}")
        
        await message.answer(f"✅ Вы успешно перевели ***{amount}*** баллов пользователю с ID `{recipient_id}`.",
                           parse_mode="Markdown")
        try:
            await bot.send_message(recipient_id,
                                 f"🎉 Вам поступил перевод на ***{amount}*** баллов от пользователя `{sender_id}`.",
                                 parse_mode="Markdown")
        except:
            pass
        await state.clear()
    
    except Exception as e:
        logger.error(f"Error in transfer: {e}")
        await message.answer("❌ Произошла ошибка при переводе.")
        await state.clear()


def rating_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="🏆 Топ по рефералам", callback_data="rating_referrals")
    builder.button(text="💰 Топ по тратам", callback_data="rating_spent")
    builder.button(text="👑 Мой титул и награды", callback_data="rating_titles")
    builder.adjust(1)
    return builder.as_markup()


@dp.callback_query(F.data.startswith("rating_"))
async def rating_callback_handler(callback: types.CallbackQuery):
    action, cursor = callback.data.split("_")[1], db.conn.cursor()
    text, markup = "", rating_keyboard()
    if action == "referrals":
        cursor.execute(
            'SELECT username, referrals FROM users WHERE referrals > 0 ORDER BY referrals DESC LIMIT 10');
        text = "🏆 Топ-10 по рефералам:\n\n" + "\n".join(
            [f"{i}. @{u or 'Скрыт'} - {c} чел." for i, (u, c) in
             enumerate(cursor.fetchall(), 1)]) or "Пока никто не приглашал друзей."
    elif action == "spent":
        cursor.execute('SELECT username, total_spent FROM users WHERE total_spent > 0 ORDER BY total_spent DESC LIMIT 10')
        text = "💰 Топ-10 по тратам:\n\n" + "\n".join(
        [f"{i}. @{u or 'Скрыт'} - {s} баллов" for i, (u, s) in
        enumerate(cursor.fetchall(), 1)]) or "Пока никто не тратил баллы."
    elif action == "titles":
        user_id = callback.from_user.id;
        cursor.execute('SELECT title, total_spent FROM users WHERE user_id = ?', (user_id,));
        title, spent = cursor.fetchone()
        next_title_name, next_thresh = "Максимум", float('inf')
        for t, d in sorted(TITLES.items(), key=lambda i: i[1]['threshold']):
            if d['threshold'] > TITLES[title]['threshold']: next_title_name, next_thresh = t, d['threshold']; break
        text = f"👑 Ваш титул и прогресс:\n\nТекущий титул: {title}\nВсего потрачено: {spent} баллов\n\n"
        if next_title_name != "Максимум": text += f"До титула '{next_title_name}' осталось потратить {next_thresh - spent} баллов.\n\n"
        builder, has_rewards = InlineKeyboardBuilder(), False
        for t, d in TITLES.items():
            if spent >= d['threshold'] and d['reward'] > 0:
                cursor.execute('SELECT 1 FROM user_title_rewards WHERE user_id = ? AND title = ?', (user_id, t))
                if not cursor.fetchone(): builder.button(text=f"🎁 Забрать {d['reward']} баллов за '{t}'",
                                                         callback_data=f"claim_{t}"); has_rewards = True
        if has_rewards:
            text += "🎁 Доступные награды:";
            builder.row(
                InlineKeyboardButton(text="🔙 Назад", callback_data="rating_spent"));
            markup = builder.as_markup()
        else:
            text += "У вас нет доступных наград."
    await callback.message.edit_text(text, reply_markup=markup)


@dp.callback_query(F.data.startswith("claim_"))
@prevent_callback_spam("claim_")
async def claim_title_reward(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    title = callback.data.split("_")[1]
    reward = TITLES[title]['reward']
    
    def claim_reward_transaction(cursor):
        cursor.execute('INSERT OR IGNORE INTO user_title_rewards (user_id, title) VALUES (?, ?)', (user_id, title))
        
        if cursor.rowcount > 0:
            cursor.execute('UPDATE users SET balance = balance + ? WHERE user_id = ?', (reward, user_id))
            return {"success": True, "reward": reward}
        else:
            return {"error": "Вы уже получали эту награду."}
    
    try:
        result = db.execute_transaction(claim_reward_transaction)
        
        if "error" in result:
            await callback.answer(result["error"], show_alert=True)
        else:
            await callback.answer(f"✅ Вы получили {result['reward']} баллов!", show_alert=True)
        
        callback.data = "rating_titles"
        await rating_callback_handler(callback)
    
    except Exception as e:
        logger.error(f"Error claiming reward: {e}")
        await callback.answer("❌ Произошла ошибка.", show_alert=True)


@dp.message(F.text == "🔧 Админ панель", StateFilter("*"))
@dp.message(Command("admin"), StateFilter("*"))
async def admin_panel_handler(message: types.Message, state: FSMContext):
    await state.clear()
    if message.from_user.id not in ADMIN_IDS: return
    await message.answer("🔧 ***Админ-панель***", reply_markup=admin_panel_keyboard(), parse_mode="Markdown")


@dp.callback_query(F.data == "admin_panel")
async def admin_panel_callback_handler(callback: types.CallbackQuery):
    await callback.message.edit_text("🔧 ***Админ-панель***", reply_markup=admin_panel_keyboard(), parse_mode="Markdown")


@dp.callback_query(F.data == "admin_stats")
async def admin_stats_handler(callback: types.CallbackQuery):
    cursor = db.conn.cursor();
    cursor.execute(
        'SELECT COUNT(*), COUNT(CASE WHEN registered_at >= datetime("now", "-1 day") THEN 1 END) FROM users');
    total_users, new_users = cursor.fetchone()
    cursor.execute('SELECT COUNT(*), COUNT(CASE WHEN status = "active" THEN 1 END) FROM tasks');
    total_tasks, active_tasks = cursor.fetchone()
    api_balance = await boost_api.get_balance()
    await callback.message.edit_text(
        f"📊 ***Детальная статистика***\n\n💰 Баланс API: ***{api_balance}***\n\n👥 **Пользователи:***\n   - Всего: ***{total_users}***\n   - Новых за 24ч: ***{new_users}***\n\n📋 **Задания:***\n   - Всего создано: ***{total_tasks}***\n   - Активных: ***{active_tasks}***",
        reply_markup=admin_panel_keyboard(), parse_mode="Markdown")


@dp.callback_query(F.data == "admin_add_balance")
async def admin_add_balance_handler(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_text("👤 Введите ID пользователя:");
    await state.set_state(Form.waiting_for_admin_user_id)


@dp.message(Form.waiting_for_admin_user_id)
async def process_admin_user_id(message: types.Message, state: FSMContext):
    try:
        await state.update_data(target_user_id=int(message.text)); await message.answer(
            "💰 Введите сумму пополнения:"); await state.set_state(Form.waiting_for_admin_amount)
    except ValueError:
        await message.answer("❌ Неверный ID.")


@dp.message(Form.waiting_for_admin_amount)
async def process_admin_amount(message: types.Message, state: FSMContext):
    try:
        amount = int(message.text);
        target_user_id = (await state.get_data())['target_user_id']
        cursor = db.conn.cursor();
        cursor.execute('UPDATE users SET balance = balance + ? WHERE user_id = ?', (amount, target_user_id))
        if cursor.rowcount == 0: await state.clear(); return await message.answer("❌ Пользователь не найден.")
        db.conn.commit();
        await message.answer(f"✅ Баланс пользователя `{target_user_id}` пополнен на **{amount}** баллов.",
                             parse_mode="Markdown")
        try:
            await bot.send_message(target_user_id, f"🎉 Ваш баланс пополнен администратором на ***{amount}*** баллов!",parse_mode="Markdown")
        except:
            pass
    except ValueError:
        await message.answer("❌ Неверная сумма.")
    finally:
        await state.clear()


@dp.message(Command("create_promo"))
async def create_promo_command(message: types.Message):
    if message.from_user.id not in ADMIN_IDS: return
    try:
        _, code, reward, uses = message.text.split();
        cursor = db.conn.cursor()
        cursor.execute('INSERT INTO promocodes (code, reward, max_uses) VALUES (?, ?, ?)',
                       (code.upper(), int(reward), int(uses)));
        db.conn.commit()
        await message.answer(f"✅ Промокод `{code.upper()}` на ***{reward}*** баллов (***{uses}*** активаций) создан.",
                             parse_mode="Markdown")
    except:
        await message.answer("❌ Ошибка. Формат: `/create_promo КОД НАГРАДА ИСПОЛЬЗОВАНИЙ`")


@dp.callback_query(F.data == "admin_create_promo")
async def admin_create_promo_handler(callback: types.CallbackQuery):
    await callback.message.edit_text(
        "💎 ***Создание промокода***\n\nИспользуйте команду:\n`/create_promo <код> <награда> <использований>`\n\n***Пример:***\n`/create_promo BONUS100 100 50`",
        reply_markup=admin_panel_keyboard(), parse_mode="Markdown")


@dp.callback_query(F.data == "admin_manage_channels")
async def admin_manage_channels_handler(callback: types.CallbackQuery):
    await callback.message.edit_text("📺 Управление обязательными каналами:",
                                     reply_markup=channels_management_keyboard())


@dp.callback_query(F.data == "admin_show_channels")
async def admin_show_channels_handler(callback: types.CallbackQuery):
    text = "📋 ***Текущие обязательные каналы:***\n\n" + "\n".join(
        [f"***{i}. {ch['name']}*** ({ch['username']}) - ***{ch['reward']}*** баллов" for i, ch in
         enumerate(load_channels_from_db(), 1)]) or "Каналы не настроены."
    await callback.message.edit_text(text, reply_markup=channels_management_keyboard(), parse_mode="Markdown")


@dp.callback_query(F.data == "admin_add_channel")
async def admin_add_channel_handler(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_text("📝 Введите название канала (например, 'Наш новостной канал'):");
    await state.set_state(Form.waiting_for_channel_name)


@dp.message(Form.waiting_for_channel_name)
async def process_channel_name(message: types.Message, state: FSMContext):
    await state.update_data(channel_name=message.text);
    await message.answer("👤 Введите username канала (например, @durov):");
    await state.set_state(Form.waiting_for_channel_username)


@dp.message(Form.waiting_for_channel_username)
async def process_channel_username(message: types.Message, state: FSMContext):
    if not message.text.startswith('@'): return await message.answer("❌ Username должен начинаться с @")
    await state.update_data(channel_username=message.text);
    await message.answer("💰 Введите награду за подписку (например, 500):");
    await state.set_state(Form.waiting_for_channel_reward)


@dp.message(Form.waiting_for_channel_reward)
async def process_channel_reward(message: types.Message, state: FSMContext):
    try:
        reward = int(message.text);
        data = await state.get_data();
        cursor = db.conn.cursor()
        cursor.execute('INSERT INTO required_channels (name, username, reward) VALUES (?, ?, ?)',
                       (data['channel_name'], data['channel_username'], reward));
        db.conn.commit()
        await message.answer("✅ Канал успешно добавлен!")
    except ValueError:
        await message.answer("❌ Введите число.")
    except sqlite3.IntegrityError:
        await message.answer("❌ Канал с таким username уже существует.")
    finally:
        await state.clear()


@dp.callback_query(F.data == "admin_delete_channel")
async def admin_delete_channel_handler(callback: types.CallbackQuery, state: FSMContext):
    channels = load_channels_from_db()
    if not channels: return await callback.answer("Нет каналов для удаления.", show_alert=True)
    text = "🗑 ***Выберите канал для удаления (введите номер):***\n\n" + "\n".join(
        [f"***{i}.*** {ch['name']} ({ch['username']})" for i, ch in enumerate(channels, 1)])
    await callback.message.edit_text(text, parse_mode="Markdown");
    await state.set_state(Form.waiting_for_channel_delete)


@dp.message(Form.waiting_for_channel_delete)
async def process_channel_delete(message: types.Message, state: FSMContext):
    try:
        num = int(message.text);
        channels = load_channels_from_db()
        if 1 <= num <= len(channels):
            channel_to_delete = channels[num - 1];
            cursor = db.conn.cursor()
            cursor.execute('DELETE FROM required_channels WHERE username = ?', (channel_to_delete['username'],));
            db.conn.commit()
            await message.answer(f"✅ Канал '{channel_to_delete['name']}' удален!")
        else:
            await message.answer("❌ Неверный номер.")
    except ValueError:
        await message.answer("❌ Введите число.")
    finally:
        await state.clear()
class AdminStates(StatesGroup):
    waiting_for_mailing_message = State()
    waiting_for_button_text = State()
    waiting_for_button_url = State()
    waiting_for_mailing_photo = State()
    
@dp.callback_query(F.data == "admin_rasilka")
async def admin_rasilka_handler(query: types.CallbackQuery, state: FSMContext):
    if query.from_user.id not in ADMIN_IDS: return
    await query.message.edit_text("📢 Введите текст рассылки\n\n/exit для отмены")
    await state.set_state(AdminStates.waiting_for_mailing_message)
    
@dp.message(AdminStates.waiting_for_mailing_message)
async def process_broadcast_message(message: types.Message, state: FSMContext):
    if message.text == "/exit":
        await message.answer("❌ Рассылка отменена.")
        await state.clear()
        return
    
    await state.update_data(broadcast_text=message.text)
    await message.answer("🖼 Отправьте фото для рассылки (или /skip для пропуска)")
    await state.set_state(AdminStates.waiting_for_mailing_photo)

@dp.message(AdminStates.waiting_for_mailing_photo)
async def process_mailing_photo(message: types.Message, state: FSMContext):
    if message.text == "/skip":
        await message.answer("📝 Введите текст кнопки (например, '🔗 Перейти в канал')\n\n/skip для пропуска")
        await state.set_state(AdminStates.waiting_for_button_text)
        return
    
    if message.photo:
        photo_file_id = message.photo[-1].file_id
        await state.update_data(photo_file_id=photo_file_id)
        await message.answer("📝 Введите текст кнопки (например, '🔗 Перейти в канал')\n\n/skip для пропуска")
        await state.set_state(AdminStates.waiting_for_button_text)
    else:
        await message.answer("❌ Пожалуйста, отправьте фото или /skip для пропуска")

@dp.message(AdminStates.waiting_for_button_text)
async def process_button_text(message: types.Message, state: FSMContext):
    if message.text == "/skip":
        data = await state.get_data()
        broadcast_text = data['broadcast_text']
        photo_file_id = data.get('photo_file_id')
        await send_broadcast(message, broadcast_text, None, None, photo_file_id)
        await state.clear()
        return
    
    await state.update_data(button_text=message.text)
    await message.answer("🔗 Введите URL ссылки (например, https://t.me/your_channel)")
    await state.set_state(AdminStates.waiting_for_button_url)

@dp.message(AdminStates.waiting_for_button_url)
async def process_button_url(message: types.Message, state: FSMContext):
    data = await state.get_data()
    broadcast_text = data['broadcast_text']
    button_text = data['button_text']
    button_url = message.text
    photo_file_id = data.get('photo_file_id')
    
    await send_broadcast(message, broadcast_text, button_text, button_url, photo_file_id)
    await state.clear()

async def send_broadcast(message: types.Message, text: str, button_text: str = None, button_url: str = None, photo_file_id: str = None):
    cursor = db.conn.cursor()
    cursor.execute('SELECT user_id FROM users')
    users = cursor.fetchall()
    
    markup = None
    if button_text and button_url:
        markup = InlineKeyboardMarkup(
            inline_keyboard=[[
                InlineKeyboardButton(text=button_text, url=button_url)
            ]]
        )
    
    await message.answer(f"📢 Рассылка начата! Сообщение будет отправлено {len(users)} пользователям.")
    
    success_count = 0
    fail_count = 0
    
    for (user_id,) in users:
        try:
            if photo_file_id:
                await bot.send_photo(
                    user_id, 
                    photo=photo_file_id, 
                    caption=text, 
                    reply_markup=markup, 
                    parse_mode="Markdown"
                )
            else:
                await bot.send_message(user_id, text, reply_markup=markup, parse_mode="Markdown")
            success_count += 1
            await asyncio.sleep(0.05)
        except Exception as e:
            logger.error(f"Failed to send broadcast to {user_id}: {e}")
            fail_count += 1
    
    await message.answer(
        f"📢 ***Рассылка завершена!***\n✅ Успешно: {success_count}\n❌ Не удалось: {fail_count}",
        parse_mode="Markdown"
    )
    

@dp.message(F.text == "🎁 Бонусы", StateFilter("*"))
async def bonuses_handler(message: types.Message, state: FSMContext):
    await state.clear()
    builder = InlineKeyboardBuilder()
    builder.button(text="🎁 Ежедневный бонус", callback_data="bonus_daily")
    builder.adjust(1)
    
    await message.answer("🎁 ***Выберите бонус:***", reply_markup=builder.as_markup(), parse_mode="Markdown")


@dp.message(F.text == "⚡ Меню", StateFilter("*"))
async def menu_handler(message: types.Message, state: FSMContext):
    await state.clear()
    builder = InlineKeyboardBuilder()
    builder.button(text="💰 Тарифы на услуги", callback_data="menu_tariffs")
    builder.button(text="🎁 Рефералы", callback_data="menu_referrals")
    builder.button(text="💎 Промокод", callback_data="menu_promo")
    builder.button(text="🏆 Рейтинг", callback_data="menu_rating")
    builder.button(text="💸 Перевести баллы", callback_data="menu_transfer")
    builder.button(text="🎰 Казино", callback_data="bonus_casino")
    builder.adjust(2)
    
    await message.answer("📋 ***Дополнительное меню:***", reply_markup=builder.as_markup(), parse_mode="Markdown")


@dp.callback_query(F.data == "menu_tariffs")
async def menu_tariffs_handler(callback: types.CallbackQuery):
    cursor = db.conn.cursor()
    cursor.execute('SELECT balance FROM users WHERE user_id = ?', (callback.from_user.id,))
    balance = cursor.fetchone()[0]
    text = (
        f"💰 Ваш баланс: {balance} баллов\n\n"
        f"📊 ***Тарифы на услуги:***\n\n"
        f"📱 ***Telegram:***\n"
        f"• Подписчики — {PRICES['telegram_members']} баллов\n"
        f"• Реакции — {PRICES['telegram_reactions']} баллов\n"
        f"• Просмотры — {PRICES['telegram_views']} балла\n\n"
        f"🎭 ***VK:***\n"
        f"• Просмотры на пост — {PRICES['vk_post_views']} балла\n"
        f"• Просмотры на видео — {PRICES['vk_video_views']} баллов\n"
        f"• Лайки — {PRICES['vk_likes']} баллов\n\n"
        f"🎵 ***TikTok:***\n"
        f"• Просмотры — {PRICES['tiktok_views']} баллов\n"
        f"• Лайки — {PRICES['tiktok_likes']} баллов\n\n"
        f"📷 ***Instagram:***\n"
        f"• Лайки — {PRICES['instagram_likes']} баллов\n"
        f"• Просмотры — {PRICES['instagram_views']} балла\n\n"
        f"📺 ***YouTube:***\n"
        f"• Подписчики — {PRICES['youtube_subscribers']} баллов\n"
        f"• Лайки — {PRICES['youtube_likes']} баллов\n"
        f"• Просмотры — {PRICES['youtube_views']} баллов\n\n"
        f"👑 ***Elite подписчики (с гарантией 365 дней):***\n"
        f"• Цена — {PRICES['telegram_members_elite']} баллов\n\n"
        f"⚠️ *Проект не несет ответственность за отписки обычных подписчиков*"
    )
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")]]
    ))


@dp.callback_query(F.data == "menu_referrals")
async def menu_referrals_handler(callback: types.CallbackQuery):
    user_id, cursor = callback.from_user.id, db.conn.cursor()
    cursor.execute('SELECT referrals FROM users WHERE user_id = ?', (user_id,))
    count = cursor.fetchone()[0]
    bot_username = (await bot.get_me()).username
    text = (
        f"🎁 ***Реферальная программа***\n\n"
        f"👥 Приглашено: ***{count}*** человек\n"
        f"💰 Заработано: ***{count * 7500}*** баллов\n\n"
        f"🔗 Ваша реферальная ссылка:\n"
        f"`https://t.me/{bot_username}?start=ref{user_id}`\n\n"
        f"🎯 ***Условия:***\n"
        f"• Вы получаете ***7500*** баллов\n"
        f"• Ваш друг получает ***1000*** баллов при регистрации\n\n"
        f"📢 *Бонус начисляется после того, как ваш друг подпишется на все обязательные каналы.*"
    )
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")]]
    ))


@dp.callback_query(F.data == "menu_promo")
async def menu_promo_handler(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_text("🔤 Введите промокод:", reply_markup=InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")]]
    ))
    await state.set_state(Form.waiting_for_promo_code)


@dp.callback_query(F.data == "menu_rating")
async def menu_rating_handler(callback: types.CallbackQuery):
    await callback.message.edit_text("🏆 Выберите категорию рейтинга:", reply_markup=rating_keyboard())


@dp.callback_query(F.data == "menu_transfer")
async def menu_transfer_handler(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_text("Введите ID пользователя, которому хотите перевести баллы:", reply_markup=InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")]]
    ))
    await state.set_state(Form.waiting_for_recipient_id)


@dp.callback_query(F.data == "back_to_menu")
async def back_to_menu_handler(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    builder = InlineKeyboardBuilder()
    builder.button(text="💰 Тарифы на услуги", callback_data="menu_tariffs")
    builder.button(text="🎁 Рефералы", callback_data="menu_referrals")
    builder.button(text="💎 Промокод", callback_data="menu_promo")
    builder.button(text="🏆 Рейтинг", callback_data="menu_rating")
    builder.button(text="💸 Перевести баллы", callback_data="menu_transfer")
    builder.button(text="🎰 Казино", callback_data="bonus_casino")
    builder.adjust(2)
    
    await callback.message.edit_text("📋 ***Дополнительное меню:***", reply_markup=builder.as_markup(), parse_mode="Markdown")


@dp.callback_query(F.data == "bonus_daily")
async def bonus_daily_handler(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    cursor = db.conn.cursor()
    cursor.execute('SELECT last_bonus_claim FROM users WHERE user_id = ?', (user_id,))
    last_claim_str = cursor.fetchone()[0]
    now = datetime.now()

    if last_claim_str:
        last_claim = datetime.fromisoformat(last_claim_str)
        if (now - last_claim) < timedelta(hours=24):
            time_left = timedelta(hours=24) - (now - last_claim)
            hours, rem = divmod(time_left.seconds, 3600)
            minutes, _ = divmod(rem, 60)
            await callback.answer(f"❌ Следующий бонус будет доступен через {hours} ч. {minutes} мин.", show_alert=True)
            return

    bonus = 800
    cursor.execute('UPDATE users SET balance = balance + ?, last_bonus_claim = ? WHERE user_id = ?', (bonus, now.isoformat(), user_id))
    db.conn.commit()
    
    await callback.answer(f"🎉 Вы получили ежедневный бонус: {bonus} баллов!", show_alert=True)


@dp.callback_query(F.data == "bonus_casino")
async def bonus_casino_handler(callback: types.CallbackQuery, state: FSMContext):
    cursor = db.conn.cursor()
    cursor.execute('SELECT balance FROM users WHERE user_id = ?', (callback.from_user.id,))
    balance = cursor.fetchone()[0]
    
    text = (
        f"🎰 Добро пожаловать в казино!\n"
        f"Ваш баланс: ***{balance}*** баллов.\n\n"
        f"***Возможные множители:***\n"
        f"`x0` | `x1` | `x2` | `x2.5`\n\n"
        f"Введите сумму ставки:"
    )
    
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_bonuses")]]
    ))
    await state.set_state(Form.waiting_for_bet)


@dp.callback_query(F.data == "back_to_bonuses")
async def back_to_bonuses_handler(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    builder = InlineKeyboardBuilder()
    builder.button(text="🎁 Ежедневный бонус", callback_data="bonus_daily")
    builder.adjust(1)
    
    await callback.message.edit_text("🎁 ***Выберите бонус:***", reply_markup=builder.as_markup(), parse_mode="Markdown")


@dp.callback_query(F.data == "buy_elite_from_profile")
async def buy_elite_from_profile_handler(callback: types.CallbackQuery):
    photo_path = "assets/Элита.jpg"
    caption = (
        "💎 ***Elite Подписка (30 дней)***\n\n"
        "Получите доступ к эксклюзивным возможностям!\n\n"
        "***Преимущества:***\n"
        "⭐ Доступ к раскрутке ***Telegram подписчиков с гарантией 365 дней*** от отписок.\n\n"
        "***Стоимость:***\n"
        "- `25,000` внутриигровых баллов\n"
        "- `20` Telegram Stars (⭐)"
    )
    
    await callback.message.answer_photo(
        photo=types.FSInputFile(photo_path), 
        caption=caption,
        parse_mode="Markdown",
        reply_markup=elite_sub_keyboard()
    )


@dp.callback_query(F.data == "buy_balance_from_profile")
async def buy_balance_from_profile_handler(callback: types.CallbackQuery):
    photo_path = "assets/Купить Звезды.png"
    caption = "💳 Выберите способ пополнения баланса:"
    
    await callback.message.answer_photo(
        photo=types.FSInputFile(photo_path), 
        caption=caption,
        reply_markup=payment_choice_keyboard()
    )


async def status_checker():
    while True:
        await asyncio.sleep(300)
        cursor = db.conn.cursor()
        cursor.execute("SELECT task_id, api_order_id FROM tasks WHERE status = 'active'")
        for task_id, order_id in cursor.fetchall():
            try:
                status_result = await boost_api.get_order_status(order_id)
                if "error" not in status_result:
                    api_status = status_result.get("status", "active").lower()
                    if api_status in ["completed", "partial", "canceled"]:
                        db.conn.execute("UPDATE tasks SET status = ? WHERE task_id = ?", (api_status, task_id));
                        db.conn.commit()
            except Exception as e:
                logger.error(f"Status check error for order {order_id}: {e}")


async def main():
    await boost_api.create_session()
    asyncio.create_task(status_checker())
    asyncio.create_task(check_crypto_invoices())
    try:
        logger.info("Бот запускается...")
        await dp.start_polling(bot)
    finally:
        await boost_api.close_session()
        db.conn.close()


if __name__ == "__main__":
    asyncio.run(main())
