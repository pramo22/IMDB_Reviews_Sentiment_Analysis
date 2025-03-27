from flask import Flask, request, jsonify, render_template, flash, redirect, url_for
import joblib
from sklearn.feature_extraction.text import TfidfVectorizer
import nltk
from flask_sqlalchemy import SQLAlchemy
from flask_bcrypt import Bcrypt
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from models import db, Reviews, Users # Assuming you have these models
from collections import deque
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime, timedelta
from sklearn.feature_extraction.text import CountVectorizer
import logging
import random
import numpy as np
from sklearn.linear_model import LogisticRegression
nltk.download('punkt')
# Create Flask app
app = Flask(__name__, static_folder='static')
app.config["SECRET_KEY"] = "thisisasecretkey"
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///users.db"
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.secret_key = '714d2cfbf4fd011fca0c5817bc07998498f7168a9d5a2d38c8082ed0f09c61d7'

db.init_app(app)
bcrypt = Bcrypt(app)
login_manager = LoginManager(app)
login_manager.login_view = "login"

# Load the saved SVM model and TF-IDF vectorizer
svm_model = joblib.load('svm_sentiment_model.pkl')
vectorizer = joblib.load('tfidf_vectorizer.pkl')
nltk.download('stopwords')

@login_manager.user_loader
def load_users(user_id):
    return Users.query.get(int(user_id))


@app.route('/')
def index():
    return render_template('index.html', user=current_user) 

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == "POST":
        data = request.form
        password = data['password']
        confirm_password = data['confirm_password']
        if password != confirm_password:
            flash("Passwords do not match", "danger")
            return render_template('register.html')

        # Check if the email already exists
        email = data['email']
        existing_user = Users.query.filter_by(email=email).first()
        if existing_user:
            flash("An account with this name already exists.", "danger")
            return render_template('register.html')
        hashed_password = bcrypt.generate_password_hash(data['password']).decode('utf-8')
        new_user = Users(username=data['username'],email=email, password=hashed_password)
        db.session.add(new_user)
        db.session.commit()
        flash('Account created successfully! You can log in now.', 'success')
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == "POST":
        data = request.form
        user = Users.query.filter_by(username=data["username"]).first()

        if user and bcrypt.check_password_hash(user.password, data["password"]):
            login_user(user)
            return redirect(url_for('index'))
        else:
            flash("Invalid username and password", "danger")
            return redirect(url_for('login'))
    return render_template('login.html')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash("Logged out successfully", "info")
    return redirect(url_for('login'))


# Define the sentiment prediction route
# Task queue for prioritization
@app.route('/delete_review/<int:review_id>', methods=['GET'])
@login_required
def delete_review(review_id):
    review = Reviews.query.get(review_id)  # Get the review by ID
    if review and review.user_id == current_user.id:  # Ensure the review belongs to the current user
        db.session.delete(review)  # Delete the review
        db.session.commit()  # Commit the change to the database
    else:
        flash("Review not found or you're not authorized to delete this review.", "danger")
    
    return redirect(url_for('dashboard'))  # Redirect back to the dashboard

    

scheduler = BackgroundScheduler()

def auto_update_status():
    logging.info("Running automatic scheduling to update task statuses.")
    
    current_time = datetime.now()  # Get the current time
    
    reviews = Reviews.query.all()  # Fetch all reviews (tasks)
    for review in reviews:
        review.update_task(current_time)  # Update task status based on the current time
        db.session.commit()  # Commit the changes to the database
    logging.info("Automatic scheduling completed.")

scheduler.add_job(func=auto_update_status, trigger="interval", minutes=2)
scheduler.start()


def predict_sentiment(review):
    review_vector = vectorizer.transform([review]).toarray()
    prediction = svm_model.predict(review_vector)
    sentiment_map = {0: 'Negative', 1: 'Neutral', 2: 'Positive'}
    return sentiment_map[prediction[0]]



