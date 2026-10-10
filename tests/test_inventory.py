"""Integration tests against an explicitly selected, real PostgreSQL database."""
import io
import os
import uuid
from concurrent.futures import ThreadPoolExecutor

import psycopg
import pytest
from PIL import Image
from psycopg.conninfo import make_conninfo

from app import create_app


@pytest.fixture
def app(tmp_path):
    dsn = os.getenv('TEST_DATABASE_URL')
    if not dsn:
        pytest.skip('Set TEST_DATABASE_URL to a disposable PostgreSQL database')
    schema = 'test_' + uuid.uuid4().hex
    with psycopg.connect(dsn, autocommit=True) as db:
        db.execute(f'CREATE SCHEMA {schema}')
    test_app = create_app(dict(TESTING=True, DATABASE_URL=make_conninfo(dsn, options=f'-c search_path={schema}'),
                              DATA_DIR=str(tmp_path), ADMIN_USERNAME='owner', ADMIN_PASSWORD='test-owner-password', COOKIE_SECURE=False))
    yield test_app
    with psycopg.connect(dsn, autocommit=True) as db:
        db.execute(f'DROP SCHEMA {schema} CASCADE')


class Client:
    def __init__(self, app, username='owner', password='test-owner-password'):
        self.raw = app.test_client()
        result = self.raw.post('/api/login', json=dict(username=username, password=password))
        assert result.status_code == 200
        self.csrf = result.json['csrf']

    def call(self, path, data=None, method='POST'):
        return self.raw.open(path, method=method, json=data, headers={'X-CSRF-Token': self.csrf})

    def state(self):
        return self.raw.get('/api/state').json

    def photo(self):
        output = io.BytesIO()
        Image.new('RGB', (20, 20), 'green').save(output, 'PNG')
        output.seek(0)
        result = self.raw.post('/api/photos', data={'photo': (output, 'test.png')}, headers={'X-CSRF-Token': self.csrf})
        assert result.status_code == 201
        return result.json['id']

    def container(self, kind='box', parent=None, name='测试箱'):
        data = dict(name=name, kind=kind, parent_id=parent, floor_note='门后', photo_id=self.photo(), description='描述')
        result = self.call('/api/containers', data)
        assert result.status_code == 201, result.json
        return result.json['id']

    def intake(self, container=None, mode='count', quantity='10', tags=None):
        if container is None:
            container = next(c['id'] for c in self.state()['containers'] if c['kind'] == 'shelf')
        result = self.call('/api/intake', dict(name='洗碗液', description='日用', unit='瓶', mode=mode,
                                              photo_id=self.photo(), quantity=quantity, container_id=container, tags=tags or ['清洁', '杂项']))
        assert result.status_code == 201, result.json
        return result.json


@pytest.fixture
def client(app):
    return Client(app)


def test_seed_and_restart(app, client):
    rows = client.state()['containers']
    assert len([r for r in rows if r['kind'] == 'rack']) == 7
    assert len([r for r in rows if r['kind'] == 'cabinet']) == 2
    assert len([r for r in rows if r['kind'] == 'shelf']) == 51
    middle = next(r for r in rows if r['name'] == '中3' and r['kind'] == 'rack')
    assert sorted(r['level'] for r in rows if r['parent_id'] == middle['id']) == [1,2,3,4,5]
    create_app(app.config)
    assert len(client.state()['containers']) == 60


def test_upgrade_adds_middle3_once(app, client):
    with psycopg.connect(app.config['DATABASE_URL']) as db:
        middle = db.execute("SELECT id FROM containers WHERE name='中3' AND kind='rack'").fetchone()[0]
        db.execute('DELETE FROM containers WHERE parent_id=%s', (middle,))
        db.execute('DELETE FROM containers WHERE id=%s', (middle,))
        db.execute("DELETE FROM settings WHERE key='default_middle3_v1'")
    create_app(app.config)
    middle = next(c for c in client.state()['containers'] if c['name'] == '中3' and c['kind'] == 'rack')
    assert len([c for c in client.state()['containers'] if c['parent_id'] == middle['id']]) == 5
    create_app(app.config)
    assert len(client.state()['containers']) == 60
    assert client.call(f"/api/containers/{middle['id']}", method='DELETE').status_code == 200
    create_app(app.config)
    assert not any(c['name'] == '中3' for c in client.state()['containers'])


