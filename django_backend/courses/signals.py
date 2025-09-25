from django.db.models.signals import post_save
from django.dispatch import receiver
import logging

from .models import CourseFile, Subscription, Notification

logger = logging.getLogger(__name__)


@receiver(post_save, sender=CourseFile)
def create_notification_on_new_file(sender, instance: CourseFile, created: bool, **kwargs):
    if not created:
        return

    course = instance.course
    # Collect subscribers for the exact triplet
    subscriber_ids = list(
        Subscription.objects.filter(
            department=course.department,
            study_year=course.study_year,
            semester=course.semester,
        ).values_list('telegram_user_id', flat=True)
    )
    if not subscriber_ids:
        logger.debug("No subscribers for new file; skipping notification creation")
        return

    Notification.objects.create(
        file=instance,
        file_name=instance.original_filename,
        department=course.department,
        study_year=course.study_year,
        semester=course.semester,
        subscriber_ids=subscriber_ids,
    )
    logger.info("Notification created for file %s to %d subscribers", instance.original_filename, len(subscriber_ids))


