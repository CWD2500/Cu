# Course Management Telegram Bot

A comprehensive Telegram bot integrated with a Django backend for managing and distributing course materials to students.

## Features

- **Hierarchical Course Selection**: Department → Year → Semester → Course Type → Course → Files
- **Dynamic Data Loading**: All data is fetched from Django REST API
- **Inline Keyboard Navigation**: Easy-to-use button-based interface
- **File Downloads**: Direct file downloads through Telegram
- **Multiple File Selection**: Students can download multiple files from the same course
- **MySQL Database**: Robust data storage with proper relationships

## Project Structure

```
course_bot_project/
├── django_backend/
│   ├── course_management/
│   │   ├── settings.py
│   │   ├── urls.py
│   │   └── ...
│   └── courses/
│       ├── models.py
│       ├── views.py
│       ├── serializers.py
│       └── ...
├── telegram_bot/
│   └── bot.py
├── requirements.txt
└── README.md
```

## Setup Instructions

### 1. Environment Setup

1. Clone or download this project
2. Create a virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

### 2. Database Setup

1. Install MySQL and create a database:
   ```sql
   CREATE DATABASE course_management;
   ```

2. Copy `env_example.txt` to `.env` and configure:
   ```bash
   cp env_example.txt .env
   ```

3. Update the `.env` file with your database credentials and Telegram bot token.

### 3. Django Backend Setup

1. Navigate to the Django backend:
   ```bash
   cd django_backend
   ```

2. Run migrations:
   ```bash
   python manage.py makemigrations
   python manage.py migrate
   ```

3. Create a superuser:
   ```bash
   python manage.py createsuperuser
   ```

4. Start the Django server:
   ```bash
   python manage.py runserver
   ```

5. Access the admin panel at `http://localhost:8000/admin/` to add your data.

### 4. Telegram Bot Setup

1. Create a new bot with [@BotFather](https://t.me/botfather):
   - Send `/newbot`
   - Choose a name and username
   - Copy the bot token

2. Update the `TELEGRAM_BOT_TOKEN` in your `.env` file

3. Run the bot:
   ```bash
   cd telegram_bot
   python bot.py
   ```

## Data Models

### Department
- `name`: Department name (e.g., "Computer Science")
- `description`: Optional description

### StudyYear
- `year`: Year number (e.g., 1, 2, 3, 4)
- `description`: Optional description

### Semester
- `name`: Semester name (e.g., "Fall", "Spring")
- `order`: Order number for sorting

### CourseType
- `name`: Type of course ("practical" or "theoretical")

### Course
- `name`: Course name
- `department`: Foreign key to Department
- `study_year`: Foreign key to StudyYear
- `semester`: Foreign key to Semester
- `course_type`: Foreign key to CourseType

### CourseFile
- `course`: Foreign key to Course
- `file`: File field for upload
- `original_filename`: Original filename
- `file_size`: File size in bytes
- `file_type`: File extension

## API Endpoints

### Admin Endpoints
- `GET/POST /api/departments/` - List/create departments
- `GET/POST /api/study-years/` - List/create study years
- `GET/POST /api/semesters/` - List/create semesters
- `GET/POST /api/course-types/` - List/create course types
- `GET/POST /api/courses/` - List/create courses
- `GET /api/courses/{id}/` - Get course details

### Bot-Specific Endpoints
- `GET /api/bot/departments/` - Get departments for bot
- `GET /api/bot/study-years/` - Get study years for bot
- `GET /api/bot/semesters/` - Get semesters for bot
- `GET /api/bot/course-types/` - Get course types for bot
- `GET /api/bot/courses/` - Get courses with filters
- `GET /api/bot/courses/{id}/files/` - Get course files
- `GET /api/bot/files/{id}/download/` - Download file

## Usage

1. Start the bot by sending `/start` to your bot
2. Follow the hierarchical selection:
   - Choose your department
   - Select your study year
   - Pick your semester
   - Choose course type (Practical/Theoretical)
   - Select your course
   - Download files by clicking on them

## Adding Data

Use the Django admin panel at `http://localhost:8000/admin/` to:
1. Add departments
2. Add study years
3. Add semesters
4. Add course types
5. Create courses
6. Upload course files

## Troubleshooting

### Common Issues

1. **Database Connection Error**: Check your MySQL credentials in `.env`
2. **Bot Token Error**: Ensure your Telegram bot token is correct
3. **File Upload Issues**: Check file permissions and Django media settings
4. **API Connection Error**: Ensure Django server is running on the correct port

### Logs

Check the console output for detailed error messages. The bot logs all API calls and errors.

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Test thoroughly
5. Submit a pull request

## License

This project is open source and available under the MIT License.

