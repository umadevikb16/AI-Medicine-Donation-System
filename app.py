import qrcode
from PIL import Image
import os
from werkzeug.security import generate_password_hash, check_password_hash
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas

from flask import Flask, request, jsonify, render_template,redirect,url_for, session
from pymongo import MongoClient
from bson.objectid import ObjectId
from datetime import datetime

from werkzeug.utils import secure_filename
from ocr.extract_expiry_selected import get_expiry_from_image

# -------------------- APP SETUP --------------------
app = Flask(__name__)
app.secret_key = "admin_secret_key"

client = MongoClient("mongodb://localhost:27017/")
db = client["medicine_db"]

# -------------------- COLLECTIONS --------------------
donation_collection = db["donations"]
medicine_collection = db["medicine_collection"]
request_collection = db["request_collection"]
donor_collection = db["donors"]
ngo_user_collection = db["ngo_users"]
stock_history_collection = db["stock_history"]


# -------------------- ADMIN CREDENTIALS --------------------
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "admin123"

# -------------------- HOME --------------------
@app.route("/")
def home():
    return render_template("home.html")

# -------------------- REGISTER DONOR --------------------
@app.route("/register/donor", methods=["GET", "POST"])
def register_donor():
    if request.method == "POST":

        # ✅ DEFINE EMAIL FIRST
        email = request.form["email"].strip().lower()

        # ✅ NOW YOU CAN USE IT
        if donor_collection.find_one({"email": email}):
            return render_template(
                "register_donor.html",
                error="Email already exists"
            )

        donor_collection.insert_one({
            "name": request.form["name"],
            "phone": request.form["phone"],
            "email": email,
            "location": request.form["location"],
            "password": generate_password_hash(request.form["password"]),
            "created_at": datetime.now()
        })

        return redirect("/login")

    return render_template("register_donor.html")


# -------------------- REGISTER NGO --------------------
@app.route("/register/ngo", methods=["GET", "POST"])
def register_ngo():
    if request.method == "POST":

        ngo_name = request.form["ngo_name"]
        ngo_type = request.form["ngo_type"]
        email = request.form["email"]
        phone = request.form["phone"]
        location = request.form["location"]

        latitude = float(request.form["latitude"])
        longitude = float(request.form["longitude"])

        raw_password = request.form["password"]
        password = generate_password_hash(raw_password)

        if ngo_user_collection.find_one({"email": email}):
            return render_template(
                "ngo_register.html",
                error="Email already registered"
            )

        ngo_user_collection.insert_one({
            "ngo_name": ngo_name,
            "ngo_type": ngo_type,
            "email": email,
            "phone": phone,
            "location": location,
            "latitude": latitude,
            "longitude": longitude,
            "priority_level": "Medium",
            "created_at": datetime.utcnow(),
            "password": password
        })

        return redirect(url_for("user_login"))

    return render_template("ngo_register.html")

