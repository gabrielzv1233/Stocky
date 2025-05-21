from flask import Flask, request, jsonify, render_template_string, send_file
import logging, time, json, random, re, uuid, os, base64, qrcode, gspread
from google.oauth2.service_account import Credentials
from googleapiclient.http import MediaIoBaseUpload
from googleapiclient.discovery import build
from sympy import sympify
from io import BytesIO
from math import ceil
from PIL import Image

# load .env files, used for development
for root, _, files in os.walk("."):
    for file in files:
        if file.endswith(".env"):
            print(f"Loading environment variables from {file}")
            full_path = os.path.join(root, file)
            with open(full_path) as f:
                for line in f:
                    if line.strip() and not line.startswith("#"):
                        key, _, value = line.strip().partition("=")
                        if value.startswith('"') and value.endswith('"'):
                            value = value[1:-1]
                        os.environ[key] = value

creds_data = base64.b64decode(os.environ['GOOGLE_CREDS']).decode() # Download creds JSON from Google Cloud Console and base64 encode it

# Leave anything below this line alone unless you know what you're doing

def extract_google_id(url: str) -> str:
    match = re.search(r'/folders/([a-zA-Z0-9_-]+)', url) or \
            re.search(r'/d/([a-zA-Z0-9_-]+)', url)
    if not match:
        raise ValueError(f"Could not extract ID from: {url}")
    return match.group(1)

SPREADSHEET_ID   = extract_google_id(os.environ['GOOGLE_SHEET_URL'])
IMAGE_FOLDER_ID  = extract_google_id(os.environ['GOOGLE_FOLDER_URL'])
CATEGORIES_SHEET = 'categories'
ITEMS_SHEET      = 'items'
SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive'
]

for folder in ["static/uploads", "static/qr"]:
    os.makedirs(folder, exist_ok=True)
    for f in os.listdir(folder):
        fp = os.path.join(folder, f)
        if os.path.isfile(fp):
            os.remove(fp)


logging.basicConfig(level=logging.DEBUG, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)
creds_json = json.loads(creds_data)
creds = Credentials.from_service_account_info(creds_json, scopes=SCOPES)
gc     = gspread.authorize(creds)
sheet  = gc.open_by_key(SPREADSHEET_ID)
drive  = build('drive', 'v3', credentials=creds)

def clear_blank_rows(worksheet):
    all_values = worksheet.get_all_values()
    for i in range(len(all_values), 0, -1):
        row = all_values[i - 1]
        if not any(cell.strip() for cell in row):
            worksheet.delete_rows(i)
            
def repair_items_parent_id():
    ws_items = sheet.worksheet(ITEMS_SHEET)
    all_values = ws_items.get_all_values()
    for i in range(2, len(all_values) + 1):
        row = all_values[i - 1]
        if len(row) >= 5:
            cat_id = row[4].strip()
            if not cat_id.isdigit():
                ws_items.update_cell(i, 5, '0')

def repair_categories_parent_id():
    ws_cats = sheet.worksheet(CATEGORIES_SHEET)
    all_values = ws_cats.get_all_values()
    for i in range(2, len(all_values) + 1):
        row = all_values[i - 1]
        if len(row) >= 3:
            parent_id = row[2].strip()
            if parent_id and not parent_id.isdigit():
                ws_cats.update_cell(i, 3, '')

def get_or_create_ws(title, headers):
    try:
        ws = sheet.worksheet(title)
        logger.debug(f"Found worksheet '{title}'")
    except gspread.WorksheetNotFound:
        ws = sheet.add_worksheet(title=title, rows='1000', cols=str(len(headers)))
        ws.append_row(headers)
        logger.debug(f"Created worksheet '{title}'")
    return ws

ws_cats = get_or_create_ws(CATEGORIES_SHEET, ['id','name','parent_id'])
ws_items = get_or_create_ws(ITEMS_SHEET,     ['uid','name','count','timestamp','category_id','image_paths'])

def read_categories():
    data = ws_cats.get_all_records()
    data = [r for r in data if any(str(cell).strip() for cell in r.values())]
    return [{
        'id':        int(r['id']),
        'name':      r['name'],
        'parent_id': int(r['parent_id']) if r['parent_id'] not in ('', None) else None
    } for r in data]

