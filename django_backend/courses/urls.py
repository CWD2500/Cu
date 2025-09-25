from django.urls import path
from . import views

urlpatterns = [
    # Admin API endpoints
    path('departments/', views.DepartmentListCreateView.as_view(), name='department-list'),
    path('study-years/', views.StudyYearListCreateView.as_view(), name='study-year-list'),
    path('semesters/', views.SemesterListCreateView.as_view(), name='semester-list'),
    path('course-types/', views.CourseTypeListCreateView.as_view(), name='course-type-list'),
    path('courses/', views.CourseListCreateView.as_view(), name='course-list'),
    path('courses/<int:pk>/', views.CourseDetailView.as_view(), name='course-detail'),
    
    # Telegram bot specific endpoints
    path('bot/departments/', views.get_departments, name='bot-departments'),
    path('bot/study-years/', views.get_study_years, name='bot-study-years'),
    path('bot/semesters/', views.get_semesters, name='bot-semesters'),
    path('bot/course-types/', views.get_course_types, name='bot-course-types'),
    path('bot/courses/', views.get_courses_by_filters, name='bot-courses'),
    path('bot/courses/<int:course_id>/files/', views.get_course_files, name='bot-course-files'),
    path('bot/files/<int:file_id>/download/', views.download_file, name='bot-file-download'),

    # Subscriptions & Notifications
    path('bot/subscriptions/', views.bot_subscriptions, name='bot-subscriptions'),
    path('bot/subscriptions/<int:pk>/', views.bot_subscription_detail, name='bot-subscription-detail'),
    path('bot/notifications/pending/', views.notifications_pending_view, name='bot-notifications-pending'),
    path('bot/notifications/ack/', views.notifications_ack_view, name='bot-notifications-ack'),
]