def test_auth_and_csrf(app, client):
    anon = app.test_client()
    assert anon.get('/api/state').status_code == 401
    assert anon.get('/photos/fake.jpg').status_code == 401
    assert client.raw.post('/api/users', json=dict(username='member', password='member-password')).status_code == 403
    assert client.call('/api/users', dict(username='member', password='member-password')).status_code == 201
    member = Client(app, 'member', 'member-password')
    assert member.raw.get('/api/users').status_code == 403
    assert member.call('/api/users', dict(username='intruder', password='member-password')).status_code == 403
    assert member.call('/api/users/1', method='DELETE').status_code == 403
    assert client.call('/api/users/1', method='DELETE').status_code == 403
    ident = next(u['id'] for u in client.raw.get('/api/users').json['users'] if u['role'] == 'member')
    assert client.call(f'/api/users/{ident}', method='DELETE').status_code == 200
    assert member.raw.get('/api/state').status_code == 401


def test_photos_validation(app, client):
    result = client.raw.post('/api/photos', data={'photo': (io.BytesIO(b'fake image'), 'a.jpg')}, headers={'X-CSRF-Token': client.csrf})
    assert result.status_code == 400
    ident = client.photo()
    assert client.raw.get(f'/photos/{ident}.jpg').status_code == 200
    assert client.raw.get('/photos/../app.py').status_code != 200


@pytest.mark.parametrize('kind,parent_kind,accepted', [('box','shelf',True),('box','box',True),('box','bag',False),('bag','bag',True),('loose','bag',True),('bag','loose',False),('box','rack',False)])
def test_container_rules(client, kind, parent_kind, accepted):
    parent = next(c['id'] for c in client.state()['containers'] if c['kind'] == parent_kind) if parent_kind in ('shelf','rack') else client.container(kind=parent_kind)
    result = client.call('/api/containers', dict(name='子容器', kind=kind, parent_id=parent, photo_id=client.photo()))
    assert result.status_code == (201 if accepted else 400)


def test_floor_and_photo_required(client):
    assert client.call('/api/containers', dict(name='箱',kind='box',floor_note='门后')).status_code == 400
    assert client.call('/api/containers', dict(name='箱',kind='box',photo_id=client.photo())).status_code == 400
    assert client.call('/api/intake',dict(name='笔',mode='count',unit='支',quantity=1,container_id=2)).status_code == 400


def test_move_chain_and_cycles(client):
    box = client.container()
    child = client.container(parent=box, name='小箱')
    bag = client.container(kind='bag',parent=child,name='小袋')
    stock = client.intake(container=bag)
    assert client.call(f'/api/containers/{box}',dict(parent_id=child),method='PUT').status_code == 400
    assert client.call(f'/api/containers/{box}',dict(parent_id=box),method='PUT').status_code == 400
    shelf = next(c['id'] for c in client.state()['containers'] if c['kind'] == 'shelf')
    assert client.call(f'/api/containers/{box}',dict(parent_id=shelf),method='PUT').status_code == 200
    row = next(s for s in client.state()['stocks'] if s['id'] == stock['id'])
    assert '左1 / 第1层 / 测试箱 / 小箱 / 小袋' == row['path']
    root = next(c for c in client.state()['containers'] if c['kind'] == 'rack')
    assert root['total_count'] == 1
    assert client.call(f'/api/containers/{box}',method='DELETE').status_code == 400