def read_items():
    raw = sheet.worksheet("items").get_all_records()
    rows = [r for r in raw if any(str(cell).strip() for cell in r.values())]
    return [{
        'uid':         str(r['uid']),
        'name':        r['name'],
        'count':       int(r['count']) if str(r['count']).strip() else 0,
        'timestamp':   int(r['timestamp']) if str(r['timestamp']).strip() else 0,
        'category_id': int(r['category_id']) if str(r['category_id']).strip() else 0,
        'image_paths': json.loads(r['image_paths']) if r['image_paths'] else []
    } for r in rows]

def find_cat_row(cid):  cell = ws_cats.find(str(cid), in_column=1);  return cell.row if cell else None
def find_item_row(uid): cell = ws_items.find(str(uid), in_column=1); return cell.row if cell else None

def append_category(name, parent_id):
    new_id = max([c['id'] for c in read_categories()] or [0]) + 1
    ws_cats.append_row([new_id, name, parent_id or '']); return new_id

def append_item(name, category_id):
    uid = ''.join(str(random.randint(0,9)) for _ in range(10))
    ws_items.append_row([uid, name, 0, int(time.time()), category_id or '', ''])
    return uid

def update_item_row(uid, name, count):
    row = find_item_row(uid); ts=int(time.time())
    ws_items.update(f'B{row}:D{row}', [[name, count, ts]])

def duplicate_exists(target_cat_id, name, is_category, exclude=None):
    name_l = name.lower()
    if is_category:
        for c in read_categories():
            if c['parent_id']==target_cat_id and c['name'].lower()==name_l and c['id']!=exclude:
                return True
    else:
        for i in read_items():
            if i['category_id']==target_cat_id and i['name'].lower()==name_l and i['uid']!=exclude:
                return True
    return False

def breadcrumb_parts(cat_id, cats):
    out=[]
    cur=cat_id
    while cur:
        c=next((x for x in cats if x['id']==cur),None)
        if not c: break
        out.append(c['name']); cur=c['parent_id']
    return list(reversed(out))

def build_breadcrumb_str(cat_id,cats): return '/' + '/'.join(breadcrumb_parts(cat_id,cats)) if cat_id else '/'
def build_breadcrumb_html(cat_id,cats): return '<b>/</b>' + '<b> / </b>'.join(breadcrumb_parts(cat_id,cats)) if cat_id else '<b>/</b>'

app = Flask(__name__)

@app.route("/api/qr/<b64url>")
def gen_qr(b64url):
    safe_name = "".join(c for c in b64url if c.isalnum() or c in ('-', '_'))
    filepath = os.path.join("static/qr", f"{safe_name}.png")

    if not os.path.exists(filepath):
        try:
            padded = b64url + '=' * (-len(b64url) % 4)
            url = base64.urlsafe_b64decode(padded).decode()
            qrcode.make(url).save(filepath)
        except Exception:
            return "Invalid base64 input", 400

    return send_file(filepath, mimetype="image/png")

@app.route('/repair')
def repair():
    clear_blank_rows(sheet.worksheet("items"))
    clear_blank_rows(sheet.worksheet("categories"))
    repair_categories_parent_id()
    repair_items_parent_id()
    return """
    <script>
        alert("Repaired empty rows and parent IDs (if needed).");
        window.location.href = "/";
    </script>
    """

@app.route('/')
def explorer():
    cid = request.args.get('cat', type=int)
    cats, items = read_categories(), read_items()

    if cid is not None:
        subcats   = [c for c in cats if c['parent_id'] == cid]
        its       = [i for i in items if i['category_id'] == cid]
        bc_html   = build_breadcrumb_html(cid, cats)
        parent_id = next((c['parent_id'] for c in cats if c['id'] == cid), None)
        parentPath= build_breadcrumb_str(parent_id, cats) if parent_id is not None else '/'
    else:
        subcats   = [c for c in cats if c['parent_id'] is None]
        its       = [i for i in items if i['category_id'] == 0 or i['category_id'] is None]
        bc_html, parent_id, parentPath = '<b>/</b>', None, None

    return render_template_string(EXPLORER_HTML,
        category={'id': cid, 'parent_id': parent_id},
        subcategories=subcats, items=its,
        breadcrumb=bc_html, parentPath=parentPath,
        build_breadcrumb_str=build_breadcrumb_str,
        read_categories=read_categories)

