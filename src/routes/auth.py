"""
Authentication routes: login, register, forgot password, logout.

Extracted from app.py to reduce monolith size.
"""
from __future__ import annotations

from flask import Blueprint, render_template, jsonify, request, redirect, url_for, session

auth_bp = Blueprint('auth', __name__)


def _get_supabase():
    """Get supabase client from app config (set by create_app)."""
    from flask import current_app
    return current_app.config.get('_supabase')


def _get_db():
    from models import db
    return db


@auth_bp.route('/auth/login', methods=['GET', 'POST'])
def auth_login():
    error = ''
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        supabase = _get_supabase()
        if supabase:
            try:
                res = supabase.auth.sign_in_with_password({"email": email, "password": password})
                if getattr(res, 'user', None) and getattr(res, 'session', None):
                    session['sb_user_id'] = res.user.id
                    session['sb_access_token'] = res.session.access_token
                    next_path = request.args.get('next') or url_for('routes.predictions_page')
                    return redirect(next_path)
                error = 'Неверный email или пароль'
            except Exception:
                error = 'Неверный email или пароль'
        else:
            from models import User
            user = User.query.filter_by(email=email).first()
            if user:
                from werkzeug.security import check_password_hash
                if check_password_hash(user.password_hash, password):
                    session['user_id'] = user.id
                    next_path = request.args.get('next') or url_for('routes.predictions_page')
                    return redirect(next_path)
            error = 'Неверный email или пароль'
    return render_template('auth/login.html', error=error)


@auth_bp.route('/auth/register', methods=['GET', 'POST'])
def auth_register():
    error = ''
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        confirm = request.form.get('confirm', '')
        if '@' not in email or '.' not in email:
            error = 'Некорректный email'
        if not error and len(password) < 6:
            error = 'Пароль слишком короткий'
        if not error and password != confirm:
            error = 'Пароли не совпадают'
        if not error:
            supabase = _get_supabase()
            if supabase:
                try:
                    supabase.auth.sign_up({"email": email, "password": password})
                    try_signin = supabase.auth.sign_in_with_password({"email": email, "password": password})
                    if getattr(try_signin, 'user', None) and getattr(try_signin, 'session', None):
                        session['sb_user_id'] = try_signin.user.id
                        session['sb_access_token'] = try_signin.session.access_token
                    return redirect(url_for('routes.predictions_page'))
                except Exception:
                    error = 'Ошибка регистрации'
            else:
                from models import User, db
                if User.query.filter_by(email=email).first():
                    error = 'Пользователь уже существует'
                else:
                    from werkzeug.security import generate_password_hash
                    user = User(email=email, password_hash=generate_password_hash(password, method='pbkdf2:sha256', salt_length=16))
                    db.session.add(user)
                    db.session.commit()
                    session['user_id'] = user.id
                    return redirect(url_for('routes.predictions_page'))
    return render_template('auth/register.html', error=error)


@auth_bp.route('/auth/forgot', methods=['GET', 'POST'])
def auth_forgot():
    message = ''
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        supabase = _get_supabase()
        if supabase:
            try:
                supabase.auth.reset_password_email(email)
                message = 'Если email существует, письмо отправлено.'
            except Exception:
                message = 'Ошибка отправки письма'
        else:
            from models import User
            exists = bool(User.query.filter_by(email=email).first())
            message = 'Пользователь найден. Инструкция отправлена.' if exists else 'Пользователь не найден.'
    return render_template('auth/forgot.html', message=message)


@auth_bp.route('/auth/logout')
def auth_logout():
    try:
        supabase = _get_supabase()
        if supabase:
            supabase.auth.sign_out()
    except Exception:
        pass
    session.clear()
    return redirect(url_for('auth.auth_login'))


@auth_bp.route('/auth/db-init')
def auth_db_init():
    try:
        from models import db
        from sqlalchemy import inspect
        db.create_all()
        inspector = inspect(db.engine)
        tables = inspector.get_table_names()
        return jsonify({'ok': True, 'tables': tables})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)})
