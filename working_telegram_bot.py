import os
import logging
import tempfile
import requests
from telegram import Update


logger = logging.getLogger(__name__)


class WorkingTelegramBot:
    """
    غلاف (Wrapper) مبسّط يركّز على تنزيل الملفات بشكل موثوق وصامت.

    طريقة الاستخدام: قم بدمج الدالة send_file_to_user داخل المعالجات لديك.
    هذه الفئة تتوقّع وجود حالة لكل مستخدم بالشكل التالي:
        self.user_states[user_id] = {
            'course_id': رقم_المساق أو None,
            'file_metadata': { course_id: { file_id: معلومات_الملف } },
            'recently_sent_file_ids': مجموعة_معرّفات_أُرسلت_مؤخرًا
        }
    بالإضافة إلى رابط أساس لواجهة البرمجة self.api_base_url.
    """

    def __init__(self, api_base_url: str):
        self.api_base_url = api_base_url
        self.user_states = {}

    def _ensure_user_state(self, user_id: int):
        if user_id not in self.user_states:
            self.user_states[user_id] = {
                'course_id': None,
                'file_metadata': {},
                'recently_sent_file_ids': set(),
            }

    async def send_file_to_user(self, update: Update, file_id: int):
        """
        تنزيل الملف بصمت وبشكل موثوق مع إعادة المحاولة تلقائيًا حتى النجاح،
        ثم إرسال الملف للمستخدم دون أي رسائل خطأ.

        - تنزيل متدفّق مع مهلة 60 ثانية إلى ملفٍ مؤقّت
        - إعادة المحاولة تلقائيًا حتى يكتمل التنزيل
        - إرسال الملف باستخدام reply_document مع اسم الملف الأصلي وتعليق عربي
        - منع أي رسائل خطأ مرئية للمستخدم عند الفشل
        - عدم إرسال رسائل نجاح مكرّرة (لا تُرسل سوى الوثيقة نفسها)
        """
        user_id = update.effective_user.id
        self._ensure_user_state(user_id)

        state = self.user_states[user_id]
        course_id = state.get('course_id')

        # جلب بيانات الملف من الذاكرة المؤقتة؛ وإن لم توجد، يتم جلبها وتخزينها
        cached = state['file_metadata'].get(course_id)
        if cached is None:
            try:
                resp = requests.get(f"{self.api_base_url}/bot/courses/{course_id}/files/")
                resp.raise_for_status()
                files = resp.json()
                cached = { f['id']: f for f in files }
                state['file_metadata'][course_id] = cached
            except Exception as e:
                # لا تُبلغ المستخدم؛ استمر بالمحاولة لاحقًا في الحلقة أدناه
                logger.error(f"فشل جلب قائمة ملفات للمساق {course_id}: {e}")
                cached = {}

        file_info = cached.get(file_id)
        if not file_info:
            # أعد الجلب مرة واحدة إن لم يُعثر على الملف، ثم ارجع لآلية إعادة المحاولة
            try:
                resp = requests.get(f"{self.api_base_url}/bot/courses/{course_id}/files/")
                resp.raise_for_status()
                files = resp.json()
                cached = { f['id']: f for f in files }
                state['file_metadata'][course_id] = cached
                file_info = cached.get(file_id)
            except Exception as e:
                logger.error(f"فشل تحديث بيانات ملفات المساق {course_id}: {e}")

        # إن ما زال غير موجود، ادخل حلقة إعادة المحاولة مع تحديث البيانات كل دورة
        while not file_info:
            try:
                resp = requests.get(f"{self.api_base_url}/bot/courses/{course_id}/files/")
                resp.raise_for_status()
                files = resp.json()
                cached = { f['id']: f for f in files }
                state['file_metadata'][course_id] = cached
                file_info = cached.get(file_id)
                if not file_info:
                    raise RuntimeError("الملف المطلوب غير موجود في بيانات الملفات.")
            except Exception as e:
                logger.warning(f"إعادة المحاولة لجلب بيانات الملفات للمساق {course_id}: {e}")
                continue

        original_filename = file_info.get('original_filename', 'file')
        file_url = file_info['file_url']

        # تنزيل مع إعادة المحاولة حتى النجاح؛ دون رسائل للمستخدم
        tmp_path = None
        while True:
            try:
                with tempfile.NamedTemporaryFile(delete=False) as tmp:
                    tmp_path = tmp.name
                    with requests.get(file_url, stream=True, timeout=60) as r:
                        r.raise_for_status()
                        for chunk in r.iter_content(chunk_size=1024 * 512):
                            if chunk:
                                tmp.write(chunk)
                break
            except Exception as e:
                logger.warning(f"فشل تنزيل الملف {file_id}، تتم إعادة المحاولة: {e}")
                # تنظيف الملف المؤقّت الجزئي قبل إعادة المحاولة
                if tmp_path and os.path.exists(tmp_path):
                    try:
                        os.remove(tmp_path)
                    except Exception:
                        pass
                tmp_path = None
                continue

        # عند النجاح، أرسل الملف؛ دون رسائل نجاح إضافية (تعليق عربي)
        try:
            with open(tmp_path, "rb") as fh:
                await update.message.reply_document(
                    document=fh,
                    filename=original_filename,
                    caption=f"📄 الملف: {original_filename}"
                )
            state['recently_sent_file_ids'].add(file_id)
        finally:
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except Exception as cleanup_err:
                    logger.warning(f"فشل تنظيف الملف المؤقّت: {cleanup_err}")


