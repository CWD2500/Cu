from rest_framework import generics, status
from rest_framework.decorators import api_view
from rest_framework.response import Response
from django.http import FileResponse
from django.shortcuts import get_object_or_404
from .models import Department, StudyYear, Semester, CourseType, Course, CourseFile, Subscription, Notification
from .serializers import (
    DepartmentSerializer, StudyYearSerializer, SemesterSerializer,
    CourseTypeSerializer, CourseSerializer, CourseListSerializer, CourseFileSerializer
)


class DepartmentListCreateView(generics.ListCreateAPIView):
    queryset = Department.objects.all()
    serializer_class = DepartmentSerializer


class StudyYearListCreateView(generics.ListCreateAPIView):
    queryset = StudyYear.objects.all()
    serializer_class = StudyYearSerializer


class SemesterListCreateView(generics.ListCreateAPIView):
    queryset = Semester.objects.all()
    serializer_class = SemesterSerializer


class CourseTypeListCreateView(generics.ListCreateAPIView):
    queryset = CourseType.objects.all()
    serializer_class = CourseTypeSerializer


class CourseListCreateView(generics.ListCreateAPIView):
    queryset = Course.objects.select_related('department', 'study_year', 'semester', 'course_type').prefetch_related('files')
    serializer_class = CourseListSerializer

    def get_serializer_class(self):
        if self.request.method == 'GET':
            return CourseListSerializer
        return CourseSerializer


class CourseDetailView(generics.RetrieveAPIView):
    queryset = Course.objects.select_related('department', 'study_year', 'semester', 'course_type').prefetch_related('files')
    serializer_class = CourseSerializer


@api_view(['GET'])
def get_departments(request):
    """Get all departments for Telegram bot"""
    departments = Department.objects.all()
    serializer = DepartmentSerializer(departments, many=True)
    return Response(serializer.data)


@api_view(['GET'])
def get_study_years(request):
    """Get all study years for Telegram bot"""
    study_years = StudyYear.objects.all()
    serializer = StudyYearSerializer(study_years, many=True)
    return Response(serializer.data)


@api_view(['GET'])
def get_semesters(request):
    """Get all semesters for Telegram bot"""
    semesters = Semester.objects.all()
    serializer = SemesterSerializer(semesters, many=True)
    return Response(serializer.data)


@api_view(['GET'])
def get_course_types(request):
    """Get all course types for Telegram bot"""
    course_types = CourseType.objects.all()
    serializer = CourseTypeSerializer(course_types, many=True)
    return Response(serializer.data)


@api_view(['GET'])
def get_courses_by_filters(request):
    """Get courses filtered by department, year, semester, and course type"""
    department_id = request.GET.get('department_id')
    study_year_id = request.GET.get('study_year_id')
    semester_id = request.GET.get('semester_id')
    course_type_id = request.GET.get('course_type_id')
    
    courses = Course.objects.select_related('department', 'study_year', 'semester', 'course_type')
    
    if department_id:
        courses = courses.filter(department_id=department_id)
    if study_year_id:
        courses = courses.filter(study_year_id=study_year_id)
    if semester_id:
        courses = courses.filter(semester_id=semester_id)
    if course_type_id:
        courses = courses.filter(course_type_id=course_type_id)
    
    serializer = CourseListSerializer(courses, many=True)
    return Response(serializer.data)


@api_view(['GET'])
def get_course_files(request, course_id):
    """Get all files for a specific course"""
    course = get_object_or_404(Course, id=course_id)
    files = course.files.all()
    serializer = CourseFileSerializer(files, many=True, context={'request': request})
    return Response(serializer.data)


@api_view(['GET'])
def download_file(request, file_id):
    """Download a specific file"""
    course_file = get_object_or_404(CourseFile, id=file_id)
    
    response = FileResponse(
        course_file.file,
        as_attachment=True,
        filename=course_file.original_filename
    )
    return response


# --- Subscriptions API for bot ---
@api_view(['GET', 'POST'])
def bot_subscriptions(request):
    if request.method == 'GET':
        telegram_user_id = request.GET.get('telegram_user_id')
        if not telegram_user_id:
            return Response({'detail': 'telegram_user_id is required'}, status=status.HTTP_400_BAD_REQUEST)
        subs = Subscription.objects.filter(telegram_user_id=telegram_user_id).select_related('department', 'study_year', 'semester')
        data = [{
            'id': s.id,
            'telegram_user_id': s.telegram_user_id,
            'department_id': s.department_id,
            'department_name': s.department.name,
            'study_year_id': s.study_year_id,
            'study_year_name': getattr(s.study_year, 'year', str(s.study_year)),
            'semester_id': s.semester_id,
            'semester_name': s.semester.name,
        } for s in subs]
        return Response(data)

    # POST
    payload = request.data
    required = ['telegram_user_id', 'department_id', 'study_year_id', 'semester_id']
    if any(k not in payload for k in required):
        return Response({'detail': 'Missing required fields'}, status=status.HTTP_400_BAD_REQUEST)
    try:
        telegram_user_id = int(payload['telegram_user_id'])
        department = Department.objects.get(id=payload['department_id'])
        study_year = StudyYear.objects.get(id=payload['study_year_id'])
        semester = Semester.objects.get(id=payload['semester_id'])
    except Exception:
        return Response({'detail': 'Invalid fields'}, status=status.HTTP_400_BAD_REQUEST)

    sub, _ = Subscription.objects.get_or_create(
        telegram_user_id=telegram_user_id,
        department=department,
        study_year=study_year,
        semester=semester,
    )
    return Response({
        'id': sub.id,
        'telegram_user_id': sub.telegram_user_id,
        'department_id': sub.department_id,
        'department_name': department.name,
        'study_year_id': sub.study_year_id,
        'study_year_name': getattr(study_year, 'year', str(study_year)),
        'semester_id': sub.semester_id,
        'semester_name': semester.name,
    }, status=status.HTTP_201_CREATED)


@api_view(['DELETE'])
def bot_subscription_detail(request, pk):
    try:
        sub = Subscription.objects.get(pk=pk)
    except Subscription.DoesNotExist:
        return Response({'detail': 'Not found'}, status=status.HTTP_404_NOT_FOUND)
    sub.delete()
    return Response({'ok': True})


# --- Notifications API for bot ---
@api_view(['GET'])
def notifications_pending_view(request):
    pending = Notification.objects.filter(acknowledged=False).select_related('department', 'study_year', 'semester').order_by('created_at')[:100]
    data = [{
        'id': n.id,
        'file_name': n.file_name,
        'department_name': n.department.name,
        'year_name': getattr(n.study_year, 'year', str(n.study_year)),
        'semester_name': n.semester.name,
        'subscriber_ids': n.subscriber_ids,
    } for n in pending]
    return Response(data)


@api_view(['POST'])
def notifications_ack_view(request):
    ids = request.data.get('ids')
    if not isinstance(ids, list):
        return Response({'detail': 'ids must be a list'}, status=status.HTTP_400_BAD_REQUEST)
    Notification.objects.filter(id__in=ids).update(acknowledged=True)
    return Response({'ok': True, 'count': len(ids)})