@app.route('/dashboard')
@login_required
def dashboard():
    # Fetch all reviews of the current user, along with sentiment and priority
    reviews = Reviews.query.filter_by(user_id=current_user.id).all()

    total_reviews = Reviews.query.filter_by(user_id=current_user.id).count()
    positive_reviews = Reviews.query.filter_by(sentiment='Positive', user_id=current_user.id).count()
    neutral_reviews = Reviews.query.filter_by(sentiment='Neutral', user_id=current_user.id).count()
    negative_reviews = Reviews.query.filter_by(sentiment='Negative', user_id=current_user.id).count()
    future_trend = predict_future_sentiment(current_user.username)
    # Add urgency based on workload and deadline
    recommended_reviews = []
    for review in reviews:
        review.update_task()
        recommended_reviews.append(review)
    recommended_reviews = sorted(recommended_reviews, key=lambda r:(r.priority,r.deadline))

    # Render the dashboard and pass reviews, sentiment, and priority to the template
    return render_template('dashboard.html', user=current_user, reviews=recommended_reviews,
                           total_reviews=total_reviews, positive_reviews=positive_reviews,
                           neutral_reviews=neutral_reviews, negative_reviews=negative_reviews, future_trend=future_trend)



@app.route('/submit_review', methods=['POST'])
@login_required
def submit_review():
    content = request.form['content']  # Review content from the form
    print(f"Review Content: {content}")  # Debugging line
    user_id = current_user.id  # Get the current logged-in user's ID
    
    # Step 1: Predict sentiment
    sentiment = predict_sentiment(content)  # Your sentiment prediction logic
    print(f"Predicted Sentiment: {sentiment}")  # Debugging line
    
    
    # Step 3: Assign workload and deadline based on priority
    
    new_review = Reviews(content=content, sentiment=sentiment, user_id=user_id, status="To-Do")
    workload, deadline = new_review.calculate_workload()
    new_review.workload = workload  # Set workload
    new_review.deadline = deadline
    db.session.add(new_review)
    db.session.commit()
    new_review.update_task() 
    # Store predicted time in the review
    db.session.commit()
    print(f"Review saved with ID: {new_review.id}")  # Debugging line
    
    # Redirect to the dashboard after review submission
    return redirect(url_for('dashboard'))

def predict_future_sentiment(username):
    user = Users.query.filter_by(username=username).first()

    if not user:
        return "User not found!"

    user_reviews = Reviews.query.filter_by(user_id=user.id).order_by(Reviews.id).all()

    if len(user_reviews) < 5:
        return "Not enough data to predict trends"
    
    sentiments_mapping = {'Negative': 0, 'Neutral': 1, 'Positive': 2}
    timestamp = []
    sentiment_scores = []

    # Get reviews along with their timestamps
    for review in user_reviews:
        timestamp.append(review.id)  # Use IDs as time markers (auto-incremented)
        sentiment_scores.append(sentiments_mapping[review.sentiment])

    if not timestamp or not sentiment_scores:
        return "Not enough valid reviews for prediction"
    

    X_train = np.array(timestamp).reshape(-1, 1)
    y_train = np.array(sentiment_scores)

    time_decay_factor = np.linspace(1, 2, len(y_train)) if len(y_train) > 1 else np.array([1])

    if X_train.shape[0] != y_train.shape[0]:
        return "Error: Mismatched training data sizes."

    model = LogisticRegression()
    model.fit(X_train, y_train, sample_weight=time_decay_factor)

    if not timestamp:
        return "No valid timestamps available for prediction"

    next_review_index = np.array([[timestamp[-1] + 1]])
    future_sentiment_code = model.predict(next_review_index)[0]

    reverse_mapping = {0: 'Negative', 1: 'Neutral', 2: 'Positive'}
    return reverse_mapping[future_sentiment_code]

@app.route('/predict', methods=['POST'])
@login_required
def predict():
    try:
        # Get the review from the request
        data = request.get_json(force=True)
        review = data.get('review', '')  # Review content
        
        if not review:
            flash("No review provided", "danger")
            return redirect(url_for('dashboard'))
        
        # Step 1: Predict sentiment
        predicted_sentiment = predict_sentiment(review)  # Your sentiment prediction logic
        
        future_sentiments = predict_future_sentiment(current_user.username)
        
        # Step 3: Store the review with sentiment and priority in the database
        new_review = Reviews(content=review, sentiment=predicted_sentiment, user_id=current_user.id,status="To-Do")
        workload, deadline = new_review.calculate_workload()
        new_review.workload = workload  # Set workload
        new_review.deadline = deadline  
        db.session.add(new_review)
        db.session.commit()
        new_review.update_task()
        db.session.commit()
        return jsonify({
            "sentiment": predicted_sentiment,
            "review_id": new_review.id,
            "future_sentiment": future_sentiments,
            "message": "Review submitted successfully"
        })
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500




# Run the Flask app
if __name__ == '__main__':
    with app.app_context():
       db.create_all()  
    app.run(debug=True)
