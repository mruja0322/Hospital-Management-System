from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
import mysql.connector
from datetime import date, datetime, timedelta
import json
import os

app = Flask(__name__)
CORS(app)

DB_CONFIG = {
    "host":     "localhost",
    "user":     "root",
    "password": os.environ.get("DB_PASSWORD", ""),
    "database": "medicore_hms",
    "autocommit": False
}

def get_db():
    if not DB_CONFIG["password"]:
        raise RuntimeError("Set the DB_PASSWORD environment variable before connecting to MySQL.")
    return mysql.connector.connect(**DB_CONFIG)

def _make_serializable(obj):
    """Recursively convert non-JSON-serializable objects."""
    if isinstance(obj, dict):
        return {k: _make_serializable(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_make_serializable(i) for i in obj]
    if isinstance(obj, (datetime, date)):
        return obj.isoformat().split('T')[0]  # always return YYYY-MM-DD
    if isinstance(obj, timedelta):
        # Convert timedelta (MySQL TIME) to HH:MM string
        total_seconds = int(obj.total_seconds())
        h = total_seconds // 3600
        m = (total_seconds % 3600) // 60
        return f"{h:02d}:{m:02d}"
    return obj

def query(sql, params=(), one=False, commit=False):
    db = get_db()
    cur = db.cursor(dictionary=True)
    cur.execute(sql, params)
    if commit:
        db.commit()
        result = {"affected": cur.rowcount}
    elif one:
        result = cur.fetchone()
    else:
        result = cur.fetchall()
    cur.close()
    db.close()
    result = _make_serializable(result)
    return result

def today():
    return date.today().isoformat()

def now_str():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')

# ── ENUM helpers ───────────────────────────────────────────────
import re as _re

def get_enum_values(cur, table, column):
    """Return list of allowed ENUM values for a column, or [] on error."""
    try:
        cur.execute(f"SHOW COLUMNS FROM `{table}` LIKE %s", (column,))
        row = cur.fetchone()
        if row:
            return [v.strip("'") for v in _re.findall(r"'([^']*)'", row.get('Type', ''))]
    except Exception:
        pass
    return []

def best_enum(cur, table, column, preferred, fallback=''):
    """Pick the best matching ENUM value; case-insensitive, then first available."""
    vals = get_enum_values(cur, table, column)
    if not vals:
        return preferred          # table might not have ENUM, just pass through
    # exact match first
    if preferred in vals:
        return preferred
    # case-insensitive match
    low = preferred.lower()
    for v in vals:
        if v.lower() == low:
            return v
    # first value as last resort
    return vals[0] if vals else fallback

def col_exists(cur, table, column):
    """Check whether a column exists in a table."""
    try:
        cur.execute(f"SHOW COLUMNS FROM `{table}` LIKE %s", (column,))
        return cur.fetchone() is not None
    except Exception:
        return False

@app.route('/')
def index():
    return render_template('index.html')

# ══ AUTH ══════════════════════════════════════════════════════
@app.route('/api/login', methods=['POST'])
def login():
    data = request.json
    username = data.get('username', '').strip()
    password = data.get('password', '').strip()
    role     = data.get('role', '').strip()

    if not username or not password:
        return jsonify({"error": "Username and password required"}), 400

    user = query(
        "SELECT * FROM users WHERE username=%s AND password=%s AND role=%s",
        (username, password, role), one=True
    )
    if not user:
        return jsonify({"error": "Invalid credentials"}), 401

    profile = {}
    if role == 'doctor':
        doc = query("SELECT * FROM doctors WHERE user_id=%s", (user['user_id'],), one=True)
        if doc:
            profile['doctor_id'] = doc['doctor_id']
            profile['name']      = doc['full_name']
    elif role == 'patient':
        pat = query("SELECT * FROM patients WHERE user_id=%s OR patient_id=%s",
                    (user['user_id'], username), one=True)
        if pat:
            profile['patient_id'] = pat['patient_id']
            profile['name'] = pat['first_name'] + ' ' + pat['last_name']
    else:
        profile['name'] = username.split('@')[0].replace('.', ' ').title()

    return jsonify({
        "user_id":  user['user_id'],
        "username": user['username'],
        "role":     user['role'],
        **profile
    })


# ══ SELF-REGISTRATION ══════════════════════════════════════════
@app.route('/api/register', methods=['POST'])
def register():
    data = request.json
    role  = data.get('role', 'patient')
    email = data.get('email', '').strip()
    username = data.get('username', email).strip()
    password = data.get('password', 'demo-patient-only').strip()

    if not username:
        return jsonify({"error": "Username/email required"}), 400

    existing = query("SELECT user_id FROM users WHERE username=%s", (username,), one=True)
    if existing:
        return jsonify({"error": "Email already registered. Please sign in."}), 409

    db = get_db()
    cur = db.cursor(dictionary=True)
    try:
        cur.execute(
            "INSERT INTO users (username, password, role) VALUES (%s, %s, %s)",
            (username, password, role)
        )
        user_id = cur.lastrowid

        if role == 'patient':
            fn = data.get('first_name', '').strip()
            ln = data.get('last_name',  '').strip()
            if not fn or not ln:
                db.rollback()
                return jsonify({"error": "First and last name required"}), 400

            cur.execute("SELECT COALESCE(MAX(CAST(SUBSTRING(patient_id,4) AS UNSIGNED)),0)+1 AS nxt FROM patients WHERE patient_id LIKE 'PAT%'")
            nxt = cur.fetchone()['nxt']
            new_id = f"PAT{str(nxt).zfill(3)}"

            patient_type = best_enum(cur, 'patients', 'patient_type', 'Outpatient', 'Outpatient')
            status_val   = best_enum(cur, 'patients', 'status',       'outpatient', 'outpatient')
            has_pw_col   = col_exists(cur, 'patients', 'password_plain')
            has_ward_col = col_exists(cur, 'patients', 'ward')

            assigned_doc = data.get('assigned_doctor') or None

            base_cols = "(patient_id, user_id, first_name, last_name, age, gender, blood_group, phone, email, assigned_doctor, patient_type, status, admission_date"
            base_vals = [new_id, user_id, fn, ln,
                         data.get('age') or None, data.get('gender', 'Male'),
                         data.get('blood_group', 'O+'), data.get('phone', ''),
                         email, assigned_doc, patient_type, status_val, today()]
            extra_cols, extra_vals = [], []
            if has_ward_col:
                extra_cols.append('ward'); extra_vals.append(None)
            if has_pw_col:
                extra_cols.append('password_plain'); extra_vals.append(password)

            col_str = base_cols + ((',' + ','.join(extra_cols)) if extra_cols else '') + ')'
            ph_str  = ','.join(['%s'] * (len(base_vals) + len(extra_vals)))
            cur.execute(f"INSERT INTO patients {col_str} VALUES ({ph_str})",
                        base_vals + extra_vals)

            db.commit()
            cur.close(); db.close()
            return jsonify({
                "message":    f"Registration successful! Your Patient ID is {new_id}",
                "patient_id": new_id,
                "user_id":    user_id
            }), 201

        elif role == 'doctor':
            fn        = data.get('first_name', '').strip()
            ln        = data.get('last_name',  '').strip()
            full_name = data.get('full_name') or f"Dr. {fn} {ln}"

            cur.execute("SELECT COALESCE(MAX(CAST(SUBSTRING(doctor_id,2) AS UNSIGNED)),0)+1 AS nxt FROM doctors WHERE doctor_id LIKE 'D%'")
            nxt = cur.fetchone()['nxt']
            new_id = f"D{str(nxt).zfill(2)}"

            # Detect correct ENUM value for doctor status
            doc_status = best_enum(cur, 'doctors', 'status', 'Active', 'Active')

            cur.execute("""
                INSERT INTO doctors
                  (doctor_id, user_id, full_name, specialization, qualification,
                   experience_yrs, consultation_fee, phone, email, status, available_days)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, (
                new_id, user_id, full_name,
                data.get('specialization', 'General Medicine'),
                data.get('qualification', 'MBBS'),
                data.get('experience_yrs', 0),
                data.get('consultation_fee', 500),
                data.get('phone', ''),
                email,
                doc_status,
                data.get('available_days', 'Mon,Wed,Fri')
            ))

            db.commit()
            cur.close(); db.close()
            return jsonify({
                "message":   "Registration submitted.",
                "doctor_id": new_id,
                "user_id":   user_id
            }), 201

        else:
            db.rollback()
            cur.close(); db.close()
            return jsonify({"error": "Self-registration only allowed for patient or doctor roles"}), 400

    except Exception as e:
        db.rollback()
        cur.close(); db.close()
        return jsonify({"error": str(e)}), 500


# ══ DOCTORS ═══════════════════════════════════════════════════
@app.route('/api/doctors', methods=['GET'])
def get_doctors():
    docs = query("""
        SELECT d.*, dep.name AS dept_name,
               GROUP_CONCAT(ds.slot_time ORDER BY ds.slot_time) AS slots
        FROM doctors d
        LEFT JOIN departments dep ON d.dept_id = dep.dept_id
        LEFT JOIN doctor_slots ds ON d.doctor_id = ds.doctor_id AND ds.is_active=1
        GROUP BY d.doctor_id
    """)
    for d in docs:
        d['slots'] = d['slots'].split(',') if d['slots'] else []
        d['avail'] = d['available_days'].split(',') if d['available_days'] else []
    return jsonify(docs)

@app.route('/api/doctors', methods=['POST'])
def add_doctor():
    d = request.json
    if not d.get('full_name'):
        return jsonify({"error": "Full name required"}), 400

    row = query("SELECT COALESCE(MAX(CAST(SUBSTRING(doctor_id,2) AS UNSIGNED)),0)+1 AS nxt FROM doctors WHERE doctor_id LIKE 'D%'", one=True)
    new_id = f"D{str(row['nxt']).zfill(2)}"

    query("""INSERT INTO doctors
             (doctor_id, full_name, specialization, qualification,
              experience_yrs, consultation_fee, phone, email, status, available_days)
             VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
          (new_id, d['full_name'], d.get('specialization'), d.get('qualification'),
           d.get('experience_yrs', 0), d.get('consultation_fee', 500),
           d.get('phone'), d.get('email'),
           d.get('status', 'Active'), d.get('available_days', 'Mon,Wed,Fri')),
          commit=True)

    for slot in d.get('slots', []):
        query("INSERT INTO doctor_slots (doctor_id, slot_time) VALUES (%s,%s)",
              (new_id, slot), commit=True)

    return jsonify({"message": f"Doctor added! ID: {new_id}", "doctor_id": new_id}), 201

@app.route('/api/doctors/<doctor_id>', methods=['PUT'])
def update_doctor(doctor_id):
    d = request.json
    query("""UPDATE doctors SET
             full_name=%s, specialization=%s, consultation_fee=%s,
             status=%s, available_days=%s
             WHERE doctor_id=%s""",
          (d['full_name'], d.get('specialization'), d.get('consultation_fee'),
           d.get('status', 'Active'), d.get('available_days'), doctor_id),
          commit=True)
    return jsonify({"message": "Doctor updated"})

@app.route('/api/doctors/<doctor_id>', methods=['DELETE'])
def delete_doctor(doctor_id):
    query("DELETE FROM doctors WHERE doctor_id=%s", (doctor_id,), commit=True)
    return jsonify({"message": "Doctor removed"})

@app.route('/api/doctors/<doctor_id>/slots', methods=['GET'])
def get_doctor_slots(doctor_id):
    slots = query("SELECT * FROM doctor_slots WHERE doctor_id=%s AND is_active=1", (doctor_id,))
    return jsonify(slots)


# ══ PATIENTS ══════════════════════════════════════════════════
@app.route('/api/patients', methods=['GET'])
def get_patients():
    doctor_id = request.args.get('doctor_id')
    status    = request.args.get('status')

    sql = """
        SELECT p.*, d.full_name AS doctor_name, d.specialization
        FROM patients p
        LEFT JOIN doctors d ON p.assigned_doctor = d.doctor_id
    """
    conditions, params = [], []
    if doctor_id:
        conditions.append("p.assigned_doctor=%s"); params.append(doctor_id)
    if status:
        conditions.append("p.status=%s"); params.append(status)
    if conditions:
        sql += " WHERE " + " AND ".join(conditions)

    return jsonify(query(sql, tuple(params)))

@app.route('/api/patients', methods=['POST'])
def add_patient():
    p = request.json
    if not p.get('first_name') or not p.get('last_name'):
        return jsonify({"error": "First and last name required"}), 400

    db = get_db()
    cur = db.cursor(dictionary=True)
    try:
        cur.execute("SELECT COALESCE(MAX(CAST(SUBSTRING(patient_id,4) AS UNSIGNED)),0)+1 AS nxt FROM patients WHERE patient_id LIKE 'PAT%'")
        new_id = f"PAT{str(cur.fetchone()['nxt']).zfill(3)}"

        ptype       = best_enum(cur, 'patients', 'patient_type', p.get('patient_type','Outpatient'), 'Outpatient')
        status_val  = best_enum(cur, 'patients', 'status',       p.get('status','outpatient'),      'outpatient')
        has_pw_col  = col_exists(cur, 'patients', 'password_plain')
        has_ward_col= col_exists(cur, 'patients', 'ward')

        base_cols = "(patient_id, first_name, last_name, age, gender, blood_group, phone, email, assigned_doctor, patient_type, status, admission_date"
        base_vals = [new_id, p['first_name'], p['last_name'],
                     p.get('age'), p.get('gender'), p.get('blood_group'),
                     p.get('phone'), p.get('email'), p.get('assigned_doctor'),
                     ptype, status_val, p.get('admission_date', today())]
        extra_cols, extra_vals = [], []
        if has_ward_col:
            extra_cols.append('ward'); extra_vals.append(p.get('ward') or None)
        if has_pw_col:
            extra_cols.append('password_plain'); extra_vals.append('demo-patient-only')

        col_str = base_cols + ((',' + ','.join(extra_cols)) if extra_cols else '') + ')'
        ph_str  = ','.join(['%s'] * (len(base_vals) + len(extra_vals)))
        cur.execute(f"INSERT INTO patients {col_str} VALUES ({ph_str})",
                    base_vals + extra_vals)
        db.commit()
        cur.close(); db.close()
        return jsonify({"message": f"Patient registered! ID: {new_id}", "patient_id": new_id}), 201
    except Exception as e:
        db.rollback()
        cur.close(); db.close()
        return jsonify({"error": str(e)}), 500

@app.route('/api/patients/<patient_id>', methods=['GET'])
def get_patient(patient_id):
    p = query("SELECT * FROM patients WHERE patient_id=%s", (patient_id,), one=True)
    if not p:
        return jsonify({"error": "Not found"}), 404
    return jsonify(p)

@app.route('/api/patients/<patient_id>', methods=['PUT'])
def update_patient(patient_id):
    p = request.json
    query("""UPDATE patients SET
             first_name=%s, last_name=%s, age=%s, gender=%s, blood_group=%s,
             phone=%s, email=%s, assigned_doctor=%s, status=%s, ward=%s
             WHERE patient_id=%s""",
          (p['first_name'], p['last_name'], p.get('age'), p.get('gender'),
           p.get('blood_group'), p.get('phone'), p.get('email'),
           p.get('assigned_doctor'), p.get('status'), p.get('ward'),
           patient_id),
          commit=True)
    return jsonify({"message": "Patient updated"})

@app.route('/api/patients/<patient_id>', methods=['DELETE'])
def delete_patient(patient_id):
    query("DELETE FROM patients WHERE patient_id=%s", (patient_id,), commit=True)
    return jsonify({"message": "Patient deleted"})


# ══ APPOINTMENTS ═══════════════════════════════════════════════
@app.route('/api/appointments', methods=['GET'])
def get_appointments():
    doctor_id  = request.args.get('doctor_id')
    patient_id = request.args.get('patient_id')
    appt_date  = request.args.get('date')
    status     = request.args.get('status')

    sql = """
        SELECT a.*,
               CONCAT(p.first_name,' ',p.last_name) AS patient_name,
               d.full_name AS doctor_name, d.specialization
        FROM appointments a
        JOIN patients p ON a.patient_id = p.patient_id
        JOIN doctors  d ON a.doctor_id  = d.doctor_id
    """
    conditions, params = [], []
    if doctor_id:
        conditions.append("a.doctor_id=%s");  params.append(doctor_id)
    if patient_id:
        conditions.append("a.patient_id=%s"); params.append(patient_id)
    if appt_date == 'today':
        conditions.append("a.appt_date=%s");  params.append(today())
    elif appt_date:
        conditions.append("a.appt_date=%s");  params.append(appt_date)
    if status:
        conditions.append("a.status=%s");     params.append(status)
    if conditions:
        sql += " WHERE " + " AND ".join(conditions)
    sql += " ORDER BY a.appt_date, a.appt_time"

    return jsonify(query(sql, tuple(params)))

@app.route('/api/appointments', methods=['POST'])
def add_appointment():
    a = request.json
    if not all([a.get('patient_id'), a.get('doctor_id'), a.get('appt_date'), a.get('appt_time')]):
        return jsonify({"error": "patient_id, doctor_id, appt_date, appt_time required"}), 400

    row = query("SELECT COALESCE(MAX(CAST(SUBSTRING(appointment_id,4) AS UNSIGNED)),0)+1 AS nxt FROM appointments WHERE appointment_id LIKE 'APT%'", one=True)
    new_id = f"APT{str(row['nxt']).zfill(3)}"

    query("""INSERT INTO appointments
             (appointment_id, patient_id, doctor_id, appt_date, appt_time,
              appt_type, duration_min, status, notes)
             VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
          (new_id, a['patient_id'], a['doctor_id'],
           a['appt_date'], a['appt_time'],
           a.get('appt_type', 'Consultation'),
           a.get('duration_min', 30),
           a.get('status', 'Confirmed'),
           a.get('notes', '')),
          commit=True)

    return jsonify({"message": "Appointment scheduled!", "appointment_id": new_id}), 201

@app.route('/api/appointments/<appt_id>', methods=['PUT'])
def update_appointment(appt_id):
    a = request.json
    query("UPDATE appointments SET status=%s, notes=%s WHERE appointment_id=%s",
          (a.get('status'), a.get('notes', ''), appt_id), commit=True)
    return jsonify({"message": "Appointment updated"})

@app.route('/api/appointments/<appt_id>/cancel', methods=['PUT'])
def cancel_appointment(appt_id):
    query("UPDATE appointments SET status='Cancelled' WHERE appointment_id=%s",
          (appt_id,), commit=True)
    return jsonify({"message": "Appointment cancelled"})


# ══ PRESCRIPTIONS ══════════════════════════════════════════════
@app.route('/api/prescriptions', methods=['GET'])
def get_prescriptions():
    patient_id = request.args.get('patient_id')
    doctor_id  = request.args.get('doctor_id')

    sql = """
        SELECT r.*,
               CONCAT(p.first_name,' ',p.last_name) AS patient_name,
               d.full_name AS doctor_name
        FROM prescriptions r
        JOIN patients p ON r.patient_id = p.patient_id
        JOIN doctors  d ON r.doctor_id  = d.doctor_id
    """
    conditions, params = [], []
    if patient_id:
        conditions.append("r.patient_id=%s"); params.append(patient_id)
    if doctor_id:
        conditions.append("r.doctor_id=%s");  params.append(doctor_id)
    if conditions:
        sql += " WHERE " + " AND ".join(conditions)
    sql += " ORDER BY r.rx_date DESC"

    return jsonify(query(sql, tuple(params)))

@app.route('/api/prescriptions', methods=['POST'])
def add_prescription():
    r = request.json
    if not r.get('patient_id') or not r.get('medicines_text'):
        return jsonify({"error": "patient_id and medicines required"}), 400

    row = query("SELECT COALESCE(MAX(CAST(SUBSTRING(rx_id,3) AS UNSIGNED)),0)+1 AS nxt FROM prescriptions WHERE rx_id LIKE 'RX%'", one=True)
    new_id = f"RX{str(row['nxt']).zfill(3)}"

    query("""INSERT INTO prescriptions
             (rx_id, patient_id, doctor_id, rx_date, diagnosis,
              medicines_text, instructions, follow_up_date)
             VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
          (new_id, r['patient_id'], r['doctor_id'],
           r.get('rx_date', today()), r.get('diagnosis'),
           r['medicines_text'], r.get('instructions'), r.get('follow_up_date')),
          commit=True)

    return jsonify({"message": "Prescription saved!", "rx_id": new_id}), 201

@app.route('/api/prescriptions/<rx_id>', methods=['DELETE'])
def delete_prescription(rx_id):
    query("DELETE FROM prescriptions WHERE rx_id=%s", (rx_id,), commit=True)
    return jsonify({"message": "Prescription deleted"})


# ══ LAB TESTS ══════════════════════════════════════════════════
@app.route('/api/labs', methods=['GET'])
def get_labs():
    patient_id = request.args.get('patient_id')
    doctor_id  = request.args.get('doctor_id')
    status     = request.args.get('status')

    sql = """
        SELECT l.*,
               CONCAT(p.first_name,' ',p.last_name) AS patient_name,
               d.full_name AS doctor_name
        FROM lab_tests l
        JOIN patients p ON l.patient_id = p.patient_id
        JOIN doctors  d ON l.doctor_id  = d.doctor_id
    """
    conditions, params = [], []
    if patient_id:
        conditions.append("l.patient_id=%s"); params.append(patient_id)
    if doctor_id:
        conditions.append("l.doctor_id=%s");  params.append(doctor_id)
    if status:
        conditions.append("l.status=%s");     params.append(status)
    if conditions:
        sql += " WHERE " + " AND ".join(conditions)
    sql += " ORDER BY l.requested_date DESC"

    return jsonify(query(sql, tuple(params)))

@app.route('/api/labs', methods=['POST'])
def add_lab():
    l = request.json
    if not l.get('patient_id') or not l.get('test_name'):
        return jsonify({"error": "patient_id and test_name required"}), 400

    row = query("SELECT COALESCE(MAX(CAST(SUBSTRING(lab_id,4) AS UNSIGNED)),0)+1 AS nxt FROM lab_tests WHERE lab_id LIKE 'LAB%'", one=True)
    new_id = f"LAB{str(row['nxt']).zfill(3)}"

    query("""INSERT INTO lab_tests
             (lab_id, patient_id, doctor_id, test_name, sample_type,
              priority, requested_date, status)
             VALUES (%s,%s,%s,%s,%s,%s,%s,'Pending')""",
          (new_id, l['patient_id'], l['doctor_id'], l['test_name'],
           l.get('sample_type', 'Blood'), l.get('priority', 'Normal'),
           l.get('requested_date', today())),
          commit=True)

    return jsonify({"message": "Lab request submitted!", "lab_id": new_id}), 201

@app.route('/api/labs/<lab_id>', methods=['PUT'])
def update_lab(lab_id):
    l = request.json
    query("""UPDATE lab_tests SET status=%s, report_ready=%s, result_notes=%s
             WHERE lab_id=%s""",
          (l.get('status'), l.get('report_ready', False),
           l.get('result_notes', ''), lab_id), commit=True)
    return jsonify({"message": "Lab updated"})

@app.route('/api/labs/<lab_id>/result', methods=['PUT'])
def upload_lab_result(lab_id):
    l = request.json
    query("""UPDATE lab_tests SET status='Completed', report_ready=1,
             result_notes=%s WHERE lab_id=%s""",
          (l.get('result_notes', ''), lab_id), commit=True)
    return jsonify({"message": "Lab result uploaded"})


# ══ MEDICINES ══════════════════════════════════════════════════
@app.route('/api/medicines', methods=['GET'])
def get_medicines():
    status = request.args.get('status')
    if status:
        return jsonify(query("SELECT * FROM medicines WHERE status=%s", (status,)))
    return jsonify(query("SELECT * FROM medicines ORDER BY name"))

@app.route('/api/medicines', methods=['POST'])
def add_medicine():
    m = request.json
    query("""INSERT INTO medicines
             (name, category, stock_quantity, unit_price, expiry_date, status, reorder_level)
             VALUES (%s,%s,%s,%s,%s,%s,%s)""",
          (m['name'], m.get('category'), m.get('stock_quantity', 0),
           m.get('unit_price', 0), m.get('expiry_date'),
           m.get('status', 'In Stock'), m.get('reorder_level', 50)),
          commit=True)
    return jsonify({"message": "Medicine added!"}), 201

@app.route('/api/medicines/<int:medicine_id>', methods=['PUT'])
def update_medicine_stock(medicine_id):
    m = request.json
    new_stock = m.get('stock_quantity')
    status = 'Out of Stock' if new_stock == 0 else ('Low Stock' if new_stock < 50 else 'In Stock')
    query("""UPDATE medicines SET stock_quantity=%s, status=%s WHERE medicine_id=%s""",
          (new_stock, status, medicine_id), commit=True)
    return jsonify({"message": "Stock updated", "status": status})


# ══ MEDICINE ORDERS ════════════════════════════════════════════
@app.route('/api/medicine-orders', methods=['GET'])
def get_medicine_orders():
    return jsonify(query("SELECT * FROM medicine_orders ORDER BY created_at DESC"))

@app.route('/api/medicine-orders', methods=['POST'])
def add_medicine_order():
    o = request.json
    if not o.get('medicine_name') or not o.get('quantity'):
        return jsonify({"error": "medicine_name and quantity required"}), 400
    query("""INSERT INTO medicine_orders
             (medicine_name, quantity, priority, supplier, notes, ordered_by, status)
             VALUES (%s,%s,%s,%s,%s,%s,'Pending')""",
          (o['medicine_name'], o['quantity'],
           o.get('priority','Normal'), o.get('supplier',''),
           o.get('notes',''), o.get('ordered_by')),
          commit=True)
    return jsonify({"message": "Medicine order placed!"}), 201


# ══ BILLING ════════════════════════════════════════════════════
@app.route('/api/bills', methods=['GET'])
def get_bills():
    patient_id = request.args.get('patient_id')
    sql = """
        SELECT b.*, CONCAT(p.first_name,' ',p.last_name) AS patient_name
        FROM bills b JOIN patients p ON b.patient_id = p.patient_id
    """
    if patient_id:
        return jsonify(query(sql + " WHERE b.patient_id=%s ORDER BY b.bill_date DESC", (patient_id,)))
    return jsonify(query(sql + " ORDER BY b.bill_date DESC"))

@app.route('/api/bills', methods=['POST'])
def add_bill():
    b = request.json
    row = query("SELECT COALESCE(MAX(CAST(SUBSTRING(bill_id,5) AS UNSIGNED)),0)+1 AS nxt FROM bills WHERE bill_id LIKE 'INV-%'", one=True)
    new_id = f"INV-{str(row['nxt']).zfill(3)}"

    # Accept either full ISO datetime or plain date; store as DATE
    raw_date = b.get('bill_date', today())
    if raw_date and 'T' in str(raw_date):
        bill_date = str(raw_date).split('T')[0]
    else:
        bill_date = raw_date or today()

    query("""INSERT INTO bills (bill_id, patient_id, total_amount, paid_amount,
             status, services, bill_date)
             VALUES (%s,%s,%s,%s,%s,%s,%s)""",
          (new_id, b['patient_id'], b.get('total_amount', 0),
           b.get('paid_amount', 0), b.get('status', 'Pending'),
           b.get('services', ''), bill_date),
          commit=True)
    return jsonify({"message": "Bill created!", "bill_id": new_id}), 201

@app.route('/api/bills/<bill_id>/pay', methods=['PUT'])
def pay_bill(bill_id):
    b = request.json
    paid = b.get('paid_amount', 0)
    bill = query("SELECT * FROM bills WHERE bill_id=%s", (bill_id,), one=True)
    if not bill:
        return jsonify({"error": "Bill not found"}), 404
    total = float(bill['total_amount'])
    new_status = 'Paid' if paid >= total else ('Partial' if paid > 0 else 'Pending')
    query("UPDATE bills SET paid_amount=%s, status=%s WHERE bill_id=%s",
          (paid, new_status, bill_id), commit=True)
    return jsonify({"message": "Payment recorded", "status": new_status})


# ══ WARDS & BEDS ════════════════════════════════════════════════
@app.route('/api/wards', methods=['GET'])
def get_wards():
    try:
        wards = query("""
            SELECT w.*,
                   SUM(CASE WHEN b.status='available' THEN 1 ELSE 0 END) AS available_beds,
                   SUM(CASE WHEN b.status='occupied'  THEN 1 ELSE 0 END) AS occupied_beds,
                   COUNT(b.bed_id) AS total_beds
            FROM wards w
            LEFT JOIN beds b ON w.ward_id = b.ward_id
            GROUP BY w.ward_id
        """)
        return jsonify(wards)
    except Exception as e:
        return jsonify([])

@app.route('/api/wards', methods=['POST'])
def add_ward():
    w = request.json
    if not w.get('name'):
        return jsonify({"error": "Ward name required"}), 400
    try:
        row = query("SELECT COALESCE(MAX(ward_id),0)+1 AS nxt FROM wards", one=True)
        new_id = int(row['nxt']) if row and row['nxt'] else 1
        query("INSERT INTO wards (ward_id, name, ward_type, floor, capacity) VALUES (%s,%s,%s,%s,%s)",
              (new_id, w['name'], w.get('ward_type','General'), w.get('floor',1), w.get('capacity',20)),
              commit=True)
        return jsonify({"message": "Ward added", "ward_id": new_id}), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/wards/<int:ward_id>', methods=['DELETE'])
def delete_ward(ward_id):
    query("DELETE FROM beds WHERE ward_id=%s", (ward_id,), commit=True)
    query("DELETE FROM wards WHERE ward_id=%s", (ward_id,), commit=True)
    return jsonify({"message": "Ward deleted"})

@app.route('/api/beds', methods=['GET'])
def get_beds():
    ward_id = request.args.get('ward_id')
    try:
        if ward_id:
            return jsonify(query("""
                SELECT b.*, CONCAT(p.first_name,' ',p.last_name) AS patient_name
                FROM beds b LEFT JOIN patients p ON b.patient_id = p.patient_id
                WHERE b.ward_id=%s ORDER BY b.bed_number
            """, (ward_id,)))
        return jsonify(query("""
            SELECT b.*, w.name AS ward_name, CONCAT(p.first_name,' ',p.last_name) AS patient_name
            FROM beds b
            LEFT JOIN wards w ON b.ward_id = w.ward_id
            LEFT JOIN patients p ON b.patient_id = p.patient_id
            ORDER BY b.ward_id, b.bed_number
        """))
    except Exception:
        return jsonify([])

@app.route('/api/beds/<int:bed_id>', methods=['PUT'])
def update_bed(bed_id):
    b = request.json
    query("""UPDATE beds SET status=%s, patient_id=%s WHERE bed_id=%s""",
          (b.get('status'), b.get('patient_id'), bed_id), commit=True)
    return jsonify({"message": "Bed updated"})

@app.route('/api/beds', methods=['POST'])
def add_bed():
    b = request.json
    query("""INSERT INTO beds (ward_id, bed_number, bed_type, status)
             VALUES (%s, %s, %s, 'available')""",
          (b['ward_id'], b['bed_number'], b.get('bed_type', 'General')),
          commit=True)
    return jsonify({"message": "Bed added"}), 201


# ══ MEDICAL RECORDS ════════════════════════════════════════════
@app.route('/api/medical-records', methods=['GET'])
def get_medical_records():
    patient_id = request.args.get('patient_id')
    doctor_id  = request.args.get('doctor_id')
    sql = """
        SELECT m.*,
               CONCAT(p.first_name,' ',p.last_name) AS patient_name,
               d.full_name AS doctor_name
        FROM medical_records m
        JOIN patients p ON m.patient_id = p.patient_id
        JOIN doctors  d ON m.doctor_id  = d.doctor_id
    """
    conditions, params = [], []
    if patient_id:
        conditions.append("m.patient_id=%s"); params.append(patient_id)
    if doctor_id:
        conditions.append("m.doctor_id=%s");  params.append(doctor_id)
    if conditions:
        sql += " WHERE " + " AND ".join(conditions)
    sql += " ORDER BY m.record_date DESC"
    return jsonify(query(sql, tuple(params)))

@app.route('/api/medical-records', methods=['POST'])
def add_medical_record():
    r = request.json
    query("""INSERT INTO medical_records
             (patient_id, doctor_id, record_date, chief_complaint,
              diagnosis, treatment_plan, notes, follow_up_date)
             VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
          (r['patient_id'], r['doctor_id'], r.get('record_date', today()),
           r.get('chief_complaint'), r.get('diagnosis'), r.get('treatment_plan'),
           r.get('notes'), r.get('follow_up_date')),
          commit=True)
    return jsonify({"message": "Medical record saved!"}), 201


# ══ VITALS ════════════════════════════════════════════════════
@app.route('/api/vitals', methods=['GET'])
def get_vitals():
    patient_id = request.args.get('patient_id')
    if not patient_id:
        return jsonify({"error": "patient_id required"}), 400
    return jsonify(query("""
        SELECT v.*, u.username AS nurse_name
        FROM vitals v LEFT JOIN users u ON v.recorded_by = u.user_id
        WHERE v.patient_id=%s ORDER BY v.recorded_at DESC
    """, (patient_id,)))

@app.route('/api/vitals', methods=['POST'])
def add_vitals():
    v = request.json
    query("""INSERT INTO vitals
             (patient_id, recorded_by, blood_pressure, pulse, temperature,
              oxygen_saturation, weight_kg, height_cm, notes)
             VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
          (v['patient_id'], v.get('recorded_by'),
           v.get('blood_pressure'), v.get('pulse'), v.get('temperature'),
           v.get('oxygen_saturation'), v.get('weight_kg'), v.get('height_cm'),
           v.get('notes', '')),
          commit=True)
    return jsonify({"message": "Vitals recorded!"}), 201


# ══ NURSES & RECEPTIONISTS ════════════════════════════════════
@app.route('/api/nurses', methods=['GET'])
def get_nurses():
    return jsonify(query("""
        SELECT n.*, w.name AS ward_name
        FROM nurses n LEFT JOIN wards w ON n.ward_id = w.ward_id
    """))

@app.route('/api/receptionists', methods=['GET'])
def get_receptionists():
    return jsonify(query("SELECT * FROM receptionists"))


# ══ DASHBOARD STATS ═══════════════════════════════════════════
@app.route('/api/dashboard/stats', methods=['GET'])
def dashboard_stats():
    total_patients  = query("SELECT COUNT(*) AS c FROM patients", one=True)['c']
    admitted        = query("SELECT COUNT(*) AS c FROM patients WHERE status='admitted'", one=True)['c']
    active_doctors  = query("SELECT COUNT(*) AS c FROM doctors WHERE status='Active'", one=True)['c']
    today_appts     = query("SELECT COUNT(*) AS c FROM appointments WHERE appt_date=%s", (today(),), one=True)['c']
    pending_appts   = query("SELECT COUNT(*) AS c FROM appointments WHERE status='Pending'", one=True)['c']
    low_stock       = query("SELECT COUNT(*) AS c FROM medicines WHERE status IN ('Low Stock','Out of Stock')", one=True)['c']
    pending_labs    = query("SELECT COUNT(*) AS c FROM lab_tests WHERE status='Pending'", one=True)['c']
    pending_bills   = query("SELECT COUNT(*) AS c FROM bills WHERE status='Pending'", one=True)['c']
    available_beds  = query("SELECT COUNT(*) AS c FROM beds WHERE status='available'", one=True)['c']

    return jsonify({
        "total_patients":  total_patients,
        "admitted":        admitted,
        "active_doctors":  active_doctors,
        "today_appts":     today_appts,
        "pending_appts":   pending_appts,
        "low_stock_meds":  low_stock,
        "pending_labs":    pending_labs,
        "pending_bills":   pending_bills,
        "available_beds":  available_beds
    })


# ══ DEPARTMENTS ════════════════════════════════════════════════
@app.route('/api/departments', methods=['GET'])
def get_departments():
    return jsonify(query("""
        SELECT dep.*, d.full_name AS head_name
        FROM departments dep
        LEFT JOIN doctors d ON dep.head_doctor = d.doctor_id
    """))


# ── ERROR HANDLERS ─────────────────────────────────────────────
@app.errorhandler(404)
def not_found(e):
    return jsonify({"error": "Not found"}), 404

@app.errorhandler(500)
def server_error(e):
    return jsonify({"error": "Internal server error", "detail": str(e)}), 500

@app.route('/api/ping', methods=['GET'])
def ping():
    return jsonify({"ok": True})


if __name__ == '__main__':
    app.run(debug=True, port=5000)