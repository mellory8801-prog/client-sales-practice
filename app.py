"""Учебная система учета клиентов и продаж. Запуск: python app.py."""
import os, sqlite3, secrets, csv, io
from decimal import Decimal, InvalidOperation
from functools import wraps
from contextlib import contextmanager
from flask import Flask, request, session, redirect, render_template_string, Response, abort
from werkzeug.security import generate_password_hash, check_password_hash

SCHEMA = '''
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, login TEXT UNIQUE NOT NULL, password TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('admin','manager')));
CREATE TABLE IF NOT EXISTS clients(id INTEGER PRIMARY KEY, name TEXT NOT NULL, phone TEXT NOT NULL DEFAULT '', email TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS products(id INTEGER PRIMARY KEY, name TEXT NOT NULL, price INTEGER NOT NULL CHECK(price>=0));
CREATE TABLE IF NOT EXISTS sales(id INTEGER PRIMARY KEY, client_id INTEGER NOT NULL REFERENCES clients(id), user_id INTEGER NOT NULL REFERENCES users(id), created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, status TEXT NOT NULL DEFAULT 'completed' CHECK(status IN ('completed','cancelled')));
CREATE TABLE IF NOT EXISTS sale_items(id INTEGER PRIMARY KEY, sale_id INTEGER NOT NULL REFERENCES sales(id), product_id INTEGER NOT NULL REFERENCES products(id), quantity INTEGER NOT NULL CHECK(quantity>0), price INTEGER NOT NULL CHECK(price>=0));
CREATE INDEX IF NOT EXISTS ix_sales_client ON sales(client_id);
CREATE INDEX IF NOT EXISTS ix_sales_created ON sales(created);
'''

PAGE='''<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>{{title}} — Клиенты и продажи</title>
<style>body{font:18px Georgia,serif;color:#000;background:#fff;margin:40px auto;max-width:1100px;padding:0 24px}nav{padding:18px 0;border-bottom:2px solid #000}a{color:#000;margin-right:22px}h1{font-size:30px}table{border-collapse:collapse;width:100%;margin:24px 0}td,th{border:1px solid #777;padding:13px;text-align:left}input,select,button{font:inherit;padding:10px;margin:6px 8px 12px 0;max-width:95%}button{background:white;border:1px solid black;cursor:pointer}.notice{padding:14px;border:1px solid black}label{display:inline-block}small{display:block;margin:20px 0}</style>
<nav><b>Клиенты и продажи</b>　{% if session.get('uid') %}<a href="/">Обзор</a><a href="/clients">Клиенты</a><a href="/products">Товары</a><a href="/sales">Продажи</a><a href="/report">Отчет</a>{% if session.role=='admin' %}<a href="/users">Сотрудники</a>{% endif %}<form style="display:inline" method="post" action="/logout"><input type="hidden" name="csrf" value="{{csrf}}"><button>Выйти</button></form>{% endif %}</nav>
<h1>{{title}}</h1>{% if error %}<p class="notice">{{error}}</p>{% endif %} BODY <small>Учебный проект · Академия ИМСИТ · Демонстрационные данные</small></html>'''

