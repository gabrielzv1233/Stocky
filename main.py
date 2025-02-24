from flask import Flask, request, jsonify, render_template_string, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
import os, random, time, json

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///stock.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

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
    tags = db.Column(db.String(200))
    timestamp = db.Column(db.Integer)
    category_id = db.Column(db.Integer, db.ForeignKey('category.id'), nullable=True)

with app.app_context():
    db.create_all()

def generate_uid():
    uid = ""
    for i in range(10):
        uid = uid + str(random.randint(0, 9))
    return uid

def build_breadcrumb(category):
    breadcrumb = []
    current = category
    while current:
        breadcrumb.append(current.name)
        current = current.parent
    breadcrumb.reverse()
    return "Root/" + "/".join(breadcrumb) if breadcrumb else "Root"

def build_breadcrumb_disp(category):
    breadcrumb = []
    current = category
    while current:
        breadcrumb.append(current.name)
        current = current.parent
    breadcrumb.reverse()
    return "Root > " + " > ".join(breadcrumb) if breadcrumb else "Root"

# --------------------- Explorer (File Browser) ---------------------
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
        parentPath = build_breadcrumb(category.parent) if category.parent else "Root"
    else:
        category = None
        subcategories = Category.query.filter_by(parent_id=None).order_by(Category.name).all()
        items = Item.query.filter_by(category_id=None).order_by(Item.name).all()
        breadcrumb = "Root"
        parentPath = None

    return render_template_string("""
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Stock Explorer</title>
    <style>
        body { background-color: #2c2c2c; color: #f0f0f0; font-family: Arial, sans-serif; margin-top: 0px; }
        .explorer { padding-top: 20px; }
        .header { display: flex; flex-direction: column; gap: 5px; width: 100%; }
        .breadcrumb { flex: 1; padding-bottom: 10px;}
        .controls { display: flex; justify-content: space-between; align-items: center; width: 100%; }
        .buttons button { padding: 5px 10px; }
        .search-bar { margin-left: auto; }
        .list { margin-top: 20px; }
        .folder, .item { padding: 10px; border: 1px solid #444; margin-bottom: 5px; cursor: pointer; }
        .folder:hover, .item:hover { background-color: #444; }
        .selected { border: 2px solid #007bff; }
        /* Back folder styling */
        .back-folder { background-color: #333;}
    </style>
    <!-- Include Fuse.js for fuzzy search and jQuery -->
    <script src="https://cdnjs.cloudflare.com/ajax/libs/fuse.js/6.6.2/fuse.basic.min.js"></script>
    <script src="https://code.jquery.com/jquery-3.6.0.min.js"></script>
</head>
<body>
    <div class="explorer">
        <div class="header">
            <span class="breadcrumb">{{ breadcrumb }}</span>
            <div class="controls">
                <div class="buttons">
                    <button onclick="newSubCategory()">New Sub Category</button>
                    <button onclick="newItem()">New Item</button>
                    <button onclick="copyPath()">Copy Path</button>
                    <button onclick="moveSelected()">Move</button>
                    <button onclick="deleteSelected()">Delete</button>
                </div>
                <div class="search-bar">
                    <input type="text" id="searchInput" placeholder="Search...">
                </div>
            </div>
        </div>
        </div>
        <div class="list" id="listContainer">
            <!-- If not at root, show the back folder at the top -->
            {% if category %}
                <div class="folder back-folder" data-path="{{ parentPath }}" draggable="true"
                    ondblclick="goBack()"
                    ondragstart="dragStart(event, this)" ondragover="allowDrop(event)" ondrop="drop(event, this)">
                    ⬅️ ...
                </div>
            {% endif %}
            <!-- Folders (each folder has a data-path attribute for its full path) -->
            {% for cat in subcategories %}
                <div class="folder" data-id="{{ cat.id }}" data-path="{{ build_breadcrumb(cat) }}" draggable="true" ondragstart="dragStart(event, this)" ondragover="allowDrop(event)" ondrop="drop(event, this)" onclick="selectItem(this, 'category', '{{ cat.id }}')" ondblclick="openFolder({{ cat.id }})">
                    📁 {{ cat.name }}
                </div>
            {% endfor %}
            <!-- Files (items) -->
            {% for item in items %}
                <div class="item" data-uid="{{ item.uid }}" draggable="true" ondragstart="dragStart(event, this)" onclick="selectItem(this, 'item', '{{ item.uid }}')" ondblclick="openItem('{{ item.uid }}')">
                    📄 {{ item.name }} ({{ item.count }})
                </div>
            {% endfor %}
            
            {% if not subcategories and not items %}
                <div class="empty-message" style="text-align: left; padding-bottom: 20px; font-size: 14px;">
                    📂 This folder is empty.
                </div>
            {% endif %}
        </div>
    </div>
<script>
    function goBack() {
        let parentId = "{{ category.parent_id if category and category.parent_id else '' }}";
        if (parentId) {
            location.href = "/?cat=" + parentId;
        } else {
            location.href = "/";
        }
    }
    // Global variable for selected element
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
        let name = prompt("Enter sub category name:");
        if(name) {
            let parent_id = "{{ category.id if category else '' }}";
            $.post("/api/new_category", { name: name, parent_id: parent_id }, function(){
                location.reload();
            });
        }
    }
    function newItem() {
        let name = prompt("Enter item name:");
        if(name) {
            let parent_id = "{{ category.id if category else '' }}";
            $.post("/api/new_item", { name: name, category_id: parent_id }, function(data){
                location.href = "/edit/" + data.uid + (location.search ? location.search : "");
            });
        }
    }
    // Custom drag & drop functions
    function dragStart(e, el) {
        // Determine type and id from element
        let type = el.classList.contains("folder") ? "category" : "item";
        let id = type === "category" ? el.getAttribute("data-id") : el.getAttribute("data-uid");
        e.dataTransfer.setData("application/json", JSON.stringify({ type: type, id: id }));
    }
    function allowDrop(e) {
        e.preventDefault();
    }
    function drop(e, target) {
    e.preventDefault();
    let data = e.dataTransfer.getData("application/json");
    if (!data) return;
    let obj = JSON.parse(data);
    // Get target folder's full path from its data-path attribute.
    let targetPath = target.getAttribute("data-path");
    if (!targetPath) {
        alert("Invalid drop target.");
        return;
    }
    $.post("/api/move", { type: obj.type, id: obj.id, path: targetPath }, function (data) {
        if (!data.success) {
            alert(data.message);
        } else {
            location.reload();
        }
    });
}
    // For the "Move" button (if using a prompt)
    function moveSelected() {
    if (!selected) {
        alert("Please select an item or category first.");
        return;
    }
    let target = prompt("Enter full path (e.g., Root/Folder/Subfolder):");
    if (!target) {
        alert("Move canceled.");
        return;
    }
    $.post("/api/move", { type: selected.type, id: selected.id, path: target }, function (data) {
        if (!data.success) {
            alert(data.message);
        } else {
            location.reload();
        }
    });
}

    // Copy Path button functionality
    function copyPath() {
        if (!selected) {
            alert("Please select an item or category first.");
            return;
        }
        $.get("/api/get_path", { type: selected.type, id: selected.id }, function (data) {
            if (data.success) {
                copyToClipboard(data.path);
                let button = document.querySelector("button[onclick='copyPath()']");
                let originalText = button.innerText;
                button.innerText = "Copied!";
                setTimeout(() => { button.innerText = originalText; }, 3000);
            } else {
                alert(data.message);
            }
        });
    }
    function copyToClipboard(text) {
        const tempInput = document.createElement("input");
        document.body.appendChild(tempInput);
        tempInput.value = text;
        tempInput.select();
        document.execCommand("copy");
        document.body.removeChild(tempInput);
    }
    function deleteSelected() {
    if (!selected) {
        alert("Please select an item or category first.");
        return;
    }
    if (confirm("Are you sure you want to delete the selected " + selected.type + "?")) {
        $.post("/api/delete", { type: selected.type === 'category' ? 'category' : 'item', id: selected.id }, function (data) {
            if (!data.success) {
                alert(data.message);
            } else {
                location.reload();
            }
        });
    }
}

    // Search using Fuse.js
    let fuse;
    let itemsIndex = [];
    $(document).ready(function(){
        $.getJSON("/api/items_index", function(data){
            itemsIndex = data;
            fuse = new Fuse(itemsIndex, { keys: ['name', 'tags'], threshold: 0.4 });
        });
        $("#searchInput").on("input", function(){
            let query = $(this).val();
            if(query.trim() === ""){
                $(".folder, .item").show();
            } else {
                let results = fuse.search(query);
                $(".folder, .item").hide();
                results.forEach(function(res){
                    if(res.item.type === "category"){
                        $(".folder[data-id='" + res.item.id + "']").show();
                    } else {
                        $(".item[data-uid='" + res.item.uid + "']").show();
                    }
                });
            }
        });
    });
</script>
</body>
</html>
    """, category=category, subcategories=subcategories, items=items, breadcrumb=breadcrumb, parentPath=parentPath, build_breadcrumb=build_breadcrumb)

