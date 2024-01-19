from flask import Flask, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from flask_wtf import FlaskForm
from wtforms import StringField, SubmitField, DateTimeField, BooleanField
from wtforms.validators import DataRequired, Email, ValidationError
from datetime import datetime, timedelta
from flask_migrate import Migrate
import smtplib
from email.mime.text import MIMEText
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.base import JobLookupError
import secrets

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///db.sqlite'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = secrets.token_hex(16)
db = SQLAlchemy(app)
migrate = Migrate(app, db)

scheduler = BackgroundScheduler(daemon=True)
scheduler.start()

class Todo(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100))
    email = db.Column(db.String(100))
    deadline = db.Column(db.DateTime)
    complete = db.Column(db.Boolean)

class AddTaskForm(FlaskForm):
    title = StringField('Title', validators=[DataRequired()])
    email = StringField('Email', validators=[Email(), DataRequired()])
    deadline = DateTimeField('Deadline', format='%d-%m-%Y %H:%M', validators=[DataRequired()])
    submit = SubmitField('Add Task')

@app.before_first_request
def create_tables():
    db.create_all()

@app.route('/')
def index():
    todo_list = Todo.query.all()
    total_todo = Todo.query.count()
    completed_todo = Todo.query.filter_by(complete=True).count()
    uncompleted_todo = total_todo - completed_todo
    return render_template('index.html', **locals())

@app.route('/add', methods=['GET', 'POST'])
def add():
    form = AddTaskForm()
    if form.validate_on_submit():
        now = datetime.utcnow()
        deadline = form.deadline.data

        if deadline <= now:
            flash('Deadline must be set to a future time.', 'error')
            return redirect(url_for('add'))
        new_task = Todo(
            title=form.title.data,
            email=form.email.data,
            deadline=form.deadline.data,
            complete=False
        )
        db.session.add(new_task)
        db.session.commit()
        send_email(new_task, 'Task Created', f'Your Task "{new_task.title}" created successfully!\n\nDeadline: {new_task.deadline}')
        schedule_reminder(new_task)
        flash('Task created successfully!', 'success')
        return redirect(url_for('index'))
    return render_template('add.html', form=form)

def send_email(task, subject, body):
    sender_email = 'surendravarma2302@gmail.com'
    password = 'bcra krel mlpu tgzw'
    try:
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(sender_email, password)
        msg = MIMEText(body)
        msg['Subject'] = subject
        msg['From'] = sender_email
        msg['To'] = task.email
        server.sendmail(sender_email, [task.email], msg.as_string())
        server.quit()
    except Exception as e:
        print(f"Error sending email: {e}")

def schedule_reminder(task):
    if task.id is None:
        flash('Task ID is None. Unable to schedule reminder.', 'error')
        return
    reminder_time = task.deadline - timedelta(minutes=60)
    job_id = f'reminder_job_{task.id}'
    if job_id in [job.id for job in scheduler.get_jobs()]:
        flash(f'A reminder for task "{task.title}" is already scheduled.', 'warning')
        return
    scheduler.add_job(
        send_email,
        'date',
        run_date=reminder_time,
        args=[task, 'Task Reminder', f'Reminder: Your task "{task.title}" is due. Deadline: {task.deadline}'],
        id=job_id
    )

@app.route('/about')
def about():
    return render_template('about.html')

@app.route('/search', methods=['GET', 'POST'])
def search():
    query = request.args.get('query')
    if query:
        search_results = Todo.query.filter(Todo.title.contains(query)).all()
    else:
        search_results = []
    return render_template('search_results.html', query=query, results=search_results)

@app.route('/delete/<int:todo_id>')
def delete(todo_id):
    todo = Todo.query.get(todo_id)
    if todo is None:
        flash('Task not found', 'error')
        return redirect(url_for('index'))
    job_id = f'reminder_job_{todo.id}'
    try:
        scheduler.remove_job(job_id, jobstore='default')
    except JobLookupError:
        pass
    db.session.delete(todo)
    db.session.commit()
    return redirect(url_for('index'))

class UpdateTaskForm(FlaskForm):
    title = StringField('Title', validators=[DataRequired()])
    complete = BooleanField('Mark as Complete')
    deadline = DateTimeField('Deadline', format='%d-%m-%Y %H:%M', validators=[DataRequired()])
    submit = SubmitField('Update Task')
    def validate_deadline(self, field):
        validated_deadline = field.data
        if validated_deadline <= datetime.utcnow():
            raise ValidationError('Deadline must be set to a future date and time.')
        setattr(self, '_validated_deadline', validated_deadline)

@app.route('/update/<int:todo_id>', methods=['GET', 'POST'])
def update(todo_id):
    todo = Todo.query.get(todo_id)
    if todo is None:
        flash('Task not found', 'error')
        return redirect(url_for('index'))
    form = UpdateTaskForm(obj=todo)
    if form.validate_on_submit():
        todo.complete = form.complete.data
        if form.deadline.data:
            old_job_id = f'reminder_job_{todo.id}'
            try:
                scheduler.remove_job(old_job_id, jobstore='default')
            except JobLookupError:
                pass
            todo.deadline = form.deadline.data
            send_email(todo, 'Task Updated', f'Your task "{todo.title}" is updated\n Deadline: {todo.deadline}')
        if todo.complete:
            send_email(todo, 'Task Completed', f'Your task "{todo.title}" is marked as complete.')
        db.session.commit()
        flash('Task updated successfully!', 'success')
        schedule_reminder(todo)
        return redirect(url_for('index'))
    return render_template('update.html', form=form, todo=todo)

if __name__ == "__main__":
    try:
        app.run(debug=True)
    finally:
        db.session.close()