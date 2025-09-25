from django.db import models


class Department(models.Model):
    name = models.CharField(max_length=100, unique=True, verbose_name='القسم')
    description = models.TextField(blank=True, null=True, verbose_name='الوصف')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='تاريخ الإنشاء')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='تاريخ التحديث')

    class Meta:
        ordering = ['name']
        verbose_name = 'قسم'
        verbose_name_plural = 'الأقسام'

    def __str__(self):
        return self.name


class StudyYear(models.Model):
    year = models.IntegerField(unique=True, verbose_name='السنة الدراسية')
    description = models.TextField(blank=True, null=True, verbose_name='الوصف')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='تاريخ الإنشاء')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='تاريخ التحديث')

    class Meta:
        ordering = ['year']
        verbose_name = 'سنة دراسية'
        verbose_name_plural = 'السنوات الدراسية'

    def __str__(self):
        return f"السنة {self.year}"


class Semester(models.Model):
    name = models.CharField(max_length=50, unique=True, verbose_name='الفصل')
    order = models.IntegerField(unique=True, verbose_name='الترتيب')  # 1, 2, 3, إلخ.
    description = models.TextField(blank=True, null=True, verbose_name='الوصف')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='تاريخ الإنشاء')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='تاريخ التحديث')

    class Meta:
        ordering = ['order']
        verbose_name = 'فصل'
        verbose_name_plural = 'الفصول'

    def __str__(self):
        return self.name


class CourseType(models.Model):
    COURSE_TYPE_CHOICES = [
        ('practical', 'عملي'),
        ('theoretical', 'نظري'),
    ]
    
    name = models.CharField(max_length=20, choices=COURSE_TYPE_CHOICES, unique=True, verbose_name='نوع المقرر')
    description = models.TextField(blank=True, null=True, verbose_name='الوصف')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='تاريخ الإنشاء')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='تاريخ التحديث')

    class Meta:
        ordering = ['name']
        verbose_name = 'نوع مقرر'
        verbose_name_plural = 'أنواع المقررات'

    def __str__(self):
        return self.get_name_display()


class Course(models.Model):
    name = models.CharField(max_length=200, verbose_name='اسم المقرر')
    department = models.ForeignKey(Department, on_delete=models.CASCADE, related_name='courses', verbose_name='القسم')
    study_year = models.ForeignKey(StudyYear, on_delete=models.CASCADE, related_name='courses', verbose_name='السنة الدراسية')
    semester = models.ForeignKey(Semester, on_delete=models.CASCADE, related_name='courses', verbose_name='الفصل')
    course_type = models.ForeignKey(CourseType, on_delete=models.CASCADE, related_name='courses', verbose_name='نوع المقرر')
    description = models.TextField(blank=True, null=True, verbose_name='الوصف')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='تاريخ الإنشاء')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='تاريخ التحديث')

    class Meta:
        ordering = ['department', 'study_year', 'semester', 'course_type', 'name']
        unique_together = ['name', 'department', 'study_year', 'semester', 'course_type']
        verbose_name = 'مقرر'
        verbose_name_plural = 'المقررات'

    def __str__(self):
        return f"{self.name} - {self.department.name} - السنة {self.study_year.year} - {self.semester.name} - {self.course_type.get_name_display()}"


class CourseFile(models.Model):
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name='files', verbose_name='المقرر')
    file = models.FileField(upload_to='course_files/%Y/%m/%d/', verbose_name='الملف')
    original_filename = models.CharField(max_length=255, verbose_name='اسم الملف الأصلي')
    file_size = models.BigIntegerField(verbose_name='حجم الملف (بايت)')
    file_type = models.CharField(max_length=100, verbose_name='نوع الملف')
    description = models.TextField(blank=True, null=True, verbose_name='الوصف')
    uploaded_at = models.DateTimeField(auto_now_add=True, verbose_name='تاريخ الرفع')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='تاريخ التحديث')

    class Meta:
        ordering = ['uploaded_at']
        verbose_name = 'ملف مقرر'
        verbose_name_plural = 'ملفات المقررات'

    def __str__(self):
        return f"{self.original_filename} - {self.course.name}"

    def save(self, *args, **kwargs):
        if not self.original_filename:
            self.original_filename = self.file.name
        if not self.file_size:
            self.file_size = self.file.size
        if not self.file_type:
            self.file_type = self.file.name.split('.')[-1].lower()
        super().save(*args, **kwargs)


class Subscription(models.Model):
    telegram_user_id = models.BigIntegerField(db_index=True)
    department = models.ForeignKey(Department, on_delete=models.CASCADE)
    study_year = models.ForeignKey(StudyYear, on_delete=models.CASCADE)
    semester = models.ForeignKey(Semester, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('telegram_user_id', 'department', 'study_year', 'semester')
        indexes = [
            models.Index(fields=['telegram_user_id']),
            models.Index(fields=['department', 'study_year', 'semester']),
        ]

    def __str__(self):
        return f"Sub({self.telegram_user_id}) - {self.department.name} - {self.study_year.year} - {self.semester.name}"


class Notification(models.Model):
    file = models.ForeignKey(CourseFile, on_delete=models.CASCADE, related_name='notifications', null=True, blank=True)
    file_name = models.CharField(max_length=255)
    department = models.ForeignKey(Department, on_delete=models.CASCADE)
    study_year = models.ForeignKey(StudyYear, on_delete=models.CASCADE)
    semester = models.ForeignKey(Semester, on_delete=models.CASCADE)
    subscriber_ids = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True)
    acknowledged = models.BooleanField(default=False)

    class Meta:
        indexes = [
            models.Index(fields=['acknowledged', 'created_at']),
            models.Index(fields=['department', 'study_year', 'semester']),
        ]

    def __str__(self):
        return f"Notif({self.file_name}) - {self.department.name} - {self.study_year.year} - {self.semester.name}"