# --------------------- API Endpoints ---------------------
@app.route('/api/items_index')
def items_index():
    categories = Category.query.all()
    items = Item.query.all()
    index = []
    for cat in categories:
        index.append({
            "type": "category",
            "id": cat.id,
            "name": cat.name,
            "tags": ""
        })
    for item in items:
        index.append({
            "type": "item",
            "uid": item.uid,
            "name": item.name,
            "tags": item.tags
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
        path = build_breadcrumb(item.category) if item.category else "Root"
    else:
        return jsonify({"message": "Invalid type.", "success": False})
    return jsonify({"path": path, "success": True})

@app.route('/api/new_item', methods=['POST'])
def new_item():
    name = request.form.get('name')
    category_id = request.form.get('category_id')
    if category_id == '':
        category_id = None
    existing = Item.query.filter_by(name=name, category_id=category_id).first()
    if existing:
        return jsonify({"message": "Item exists", "uid": existing.uid})
    uid = generate_uid()
    timestamp = int(time.time())
    item = Item(uid=uid, name=name, count=0, tags="", timestamp=timestamp, category_id=category_id)
    db.session.add(item)
    db.session.commit()
    return jsonify({"message": "Created", "uid": uid})

@app.route('/api/new_category', methods=['POST'])
def new_category():
    name = request.form.get('name')
    parent_id = request.form.get('parent_id')
    if parent_id == '':
        parent_id = None
    cat = Category(name=name, parent_id=parent_id)
    db.session.add(cat)
    db.session.commit()
    return jsonify({"message": "Category created", "id": cat.id})

@app.route('/api/move', methods=['POST'])
def move():
    type_ = request.form.get('type')
    id_ = request.form.get('id')
    path = request.form.get('path')
    
    if path == "Root":
        path = "Root/"
        
    if not path or not path.startswith("Root/"):
        return jsonify({"message": "Invalid path. Must start with 'Root/'.", "success": False})

    if path == "Root/":
        target_category = None
    else:
        parts = path.split('/')[1:]
        current = None

        for part in parts:
            found = Category.query.filter_by(name=part, parent_id=current.id if current else None).first()
            if not found:
                return jsonify({"message": f"Path not found: {path}", "success": False})
            current = found

        target_category = current

    if type_ == 'category':
        category = Category.query.filter_by(id=id_).first()
        if not category:
            return jsonify({"message": "Category not found.", "success": False})
        if category.id == (target_category.id if target_category else None):
            return jsonify({"message": "Cannot move category into itself.", "success": False})

        category.parent_id = target_category.id if target_category else None

    elif type_ == 'item':
        item = Item.query.filter_by(uid=id_).first()
        if not item:
            return jsonify({"message": "Item not found.", "success": False})
        item.category_id = target_category.id if target_category else None

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
            return jsonify({"message": "Item not found"})
    elif type_ == 'category':
        cat = Category.query.filter_by(id=id_).first()
        if cat:
            if category_has_items(cat):
                return jsonify({"message": "Cannot delete category: it contains files."})
            def delete_cat(c):
                for child in c.children:
                    delete_cat(child)
                db.session.delete(c)
            delete_cat(cat)
            db.session.commit()
            return jsonify({"message": "Category deleted", "success": True})
        else:
            return jsonify({"message": "Category not found"})
    return jsonify({"message": "Invalid type"})

@app.route('/api/item/<uid>', methods=['GET', 'POST'])
def item_api(uid):
    item = Item.query.filter_by(uid=uid).first()
    if request.method == 'GET':
        if item:
            return jsonify({
                "uid": item.uid,
                "name": item.name,
                "count": item.count,
                "tags": item.tags,
                "timestamp": item.timestamp,
                "category_id": item.category_id
            })
        else:
            return jsonify({"message": "Item not found"}), 404
    else:
        data = request.form
        item.name = data.get('name')
        item.count = int(data.get('count'))
        item.tags = data.get('tags')
        item.timestamp = int(time.time())
        db.session.commit()
        return jsonify({"message": "Item updated"})

# --------------------- Tags API ---------------------
TAGS_FILE = 'tags.json'
def load_tags():
    if not os.path.exists(TAGS_FILE):
        with open(TAGS_FILE, 'w') as f:
            json.dump([], f)
    with open(TAGS_FILE, 'r') as f:
        return json.load(f)
def save_tags(tags):
    with open(TAGS_FILE, 'w') as f:
        json.dump(tags, f)
@app.route('/api/tags', methods=['GET', 'POST'])
def tags_api():
    if request.method == 'GET':
        return jsonify(load_tags())
    else:
        tag = request.form.get('tag')
        tags = load_tags()
        if tag not in tags:
            tags.append(tag)
            save_tags(tags)
        return jsonify({"message": "Tag added", "tags": tags})

# --------------------- Export ---------------------
@app.route('/export')
def export():
    data = {}
    cats = Category.query.all()
    its = Item.query.all()
    data['categories'] = [{"id": c.id, "name": c.name, "parent_id": c.parent_id} for c in cats]
    data['items'] = [{"uid": i.uid, "name": i.name, "count": i.count, "tags": i.tags, "timestamp": i.timestamp, "category_id": i.category_id} for i in its]
    return app.response_class(
        response=json.dumps(data, indent=4),
        mimetype='application/json'
    )

# --------------------- Item Editor ---------------------
@app.route('/edit/<uid>')
def edit(uid):
    item = Item.query.filter_by(uid=uid).first()
    if not item:
        return "Item not found", 404
    tags = load_tags()
    parent_cat = request.args.get('cat', '')
    return render_template_string("""
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Edit Item</title>
    <style>
        body { background-color: #2c2c2c; color: #f0f0f0; font-family: Arial, sans-serif; padding: 20px; }
        .editor { max-width: 600px; margin: auto; }
        input { width: 100%; padding: 10px; margin-bottom: 10px; background-color: #444; border: 1px solid #666; color: #f0f0f0; }
        .buttons { position: fixed; bottom: 20px; right: 20px; }
        .buttons button { margin-left: 5px; padding: 10px 20px; }
        .cancel { background: #fff; color: #888; border: 1px solid #888; }
        .save { background: #007bff; color: #fff; border: none; }
    </style>
    <script src="https://code.jquery.com/jquery-3.6.0.min.js"></script>
</head>
<body>
    <div class="editor">
        <h2>Edit Item: {{ item.name }}</h2>
        <input type="hidden" id="serverTimestamp" value="{{ item.timestamp }}">
        <label>Name:</label>
        <input type="text" id="name" value="{{ item.name }}">
        <label>Count:</label>
        <input type="number" id="count" value="{{ item.count }}">
        <label>Tags (comma separated):</label>
        <input type="text" id="tags" value="{{ item.tags }}">
    </div>
    <div class="buttons">
        <button class="cancel" onclick="cancelEdit()">Cancel</button>
        <button class="save" onclick="saveItem()">Save</button>
        <button class="save" onclick="saveAndExit()">Save & Exit</button>
    </div>
<script>
    const uid = "{{ item.uid }}";
    const autosaveKey = "autosave_" + uid;
    const parentCat = "{{ parent_cat }}";
    $(document).ready(function(){
        let autosaveData = localStorage.getItem(autosaveKey);
        if(autosaveData) {
            let data = JSON.parse(autosaveData);
            let serverTs = parseInt($("#serverTimestamp").val());
            if(data.timestamp > serverTs) {
                if(confirm("Found a local autosave for this file that has not been pushed. Restore it?")) {
                    $("#name").val(data.name);
                    $("#count").val(data.count);
                    $("#tags").val(data.tags);
                } else {
                    localStorage.removeItem(autosaveKey);
                }
            }
        }
    });
    function autosave() {
        let data = {
            name: $("#name").val(),
            count: $("#count").val(),
            tags: $("#tags").val(),
            timestamp: Date.now()
        };
        localStorage.setItem(autosaveKey, JSON.stringify(data));
    }
    setInterval(autosave, 15000);
    $("input").on("blur", autosave);
    $("#count").on("keydown", function(e){
        let val = parseInt($(this).val());
        if(isNaN(val)) val = 0;
        if(e.key === "ArrowUp") { $(this).val(val+1); e.preventDefault(); }
        else if(e.key === "ArrowDown") { $(this).val(val-1); e.preventDefault(); }
    });
    function saveItem(callback) {
    $.post("/api/item/" + uid, {
        name: $("#name").val(),
        count: $("#count").val(),
        tags: $("#tags").val()
    }, function (data) {
        // If the API returns a "success": false property, show its message.
        if (data.success === false) {
            alert(data.message);
        }
        localStorage.removeItem(autosaveKey);
        if (callback) callback();
    });
    }

    function saveAndExit() { saveItem(function(){ window.location.href = "/?cat=" + parentCat; }); }
    function cancelEdit() { localStorage.removeItem(autosaveKey); window.location.href = "/?cat=" + parentCat; }
</script>
</body>
</html>
    """, item=item, tags=tags, parent_cat=parent_cat)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