# -------------------- LOGIN --------------------
@app.route("/admin", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
            session["admin_logged_in"] = True
            return redirect("/admin/home")
        else:
            return render_template("admin_login.html", error="Invalid credentials")

    return render_template("admin_login.html")

@app.route("/admin/home")
def admin_home():
    if not session.get("admin_logged_in"):
        return redirect("/admin")

    high_count = donation_collection.count_documents({"priority": "High"})
    medium_count = donation_collection.count_documents({"priority": "Medium"})
    low_count = donation_collection.count_documents({"priority": "Low"})

    total_donations = donation_collection.count_documents({})

    donation_progress = min(int((total_donations / 100) * 100), 100)

    return render_template(
        "admin_home.html",
        high_count=high_count,
        medium_count=medium_count,
        low_count=low_count,
        total_donations=total_donations,
        donation_progress=donation_progress
    )

@app.route("/admin/dashboard")
def admin_dashboard():
    if not session.get("admin_logged_in"):
        return redirect("/admin")

    total_donations = donation_collection.count_documents({})
    pending_requests = request_collection.count_documents({"status": "Pending"})
    approved_requests = request_collection.count_documents({"status": "Approved"})
    delivered_requests = request_collection.count_documents({"status": "Delivered"})
    expiring_count = donation_collection.count_documents({"expiry_alert": True})

    return render_template(
        "admin_dashboard.html",
        total_donations=total_donations,
        pending_requests=pending_requests,
        approved_requests=approved_requests,
        delivered_requests=delivered_requests,
        expiring_count=expiring_count
    )

@app.route("/admin/donations")
def admin_all_donations():
    donations = donation_collection.find().sort("created_at", -1)
    return render_template(
        "admin_donations.html",
        donations=donations
    )

@app.route("/admin/donations/<donation_id>")
def admin_view_donation(donation_id):
    donation = donation_collection.find_one(
        {"_id": ObjectId(donation_id)}
    )

    if not donation:
        return "Donation not found", 404

    return render_template(
        "admin_view_donation.html",
        donation=donation
    )

@app.route("/admin/expiring-medicines")
def admin_expiring_medicines():
    if not session.get("admin_logged_in"):
        return redirect("/admin")

    medicines = list(
        donation_collection.find({"expiry_alert": True})
        .sort("expiry_date", 1)
    )

    return render_template(
        "admin_expiring_medicines.html",
        medicines=medicines
    )

@app.route("/admin/ngo/requests")
def admin_view_ngo_requests():
    if not session.get("admin_logged_in"):
        return redirect("/admin")

    requests = list(
        request_collection.find().sort("requested_at", -1)
    )

    return render_template(
        "admin_ngo_requests.html",
        requests=requests
    )
from bson.objectid import ObjectId

@app.route("/admin/ngo/request/action/<request_id>", methods=["POST"])
def admin_request_action(request_id):
    if not session.get("admin_logged_in"):
        return redirect("/admin")

    action = request.form["action"]

    req = request_collection.find_one(
        {"_id": ObjectId(request_id)}
    )

    if not req:
        return redirect("/admin/ngo/requests")

    medicine = donation_collection.find_one(
        {"_id": ObjectId(req["medicine_id"])}
    )

    if not medicine:
        return redirect("/admin/ngo/requests")

    # ✅ APPROVE
    if action == "approve":
        requested_qty = req["quantity"]
        available_qty = medicine.get("quantity", 0)

        # 🚫 INSUFFICIENT STOCK
        if requested_qty > available_qty:
            return redirect("/admin/ngo/requests")

        new_qty = available_qty - requested_qty

        # 1️⃣ Update stock
        donation_collection.update_one(
            {"_id": medicine["_id"]},
            {"$set": {
                "quantity": new_qty,
                "status": "Out of Stock" if new_qty == 0 else "Available"
            }}
        )

        # 📍 GOOGLE MAP LINK
        lat = medicine.get("donor_lat")
        lon = medicine.get("donor_lon")

        map_link = None
        if lat and lon:
            map_link = f"https://www.google.com/maps?q={lat},{lon}"

        # 2️⃣ Update request + collection details
        request_collection.update_one(
            {"_id": ObjectId(request_id)},
            {"$set": {
                "status": "Approved",

                "collection_method": "pickup",
                "collection_address": f"{medicine.get('donor_name', 'Donor')} - {medicine.get('donor_phone', 'Not Available')}",
                "collection_status": "Pending",

                # 🔗 MAP LINK STORED HERE
                "map_link": map_link
            }}
        )

        # 3️⃣ Stock history log
        stock_history_collection.insert_one({
            "medicine_id": medicine["_id"],
            "medicine_name": medicine.get("medicine_name"),
            "action": "Approved",
            "quantity_changed": requested_qty,
            "previous_stock": available_qty,
            "new_stock": new_qty,
            "admin": "admin",
            "request_id": ObjectId(request_id),
            "timestamp": datetime.now()
        })

        # 4️⃣ Notification
        send_ngo_notification(
            ngo_email=req["ngo_email"],
            medicine_name=req["medicine_name"],
            quantity=req["quantity"],
            status="Approved"
        )

    # ❌ REJECT
    elif action == "reject":
        request_collection.update_one(
            {"_id": ObjectId(request_id)},
            {"$set": {"status": "Rejected"}}
        )

        send_ngo_notification(
            ngo_email=req["ngo_email"],
            medicine_name=req["medicine_name"],
            quantity=req["quantity"],
            status="Rejected"
        )

    # 📦 DELIVER
    elif action == "deliver":
        request_collection.update_one(
            {"_id": ObjectId(request_id)},
            {"$set": {"status": "Delivered"}}
        )

        stock_history_collection.insert_one({
            "medicine_id": medicine["_id"],
            "medicine_name": medicine.get("medicine_name"),
            "action": "Delivered",
            "quantity_changed": 0,
            "previous_stock": medicine.get("quantity"),
            "new_stock": medicine.get("quantity"),
            "admin": "admin",
            "request_id": ObjectId(request_id),
            "timestamp": datetime.now()
        })

        send_ngo_notification(
            ngo_email=req["ngo_email"],
            medicine_name=req["medicine_name"],
            quantity=req["quantity"],
            status="Delivered"
        )

    return redirect("/admin/ngo/requests")


@app.route("/ngo/collect/<request_id>", methods=["POST"])
def ngo_mark_collected(request_id):
    if session.get("user_role") != "ngo":
        return redirect("/login")

    request_collection.update_one(
        {"_id": ObjectId(request_id)},
        {"$set": {"collection_status": "Collected"}}
    )
    req = request_collection.find_one({"_id": ObjectId(request_id)})
    medicine = donation_collection.find_one({"_id": req["medicine_id"]})

    # Send WhatsApp / notification (demo)
    print("📲 WhatsApp Notification")
    print(f"NGO has collected medicine: {medicine['medicine_name']}")
    print(f"Quantity: {req['quantity']}")
    print(f"NGO: {req['ngo_email']}")

    return redirect("/ngo/requests/approved")


@app.route("/admin/stock-history")
def admin_stock_history():
    if not session.get("admin_logged_in"):
        return redirect("/admin")

    logs = list(
        stock_history_collection.find().sort("timestamp", -1)
    )

    return render_template(
        "admin_stock_history.html",
        logs=logs
    )

@app.route("/login", methods=["GET", "POST"])
def user_login():
    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]

        user = donor_collection.find_one({"email": email})
        role = "donor"

        if not user:
            user = ngo_user_collection.find_one({"email": email})
            role = "ngo"

        if not user:
            return render_template(
                "login.html",
                error="User not found"
            )

        if not check_password_hash(user["password"], password):
            return render_template(
                "login.html",
                error="Invalid password"
            )

        # ✅ SUCCESS LOGIN
        session["user_email"] = email
        session["user_role"] = role

        if role == "donor":
            return redirect("/donor/home")
        else:
            return redirect("/ngo/dashboard")

    # ✅ THIS RUNS ONLY FOR GET REQUEST
    return render_template("login.html")