@app.route('/api/items_index')
def items_index():
    cats, items = read_categories(), read_items()
    idx=[]
    for c in cats:
        idx.append({'type':'category','id':c['id'],'name':c['name'].lower(),
                    'count':0,'path':build_breadcrumb_str(c['id'],cats)+'/'})
    for i in items:
        idx.append({'type':'item','uid':i['uid'],'name':i['name'].lower(),
                    'count':i['count'],
                    'path':build_breadcrumb_str(i['category_id'],cats)+i['name']})
    return jsonify(idx)

@app.route('/api/get_path')
def get_path():
    t = request.args.get('type'); id_=request.args.get('id')
    cats,items = read_categories(), read_items()
    if t=='category':
        c = next((x for x in cats if str(x['id'])==id_),None)
        if not c: return jsonify(success=False,message='Category not found')
        return jsonify(success=True,path=build_breadcrumb_str(c['id'],cats))
    if t=='item':
        i = next((x for x in items if x['uid']==id_),None)
        if not i: return jsonify(success=False,message='Item not found')
        return jsonify(success=True,path=build_breadcrumb_str(i['category_id'],cats))
    return jsonify(success=False,message='Invalid type')

@app.route('/api/new_category',methods=['POST'])
def new_category():
    name = request.form['name'].strip()
    if not re.fullmatch(r'[A-Za-z0-9 _\-,.]+',name): return jsonify(success=False,message='Invalid')
    parent_id = request.form.get('parent_id'); parent_id=int(parent_id) if parent_id else None
    if duplicate_exists(parent_id,name,True):   return jsonify(success=False,message='Duplicate')
    cid=append_category(name,parent_id)
    return jsonify(success=True,id=cid,message='Created')

@app.route('/api/new_item',methods=['POST'])
def new_item():
    name = request.form['name'].strip()
    if not re.fullmatch(r'[A-Za-z0-9 _\-,.]+',name): return jsonify(success=False,message='Invalid')
    category_id = request.form.get('category_id'); category_id=int(category_id) if category_id else None
    if duplicate_exists(category_id,name,False): return jsonify(success=False,message='Duplicate')
    uid = append_item(name,category_id)
    return jsonify(success=True,uid=uid,message='Created')

def resolve_target_category(abs_path,cats):
    if abs_path=='/': return None
    parts = [p for p in abs_path.strip('/').split('/') if p]
    cur=None
    for p in parts:
        cur=next((c for c in cats if c['name'].lower()==p.lower() and c['parent_id']==(cur['id'] if cur else None)),None)
        if not cur: return None
    return cur

@app.route('/api/move',methods=['POST'])
def move():
    t,id_,path = request.form['type'], request.form['id'], request.form['path'].strip()
    if not path.startswith('/'): return jsonify(success=False,message='Path must start with /')
    cats,items=read_categories(),read_items()
    target_cat = resolve_target_category(path,cats)
    target_id = target_cat['id'] if target_cat else None

    if t=='category':
        cat = next((c for c in cats if str(c['id'])==id_),None)
        if not cat: return jsonify(success=False,message='Cat not found')

        anc=target_cat
        while anc:
            if anc['id']==cat['id']: return jsonify(success=False,message='Cannot move into itself')
            anc = next((c for c in cats if c['id']==anc['parent_id']),None)
        if duplicate_exists(target_id,cat['name'],True,exclude=cat['id']):
            return jsonify(success=False,message='Name exists in target')
        row=find_cat_row(cat['id']); ws_cats.update_cell(row,3,target_id or '')
        return jsonify(success=True,message='Moved')

    if t=='item':
        it = next((i for i in items if i['uid']==id_),None)
        if not it: return jsonify(success=False,message='Item not found')
        if duplicate_exists(target_id,it['name'],False,exclude=it['uid']):
            return jsonify(success=False,message='Name exists in target')
        row=find_item_row(it['uid']); ws_items.update_cell(row,5,target_id or '')
        return jsonify(success=True,message='Moved')

    return jsonify(success=False,message='Invalid type')

@app.route('/api/delete',methods=['POST'])
def delete():
    t,id_ = request.form['type'],request.form['id']
    if t=='item':
        row=find_item_row(id_); ws_items.batch_clear([f"A{row}:F{row}"])
        return jsonify(success=True,message='Item deleted')
    if t=='category':
        cats = read_categories()
        if any(i for i in read_items() if i['category_id']==int(id_)):
            return jsonify(success=False,message='Not empty')

        to_delete=[int(id_)]
        while True:
            extra = [c['id'] for c in cats if c['parent_id'] in to_delete]
            if not extra: break
            to_delete.extend(extra)
        for cid in to_delete:
            row=find_cat_row(cid); ws_cats.batch_clear([f"A{row}:C{row}"])
        return jsonify(success=True,message='Category deleted')
    return jsonify(success=False,message='Invalid type')

