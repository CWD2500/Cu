from rest_framework import serializers
from .models import Department, StudyYear, Semester, CourseType, Course, CourseFile


class DepartmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Department
        fields = ['id', 'name', 'description', 'created_at', 'updated_at']


class StudyYearSerializer(serializers.ModelSerializer):
    class Meta:
        model = StudyYear
        fields = ['id', 'year', 'description', 'created_at', 'updated_at']


class SemesterSerializer(serializers.ModelSerializer):
    class Meta:
        model = Semester
        fields = ['id', 'name', 'order', 'description', 'created_at', 'updated_at']


class CourseTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = CourseType
        fields = ['id', 'name', 'description', 'created_at', 'updated_at']


class CourseFileSerializer(serializers.ModelSerializer):
    file_url = serializers.SerializerMethodField()
    
    class Meta:
        model = CourseFile
        fields = ['id', 'original_filename', 'file_url', 'file_size', 'file_type', 'description', 'uploaded_at']
    
    def get_file_url(self, obj):
        request = self.context.get('request')
        if request:
            return request.build_absolute_uri(obj.file.url)
        return obj.file.url


class CourseSerializer(serializers.ModelSerializer):
    department = DepartmentSerializer(read_only=True)
    study_year = StudyYearSerializer(read_only=True)
    semester = SemesterSerializer(read_only=True)
    course_type = CourseTypeSerializer(read_only=True)
    files = CourseFileSerializer(many=True, read_only=True)
    
    class Meta:
        model = Course
        fields = ['id', 'name', 'department', 'study_year', 'semester', 'course_type', 'description', 'files', 'created_at', 'updated_at']


class CourseListSerializer(serializers.ModelSerializer):
    department = DepartmentSerializer(read_only=True)
    study_year = StudyYearSerializer(read_only=True)
    semester = SemesterSerializer(read_only=True)
    course_type = CourseTypeSerializer(read_only=True)
    files_count = serializers.SerializerMethodField()
    
    class Meta:
        model = Course
        fields = ['id', 'name', 'department', 'study_year', 'semester', 'course_type', 'description', 'files_count', 'created_at', 'updated_at']
    
    def get_files_count(self, obj):
        return obj.files.count()

