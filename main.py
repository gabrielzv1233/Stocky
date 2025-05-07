from flask import Flask, request, jsonify, render_template_string, redirect, url_for, send_file
from flask_sqlalchemy import SQLAlchemy
from sympy import sympify
from math import ceil 
from PIL import Image
import posixpath
import random
import time
import json
import uuid
import os
import re

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///stock.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# ----------------- Models -----------------
class Category(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100))
    parent_id = db.Column(db.Integer, db.ForeignKey('category.id'), nullable=True)
    children = db.relationship("Category", backref=db.backref('parent', remote_side=[id]), lazy=True)
    items = db.relationship("Item", backref='category', lazy=True)

class Item(db.Model):
    uid = db.Column(db.String(10), primary_key=True)
    name = db.Column(db.String(100))
    count = db.Column(db.Integer)
    timestamp = db.Column(db.Integer)
    category_id = db.Column(db.Integer, db.ForeignKey('category.id'), nullable=True)
    image_paths = db.Column(db.Text)  # JSON-encoded list of image URLs (e.g. ["/static/uploads/abc123_1.webp", ...])

with app.app_context():
    db.create_all()

# ----------------- Utilities -----------------
def generate_uid():
    return "".join(str(random.randint(0, 9)) for i in range(10))

def enforce_name(name):
    trimmed = name.strip()
    if not re.match(r'^[A-Za-z0-9 _\-,.]+$', trimmed):
        return None
    return trimmed

def build_breadcrumb(category):
    parts = []
    current = category
    while current:
        parts.append(current.name)
        current = current.parent
    parts.reverse()
    return "/" + "/".join(parts) if parts else "/"

def build_breadcrumb_disp(category):
    parts = []
    current = category
    while current:
        parts.append(current.name)
        current = current.parent
    parts.reverse()
    return "<b>/</b>" + "<b> / </b>".join(parts) if parts else "<b>/</b>"

def resolve_path(current_path, input_path):
    if input_path.startswith("/"):
        abs_path = input_path
    else:
        abs_path = posixpath.join(current_path, input_path)
    return posixpath.normpath(abs_path) + "/"  if abs_path != "/" else "/"

def duplicate_exists(target_category, name, is_category, exclude_id=None):
    name_lower = name.lower()
    if is_category:
        query = Category.query.filter(db.func.lower(Category.name)==name_lower)
        if target_category:
            query = query.filter(Category.parent_id==target_category.id)
        else:
            query = query.filter(Category.parent_id==None)
        if exclude_id:
            query = query.filter(Category.id != exclude_id)
        return query.first() is not None
    else:
        query = Item.query.filter(db.func.lower(Item.name)==name_lower)
        if target_category:
            query = query.filter(Item.category_id==target_category.id)
        else:
            query = query.filter(Item.category_id==None)
        if exclude_id:
            query = query.filter(Item.uid != exclude_id)
        return query.first() is not None