UPLOAD_DIR = os.path.join(app.root_path, 'static', 'uploads')
os.makedirs(UPLOAD_DIR, exist_ok=True)

@app.route('/api/upload_image/<uid>', methods=['POST'])
def upload_image(uid):
    if 'file' not in request.files:
        return jsonify(success=False, message='No file')

    f = request.files['file']
    raw = f.read()
    stream = BytesIO(raw)

    meta = {
        'name': f"{uid}_{uuid.uuid4().hex}",
        'parents': [IMAGE_FOLDER_ID]
    }
    media = MediaIoBaseUpload(stream,
                              mimetype=f.mimetype or 'application/octet-stream',
                              resumable=False)

    fid = drive.files().create(
        body=meta,
        media_body=media,
        fields='id',
        supportsAllDrives=True
    ).execute()['id']

    drive.permissions().create(
        fileId=fid,
        body={'role': 'reader', 'type': 'anyone'},
        supportsAllDrives=True
    ).execute()

    full_url = f"https://drive.usercontent.google.com/download?id={fid}&authuser=0"

    img = Image.open(BytesIO(raw)).convert("RGBA")
    thumb = img.resize((128, 128), Image.Resampling.LANCZOS)
    thumb_name = f"{uid}_{uuid.uuid4().hex}_thumb.webp"
    thumb_path = os.path.join(UPLOAD_DIR, thumb_name)
    thumb.save(thumb_path, "WEBP")
    thumb_url = f"/static/uploads/{thumb_name}"

    row = find_item_row(uid)
    items = read_items()
    imgs = next(i['image_paths'] for i in items if i['uid'] == uid)
    imgs.append({"thumb": thumb_url, "full": full_url, "fid": fid})
    ws_items.update_cell(row, 6, json.dumps(imgs))

    return jsonify(success=True, image_path=thumb_url, full_path=full_url)


@app.route('/api/delete_image/<uid>', methods=['POST'])
def delete_image(uid):
    thumb = request.form.get('thumb')
    if not thumb:
        return jsonify(success=False, message='No thumb')
    
    row = find_item_row(uid)
    items = read_items()
    item = next(i for i in items if i['uid'] == uid)
    entry = next((e for e in item['image_paths'] if isinstance(e, dict) and e.get("thumb") == thumb), None)
    if not entry:
        return jsonify(success=False, message='Not found')

    try:
        drive.files().delete(fileId=entry.get("fid")).execute()
    except Exception:
        pass

    local = os.path.join(app.root_path, thumb.lstrip('/'))
    if os.path.exists(local):
        os.remove(local)

    item['image_paths'].remove(entry)
    ws_items.update_cell(row, 6, json.dumps(item['image_paths']))

    return jsonify(success=True, message='Deleted')

@app.route('/edit/<uid>')
def edit(uid):
    items, cats = read_items(), read_categories()
    item = next((i for i in items if i['uid']==uid),None)
    if not item: return "Item not found",404
    parent = request.args.get('cat','')
    breadcrumb=build_breadcrumb_html(item['category_id'],cats) if item['category_id'] else '<b>/</b>'
    return render_template_string(EDITOR_HTML,item=item,images=item['image_paths'],
                                  breadcrumb=breadcrumb,parent=parent)

@app.route('/api/item/<uid>',methods=['POST'])
def item_api(uid):
    name = request.form['name'].strip()
    count_raw = request.form['count']
    if not re.fullmatch(r'[A-Za-z0-9 _\-,.]+',name): return jsonify(success=False,message='Invalid')
    if not re.fullmatch(r'[0-9+\-*/(). ]*',count_raw): return jsonify(success=False,message='Invalid count')
    count=int(ceil(sympify(re.sub(r'[^0-9+\-*/(). ]','',count_raw) or '0').evalf()))
    update_item_row(uid,name,count)
    return jsonify(success=True)

@app.route('/export')
def export(): return jsonify(categories=read_categories(),items=read_items())

