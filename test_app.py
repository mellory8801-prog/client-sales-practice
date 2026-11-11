import unittest, tempfile, sqlite3, os
from contextlib import contextmanager
@contextmanager
def connect(path):
    c=sqlite3.connect(path)
    try:
        with c: yield c
    finally: c.close()
from app import create_app
from werkzeug.security import generate_password_hash

class SalesTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.path=os.path.join(self.tmp.name,'test.db')
        self.app=create_app(self.path); self.app.config['TESTING']=True; self.c=self.app.test_client()
        with connect(self.path) as db: db.execute('INSERT INTO users(login,password,role) VALUES(?,?,?)',('admin',generate_password_hash('test-password'),'admin'))
        self.c.get('/login')
        with self.c.session_transaction() as s: self.token=s['csrf']
        self.c.post('/login',data={'login':'admin','password':'test-password','csrf':self.token})
        self.c.get('/')
        with self.c.session_transaction() as s: self.token=s['csrf']
    def tearDown(self): self.tmp.cleanup()
    def post(self,url,**data): return self.c.post(url,data=dict(csrf=self.token,**data))
    def seed(self):
        self.post('/clients',name='Тестовый клиент',phone='000',email='demo@example.com')
        self.post('/products',name='Товар',price='125.50')
    def test_sale_total(self):
        self.seed(); self.post('/sales',client='1',product='1',quantity='3')
        self.assertIn('376.50',self.c.get('/report').text)
    def test_empty_client(self):
        self.post('/clients',name='  ')
        with connect(self.path) as db: self.assertEqual(db.execute('SELECT count(*) FROM clients').fetchone()[0],0)
    def test_bad_prices(self):
        for v in ['-1','NaN','1.001','abc']: self.post('/products',name='X',price=v)
        with connect(self.path) as db: self.assertEqual(db.execute('SELECT count(*) FROM products').fetchone()[0],0)
    def test_invalid_sale_atomic(self):
        self.seed(); self.post('/sales',client='999',product='1',quantity='2'); self.post('/sales',client='1',product='1',quantity='0')
        with connect(self.path) as db: self.assertEqual(db.execute('SELECT count(*) FROM sales').fetchone()[0],0)
    def test_cancel(self):
        self.seed(); self.post('/sales',client='1',product='1',quantity='2'); self.post('/cancel/1')
        self.assertNotIn('251.00',self.c.get('/report').text)
        with connect(self.path) as db: self.assertEqual(db.execute('SELECT status FROM sales').fetchone()[0],'cancelled')
    def test_access(self):
        with self.c.session_transaction() as s: s['role']='manager'
        self.assertEqual(self.c.get('/users').status_code,403)
        self.assertEqual(self.post('/cancel/1').status_code,403)
    def test_csrf(self): self.assertEqual(self.c.post('/clients',data={'name':'X'}).status_code,400)
    def test_login_required(self):
        self.post('/logout'); self.assertEqual(self.c.get('/sales').status_code,302)
    def test_csv_period(self):
        self.seed(); self.post('/sales',client='1',product='1',quantity='2')
        r=self.c.get('/report?csv=1'); self.assertIn('251.00',r.text); self.assertIn('text/csv',r.content_type)
        self.assertNotIn('251.00',self.c.get('/report?start=2000-01-01&end=2000-01-02').text)
    def test_escape(self):
        self.post('/clients',name='<script>alert(1)</script>')
        self.assertNotIn('<script>',self.c.get('/clients').text)

if __name__=='__main__': unittest.main(verbosity=2)