# ----------------- Explorer (File Browser) -----------------
@app.route('/')
def explorer():
    cat_id = request.args.get('cat')
    if cat_id:
        category = Category.query.filter_by(id=cat_id).first()
        if not category:
            return redirect(url_for('explorer'))
        subcategories = Category.query.filter_by(parent_id=category.id).order_by(Category.name).all()
        items = Item.query.filter_by(category_id=category.id).order_by(Item.name).all()
        breadcrumb = build_breadcrumb_disp(category)
        parentPath = build_breadcrumb(category.parent) if category.parent else "/"
    else:
        category = None
        subcategories = Category.query.filter_by(parent_id=None).order_by(Category.name).all()
        items = Item.query.filter_by(category_id=None).order_by(Item.name).all()
        breadcrumb = "<b>/</b>"
        parentPath = None

    return render_template_string("""
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Stocky</title>
    <style>
        body { background-color: #2c2c2c; color: #f0f0f0; font-family: Arial, sans-serif; margin: 0; }
        .explorer { padding: 20px; }
        .header { display: flex; flex-direction: column; gap: 5px; width: 100%; }
        .breadcrumb { padding-bottom: 10px; font-size: 14px; }
        .controls { display: flex; justify-content: space-between; align-items: center; width: 100%; }
        .buttons button { padding: 5px 10px; margin-right: 3px; background-color: #ffffff; color: #000; border: solid 1.5px black; border-radius: 7px; cursor: pointer; }
        .list { margin-top: 20px; }
        .folder, .item { padding: 10px; border: 1px solid #444; margin-bottom: 5px; cursor: pointer; }
        .folder:hover, .item:hover { background-color: #444; }
        .selected { border: 2px solid #007bff; }
        .back-folder { background-color: #333; }
        .empty-message { text-align: left; padding-bottom: 20px; font-size: 14px; color: #888; }
    </style>
    <script src="https://code.jquery.com/jquery-3.6.0.min.js"></script>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body>
    <div class="explorer">
        <div class="header">
            <span class="breadcrumb">{{ breadcrumb | safe }}</span>
            <div class="controls">
                <div class="buttons">
                    <button onclick="newSubCategory()">New Sub Category</button><button onclick="newItem()">New Item</button><button onclick="deleteSelected()">Delete</button>
                </div>
            </div>
        </div>
        <div class="list" id="listContainer">
            {% if category %}
                <div class="folder back-folder" data-path="{{ parentPath }}" draggable="true"
                    ondblclick="goBack()"
                    ondragstart="dragStart(event, this)" ondragover="allowDrop(event)" ondrop="drop(event, this)">
                    ⬅️ ...
                </div>
            {% endif %}
            {% for cat in subcategories %}
                <div class="folder" data-id="{{ cat.id }}" data-path="{{ build_breadcrumb(cat) }}" draggable="true" 
                     ondragstart="dragStart(event, this)" ondragover="allowDrop(event)" ondrop="drop(event, this)" 
                     onclick="selectItem(this, 'category', '{{ cat.id }}')" ondblclick="openFolder({{ cat.id }})">
                    📁 {{ cat.name }}
                </div>
            {% endfor %}
            {% for item in items %}
                <div class="item" data-uid="{{ item.uid }}" draggable="true" 
                     ondragstart="dragStart(event, this)" onclick="selectItem(this, 'item', '{{ item.uid }}')" 
                     ondblclick="openItem('{{ item.uid }}')">
                    📄 {{ item.name }} ({{ item.count }})
                </div>
            {% endfor %}
            {% if not subcategories and not items %}
                <div class="empty-message">
                    📂 This folder is empty.
                </div>
            {% endif %}
        </div>
    </div>
<script>
    // Navigation functions
    function goBack() {
        let parentId = "{{ category.parent_id if category and category.parent_id else '' }}";
        if (parentId) {
            location.href = "/?cat=" + parentId;
        } else {
            location.href = "/";
        }
    }
    // Global selected element variable
    let selected = null; // { type: 'item' or 'category', id: '...' }
    function selectItem(element, type, id) {
        document.querySelectorAll('.selected').forEach(el => el.classList.remove('selected'));
        element.classList.add('selected');
        selected = {type: type, id: id};
    }
    function openFolder(id) { location.href = "/?cat=" + id; }
    function openItem(uid) {
        let params = new URLSearchParams(window.location.search);
        location.href = "/edit/" + uid + "?" + params.toString();
    }
    function newSubCategory() {
        let name = prompt("Enter sub category name:").trim();
        if(name) {
            let valid = enforceNameJS(name);
            if(!valid) { alert("Invalid name. Only letters, spaces, underscores, and dashes allowed."); return; }
            let parent_id = "{{ category.id if category else '' }}";
            $.post("/api/new_category", { name: name, parent_id: parent_id }, function(data){
                if(data.success===false){ alert(data.message); } else { location.reload(); }
            });
        }
    }
    function newItem() {
        let name = prompt("Enter item name:").trim();
        if(name) {
            let valid = enforceNameJS(name);
            if(!valid) { alert("Invalid name. Only letters, spaces, underscores, and dashes allowed."); return; }
            let parent_id = "{{ category.id if category else '' }}";
            $.post("/api/new_item", { name: name, category_id: parent_id }, function(data){
                if(data.success===false){ alert(data.message); }
                else { location.href = "/edit/" + data.uid + (location.search ? location.search : ""); }
            });
        }
    }
    // Simple JS version of enforceName for client-side checking
    function enforceNameJS(name) {
        let pattern = /^[A-Za-z0-9 _\-,.]+$/;
        return pattern.test(name);
    }
    // Drag & Drop functions
    function dragStart(e, el) {
        let type = el.classList.contains("folder") ? "category" : "item";
        let id = type === "category" ? el.getAttribute("data-id") : el.getAttribute("data-uid");
        e.dataTransfer.setData("application/json", JSON.stringify({ type: type, id: id }));
    }
    function allowDrop(e) { e.preventDefault(); }
    function drop(e, target) {
        e.preventDefault();
        let data = e.dataTransfer.getData("application/json");
        if (!data) return;
        let obj = JSON.parse(data);
        let targetPath = target.getAttribute("data-path");
        if (!targetPath) { alert("Invalid drop target."); return; }
        // Use the target folder's absolute path for the move.
        $.post("/api/move", { type: obj.type, id: obj.id, path: targetPath }, function(data) {
            if (!data.success) { alert(data.message); } else { location.reload(); }
        });
    }

    function deleteSelected() {
        if (!selected) { alert("Please select an item or category first."); return; }
        if (confirm("Are you sure you want to delete the selected " + selected.type + "?")) {
            $.post("/api/delete", { type: selected.type, id: selected.id }, function(data) {
                if (!data.success) { alert(data.message); } else { location.reload(); }
            });
        }
    }
</script>
</body>
</html>
    """, category=category, subcategories=subcategories, items=items, breadcrumb=breadcrumb, parentPath=parentPath, build_breadcrumb=build_breadcrumb)

