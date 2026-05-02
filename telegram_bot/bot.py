import os
import logging
import asyncio
import inspect
import requests
from datetime import datetime, timedelta
import httpx
import time
import tempfile
from io import BytesIO
import json
from telegram.error import TimedOut, NetworkError
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton, InputFile
from telegram.constants import ChatAction
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, PicklePersistence
from telegram.request import HTTPXRequest
from dotenv import load_dotenv
import aiohttp

try:
    from telegram.ext import JobQueue
except Exception:
    JobQueue = None

# Load environment variables from the parent directory (.env)
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env'))

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Set debug level for duplicate click detection
logging.getLogger(__name__).setLevel(logging.DEBUG)

# Configuration
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
DJANGO_API_BASE_URL = os.getenv('DJANGO_API_BASE_URL', 'http://localhost:8000/api')
BOT_API_KEY = os.getenv('BOT_API_KEY', '')
NOTIFICATIONS_POLL_INTERVAL_SEC = int(os.getenv('NOTIFICATIONS_POLL_INTERVAL_SEC', '5'))

BOT_HEADERS = {'Authorization': f'Bearer {BOT_API_KEY}'} if BOT_API_KEY else {}

# Global semaphore to limit concurrent file downloads/sends
DOWNLOAD_CONCURRENCY = int(os.getenv('DOWNLOAD_CONCURRENCY', '20'))
download_semaphore = asyncio.Semaphore(DOWNLOAD_CONCURRENCY)

