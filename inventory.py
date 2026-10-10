"""Container rules and transactional inventory operations."""
import io
import secrets
from decimal import Decimal, InvalidOperation
from pathlib import Path

from flask import g, jsonify, request, send_from_directory
from PIL import Image, ImageOps, UnidentifiedImageError


def register_inventory(app, require, body, field, integer, now, log):
    def description(data):
        value = data.get('description', '')
        if not isinstance(value, str) or len(value) > 1000:
            raise ValueError('描述最多 1000 字')
        return value.strip()

    def get(table, ident, lock=False):
        ident = integer(ident, '记录编号', 1)
        row = g.db.execute(f'SELECT * FROM {table} WHERE id=%s' + (' FOR UPDATE' if lock else ''), (ident,)).fetchone()
        if not row:
            raise ValueError('记录不存在，请刷新后重试')
        return row

    def amount(value, mode, positive=True):
        try:
            if isinstance(value, bool):
                raise InvalidOperation
            number = Decimal(str(value))
            if not number.is_finite() or number < 0 or (positive and number == 0) or number > (100 if mode == 'percent' else 1000000) or number != number.quantize(Decimal('0.001')):
                raise InvalidOperation
            return number
        except (InvalidOperation, ValueError):
            raise ValueError('数量需为有效正数，最多 3 位小数；百分比不能超过 100%')

    def photo(data, required=False):
        ident = data.get('photo_id')
        if not ident and not required:
            return None
        if not isinstance(ident, str) or not g.db.execute('SELECT 1 FROM photos WHERE id=%s', (ident,)).fetchone():
            raise ValueError('请先拍照或上传照片')
        return ident

    def position(kind, data, current_id=None):
        parent_id = data.get('parent_id')
        floor_note = data.get('floor_note', '')
        if not isinstance(floor_note, str) or len(floor_note) > 300:
            raise ValueError('地面位置描述最多 300 字')
        if kind in ('rack', 'cabinet'):
            if parent_id:
                raise ValueError('架子与柜子只能放在地面')
            return None, floor_note.strip()
        if parent_id is None:
            if not floor_note.strip():
                raise ValueError('放在地面时，请填写具体位置')
            return None, floor_note.strip()
        parent = get('containers', parent_id)
        allowed = {'box': ('shelf', 'box'), 'bag': ('shelf', 'box', 'bag'), 'loose': ('shelf', 'box', 'bag')}
        if parent['kind'] not in allowed[kind]:
            raise ValueError('此容器不能放在所选位置；架子/柜子需选择具体层，箱子不能放入袋子')
        seen = set()
        while parent:
            if parent['id'] == current_id or parent['id'] in seen:
                raise ValueError('不能把容器放入自身或自身的下级容器')
            seen.add(parent['id'])
            parent = get('containers', parent['parent_id']) if parent['parent_id'] else None
        return parent_id, ''

    def destination(ident):
        row = get('containers', ident)
        if row['kind'] in ('rack', 'cabinet'):
            raise ValueError('请选择架子或柜子的具体层')
        return row

    def save_tags(product_id, tag_names):
        if not isinstance(tag_names, list) or len(tag_names) > 20:
            raise ValueError('标签最多 20 个')
        names = [field({'name': name}, 'name', '标签', 32) for name in tag_names]
        g.db.execute('DELETE FROM product_tags WHERE product_id=%s', (product_id,))
        for name in set(names):
            tag_id = g.db.execute('INSERT INTO tags(name) VALUES(%s) ON CONFLICT(name) DO UPDATE SET name=EXCLUDED.name RETURNING id', (name,)).fetchone()['id']
            g.db.execute('INSERT INTO product_tags VALUES(%s,%s)', (product_id, tag_id))

    def paths(rows):
        lookup = {r['id']: r for r in rows}
        def chain(ident):
            result, seen = [], set()
            while ident and ident not in seen:
                seen.add(ident)
                row = lookup[ident]
                result.append(row['name'])
                if not row['parent_id'] and row['floor_note']:
                    result.append('地面：' + row['floor_note'])
                ident = row['parent_id']
            return ' / '.join(reversed(result))
        return chain

    @app.post('/api/photos')
    @require()
    def upload():
        uploaded = request.files.get('photo')
        if not uploaded:
            raise ValueError('请选择照片')
        try:
            with Image.open(uploaded.stream) as original:
                if original.width * original.height > 25000000:
                    raise ValueError('照片像素过大，最多 2500 万像素')
                image = ImageOps.exif_transpose(original).convert('RGB')
                image.thumbnail((1600, 1600))
                output = io.BytesIO()
                image.save(output, 'JPEG', quality=85)
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
            raise ValueError('照片格式无效，请使用 JPEG、PNG 或 WebP')
        ident = secrets.token_hex(16)
        folder = Path(app.config['DATA_DIR']) / 'photos'
        folder.mkdir(exist_ok=True)
        (folder / (ident + '.jpg')).write_bytes(output.getvalue())
        g.db.execute('INSERT INTO photos VALUES(%s,%s)', (ident, now()))
        g.db.commit()
        return jsonify(id=ident, url='/photos/' + ident + '.jpg'), 201

    @app.get('/photos/<filename>')
    @require()
    def serve_photo(filename):
        return send_from_directory(Path(app.config['DATA_DIR']).resolve() / 'photos', filename)

    @app.get('/api/state')
    @require()
    def state():
        containers = g.db.execute('SELECT * FROM containers ORDER BY id').fetchall()
        chain = paths(containers)
        stocks = g.db.execute('SELECT * FROM stocks WHERE quantity>0 ORDER BY updated_at DESC,id DESC').fetchall()
        lookup = {r['id']: r for r in containers}
        for row in containers:
            row.update(path=chain(row['id']), direct_count=0, total_count=0)
        for row in stocks:
            row['path'] = chain(row['container_id'])
            lookup[row['container_id']]['direct_count'] += 1
            ident = row['container_id']
            while ident:
                lookup[ident]['total_count'] += 1
                ident = lookup[ident]['parent_id']
        products = g.db.execute('SELECT * FROM products ORDER BY name,id').fetchall()
        tags = g.db.execute('SELECT * FROM tags ORDER BY name').fetchall()
        links = g.db.execute('SELECT pt.product_id,t.name FROM product_tags pt JOIN tags t ON t.id=pt.tag_id ORDER BY t.name').fetchall()
        for product in products:
            product['tags'] = [r['name'] for r in links if r['product_id'] == product['id']]
        return jsonify(containers=containers, products=products, stocks=stocks, tags=tags,
                       movements=g.db.execute('SELECT * FROM movements ORDER BY id DESC LIMIT 100').fetchall())

    @app.post('/api/containers')
    @require()
    def add_container():
        data = body()
        kind = data.get('kind')
        if kind not in ('rack', 'cabinet', 'box', 'bag', 'loose'):
            raise ValueError('请选择有效容器类型')
        parent_id, floor_note = position(kind, data)
        name = field(data, 'name', '容器名')
        ident = g.db.execute('INSERT INTO containers(name,kind,description,photo_id,parent_id,floor_note) VALUES(%s,%s,%s,%s,%s,%s) RETURNING id',
                             (name, kind, description(data), photo(data, kind in ('box', 'bag', 'loose')), parent_id, floor_note)).fetchone()['id']
        if kind in ('rack', 'cabinet'):
            levels = integer(data.get('levels'), '层数', 1)
            if levels > 100:
                raise ValueError('层数最多 100 层')
            for level in range(1, levels + 1):
                g.db.execute("INSERT INTO containers(name,kind,parent_id,level,description) VALUES(%s,'shelf',%s,%s,'')", (f'第{level}层', ident, level))
        log(name, '创建容器', f'类型 {kind}；{floor_note or "上级 #" + str(parent_id)}')
        g.db.commit()
        return jsonify(id=ident), 201

    @app.put('/api/containers/<int:ident>')
    @require()
    def update_container(ident):
        row, data = get('containers', ident, True), body()
        merged = {**row, **data}
        if row['kind'] == 'shelf':
            if merged['parent_id'] != row['parent_id']:
                raise ValueError('层不能从架子或柜子中移出')
            parent_id, floor_note = row['parent_id'], ''
        else:
            parent_id, floor_note = position(row['kind'], merged, ident)
        chain = paths(g.db.execute('SELECT * FROM containers').fetchall())
        old_path = chain(ident)
        g.db.execute('UPDATE containers SET name=%s,description=%s,parent_id=%s,floor_note=%s WHERE id=%s',
                     (field(merged, 'name', '容器名'), description(merged), parent_id, floor_note, ident))
        chain = paths(g.db.execute('SELECT * FROM containers').fetchall())
        log(row['name'], '更新 / 转移容器', old_path + ' → ' + chain(ident))
        g.db.commit()
        return jsonify(ok=True)

    @app.delete('/api/containers/<int:ident>')
    @require()
    def delete_container(ident):
        row = get('containers', ident, True)
        ids = [ident]
        children = g.db.execute('SELECT * FROM containers WHERE parent_id=%s', (ident,)).fetchall()
        if row['kind'] in ('rack', 'cabinet'):
            ids.extend(r['id'] for r in children)
        elif children:
            raise ValueError('请先移走下级容器')
        if g.db.execute('SELECT 1 FROM containers WHERE parent_id=ANY(%s) AND NOT(id=ANY(%s))', (ids, ids)).fetchone() or g.db.execute('SELECT 1 FROM stocks WHERE container_id=ANY(%s) AND quantity>0', (ids,)).fetchone():
            raise ValueError('请先移走或清除容器内库存与下级容器')
        if row['kind'] == 'shelf':
            raise ValueError('层属于架子或柜子，不能单独删除')
        g.db.execute('DELETE FROM stocks WHERE container_id=ANY(%s)', (ids,))
        g.db.execute("DELETE FROM containers WHERE parent_id=%s AND kind='shelf'", (ident,))
        g.db.execute('DELETE FROM containers WHERE id=%s', (ident,))
        log(row['name'], '删除空容器', description(row))
        g.db.commit()
        return jsonify(ok=True)

    @app.post('/api/intake')
    @require()
    def intake():
        data = body()
        if data.get('product_id'):
            product = get('products', data['product_id'])
        else:
            mode = data.get('mode')
            if mode not in ('count', 'percent'):
                raise ValueError('请选择计量方式')
            product = g.db.execute('INSERT INTO products(name,description,unit,mode,photo_id) VALUES(%s,%s,%s,%s,%s) RETURNING *',
                                   (field(data, 'name', '物品名'), description(data), '%' if mode == 'percent' else field(data, 'unit', '单位', 20), mode, photo(data, True))).fetchone()
            save_tags(product['id'], data.get('tags', []))
        container = destination(data.get('container_id'))
        quantity = amount(data.get('quantity'), product['mode'])
        ident = g.db.execute('INSERT INTO stocks(product_id,container_id,quantity,description,updated_at) VALUES(%s,%s,%s,%s,%s) RETURNING id',
                             (product['id'], container['id'], quantity, description({'description': data.get('stock_description', '')}), now())).fetchone()['id']
        chain = paths(g.db.execute('SELECT * FROM containers').fetchall())
        log(product['name'], '入库', f"{quantity} {product['unit']} → {chain(container['id'])}")
        g.db.commit()
        return jsonify(id=ident, product_id=product['id']), 201

    @app.put('/api/products/<int:ident>')
    @require()
    def update_product(ident):
        row, data = get('products', ident, True), body()
        merged = {**row, **data}
        g.db.execute('UPDATE products SET name=%s,description=%s,photo_id=%s WHERE id=%s',
                     (field(merged, 'name', '物品名'), description(merged), photo(merged, True), ident))
        if 'tags' in data:
            save_tags(ident, data['tags'])
        log(row['name'], '编辑物品资料', field(merged, 'name', '物品名'))
        g.db.commit()
        return jsonify(ok=True)

    @app.post('/api/stocks/<int:ident>/<action>')
    @require()
    def stock_action(ident, action):
        if action not in ('withdraw', 'transfer', 'clear', 'estimate'):
            raise ValueError('未知操作')
        data = body()
        stock = get('stocks', ident, True)
        product = get('products', stock['product_id'])
        chain = paths(g.db.execute('SELECT * FROM containers').fetchall())
        source = chain(stock['container_id'])
        reason = description(data)
        if stock['quantity'] <= 0:
            raise ValueError('此库存已用完或已清除')
        if action == 'clear':
            if not reason:
                raise ValueError('请填写清除原因')
            remaining = Decimal(0)
            detail = f"{source}；清除 {stock['quantity']} {product['unit']}；原因：{reason}"
        elif action == 'estimate':
            if product['mode'] != 'percent':
                raise ValueError('只有百分比物品可目测余量')
            remaining = amount(data.get('quantity'), 'percent', False)
            detail = f"{source}；余量 {stock['quantity']}% → {remaining}%；{reason}"
        else:
            quantity = amount(data.get('quantity'), product['mode'])
            if quantity > stock['quantity']:
                raise ValueError('操作数量不能超过现有库存')
            remaining = stock['quantity'] - quantity
            detail = f"{source}；{quantity} {product['unit']}；余量 {remaining}"
            if action == 'transfer':
                target = destination(data.get('container_id'))
                if target['id'] == stock['container_id']:
                    raise ValueError('目标容器与当前位置相同')
                if product['mode'] == 'percent' and remaining:
                    raise ValueError('百分比记录代表一份包装，请整体转移')
                if remaining == 0:
                    g.db.execute('UPDATE stocks SET container_id=%s,updated_at=%s WHERE id=%s', (target['id'], now(), ident))
                    remaining = stock['quantity']
                else:
                    g.db.execute('INSERT INTO stocks(product_id,container_id,quantity,description,updated_at) VALUES(%s,%s,%s,%s,%s)',
                                 (product['id'], target['id'], quantity, stock['description'], now()))
                detail = f"{source} → {chain(target['id'])}；{quantity} {product['unit']}"
        g.db.execute('UPDATE stocks SET quantity=%s,updated_at=%s WHERE id=%s', (remaining, now(), ident))
        log(product['name'], {'withdraw': '出库', 'transfer': '转移物品', 'clear': '清除记录', 'estimate': '目测余量'}[action], detail)
        g.db.commit()
        return jsonify(ok=True)