@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        email = request.form["email"]
        new_password = request.form["new_password"]

        hashed_password = generate_password_hash(new_password)

        # Donor password reset
        if donor_collection.find_one({"email": email}):
            donor_collection.update_one(
                {"email": email},
                {"$set": {"password": hashed_password}}
            )
            return redirect("/login")

        # NGO password reset
        if ngo_user_collection.find_one({"email": email}):
            ngo_user_collection.update_one(
                {"email": email},
                {"$set": {"password": hashed_password}}
            )
            return redirect("/login")

        # Email not found
        return render_template(
            "forgot_password.html",
            error="Email not found"
        )

    # ✅ ALWAYS return something for GET
    return render_template("forgot_password.html")

@app.route("/upload", methods=["GET"])
def upload_form():
    return render_template("upload.html")


from datetime import datetime

def get_priority_level(impact_score):
        if impact_score >= 70:
            return "High"
        elif impact_score >= 40:
            return "Medium"
        else:
            return "Low"

def ai_distribution_recommendation(impact_score):
    if impact_score >= 80:
        return "Distribute Immediately"
    elif impact_score >= 60:
        return "High Distribution Priority"
    elif impact_score >= 40:
        return "Normal Distribution"
    else:
        return "Low Priority Medicine"

def calculate_impact_score(expiry_date, quantity):
    score = 20  # base score

    # EXPIRY SCORE
    try:
        if expiry_date:
            expiry = datetime.strptime(expiry_date, "%m/%Y")
            months_left = (expiry.year - datetime.now().year) * 12 + (expiry.month - datetime.now().month)

            if months_left <= 6:
                score += 50
            elif months_left <= 12:
                score += 30
            else:
                score += 10
    except:
        score += 10  # safe fallback

    # QUANTITY SCORE
    if quantity >= 50:
        score += 30
    elif quantity >= 20:
        score += 20
    else:
        score += 10

    return score

from datetime import datetime

def is_expiring_soon(expiry_date):
    if not expiry_date:
        return False

    try:
        expiry = datetime.strptime(expiry_date, "%m/%Y")
        today = datetime.now()

        months_left = (expiry.year - today.year) * 12 + (expiry.month - today.month)

        return months_left <= 3
    except:
        return False

def get_ngo_priority():
    ngos = list(ngo_user_collection.find())

    if not ngos:
        return []   # 👈 IMPORTANT: return empty list, NOT string

    priority_order = {
        "High": 1,
        "Medium": 2,
        "Low": 3
    }

    recommended_ngos = []

    for ngo in ngos:
        recommended_ngos.append({
            "name": ngo.get("name") or ngo.get("ngo_name") or ngo.get("email", "Unknown NGO"),
            "priority": ngo.get("priority_level", "Medium")
        })

    # Sort NGOs by priority
    recommended_ngos.sort(
        key=lambda x: priority_order.get(x["priority"], 2)
    )

    return recommended_ngos

def send_whatsapp_notification(donor_phone, medicine_name, donation_id, priority):
    message = f"""
📦 Medicine Donation Confirmation

Thank you for your donation!

🧴 Medicine: {medicine_name}
🆔 Donation ID: {donation_id}
🚦 Priority: {priority}

🙏 Your support helps save lives.
    """

    # DEMO: Print message (simulating WhatsApp)
    print("📲 WhatsApp Notification Sent To:", donor_phone)
    print(message)

def send_ngo_notification(ngo_email, medicine_name, quantity, status):
    message = f"""
📢 NGO Request Status Update

Medicine: {medicine_name}
Quantity: {quantity}
Status: {status}

Thank you for your service.
- Medicine Donation System
    """

    # 📧 EMAIL (DEMO)
    print("📧 Email sent to:", ngo_email)
    print(message)

    # 📲 WHATSAPP (DEMO)
    print("📲 WhatsApp message sent to:", ngo_email)
    print(message)

# ================== LOCATION BASED LOGIC ==================
from math import radians, sin, cos, sqrt, atan2

def calculate_distance(lat1, lon1, lat2, lon2):
    R = 6371  # Earth radius in KM
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)

    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    c = 2 * atan2(sqrt(a), sqrt(1 - a))

    return round(R * c, 2)

def find_nearest_ngo(donor_lat, donor_lon):
    ngos = list(ngo_user_collection.find())

    nearest_ngo = None
    min_distance = float("inf")

    for ngo in ngos:
        if "latitude" not in ngo or "longitude" not in ngo:
            continue

        distance = calculate_distance(
            donor_lat,
            donor_lon,
            ngo["latitude"],
            ngo["longitude"]
        )

        if distance < min_distance:
            min_distance = distance
            nearest_ngo = ngo

    return nearest_ngo, min_distance

