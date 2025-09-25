import os
import logging
import asyncio
import inspect
import requests
from datetime import datetime, timedelta
import httpx
import time
import tempfile
from telegram.error import TimedOut, NetworkError
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.constants import ChatAction
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
try:
    from telegram.ext import JobQueue
except Exception:
    JobQueue = None
from dotenv import load_dotenv

load_dotenv()

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
NOTIFICATIONS_POLL_INTERVAL_SEC = int(os.getenv('NOTIFICATIONS_POLL_INTERVAL_SEC', '5'))

# Global semaphore to limit concurrent file downloads/sends
DOWNLOAD_CONCURRENCY = int(os.getenv('DOWNLOAD_CONCURRENCY', '20'))
download_semaphore = asyncio.Semaphore(DOWNLOAD_CONCURRENCY)

class CourseBot:
    def __init__(self):
        self.api_base_url = DJANGO_API_BASE_URL
        self.user_states = {}  # Store user selection states and option maps
        
    # ----- User visit helpers -----
    def _get_last_visit(self, telegram_user_id: int):
        try:
            resp = requests.get(
                f"{self.api_base_url}/bot/users/last-visit/",
                params={'telegram_user_id': telegram_user_id},
                timeout=10
            )
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            data = resp.json()
            return data
        except Exception:
            return None

    def _record_visit(self, telegram_user_id: int, username: str):
        try:
            requests.post(
                f"{self.api_base_url}/bot/users/visit/",
                json={'telegram_user_id': telegram_user_id, 'username': username},
                timeout=10
            )
        except Exception:
            pass

    def _is_morning(self) -> bool:
        hour = datetime.now().hour
        return 5 <= hour < 12

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
                resp = requests.get(url, params=params, timeout=timeout)
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

        # Fetch last visit info (non-blocking to thread)
        last_visit_data = await asyncio.to_thread(self._get_last_visit, user_id)
        # Decide which greeting to send
        greeting_sent = False
        if not last_visit_data:
            # New user welcome (only once)
            welcome = (
                f"أهلاً {user_name}! 👋\n\n"
                "مرحباً بك في بوت المعهد التقاني لتقنيات الحاسوب.\n"
                "هذا البوت صُمم خصيصًا لمساعدتك في التعلم والوصول إلى الملفات الدراسية بسهولة وسرعة.\n\n"
                "اكتشف القوائم وابدأ رحلتك الدراسية الآن.\n"
                "تصفح المواد، اختر نوع المقرر، وحمّل الملفات بكل سهولة.\n\n"
                "لا تنسَ الاشتراك في قسمك الخاص باستخدام زر 'اشترك' الموجود بالأسفل لتصلك كل الملفات والإشعارات الخاصة بقسمك وسنتك وفصلك.\n\n"
                "فريق التطوير: MS Developer"
            )
            await update.message.reply_text(welcome)
            greeting_sent = True
        else:
            try:
                last_str = last_visit_data.get('last_visit')
                if last_str:
                    last_dt = datetime.fromisoformat(last_str.replace('Z', '+00:00')).astimezone()
                    if datetime.now().astimezone() - last_dt >= timedelta(days=2):
                        if self._is_morning():
                            msg = f"صباح الخير {user_name}! 🌞 اشتقنا لك، تابع دراستك اليوم."
                        else:
                            msg = f"مساء الخير {user_name}! 🌙 لا تنسَ متابعة دراستك."
                        await update.message.reply_text(msg)
                        greeting_sent = True
            except Exception:
                pass

        # Record this visit (fire and forget)
        asyncio.create_task(asyncio.to_thread(self._record_visit, user_id, user_name))
        self.user_states[user_id] = {
            'department_id': None,
            'study_year_id': None,
            'semester_id': None,
            'course_type_id': None,
            'course_id': None,
            'current_step': 'department',
            'options_map': {},
            'file_metadata': {}
        }
        
        welcome_message = (
            "🎓 أهلاً بك في بوت إدارة المقررات!\n\n"
            "سأساعدك في العثور على مواد المقررات وتحميلها. "
            "لنبدأ باختيار القسم."
        )

        keyboard = await self.build_departments_keyboard(user_id)
        if keyboard is None:
            await update.message.reply_text("❌ لم يتمكن البوت من الاتصال بالسيرفر، حاول لاحقًا.")
        else:
            if not greeting_sent:
                await update.message.reply_text(welcome_message, reply_markup=keyboard)
            else:
                await update.message.reply_text("لنبدأ باختيار القسم.", reply_markup=keyboard)
    
    def build_base_controls(self):
        return [
            KeyboardButton("🏠 ابدأ من جديد"),
            KeyboardButton("❓ مساعدة"),
            KeyboardButton("🔔 Subscribe / Unsubscribe"),
            KeyboardButton("رجوع"),
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
        rows.append(self.build_base_controls())
        return ReplyKeyboardMarkup(rows, resize_keyboard=True)

    async def build_subs_menu_keyboard(self, user_id):
        def _fetch():
            try:
                r = requests.get(f"{self.api_base_url}/bot/subscriptions/", params={'telegram_user_id': user_id}, timeout=15)
                r.raise_for_status()
                return r.json()
            except Exception:
                return []
        subs = await asyncio.to_thread(_fetch)
        has_subs = bool(subs)
        buttons = []
        if has_subs:
            buttons.append([KeyboardButton("➖ Unsubscribe")])
        else:
            buttons.append([KeyboardButton("➕ Subscribe")])
        buttons.append(self.build_base_controls())
        return ReplyKeyboardMarkup(buttons, resize_keyboard=True)
    
    async def build_departments_keyboard(self, user_id):
        """Fetch departments and build a ReplyKeyboard; store label->id mapping."""
        try:
            departments = await asyncio.to_thread(self._get_json_with_retries, f"{self.api_base_url}/bot/departments/")
            
            labels = []
            options_map = {}
            for dept in departments:
                label = f"🏫 {dept['name']}"
                labels.append(label)
                options_map[label] = dept['id']

            self.user_states[user_id]['options_map']['department'] = options_map
            return self.make_reply_keyboard(labels)
        except Exception as e:
            logger.error(f"Error fetching departments: {e}")
            return None
    
    async def build_years_keyboard(self, user_id):
        try:
            years = await asyncio.to_thread(self._get_json_with_retries, f"{self.api_base_url}/bot/study-years/")
            
            labels = []
            options_map = {}
            for year in years:
                label = f"📚 السنة {year['year']}"
                labels.append(label)
                options_map[label] = year['id']

            self.user_states[user_id]['options_map']['year'] = options_map
            return self.make_reply_keyboard(labels)
        except Exception as e:
            logger.error(f"Error fetching study years: {e}")
            return None
    
    async def build_semesters_keyboard(self, user_id):
        try:
            semesters = await asyncio.to_thread(self._get_json_with_retries, f"{self.api_base_url}/bot/semesters/")
            
            labels = []
            options_map = {}
            for sem in semesters:
                label = f"📅 {sem['name']}"
                labels.append(label)
                options_map[label] = sem['id']

            self.user_states[user_id]['options_map']['semester'] = options_map
            return self.make_reply_keyboard(labels)
        except Exception as e:
            logger.error(f"Error fetching semesters: {e}")
            return None
    
    async def build_course_types_keyboard(self, user_id):
        try:
            course_types = await asyncio.to_thread(self._get_json_with_retries, f"{self.api_base_url}/bot/course-types/")
            
            labels = []
            options_map = {}
            for ct in course_types:
                label = f"📖 {ct['name'].title()}"
                labels.append(label)
                options_map[label] = ct['id']

            self.user_states[user_id]['options_map']['course_type'] = options_map
            return self.make_reply_keyboard(labels)
        except Exception as e:
            logger.error(f"Error fetching course types: {e}")
            return None
    
    async def build_courses_keyboard(self, user_id):
        try:
            state = self.user_states.get(user_id, {})
            params = {
                'department_id': state.get('department_id'),
                'study_year_id': state.get('study_year_id'),
                'semester_id': state.get('semester_id'),
                'course_type_id': state.get('course_type_id')
            }
            
            courses = await asyncio.to_thread(self._get_json_with_retries, f"{self.api_base_url}/bot/courses/", params)
            
            labels = []
            options_map = {}
            for course in courses:
                files_count = course.get('files_count', 0)
                label = f"📘 {course['name']} ({files_count})"
                labels.append(label)
                options_map[label] = course['id']

            self.user_states[user_id]['options_map']['course'] = options_map
            return self.make_reply_keyboard(labels)
        except Exception as e:
            logger.error(f"Error fetching courses: {e}")
            return None
    
    async def build_files_keyboard(self, user_id, course_id):
        try:
            files = await asyncio.to_thread(self._get_json_with_retries, f"{self.api_base_url}/bot/courses/{course_id}/files/")
            
            labels = []
            options_map = {}
            for f in files:
                file_size = f.get('file_size', 0)
                size_mb = round(file_size / (1024 * 1024), 2) if file_size > 0 else 0
                label = f"📄 {f['original_filename']} ({size_mb} م.ب)"
                # Telegram limits button text length; keep as-is for now
                labels.append(label)
                options_map[label] = f['id']

            self.user_states[user_id]['options_map']['file'] = options_map
            # Cache file metadata for this course to avoid re-fetching
            self.user_states[user_id]['file_metadata'][course_id] = { f['id']: f for f in files }
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

        # Ensure state exists
        if user_id not in self.user_states:
            await self.start(update, context)
            return
        
        state = self.user_states[user_id]

        # Global controls
        if text == "🏠 ابدأ من جديد":
            self.user_states[user_id] = {
                'department_id': None,
                'study_year_id': None,
                'semester_id': None,
                'course_type_id': None,
                'course_id': None,
                'current_step': 'department',
                'options_map': {},
                'file_metadata': {}
            }
            keyboard = await self.build_departments_keyboard(user_id)
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
                kb = await self.build_departments_keyboard(user_id)
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
                kb = await self.build_departments_keyboard(user_id)
                if kb is None:
                    await update.message.reply_text("❌ لم يتمكن البوت من الاتصال بالسيرفر، حاول لاحقًا.")
                else:
                    await update.message.reply_text("🏫 اختر القسم:", reply_markup=kb)
                return
            if step in ('semester', 'subs_semester'):
                state['current_step'] = 'year' if step == 'semester' else 'subs_year'
                kb = await self.build_years_keyboard(user_id)
                if kb is None:
                    await update.message.reply_text("❌ لم يتمكن البوت من الاتصال بالسيرفر، حاول لاحقًا.")
                else:
                    await update.message.reply_text("📚 اختر السنة الدراسية:", reply_markup=kb)
                return
            if step == 'course_type':
                state['current_step'] = 'semester'
                kb = await self.build_semesters_keyboard(user_id)
                if kb is None:
                    await update.message.reply_text("❌ لم يتمكن البوت من الاتصال بالسيرفر، حاول لاحقًا.")
                else:
                    await update.message.reply_text("📅 اختر الفصل الدراسي:", reply_markup=kb)
                return
            if step == 'course':
                state['current_step'] = 'course_type'
                kb = await self.build_course_types_keyboard(user_id)
                if kb is None:
                    await update.message.reply_text("❌ لم يتمكن البوت من الاتصال بالسيرفر، حاول لاحقًا.")
                else:
                    await update.message.reply_text("📖 اختر نوع المقرر:", reply_markup=kb)
                return
            if step == 'file':
                state['current_step'] = 'course'
                kb = await self.build_courses_keyboard(user_id)
                if kb is None:
                    await update.message.reply_text("❌ لم يتمكن البوت من الاتصال بالسيرفر، حاول لاحقًا.")
                else:
                    await update.message.reply_text("📋 اختر المقرر:", reply_markup=kb)
                return
            if step in ('subs_menu', 'subs_unsubscribe'):
                state['current_step'] = 'department'
                kb = await self.build_departments_keyboard(user_id)
                if kb is None:
                    await update.message.reply_text("❌ لم يتمكن البوت من الاتصال بالسيرفر، حاول لاحقًا.")
                else:
                    await update.message.reply_text("🔙 عدنا للقائمة الرئيسية. اختر القسم:", reply_markup=kb)
                return
        
        if text == "❓ مساعدة":
            await self.help_command(update, context)
            return

        # Entry point for subscriptions menu
        if text == "🔔 Subscribe / Unsubscribe":
            state['current_step'] = 'subs_menu'
            keyboard = await self.build_subs_menu_keyboard(user_id)
            await update.message.reply_text("🔔 Subscription menu:", reply_markup=keyboard)
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
                    keyboard = await builder_fn(user_id)
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
            keyboard = await builder_fn(user_id)
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
            await handle_choice('semester', 'course_type', self.build_course_types_keyboard, "📖 الآن اختر نوع المقرر:")
            return
        if step == 'course_type':
            await handle_choice('course_type', 'course', self.build_courses_keyboard, "📋 الآن اختر المقرر:")
            return
        if step == 'subs_menu':
            if text == "➕ Subscribe":
                # init temporary selection
                state['subs_selection'] = {'department_id': None, 'year_id': None, 'semester_id': None}
                state['current_step'] = 'subs_department'
                kb = await self.build_departments_keyboard(user_id)
                if kb is None:
                    await update.message.reply_text("❌ لم يتمكن البوت من الاتصال بالسيرفر، حاول لاحقًا.")
                else:
                    await update.message.reply_text("🏫 اختر القسم للاشتراك:", reply_markup=kb)
                return
            if text == "➖ Unsubscribe":
                state['current_step'] = 'subs_unsubscribe'
                kb = await self.build_unsubscribe_keyboard(user_id)
                if kb is None:
                    await update.message.reply_text("❌ لم يتمكن البوت من الاتصال بالسيرفر، حاول لاحقًا.")
                else:
                    await update.message.reply_text("اختر اشتراكًا لإلغائه:", reply_markup=kb)
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
                kb = await self.build_departments_keyboard(user_id)
                if kb is None:
                    await update.message.reply_text("❌ لم يتمكن البوت من الاتصال بالسيرفر، حاول لاحقًا.")
                else:
                    await update.message.reply_text("يرجى اختيار قسم من لوحة الأزرار:", reply_markup=kb)
                return
            state.setdefault('subs_selection', {})['department_id'] = chosen_id
            state['current_step'] = 'subs_year'
            kb = await self.build_years_keyboard(user_id)
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
                kb = await self.build_years_keyboard(user_id)
                if kb is None:
                    await update.message.reply_text("❌ لم يتمكن البوت من الاتصال بالسيرفر، حاول لاحقًا.")
                else:
                    await update.message.reply_text("يرجى اختيار سنة دراسية من لوحة الأزرار:", reply_markup=kb)
                return
            state.setdefault('subs_selection', {})['year_id'] = chosen_id
            state['current_step'] = 'subs_semester'
            kb = await self.build_semesters_keyboard(user_id)
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
                kb = await self.build_semesters_keyboard(user_id)
                if kb is None:
                    await update.message.reply_text("❌ لم يتمكن البوت من الاتصال بالسيرفر، حاول لاحقًا.")
                else:
                    await update.message.reply_text("يرجى اختيار فصل دراسي من لوحة الأزرار:", reply_markup=kb)
                return
            state.setdefault('subs_selection', {})['semester_id'] = chosen_id
            # Persist subscription via backend
            await self.create_subscription(update, user_id)
            # Back to main menu
            state['current_step'] = 'department'
            kb = await self.build_departments_keyboard(user_id)
            if kb is None:
                await update.message.reply_text("✅ تم حفظ الاشتراك. استخدم /start للعودة إلى القائمة.")
            else:
                await update.message.reply_text("✅ تم حفظ الاشتراك. عدنا إلى القائمة الرئيسية، اختر القسم:", reply_markup=kb)
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
                kb = await self.build_unsubscribe_keyboard(user_id)
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
            keyboard = await self.build_subs_menu_keyboard(user_id)
            await update.message.reply_text("🔔 Subscription menu:", reply_markup=keyboard)
            return
        if step == 'course':
            # Move to files after selecting a course
            options = state['options_map'].get('course', {})
            if text not in options:
                keyboard = await self.build_courses_keyboard(user_id)
                if keyboard is None:
                    await update.message.reply_text("❌ لم يتمكن البوت من الاتصال بالسيرفر، حاول لاحقًا.")
                else:
                    await update.message.reply_text("يرجى اختيار مقرر من لوحة الأزرار:", reply_markup=keyboard)
                return
            state['course_id'] = options[text]
            state['current_step'] = 'file'
            keyboard = await self.build_files_keyboard(user_id, state['course_id'])
            if keyboard is None:
                await update.message.reply_text("❌ لم يتمكن البوت من الاتصال بالسيرفر، حاول لاحقًا.")
            else:
                await update.message.reply_text("📁 اختر الملفات للتحميل:", reply_markup=keyboard)
            return
        if step == 'file':
            # Send selected file if valid, then keep files keyboard visible
            file_options = state['options_map'].get('file', {})
            if text not in file_options:
                keyboard = await self.build_files_keyboard(user_id, state['course_id'])
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
            await self.send_file_to_user(update, file_id)
            return
    
    async def send_file_to_user(self, update: Update, file_id):
        """تنزيل الملف بصمت مع إعادة المحاولة حتى النجاح ثم إرساله للمستخدم."""
        user_id = update.effective_user.id
        course_id = self.user_states[user_id]['course_id']
            
        # احصل على بيانات الملف من الكاش أولاً لتجنب طلبات غير ضرورية
        cached_by_course = self.user_states[user_id]['file_metadata'].get(course_id)
        file_info = None
        if cached_by_course is not None:
            file_info = cached_by_course.get(file_id)

        # إن لم نجد الكاش للمساق، اجلبه مرة واحدة وخزّنه
        if file_info is None and cached_by_course is None:
            try:
                resp = requests.get(f"{self.api_base_url}/bot/courses/{course_id}/files/")
                resp.raise_for_status()
                files = resp.json()
                cached_by_course = {f['id']: f for f in files}
                self.user_states[user_id]['file_metadata'][course_id] = cached_by_course
                file_info = cached_by_course.get(file_id)
            except Exception as e:
                logger.warning(f"فشل جلب قائمة الملفات للمساق {course_id}: {e}")
                cached_by_course = {}

        # إذا كان لدينا كاش لكنه لا يحتوي الملف المطلوب، حدّث القائمة مرة واحدة فقط بسرعة
        if file_info is None and cached_by_course is not None:
            try:
                resp = requests.get(f"{self.api_base_url}/bot/courses/{course_id}/files/")
                resp.raise_for_status()
                files = resp.json()
                cached_by_course = {f['id']: f for f in files}
                self.user_states[user_id]['file_metadata'][course_id] = cached_by_course
                file_info = cached_by_course.get(file_id)
            except Exception as e:
                logger.warning(f"فشل تحديث بيانات الملفات للمساق {course_id}: {e}")

        if not file_info:
            await update.message.reply_text("❌ لم يتم العثور على بيانات الملف، حاول لاحقًا.")
            return

        original_filename = file_info.get('original_filename', 'file')
        file_url = file_info['file_url']

        # نزّل الملف مع دعم الاستئناف (HTTP Range) وإعادة المحاولة الصامتة حتى النجاح
        def _download_with_resume(url: str) -> str:
            tmp_local_path = None
            while True:
                try:
                    if not tmp_local_path:
                        fd, tmp_local_path = tempfile.mkstemp()
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

                    with requests.get(url, stream=True, timeout=30, headers=headers) as r:
                        if r.status_code == 200 and downloaded_bytes > 0:
                            try:
                                os.remove(tmp_local_path)
                            except Exception:
                                pass
                            downloaded_bytes = 0
                            with requests.get(url, stream=True, timeout=30) as r_full:
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
                    logger.warning(f"فشل تنزيل الملف {file_id}، تتم إعادة المحاولة: {e}")
                    time.sleep(1)
                    continue

        # Concurrency control for downloads and sends
        queued_ts = time.time()
        if download_semaphore.locked():
            logger.info(f"[DL-QUEUE] user={user_id} course={course_id} file_id={file_id} queued; active limit reached")
        async with download_semaphore:
            wait_ms = int((time.time() - queued_ts) * 1000)
            logger.info(f"[DL-START] user={user_id} course={course_id} file_id={file_id} waited_ms={wait_ms}")
            try:
                tmp_path = await asyncio.to_thread(_download_with_resume, file_url)
            except Exception as e:
                logger.error(f"[DL-ERROR] user={user_id} course={course_id} file_id={file_id} download failed: {e}")
                await update.message.reply_text("❌ حدث خطأ أثناء تنزيل الملف. حاول لاحقًا.")
                return

            # عند النجاح، أرسل الوثيقة في نفس الحجز لضمان عدم تجاوز الحد أثناء الرفع
            try:
                attempts = 0
                while attempts < 3:
                    attempts += 1
                    try:
                        try:
                            await update.effective_chat.send_action(action=ChatAction.UPLOAD_DOCUMENT)
                        except Exception:
                            pass
                        with open(tmp_path, "rb") as fh:
                            await update.effective_chat.send_document(document=fh, filename=original_filename, caption=f"📄 الملف: {original_filename}")
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
                if 'tmp_path' in locals() and tmp_path and os.path.exists(tmp_path):
                    try:
                        os.remove(tmp_path)
                    except Exception as cleanup_err:
                        logger.warning(f"فشل تنظيف الملف المؤقت: {cleanup_err}")

        # بعد الإرسال، أعد عرض لوحة الملفات حتى يتمكن المستخدم من متابعة التحميل
        try:
            keyboard = await self.build_files_keyboard(user_id, course_id)
            if keyboard is not None:
                await update.message.reply_text("📁 اختر المزيد من الملفات للتحميل:", reply_markup=keyboard)
        except Exception as e:
            logger.warning(f"فشل إعادة عرض قائمة الملفات بعد الإرسال: {e}")

    async def create_subscription(self, update: Update, user_id: int):
        state = self.user_states.get(user_id, {})
        sel = state.get('subs_selection', {})
        payload = {
            'telegram_user_id': user_id,
            'department_id': sel.get('department_id'),
            'study_year_id': sel.get('year_id'),
            'semester_id': sel.get('semester_id'),
        }
        def _post():
            try:
                resp = requests.post(f"{self.api_base_url}/bot/subscriptions/", json=payload, timeout=30)
                resp.raise_for_status()
                return resp.json()
            except Exception as e:
                logger.error(f"فشل إنشاء الاشتراك: {e}")
                return None
        result = await asyncio.to_thread(_post)
        if result:
            dept = result.get('department_name') or ''
            year = result.get('study_year_name') or ''
            sem = result.get('semester_name') or ''
            await update.message.reply_text(f"✅ You are subscribed to: {dept} - {year} - {sem}")
        else:
            await update.message.reply_text("❌ تعذر حفظ الاشتراك الآن.")

    async def build_unsubscribe_keyboard(self, user_id):
        def _fetch():
            try:
                resp = requests.get(f"{self.api_base_url}/bot/subscriptions/", params={'telegram_user_id': user_id}, timeout=30)
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
        self.user_states[user_id]['options_map']['subs_list'] = options_map
        return self.make_reply_keyboard(labels)

    async def delete_subscription(self, sub_id: int) -> bool:
        def _delete():
            try:
                resp = requests.delete(f"{self.api_base_url}/bot/subscriptions/{sub_id}/", timeout=30)
                if resp.status_code in (200, 204):
                    return True
                return False
            except Exception as e:
                logger.error(f"فشل حذف الاشتراك {sub_id}: {e}")
                return False
        return await asyncio.to_thread(_delete)

    async def poll_notifications(self, context: ContextTypes.DEFAULT_TYPE):
        # Fetch pending notifications from backend and deliver quickly and concurrently
        def _fetch_pending():
            try:
                resp = requests.get(f"{self.api_base_url}/bot/notifications/pending/", timeout=30)
                resp.raise_for_status()
                return resp.json()
            except Exception as e:
                logger.debug(f"لا إشعارات معلّقة أو فشل الجلب: {e}")
                return []
        pending = await asyncio.to_thread(_fetch_pending)
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
            message = (
                "📢 تم إضافة ملف جديد!\n"
                f"📄 اسم الملف: {n.get('file_name','')}\n"
                f"🏫 القسم: {n.get('department_name','')}\n"
                f"📚 السنة: {n.get('year_name','')}\n"
                f"📅 الفصل: {n.get('semester_name','')}"
            )
            for chat_id in (n.get('subscriber_ids') or []):
                send_tasks.append(asyncio.create_task(send_one(chat_id, message)))

        if send_tasks:
            await asyncio.gather(*send_tasks, return_exceptions=True)
        # Acknowledge delivered notifications
        def _ack(ids):
            try:
                requests.post(f"{self.api_base_url}/bot/notifications/ack/", json={'ids': ids}, timeout=30)
            except Exception as e:
                logger.debug(f"فشل تأكيد الإشعارات: {e}")
        ids = [n.get('id') for n in pending if n.get('id') is not None]
        if ids:
            await asyncio.to_thread(_ack, ids)
    
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

def main():
    """Main function to run the bot"""
    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN not found in environment variables")
        return
    
    # Create bot instance
    bot = CourseBot()
    
    # Create application
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
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
