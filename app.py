from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, send_from_directory
from flask_login import LoginManager, login_user, login_required, logout_user, current_user, UserMixin
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate 
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import pickle
import requests
import os
import json
from datetime import datetime

app = Flask(__name__)
app.secret_key = '067b5672a61f93277a6cd20f5feb3f9bf31c1b1b71189ab5eb0898f6f9f438fd'  # Change this in production

# Configure SQLite database
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///users.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)
migrate = Migrate(app, db)

# Configure upload folder
app.config['UPLOAD_FOLDER'] = 'static/uploads'
app.config['ALLOWED_EXTENSIONS'] = {'png', 'jpg', 'jpeg', 'gif'}
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Flask-Login setup
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# TMDB API
TMDB_API_KEY = 'fbc4939b3ed2be080aa1ea14fc947d92'
TMDB_IMAGE_BASE = 'https://image.tmdb.org/t/p/w500'

# Load recommender data
movies = pickle.load(open('movies.pkl', 'rb'))
similarity = pickle.load(open('similarity.pkl', 'rb'))

# Feedback model
class Feedback(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    type = db.Column(db.String(50), nullable=False)
    rating = db.Column(db.Integer, nullable=False)
    message = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    user = db.relationship('User', backref='feedbacks')

# Search History model
class SearchHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    query = db.Column(db.String(100), nullable=False)
    results_count = db.Column(db.Integer, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    user = db.relationship('User', backref='search_history')

# User model
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    profile_pic = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_login = db.Column(db.DateTime)
    settings = db.Column(db.String(500))  # JSON string for settings
    
    def get_settings(self):
        if self.settings:
            return json.loads(self.settings)
        return {}
    
    def set_settings(self, settings_dict):
        self.settings = json.dumps(settings_dict)
    
    @property
    def recent_searches(self):
        return SearchHistory.query.filter_by(user_id=self.id).order_by(SearchHistory.timestamp.desc()).limit(10).all()
    
    @property
    def recommendations_count(self):
        return len(self.search_history)
    
    @property
    def movies_searched(self):
        return len(set([s.query for s in self.search_history]))

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

def fetch_movie_details(movie_id):
    try:
        url = f'https://api.themoviedb.org/3/movie/{movie_id}?api_key={TMDB_API_KEY}&language=en-US'
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
        return {
            'poster': f"{TMDB_IMAGE_BASE}{data.get('poster_path', '')}" if data.get('poster_path') else 'https://via.placeholder.com/300x450?text=Poster+Not+Available',
            'plot': data.get('overview', 'Plot unavailable'),
            'year': data.get('release_date', 'N/A')[:4] if data.get('release_date') else 'N/A',
            'rating': round(float(data.get('vote_average', 0)), 1),
            'tmdb_id': data.get('id', movie_id)
        }
    except Exception as e:
        print(f"TMDB error: {e}")
        return {
            'poster': 'https://via.placeholder.com/300x450?text=Poster+Not+Available',
            'plot': 'Plot unavailable',
            'year': 'N/A',
            'rating': 0.0,
            'tmdb_id': movie_id
        }

def fetch_trending_movies():
    try:
        url = f'https://api.themoviedb.org/3/trending/movie/week?api_key={TMDB_API_KEY}'
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
        
        trending_movies = []
        for i, movie in enumerate(data.get('results', [])[:5]):  # Get top 5 trending movies
            trending_movies.append({
                'title': movie.get('title', ''),
                'poster': f"{TMDB_IMAGE_BASE}{movie.get('poster_path', '')}" if movie.get('poster_path') else 'https://via.placeholder.com/300x450?text=Poster+Not+Available',
                'year': movie.get('release_date', 'N/A')[:4] if movie.get('release_date') else 'N/A',
                'rating': round(float(movie.get('vote_average', 0)), 1),
                'tmdb_id': movie.get('id', ''),
                'delay': i * 0.1  # Add delay for animation sequence
            })
        return trending_movies
    except Exception as e:
        print(f"Error fetching trending movies: {e}")
        return []

@app.route('/')
def home():
    trending_movies = fetch_trending_movies()
    return render_template('index.html', user=current_user, trending_movies=trending_movies)

@app.route('/titles')
def titles():
    query = request.args.get('q', '').lower()
    matched = movies[movies['title'].str.lower().str.contains(query)]['title'].tolist()[:10]
    return jsonify({'titles': matched})

@app.route('/recommend', methods=['POST'])
@login_required
def recommend():
    movie = request.form.get('movie', '').strip()
    if not movie:
        return render_template('results.html', error="Please enter a movie title.", recommendations=[], user=current_user)
    try:
        matched_movies = movies[movies['title'].str.lower().str.strip().str.contains(movie.lower())]
        if matched_movies.empty:
            return render_template('results.html', error="Movie not found in dataset.", recommendations=[], user=current_user)
        idx = matched_movies.index[0]
        distances = sorted(list(enumerate(similarity[idx])), reverse=True, key=lambda x: x[1])[1:12]
        recommendations = []
        for i, _ in distances:
            movie_id = movies.iloc[i].id
            title = movies.iloc[i].title
            details = fetch_movie_details(movie_id)
            recommendations.append({
                'title': title,
                'poster': details['poster'],
                'plot': details['plot'],
                'year': details['year'],
                'rating': details['rating'],
                'tmdb_id': details['tmdb_id']
            })
        
        # Save search history
        search = SearchHistory(
            user_id=current_user.id,
            query=movie,
            results_count=len(recommendations)
        )
        db.session.add(search)
        db.session.commit()
        
        return render_template('results.html', recommendations=recommendations, user=current_user)
    except Exception as e:
        print(f"Recommendation error: {e}")
        return render_template('results.html', error="An error occurred while processing your request.", recommendations=[], user=current_user)

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'GET':
        return render_template('signup.html')
    
    name = request.form.get('full_name')
    email = request.form.get('email')
    password = request.form.get('password')

    if User.query.filter_by(email=email).first():
        flash('Email already registered.', 'danger')
        return redirect(url_for('signup'))

    hashed_password = generate_password_hash(password)
    user = User(full_name=name, email=email, password=hashed_password)
    db.session.add(user)
    db.session.commit()
    flash('Account created! Please login.', 'success')
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'GET':
        return render_template('login.html')
    
    email = request.form.get('email')
    password = request.form.get('password')

    user = User.query.filter_by(email=email).first()
    if user and check_password_hash(user.password, password):
        login_user(user, remember=True)
        user.last_login = datetime.utcnow()
        db.session.commit()
        flash('Logged in successfully!', 'success')
        return redirect(url_for('home'))
    else:
        flash('Invalid email or password.', 'danger')
        return redirect(url_for('login'))

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Logged out successfully!', 'info')
    return redirect(url_for('home'))

@app.route('/profile')
@login_required
def profile():
    # Get all feedback for the community view
    all_feedback = Feedback.query.order_by(Feedback.timestamp.desc()).all()
    return render_template('profile.html', user=current_user, all_feedback=all_feedback, theme=current_user.get_settings().get('dark_mode', True))

@app.route('/watchlist')
@login_required
def watchlist():
    return render_template('watchlist.html', user=current_user)

@app.route('/update_profile', methods=['POST'])
@login_required
def update_profile():
    try:
        user = User.query.get(current_user.id)
        
        # Update full name
        if 'full_name' in request.form:
            user.full_name = request.form['full_name']
        
        # Update password if provided
        if 'current_password' in request.form and request.form['current_password']:
            if not check_password_hash(user.password, request.form['current_password']):
                return jsonify({'success': False, 'message': 'Current password is incorrect'})
            
            if 'new_password' in request.form and request.form['new_password']:
                if request.form['new_password'] != request.form['confirm_password']:
                    return jsonify({'success': False, 'message': 'New passwords do not match'})
                
                user.password = generate_password_hash(request.form['new_password'])
        
        # Handle profile picture upload
        if 'profile_pic' in request.files:
            file = request.files['profile_pic']
            if file.filename != '' and allowed_file(file.filename):
                filename = secure_filename(f"user_{current_user.id}_{datetime.now().timestamp()}.{file.filename.rsplit('.', 1)[1].lower()}")
                file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file.save(file_path)
                
                # Delete old profile picture if it exists
                if user.profile_pic and os.path.exists(user.profile_pic.replace('/', os.sep)):
                    try:
                        os.remove(user.profile_pic.replace('/', os.sep))
                    except:
                        pass
                
                user.profile_pic = file_path.replace(os.sep, '/')
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'full_name': user.full_name,
            'profile_pic': url_for('static', filename=user.profile_pic.replace('static/', '')) if user.profile_pic else None
        })
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@app.route('/submit_feedback', methods=['POST'])
@login_required
def submit_feedback():
    try:
        feedback_type = request.form.get('type')
        rating = int(request.form.get('rating', 0))
        message = request.form.get('message')
        
        if not all([feedback_type, rating, message]):
            return jsonify({'success': False, 'message': 'All fields are required'})
        
        feedback = Feedback(
            user_id=current_user.id,
            type=feedback_type,
            rating=rating,
            message=message
        )
        
        db.session.add(feedback)
        db.session.commit()
        
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@app.route('/update_settings', methods=['POST'])
@login_required
def update_settings():
    try:
        user = User.query.get(current_user.id)
        settings = user.get_settings()
        
        # Update settings based on form data
        settings['email_notifications'] = request.form.get('email_notifications', 'all')
        settings['dark_mode'] = 'darkMode' in request.form
        
        user.set_settings(settings)
        db.session.commit()
        
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@app.route('/delete_account', methods=['POST'])
@login_required
def delete_account():
    try:
        password = request.form.get('password')
        
        if not check_password_hash(current_user.password, password):
            return jsonify({'success': False, 'message': 'Incorrect password'})
        
        # Delete profile picture if it exists
        if current_user.profile_pic and os.path.exists(current_user.profile_pic.replace('/', os.sep)):
            try:
                os.remove(current_user.profile_pic.replace('/', os.sep))
            except:
                pass
        
        # Delete user from database
        db.session.delete(current_user)
        db.session.commit()
        
        logout_user()
        
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)