@app.route('/view_image/<path:filename>')
def view_image(filename):

    p=os.path.join(app.root_path,'static','uploads',filename)
    return send_file(p,mimetype='image/webp',as_attachment=False) if os.path.exists(p) else ('Not found',404)

EXPLORER_HTML = """
<!DOCTYPE html><html><head><meta charset="utf-8"><title>Stocky</title>
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<style>
body{background:#2c2c2c;color:#f0f0f0;font-family:Arial,sans-serif;margin:0}
.explorer{padding:20px}.header{display:flex;flex-direction:column;gap:5px}
.breadcrumb{padding-bottom:10px;font-size:14px}
.controls{display:flex;justify-content:space-between;align-items:center}
.buttons button{padding:5px 10px;margin-right:3px;background:#fff;color:#000;border:1.5px solid #000;border-radius:7px;cursor:pointer}
.list{margin-top:20px}.folder,.item{padding:10px;border:1px solid #444;margin-bottom:5px;cursor:pointer}
.folder:hover,.item:hover{background:#444}.selected{border:2px solid #007bff}
.back-folder{background:#333}.empty-message{color:#888;font-size:14px;padding-bottom:20px}
</style><script src="https://code.jquery.com/jquery-3.6.0.min.js"></script></head>
<body><div class="explorer">
<div class="header"><span class="breadcrumb">{{breadcrumb|safe}}</span>
<div class="controls"><div class="buttons">
<button onclick="newSubCategory()">New Sub Category</button>
<button onclick="newItem()">New Item</button>
<button onclick="deleteSelected()">Delete</button>
</div></div></div>
<div class="list">
{% if category.id %}
  <div class="folder back-folder" ondblclick="goBack()">⬅️ ...</div>
{% endif %}
{% for cat in subcategories %}
  <div class="folder" data-id="{{cat.id}}" onclick="selectItem(this,'category','{{cat.id}}')" ondblclick="openFolder({{cat.id}})">
    📁 {{cat.name}}
  </div>
{% endfor %}
{% for item in items %}
  <div class="item" data-uid="{{item.uid}}" onclick="selectItem(this,'item','{{item.uid}}')" ondblclick="openItem('{{item.uid}}')">
    📄 {{item.name}} ({{item.count}})
  </div>
{% endfor %}
{% if not subcategories and not items %}
  <div class="empty-message">📂 This folder is empty.</div>
{% endif %}
</div></div>
<script>
let selected=null;
function selectItem(el,t,id){document.querySelectorAll('.selected').forEach(x=>x.classList.remove('selected'));el.classList.add('selected');selected={type:t,id:id}}
function goBack(){const pid='{{category.parent_id if category.id else ""}}';location.href=pid?"/?cat="+pid:"/"}
function openFolder(id){location.href="/?cat="+id}
function openItem(uid){const p=new URLSearchParams(location.search);const c=p.get('cat');location.href="/edit/"+uid+(c?"?cat="+c:"")}
function newSubCategory(){const name=prompt("Enter sub category name:");if(!name)return;$.post("/api/new_category",{name,parent_id:'{{category.id if category.id else ""}}'}).done(d=>d.success?location.reload():alert(d.message))}
function newItem(){const name=prompt("Enter item name:");if(!name)return;$.post("/api/new_item",{name,category_id:'{{category.id if category.id else ""}}'}).done(d=>d.success?location.reload():alert(d.message))}
function deleteSelected(){if(!selected)return alert("Select something first.");if(!confirm("Delete "+selected.type+"?"))return;$.post("/api/delete",selected).done(d=>d.success?location.reload():alert(d.message))}
</script></body></html>
"""

