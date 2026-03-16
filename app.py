from flask import (Flask, render_template, request, redirect, url_for,
                   flash, session, jsonify, send_file, make_response)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from datetime import datetime, timedelta
from functools import wraps
import sqlite3, os, json, io, csv

app = Flask(__name__)
app.secret_key = "farmerspulse-secret-2025"

DATABASE = "database/farmerspulse.db"
UPLOAD_FOLDER = "static/uploads"
ALLOWED_EXTENSIONS = {'png','jpg','jpeg','gif','webp'}

def get_db():
    if not os.path.exists("database"):
        os.makedirs("database")
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()
    c.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        email TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        role TEXT DEFAULT 'farmer',
        full_name TEXT DEFAULT '',
        phone TEXT DEFAULT '',
        county TEXT DEFAULT '',
        crop_types TEXT DEFAULT '',
        farm_size TEXT DEFAULT '',
        bio TEXT DEFAULT '',
        profile_pic TEXT DEFAULT '',
        is_active INTEGER DEFAULT 1,
        is_banned INTEGER DEFAULT 0,
        ban_reason TEXT DEFAULT '',
        created_at TEXT DEFAULT (datetime('now')),
        last_login TEXT
    );
    CREATE TABLE IF NOT EXISTS posts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        short_text TEXT NOT NULL,
        full_text TEXT DEFAULT '',
        image_url TEXT DEFAULT '',
        category TEXT DEFAULT 'advisory',
        tags TEXT DEFAULT '',
        target_crops TEXT DEFAULT '',
        target_counties TEXT DEFAULT '',
        source TEXT DEFAULT 'manual',
        is_published INTEGER DEFAULT 1,
        is_pinned INTEGER DEFAULT 0,
        user_id INTEGER NOT NULL,
        created_at TEXT DEFAULT (datetime('now')),
        updated_at TEXT DEFAULT (datetime('now'))
    );
    CREATE TABLE IF NOT EXISTS comments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        content TEXT NOT NULL,
        post_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        parent_id INTEGER,
        is_flagged INTEGER DEFAULT 0,
        flag_reason TEXT DEFAULT '',
        created_at TEXT DEFAULT (datetime('now'))
    );
    CREATE TABLE IF NOT EXISTS likes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        post_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        is_like INTEGER DEFAULT 1,
        created_at TEXT DEFAULT (datetime('now')),
        UNIQUE(post_id, user_id)
    );
    CREATE TABLE IF NOT EXISTS saved_posts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        post_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        created_at TEXT DEFAULT (datetime('now')),
        UNIQUE(post_id, user_id)
    );
    CREATE TABLE IF NOT EXISTS follows (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        follower_id INTEGER NOT NULL,
        followed_id INTEGER NOT NULL,
        created_at TEXT DEFAULT (datetime('now')),
        UNIQUE(follower_id, followed_id)
    );
    CREATE TABLE IF NOT EXISTS notifications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        content TEXT NOT NULL,
        notif_type TEXT DEFAULT 'system',
        is_read INTEGER DEFAULT 0,
        link TEXT DEFAULT '',
        created_at TEXT DEFAULT (datetime('now'))
    );
    CREATE TABLE IF NOT EXISTS ai_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        endpoint TEXT,
        payload TEXT,
        response_status TEXT,
        post_id INTEGER,
        created_at TEXT DEFAULT (datetime('now'))
    );
    CREATE TABLE IF NOT EXISTS feedback (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        name TEXT NOT NULL,
        email TEXT NOT NULL,
        subject TEXT NOT NULL,
        message TEXT NOT NULL,
        category TEXT DEFAULT 'general',
        status TEXT DEFAULT 'unread',
        admin_reply TEXT DEFAULT '',
        created_at TEXT DEFAULT (datetime('now'))
    );
    CREATE TABLE IF NOT EXISTS ai_personalization_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        request_payload TEXT,
        response_payload TEXT,
        post_ids_returned TEXT,
        response_time_ms INTEGER,
        created_at TEXT DEFAULT (datetime('now'))
    );
    """)
    conn.commit()
    admin = conn.execute("SELECT id FROM users WHERE username='admin'").fetchone()
    if not admin:
        pw = generate_password_hash("admin123")
        conn.execute("INSERT INTO users (username,email,password,role,full_name,county) VALUES (?,?,?,?,?,?)",
                     ("admin","admin@farmerspulse.com",pw,"admin","FarmersPulse Admin","Narok"))
        conn.commit()
    if conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0] == 0:
        aid = conn.execute("SELECT id FROM users WHERE role='admin'").fetchone()["id"]
        samples = [
            ("Maize Advisory: Nitrogen Fertilizer","Apply nitrogen fertilizer during early growth stage to improve yield.",
             "Monitor soil moisture, avoid over-fertilization, apply potassium if needed. Recommended: 50kg CAN per acre at knee height.",
             "https://picsum.photos/600/400?random=1","advisory","maize,fertilizer","Maize","","manual",1,1),
            ("Market Price Alert: Maize Up 8%","Maize prices have increased by 8% in Narok County this week.",
             "Current price: Ksh 4,200 per 90kg bag. Consider timing your sales strategically.",
             "https://picsum.photos/600/400?random=2","market","maize,prices","Maize","Narok","manual",1,0),
            ("Weather Forecast: Moderate Rainfall","Moderate rainfall expected over the next three days across Rift Valley.",
             "Prepare drainage systems to prevent waterlogging. Monitor local weather for changes.",
             "https://picsum.photos/600/400?random=3","weather","rain","","","manual",1,0),
            ("Fall Armyworm Alert – Take Action","Fall armyworm infestation reported in Trans Nzoia. Scout your fields.",
             "Look for egg masses in the whorl. Apply Emamectin Benzoate at first sign of damage.",
             "https://picsum.photos/600/400?random=4","pest","armyworm,maize","Maize","Trans Nzoia","ai_model",1,1),
        ]
        for s in samples:
            conn.execute("INSERT INTO posts (title,short_text,full_text,image_url,category,tags,target_crops,target_counties,source,is_published,is_pinned,user_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                         (s[0],s[1],s[2],s[3],s[4],s[5],s[6],s[7],s[8],s[9],s[10],aid))
        conn.commit()
    conn.close()

def login_required(f):
    @wraps(f)
    def dec(*a,**k):
        if "user_id" not in session: return redirect(url_for("login"))
        return f(*a,**k)
    return dec

def admin_required(f):
    @wraps(f)
    def dec(*a,**k):
        if "user_id" not in session or session.get("role")!="admin":
            flash("Admin access required.","error"); return redirect(url_for("dashboard"))
        return f(*a,**k)
    return dec

def current_user():
    if "user_id" not in session: return None
    conn=get_db(); u=conn.execute("SELECT * FROM users WHERE id=?",(session["user_id"],)).fetchone(); conn.close(); return u

def allowed_file(fn):
    return '.' in fn and fn.rsplit('.',1)[1].lower() in ALLOWED_EXTENSIONS

@app.context_processor
def inject_globals():
    u=current_user(); unread=0; pending_ai=0; unread_feedback=0
    if u:
        conn=get_db()
        unread=conn.execute("SELECT COUNT(*) FROM notifications WHERE user_id=? AND is_read=0",(u["id"],)).fetchone()[0]
        if u["role"]=="admin":
            pending_ai=conn.execute("SELECT COUNT(*) FROM posts WHERE is_published=0 AND source='ai_model'").fetchone()[0]
            unread_feedback=conn.execute("SELECT COUNT(*) FROM feedback WHERE status='unread'").fetchone()[0]
        conn.close()
    return dict(current_user=u,unread_count=unread,pending_ai_count=pending_ai,unread_feedback=unread_feedback)

# ROUTES
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/login",methods=["GET","POST"])
def login():
    if "user_id" in session:
        return redirect(url_for("admin_dashboard") if session.get("role")=="admin" else url_for("dashboard"))
    if request.method=="POST":
        ident=request.form.get("username","").strip(); pw=request.form.get("password","")
        conn=get_db(); u=conn.execute("SELECT * FROM users WHERE (username=? OR email=?) AND is_active=1",(ident,ident)).fetchone(); conn.close()
        if u and check_password_hash(u["password"],pw):
            if u["is_banned"]:
                flash(f"Account suspended: {u['ban_reason'] or 'Policy violation'}","error"); return redirect(url_for("login"))
            session["user_id"]=u["id"]; session["username"]=u["username"]; session["role"]=u["role"]
            conn=get_db(); conn.execute("UPDATE users SET last_login=datetime('now') WHERE id=?",(u["id"],)); conn.commit(); conn.close()
            return redirect(url_for("admin_dashboard") if u["role"]=="admin" else url_for("dashboard"))
        flash("Invalid credentials.","error")
    return render_template("login.html")

@app.route("/register",methods=["POST"])
def register():
    d=request.form; conn=get_db()
    if conn.execute("SELECT id FROM users WHERE username=?",(d["username"],)).fetchone():
        flash("Username taken.","error"); conn.close(); return redirect(url_for("login"))
    if conn.execute("SELECT id FROM users WHERE email=?",(d["email"],)).fetchone():
        flash("Email registered.","error"); conn.close(); return redirect(url_for("login"))
    pw=generate_password_hash(d["password"])
    conn.execute("INSERT INTO users (username,email,password,full_name,phone,county,crop_types,farm_size,role) VALUES (?,?,?,?,?,?,?,?,?)",
                 (d["username"],d["email"],pw,d.get("full_name",""),d.get("phone",""),d.get("county",""),d.get("crop_types",""),d.get("farm_size",""),"farmer"))
    uid=conn.execute("SELECT id FROM users WHERE username=?",(d["username"],)).fetchone()["id"]
    conn.execute("INSERT INTO notifications (user_id,content,notif_type,link) VALUES (?,?,?,?)",(uid,"Welcome to FarmersPulse!","system","/dashboard"))
    conn.commit(); conn.close(); flash("Account created! Sign in.","success"); return redirect(url_for("login"))

@app.route("/logout")
def logout():
    session.clear(); return redirect(url_for("index"))

@app.route("/dashboard")
@login_required
def dashboard():
    if session.get("role")=="admin": return redirect(url_for("admin_dashboard"))
    page=request.args.get("page",1,type=int); per_page=10; category=request.args.get("category",""); search=request.args.get("search",""); offset=(page-1)*per_page
    conn=get_db(); uid=session["user_id"]

    # ── AI PERSONALIZATION ──
    # Check if AI has provided a ranked list of post IDs for this user
    ai_log = conn.execute("SELECT post_ids_returned FROM ai_personalization_logs WHERE user_id=? ORDER BY created_at DESC LIMIT 1", (uid,)).fetchone()
    using_ai_feed = False

    if ai_log and not category and not search:
        # AI has ranked posts for this user — serve them in that order
        ranked_ids = json.loads(ai_log["post_ids_returned"])
        if ranked_ids:
            using_ai_feed = True
            # Build placeholders for SQL IN clause preserving order
            placeholders = ",".join("?" * len(ranked_ids))
            all_ranked = conn.execute(
                f"SELECT * FROM posts WHERE id IN ({placeholders}) AND is_published=1",
                ranked_ids).fetchall()
            # Sort in the AI-prescribed order
            id_to_post = {p["id"]: p for p in all_ranked}
            ordered = [id_to_post[i] for i in ranked_ids if i in id_to_post]
            # Pinned posts always go first even in AI feed
            pinned = [p for p in ordered if p["is_pinned"]]
            rest   = [p for p in ordered if not p["is_pinned"]]
            ordered = pinned + rest
            total = len(ordered)
            posts = ordered[offset:offset+per_page]
        else:
            using_ai_feed = False

    if not using_ai_feed:
        # Standard chronological feed (fallback or when filters applied)
        where=["is_published=1"]; params=[]
        if category: where.append("category=?"); params.append(category)
        if search: where.append("(title LIKE ? OR short_text LIKE ?)"); params.extend([f"%{search}%",f"%{search}%"])
        ws=" AND ".join(where)
        total=conn.execute(f"SELECT COUNT(*) FROM posts WHERE {ws}",params).fetchone()[0]
        posts=conn.execute(f"SELECT * FROM posts WHERE {ws} ORDER BY is_pinned DESC,created_at DESC LIMIT ? OFFSET ?",params+[per_page,offset]).fetchall()

    saved_ids=[r["post_id"] for r in conn.execute("SELECT post_id FROM saved_posts WHERE user_id=?",(uid,)).fetchall()]
    liked_map={r["post_id"]:bool(r["is_like"]) for r in conn.execute("SELECT post_id,is_like FROM likes WHERE user_id=?",(uid,)).fetchall()}
    notifs=conn.execute("SELECT * FROM notifications WHERE user_id=? ORDER BY created_at DESC LIMIT 10",(uid,)).fetchall()
    def ps(pid):
        l=conn.execute("SELECT COUNT(*) FROM likes WHERE post_id=? AND is_like=1",(pid,)).fetchone()[0]
        d=conn.execute("SELECT COUNT(*) FROM likes WHERE post_id=? AND is_like=0",(pid,)).fetchone()[0]
        c=conn.execute("SELECT COUNT(*) FROM comments WHERE post_id=? AND parent_id IS NULL",(pid,)).fetchone()[0]
        return l,d,c
    posts_data=[{"post":p,"likes":ps(p["id"])[0],"dislikes":ps(p["id"])[1],"comments":ps(p["id"])[2]} for p in posts]
    conn.close(); total_pages=(total+per_page-1)//per_page
    return render_template("dashboard.html",posts_data=posts_data,saved_ids=saved_ids,liked_map=liked_map,notifs=notifs,category=category,search=search,page=page,total_pages=total_pages,total=total,using_ai_feed=using_ai_feed)

@app.route("/post/<int:post_id>")
@login_required
def post_detail(post_id):
    conn=get_db(); post=conn.execute("SELECT * FROM posts WHERE id=?",(post_id,)).fetchone()
    if not post: conn.close(); return redirect(url_for("dashboard"))
    uid=session["user_id"]
    cr=conn.execute("SELECT c.*,u.username,u.full_name,u.profile_pic FROM comments c JOIN users u ON c.user_id=u.id WHERE c.post_id=? AND c.parent_id IS NULL ORDER BY c.created_at DESC",(post_id,)).fetchall()
    comments=[{"comment":c,"replies":conn.execute("SELECT c.*,u.username,u.full_name,u.profile_pic FROM comments c JOIN users u ON c.user_id=u.id WHERE c.parent_id=? ORDER BY c.created_at",(c["id"],)).fetchall()} for c in cr]
    saved_ids=[r["post_id"] for r in conn.execute("SELECT post_id FROM saved_posts WHERE user_id=?",(uid,)).fetchall()]
    liked_map={r["post_id"]:bool(r["is_like"]) for r in conn.execute("SELECT post_id,is_like FROM likes WHERE user_id=?",(uid,)).fetchall()}
    likes=conn.execute("SELECT COUNT(*) FROM likes WHERE post_id=? AND is_like=1",(post_id,)).fetchone()[0]
    dislikes=conn.execute("SELECT COUNT(*) FROM likes WHERE post_id=? AND is_like=0",(post_id,)).fetchone()[0]
    cc=conn.execute("SELECT COUNT(*) FROM comments WHERE post_id=? AND parent_id IS NULL",(post_id,)).fetchone()[0]
    conn.close()
    return render_template("post_detail.html",post=post,comments=comments,saved_ids=saved_ids,liked_map=liked_map,likes=likes,dislikes=dislikes,comment_count=cc)

@app.route("/like/<int:post_id>",methods=["POST"])
@login_required
def like_post(post_id):
    is_like=request.json.get("is_like",True); uid=session["user_id"]; conn=get_db()
    ex=conn.execute("SELECT id,is_like FROM likes WHERE post_id=? AND user_id=?",(post_id,uid)).fetchone()
    if ex:
        if ex["is_like"]==(1 if is_like else 0): conn.execute("DELETE FROM likes WHERE id=?",(ex["id"],))
        else: conn.execute("UPDATE likes SET is_like=? WHERE id=?",(1 if is_like else 0,ex["id"]))
    else: conn.execute("INSERT INTO likes (post_id,user_id,is_like) VALUES (?,?,?)",(post_id,uid,1 if is_like else 0))
    conn.commit()
    l=conn.execute("SELECT COUNT(*) FROM likes WHERE post_id=? AND is_like=1",(post_id,)).fetchone()[0]
    d=conn.execute("SELECT COUNT(*) FROM likes WHERE post_id=? AND is_like=0",(post_id,)).fetchone()[0]
    conn.close(); return jsonify({"likes":l,"dislikes":d})

@app.route("/comment/<int:post_id>",methods=["POST"])
@login_required
def add_comment(post_id):
    content=request.form.get("content","").strip(); parent_id=request.form.get("parent_id",type=int)
    if not content: return jsonify({"error":"Empty"}),400
    uid=session["user_id"]; conn=get_db()
    conn.execute("INSERT INTO comments (content,post_id,user_id,parent_id) VALUES (?,?,?,?)",(content,post_id,uid,parent_id))
    cid=conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    u=conn.execute("SELECT username,full_name,profile_pic FROM users WHERE id=?",(uid,)).fetchone()
    conn.commit(); conn.close()
    return jsonify({"id":cid,"content":content,"username":u["username"],"full_name":u["full_name"] or u["username"],"profile_pic":u["profile_pic"] or "","parent_id":parent_id,"created_at":datetime.now().strftime("%b %d, %Y %H:%M")})

@app.route("/comment/delete/<int:cid>",methods=["POST"])
@login_required
def delete_comment(cid):
    uid=session["user_id"]; conn=get_db(); c=conn.execute("SELECT user_id FROM comments WHERE id=?",(cid,)).fetchone()
    if not c: conn.close(); return jsonify({"error":"Not found"}),404
    if c["user_id"]!=uid and session.get("role")!="admin": conn.close(); return jsonify({"error":"Unauthorized"}),403
    conn.execute("DELETE FROM comments WHERE id=? OR parent_id=?",(cid,cid)); conn.commit(); conn.close(); return jsonify({"success":True})

@app.route("/save/<int:post_id>",methods=["POST"])
@login_required
def save_post(post_id):
    uid=session["user_id"]; conn=get_db(); ex=conn.execute("SELECT id FROM saved_posts WHERE post_id=? AND user_id=?",(post_id,uid)).fetchone()
    if ex: conn.execute("DELETE FROM saved_posts WHERE id=?",(ex["id"],)); saved=False
    else: conn.execute("INSERT INTO saved_posts (post_id,user_id) VALUES (?,?)",(post_id,uid)); saved=True
    conn.commit(); conn.close(); return jsonify({"saved":saved})

@app.route("/share/<int:post_id>")
@login_required
def share_post(post_id):
    conn=get_db(); post=conn.execute("SELECT title FROM posts WHERE id=?",(post_id,)).fetchone(); conn.close()
    return jsonify({"url":request.host_url+f"post/{post_id}","title":post["title"] if post else ""})

@app.route("/notifications/read",methods=["POST"])
@login_required
def mark_notifications_read():
    conn=get_db(); conn.execute("UPDATE notifications SET is_read=1 WHERE user_id=?",(session["user_id"],)); conn.commit(); conn.close(); return jsonify({"success":True})

@app.route("/profile/<int:user_id>")
@login_required
def profile(user_id):
    conn=get_db(); user=conn.execute("SELECT * FROM users WHERE id=?",(user_id,)).fetchone()
    if not user: conn.close(); return redirect(url_for("dashboard"))
    posts=conn.execute("SELECT * FROM posts WHERE user_id=? AND is_published=1 ORDER BY created_at DESC",(user_id,)).fetchall()
    followers=conn.execute("SELECT COUNT(*) FROM follows WHERE followed_id=?",(user_id,)).fetchone()[0]
    following=conn.execute("SELECT COUNT(*) FROM follows WHERE follower_id=?",(user_id,)).fetchone()[0]
    is_following=bool(conn.execute("SELECT id FROM follows WHERE follower_id=? AND followed_id=?",(session["user_id"],user_id)).fetchone())
    def ps(pid):
        l=conn.execute("SELECT COUNT(*) FROM likes WHERE post_id=? AND is_like=1",(pid,)).fetchone()[0]
        c=conn.execute("SELECT COUNT(*) FROM comments WHERE post_id=?",(pid,)).fetchone()[0]
        return l,c
    posts_data=[{"post":p,"likes":ps(p["id"])[0],"comments":ps(p["id"])[1]} for p in posts]
    saved_count=conn.execute("SELECT COUNT(*) FROM saved_posts WHERE user_id=?",(user_id,)).fetchone()[0]
    total_likes=conn.execute("SELECT COUNT(*) FROM likes l JOIN posts p ON l.post_id=p.id WHERE p.user_id=? AND l.is_like=1",(user_id,)).fetchone()[0]
    conn.close()
    return render_template("profile.html",user=user,posts_data=posts_data,followers=followers,following=following,is_following=is_following,saved_count=saved_count,total_likes=total_likes)

@app.route("/saved")
@login_required
def saved_posts():
    uid=session["user_id"]; conn=get_db()
    saves=conn.execute("SELECT p.* FROM posts p JOIN saved_posts s ON p.id=s.post_id WHERE s.user_id=? ORDER BY s.created_at DESC",(uid,)).fetchall()
    conn.close(); return render_template("saved_posts.html",posts=saves)

@app.route("/profile/edit",methods=["GET","POST"])
@login_required
def edit_profile():
    uid=session["user_id"]
    if request.method=="POST":
        conn=get_db(); existing=conn.execute("SELECT * FROM users WHERE id=?",(uid,)).fetchone()
        full_name=request.form.get("full_name",""); bio=request.form.get("bio",""); phone=request.form.get("phone",""); county=request.form.get("county",""); crop_types=request.form.get("crop_types",""); farm_size=request.form.get("farm_size",""); new_email=request.form.get("email",existing["email"])
        if new_email!=existing["email"] and conn.execute("SELECT id FROM users WHERE email=? AND id!=?",(new_email,uid)).fetchone():
            flash("Email in use.","error"); conn.close(); return redirect(url_for("edit_profile"))
        pic=existing["profile_pic"] or ""
        if "profile_pic" in request.files:
            file=request.files["profile_pic"]
            if file and file.filename and allowed_file(file.filename):
                os.makedirs(UPLOAD_FOLDER,exist_ok=True); fn=secure_filename(f"profile_{uid}_{file.filename}"); file.save(os.path.join(UPLOAD_FOLDER,fn)); pic=fn
        conn.execute("UPDATE users SET full_name=?,bio=?,phone=?,county=?,crop_types=?,farm_size=?,email=?,profile_pic=? WHERE id=?",(full_name,bio,phone,county,crop_types,farm_size,new_email,pic,uid))
        new_pw=request.form.get("new_password","")
        if new_pw:
            if not check_password_hash(existing["password"],request.form.get("current_password","")):
                flash("Wrong current password.","error"); conn.commit(); conn.close(); return redirect(url_for("edit_profile"))
            conn.execute("UPDATE users SET password=? WHERE id=?",(generate_password_hash(new_pw),uid))
        conn.commit(); conn.close(); flash("Profile updated!","success"); return redirect(url_for("profile",user_id=uid))
    conn=get_db(); u=conn.execute("SELECT * FROM users WHERE id=?",(uid,)).fetchone(); conn.close()
    return render_template("edit_profile.html",user=u)

@app.route("/follow/<int:user_id>",methods=["POST"])
@login_required
def follow_user(user_id):
    fid=session["user_id"]
    if fid==user_id: return jsonify({"error":"Cannot follow yourself"}),400
    conn=get_db(); ex=conn.execute("SELECT id FROM follows WHERE follower_id=? AND followed_id=?",(fid,user_id)).fetchone()
    if ex: conn.execute("DELETE FROM follows WHERE id=?",(ex["id"],)); following=False
    else: conn.execute("INSERT INTO follows (follower_id,followed_id) VALUES (?,?)",(fid,user_id)); following=True
    conn.commit(); count=conn.execute("SELECT COUNT(*) FROM follows WHERE followed_id=?",(user_id,)).fetchone()[0]; conn.close()
    return jsonify({"following":following,"followers":count})

# ADMIN ROUTES
@app.route("/admin")
@login_required
@admin_required
def admin_dashboard():
    conn=get_db()
    tu=conn.execute("SELECT COUNT(*) FROM users WHERE role='farmer'").fetchone()[0]
    tp=conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0]
    tc=conn.execute("SELECT COUNT(*) FROM comments").fetchone()[0]
    pp=conn.execute("SELECT COUNT(*) FROM posts WHERE is_published=1").fetchone()[0]
    tl=conn.execute("SELECT COUNT(*) FROM likes WHERE is_like=1").fetchone()[0]
    bu=conn.execute("SELECT COUNT(*) FROM users WHERE is_banned=1").fetchone()[0]
    ru=conn.execute("SELECT * FROM users WHERE role='farmer' ORDER BY created_at DESC LIMIT 5").fetchall()
    rp=conn.execute("SELECT * FROM posts ORDER BY created_at DESC LIMIT 5").fetchall()
    now=datetime.utcnow(); ug=[]; pg=[]
    for i in range(6,-1,-1):
        d=(now-timedelta(days=i)).strftime("%Y-%m-%d"); lbl=(now-timedelta(days=i)).strftime("%a")
        ug.append({"day":lbl,"count":conn.execute("SELECT COUNT(*) FROM users WHERE DATE(created_at)=?",(d,)).fetchone()[0]})
        pg.append({"day":lbl,"count":conn.execute("SELECT COUNT(*) FROM posts WHERE DATE(created_at)=?",(d,)).fetchone()[0]})
    cs=conn.execute("SELECT category,COUNT(*) as c FROM posts GROUP BY category").fetchall()
    coy=conn.execute("SELECT county,COUNT(*) as c FROM users WHERE role='farmer' GROUP BY county LIMIT 8").fetchall()
    logs=conn.execute("SELECT * FROM ai_logs ORDER BY created_at DESC LIMIT 5").fetchall()
    top=conn.execute("SELECT p.*,COUNT(l.id) as lc FROM posts p LEFT JOIN likes l ON p.id=l.post_id AND l.is_like=1 GROUP BY p.id ORDER BY lc DESC LIMIT 5").fetchall()
    conn.close()
    return render_template("admin_dashboard.html",total_users=tu,total_posts=tp,total_comments=tc,published_posts=pp,total_likes=tl,banned_users=bu,recent_users=ru,recent_posts=rp,user_growth=json.dumps(ug),post_growth=json.dumps(pg),cat_stats=json.dumps([{"label":r["category"] or "General","value":r["c"]} for r in cs]),county_stats=json.dumps([{"label":r["county"] or "Unknown","value":r["c"]} for r in coy]),ai_logs=logs,top_posts=top)

@app.route("/admin/users")
@login_required
@admin_required
def admin_users():
    page=request.args.get("page",1,type=int); search=request.args.get("search",""); per_page=15; offset=(page-1)*per_page
    conn=get_db(); where="role='farmer'"; params=[]
    if search: where+=" AND (username LIKE ? OR email LIKE ? OR full_name LIKE ?)"; params.extend([f"%{search}%"]*3)
    total=conn.execute(f"SELECT COUNT(*) FROM users WHERE {where}",params).fetchone()[0]
    users=conn.execute(f"SELECT * FROM users WHERE {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",params+[per_page,offset]).fetchall()
    conn.close(); total_pages=(total+per_page-1)//per_page
    return render_template("admin_users.html",users=users,search=search,page=page,total_pages=total_pages,total=total)

@app.route("/admin/users/toggle/<int:uid>",methods=["POST"])
@login_required
@admin_required
def toggle_user(uid):
    conn=get_db(); u=conn.execute("SELECT is_active,role FROM users WHERE id=?",(uid,)).fetchone()
    new_val=0 if u["is_active"] else 1
    if u and u["role"]!="admin": conn.execute("UPDATE users SET is_active=? WHERE id=?",(new_val,uid)); conn.commit()
    conn.close(); return jsonify({"active":bool(new_val)})

@app.route("/admin/users/ban/<int:uid>",methods=["POST"])
@login_required
@admin_required
def ban_user(uid):
    reason=request.json.get("reason","Policy violation"); conn=get_db(); u=conn.execute("SELECT is_banned,role FROM users WHERE id=?",(uid,)).fetchone()
    new_val=0 if u["is_banned"] else 1; rsn=reason if new_val else ""
    if u and u["role"]!="admin": conn.execute("UPDATE users SET is_banned=?,ban_reason=? WHERE id=?",(new_val,rsn,uid)); conn.commit()
    conn.close(); return jsonify({"banned":bool(new_val)})

@app.route("/admin/users/delete/<int:uid>",methods=["POST"])
@login_required
@admin_required
def delete_user(uid):
    conn=get_db(); u=conn.execute("SELECT role FROM users WHERE id=?",(uid,)).fetchone()
    if u and u["role"]!="admin":
        conn.execute("DELETE FROM users WHERE id=?",(uid,)); conn.execute("DELETE FROM comments WHERE user_id=?",(uid,)); conn.execute("DELETE FROM likes WHERE user_id=?",(uid,)); conn.execute("DELETE FROM saved_posts WHERE user_id=?",(uid,)); conn.commit()
    conn.close(); flash("User deleted.","success"); return redirect(url_for("admin_users"))

@app.route("/admin/users/edit/<int:uid>",methods=["GET","POST"])
@login_required
@admin_required
def admin_edit_user(uid):
    conn=get_db(); u=conn.execute("SELECT * FROM users WHERE id=?",(uid,)).fetchone()
    if not u: conn.close(); return redirect(url_for("admin_users"))
    if request.method=="POST":
        conn.execute("UPDATE users SET full_name=?,email=?,phone=?,county=?,crop_types=?,farm_size=?,role=?,is_active=? WHERE id=?",
                     (request.form.get("full_name",""),request.form.get("email",u["email"]),request.form.get("phone",""),
                      request.form.get("county",""),request.form.get("crop_types",""),request.form.get("farm_size",""),
                      request.form.get("role",u["role"]),1 if request.form.get("is_active") else 0,uid))
        npw=request.form.get("new_password","")
        if npw: conn.execute("UPDATE users SET password=? WHERE id=?",(generate_password_hash(npw),uid))
        conn.commit(); conn.close(); flash("User updated.","success"); return redirect(url_for("admin_users"))
    conn.close(); return render_template("admin_edit_user.html",user=u)

@app.route("/admin/users/flag_comment/<int:cid>",methods=["POST"])
@login_required
@admin_required
def flag_comment(cid):
    reason=request.json.get("reason","Negative content"); conn=get_db()
    conn.execute("UPDATE comments SET is_flagged=1,flag_reason=? WHERE id=?",(reason,cid)); conn.commit(); conn.close()
    return jsonify({"success":True})

@app.route("/admin/account",methods=["GET","POST"])
@login_required
@admin_required
def admin_account():
    uid=session["user_id"]; conn=get_db()
    if request.method=="POST":
        action=request.form.get("action","")
        if action=="update_self":
            pic=conn.execute("SELECT profile_pic FROM users WHERE id=?",(uid,)).fetchone()["profile_pic"] or ""
            if "profile_pic" in request.files:
                f=request.files["profile_pic"]
                if f and f.filename and allowed_file(f.filename):
                    os.makedirs(UPLOAD_FOLDER,exist_ok=True); fn=secure_filename(f"profile_{uid}_{f.filename}"); f.save(os.path.join(UPLOAD_FOLDER,fn)); pic=fn
            conn.execute("UPDATE users SET full_name=?,email=?,phone=?,county=?,profile_pic=? WHERE id=?",
                         (request.form.get("full_name",""),request.form.get("email",""),request.form.get("phone",""),request.form.get("county",""),pic,uid))
            npw=request.form.get("new_password","")
            if npw:
                u=conn.execute("SELECT password FROM users WHERE id=?",(uid,)).fetchone()
                if not check_password_hash(u["password"],request.form.get("current_password","")):
                    flash("Wrong current password.","error"); conn.commit(); conn.close(); return redirect(url_for("admin_account"))
                conn.execute("UPDATE users SET password=? WHERE id=?",(generate_password_hash(npw),uid))
            conn.commit(); flash("Profile updated!","success")
        elif action=="add_admin":
            un=request.form.get("new_username","").strip(); em=request.form.get("new_email","").strip(); pw=request.form.get("new_password_admin",""); fn=request.form.get("new_full_name","")
            if not un or not em or not pw: flash("All fields required.","error")
            elif conn.execute("SELECT id FROM users WHERE username=?",(un,)).fetchone(): flash("Username taken.","error")
            elif conn.execute("SELECT id FROM users WHERE email=?",(em,)).fetchone(): flash("Email used.","error")
            else:
                conn.execute("INSERT INTO users (username,email,password,role,full_name) VALUES (?,?,?,?,?)",(un,em,generate_password_hash(pw),"admin",fn))
                conn.commit(); flash(f"Admin '{un}' created.","success")
        conn.close(); return redirect(url_for("admin_account"))
    me=conn.execute("SELECT * FROM users WHERE id=?",(uid,)).fetchone()
    admins=conn.execute("SELECT * FROM users WHERE role='admin' AND id!=?",(uid,)).fetchall()
    conn.close(); return render_template("admin_account.html",me=me,admins=admins)

@app.route("/admin/account/delete_admin/<int:aid>",methods=["POST"])
@login_required
@admin_required
def delete_admin(aid):
    if aid==session["user_id"]: flash("Cannot delete yourself.","error"); return redirect(url_for("admin_account"))
    conn=get_db(); conn.execute("DELETE FROM users WHERE id=? AND role='admin'",(aid,)); conn.commit(); conn.close()
    flash("Admin removed.","success"); return redirect(url_for("admin_account"))

@app.route("/admin/posts")
@login_required
@admin_required
def admin_posts():
    page=request.args.get("page",1,type=int); search=request.args.get("search",""); category=request.args.get("category",""); per_page=15; offset=(page-1)*per_page
    conn=get_db(); where=["1=1"]; params=[]
    if search: where.append("title LIKE ?"); params.append(f"%{search}%")
    if category: where.append("category=?"); params.append(category)
    ws=" AND ".join(where)
    total=conn.execute(f"SELECT COUNT(*) FROM posts WHERE {ws}",params).fetchone()[0]
    posts=conn.execute(f"SELECT * FROM posts WHERE {ws} ORDER BY created_at DESC LIMIT ? OFFSET ?",params+[per_page,offset]).fetchall()
    def st(pid):
        l=conn.execute("SELECT COUNT(*) FROM likes WHERE post_id=? AND is_like=1",(pid,)).fetchone()[0]
        c=conn.execute("SELECT COUNT(*) FROM comments WHERE post_id=?",(pid,)).fetchone()[0]
        return l,c
    posts_data=[{"post":p,"likes":st(p["id"])[0],"comments":st(p["id"])[1]} for p in posts]
    conn.close(); total_pages=(total+per_page-1)//per_page
    return render_template("admin_posts.html",posts_data=posts_data,search=search,category=category,page=page,total_pages=total_pages,total=total)

@app.route("/admin/posts/create",methods=["GET","POST"])
@login_required
@admin_required
def admin_create_post():
    if request.method=="POST":
        img=request.form.get("image_url","")
        if "image_file" in request.files:
            f=request.files["image_file"]
            if f and f.filename and allowed_file(f.filename):
                os.makedirs(UPLOAD_FOLDER,exist_ok=True); fn=secure_filename(f"post_{datetime.now().timestamp()}_{f.filename}"); f.save(os.path.join(UPLOAD_FOLDER,fn)); img=f"/static/uploads/{fn}"
        conn=get_db(); conn.execute("INSERT INTO posts (title,short_text,full_text,image_url,category,tags,target_crops,target_counties,is_published,is_pinned,user_id,source) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                     (request.form["title"],request.form["short_text"],request.form.get("full_text",""),img,request.form.get("category","advisory"),request.form.get("tags",""),request.form.get("target_crops",""),request.form.get("target_counties",""),1 if request.form.get("is_published") else 0,1 if request.form.get("is_pinned") else 0,session["user_id"],"manual"))
        conn.commit(); conn.close(); flash("Post created!","success"); return redirect(url_for("admin_posts"))
    return render_template("admin_post_form.html",post=None)

@app.route("/admin/posts/edit/<int:pid>",methods=["GET","POST"])
@login_required
@admin_required
def admin_edit_post(pid):
    conn=get_db(); post=conn.execute("SELECT * FROM posts WHERE id=?",(pid,)).fetchone()
    if not post: conn.close(); return redirect(url_for("admin_posts"))
    if request.method=="POST":
        img=request.form.get("image_url",post["image_url"])
        if "image_file" in request.files:
            f=request.files["image_file"]
            if f and f.filename and allowed_file(f.filename):
                os.makedirs(UPLOAD_FOLDER,exist_ok=True); fn=secure_filename(f"post_{pid}_{f.filename}"); f.save(os.path.join(UPLOAD_FOLDER,fn)); img=f"/static/uploads/{fn}"
        conn.execute("UPDATE posts SET title=?,short_text=?,full_text=?,image_url=?,category=?,tags=?,target_crops=?,target_counties=?,is_published=?,is_pinned=?,updated_at=datetime('now') WHERE id=?",
                     (request.form["title"],request.form["short_text"],request.form.get("full_text",""),img,request.form.get("category","advisory"),request.form.get("tags",""),request.form.get("target_crops",""),request.form.get("target_counties",""),1 if request.form.get("is_published") else 0,1 if request.form.get("is_pinned") else 0,pid))
        conn.commit(); conn.close(); flash("Post updated!","success"); return redirect(url_for("admin_posts"))
    conn.close(); return render_template("admin_post_form.html",post=post)

@app.route("/admin/posts/delete/<int:pid>",methods=["POST"])
@login_required
@admin_required
def admin_delete_post(pid):
    conn=get_db(); conn.execute("DELETE FROM posts WHERE id=?",(pid,)); conn.execute("DELETE FROM comments WHERE post_id=?",(pid,)); conn.execute("DELETE FROM likes WHERE post_id=?",(pid,)); conn.commit(); conn.close()
    flash("Post deleted.","success"); return redirect(url_for("admin_posts"))

@app.route("/admin/posts/toggle/<int:pid>",methods=["POST"])
@login_required
@admin_required
def toggle_post(pid):
    conn=get_db(); p=conn.execute("SELECT is_published FROM posts WHERE id=?",(pid,)).fetchone(); new_val=0 if p["is_published"] else 1
    conn.execute("UPDATE posts SET is_published=? WHERE id=?",(new_val,pid)); conn.commit(); conn.close(); return jsonify({"published":bool(new_val)})

@app.route("/admin/posts/pending")
@login_required
@admin_required
def admin_pending_posts():
    conn=get_db(); posts=conn.execute("SELECT * FROM posts WHERE is_published=0 AND source='ai_model' ORDER BY created_at DESC").fetchall(); conn.close()
    return render_template("admin_pending.html",posts=posts)

@app.route("/admin/posts/approve/<int:pid>",methods=["POST"])
@login_required
@admin_required
def approve_post(pid):
    conn=get_db(); conn.execute("UPDATE posts SET is_published=1 WHERE id=?",(pid,)); conn.commit(); conn.close(); return jsonify({"success":True})

@app.route("/admin/reports")
@login_required
@admin_required
def admin_reports():
    conn=get_db()
    tu=conn.execute("SELECT COUNT(*) FROM users WHERE role='farmer'").fetchone()[0]
    au=conn.execute("SELECT COUNT(*) FROM users WHERE role='farmer' AND is_active=1").fetchone()[0]
    bu=conn.execute("SELECT COUNT(*) FROM users WHERE is_banned=1").fetchone()[0]
    tp=conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0]
    ai=conn.execute("SELECT COUNT(*) FROM posts WHERE source='ai_model'").fetchone()[0]
    mp=conn.execute("SELECT COUNT(*) FROM posts WHERE source='manual'").fetchone()[0]
    tl=conn.execute("SELECT COUNT(*) FROM likes WHERE is_like=1").fetchone()[0]
    tc=conn.execute("SELECT COUNT(*) FROM comments").fetchone()[0]
    ts=conn.execute("SELECT COUNT(*) FROM saved_posts").fetchone()[0]
    fc=conn.execute("SELECT COUNT(*) FROM comments WHERE is_flagged=1").fetchone()[0]
    coy=conn.execute("SELECT county,COUNT(*) as c FROM users WHERE role='farmer' GROUP BY county").fetchall()
    crp=conn.execute("SELECT crop_types,COUNT(*) as c FROM users WHERE role='farmer' GROUP BY crop_types").fetchall()
    cat=conn.execute("SELECT category,COUNT(*) as c FROM posts GROUP BY category").fetchall()
    ceng=conn.execute("SELECT p.category,COUNT(l.id) as c FROM posts p LEFT JOIN likes l ON p.id=l.post_id AND l.is_like=1 GROUP BY p.category").fetchall()
    mly=[]
    for i in range(5,-1,-1):
        d=(datetime.utcnow()-timedelta(days=i*30)); ym=d.strftime("%Y-%m")
        mly.append({"month":d.strftime("%b %Y"),"count":conn.execute("SELECT COUNT(*) FROM users WHERE strftime('%Y-%m',created_at)=?",(ym,)).fetchone()[0]})
    top=conn.execute("SELECT p.title,p.category,COUNT(l.id) as lc,(SELECT COUNT(*) FROM comments WHERE post_id=p.id) as cc FROM posts p LEFT JOIN likes l ON p.id=l.post_id AND l.is_like=1 GROUP BY p.id ORDER BY lc DESC LIMIT 10").fetchall()
    conn.close()
    return render_template("admin_reports.html",total_users=tu,active_users=au,banned_users=bu,total_posts=tp,ai_posts=ai,manual_posts=mp,total_likes=tl,total_comments=tc,total_saves=ts,flagged_comments=fc,
        county_data=json.dumps([{"label":r["county"] or "Unknown","value":r["c"]} for r in coy]),
        crop_data=json.dumps([{"label":r["crop_types"] or "Unknown","value":r["c"]} for r in crp]),
        cat_data=json.dumps([{"label":r["category"] or "General","value":r["c"]} for r in cat]),
        cat_eng=json.dumps([{"label":r["category"] or "General","value":r["c"]} for r in ceng]),
        monthly=json.dumps(mly),top_posts=top)

@app.route("/admin/reports/export")
@login_required
@admin_required
def export_report():
    rtype=request.args.get("type","users"); fmt=request.args.get("format","csv"); conn=get_db()
    if rtype=="users":
        rows=conn.execute("SELECT id,username,email,full_name,county,crop_types,farm_size,phone,created_at,last_login,is_active,is_banned FROM users WHERE role='farmer'").fetchall()
        headers=["ID","Username","Email","Full Name","County","Crops","Farm Size","Phone","Joined","Last Login","Active","Banned"]
    elif rtype=="posts":
        rows=conn.execute("SELECT p.id,p.title,p.category,p.source,p.is_published,(SELECT COUNT(*) FROM likes WHERE post_id=p.id AND is_like=1) as likes,(SELECT COUNT(*) FROM comments WHERE post_id=p.id) as comments,p.created_at FROM posts p").fetchall()
        headers=["ID","Title","Category","Source","Published","Likes","Comments","Created"]
    elif rtype=="engagement":
        rows=conn.execute("SELECT p.title,p.category,(SELECT COUNT(*) FROM likes WHERE post_id=p.id AND is_like=1) as likes,(SELECT COUNT(*) FROM likes WHERE post_id=p.id AND is_like=0) as dislikes,(SELECT COUNT(*) FROM comments WHERE post_id=p.id) as comments,(SELECT COUNT(*) FROM saved_posts WHERE post_id=p.id) as saves FROM posts p").fetchall()
        headers=["Title","Category","Likes","Dislikes","Comments","Saves"]
    elif rtype=="comments":
        rows=conn.execute("SELECT c.id,u.username,p.title,c.content,c.is_flagged,c.flag_reason,c.created_at FROM comments c JOIN users u ON c.user_id=u.id JOIN posts p ON c.post_id=p.id ORDER BY c.created_at DESC").fetchall()
        headers=["ID","User","Post","Comment","Flagged","Flag Reason","Date"]
    else: rows=[]; headers=[]
    conn.close(); data=[dict(r) for r in rows]; ts=datetime.now().strftime("%Y%m%d_%H%M")
    if fmt=="csv":
        si=io.StringIO(); w=csv.writer(si); w.writerow(headers)
        for r in data: w.writerow(list(r.values()))
        return send_file(io.BytesIO(si.getvalue().encode("utf-8")),mimetype="text/csv",as_attachment=True,download_name=f"fp_{rtype}_{ts}.csv")
    elif fmt=="json":
        out=json.dumps({"report":rtype,"generated":ts,"total":len(data),"data":data},indent=2)
        return send_file(io.BytesIO(out.encode()),mimetype="application/json",as_attachment=True,download_name=f"fp_{rtype}_{ts}.json")
    elif fmt=="html":
        rh="".join(f"<tr>{''.join(f'<td>{v}</td>' for v in r.values())}</tr>" for r in data)
        hh="".join(f"<th>{h}</th>" for h in headers)
        html=f"""<!DOCTYPE html><html><head><meta charset='UTF-8'><title>FarmersPulse – {rtype} Report</title>
        <style>body{{font-family:'Times New Roman',serif;padding:32px;}}h1{{color:#2e7d32;}}h2{{color:#ff7f0e;font-size:16px;}}
        table{{width:100%;border-collapse:collapse;margin-top:20px;font-size:13px;}}th{{background:#2e7d32;color:#fff;padding:8px 10px;text-align:left;}}
        td{{padding:7px 10px;border-bottom:1px solid #dde8dd;}}tr:nth-child(even){{background:#f3f7f3;}}@media print{{.noprint{{display:none;}}}}</style></head>
        <body><h1>FarmersPulse – {rtype.title()} Report</h1><h2>Generated: {datetime.now().strftime('%B %d, %Y %H:%M')}</h2>
        <p>Total records: {len(data)}</p><button class='noprint' onclick='window.print()' style='background:#2e7d32;color:#fff;border:none;padding:8px 20px;border-radius:6px;cursor:pointer;margin-bottom:16px;'>Print / Save PDF</button>
        <table><thead><tr>{hh}</tr></thead><tbody>{rh}</tbody></table></body></html>"""
        resp=make_response(html); resp.headers["Content-Type"]="text/html; charset=utf-8"; resp.headers["Content-Disposition"]=f"attachment; filename=fp_{rtype}_{ts}.html"; return resp
    return redirect(url_for("admin_reports"))

AI_API_KEY=os.environ.get("FARMERSPULSE_AI_KEY","fp-ai-secret-2025")

# ─────────────────────────── AI: RECEIVE POST ───────────────────────────
@app.route("/api/ai/post",methods=["POST"])
def api_receive_post():
    if request.headers.get("X-API-Key","")!=AI_API_KEY: return jsonify({"error":"Unauthorized"}),401
    data=request.get_json()
    if not data or not data.get("title") or not data.get("short_text"): return jsonify({"error":"title and short_text required"}),400
    conn=get_db(); admin=conn.execute("SELECT id FROM users WHERE role='admin'").fetchone()
    conn.execute("INSERT INTO posts (title,short_text,full_text,image_url,category,tags,target_crops,target_counties,is_published,source,user_id) VALUES (?,?,?,?,?,?,?,?,0,?,?)",
                 (data["title"],data["short_text"],data.get("full_text",""),data.get("image_url",""),data.get("category","advisory"),data.get("tags",""),data.get("target_crops",""),data.get("target_counties",""),"ai_model",admin["id"] if admin else 1))
    pid=conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.execute("INSERT INTO ai_logs (endpoint,payload,response_status,post_id) VALUES (?,?,?,?)",("/api/ai/post",json.dumps(data),"success",pid))
    if admin: conn.execute("INSERT INTO notifications (user_id,content,notif_type,link) VALUES (?,?,?,?)",(admin["id"],f"New AI post pending: {data['title'][:50]}","system","/admin/posts/pending"))
    conn.commit(); conn.close(); return jsonify({"success":True,"post_id":pid,"status":"pending_review"}),201

# ─────────────────────────── AI: PERSONALIZATION API ───────────────────────────
# ==============================================================================
# PERSONALIZATION INTEGRATION POINT
#
# Your AI model (Google Colab) can call TWO endpoints:
#
# 1. GET /api/ai/user-profile/<user_id>
#    Returns the farmer's profile so your model can build a personalization query.
#    Headers: { "X-API-Key": "fp-ai-secret-2025" }
#
# 2. POST /api/ai/personalized-feed
#    Your model sends back an ordered list of post IDs for a user.
#    FarmersPulse will serve posts in that exact order.
#    Headers: { "X-API-Key": "fp-ai-secret-2025" }
#    Body: { "user_id": 3, "post_ids": [4, 1, 7, 2, ...], "model_version": "v1.0" }
#
# 3. GET /api/ai/all-posts (paginated, for your model to analyze)
#    Returns all published posts with metadata your model needs to rank them.
#    Headers: { "X-API-Key": "fp-ai-secret-2025" }
#    Query params: ?page=1&limit=100
#
# HOW IT WORKS END-TO-END:
#   a) Your Colab model calls /api/ai/user-profile/<id> to get farmer details
#   b) Model runs recommendation logic (crops, county, past likes, categories)
#   c) Model POSTs ranked post_ids back to /api/ai/personalized-feed
#   d) FarmersPulse caches that order in the DB
#   e) When farmer opens /dashboard, posts appear in AI-ranked order
#   f) Falls back to chronological if no AI ranking exists for the user
# ==============================================================================

@app.route("/api/ai/user-profile/<int:uid>", methods=["GET"])
def api_get_user_profile(uid):
    if request.headers.get("X-API-Key","") != AI_API_KEY:
        return jsonify({"error":"Unauthorized"}), 401
    conn = get_db()
    u = conn.execute("SELECT id,username,full_name,county,crop_types,farm_size,created_at,last_login FROM users WHERE id=? AND role='farmer'", (uid,)).fetchone()
    if not u:
        conn.close(); return jsonify({"error":"User not found"}), 404
    # Include interaction history for better recommendations
    liked_posts = conn.execute("""SELECT p.id,p.category,p.tags,p.target_crops,p.target_counties
                                  FROM likes l JOIN posts p ON l.post_id=p.id
                                  WHERE l.user_id=? AND l.is_like=1 ORDER BY l.created_at DESC LIMIT 20""", (uid,)).fetchall()
    saved_posts = conn.execute("""SELECT p.id,p.category,p.tags FROM saved_posts s JOIN posts p ON s.post_id=p.id
                                  WHERE s.user_id=? ORDER BY s.created_at DESC LIMIT 20""", (uid,)).fetchall()
    commented = conn.execute("""SELECT DISTINCT p.id,p.category FROM comments c JOIN posts p ON c.post_id=p.id
                                WHERE c.user_id=? ORDER BY c.created_at DESC LIMIT 10""", (uid,)).fetchall()
    conn.close()
    return jsonify({
        "user_id": u["id"],
        "username": u["username"],
        "county": u["county"] or "",
        "crop_types": [c.strip() for c in (u["crop_types"] or "").split(",") if c.strip()],
        "farm_size": u["farm_size"] or "",
        "joined": u["created_at"][:10],
        "last_active": u["last_login"][:10] if u["last_login"] else None,
        "interaction_history": {
            "liked_posts": [{"id":p["id"],"category":p["category"],"tags":p["tags"],"crops":p["target_crops"],"counties":p["target_counties"]} for p in liked_posts],
            "saved_posts":  [{"id":p["id"],"category":p["category"],"tags":p["tags"]} for p in saved_posts],
            "commented_on": [{"id":p["id"],"category":p["category"]} for p in commented]
        }
    })

@app.route("/api/ai/all-posts", methods=["GET"])
def api_get_all_posts():
    if request.headers.get("X-API-Key","") != AI_API_KEY:
        return jsonify({"error":"Unauthorized"}), 401
    page  = request.args.get("page",  1, type=int)
    limit = request.args.get("limit", 100, type=int)
    limit = min(limit, 200)
    offset = (page-1)*limit
    conn = get_db()
    total = conn.execute("SELECT COUNT(*) FROM posts WHERE is_published=1").fetchone()[0]
    posts = conn.execute("""SELECT id,title,short_text,category,tags,target_crops,target_counties,
                            source,created_at,is_pinned FROM posts WHERE is_published=1
                            ORDER BY created_at DESC LIMIT ? OFFSET ?""", (limit,offset)).fetchall()
    # Include engagement counts so model can factor in popularity
    result = []
    for p in posts:
        likes = conn.execute("SELECT COUNT(*) FROM likes WHERE post_id=? AND is_like=1", (p["id"],)).fetchone()[0]
        comments = conn.execute("SELECT COUNT(*) FROM comments WHERE post_id=?", (p["id"],)).fetchone()[0]
        result.append({
            "id": p["id"], "title": p["title"], "short_text": p["short_text"],
            "category": p["category"], "tags": [t.strip() for t in (p["tags"] or "").split(",") if t.strip()],
            "target_crops": [c.strip() for c in (p["target_crops"] or "").split(",") if c.strip()],
            "target_counties": [c.strip() for c in (p["target_counties"] or "").split(",") if c.strip()],
            "source": p["source"], "created_at": p["created_at"][:10],
            "is_pinned": bool(p["is_pinned"]),
            "engagement": {"likes": likes, "comments": comments}
        })
    conn.close()
    return jsonify({"total": total, "page": page, "limit": limit, "posts": result})

@app.route("/api/ai/personalized-feed", methods=["POST"])
def api_set_personalized_feed():
    """Your AI model POSTs the ranked list of post IDs for a user here."""
    if request.headers.get("X-API-Key","") != AI_API_KEY:
        return jsonify({"error":"Unauthorized"}), 401
    data = request.get_json()
    if not data or not data.get("user_id") or not isinstance(data.get("post_ids"), list):
        return jsonify({"error":"user_id and post_ids (list) required"}), 400
    uid = data["user_id"]
    post_ids = data["post_ids"]  # ordered list, most relevant first
    import time
    conn = get_db()
    # Store in personalization logs — dashboard reads from here
    conn.execute("DELETE FROM ai_personalization_logs WHERE user_id=?", (uid,))
    conn.execute("""INSERT INTO ai_personalization_logs (user_id,request_payload,response_payload,post_ids_returned,response_time_ms)
                    VALUES (?,?,?,?,?)""",
                 (uid, json.dumps(data.get("request_context",{})),
                  json.dumps({"model_version": data.get("model_version","unknown")}),
                  json.dumps(post_ids), data.get("response_time_ms", 0)))
    conn.commit(); conn.close()
    return jsonify({"success": True, "user_id": uid, "posts_ranked": len(post_ids)}), 200

@app.route("/api/ai/bulk-profiles", methods=["GET"])
def api_bulk_profiles():
    """Get all farmer profiles at once — for batch recommendation runs."""
    if request.headers.get("X-API-Key","") != AI_API_KEY:
        return jsonify({"error":"Unauthorized"}), 401
    conn = get_db()
    users = conn.execute("SELECT id,username,county,crop_types,farm_size,last_login FROM users WHERE role='farmer' AND is_active=1 AND is_banned=0").fetchall()
    conn.close()
    return jsonify({"total": len(users), "users": [{"id":u["id"],"username":u["username"],"county":u["county"] or "","crop_types":[c.strip() for c in (u["crop_types"] or "").split(",") if c.strip()],"farm_size":u["farm_size"] or "","last_active":u["last_login"][:10] if u["last_login"] else None} for u in users]})

# ─────────────────────────── FEEDBACK ───────────────────────────

@app.route("/about")
@login_required
def about():
    return render_template("about.html")

@app.route("/feedback", methods=["GET","POST"])
@login_required
def feedback():
    if request.method == "POST":
        conn = get_db()
        conn.execute("""INSERT INTO feedback (user_id,name,email,subject,message,category)
                        VALUES (?,?,?,?,?,?)""",
                     (session["user_id"],
                      request.form.get("name",""),
                      request.form.get("email",""),
                      request.form.get("subject",""),
                      request.form.get("message",""),
                      request.form.get("category","general")))
        # Notify admin
        admin = conn.execute("SELECT id FROM users WHERE role='admin'").fetchone()
        if admin:
            conn.execute("INSERT INTO notifications (user_id,content,notif_type,link) VALUES (?,?,?,?)",
                         (admin["id"], f"New feedback from {session['username']}: {request.form.get('subject','')[:50]}", "system", "/admin/feedback"))
        conn.commit(); conn.close()
        flash("Thank you for your feedback! We'll review it shortly.", "success")
        return redirect(url_for("about"))
    conn = get_db()
    u = conn.execute("SELECT * FROM users WHERE id=?", (session["user_id"],)).fetchone()
    conn.close()
    return render_template("feedback.html", user=u)

@app.route("/admin/feedback")
@login_required
@admin_required
def admin_feedback():
    status_filter = request.args.get("status","")
    conn = get_db()
    where = "1=1"
    params = []
    if status_filter:
        where = "status=?"
        params = [status_filter]
    feedbacks = conn.execute(f"""SELECT f.*,u.username FROM feedback f
                                 LEFT JOIN users u ON f.user_id=u.id
                                 WHERE {where} ORDER BY f.created_at DESC""", params).fetchall()
    counts = {
        "total":    conn.execute("SELECT COUNT(*) FROM feedback").fetchone()[0],
        "unread":   conn.execute("SELECT COUNT(*) FROM feedback WHERE status='unread'").fetchone()[0],
        "reviewed": conn.execute("SELECT COUNT(*) FROM feedback WHERE status='reviewed'").fetchone()[0],
        "resolved": conn.execute("SELECT COUNT(*) FROM feedback WHERE status='resolved'").fetchone()[0],
    }
    conn.close()
    return render_template("admin_feedback.html", feedbacks=feedbacks, counts=counts, status_filter=status_filter)

@app.route("/admin/feedback/update/<int:fid>", methods=["POST"])
@login_required
@admin_required
def update_feedback(fid):
    status = request.form.get("status","reviewed")
    reply  = request.form.get("admin_reply","")
    conn = get_db()
    conn.execute("UPDATE feedback SET status=?,admin_reply=? WHERE id=?", (status,reply,fid))
    conn.commit(); conn.close()
    flash("Feedback updated.", "success")
    return redirect(url_for("admin_feedback"))

@app.route("/admin/feedback/delete/<int:fid>", methods=["POST"])
@login_required
@admin_required
def delete_feedback(fid):
    conn = get_db()
    conn.execute("DELETE FROM feedback WHERE id=?", (fid,))
    conn.commit(); conn.close()
    return jsonify({"success": True})

os.makedirs(UPLOAD_FOLDER,exist_ok=True)
init_db()

if __name__=="__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