@app.route("/upload", methods=["POST"])
def upload():
    if session.get("user_role") != "donor":
        return redirect("/login")

    medicine_name = request.form["medicine_name"]
    donor_lat = float(request.form["donor_lat"])
    donor_lon = float(request.form["donor_lon"])
    manual_expiry = request.form.get("manual_expiry")
    image = request.files["image"]
    quantity = request.form["quantity"]

    # 🔗 Get donor details
    donor = donor_collection.find_one({"email": session.get("user_email")})

    # 📁 Save image first (temporary name)
    upload_folder = "static/uploads"
    os.makedirs(upload_folder, exist_ok=True)
    temp_image_path = os.path.join(upload_folder, image.filename)
    image.save(temp_image_path)

    # 🔍 OCR
    expiry_date = get_expiry_from_image(temp_image_path)
    if expiry_date is None:
        expiry_date = manual_expiry

    impact_score = calculate_impact_score(expiry_date, int(quantity))
    priority = get_priority_level(impact_score)
    expiry_alert = is_expiring_soon(expiry_date)

    ai_recommendation = ai_distribution_recommendation(impact_score)
    # 📦 Insert donation WITHOUT image path first
    data = {
        "medicine_name": medicine_name,
        "expiry_date": expiry_date,
        "quantity": int(quantity),   # current stock
        "donated_quantity": int(quantity),     # original donated amount
        "impact_score": impact_score,
        "priority": priority,
        "ai_recommendation": ai_recommendation,
        "expiry_alert": expiry_alert,
        "status": "Stored",
        "created_at": datetime.now(),

         # 📍 DONOR LOCATION (ADD HERE)
        "donor_lat": donor_lat,
        "donor_lon": donor_lon,

        # 🔗 Donor linkage
        "donor_email": donor["email"],
        "donor_name": donor["name"],
        "donor_phone": donor["phone"],

        # placeholders
        "medicine_image": "",
        "ngo_email": None,
        "review": ""
    }

    result = donation_collection.insert_one(data)

    donation_id = str(result.inserted_id)

    # 📍 FIND NEAREST NGO
    nearest_ngo, distance_km = find_nearest_ngo(donor_lat, donor_lon)
    if nearest_ngo:
        donation_collection.update_one(
            {"_id": ObjectId(donation_id)},
            {"$set": {
                "assigned_ngo": nearest_ngo["ngo_name"],
                "ngo_email": nearest_ngo["email"],
                "distance_km": distance_km,
                "status": "Assigned"
            }}
        )

    # 🔳 Generate QR Code
    qr_folder = "static/qr_codes"
    os.makedirs(qr_folder, exist_ok=True)

    BASE_URL = "http://192.168.43.248:5000"

    qr_data = f"{BASE_URL}/scan?donation_id={donation_id}"


    qr_path = os.path.join(qr_folder, f"{donation_id}.png")
    qr = qrcode.make(qr_data)
    qr.save(qr_path)

    # 🖼️ Rename image using donation_id
    final_image_path = os.path.join(upload_folder, f"{donation_id}.jpg")
    os.rename(temp_image_path, final_image_path)

    # 🔄 Update document with image path
    donation_collection.update_one(
        {"_id": result.inserted_id},
        {"$set": {"medicine_image": final_image_path}}
    )

    send_whatsapp_notification(
        donor["phone"],
        medicine_name,
        donation_id,
        priority
    )

    return render_template(
        "result.html",
        donation_id=donation_id,
        impact_score=impact_score,
        priority=priority,
        qr_image=f"qr_codes/{donation_id}.png",
        assigned_ngo=nearest_ngo["ngo_name"] if nearest_ngo else None,
        distance_km=distance_km if nearest_ngo else None
    )

@app.route("/history")
def donation_history():
        if not session.get("admin_logged_in"):
            return redirect("/admin")

        search = request.args.get("search")

        if search:
            donations = donation_collection.find(
            {"medicine_name": {"$regex": search, "$options": "i"}}
        ).sort("created_at", -1)
        else:
           donations = donation_collection.find().sort("created_at", -1)


        return render_template("history.html", donations=donations, search=search)

@app.route("/admin/stock")
def admin_stock():
    medicines = donation_collection.find(
        { "quantity": { "$gt": 0 } }  # ONLY available stock
    )
    return render_template("admin_stock.html", medicines=medicines)

def send_whatsapp_expiry_alert(expiring_medicines):
    if not expiring_medicines:
        return

    print("\n⚠️ EXPIRY ALERTS ⚠️")
    for med in expiring_medicines:
        name = med.get("medicine_name", "Unknown Medicine")
        expiry = med.get("expiry_date", "Unknown Expiry")
        print(f"Medicine: {name} | Expiry: {expiry}")

from collections import Counter

@app.route("/dashboard")
def dashboard():
    # 🔐 Allow ADMIN or DONOR only
    if not session.get("admin_logged_in") and session.get("user_role") != "donor":
        return redirect("/login")

    # ===== ANALYTICS LOGIC (Charts) =====

    high_count = donation_collection.count_documents({"priority": "High"})
    medium_count = donation_collection.count_documents({"priority": "Medium"})
    low_count = donation_collection.count_documents({"priority": "Low"})

    from collections import Counter
    donations = donation_collection.find()
    date_counter = Counter()

    for d in donations:
        if "created_at" in d:
            date = d["created_at"].strftime("%Y-%m-%d")
            date_counter[date] += 1

    dates = list(date_counter.keys())
    counts = list(date_counter.values())

    expiring_count = donation_collection.count_documents({"expiry_alert": True})
    expiring_medicines = get_expiring_medicines(90)

    ngo_priority = get_ngo_priority()

    return render_template(
        "dashboard.html",
        high_count=high_count,
        medium_count=medium_count,
        low_count=low_count,
        expiring_count=expiring_count,
        expiring_medicines=list(expiring_medicines),
        ngo_priority=ngo_priority,
        dates=dates,
        counts=counts
    )