# ----------------- API Endpoints -----------------
@app.route('/api/items_index')
def items_index():
    categories = Category.query.all()
    items = Item.query.all()
    index = []

    for cat in categories:
        index.append({
            "type": "category",
            "id": cat.id,
            "name": cat.name.lower(),
            "count": 0,
            "path": build_breadcrumb(cat) + "/"
        })

    for item in items:
        index.append({
            "type": "item",
            "uid": item.uid,
            "name": item.name.lower(),
            "count": item.count,
            "path": (build_breadcrumb(item.category) if item.category else "/") + item.name
        })

    return jsonify(index)

@app.route('/api/get_path', methods=['GET'])
def get_path():
    type_ = request.args.get('type')
    id_ = request.args.get('id')
    if type_ == 'category':
        category = Category.query.filter_by(id=id_).first()
        if not category:
            return jsonify({"message": "Category not found.", "success": False})
        path = build_breadcrumb(category)
    elif type_ == 'item':
        item = Item.query.filter_by(uid=id_).first()
        if not item:
            return jsonify({"message": "Item not found.", "success": False})
        path = (build_breadcrumb(item.category) if item.category else "/")
    else:
        return jsonify({"message": "Invalid type.", "success": False})
    return jsonify({"path": path, "success": True})

@app.route('/api/new_item', methods=['POST'])
def new_item():
    name = request.form.get('name')
    name = enforce_name(name) if name else None
    if not name:
        return jsonify({"message": "Invalid item name.", "success": False})
    category_id = request.form.get('category_id')
    if category_id == '':
        category_id = None
    if duplicate_exists(Category.query.get(category_id) if category_id else None, name, is_category=False):
        return jsonify({"message": "Item with that name already exists.", "success": False})
    uid = generate_uid()
    timestamp = int(time.time())
    item = Item(uid=uid, name=name, count=0, timestamp=timestamp, category_id=category_id)
    db.session.add(item)
    db.session.commit()
    return jsonify({"message": "Created", "uid": uid, "success": True})

@app.route('/api/new_category', methods=['POST'])
def new_category():
    name = request.form.get('name')
    name = enforce_name(name) if name else None
    if not name:
        return jsonify({"message": "Invalid category name.", "success": False})
    parent_id = request.form.get('parent_id')
    if parent_id == '':
        parent_id = None
    if duplicate_exists(Category.query.get(parent_id) if parent_id else None, name, is_category=True):
        return jsonify({"message": "Category with that name already exists.", "success": False})
    cat = Category(name=name, parent_id=parent_id)
    db.session.add(cat)
    db.session.commit()
    return jsonify({"message": "Category created", "id": cat.id, "success": True})