def test_count_operations_and_tags(client):
    first = client.intake(quantity='10.5',tags=['清洁','杂项','清洁'])
    assert len(client.state()['tags']) == 2
    box = client.container()
    assert client.call(f"/api/stocks/{first['id']}/withdraw",dict(quantity='11')).status_code == 400
    assert client.call(f"/api/stocks/{first['id']}/withdraw",dict(quantity='0.5')).status_code == 200
    assert client.call(f"/api/stocks/{first['id']}/transfer",dict(quantity='3',container_id=box)).status_code == 200
    stocks = client.state()['stocks']
    assert sorted(float(s['quantity']) for s in stocks) == [3,7]
    assert client.call('/api/intake',dict(product_id=first['product_id'],quantity=2,container_id=box)).status_code == 201
    assert len(client.state()['products']) == 1
    assert client.call(f"/api/products/{first['product_id']}",dict(tags=['文具','杂项'],description='更新'),method='PUT').status_code == 200
    assert len(client.state()['tags']) == 3
    assert client.state()['products'][0]['tags'] == ['文具','杂项']


def test_percent_batches(client):
    first = client.intake(mode='percent',quantity='80')
    box = client.container()
    assert client.call('/api/intake',dict(product_id=first['product_id'],quantity='50',container_id=box)).status_code == 201
    assert len(client.state()['stocks']) == 2
    assert client.call(f"/api/stocks/{first['id']}/transfer",dict(quantity='20',container_id=box)).status_code == 400
    assert client.call(f"/api/stocks/{first['id']}/estimate",dict(quantity='101')).status_code == 400
    assert client.call(f"/api/stocks/{first['id']}/estimate",dict(quantity='40')).status_code == 200
    assert client.call(f"/api/stocks/{first['id']}/withdraw",dict(quantity='10')).status_code == 200
    assert client.call(f"/api/stocks/{first['id']}/transfer",dict(quantity='30',container_id=box)).status_code == 200
    assert next(s for s in client.state()['stocks'] if s['id'] == first['id'])['container_id'] == box


@pytest.mark.parametrize('quantity', ['NaN','Infinity','-1','0','1000001','1.0001',True,None,{},[]])
def test_invalid_quantities_atomic(client, quantity):
    shelf = next(c['id'] for c in client.state()['containers'] if c['kind'] == 'shelf')
    result = client.call('/api/intake',dict(name='坏数据',mode='count',unit='个',quantity=quantity,container_id=shelf,photo_id=client.photo(),tags=['不能留下']))
    assert result.status_code == 400
    assert not client.state()['products']
    assert not client.state()['tags']


def test_clear_and_delete_empty(client):
    box = client.container()
    stock = client.intake(container=box)
    assert client.call(f"/api/stocks/{stock['id']}/clear",{}).status_code == 400
    assert client.call(f"/api/stocks/{stock['id']}/clear",dict(description='实际已用完')).status_code == 200
    assert not client.state()['stocks']
    assert client.state()['products']
    assert client.call(f'/api/containers/{box}',method='DELETE').status_code == 200
    assert any(m['action'] == '清除记录' for m in client.state()['movements'])


def test_concurrent_withdrawal(app, client):
    stock = client.intake(quantity='10')
    cookie = client.raw.get_cookie('wh_session').value
    def withdraw(_):
        raw = app.test_client()
        raw.set_cookie('wh_session',cookie)
        return raw.post(f"/api/stocks/{stock['id']}/withdraw",json={'quantity':'7'},headers={'X-CSRF-Token':client.csrf}).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(withdraw,range(2))) == [200,400]
    assert float(client.state()['stocks'][0]['quantity']) == 3


def test_password_invalidates_all_sessions(app, client):
    second = Client(app)
    assert client.call('/api/password',dict(old_password='bad',password='new-long-password')).status_code == 400
    assert client.call('/api/password',dict(old_password='test-owner-password',password='new-long-password')).status_code == 200
    assert second.raw.get('/api/state').status_code == 401
    assert Client(app,'owner','new-long-password').state()


def test_login_rate_limit(app):
    raw = app.test_client()
    for _ in range(10):
        assert raw.post('/api/login',json=dict(username='owner',password='wrong')).status_code == 401
    assert raw.post('/api/login',json=dict(username='owner',password='test-owner-password')).status_code == 429