from datetime import timedelta

def get_expiring_medicines(days=30):
    today = datetime.now()
    upcoming = today + timedelta(days=days)

    expiring = []

    for d in donation_collection.find({"expiry_date": {"$ne": None}}):
        try:
            exp = datetime.strptime(d["expiry_date"], "%m/%Y")
            if today <= exp <= upcoming:
                expiring.append(d)
        except:
            pass

    return expiring

@app.route("/donor/dashboard")
def donor_dashboard():
    if session.get("user_role") != "donor":
        return redirect("/login")

    donor_email = session.get("user_email")

    donations = list(donation_collection.find(
        {"donor_email": donor_email}
    ).sort("created_at", -1))

    total_donations = len(donations)

    # 🏅 BADGE LOGIC
    if total_donations >= 11:
        badge = "Gold Donor"
        badge_icon = "🥇"
        badge_color = "#f4c430"

    elif total_donations >= 6:
        badge = "Silver Donor"
        badge_icon = "🥈"
        badge_color = "#c0c0c0"

    elif total_donations >= 3:
        badge = "Bronze Donor"
        badge_icon = "🥉"
        badge_color = "#cd7f32"

    else:
        badge = "New Donor"
        badge_icon = "🤍"
        badge_color = "#999"

    return render_template(
        "donor_dashboard.html",
        donations=donations,
        total_donations=total_donations,
        badge=badge,
        badge_icon=badge_icon,
        badge_color=badge_color
    )

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
from flask import send_file
import qrcode, os
from datetime import datetime

@app.route("/donor/certificate")
def donor_certificate():
    if session.get("user_role") != "donor":
        return redirect("/login")

    donor = donor_collection.find_one({"email": session.get("user_email")})
    total_donations = donation_collection.count_documents({"donor_email": donor["email"]})

    # BADGE
    if total_donations >= 11:
        badge = "Gold Donor"
    elif total_donations >= 6:
        badge = "Silver Donor"
    elif total_donations >= 3:
        badge = "Bronze Donor"
    else:
        badge = "New Donor"

    # PATHS
    cert_folder = os.path.join(app.root_path, "static", "certificates")
    qr_folder = os.path.join(app.root_path, "static", "qr_codes")
    sign_path = os.path.join(app.root_path, "static", "signatures", "admin_sign.png")

    os.makedirs(cert_folder, exist_ok=True)
    os.makedirs(qr_folder, exist_ok=True)

    filename = f"{donor['name'].replace(' ', '_')}_certificate.pdf"
    file_path = os.path.join(cert_folder, filename)

    # SERIAL NUMBER
    year = datetime.now().year
    serial_no = f"MDNS-{year}-{donor['_id']}-{total_donations}"

    # CREATE QR CODE
    qr_data = f"Verified Donation | Donor: {donor['name']} | Total Donations: {total_donations}"
    qr_img = qrcode.make(qr_data)
    qr_path = os.path.join(qr_folder, "qr_temp.png")
    qr_img.save(qr_path)
    
    # CREATE PDF (ALWAYS REGENERATE)
    c = canvas.Canvas(file_path, pagesize=A4)
    width, height = A4

    # BORDER
    c.setLineWidth(5)
    c.rect(40, 40, width - 80, height - 80)

    # SERIAL NUMBER (TOP RIGHT)
    c.setFont("Helvetica", 10)
    c.drawRightString(
    width - 60,
    height - 70,
    f"Certificate No: {serial_no}")

    # TITLE
    c.setFont("Helvetica-Bold", 28)
    c.drawCentredString(width / 2, height - 120, "Certificate of Appreciation")

    # BODY
    c.setFont("Helvetica", 16)
    c.drawCentredString(width / 2, height - 200, "This certificate is proudly presented to")

    c.setFont("Helvetica-Bold", 22)
    c.drawCentredString(width / 2, height - 250, donor["name"])

    c.setFont("Helvetica", 16)
    c.drawCentredString(width / 2, height - 310, f"For donating medicines {total_donations} time(s)")
    c.drawCentredString(width / 2, height - 350, f"Donor Badge: {badge}")
    c.drawCentredString(width / 2, height - 420, f"Issued on: {datetime.now().strftime('%d %B %Y')}")

    # VERIFIED SEAL
    c.setFont("Helvetica-Bold", 16)
    c.setFillColorRGB(0.1, 0.6, 0.2)
    c.drawCentredString(width / 2, height - 470, "✔ VERIFIED NGO DONATION")
    c.setFillColorRGB(0, 0, 0)

    # ===== BOTTOM SECTION LAYOUT =====
    bottom_y = 140   # base alignment line

    # --- QR CODE (LEFT) ---
    c.drawImage(ImageReader(qr_path),80,bottom_y,110,110,mask='auto')
    c.setFont("Helvetica", 9)
    c.drawString(80, bottom_y - 15, f"Certificate ID: {serial_no}")
    c.drawString(80, bottom_y - 30, "NGO Coordinator")

    # --- ADMIN SIGNATURE (RIGHT) ---
    if os.path.exists(sign_path):
        c.drawImage(ImageReader(sign_path),width - 260,bottom_y + 25,150,45,mask='auto')
        c.setFont("Helvetica", 9)
        c.drawString(width - 245, bottom_y - 34, "System Administrator")

    # NGO STAMP
    #stamp_path = os.path.join(app.root_path, "static", "stamps", "ngo_stamp.png")
    #if os.path.exists(stamp_path):
     #   c.drawImage(ImageReader(stamp_path),
      #  width/2 - 70,   # center horizontally
       # 85,             # bottom area
        #140, 140,       # stamp size
        #mask='auto')

    c.save()

    # CLEAN TEMP QR
    if os.path.exists(qr_path):
        os.remove(qr_path)

    return send_file(file_path, as_attachment=True)



