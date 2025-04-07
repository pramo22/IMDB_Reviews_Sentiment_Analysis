from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta
from flask_login import UserMixin 
from textstat import textstat



 
db = SQLAlchemy()
class Users(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(100), nullable=False)
    security_answer = db.Column(db.String(100), nullable=False)
    # Changed the backref to 'user_reviews' for uniqueness
    reviews = db.relationship('Reviews', backref='user_reviews', lazy=True)  # Changed backref name

    def __repr__(self):
        return f'<User {self.username}>'

class Reviews(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.Text, nullable=False)
    sentiment = db.Column(db.String(20), nullable=False)  # Positive, Neutral, Negative
    priority = db.Column(db.Integer, nullable=False, default=1)
    urgency = db.Column(db.String(50), nullable=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    workload = db.Column(db.Integer, nullable=False)
    deadline = db.Column(db.DateTime, nullable=False)
    status = db.Column(db.String(50), nullable=True, default='To-Do')  # Task status
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    completion_time = db.Column(db.Float, nullable=True)
    predicted_time = db.Column(db.Float, nullable=True)  
    efficiency = db.Column(db.Integer, nullable=True)
    start_time = db.Column(db.DateTime, nullable=True)  # Start time of the task
    end_time = db.Column(db.DateTime, nullable=True)  # End time (when task is completed)
    # Changed the backref to 'review_user' to avoid conflicts with 'user_reviews'
    user = db.relationship('Users', backref='review_user', lazy=True)  # Changed backref name
    def __repr__(self):
        return f'<Review {self.content[:20]} - Sentiment: {self.sentiment}, urgency: {self.urgency},status: {self.status}, Workload: {self.workload},start_time:{self.start_time},end_time:{self.end_time},predicted_time:{self.predicted_time},completion_time:{self.completion_time}, Deadline: {self.deadline.strftime("%d-%m-%Y %H:%M:%S")}>'

    def calculate_workload(self):
        """Calculate workload based on sentiment and review complexity."""
        complexity = len(self.content.split())  # Example complexity based on word count
        if self.sentiment == 'Negative':
             workload = complexity * 2 # Default neutral weight
             deadline = datetime.now() + timedelta(seconds=30)
        elif self.sentiment == 'Neutral':
             workload = complexity * 1 # Default neutral weight
             deadline = datetime.now() + timedelta(seconds=50)
        elif self.sentiment == 'Positive':
             workload = complexity * 0.5 # Default neutral weight
             deadline = datetime.now() + timedelta(seconds=60) 
        self.workload=int(workload)
        self.deadline=deadline  
        db.session.commit()   
        return self.workload,self.deadline


    def update_task(self):
        """Update task status, workload, urgency, and priority."""
        now = datetime.now()
        time_left = (self.deadline - now).total_seconds()  # Time left in hours
        # Adjust workload decrement based on status and sentiment
        if self.status == "In Progress":
            if self.sentiment == 'Negative':
                decrement_value = max(8, int(self.workload * 0.3))  # Faster reduction for negative sentiment
            elif self.sentiment == 'Neutral':
                decrement_value = max(5, int(self.workload * 0.2))  # Moderate reduction for neutral sentiment
            else:
                decrement_value = max(3, int(self.workload * 0.1))  # Slower reduction for positive sentiment
            self.workload = max(self.workload - decrement_value, 0)  # Prevent negative workload

        # Update urgency as a string based on workload and time left
        if self.workload > 30 or time_left <= 40:
            self.urgency = "High Urgency"
        elif 15 <= self.workload <= 30:
            self.urgency = "Medium Urgency"
        else:
            self.urgency = "Low Urgency"

        # Calculate urgency factor based on urgency string
        if self.urgency == "High Urgency":
            urgency_factor = 2.0
        elif self.urgency == "Medium Urgency":
            urgency_factor = 1.5
        else:
            urgency_factor = 1.0

        # Update predicted time based on workload, time left, and urgency
        if time_left > 0:
            self.predicted_time = round((self.workload / time_left) * urgency_factor, 2)  # Round to 2 decimal places
        else:
            self.predicted_time = round(self.workload, 2)   # If no time left, predict remaining workload
        
        # Update task status based on urgency
        if self.urgency == "High Urgency" and  self.status != "In Progress":
            self.status = "In Progress"
            self.start_time = datetime.now() if self.start_time is None else self.start_time
            self.calculate_efficiency()
        elif self.workload <= 0 :
            self.status = "Completed"
            self.end_time = datetime.now()
        elif time_left > 40 and self.workload > 0:
            self.status = "To-Do"  # If there is more time left and workload is still remaining
        elif time_left <= 40 and self.workload > 0:
            self.status = "In Progress"  # If time is running out but there is still work to be done
            self.start_time = datetime.now() if self.start_time is None else self.start_time
        if self.urgency == 'High Urgency' or self.workload >=30 or time_left <= 40:
            self.priority = 1  # High priority
        elif 30 < time_left <= 40:
            self.priority = 2  # Medium priority
        else:
            self.priority = 3  # Low priority
        
        self.calculate_efficiency()
        db.session.commit()

    def calculate_efficiency(self):
        """Dynamically calculate efficiency as the ratio of predicted to actual time taken."""
        if self.start_time:
            # If the task is completed, use end_time, otherwise use the current time
            current_time = self.end_time if self.end_time else datetime.now()
            
            # Calculate the actual time taken (in minutes)
            actual_time = (current_time - self.start_time).total_seconds() # Actual time in minutes
            
            # Prevent division by zero and calculate efficiency dynamically
            if actual_time > 0 and self.predicted_time > 0:
                self.efficiency = max(int(self.predicted_time/actual_time) *100,100)  # Efficiency as a percentage
            else:
                self.efficiency = 100  # If no actual time, set efficiency to 100% (e.g., task completed instantly)

            db.session.commit()  # Commit the changes to the database
       


    