class CourseBot:
    def __init__(self):
        self.api_base_url = DJANGO_API_BASE_URL.rstrip('/')
        # Cache for menus
        self._cache = {}
        self._cache_ttl = 300  # 5 minutes cache
        self._session = None # aiohttp session
        
    async def _get_session(self):
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(headers=BOT_HEADERS, timeout=aiohttp.ClientTimeout(total=15))
        return self._session

    async def _async_get_json(self, url, params=None):
        session = await self._get_session()
        try:
            async with session.get(url, params=params) as resp:
                resp.raise_for_status()
                return await resp.json()
        except Exception as e:
            logger.error(f"Async GET failed for {url}: {e}")
            raise
        
    # ----- User visit helpers -----
    def _get_last_visit(self, telegram_user_id: int):
        try:
            resp = requests.get(
                f"{self.api_base_url}/bot/users/last-visit/",
                params={'telegram_user_id': telegram_user_id},
                headers=BOT_HEADERS,
                timeout=10
            )
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            data = resp.json()
            return data
        except Exception as e:
            logger.error(f"Error getting last visit: {e}")
            return None

    def _record_visit(self, telegram_user_id: int, username: str):
        try:
            requests.post(
                f"{self.api_base_url}/bot/users/visit/",
                json={'telegram_user_id': telegram_user_id, 'username': username},
                headers=BOT_HEADERS,
                timeout=10
            )
        except Exception as e:
            logger.error(f"Error recording visit for {telegram_user_id}: {e}")

    def _get_greeting(self, name: str = "") -> str:
        """Return a time-appropriate Arabic greeting."""
        hour = datetime.now().hour
        if 5 <= hour < 12:
            # صباح
            options = [
                f"🌞 صباح الخير يا {name}",
                f"☀️ يسعد صباحك يا {name}",
                f"🌹 صباحك ورد يا {name}",
            ]
        elif 12 <= hour < 17:
            # ظهر
            options = [
                f"🌞 مساء الخير يا {name}",
                f"☀️ خير المساء يا {name}",
            ]
        else:
            # مساء / ليل
            options = [
                f"🌙 مساء النور يا {name}",
                f"✨ مساء الفل يا {name}",
            ]
        import random
        return random.choice(options)

    def _normalize_label(self, text: str) -> str:
        """Normalize labels by stripping leading emojis/symbols and extra spaces."""
        if not isinstance(text, str):
            return ""
        # Remove leading non-letter/digit (including emojis), then collapse spaces
        i = 0
        while i < len(text) and not (text[i].isalnum() or ('\u0600' <= text[i] <= '\u06FF')):
            i += 1
        normalized = text[i:].strip()
        return " ".join(normalized.split())
        
    def _get_json_with_retries(self, url, params=None, max_retries=3, timeout=30):
        """Fetch JSON from backend with retries and a longer timeout."""
        attempt = 0
        while True:
            try:
                resp = requests.get(url, params=params, headers=BOT_HEADERS, timeout=timeout)
                resp.raise_for_status()
                return resp.json()
            except (requests.exceptions.Timeout, httpx.ConnectTimeout, requests.exceptions.ConnectionError) as e:
                attempt += 1
                if attempt >= max_retries:
                    raise
                time.sleep(2)
            except Exception:
                # Non-timeout errors also retry up to max_retries
                attempt += 1
                if attempt >= max_retries:
                    raise
                time.sleep(2)
        
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Start command handler"""
        user_id = update.effective_user.id
        user_name = (update.effective_user.first_name or update.effective_user.username or "صديقي").strip()
        SEP = "─" * 20

        # Fetch last visit info (non-blocking to thread)
        last_visit_data = await asyncio.to_thread(self._get_last_visit, user_id)

        greeting_sent = False
        if not last_visit_data:
            # ► First time user — warm welcome
            greeting = self._get_greeting(user_name)
            welcome = (
                f"{greeting}\n\n"
                f"👋 أهلاً وسهلاً بك في بوت\n"
                f"🏫 المعهد التقاني لتقنيات الحاسوب\n\n"
                f"تستطيع من خلاله تصفح وتحميل موادك الدراسية بسهولة.\n"
                f"اشترك في قسمك الدراسي لتصلك إشعارات بجميع المواد الجديدة أولاً بأول.\n\n"
                f"👨‍💻 فريق التطوير: MS Developer"
            )
            await update.message.reply_text(welcome)
            greeting_sent = True
        else:
            try:
                last_str = last_visit_data.get('last_visit')
                if last_str:
                    last_dt = datetime.fromisoformat(last_str.replace('Z', '+00:00')).astimezone()
                    days_away = (datetime.now().astimezone() - last_dt).days
                    if days_away >= 2:
                        # ► Returning user after absence
                        greeting = self._get_greeting(user_name)
                        msg = (
                            f"{greeting}\n\n"
                            f"🥳 سعدين بعودتك، {user_name}!"
                            + (f" لقد غبت {days_away} يوماً!" if days_away < 30 else "")
                            + f"\nتفضل، في موادك تنتظرك."
                        )
                        await update.message.reply_text(msg)
                        greeting_sent = True
                    elif days_away == 0:
                        # Daily visit, just a light greeting
                        greeting = self._get_greeting(user_name)
                        await update.message.reply_text(f"{greeting}")
                        greeting_sent = True
            except Exception:
                pass

        # Record this visit (fire and forget)
        asyncio.create_task(asyncio.to_thread(self._record_visit, user_id, user_name))
        # Ensure clean state on /start
        context.user_data.update({
            'telegram_user_id': user_id,
            'department_id': None,
            'study_year_id': None,
            'semester_id': None,
            'course_type_id': None,
            'course_id': None,
            'current_step': 'department',
            'options_map': {}
            # Purged 'file_metadata' definition from global user state
        })

        keyboard = await self.build_departments_keyboard(context.user_data)
        if keyboard is None:
            await update.message.reply_text("❌ تعذّر الاتصال بالخادم، حاول لاحقًا.")
        else:
            if not greeting_sent:
                prompt = (
                    f"🎓 أهلاً {user_name}!\n"
                    f"اختر قسمك للبدء:"
                )
                await update.message.reply_text(prompt, reply_markup=keyboard)
            else:
                await update.message.reply_text("لنبدأ باختيار القسم.", reply_markup=keyboard)
    
    def build_base_controls(self):
        return [
            [KeyboardButton("رجوع"), KeyboardButton("🔔 الإشعارات والاشتراك")],
            [KeyboardButton("🏠 ابدأ من جديد"), KeyboardButton("❓ مساعدة")]
        ]

    def make_reply_keyboard(self, labels):
        # Arrange buttons in rows of 2 for readability
        rows = []
        row = []
        for label in labels:
            row.append(KeyboardButton(label))
            if len(row) == 2:
                rows.append(row)
                row = []
        if row:
            rows.append(row)
        rows.extend(self.build_base_controls())
        return ReplyKeyboardMarkup(rows, resize_keyboard=True)

    async def build_subs_menu_keyboard(self, user_id):
        try:
            base = self.api_base_url.rstrip('/')
            url = f"{base}/bot/subscriptions/"
            subs = await self._async_get_json(url, params={'telegram_user_id': user_id})
        except Exception as e:
            logger.error(f"Error fetching subs: {e}")
            subs = []
            
        has_subs = bool(subs)
        buttons = []
        if has_subs:
            # If the user has subscribed, offer the option to unsubscribe
            buttons.append([KeyboardButton("❌ إلغاء / Unsubscribe")])
        else:
            # If the user hasn't subscribed, offer the option to subscribe
            buttons.append([KeyboardButton("✅ اشتراك / Subscribe")])
            
        buttons.extend(self.build_base_controls())
        return ReplyKeyboardMarkup(buttons, resize_keyboard=True)
    
    async def build_departments_keyboard(self, user_data):
        """Fetch departments and build a ReplyKeyboard; store label->id mapping."""
        # Use simple caching to avoid slow HTTP requests for static data
        cache_key = 'departments'
        now = time.time()
        
        if cache_key in self._cache and now - self._cache[cache_key]['ts'] < self._cache_ttl:
            departments = self._cache[cache_key]['data']
        else:
            try:
                departments = await self._async_get_json(f"{self.api_base_url}/bot/departments/")
                self._cache[cache_key] = {'ts': now, 'data': departments}
            except Exception as e:
                logger.error(f"Error fetching departments: {e}")
                return None

        labels = []
        options_map = {}
        for dept in departments:
            label = f"🏫 {dept['name']}"
            labels.append(label)
            options_map[label] = dept['id']

        user_data.setdefault('options_map', {})['department'] = options_map
        return self.make_reply_keyboard(labels)
    
    async def build_years_keyboard(self, user_data):
        cache_key = 'years'
        now = time.time()
        
        if cache_key in self._cache and now - self._cache[cache_key]['ts'] < self._cache_ttl:
            years = self._cache[cache_key]['data']
        else:
            try:
                years = await self._async_get_json(f"{self.api_base_url}/bot/study-years/")
                self._cache[cache_key] = {'ts': now, 'data': years}
            except Exception as e:
                logger.error(f"Error fetching study years: {e}")
                return None

        labels = []
        options_map = {}
        for year in years:
            label = f"📚 السنة {year['year']}"
            labels.append(label)
            options_map[label] = year['id']

        user_data.setdefault('options_map', {})['year'] = options_map
        return self.make_reply_keyboard(labels)
    
    async def build_semesters_keyboard(self, user_data):
        cache_key = 'semesters'
        now = time.time()
        
        if cache_key in self._cache and now - self._cache[cache_key]['ts'] < self._cache_ttl:
            semesters = self._cache[cache_key]['data']
        else:
            try:
                semesters = await self._async_get_json(f"{self.api_base_url}/bot/semesters/")
                self._cache[cache_key] = {'ts': now, 'data': semesters}
            except Exception as e:
                logger.error(f"Error fetching semesters: {e}")
                return None
            
        labels = []
        options_map = {}
        for sem in semesters:
            label = f"📅 {sem['name']}"
            labels.append(label)
            options_map[label] = sem['id']

        user_data.setdefault('options_map', {})['semester'] = options_map
        return self.make_reply_keyboard(labels)
    
    # course_types_keyboard removed as it is bypassed
    
    async def build_courses_keyboard(self, user_data):
        try:
            params = {
                'department_id': user_data.get('department_id'),
                'study_year_id': user_data.get('study_year_id'),
                'semester_id': user_data.get('semester_id'),
                'course_type_id': user_data.get('course_type_id')
            }
            # aiohttp does not allow None values in query params
            params = {k: v for k, v in params.items() if v is not None}
            
            courses = await self._async_get_json(f"{self.api_base_url}/bot/courses/", params)
            
            labels = []
            options_map = {}
            for course in courses:
                files_count = course.get('files_count', 0)
                label = f"📘 {course['name']} ({files_count})"
                labels.append(label)
                options_map[label] = course['id']

            user_data.setdefault('options_map', {})['course'] = options_map
            return self.make_reply_keyboard(labels)
        except Exception as e:
            logger.error(f"Error fetching courses: {e}")
            return None
    
    async def build_files_keyboard(self, user_data, course_id):
        try:
            files = await self._async_get_json(f"{self.api_base_url}/bot/courses/{course_id}/files/")
            
            labels = []
            options_map = {}
            for f in files:
                file_size = f.get('file_size', 0)
                size_mb = round(file_size / (1024 * 1024), 2) if file_size > 0 else 0
                label = f"📄 {f['original_filename']} ({size_mb} م.ب)"
                # Telegram limits button text length; keep as-is for now
                labels.append(label)
                options_map[label] = f['id']

            user_data.setdefault('options_map', {})['file'] = options_map
            # Purge legacy file metadata to save disk and RAM in pickle persistent storage
            if 'file_metadata' in user_data:
                del user_data['file_metadata']
            # Migrate to global memory cache
            self._cache.setdefault('file_metadata', {})[course_id] = { f['id']: f for f in files }
            
            # Add a Back row on top of base controls
            keyboard = self.make_reply_keyboard(labels)
            return keyboard
        except Exception as e:
            logger.error(f"Error fetching files: {e}")
            return None
    
    async def handle_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle all text messages and drive navigation via ReplyKeyboard buttons."""
        user_id = update.effective_user.id
        text = (update.message.text or '').strip()

        # Ensure state exists (by relying on start logic or context initialization)
        if 'department_id' not in context.user_data:
            await self.start(update, context)
            return
        
        state = context.user_data
        if 'telegram_user_id' not in state:
            state['telegram_user_id'] = user_id

        # Global controls
        if text == "🏠 ابدأ من جديد":
            context.user_data.update({
                'department_id': None,
                'study_year_id': None,
                'semester_id': None,
                'course_type_id': None,
                'course_id': None,
                'current_step': 'department',
                'options_map': {}
            })
            keyboard = await self.build_departments_keyboard(context.user_data)
            if keyboard is None:
                await update.message.reply_text("❌ لم يتمكن البوت من الاتصال بالسيرفر، حاول لاحقًا.")
            else:
                await update.message.reply_text("لنبدأ من جديد. اختر القسم:", reply_markup=keyboard)
            return
        
        # Global back button
        if text == "رجوع":
            step = state.get('current_step', 'department')
            # Simple step back logic
            # If already at top-level department menu, stay there and re-show it
            if step == 'department':
                state['current_step'] = 'department'
                kb = await self.build_departments_keyboard(context.user_data)
                if kb is None:
                    await update.message.reply_text("❌ لم يتمكن البوت من الاتصال بالسيرفر، حاول لاحقًا.")
                else:
                    await update.message.reply_text("🏫 اختر القسم:", reply_markup=kb)
                return
            # If in subscriptions department selection, go back to subscriptions menu
            if step == 'subs_department':
                state['current_step'] = 'subs_menu'
                kb = await self.build_subs_menu_keyboard(user_id)
                await update.message.reply_text("🔔 Subscription menu:", reply_markup=kb)
                return
            if step in ('year', 'subs_year'):
                state['current_step'] = 'department' if step == 'year' else 'subs_department'
                kb = await self.build_departments_keyboard(context.user_data)
                if kb is None:
                    await update.message.reply_text("❌ لم يتمكن البوت من الاتصال بالسيرفر، حاول لاحقًا.")
                else:
                    await update.message.reply_text("🏫 اختر القسم:", reply_markup=kb)
                return
            if step in ('semester', 'subs_semester'):
                state['current_step'] = 'year' if step == 'semester' else 'subs_year'
                kb = await self.build_years_keyboard(context.user_data)
                if kb is None:
                    await update.message.reply_text("❌ لم يتمكن البوت من الاتصال بالسيرفر، حاول لاحقًا.")
                else:
                    await update.message.reply_text("📚 اختر السنة الدراسية:", reply_markup=kb)
                return
            if step == 'course_type':
                state['current_step'] = 'semester'
                kb = await self.build_semesters_keyboard(context.user_data)
                if kb is None:
                    await update.message.reply_text("❌ لم يتمكن البوت من الاتصال بالسيرفر، حاول لاحقًا.")
                else:
                    await update.message.reply_text("📅 اختر الفصل الدراسي:", reply_markup=kb)
                return
            if step == 'course':
                state['current_step'] = 'semester'
                kb = await self.build_semesters_keyboard(context.user_data)
                if kb is None:
                    await update.message.reply_text("❌ لم يتمكن البوت من الاتصال بالسيرفر، حاول لاحقًا.")
                else:
                    await update.message.reply_text("📅 اختر الفصل الدراسي:", reply_markup=kb)
                return
            if step == 'file':
                state['current_step'] = 'course'
                kb = await self.build_courses_keyboard(context.user_data)
                if kb is None:
                    await update.message.reply_text("❌ لم يتمكن البوت من الاتصال بالسيرفر، حاول لاحقًا.")
                else:
                    await update.message.reply_text("📋 اختر المقرر:", reply_markup=kb)
                return
            if step in ('subs_menu', 'subs_unsubscribe'):
                state['current_step'] = 'department'
                kb = await self.build_departments_keyboard(context.user_data)
                if kb is None:
                    await update.message.reply_text("❌ لم يتمكن البوت من الاتصال بالسيرفر، حاول لاحقًا.")
                else:
                    await update.message.reply_text("🔙 عدنا للقائمة الرئيسية. اختر القسم:", reply_markup=kb)
                return
        
        if text == "❓ مساعدة":
            await self.help_command(update, context)
            return
        if text == "🔔 الإشعارات والاشتراك":
            await update.message.reply_chat_action(ChatAction.TYPING)
            state['current_step'] = 'subs_menu'
            keyboard = await self.build_subs_menu_keyboard(update.effective_user.id)
            await update.message.reply_text("🔔 قائمة الإشعارات والاشتراكات:", reply_markup=keyboard)
            return

        step = state.get('current_step', 'department')

        # Helper to validate choice and move step
        async def handle_choice(step_key, next_step, builder_fn, prompt):
            options = state['options_map'].get(step_key, {})
            chosen_id = None
            if text in options:
                chosen_id = options[text]
            else:
                # Try normalized match to tolerate emoji/spacing differences
                normalized_text = self._normalize_label(text)
                for label, opt_id in options.items():
                    if self._normalize_label(label) == normalized_text:
                        chosen_id = opt_id
                        break
                if chosen_id is None:
                    # Re-show the intended prompt with keyboard only (no extra warning message)
                    keyboard = await builder_fn(context.user_data)
                    if keyboard is None:
                        await update.message.reply_text("❌ لم يتمكن البوت من الاتصال بالسيرفر، حاول لاحقًا.")
                    else:
                        await update.message.reply_text(prompt, reply_markup=keyboard)
                    return
            if step_key == 'department':
                state['department_id'] = chosen_id
            elif step_key == 'year':
                state['study_year_id'] = chosen_id
            elif step_key == 'semester':
                state['semester_id'] = chosen_id
            elif step_key == 'course_type':
                state['course_type_id'] = chosen_id
            elif step_key == 'course':
                state['course_id'] = chosen_id

            state['current_step'] = next_step
            keyboard = await builder_fn(context.user_data)
            if keyboard is None:
                await update.message.reply_text("❌ لم يتمكن البوت من الاتصال بالسيرفر، حاول لاحقًا.")
            else:
                await update.message.reply_text(prompt, reply_markup=keyboard)

        if step == 'department':
            await handle_choice('department', 'year', self.build_years_keyboard, "📚 الآن اختر السنة الدراسية:")
            return
        if step == 'year':
            await handle_choice('year', 'semester', self.build_semesters_keyboard, "📅 الآن اختر الفصل الدراسي:")
            return
        if step == 'semester':
            # Bypass course_type and go straight to course selection
            state['course_type_id'] = None # Clear this since we are bypassing
            await handle_choice('semester', 'course', self.build_courses_keyboard, "📋 الآن اختر المقرر:")
            return
        if step == 'subs_menu':
            if text == "✅ اشتراك / Subscribe":
                # init temporary selection
                state['subs_selection'] = {'department_id': None, 'year_id': None, 'semester_id': None}
                state['current_step'] = 'subs_department'
                kb = await self.build_departments_keyboard(context.user_data)
                if kb is None:
                    await update.message.reply_text("❌ لم يتمكن البوت من الاتصال بالسيرفر، حاول لاحقًا.")
                else:
                    await update.message.reply_text("🏫 اختر القسم للاشتراك:", reply_markup=kb)
                return
            if text == "❌ إلغاء / Unsubscribe":
                kb = await self.build_unsubscribe_keyboard(context.user_data)
                subs_list = state.get('options_map', {}).get('subs_list', {})
                if not subs_list:
                    await update.message.reply_text("💡 ليس لديك أي اشتراكات نشطة حالياً لإلغائها.")
                    state['current_step'] = 'subs_menu'
                    kb = await self.build_subs_menu_keyboard(user_id)
                    await update.message.reply_text("🔔 قائمة الإشعارات والاشتراكات:", reply_markup=kb)
                elif len(subs_list) == 1:
                    # Automate unsubscription if only one exists
                    label, sub_id = list(subs_list.items())[0]
                    success = await self.delete_subscription(sub_id)
                    if success:
                        await update.message.reply_text(f"✅ تم إلغاء اشتراكك: {label}")
                    else:
                        await update.message.reply_text("❌ تعذر إلغاء الاشتراك الآن.")
                    state['current_step'] = 'subs_menu'
                    kb = await self.build_subs_menu_keyboard(user_id)
                    await update.message.reply_text("🔔 قائمة الإشعارات والاشتراكات:", reply_markup=kb)
                else:
                    state['current_step'] = 'subs_unsubscribe'
                    await update.message.reply_text("🗑 اختر اشتراكاً من القائمة لإلغائه:", reply_markup=kb)
                return
            # fallback re-show
            keyboard = await self.build_subs_menu_keyboard(user_id)
            await update.message.reply_text("🔔 Subscription menu:", reply_markup=keyboard)
            return
        if step == 'subs_department':
            # Use normalized label matching with department options
            options = state['options_map'].get('department', {})
            chosen_id = options.get(text)
            if not chosen_id:
                normalized_text = self._normalize_label(text)
                for label, opt_id in options.items():
                    if self._normalize_label(label) == normalized_text:
                        chosen_id = opt_id
                        break
            if not chosen_id:
                kb = await self.build_departments_keyboard(context.user_data)
                if kb is None:
                    await update.message.reply_text("❌ لم يتمكن البوت من الاتصال بالسيرفر، حاول لاحقًا.")
                else:
                    await update.message.reply_text("يرجى اختيار قسم من لوحة الأزرار:", reply_markup=kb)
                return
            state.setdefault('subs_selection', {})['department_id'] = chosen_id
            state['current_step'] = 'subs_year'
            kb = await self.build_years_keyboard(context.user_data)
            if kb is None:
                await update.message.reply_text("❌ لم يتمكن البوت من الاتصال بالسيرفر، حاول لاحقًا.")
            else:
                await update.message.reply_text("📚 اختر السنة الدراسية للاشتراك:", reply_markup=kb)
            return
        if step == 'subs_year':
            options = state['options_map'].get('year', {})
            chosen_id = options.get(text)
            if not chosen_id:
                normalized_text = self._normalize_label(text)
                for label, opt_id in options.items():
                    if self._normalize_label(label) == normalized_text:
                        chosen_id = opt_id
                        break
            if not chosen_id:
                kb = await self.build_years_keyboard(context.user_data)
                if kb is None:
                    await update.message.reply_text("❌ لم يتمكن البوت من الاتصال بالسيرفر، حاول لاحقًا.")
                else:
                    await update.message.reply_text("يرجى اختيار سنة دراسية من لوحة الأزرار:", reply_markup=kb)
                return
            state.setdefault('subs_selection', {})['year_id'] = chosen_id
            state['current_step'] = 'subs_semester'
            kb = await self.build_semesters_keyboard(context.user_data)
            if kb is None:
                await update.message.reply_text("❌ لم يتمكن البوت من الاتصال بالسيرفر، حاول لاحقًا.")
            else:
                await update.message.reply_text("📅 اختر الفصل الدراسي للاشتراك:", reply_markup=kb)
            return
        if step == 'subs_semester':
            options = state['options_map'].get('semester', {})
            chosen_id = options.get(text)
            if not chosen_id:
                normalized_text = self._normalize_label(text)
                for label, opt_id in options.items():
                    if self._normalize_label(label) == normalized_text:
                        chosen_id = opt_id
                        break
            if not chosen_id:
                kb = await self.build_semesters_keyboard(context.user_data)
                if kb is None:
                    await update.message.reply_text("❌ لم يتمكن البوت من الاتصال بالسيرفر، حاول لاحقًا.")
                else:
                    await update.message.reply_text("يرجى اختيار فصل دراسي من لوحة الأزرار:", reply_markup=kb)
                return
            state.setdefault('subs_selection', {})['semester_id'] = chosen_id
            # Persist subscription via backend
            success = await self.create_subscription(update, context.user_data)
            if success:
                # Back to subscription menu
                state['current_step'] = 'subs_menu'
                kb = await self.build_subs_menu_keyboard(update.effective_user.id)
                if kb is None:
                    await update.message.reply_text("✅ تم حفظ الاشتراك. استخدم /start للعودة إلى القائمة.")
                else:
                    await update.message.reply_text("✅ تم حفظ الاشتراك. عدنا إلى قائمة الاشتراكات:", reply_markup=kb)
            else:
                # Error message already sent by create_subscription or we can add a general fallback here
                pass
            return
        if step == 'subs_unsubscribe':
            # Expect selection of an existing subscription label
            subs_map = state.get('options_map', {}).get('subs_list', {})
            sub_id = subs_map.get(text)
            if not sub_id:
                # Try normalized match
                normalized_text = self._normalize_label(text)
                for label, sid in subs_map.items():
                    if self._normalize_label(label) == normalized_text:
                        sub_id = sid
                        break
            if not sub_id:
                kb = await self.build_unsubscribe_keyboard(context.user_data)
                if kb is None:
                    await update.message.reply_text("❌ لم يتمكن البوت من الاتصال بالسيرفر، حاول لاحقًا.")
                else:
                    await update.message.reply_text("يرجى اختيار اشتراك من القائمة:", reply_markup=kb)
                return
            # Delete via backend
            success = await self.delete_subscription(sub_id)
            if success:
                await update.message.reply_text("✅ تم إلغاء الاشتراك.")
            else:
                await update.message.reply_text("❌ تعذر إلغاء الاشتراك الآن.")
            # Back to subs menu
            state['current_step'] = 'subs_menu'
            keyboard = await self.build_subs_menu_keyboard(update.effective_user.id)
            await update.message.reply_text("🔔 Subscription menu:", reply_markup=keyboard)
            return
        if step == 'course':
            # Move to files after selecting a course
            options = state['options_map'].get('course', {})
            if text not in options:
                keyboard = await self.build_courses_keyboard(context.user_data)
                if keyboard is None:
                    await update.message.reply_text("❌ لم يتمكن البوت من الاتصال بالسيرفر، حاول لاحقًا.")
                else:
                    await update.message.reply_text("يرجى اختيار مقرر من لوحة الأزرار:", reply_markup=keyboard)
                return
            state['course_id'] = options[text]
            state['current_step'] = 'file'
            keyboard = await self.build_files_keyboard(context.user_data, state['course_id'])
            if keyboard is None:
                await update.message.reply_text("❌ لم يتمكن البوت من الاتصال بالسيرفر، حاول لاحقًا.")
            else:
                await update.message.reply_text("📁 اختر الملفات للتحميل:", reply_markup=keyboard)
            return
        if step == 'file':
            # Send selected file if valid, then keep files keyboard visible
            file_options = state['options_map'].get('file', {})
            if text not in file_options:
                keyboard = await self.build_files_keyboard(context.user_data, state['course_id'])
                if keyboard is None:
                    await update.message.reply_text("❌ لم يتمكن البوت من الاتصال بالسيرفر، حاول لاحقًا.")
                else:
                    await update.message.reply_text("يرجى اختيار ملف من لوحة الأزرار:", reply_markup=keyboard)
                return
            file_id = file_options[text]
            # Inform user we're fetching the file, then send in background
            try:
                await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
            except Exception:
                pass
            await update.message.reply_text("⏳ جاري جلب الملف المطلوب...")
            await self.send_file_to_user(
                update, 
                file_id, 
                course_id=state['course_id']
            )
            return
    
    async def send_file_to_user(self, update: Update, file_id, course_id):
        """تنزيل الملف بصمت مع إعادة المحاولة حتى النجاح ثم إرساله للمستخدم."""
        user_id = update.effective_user.id
            
        # احصل على بيانات الملف من الكاش أولاً لتجنب طلبات غير ضرورية
        file_metadata_cache = self._cache.setdefault('file_metadata', {})
        cached_by_course = file_metadata_cache.get(course_id)
        file_info = None
        if cached_by_course is not None:
            file_info = cached_by_course.get(file_id)

        # إن لم نجد الكاش للمساق، اجلبه مرة واحدة وخزّنه
        if file_info is None and cached_by_course is None:
            try:
                session = await self._get_session()
                async with session.get(f"{self.api_base_url}/bot/courses/{course_id}/files/") as resp:
                    resp.raise_for_status()
                    files = await resp.json()
                cached_by_course = {f['id']: f for f in files}
                file_metadata_cache[course_id] = cached_by_course
                file_info = cached_by_course.get(file_id)
            except Exception as e:
                logger.warning(f"فشل جلب قائمة الملفات للمساق {course_id}: {e}")
                cached_by_course = {}

        # إذا كان لدينا كاش لكنه لا يحتوي الملف المطلوب، حدّث القائمة مرة واحدة فقط بسرعة
        if file_info is None and cached_by_course is not None:
            try:
                session = await self._get_session()
                async with session.get(f"{self.api_base_url}/bot/courses/{course_id}/files/") as resp:
                    resp.raise_for_status()
                    files = await resp.json()
                cached_by_course = {f['id']: f for f in files}
                file_metadata_cache[course_id] = cached_by_course
                file_info = cached_by_course.get(file_id)
            except Exception as e:
                logger.warning(f"فشل تحديث بيانات الملفات للمساق {course_id}: {e}")

        if not file_info:
            await update.message.reply_text("❌ لم يتم العثور على بيانات الملف، حاول لاحقًا.")
            return

        original_filename = file_info.get('original_filename', 'file')
        
        # التأكد من أن اسم الملف يحتفظ بالامتداد الصحيح
        if not original_filename.lower().endswith('.pdf'):
            # إذا لم يكن للملف امتداد PDF، نضيفه
            original_filename += '.pdf'
        
        # Use the proper download endpoint instead of media URL
        download_url = f"{self.api_base_url}/bot/files/{file_id}/download/"

        # نزّل الملف مع دعم الاستئناف (HTTP Range) وإعادة المحاولة الصامتة حتى النجاح
        def _download_with_resume(url: str) -> str:
            tmp_local_path = None
            max_retries = 5
            attempt = 0
            while attempt < max_retries:
                attempt += 1
                try:
                    if not tmp_local_path:
                        # إنشاء ملف مؤقت بامتداد PDF صحيح
                        fd, tmp_local_path = tempfile.mkstemp(suffix='.pdf')
                        os.close(fd)

                    downloaded_bytes = 0
                    if os.path.exists(tmp_local_path):
                        try:
                            downloaded_bytes = os.path.getsize(tmp_local_path)
                        except Exception:
                            downloaded_bytes = 0

                    headers = {}
                    if downloaded_bytes > 0:
                        headers["Range"] = f"bytes={downloaded_bytes}-"
                    
                    # Merge with BOT_HEADERS for authentication 
                    headers.update(BOT_HEADERS)

                    with requests.get(url, stream=True, timeout=30, headers=headers) as r:
                        # سجل معلومات الاستجابة للتdebug
                        content_type = r.headers.get('Content-Type', '')
                        content_disposition = r.headers.get('Content-Disposition', '')
                        logger.info(f"Download headers - Status: {r.status_code}, Content-Type: {content_type}, Content-Disposition: {content_disposition}")
                        
                        if r.status_code == 404:
                            # File is missing on backend
                            if tmp_local_path and os.path.exists(tmp_local_path):
                                try:
                                    os.remove(tmp_local_path)
                                except Exception:
                                    pass
                            return None
                        
                        if r.status_code == 200 and downloaded_bytes > 0:
                            try:
                                os.remove(tmp_local_path)
                            except Exception:
                                pass
                            downloaded_bytes = 0
                            fd, tmp_local_path = tempfile.mkstemp(suffix='.pdf')
                            os.close(fd)
                            with requests.get(url, stream=True, timeout=30, headers=BOT_HEADERS) as r_full:
                                r_full.raise_for_status()
                                with open(tmp_local_path, "wb") as fh:
                                    for chunk in r_full.iter_content(chunk_size=1024 * 1024):
                                        if chunk:
                                            fh.write(chunk)
                            return tmp_local_path

                        r.raise_for_status()
                        
                        mode = "ab" if downloaded_bytes > 0 else "wb"
                        with open(tmp_local_path, mode) as fh:
                            for chunk in r.iter_content(chunk_size=1024 * 1024):
                                if chunk:
                                    fh.write(chunk)
                    return tmp_local_path
                except Exception as e:
                    logger.warning(f"فشل تنزيل الملف {file_id}، المحاولة ({attempt}/{max_retries}): {e}")
                    time.sleep(2)
                    continue
            return None

        # Concurrency control for downloads and sends
        queued_ts = time.time()
        if download_semaphore.locked():
            logger.info(f"[DL-QUEUE] user={user_id} course={course_id} file_id={file_id} queued; active limit reached")
        
        async with download_semaphore:
            wait_ms = int((time.time() - queued_ts) * 1000)
            logger.info(f"[DL-START] user={user_id} course={course_id} file_id={file_id} waited_ms={wait_ms}")
            
            try:
                tmp_path = await asyncio.to_thread(_download_with_resume, download_url)
                if tmp_path is None:
                    await update.message.reply_text("❌ عذراً، هذا الملف غير متوفر على الخادم (ربما تم حذفه محلياً).")
                    return
            except Exception as e:
                logger.error(f"[DL-ERROR] user={user_id} course={course_id} file_id={file_id} download failed: {e}")
                await update.message.reply_text("❌ حدث خطأ أثناء تنزيل الملف. حاول لاحقًا.")
                return

            # عند النجاح، أرسل الوثيقة مع التأكد من اسم الملف الصحيح
            try:
                attempts = 0
                while attempts < 3:
                    attempts += 1
                    try:
                        await update.effective_chat.send_action(action=ChatAction.UPLOAD_DOCUMENT)
                        
                        # قراءة الملف وإرساله مع الاسم الصحيح
                        with open(tmp_path, "rb") as fh:
                            file_data = fh.read()
                        
                        # إنشاء BytesIO مع الاسم الصحيح
                        file_stream = BytesIO(file_data)
                        file_stream.name = original_filename  # هذا هو المفتاح!
                        
                        await update.effective_chat.send_document(
                            document=InputFile(file_stream, filename=original_filename),
                            caption=f"📄 الملف: {original_filename}",
                            parse_mode=None
                        )
                        logger.info(f"[DL-END] user={user_id} course={course_id} file_id={file_id} attempts={attempts}")
                        break
                        
                    except (TimedOut, NetworkError) as e:
                        logger.warning(f"مهلة إرسال الملف للمستخدم {user_id}: {e}")
                        break
                    except Exception as e:
                        logger.warning(f"فشل إرسال الملف، إعادة المحاولة ({attempts}/3): {e}")
                        await asyncio.sleep(2)
                        continue
                        
            finally:
                # تنظيف الملف المؤقت
                if 'tmp_path' in locals() and tmp_path and os.path.exists(tmp_path):
                    try:
                        os.remove(tmp_path)
                    except Exception as cleanup_err:
                        logger.warning(f"فشل تنظيف الملف المؤقت: {cleanup_err}")

        # بعد الإرسال، أعد عرض لوحة الملفات
        try:
            keyboard = await self.build_files_keyboard(user_id, course_id)
            if keyboard is not None:
                await update.message.reply_text("📁 اختر المزيد من الملفات للتحميل:", reply_markup=keyboard)
        except Exception as e:
            logger.warning(f"فشل إعادة عرض قائمة الملفات بعد الإرسال: {e}")


    async def create_subscription(self, update: Update, user_data: dict) -> bool:
        sel = user_data.get('subs_selection', {})
        user_id = update.effective_user.id
        payload = {
            'telegram_user_id': user_id,
            'department_id': sel.get('department_id'),
            'study_year_id': sel.get('year_id'),
            'semester_id': sel.get('semester_id'),
        }
        def _post():
            try:
                base = self.api_base_url.rstrip('/')
                url = f"{base}/bot/subscriptions/"
                logger.info(f"Creating sub: {url} payload={payload}")
                resp = requests.post(url, json=payload, headers=BOT_HEADERS, timeout=30)
                if resp.status_code == 201:
                    return resp.json()
                logger.error(f"Failed to create sub. Status: {resp.status_code}, Response: {resp.text}")
                return None
            except Exception as e:
                logger.error(f"فشل إنشاء الاشتراك: {e}")
                return None
        result = await asyncio.to_thread(_post)
        if result:
            dept = result.get('department_name') or ''
            year = result.get('study_year_name') or ''
            sem = result.get('semester_name') or ''
            await update.message.reply_text(f"✅ تم تأكيد اشتراكك في: {dept} - {year} - {sem}\nستصلك إشعارات فورية عند رفع أي ملفات جديدة لهذا الفصل.")
            return True
        else:
            await update.message.reply_text("❌ تعذر حفظ الاشتراك الآن.")
            return False
    async def build_unsubscribe_keyboard(self, user_data):
        def _fetch():
            user_id = user_data.get('telegram_user_id') or 0
            try:
                base = self.api_base_url.rstrip('/')
                url = f"{base}/bot/subscriptions/"
                resp = requests.get(url, params={'telegram_user_id': user_id}, headers=BOT_HEADERS, timeout=30)
                resp.raise_for_status()
                return resp.json()
            except Exception as e:
                logger.error(f"فشل جلب قائمة الاشتراكات: {e}")
                return None
        subs = await asyncio.to_thread(_fetch)
        if not subs:
            return self.make_reply_keyboard([])
        labels = []
        options_map = {}
        for s in subs:
            dept = s.get('department_name') or s.get('department') or ''
            year = s.get('study_year_name') or s.get('study_year') or ''
            sem = s.get('semester_name') or s.get('semester') or ''
            label = f"🏫 {dept} | 📚 {year} | 📅 {sem}"
            labels.append(label)
            options_map[label] = s['id']
        # store under subs_list
        user_data.setdefault('options_map', {})['subs_list'] = options_map
        return self.make_reply_keyboard(labels)

    async def delete_subscription(self, sub_id: int) -> bool:
        def _delete():
            try:
                # Ensure no double slashes if base_url ends with slash
                base = self.api_base_url.rstrip('/')
                url = f"{base}/bot/subscriptions/{sub_id}/"
                resp = requests.delete(url, headers=BOT_HEADERS, timeout=30)
                if resp.status_code in (200, 204):
                    return True
                if resp.status_code == 404:
                    logger.info(f"Subscription {sub_id} not found on server; treating as deleted.")
                    return True
                logger.error(f"Failed to delete subscription {sub_id}. Status: {resp.status_code}, Response: {resp.text}")
                return False
            except Exception as e:
                logger.error(f"فشل حذف الاشتراك {sub_id}: {e}")
                return False
        return await asyncio.to_thread(_delete)

    async def poll_notifications(self, context: ContextTypes.DEFAULT_TYPE):
        # Fetch pending notifications from backend
        try:
            pending = await self._async_get_json(f"{self.api_base_url}/bot/notifications/pending/")
        except Exception as e:
            logger.debug(f"لا إشعارات معلّقة أو فشل الجلب: {e}")
            return
            
        if not pending:
            return
        # Send notifications concurrently with throttling
        semaphore = asyncio.Semaphore(10)

        async def send_one(chat_id: int, text: str):
            async with semaphore:
                try:
                    await context.application.bot.send_message(chat_id=chat_id, text=text)
                except Exception as e:
                    logger.warning(f"فشل إرسال إشعار إلى {chat_id}: {e}")

        send_tasks = []
        for n in pending:
            action_type = n.get('action_type', 'create')
            course_name = n.get('course_name', 'غير محدد')
            course_type = n.get('course_type', '')
            course_info = f"{course_name} ({course_type})" if course_type else course_name
            
            dept_name = n.get('department_name', '')
            
            year_mapping = {
                '1': 'الأولى', '2': 'الثانية', '3': 'الثالثة',
                '4': 'الرابعة', '5': 'الخامسة', '6': 'السادسة'
            }
            raw_year = str(n.get('year_name', ''))
            formatted_year = year_mapping.get(raw_year, raw_year)
            semester_name = n.get('semester_name', '')
            
            if action_type == 'update':
                title = "🔄 تحديث مادة / Material Updated"
                message = (
                    f"{title}\n"
                    f"📂 القسم: {dept_name} | السنة: {formatted_year} | الفصل: {semester_name}\n"
                    f"📝 تم تعديل: {n.get('file_name','')}"
                )
            else:
                title = "✨ مادة جديدة / New Material"
                message = (
                    f"{title}\n"
                    f"📂 القسم: {dept_name} | السنة: {formatted_year} | الفصل: {semester_name}\n"
                    f"📝 الملف: {n.get('file_name','')}"
                )
            sub_ids = n.get('subscriber_ids') or []
            if isinstance(sub_ids, int):
                sub_ids = [sub_ids]
            elif isinstance(sub_ids, str):
                try:
                    import json
                    sub_ids = json.loads(sub_ids)
                    if not isinstance(sub_ids, list): sub_ids = [sub_ids]
                except:
                    sub_ids = [sub_ids]
            
            for chat_id in sub_ids:
                send_tasks.append(asyncio.create_task(send_one(chat_id, message)))

        if send_tasks:
            await asyncio.gather(*send_tasks, return_exceptions=True)
            
        # Acknowledge delivered notifications
        ids = [n.get('id') for n in pending if n.get('id') is not None]
        if ids:
            session = await self._get_session()
            try:
                async with session.post(f"{self.api_base_url}/bot/notifications/ack/", json={'ids': ids}) as resp:
                    pass
            except Exception as e:
                logger.debug(f"فشل تأكيد الإشعارات: {e}")
    
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Help command handler"""
        help_text = (
            "🤖 مساعدة بوت إدارة المقررات\n\n"
            "الأوامر:\n"
            "/start - بدء استخدام البوت والاختيار\n"
            "/help - عرض رسالة المساعدة\n"
            "/sync_notifications - جلب الإشعارات المعلّقة من الخادم وإرسالها\n\n"
            "طريقة الاستخدام:\n"
            "1. استخدم /start للبدء\n"
            "2. اختر القسم\n"
            "3. اختر السنة الدراسية\n"
            "4. اختر الفصل الدراسي\n"
            "5. اختر نوع المقرر (عملي/نظري)\n"
            "6. اختر المقرر\n"
            "7. حمّل الملفات بالضغط على أسمائها\n\n"
            "يمكنك تحميل عدة ملفات من نفس المقرر!"
        )
        await update.message.reply_text(help_text)
    
    async def handle_persistent_keyboard(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        # Kept for backward compatibility; delegate to handle_text
        await self.handle_text(update, context)

    async def handle_error(self, update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Log the error and send a telegram message to notify the developer."""
        logger.error(f"Exception while handling an update: {context.error}", exc_info=context.error)
        
        # Build the message
        message = "⚠️ حدث خطأ تقني غير متوقع في البوت. تم تسجيل الخطأ للمراجعة."
        
        # If possible, notify the user
        if isinstance(update, Update) and update.effective_message:
            try:
                await update.effective_message.reply_text(message)
            except Exception:
                pass