@app.route("/my/donations")
def my_donations():
    if session.get("user_role") != "donor":
        return redirect("/login")

    donations = donation_collection.find(
        {"donor_email": session.get("user_email")}
    ).sort("created_at", -1)

    return render_template(
        "my_donations.html",
        donations=donations
    )


@app.route("/donor/history")
def donor_history():
    if session.get("user_role") != "donor":
        return redirect("/login")

    donations = donation_collection.find(
        {"donor_email": session.get("user_email")}
    ).sort("created_at", -1)

    return render_template(
        "donor_history.html",
        donations=donations
    )


@app.route("/donor/home")
def donor_home():
    if session.get("user_role") != "donor":
        return redirect("/login")

    return render_template("donor_home.html")

from werkzeug.utils import secure_filename

@app.route("/donor/profile/edit", methods=["GET", "POST"])
def donor_edit_profile():
    if session.get("user_role") != "donor":
        return redirect("/login")

    donor = donor_collection.find_one(
        {"email": session.get("user_email")}
    )

    if request.method == "POST":
        name = request.form["name"]
        phone = request.form["phone"]
        location = request.form["location"]

        update_data = {
            "name": name,
            "phone": phone,
            "location": location
        }

        # 🗑 REMOVE PHOTO
        if request.form.get("remove_photo"):
            donor_collection.update_one(
                {"email": donor["email"]},
                {"$unset": {"profile_photo": ""}}
            )
            return redirect("/donor/profile")

        # 📸 PROFILE PHOTO UPLOAD + AUTO CROP
        photo = request.files.get("profile_photo")
        if photo and photo.filename != "":
            filename = secure_filename(photo.filename)
            photo_folder = "static/profile_photos"
            os.makedirs(photo_folder, exist_ok=True)

            path = os.path.join(photo_folder, filename)
            photo.save(path)

            # ✂ AUTO-CROP CENTER SQUARE
            img = Image.open(path)
            w, h = img.size
            min_edge = min(w, h)

            left = (w - min_edge) / 2
            top = (h - min_edge) / 2
            right = (w + min_edge) / 2
            bottom = (h + min_edge) / 2

            img = img.crop((left, top, right, bottom))
            img = img.resize((300, 300))
            img.save(path)

            update_data["profile_photo"] = path

        donor_collection.update_one(
            {"email": donor["email"]},
            {"$set": update_data}
        )

        return redirect("/donor/profile")

    return render_template(
        "donor_edit_profile.html",
        donor=donor
    )


@app.route("/donor/profile")
def donor_profile():
    if session.get("user_role") != "donor":
        return redirect("/login")

    donor = donor_collection.find_one(
        {"email": session.get("user_email")}
    )

    donations = list(
        donation_collection.find(
            {"donor_email": donor["email"]}
        ).sort("created_at", -1)
    )

    total_donations = len(donations)
    last_donation = donations[0]["created_at"] if total_donations > 0 else None

        # 🏅 BADGE + PROGRESS LOGIC
    if total_donations >= 11:
        badge = "Gold Donor 🥇"
        badge_color = "#f4c430"
        next_badge = None
        progress_percent = 100
        remaining = 0

    elif total_donations >= 6:
        badge = "Silver Donor 🥈"
        badge_color = "#c0c0c0"
        next_badge = "Gold Donor 🥇"
        progress_percent = int((total_donations / 11) * 100)
        remaining = 11 - total_donations

    elif total_donations >= 3:
        badge = "Bronze Donor 🥉"
        badge_color = "#cd7f32"
        next_badge = "Silver Donor 🥈"
        progress_percent = int(((total_donations - 3) / 3) * 100)
        remaining = 6 - total_donations

    else:
        badge = "New Donor 🤍"
        badge_color = "#888"
        next_badge = "Bronze Donor 🥉"
        progress_percent = int((total_donations / 3) * 100)
        remaining = 3 - total_donations

    return render_template(
    "donor_profile.html",
    donor=donor,
    total_donations=total_donations,
    last_donation=last_donation,
    badge=badge,
    badge_color=badge_color,
    next_badge=next_badge,
    progress_percent=progress_percent,
    remaining=remaining
    )

