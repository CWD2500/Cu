from django.contrib import admin
from django.contrib.admin import AdminSite
from .models import Department, StudyYear, Semester, CourseType, Course, CourseFile, Subscription, Notification


# تخصيص عناوين واجهة المدير بالعربية
AdminSite.site_header = 'لوحة إدارة النظام'
AdminSite.site_title = 'لوحة الإدارة'
AdminSite.index_title = 'مرحبًا بك في لوحة الإدارة'


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ['name', 'description', 'created_at']
    search_fields = ['name', 'description']
    list_filter = ['created_at']


@admin.register(StudyYear)
class StudyYearAdmin(admin.ModelAdmin):
    list_display = ['year', 'description', 'created_at']
    search_fields = ['year', 'description']
    list_filter = ['year', 'created_at']


@admin.register(Semester)
class SemesterAdmin(admin.ModelAdmin):
    list_display = ['name', 'order', 'description', 'created_at']
    search_fields = ['name', 'description']
    list_filter = ['order', 'created_at']


@admin.register(CourseType)
class CourseTypeAdmin(admin.ModelAdmin):
    list_display = ['name', 'description', 'created_at']
    search_fields = ['name', 'description']
    list_filter = ['name', 'created_at']


@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = ['name', 'department', 'study_year', 'semester', 'course_type', 'created_at']
    search_fields = ['name', 'department__name', 'description']
    list_filter = ['department', 'study_year', 'semester', 'course_type', 'created_at']
    raw_id_fields = ['department', 'study_year', 'semester', 'course_type']


@admin.register(CourseFile)
class CourseFileAdmin(admin.ModelAdmin):
    list_display = ['original_filename', 'course', 'file_size', 'file_type', 'uploaded_at']
    search_fields = ['original_filename', 'course__name', 'description']
    list_filter = ['file_type', 'uploaded_at', 'course__department', 'course__study_year']
    raw_id_fields = ['course']


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ['telegram_user_id', 'department', 'study_year', 'semester', 'created_at']
    search_fields = ['telegram_user_id', 'department__name']
    list_filter = ['department', 'study_year', 'semester', 'created_at']
    raw_id_fields = ['department', 'study_year', 'semester']


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ['file_name', 'department', 'study_year', 'semester', 'created_at', 'acknowledged']
    search_fields = ['file_name', 'department__name']
    list_filter = ['acknowledged', 'created_at', 'department', 'study_year', 'semester']
    raw_id_fields = ['department', 'study_year', 'semester', 'file']