def create_app(database=None):
    app=Flask(__name__)
    app.secret_key=os.environ.get('APP_SECRET') or secrets.token_hex(32)
    app.config.update(DATABASE=database or os.environ.get('APP_DB','sales.db'), SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax', MAX_CONTENT_LENGTH=1024*1024)
    @contextmanager
    def db():
        c=sqlite3.connect(app.config['DATABASE']); c.row_factory=sqlite3.Row; c.execute('PRAGMA foreign_keys=ON')
        try:
            with c: yield c
        finally: c.close()
    with db() as c: c.executescript(SCHEMA)
    def page(title,body,**kw):
        session.setdefault('csrf',secrets.token_hex(24))
        return render_template_string(PAGE.replace('BODY',body),title=title,csrf=session['csrf'],**kw)
    def auth(f):
        @wraps(f)
        def wrapped(*args,**kwargs):
            if not session.get('uid'): return redirect('/login')
            return f(*args,**kwargs)
        return wrapped
    @app.before_request
    def csrf():
        if request.method=='POST' and not secrets.compare_digest(request.form.get('csrf',''),session.get('csrf','invalid')): abort(400)
    def form(fields,button='Сохранить'):
        return '<form method="post"><input type="hidden" name="csrf" value="{{csrf}}">'+fields+'<button>'+button+'</button></form>'
    @app.route('/login',methods=['GET','POST'])
    def login():
        error=None
        if request.method=='POST':
            with db() as c: u=c.execute('SELECT * FROM users WHERE login=?',(request.form.get('login',''),)).fetchone()
            if u and check_password_hash(u['password'],request.form.get('password','')):
                session.clear(); session.update(uid=u['id'],role=u['role']); return redirect('/')
            error='Неверный логин или пароль'
        return page('Вход в систему',form('<label>Логин<br><input name="login" required></label><label>Пароль<br><input name="password" type="password" required></label>','Войти'),error=error)
    @app.post('/logout')
    def logout(): session.clear(); return redirect('/login')
    @app.get('/')
    @auth
    def home():
        with db() as c:
            clients=c.execute('SELECT count(*) FROM clients').fetchone()[0]
            sales=c.execute("SELECT count(*) FROM sales WHERE status='completed'").fetchone()[0]
            total=c.execute("SELECT coalesce(sum(i.price*i.quantity),0) FROM sale_items i JOIN sales s ON s.id=i.sale_id WHERE s.status='completed'").fetchone()[0]
        return page('Обзор работы', '<table><tr><th>Клиенты</th><th>Продажи</th><th>Выручка, руб.</th></tr><tr><td>{{clients}}</td><td>{{sales}}</td><td>{{"%.2f"%(total/100)}}</td></tr></table><p>Зарегистрируйте клиента, добавьте товары и оформите продажу. Отмененные операции сохраняются в истории и не входят в выручку.</p>',clients=clients,sales=sales,total=total)
    @app.route('/clients',methods=['GET','POST'])
    @auth
    def clients():
        error=None
        if request.method=='POST':
            name=request.form.get('name','').strip(); phone=request.form.get('phone','').strip(); email=request.form.get('email','').strip()
            if not name or len(name)>120 or len(phone)>40 or len(email)>120: error='Проверьте имя и длину полей'
            else:
                with db() as c: c.execute('INSERT INTO clients(name,phone,email) VALUES(?,?,?)',(name,phone,email))
                return redirect('/clients')
        q=request.args.get('q','')
        with db() as c: rows=c.execute('SELECT * FROM clients WHERE name LIKE ? OR phone LIKE ? ORDER BY id',('%'+q+'%','%'+q+'%')).fetchall()
        return page('Клиенты',form('<input name="name" placeholder="Имя клиента" required maxlength="120"><input name="phone" placeholder="Телефон"><input name="email" type="email" placeholder="Электронная почта">')+'<form><input name="q" placeholder="Поиск по имени или телефону" value="{{q}}"><button>Найти</button></form><table><tr><th>№</th><th>Клиент</th><th>Телефон</th><th>Почта</th></tr>{% for r in rows %}<tr><td>{{r.id}}</td><td>{{r.name}}</td><td>{{r.phone}}</td><td>{{r.email}}</td></tr>{% endfor %}</table>',rows=rows,q=q,error=error)
    @app.route('/products',methods=['GET','POST'])
    @auth
    def products():
        error=None
        if request.method=='POST':
            try:
                name=request.form.get('name','').strip(); value=Decimal(request.form.get('price',''))
                if not name or len(name)>120 or not value.is_finite() or value<0 or value>10000000 or value*100!=int(value*100): raise ValueError()
                with db() as c: c.execute('INSERT INTO products(name,price) VALUES(?,?)',(name,int(value*100)))
                return redirect('/products')
            except (ValueError,InvalidOperation): error='Введите название и неотрицательную цену с точностью до копейки'
        with db() as c: rows=c.execute('SELECT * FROM products').fetchall()
        return page('Товары',form('<input name="name" placeholder="Название товара" required><input name="price" type="number" min="0" step="0.01" placeholder="Цена, руб." required>')+'<table><tr><th>№</th><th>Товар</th><th>Цена, руб.</th></tr>{% for r in rows %}<tr><td>{{r.id}}</td><td>{{r.name}}</td><td>{{"%.2f"%(r.price/100)}}</td></tr>{% endfor %}</table>',rows=rows,error=error)
    @app.route('/sales',methods=['GET','POST'])
    @auth
    def sales():
        error=None
        if request.method=='POST':
            try:
                qty=int(request.form.get('quantity','0'))
                if not 1<=qty<=100000: raise ValueError()
                with db() as c:
                    p=c.execute('SELECT price FROM products WHERE id=?',(request.form.get('product'),)).fetchone()
                    if not p: raise ValueError()
                    sale=c.execute('INSERT INTO sales(client_id,user_id) VALUES(?,?)',(request.form.get('client'),session['uid'])).lastrowid
                    c.execute('INSERT INTO sale_items(sale_id,product_id,quantity,price) VALUES(?,?,?,?)',(sale,request.form['product'],qty,p['price']))
                return redirect('/sales')
            except (ValueError,sqlite3.IntegrityError): error='Выберите существующего клиента и товар; количество должно быть от 1 до 100000'
        with db() as c:
            clients=c.execute('SELECT * FROM clients').fetchall(); products=c.execute('SELECT * FROM products').fetchall()
            rows=c.execute('SELECT s.*,c.name,sum(i.price*i.quantity) total FROM sales s JOIN clients c ON c.id=s.client_id JOIN sale_items i ON i.sale_id=s.id GROUP BY s.id ORDER BY s.id DESC').fetchall()
        body=form('<label>Клиент<br><select name="client">{% for c in clients %}<option value="{{c.id}}">{{c.name}}</option>{% endfor %}</select></label><label>Товар<br><select name="product">{% for p in products %}<option value="{{p.id}}">{{p.name}}</option>{% endfor %}</select></label><label>Количество<br><input name="quantity" type="number" value="1" min="1" max="100000"></label>','Оформить продажу')
        body+='<table><tr><th>№</th><th>Дата UTC</th><th>Клиент</th><th>Сумма, руб.</th><th>Статус</th></tr>{% for r in rows %}<tr><td>{{r.id}}</td><td>{{r.created}}</td><td>{{r.name}}</td><td>{{"%.2f"%(r.total/100)}}</td><td>{{"Завершена" if r.status=="completed" else "Отменена"}}{% if session.role=="admin" and r.status=="completed" %}<form method="post" action="/cancel/{{r.id}}"><input type="hidden" name="csrf" value="{{csrf}}"><button>Отменить</button></form>{% endif %}</td></tr>{% endfor %}</table>'
        return page('Продажи',body,rows=rows,clients=clients,products=products,error=error)
    @app.post('/cancel/<int:id>')
    @auth
    def cancel(id):
        if session['role']!='admin': abort(403)
        with db() as c: c.execute("UPDATE sales SET status='cancelled' WHERE id=?",(id,))
        return redirect('/sales')
    @app.get('/report')
    @auth
    def report():
        start=request.args.get('start') or '0001-01-01'; end=request.args.get('end') or '9999-12-31'
        with db() as c: rows=c.execute("SELECT substr(s.created,1,10) day,count(distinct s.id) count,sum(i.price*i.quantity) total FROM sales s JOIN sale_items i ON i.sale_id=s.id WHERE s.status='completed' AND substr(s.created,1,10) BETWEEN ? AND ? GROUP BY day ORDER BY day",(start,end)).fetchall()
        if request.args.get('csv'):
            out=io.StringIO(); writer=csv.writer(out,delimiter=';'); writer.writerow(['Дата UTC','Продажи','Выручка, руб.'])
            for r in rows: writer.writerow([r['day'],r['count'],f"{r['total']/100:.2f}"])
            return Response('\ufeff'+out.getvalue(),content_type='text/csv; charset=utf-8',headers={'Content-Disposition':'attachment; filename=report.csv'})
        return page('Отчет о продажах','<form><label>С даты<input type="date" name="start" value="{{start}}"></label><label>По дату<input type="date" name="end" value="{{end}}"></label><button>Сформировать</button><button name="csv" value="1">Скачать CSV</button></form><table><tr><th>Дата UTC</th><th>Продажи</th><th>Выручка, руб.</th></tr>{% for r in rows %}<tr><td>{{r.day}}</td><td>{{r.count}}</td><td>{{"%.2f"%(r.total/100)}}</td></tr>{% endfor %}</table>',rows=rows,start=start,end=end)
    @app.route('/users',methods=['GET','POST'])
    @auth
    def users():
        if session['role']!='admin': abort(403)
        error=None
        if request.method=='POST':
            login=request.form.get('login','').strip(); password=request.form.get('password',''); role=request.form.get('role','manager')
            if not login or len(login)>80 or len(password)<10 or role not in ('admin','manager'): error='Логин обязателен, пароль не короче 10 символов'
            else:
                try:
                    with db() as c: c.execute('INSERT INTO users(login,password,role) VALUES(?,?,?)',(login,generate_password_hash(password),role))
                    return redirect('/users')
                except sqlite3.IntegrityError: error='Логин уже существует'
        with db() as c: rows=c.execute('SELECT login,role FROM users').fetchall()
        return page('Сотрудники',form('<input name="login" placeholder="Логин" required><input name="password" type="password" placeholder="Пароль" minlength="10" required><select name="role"><option value="manager">Менеджер</option><option value="admin">Администратор</option></select>')+'<table><tr><th>Логин</th><th>Роль</th></tr>{% for r in rows %}<tr><td>{{r.login}}</td><td>{{r.role}}</td></tr>{% endfor %}</table>',rows=rows,error=error)
    return app

if __name__=='__main__':
    app=create_app()
    with sqlite3.connect(app.config['DATABASE']) as c:
        if not c.execute('SELECT count(*) FROM users').fetchone()[0]:
            import getpass
            password=getpass.getpass('Пароль администратора (не менее 10 символов): ')
            if len(password)<10: raise SystemExit('Пароль слишком короткий')
            c.execute('INSERT INTO users(login,password,role) VALUES(?,?,?)',('admin',generate_password_hash(password),'admin'))
    app.run(host='127.0.0.1',port=5000,debug=False)