EDITOR_HTML = """
<!DOCTYPE html><html><head><meta charset='utf-8'><title>Stocky – Edit</title>
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<style>
body{background:#2c2c2c;color:#f0f0f0;font-family:Arial,sans-serif;padding:20px}
.editor{max-width:600px;margin:auto}
input{width:100%;padding:10px;margin-bottom:10px;background:#444;border:1px solid #666;color:#f0f0f0}
.buttons{position:fixed;bottom:20px;right:20px}.buttons button{margin-left:5px;padding:10px 20px}
.cancel{background:#fff;color:#888;border:1px solid #888}.save{background:#007bff;color:#fff;border:none}
.spancopy{cursor:pointer;font-family:monospace;background:#424242;color:#E7E7E7;padding:2px 5px;border-radius:4px}
#imageUploadContainer,#imageContainer{display:flex;flex-wrap:wrap;gap:10px}
#uploadWrapper{width:128px;height:128px;cursor:pointer}#uploadWrapper img{width:100%;height:100%}
.uploaded-img{width:128px;height:128px;object-fit:cover;cursor:pointer}
</style><script src='https://code.jquery.com/jquery-3.6.0.min.js'></script></head>
<body>
<div class='editor'>
<h2>Editing item <code title="Generate QR code for this item" class='spancopy' onclick='genQR()'>{{ item.uid }}</code>:</h2>
<label>Name:<input type='text' id='name' value='{{ item.name }}'></label>
<label>Count:<input pattern='[0-9+\\-*/(). ]*' type='text' id='count' value='{{ item.count }}'></label>
<div id='imageUploadContainer'>
  <div id='uploadWrapper'>
    <img id='uploadBtn' src='/static/upload_button.png'><input id='imageInput' type='file' accept='image/*' style='display:none'>
  </div>
  <div id='imageContainer'>
    {% for url in images %}
      {% if url is mapping %}
        <img class='uploaded-img' src='{{ url.thumb }}' data-full='{{ url.full }}'>
      {% else %}
        <img class='uploaded-img' src='{{ url }}' data-full='{{ url }}'>
      {% endif %}
    {% endfor %}
  </div>
</div>
</div>
<div class='buttons'><button class='cancel' onclick='cancel()'>Cancel</button><button class='save' onclick='save()'>Save & Exit</button></div>
<script>
const uid    = "{{ item.uid }}";
const parent = "{{ parent }}";
const $btnImg = $("#uploadBtn");
const UP_ICON    = "/static/upload_button.png";
const LOADING_GIF= "/static/loading.gif";

function genQR() {
    const url = window.location.href;
    const encoded = btoa(url)
        .replace(/\+/g, '-')
        .replace(/\//g, '_')
        .replace(/=+$/, '');
    window.open('/api/qr/' + encoded, '_blank');
}

function copyid(e){
  const s=e.target, t=s.textContent;
  navigator.clipboard.writeText(t).then(()=>{
    s.textContent="Copied!"; setTimeout(()=>s.textContent=t,1e3);
  });
}

function toggleUploadButton(){
  $("#uploadWrapper").toggle($("#imageContainer img").length < 3);
}
toggleUploadButton();

function save(){
  $.post("/api/item/"+uid,{name:$("#name").val(),count:$("#count").val()})
    .done(d=> d.success ? location.href="/?cat="+parent : alert(d.message));
}
function cancel(){ location.href="/?cat="+parent }

function spinner(on){
  $btnImg.attr("src", on ? LOADING_GIF : UP_ICON);
  $("#uploadWrapper").css("pointer-events", on ? "none" : "auto");
}
spinner(true);
$(window).on("load", ()=> spinner(false));

$("#uploadBtn").click(()=> $("#imageInput").click());
$("#imageInput").on("change", e=>{
  const f=e.target.files[0]; if(!f) return;
  const fd=new FormData(); fd.append("file",f);

  spinner(true);
  $.ajax({
    url:`/api/upload_image/${uid}`,
    type:"POST",
    data:fd,
    processData:false,
    contentType:false
  }).done(d=>{
    spinner(false);
    if(d.success){
      $("#imageContainer").append(
        `<img class="uploaded-img" src="${d.image_path}" data-full="${d.full_path}">`
      );
      toggleUploadButton();
      $("#imageInput").val("");
    } else alert(d.message);
  }).fail(()=> spinner(false));
});

$(document).on("click", ".uploaded-img", function(){
  const img=this;

  if(img.__timer){
    clearTimeout(img.__timer); img.__timer=null;

    if(confirm("Delete this image?")){
      spinner(true);
      const rel = img.src.startsWith(location.origin)
                 ? img.src.slice(location.origin.length) : img.src;

      $.post(`/api/delete_image/${uid}`, { thumb: rel })
        .done(d=>{
          spinner(false);
          if(d.success){ $(img).remove(); toggleUploadButton(); }
          else alert(d.message);
        }).fail(()=> spinner(false));
    }
  }else{
    img.__timer=setTimeout(()=>{
      img.__timer=null;
      window.open($(img).data("full"), "_blank");
    },300);
  }
});
</script>
</body></html>
"""

if __name__=='__main__':
    app.run(host='0.0.0.0',port=80,debug=False)