@app.route('/api/move', methods=['POST'])
def move():
    type_ = request.form.get('type')
    id_ = request.form.get('id')
    input_path = request.form.get('path').strip()

    if not input_path:
        return jsonify({"message": "No path provided.", "success": False})

    input_path = posixpath.normpath(input_path)
    if not input_path.startswith("/"):
        return jsonify({"message": "Invalid path. Must be absolute and start with '/'", "success": False})

    abs_path = input_path.rstrip("/") if input_path != "/" else "/"

    print(f"Attempting to move {type_} {id_} to {abs_path}")

    target_category = None if abs_path == "/" else None
    if abs_path != "/":
        path_parts = [p for p in abs_path.split("/") if p]
        current = None

        for part in path_parts:
            found = Category.query.filter(db.func.lower(Category.name) == part.lower(), Category.parent_id == (current.id if current else None)).first()
            if not found:
                return jsonify({"message": f"Path not found: {abs_path}", "success": False})
            current = found

        target_category = current

    if type_ == "category":
        category = Category.query.filter_by(id=id_).first()
        if not category:
            return jsonify({"message": "Category not found.", "success": False})

        cur = target_category
        while cur:
            if cur.id == category.id:
                return jsonify({"message": "Cannot move a category into itself or its descendant.", "success": False})
            cur = cur.parent

        if (category.parent_id or None) == (target_category.id if target_category else None):
            return jsonify({"message": "Category already in this location.", "success": True})

        if duplicate_exists(target_category, category.name, is_category=True, exclude_id=category.id):
            return jsonify({"message": "A category with that name already exists at the target location.", "success": False})

        category.parent_id = target_category.id if target_category else None

    elif type_ == "item":
        item = Item.query.filter_by(uid=id_).first()
        if not item:
            return jsonify({"message": "Item not found.", "success": False})

        if (item.category_id or None) == (target_category.id if target_category else None):
            return jsonify({"message": "Item already in this location.", "success": True})

        if duplicate_exists(target_category, item.name, is_category=False, exclude_id=item.uid):
            return jsonify({"message": "An item with that name already exists at the target location.", "success": False})

        item.category_id = target_category.id if target_category else None

    else:
        return jsonify({"message": "Invalid type.", "success": False})

    db.session.commit()
    return jsonify({"message": "Move successful.", "success": True})

def category_has_items(cat):
    if cat.items:
        return True
    for child in cat.children:
        if category_has_items(child):
            return True
    return False

@app.route('/api/delete', methods=['POST'])
def delete():
    type_ = request.form.get('type')
    id_ = request.form.get('id')
    if type_ == 'item':
        item = Item.query.filter_by(uid=id_).first()
        if item:
            db.session.delete(item)
            db.session.commit()
            return jsonify({"message": "Item deleted", "success": True})
        else:
            return jsonify({"message": "Item not found", "success": False})
    elif type_ == 'category':
        cat = Category.query.filter_by(id=id_).first()
        if cat:
            if category_has_items(cat):
                return jsonify({"message": "Cannot delete category: it contains files.", "success": False})
            def delete_cat(c):
                for child in c.children:
                    delete_cat(child)
                db.session.delete(c)
            delete_cat(cat)
            db.session.commit()
            return jsonify({"message": "Category deleted", "success": True})
        else:
            return jsonify({"message": "Category not found", "success": False})
    return jsonify({"message": "Invalid type", "success": False})

@app.route('/api/item/<uid>', methods=['GET', 'POST'])
def item_api(uid):
    item = Item.query.filter_by(uid=uid).first()
    if request.method == 'GET':
        if item:
            return jsonify({
                "uid": item.uid,
                "name": item.name,
                "count": item.count,
                "timestamp": item.timestamp,
                "category_id": item.category_id
            })
        else:
            return jsonify({"message": "Item not found"}), 404
    else:
        data = request.form
        new_name = data.get('name').strip()
        new_name = enforce_name(new_name)
        if not new_name:
            return jsonify({"message": "Invalid name.", "success": False})
        current_cat = item.category
        if duplicate_exists(current_cat, new_name, is_category=False, exclude_id=item.uid):
            return jsonify({"message": "An item with that name already exists in this folder.", "success": False})
        item.name = new_name
        if re.search(r"\d", data.get('count')):
            item.count = int(ceil(sympify(re.sub(r"[^0-9+\-*/(). ]", "", (data.get('count') or '')).strip() or '0').evalf()))
        else:
            item.count = item.count if item.count > 0 else 0
        item.timestamp = int(time.time())
        db.session.commit()
        return jsonify({"message": "Item updated", "success": True})