def main():
    """Main function to run the bot"""
    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN not found in environment variables")
        return
    
    # Create bot instance
    bot = CourseBot()
    
    # Create application with Persistence and Explicit HTTPX Request timeouts
    persistence = PicklePersistence(filepath="bot_state.pickle")
    # A larger custom request object is required to bypass OS/Library native TCP timeouts in bad networks
    t_request = HTTPXRequest(connection_pool_size=8, connect_timeout=45.0, read_timeout=45.0)
    
    application = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .persistence(persistence)
        .request(t_request)
        .get_updates_request(t_request)
        .build()
    )
    
    # Global error handler
    application.add_error_handler(bot.handle_error)
    
    # Add handlers
    application.add_handler(CommandHandler("start", bot.start))
    application.add_handler(CommandHandler("help", bot.help_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, bot.handle_text))
    application.add_handler(CommandHandler("sync_notifications", bot.poll_notifications))

    # Auto-deliver notifications without restarts (light polling)
    try:
        jq = getattr(application, 'job_queue', None)
        if jq is None and JobQueue is not None:
            jq = JobQueue()
            jq.set_application(application)
            application.job_queue = jq
        if jq is None:
            logger.warning("JobQueue unavailable. Ensure python-telegram-bot[job-queue] is installed.")
        else:
            jq.run_repeating(bot.poll_notifications, interval=NOTIFICATIONS_POLL_INTERVAL_SEC, first=3)
    except Exception as e:
        logger.warning(f"تعذر جدولة مهمة الإشعارات: {e}")
    
    # Start the bot
    logger.info("Starting Course Management Bot...")

    # PTB v20: run_polling() is sync; v21+: it's async. Detect and run accordingly without nesting loops
    if inspect.iscoroutinefunction(application.run_polling):
        asyncio.run(application.run_polling())
    else:
        application.run_polling()

if __name__ == '__main__':
    main()