# -------------------- NGO DASHBOARD --------------------
@app.route("/ngo/dashboard")
def ngo_dashboard():
    if session.get("user_role") != "ngo":
        return redirect("/login")
    total_medicines = donation_collection.count_documents({"status": {"$in": ["Stored", "Available","Assigned"]},"quantity": {"$gt": 0}})
    total_requests = request_collection.count_documents({"ngo_email": session["user_email"]})
    approved_requests = request_collection.count_documents({"status": "Approved"})
    medicines_distributed = request_collection.count_documents({"ngo_email": session["user_email"],"status": "Delivered"})

    return render_template(
        "ngo_dashboard.html",
        total_medicines=total_medicines,
        total_requests=total_requests,
        approved_requests=approved_requests,
        medicines_distributed=medicines_distributed
    )

from bson.objectid import ObjectId

@app.route("/ngo/request/<medicine_id>", methods=["GET", "POST"])
def ngo_request_medicine(medicine_id):
    if session.get("user_role") != "ngo":
        return redirect("/login")

    ngo_email = session.get("user_email")

    # Fetch medicine
    medicine = donation_collection.find_one(
        {"_id": ObjectId(medicine_id)}
    )

    if not medicine:
        return redirect("/ngo/medicines")

    # 🔒 DB-LEVEL DUPLICATE CHECK (VERY IMPORTANT)
    existing_request = request_collection.find_one({
        "ngo_email": ngo_email,
        "medicine_id": ObjectId(medicine_id),
        "status": {"$in": ["Pending", "Approved"]}
    })

    if existing_request:
        # Already requested → block silently
        return redirect("/ngo/medicines")

    if request.method == "POST":
        request_collection.insert_one({
            "ngo_email": ngo_email,
            "medicine_id": ObjectId(medicine_id),  # ✅ ObjectId
            "medicine_name": medicine["medicine_name"],
            "quantity": int(request.form["quantity"]),
            "purpose": request.form["purpose"],
            "priority": request.form["priority"],
            "status": "Pending",
            "collection_method": None,        # pickup / drop / courier
            "collection_address": None,
            "collection_status": "Not Assigned",  # Not Assigned / Pending / Collected

            "requested_at": datetime.now()
        })

        # Better UX
        return redirect("/ngo/requests/status")

    return render_template(
        "ngo_request_medicine.html",
        medicine=medicine
    )
    
@app.route("/ngo/requests/status")
def ngo_request_status():
    if session.get("user_role") != "ngo":
        return redirect("/login")

    ngo_email = session.get("user_email")

    requests = list(
        request_collection.find(
            {"ngo_email": ngo_email}
        ).sort("requested_at", -1)
    )

    return render_template(
        "ngo_request_status.html",
        requests=requests
    )

@app.route("/ngo/received")
def ngo_received_donations():
    if session.get("user_role") != "ngo":
        return redirect("/login")

    ngo_email = session.get("user_email")

    received = list(
        request_collection.find(
            {
                "ngo_email": ngo_email,
                "status": "Delivered"
            }
        ).sort("requested_at", -1)
    )

    return render_template(
        "ngo_received_donations.html",
        received=received
    )

@app.route("/ngo/impact")
def ngo_impact_report():
    if session.get("user_role") != "ngo":
        return redirect("/login")

    ngo_email = session.get("user_email")

    # Total requests made by NGO
    total_requests = request_collection.count_documents({
        "ngo_email": ngo_email
    })

    # Total delivered requests
    delivered_requests = list(
        request_collection.find({
            "ngo_email": ngo_email,
            "status": "Delivered"
        })
    )

    total_medicines_received = len(delivered_requests)

    # Total quantity distributed
    total_quantity_distributed = sum(
        req.get("quantity", 0) for req in delivered_requests
    )

    # ✅ ALWAYS define these
    pending_requests = max(total_requests - total_medicines_received, 0)

    # Success rate
    success_rate = 0
    if total_requests > 0:
        success_rate = round((total_medicines_received / total_requests) * 100, 2)

    return render_template(
        "ngo_impact_report.html",
        total_requests=total_requests,
        total_medicines_received=total_medicines_received,
        total_quantity_distributed=total_quantity_distributed,
        success_rate=success_rate,
        pending_requests=pending_requests
    )

@app.route("/ngo/requests/approved")
def ngo_approved_requests():
    if session.get("user_role") != "ngo":
        return redirect("/login")

    ngo_email = session.get("user_email")

    approved = list(
        request_collection.find({
            "ngo_email": ngo_email,
            "status": "Approved"
        }).sort("requested_at", -1)
    )

    return render_template(
        "ngo_approved_requests.html",
        requests=approved
    )

@app.route("/ngo/profile")
def ngo_profile():
    if session.get("user_role") != "ngo":
        return redirect("/login")

    ngo = ngo_user_collection.find_one({
        "email": session.get("user_email")
    })

    if ngo is None:
        return redirect("/login")

    return render_template("ngo_profile.html", ngo=ngo)


@app.route("/ngo/profile/edit", methods=["GET", "POST"])
def ngo_edit_profile():
    if session.get("user_role") != "ngo":
        return redirect("/login")

    ngo = ngo_user_collection.find_one({
        "email": session.get("user_email")
    })

    if request.method == "POST":
        ngo_user_collection.update_one(
            {"email": session["user_email"]},
            {"$set": {
                "ngo_name": request.form["ngo_name"],
                "ngo_type": request.form["ngo_type"],
                "phone": request.form["phone"],
                "location": request.form["location"],
                "priority_level": request.form.get("priority_level", "Medium")
            }}
        )
        return redirect("/ngo/profile")

    return render_template("ngo_edit_profile.html", ngo=ngo)