@app.route('/api/upload_image/<uid>', methods=['POST'])
def upload_image(uid):
    item = Item.query.filter_by(uid=uid).first()
    if not item:
        return jsonify({"message": "Item not found", "success": False}), 404

    images = json.loads(item.image_paths) if item.image_paths else []
    if len(images) >= 3:
        return jsonify({"message": "Maximum images reached", "success": False}), 400

    if 'file' not in request.files:
        return jsonify({"message": "No file provided", "success": False}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({"message": "No selected file", "success": False}), 400

    try:
        image = Image.open(file.stream).convert("RGBA")
    except Exception as e:
        return jsonify({"message": "Invalid image file", "success": False}), 400

    upload_folder = os.path.join(app.root_path, 'static', 'uploads')
    os.makedirs(upload_folder, exist_ok=True)

    image_uid = uuid.uuid4().hex[:8]

    # ===== Full image (downscale to max 1080px on any axis) =====
    orig_w, orig_h = image.size
    scale = min(1080 / orig_w, 1080 / orig_h, 1.0)
    new_orig_size = (int(orig_w * scale), int(orig_h * scale))
    full_image = image.resize(new_orig_size, Image.Resampling.LANCZOS)

    full_filename = f"{uid}_{image_uid}_full.webp"
    full_path = os.path.join(upload_folder, full_filename)
    full_image.save(full_path, "WEBP")
    full_url = f"/static/uploads/{full_filename}"

    # ===== Thumbnail image (crop 128x128 centered) =====
    thumb_scale = 128 / min(orig_w, orig_h)
    thumb_w, thumb_h = int(orig_w * thumb_scale), int(orig_h * thumb_scale)
    thumb_image = image.resize((thumb_w, thumb_h), Image.Resampling.LANCZOS)

    left = (thumb_w - 128) // 2
    top = (thumb_h - 128) // 2
    thumb_image = thumb_image.crop((left, top, left + 128, top + 128))

    thumb_filename = f"{uid}_{image_uid}_thumb.webp"
    thumb_path = os.path.join(upload_folder, thumb_filename)
    thumb_image.save(thumb_path, "WEBP")
    thumb_url = f"/static/uploads/{thumb_filename}"

    images.append({
        "thumb": thumb_url,
        "full": full_url
    })
    item.image_paths = json.dumps(images)
    db.session.commit()

    return jsonify({
        "message": "Image uploaded",
        "success": True,
        "image_path": thumb_url,
        "full_path": full_url
    })

@app.route('/api/delete_image/<uid>', methods=['POST'])
def delete_image(uid):
    item = Item.query.filter_by(uid=uid).first()
    if not item:
        return jsonify({"message": "Item not found", "success": False}), 404

    thumb_to_delete = request.form.get('thumb')
    if not thumb_to_delete:
        return jsonify({"message": "Missing thumbnail path", "success": False}), 400

    images = json.loads(item.image_paths) if item.image_paths else []
    updated_images = []

    deleted_thumb = None
    deleted_full = None

    for img in images:
        if isinstance(img, str) and img == thumb_to_delete:
            deleted_thumb = os.path.join(app.root_path, img.lstrip("/"))
        elif isinstance(img, dict) and img.get("thumb") == thumb_to_delete:
            deleted_thumb = os.path.join(app.root_path, img["thumb"].lstrip("/"))
            deleted_full = os.path.join(app.root_path, img["full"].lstrip("/"))
        else:
            updated_images.append(img)

    if not deleted_thumb or not os.path.exists(deleted_thumb):
        return jsonify({"message": "Image not found", "success": False}), 404

    try:
        os.remove(deleted_thumb)
        if deleted_full and os.path.exists(deleted_full):
            os.remove(deleted_full)
    except Exception as e:
        return jsonify({"message": f"Failed to delete files: {str(e)}", "success": False}), 500

    item.image_paths = json.dumps(updated_images)
    db.session.commit()
    return jsonify({"message": "Image deleted", "success": True})

# ----------------- Export -----------------
@app.route('/export')
def export():
    data = {}
    cats = Category.query.all()
    its = Item.query.all()
    data['categories'] = [{"id": c.id, "name": c.name, "parent_id": c.parent_id} for c in cats]
    data['items'] = [{"uid": i.uid, "name": i.name, "count": i.count, "timestamp": i.timestamp, "category_id": i.category_id} for i in its]
    return app.response_class(
        response=json.dumps(data, indent=4),
        mimetype='application/json'
    )

# ----------------- Item Editor -----------------
@app.route('/view_image/<filename>')
def view_image(filename):
    path = os.path.join(app.root_path, 'static', 'uploads', filename)
    if not os.path.exists(path):
        return "Image not found", 404
    return send_file(path, mimetype='image/webp', as_attachment=False)

@app.route('/edit/<uid>')
def edit(uid):
    item = Item.query.filter_by(uid=uid).first()
    if not item:
        return "Item not found", 404

    parent_cat = request.args.get('cat', '')
    images = json.loads(item.image_paths) if item.image_paths else []

    return render_template_string("""
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Stocky - Edit Item</title>
    <style>
        body { background-color: #2c2c2c; color: #f0f0f0; font-family: Arial, sans-serif; padding: 20px; }
        .editor { max-width: 600px; margin: auto; }
        input { width: 100%; padding: 10px; margin-bottom: 10px; background-color: #444; border: 1px solid #666; color: #f0f0f0; }
        .buttons { position: fixed; bottom: 20px; right: 20px; }
        .buttons button { margin-left: 5px; padding: 10px 20px; }
        .cancel { background: #fff; color: #888; border: 1px solid #888; }
        .save { background: #007bff; color: #fff; border: none; }
        .spancopy {
            cursor: pointer;
            font-family: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace;
            background-color: #424242;
            color: #E7E7E7;
            padding: 2px 5px;
            border-radius: 4px;
            font-size: 0.95em;
            white-space: nowrap;
        }
        #imageUploadContainer { margin-top: 20px; }
        #uploadWrapper { display: inline-block; width: 128px; height: 128px; cursor: pointer; }
        #uploadWrapper img { width: 128px; height: 128px; }
        #imageContainer { display: inline-block; margin-left: 10px; vertical-align: top; }
        #imageContainer img { width: 128px; height: 128px; object-fit: cover; object-position: center; margin: 5px; cursor: pointer; }
        #imageUploadContainer {
            display: flex;
            flex-wrap: wrap;
            gap: 10px;
        }
        #uploadWrapper {
            width: 128px;
            height: 128px;
            cursor: pointer;
        }
        #uploadWrapper img {
            width: 100%;
            height: 100%;
        }
        #imageContainer {
            display: flex;
            flex-wrap: wrap;
            gap: 10px;
        }
        .uploaded-img {
            width: 128px;
            height: 128px;
            object-fit: cover;
            object-position: center;
            cursor: pointer;
        }
        
    </style>
    <script src="https://code.jquery.com/jquery-3.6.0.min.js"></script>
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
</head>
<body>
    <div class="editor">
        <h2>Editing item <code class="spancopy" onclick="copyid(event)">{{ item.uid }}</code>:</h2>
        <input type="hidden" id="serverTimestamp" value="{{ item.timestamp }}">
        <label>Name:</label>
        <input type="text" id="name" value="{{ item.name }}">
        <label>Count:</label>
        <input pattern="[0-9+\-*/(). ]*" type="text" id="count" placeholder="{{ 0 if item.count <= 0 else item.count }}" value="{{ '' if item.count <= 0 else item.count }}">

        <div id="imageUploadContainer">
            <div id="uploadWrapper">
                <img id="uploadBtn" src="/static/upload_button.png" alt="Upload Image">
                <input type="file" id="imageInput" accept="image/*" style="display:none">
            </div>
            <div id="imageContainer">
                {% for img in images %}
                    <img class="uploaded-img" src="{{ img.thumb }}" data-full="{{ img.full }}" alt="Uploaded Image">
                {% endfor %}
            </div>
        </div>
    </div>
    <div class="buttons">
        <button class="cancel" onclick="cancelEdit()">Cancel</button>
        <button class="save" onclick="saveAndExit()">Save & Exit</button>
    </div>
<script>
    document.addEventListener("DOMContentLoaded", function() {
        document.querySelectorAll(".spancopy").forEach(span => {
            span.setAttribute("title", "Click to copy");
        });
    });
    function copyid(event) {
        let span = event.target;
        let originalText = span.innerText || span.textContent;
        if (navigator.clipboard && window.isSecureContext) {
            navigator.clipboard.writeText(originalText).then(() => {
                span.innerText = "Copied!";
                setTimeout(() => { span.innerText = originalText; }, 1000);
            });
        } else {
            let textarea = document.createElement("textarea");
            textarea.value = originalText;
            document.body.appendChild(textarea);
            textarea.select();
            document.execCommand("copy");
            span.innerText = "Copied!";
            setTimeout(() => { span.innerText = originalText; }, 1000);
            document.body.removeChild(textarea);
        }
    }

    const uid = "{{ item.uid }}";
    const autosaveKey = "autosave_" + uid;
    const parentCat = "{{ parent_cat }}";

    $(document).ready(function(){
        let autosaveData = localStorage.getItem(autosaveKey);
        if(autosaveData){
            let data = JSON.parse(autosaveData);
            let serverTs = parseInt($("#serverTimestamp").val());
            if(data.timestamp > serverTs){
                if(confirm("Found a local autosave that has not been pushed. Restore it?")){
                    $("#name").val(data.name);
                    $("#count").val(data.count);
                } else {
                    localStorage.removeItem(autosaveKey);
                }
            }
        }

        $("#uploadBtn").on("click", function() {
            if ($("#imageContainer img").length >= 3) return;
            $("#imageInput").click();
        });

        $("#imageInput").on("change", function(e) {
            let file = e.target.files[0];
            if(file) {
                uploadImage(file);
                $(this).val("");
            }
        });

        $("#uploadWrapper").on("dragover", function(e) {
            e.preventDefault();
            $(this).css("border", "2px dashed #007bff");
        });
        $("#uploadWrapper").on("dragleave", function(e) {
            e.preventDefault();
            $(this).css("border", "none");
        });
        $("#uploadWrapper").on("drop", function(e) {
            e.preventDefault();
            $(this).css("border", "none");
            let file = e.originalEvent.dataTransfer.files[0];
            if(file) uploadImage(file);
        });

        attachImageClickHandlers();
    });

    function uploadImage(file) {
        let formData = new FormData();
        formData.append("file", file);
        $.ajax({
            url: "/api/upload_image/" + uid,
            type: "POST",
            data: formData,
            processData: false,
            contentType: false,
            success: function(data) {
                if(data.success) {
                    let img = $("<img>", {
                        src: data.image_path,
                        "data-full": data.full_path,
                        class: "uploaded-img",
                        alt: "Uploaded Image"
                    }).css({ width: "128px", height: "128px", "object-fit": "cover", "object-position": "center", margin: "5px", cursor: "pointer" });

                    $("#imageContainer").append(img);
                    attachImageClickHandlers();

                    if($("#imageContainer img").length >= 3){
                        $("#uploadWrapper").hide();
                    }
                } else {
                    alert(data.message);
                }
            }
        });
    }

    function attachImageClickHandlers(){
        $(".uploaded-img").off("click").on("click", function(e) {
            const $img = $(this);
            if (this.clickTimeout) {
                clearTimeout(this.clickTimeout);
                this.clickTimeout = null;

                if (confirm("Do you want to delete this image?")) {
                    $.post("/api/delete_image/" + uid, {
                        thumb: $img.attr("src")
                    }, function(data) {
                        if (data.success) {
                            $img.remove();
                            if ($("#imageContainer img").length < 3) {
                                $("#uploadWrapper").show();
                            }
                        } else {
                            alert(data.message);
                        }
                    });
                }
            } else {
                this.clickTimeout = setTimeout(() => {
                    this.clickTimeout = null;
                    let fullPath = $img.attr("data-full").split("/").pop();
                    window.open("/view_image/" + fullPath, "_blank");
                }, 500);
            }
        });
    }

    function autosave(){
        let data = {
            name: $("#name").val(),
            count: $("#count").val(),
            timestamp: Date.now()
        };
        localStorage.setItem(autosaveKey, JSON.stringify(data));
    }

    setInterval(autosave, 15000);
    $("input").on("blur", autosave);
    $("#count").on("keydown", function(e){
        let val = parseInt($(this).val());
        if(isNaN(val)) val = 0;
        if(e.key === "ArrowUp"){ $(this).val(val+1); e.preventDefault(); }
        else if(e.key === "ArrowDown"){ $(this).val(val-1); e.preventDefault(); }
    });

    function saveItem(callback){
        $.post("/api/item/" + uid, {
            name: $("#name").val(),
            count: $("#count").val(),
        }, function(data){
            if(data.success === false){ alert(data.message); }
            localStorage.removeItem(autosaveKey);
            if(callback) callback();
        });
    }

    function saveAndExit(){ saveItem(function(){ window.location.href = "/?cat=" + parentCat; }); }
    function cancelEdit(){ localStorage.removeItem(autosaveKey); window.location.href = "/?cat=" + parentCat; }
</script>
</body>
</html>
    """, item=item, parent_cat=parent_cat, images=images)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)