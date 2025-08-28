#!/usr/bin/env python3
import os
import zipfile
import io

# Create a zip file in memory
zip_buffer = io.BytesIO()
with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zipf:
    
    # 1. app.py
    zipf.writestr('app.py', '''import os
import torch
import numpy as np
from flask import Flask, request, render_template, redirect, url_for, flash, jsonify
from flask_admin import Admin, AdminIndexView, expose
from flask_admin.contrib.sqla import ModelView
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
import sqlite3
from datetime import datetime
import wave
import contextlib

# Import project modules
from config import Config
from models.database import db
from models.models import Configuration, AudioFile, User
from utils.audio_processing import process_audio_with_vad, get_audio_duration
from utils.vad_utils import load_vad_model

# Initialize Flask app
app = Flask(__name__)
app.config.from_object(Config)

# Initialize database
db.init_app(app)

# Initialize login manager
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# Load Silero VAD model
vad_model, get_speech_timestamps = load_vad_model()

# Custom admin index view
class MyAdminIndexView(AdminIndexView):
    def is_accessible(self):
        return current_user.is_authenticated and current_user.is_admin
    
    def inaccessible_callback(self, name, **kwargs):
        return redirect(url_for('login'))

# Custom model view for admin
class SecureModelView(ModelView):
    def is_accessible(self):
        return current_user.is_authenticated and current_user.is_admin
    
    def inaccessible_callback(self, name, **kwargs):
        return redirect(url_for('login'))

# Initialize admin panel
admin = Admin(app, name='Stanza Automation Admin', template_mode='bootstrap3', index_view=MyAdminIndexView())
admin.add_view(SecureModelView(Configuration, db.session))
admin.add_view(SecureModelView(AudioFile, db.session))
admin.add_view(SecureModelView(User, db.session))

# Create upload directory if it doesn't exist
if not os.path.exists(app.config['UPLOAD_FOLDER']):
    os.makedirs(app.config['UPLOAD_FOLDER'])

# Routes
@app.route('/')
def index():
    audio_files = AudioFile.query.order_by(AudioFile.uploaded_at.desc()).limit(10).all()
    return render_template('index.html', audio_files=audio_files)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()
        
        if user and user.check_password(password):
            login_user(user)
            next_page = request.args.get('next')
            return redirect(next_page or url_for('index'))
        else:
            flash('Invalid username or password')
    
    return render_template('admin/login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))

@app.route('/upload', methods=['GET', 'POST'])
def upload_file():
    if request.method == 'POST':
        # Check if the post request has the file part
        if 'file' not in request.files:
            flash('No file part')
            return redirect(request.url)
        
        file = request.files['file']
        
        # If user does not select file, browser also
        # submit an empty part without filename
        if file.filename == '':
            flash('No selected file')
            return redirect(request.url)
        
        if file:
            # Save the file
            filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{file.filename}"
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(filepath)
            
            # Get duration
            duration = get_audio_duration(filepath)
            
            # Save to database
            audio_file = AudioFile(
                filename=filename,
                original_filename=file.filename,
                duration=duration
            )
            db.session.add(audio_file)
            db.session.commit()
            
            flash(f'File successfully uploaded. Duration: {duration:.2f} seconds.')
            return redirect(url_for('index'))
    
    return render_template('upload.html')

@app.route('/process/<int:file_id>')
@login_required
def process_file(file_id):
    audio_file = AudioFile.query.get_or_404(file_id)
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], audio_file.filename)
    
    # Process with VAD
    speech_segments = process_audio_with_vad(filepath, vad_model, get_speech_timestamps)
    
    # Update database
    audio_file.processed = True
    audio_file.segments = len(speech_segments)
    db.session.commit()
    
    # Here you would typically integrate with your existing Stanza automation
    # For now, we'll just return the segments found
    return render_template('process_result.html', 
                          audio_file=audio_file, 
                          segments=speech_segments)

# API endpoints
@app.route('/api/config')
def get_config():
    configs = Configuration.query.all()
    return {config.name: config.value for config in configs}

@app.route('/api/upload', methods=['POST'])
def api_upload():
    if 'file' not in request.files:
        return {'error': 'No file provided'}, 400
    
    file = request.files['file']
    if file.filename == '':
        return {'error': 'No filename'}, 400
    
    filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{file.filename}"
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(filepath)
    
    duration = get_audio_duration(filepath)
    
    audio_file = AudioFile(
        filename=filename,
        original_filename=file.filename,
        duration=duration
    )
    db.session.add(audio_file)
    db.session.commit()
    
    return {
        'id': audio_file.id,
        'filename': audio_file.original_filename,
        'duration': duration
    }

# Error handlers
@app.errorhandler(413)
def too_large(e):
    return "File is too large", 413

@app.errorhandler(404)
def not_found(e):
    return render_template('404.html'), 404

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        
        # Add default admin user if it doesn't exist
        if not User.query.filter_by(username='admin').first():
            admin_user = User(username='admin', is_admin=True)
            admin_user.set_password('admin')
            db.session.add(admin_user)
        
        # Add default configurations if they don't exist
        default_configs = [
            ('vad_threshold', '0.5', 'Voice activity detection threshold'),
            ('min_speech_duration', '0.5', 'Minimum speech duration in seconds'),
            ('max_speech_duration', '10.0', 'Maximum speech duration in seconds'),
            ('sample_rate', '16000', 'Audio sample rate'),
            ('stanza_model', 'en', 'Stanza model to use for processing'),
            ('output_format', 'text', 'Output format (text/json)'),
        ]
        
        for name, value, description in default_configs:
            if not Configuration.query.filter_by(name=name).first():
                config = Configuration(name=name, value=value, description=description)
                db.session.add(config)
        
        db.session.commit()
    
    app.run(debug=True, port=5000)
''')

    # 2. config.py
    zipf.writestr('config.py', '''import os
from datetime import timedelta

basedir = os.path.abspath(os.path.dirname(__file__))

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'your-secret-key-here'
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or \\
        'sqlite:///' + os.path.join(basedir, 'app.db')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    UPLOAD_FOLDER = os.path.join(basedir, 'uploads')
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB max file size
    ADMIN_USERNAME = os.environ.get('ADMIN_USERNAME') or 'admin'
    ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD') or 'admin'
    REMEMBER_COOKIE_DURATION = timedelta(days=7)
''')

    # 3. requirements.txt
    zipf.writestr('requirements.txt', '''flask==2.3.3
flask-admin==1.6.1
flask-sqlalchemy==3.0.5
flask-login==0.6.2
silero-vad==1.0.0
torch>=1.9.0
torchaudio>=0.9.0
scipy>=1.7.3
numpy>=1.21.0
wave>=0.0.2
python-dotenv>=0.19.0
''')

    # 4. run.py
    zipf.writestr('run.py', '''from app import app

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
''')

    # 5. Create models directory and files
    zipf.writestr('models/__init__.py', '')
    zipf.writestr('models/database.py', '''from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()
''')
    zipf.writestr('models/models.py', '''from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin

from .database import db

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False)
    password_hash = db.Column(db.String(128))
    is_admin = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def __repr__(self):
        return f'<User {self.username}>'

class Configuration(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    value = db.Column(db.String(500), nullable=False)
    description = db.Column(db.String(500))
    updated_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<Configuration {self.name}>'

class AudioFile(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(200), nullable=False)
    original_filename = db.Column(db.String(200), nullable=False)
    duration = db.Column(db.Float)  # in seconds
    segments = db.Column(db.Integer, default=0)
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)
    processed = db.Column(db.Boolean, default=False)
    processed_at = db.Column(db.DateTime)

    def __repr__(self):
        return f'<AudioFile {self.original_filename}>'
''')

    # 6. Create utils directory and files
    zipf.writestr('utils/__init__.py', '')
    zipf.writestr('utils/audio_processing.py', '''import os
import wave
import contextlib
import numpy as np
import scipy.io.wavfile as wav

def get_audio_duration(filepath):
    """Get duration of audio file in seconds"""
    try:
        with contextlib.closing(wave.open(filepath, 'r')) as f:
            frames = f.getnframes()
            rate = f.getframerate()
            return frames / float(rate)
    except:
        return 0

def process_audio_with_vad(audio_path, vad_model, get_speech_timestamps):
    """Process audio file with Silero VAD"""
    try:
        # Load audio file
        sample_rate, audio_data = wav.read(audio_path)
        
        # Convert to mono if stereo
        if len(audio_data.shape) > 1:
            audio_data = audio_data.mean(axis=1)
        
        # Convert to float32
        audio_data = audio_data.astype(np.float32) / 32768.0
        
        # Get speech timestamps
        speech_timestamps = get_speech_timestamps(audio_data, vad_model, sampling_rate=sample_rate)
        
        return speech_timestamps
    except Exception as e:
        print(f"Error processing audio: {e}")
        return []
''')
    zipf.writestr('utils/vad_utils.py', '''import torch
from silero_vad import load_silero_vad

def load_vad_model():
    """Load Silero VAD model"""
    torch.set_num_threads(1)
    model, utils = load_silero_vad()
    get_speech_timestamps = utils[0]
    return model, get_speech_timestamps
''')

    # 7. Create templates directory and files
    zipf.writestr('templates/base.html', '''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{% block title %}Stanza Automation{% endblock %}</title>
    <link rel="stylesheet" href="https://stackpath.bootstrapcdn.com/bootstrap/4.3.1/css/bootstrap.min.css">
    <link rel="stylesheet" href="{{ url_for('static', filename='css/style.css') }}">
</head>
<body>
    <nav class="navbar navbar-expand-lg navbar-dark bg-dark">
        <a class="navbar-brand" href="{{ url_for('index') }}">Stanza Automation</a>
        <button class="navbar-toggler" type="button" data-toggle="collapse" data-target="#navbarNav">
            <span class="navbar-toggler-icon"></span>
        </button>
        <div class="collapse navbar-collapse" id="navbarNav">
            <ul class="navbar-nav mr-auto">
                <li class="nav-item">
                    <a class="nav-link" href="{{ url_for('index') }}">Home</a>
                </li>
                <li class="nav-item">
                    <a class="nav-link" href="{{ url_for('upload_file') }}">Upload</a>
                </li>
                {% if current_user.is_authenticated and current_user.is_admin %}
                <li class="nav-item">
                    <a class="nav-link" href="/admin/">Admin</a>
                </li>
                {% endif %}
            </ul>
            <ul class="navbar-nav">
                {% if current_user.is_authenticated %}
                <li class="nav-item">
                    <span class="navbar-text">Hello, {{ current_user.username }}</span>
                </li>
                <li class="nav-item">
                    <a class="nav-link" href="{{ url_for('logout') }}">Logout</a>
                </li>
                {% else %}
                <li class="nav-item">
                    <a class="nav-link" href="{{ url_for('login') }}">Login</a>
                </li>
                {% endif %}
            </ul>
        </div>
    </nav>

    <div class="container mt-4">
        {% with messages = get_flashed_messages() %}
            {% if messages %}
                {% for message in messages %}
                    <div class="alert alert-info alert-dismissible fade show" role="alert">
                        {{ message }}
                        <button type="button" class="close" data-dismiss="alert">
                            <span>&times;</span>
                        </button>
                    </div>
                {% endfor %}
            {% endif %}
        {% endwith %}

        {% block content %}{% endblock %}
    </div>

    <footer class="footer mt-5 py-3 bg-light">
        <div class="container">
            <span class="text-muted">Stanza Automation with Silero VAD</span>
        </div>
    </footer>

    <script src="https://code.jquery.com/jquery-3.3.1.slim.min.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/popper.js/1.14.7/umd/popper.min.js"></script>
    <script src="https://stackpath.bootstrapcdn.com/bootstrap/4.3.1/js/bootstrap.min.js"></script>
    <script src="{{ url_for('static', filename='js/script.js') }}"></script>
</body>
</html>
''')
    zipf.writestr('templates/index.html', '''{% extends "base.html" %}

{% block title %}Home - Stanza Automation{% endblock %}

{% block content %}
<div class="jumbotron">
    <h1 class="display-4">Stanza Automation with Silero VAD</h1>
    <p class="lead">Upload audio files for processing with voice activity detection and Stanza NLP.</p>
    <hr class="my-4">
    <a class="btn btn-primary btn-lg" href="{{ url_for('upload_file') }}" role="button">Upload Audio</a>
</div>

<h2>Recent Uploads</h2>
{% if audio_files %}
<table class="table table-striped table-hover">
    <thead class="thead-dark">
        <tr>
            <th>Filename</th>
            <th>Duration</th>
            <th>Uploaded</th>
            <th>Status</th>
            <th>Actions</th>
        </tr>
    </thead>
    <tbody>
        {% for file in audio_files %}
        <tr>
            <td>{{ file.original_filename }}</td>
            <td>{{ "%.2f"|format(file.duration) }} seconds</td>
            <td>{{ file.uploaded_at.strftime('%Y-%m-%d %H:%M') }}</td>
            <td>
                {% if file.processed %}
                    <span class="badge badge-success">Processed ({{ file.segments }} segments)</span>
                {% else %}
                    <span class="badge badge-warning">Pending</span>
                {% endif %}
            </td>
            <td>
                {% if not file.processed and current_user.is_authenticated %}
                    <a href="{{ url_for('process_file', file_id=file.id) }}" class="btn btn-sm btn-primary">Process</a>
                {% else %}
                    <button class="btn btn-sm btn-secondary" disabled>View Results</button>
                {% endif %}
            </td>
        </tr>
        {% endfor %}
    </tbody>
</table>
{% else %}
<div class="alert alert-info">No audio files uploaded yet.</div>
{% endif %}
{% endblock %}
''')
    zipf.writestr('templates/upload.html', '''{% extends "base.html" %}

{% block title %}Upload - Stanza Automation{% endblock %}

{% block content %}
<div class="row">
    <div class="col-md-8 offset-md-2">
        <div class="card">
            <div class="card-header">
                <h2>Upload Audio File</h2>
            </div>
            <div class="card-body">
                <form method="post" enctype="multipart/form-data">
                    <div class="form-group">
                        <label for="file">Select audio file (WAV, MP3, etc.):</label>
                        <input type="file" class="form-control-file" id="file" name="file" accept="audio/*" required>
                        <small class="form-text text-muted">Maximum file size: 16MB</small>
                    </div>
                    <button type="submit" class="btn btn-primary">Upload</button>
                    <a href="{{ url_for('index') }}" class="btn btn-secondary">Cancel</a>
                </form>
            </div>
        </div>
    </div>
</div>
{% endblock %}
''')
    zipf.writestr('templates/process_result.html', '''{% extends "base.html" %}

{% block title %}Processing Results - Stanza Automation{% endblock %}

{% block content %}
<div class="card">
    <div class="card-header">
        <h2>Processing Results: {{ audio_file.original_filename }}</h2>
    </div>
    <div class="card-body">
        <div class="row mb-4">
            <div class="col-md-6">
                <h5>File Information</h5>
                <ul class="list-group">
                    <li class="list-group-item">Original filename: {{ audio_file.original_filename }}</li>
                    <li class="list-group-item">Duration: {{ "%.2f"|format(audio_file.duration) }} seconds</li>
                    <li class="list-group-item">Uploaded: {{ audio_file.uploaded_at.strftime('%Y-%m-%d %H:%M') }}</li>
                    <li class="list-group-item">Speech segments detected: {{ segments|length }}</li>
                </ul>
            </div>
        </div>

        <h5>Speech Segments</h5>
        {% if segments %}
        <div class="table-responsive">
            <table class="table table-striped">
                <thead class="thead-dark">
                    <tr>
                        <th>Segment</th>
                        <th>Start</th>
                        <th>End</th>
                        <th>Duration</th>
                    </tr>
                </thead>
                <tbody>
                    {% for segment in segments %}
                    <tr>
                        <td>{{ loop.index }}</td>
                        <td>{{ "%.2f"|format(segment.start) }}s</td>
                        <td>{{ "%.2f"|format(segment.end) }}s</td>
                        <td>{{ "%.2f"|format(segment.end - segment.start) }}s</td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
        {% else %}
        <div class="alert alert-warning">No speech segments detected.</div>
        {% endif %}
        
        <a href="{{ url_for('index') }}" class="btn btn-primary">Back to Home</a>
    </div>
</div>
{% endblock %}
''')
    zipf.writestr('templates/admin/login.html', '''{% extends "base.html" %}

{% block title %}Login - Stanza Automation{% endblock %}

{% block content %}
<div class="row justify-content-center">
    <div class="col-md-6">
        <div class="card">
            <div class="card-header">
                <h2>Admin Login</h2>
            </div>
            <div class="card-body">
                <form method="post">
                    <div class="form-group">
                        <label for="username">Username</label>
                        <input type="text" class="form-control" id="username" name="username" required>
                    </div>
                    <div class="form-group">
                        <label for="password">Password</label>
                        <input type="password" class="form-control" id="password" name="password" required>
                    </div>
                    <button type="submit" class="btn btn-primary">Login</button>
                </form>
            </div>
        </div>
    </div>
</div>
{% endblock %}
''')
    zipf.writestr('templates/404.html', '''{% extends "base.html" %}

{% block title %}Page Not Found - Stanza Automation{% endblock %}

{% block content %}
<div class="row justify-content-center">
    <div class="col-md-6 text-center">
        <h1>404 - Page Not Found</h1>
        <p>The page you are looking for does not exist.</p>
        <a href="{{ url_for('index') }}" class="btn btn-primary">Return to Home</a>
    </div>
</div>
{% endblock %}
''')

    # 8. Create static directory and files
    zipf.writestr('static/css/style.css', '''body {
    padding-bottom: 60px;
}

.footer {
    position: fixed;
    bottom: 0;
    width: 100%;
    height: 60px;
    line-height: 60px;
}

.jumbotron {
    background-color: #f8f9fa;
    border-radius: 0.3rem;
}

.table th {
    border-top: none;
}

.card {
    box-shadow: 0 0.125rem 0.25rem rgba(0, 0, 0, 0.075);
    margin-bottom: 1.5rem;
}

.card-header {
    background-color: #f8f9fa;
    border-bottom: 1px solid #e3e6f0;
}
''')
    zipf.writestr('static/js/script.js', '''// Basic JavaScript for additional functionality
document.addEventListener('DOMContentLoaded', function() {
    // Auto-dismiss alerts after 5 seconds
    setTimeout(function() {
        $('.alert').alert('close');
    }, 5000);
    
    // File upload validation
    const fileInput = document.getElementById('file');
    if (fileInput) {
        fileInput.addEventListener('change', function() {
            const file = this.files[0];
            if (file) {
                const fileSize = file.size / 1024 / 1024; // MB
                if (fileSize > 16) {
                    alert('File size exceeds 16MB limit. Please choose a smaller file.');
                    this.value = '';
                }
            }
        });
    }
});
''')

    # 9. Create .env file
    zipf.writestr('.env', '''SECRET_KEY=your-super-secret-key-here
ADMIN_USERNAME=admin
ADMIN_PASSWORD=change-this-password
''')

    # 10. Create README.md
    zipf.writestr('README.md', '''# Stanza Automation with Silero VAD

Enhanced version of the Stanza Automation system with Silero Voice Activity Detection, web upload interface, and admin panel.

## Features

- Silero VAD integration for speech detection
- Web-based audio file upload
- Admin panel for configuration management
- User authentication system
- REST API for programmatic access

## Installation

1. Extract all files from the zip
2. Install dependencies: `pip install -r requirements.txt`
3. Set up environment variables in `.env` file
4. Run the application: `python run.py`

## Usage

1. Access the web interface at http://localhost:5000
2. Upload audio files through the web interface
3. Process files with Silero VAD
4. Configure settings through the admin panel (/admin/)

## Admin Access

Default admin credentials:
- Username: admin
- Password: admin

Change these in production by setting the ADMIN_USERNAME and ADMIN_PASSWORD environment variables.

## API Endpoints

- GET /api/config - Get current configuration
- POST /api/upload - Upload audio file via API
''')

    # 11. Create empty directories
    zipf.writestr('uploads/.gitkeep', '')
    zipf.writestr('instance/.gitkeep', '')

# Get the zip file data
zip_data = zip_buffer.getvalue()

# Save the zip file
with open('stanza_automation_enhanced.zip', 'wb') as f:
    f.write(zip_data)

print("Zip file created: stanza_automation_enhanced.zip")