# -------------------- NGO VIEW MEDICINES --------------------
@app.route("/ngo/review/<donation_id>", methods=["POST"])
def ngo_review(donation_id):
    if session.get("user_role") != "ngo":
        return redirect("/login")

    review = request.form["review"]

    from bson.objectid import ObjectId
    donation_collection.update_one(
        {"_id": ObjectId(donation_id)},
        {
            "$set": {
                "review": review,
            }
        }
    )
    return redirect("/ngo/dashboard")


@app.route("/scan")
def scan_page():
    donation_id = request.args.get("donation_id")

    donation = None
    if donation_id:
        try:
            donation = donation_collection.find_one(
                {"_id": ObjectId(donation_id)}
            )
        except:
            donation = None

    return render_template(
        "scan_result.html",
        donation=donation,
        donation_id=donation_id
    )

from bson.objectid import ObjectId

@app.route("/scan/result", methods=["POST"])
def scan_result():
    donation_id = request.form.get("donation_id")

    try:
        donation = donation_collection.find_one({"_id": ObjectId(donation_id)})
    except:
        donation = None

    return render_template("scan_result.html", donation=donation, donation_id=donation_id)


@app.route("/donor/change-password", methods=["GET", "POST"])
def donor_change_password():
    if session.get("user_role") != "donor":
        return redirect("/login")

    donor = donor_collection.find_one({"email": session.get("user_email")})

    if request.method == "POST":
        old_password = request.form["old_password"]
        new_password = request.form["new_password"]
        confirm_password = request.form["confirm_password"]

        if not check_password_hash(donor["password"], old_password):
            return render_template(
                "donor_change_password.html",
                error="Old password is incorrect"
            )

        if new_password != confirm_password:
            return render_template(
                "donor_change_password.html",
                error="Passwords do not match"
            )

        donor_collection.update_one(
            {"email": session.get("user_email")},
            {"$set": {"password": generate_password_hash(new_password)}}
        )
        return redirect("/donor/profile")
    return render_template("donor_change_password.html")

@app.route("/ngo/medicines")
def ngo_view_medicines():
    if session.get("user_role") != "ngo":
        return redirect("/login")

    ngo_email = session.get("user_email")

    medicines = list(donation_collection.find({
            "status": {"$in": ["Stored", "Available","Assigned"]},
            "quantity": {"$gt": 0}
        }))

    # Fetch requests made by this NGO
    requests = list(
        request_collection.find({"ngo_email": ngo_email })
    )

    # Map: medicine_id -> request info
    request_map = {}

    for req in requests:
        mid = str(req["medicine_id"])

        # Track only active requests (Pending / Approved)
        if req["status"] in ["Pending", "Approved"]:
            request_map[mid] = {
                "status": req["status"],
                "requested_at": req.get("requested_at")
            }

    # Attach status to medicines
    for med in medicines:
        mid = str(med["_id"])
        if mid in request_map:
            med["requested"] = True
            med["request_status"] = request_map[mid]["status"]
            med["requested_at"] = request_map[mid]["requested_at"]
        else:
            med["requested"] = False
            med["request_status"] = None
            med["requested_at"] = None

    # 🔥 SORT: requested medicines first (latest on top)
    medicines.sort(
        key=lambda m: (
            not m["requested"],                    # requested first
            -(m["requested_at"].timestamp() if m["requested_at"] else 0)
        )
    )

    return render_template(
        "ngo_view_medicines.html",
        medicines=medicines
    )
@app.route("/admin/fix-old-donors")
def fix_old_donor_details():
    if not session.get("admin_logged_in"):
        return redirect("/admin")

    updated_count = 0

    for med in donation_collection.find({
        "$or": [
            {"donor_name": ""},
            {"donor_phone": ""},
            {"donor_name": None},
            {"donor_phone": None}
        ]
    }):

        donor_email = med.get("donor_email")
        if not donor_email:
            continue

        donor = donor_collection.find_one({"email": donor_email})
        if not donor:
            continue

        donation_collection.update_one(
            {"_id": med["_id"]},
            {"$set": {
                "donor_name": donor.get("name"),
                "donor_phone": donor.get("phone")
            }}
        )
        updated_count += 1

    return f"Updated {updated_count} donation records"

@app.route("/admin/fix-map-links")
def fix_map_links():
    if not session.get("admin_logged_in"):
        return redirect("/admin")

    updated = 0

    for req in request_collection.find({"status": "Approved"}):
        medicine = donation_collection.find_one({"_id": req["medicine_id"]})
        if not medicine:
            continue

        lat = medicine.get("donor_lat")
        lon = medicine.get("donor_lon")

        if lat and lon:
            map_link = f"https://www.google.com/maps?q={lat},{lon}"
            request_collection.update_one(
                {"_id": req["_id"]},
                {"$set": {"map_link": map_link}}
            )
            updated += 1

    return f"Updated {updated} requests with map links"

@app.route("/qr/<donation_id>")
def view_qr(donation_id):
    qr_path = f"static/qr_codes/{donation_id}.png"

    if not os.path.exists(qr_path):
        return "QR Code not found", 404

    return render_template(
        "view_qr.html",
        donation_id=donation_id,
        qr_image=f"qr_codes/{donation_id}.png"
    )


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

if __name__ == "__main__":
    app.run(host="0.0.0.0",port=5000, debug=True)

