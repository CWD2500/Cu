#!/usr/bin/env python3
"""
Script to create sample data for testing the Course Management Bot
"""

import os
import sys
import django

# Add the Django project to the Python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'course_management.settings')
django.setup()

from courses.models import Department, StudyYear, Semester, CourseType, Course, CourseFile

def create_sample_data():
    """Create sample data for testing"""
    print("🔄 Creating sample data...")
    
    # Create departments
    departments = [
        {'name': 'Computer Science', 'description': 'Computer Science and Engineering Department'},
        {'name': 'Mathematics', 'description': 'Mathematics and Statistics Department'},
        {'name': 'Physics', 'description': 'Physics Department'},
        {'name': 'Chemistry', 'description': 'Chemistry Department'},
    ]
    
    dept_objects = []
    for dept_data in departments:
        dept, created = Department.objects.get_or_create(
            name=dept_data['name'],
            defaults={'description': dept_data['description']}
        )
        dept_objects.append(dept)
        print(f"✅ Department: {dept.name}")
    
    # Create study years
    years = [1, 2, 3, 4]
    year_objects = []
    for year in years:
        year_obj, created = StudyYear.objects.get_or_create(
            year=year,
            defaults={'description': f'Year {year} of study'}
        )
        year_objects.append(year_obj)
        print(f"✅ Study Year: {year_obj}")
    
    # Create semesters
    semesters = [
        {'name': 'Fall', 'order': 1, 'description': 'Fall Semester'},
        {'name': 'Spring', 'order': 2, 'description': 'Spring Semester'},
        {'name': 'Summer', 'order': 3, 'description': 'Summer Semester'},
    ]
    
    sem_objects = []
    for sem_data in semesters:
        sem, created = Semester.objects.get_or_create(
            name=sem_data['name'],
            defaults={'order': sem_data['order'], 'description': sem_data['description']}
        )
        sem_objects.append(sem)
        print(f"✅ Semester: {sem.name}")
    
    # Create course types
    course_types = [
        {'name': 'practical', 'description': 'Practical/Lab courses'},
        {'name': 'theoretical', 'description': 'Theoretical/Lecture courses'},
    ]
    
    type_objects = []
    for type_data in course_types:
        course_type, created = CourseType.objects.get_or_create(
            name=type_data['name'],
            defaults={'description': type_data['description']}
        )
        type_objects.append(course_type)
        print(f"✅ Course Type: {course_type.get_name_display()}")
    
    # Create sample courses
    sample_courses = [
        {
            'name': 'Introduction to Programming',
            'department': 'Computer Science',
            'year': 1,
            'semester': 'Fall',
            'type': 'practical',
            'description': 'Basic programming concepts and practices'
        },
        {
            'name': 'Data Structures and Algorithms',
            'department': 'Computer Science',
            'year': 2,
            'semester': 'Spring',
            'type': 'theoretical',
            'description': 'Advanced data structures and algorithm design'
        },
        {
            'name': 'Calculus I',
            'department': 'Mathematics',
            'year': 1,
            'semester': 'Fall',
            'type': 'theoretical',
            'description': 'Differential calculus and applications'
        },
        {
            'name': 'Linear Algebra',
            'department': 'Mathematics',
            'year': 2,
            'semester': 'Spring',
            'type': 'theoretical',
            'description': 'Vector spaces, linear transformations, and matrices'
        },
        {
            'name': 'General Physics I',
            'department': 'Physics',
            'year': 1,
            'semester': 'Fall',
            'type': 'practical',
            'description': 'Mechanics and thermodynamics laboratory'
        },
        {
            'name': 'Organic Chemistry',
            'department': 'Chemistry',
            'year': 2,
            'semester': 'Spring',
            'type': 'practical',
            'description': 'Organic chemistry laboratory work'
        },
    ]
    
    course_objects = []
    for course_data in sample_courses:
        dept = next(d for d in dept_objects if d.name == course_data['department'])
        year = next(y for y in year_objects if y.year == course_data['year'])
        sem = next(s for s in sem_objects if s.name == course_data['semester'])
        course_type = next(t for t in type_objects if t.name == course_data['type'])
        
        course, created = Course.objects.get_or_create(
            name=course_data['name'],
            department=dept,
            study_year=year,
            semester=sem,
            course_type=course_type,
            defaults={'description': course_data['description']}
        )
        course_objects.append(course)
        print(f"✅ Course: {course.name}")
    
    print(f"\n🎉 Sample data created successfully!")
    print(f"📊 Created:")
    print(f"   - {len(dept_objects)} Departments")
    print(f"   - {len(year_objects)} Study Years")
    print(f"   - {len(sem_objects)} Semesters")
    print(f"   - {len(type_objects)} Course Types")
    print(f"   - {len(course_objects)} Courses")
    print(f"\n📱 You can now:")
    print(f"   1. Start the Django server: python run_django.py")
    print(f"   2. Start the Telegram bot: python run_bot.py")
    print(f"   3. Add files to courses via Django admin: http://localhost:8000/admin/")

if __name__ == "__main__":
    create_sample_data()

