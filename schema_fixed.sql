-- ============================================================
--  MediCore HMS — Complete Database Schema (FIXED)
--  Run this in MySQL: mysql -u root -p < schema_fixed.sql
--
--  Fixes applied:
--  1. Dropped DATABASE first to ensure clean re-run
--  2. Removed non-existent `diagnosis` column from patients INSERT
--  3. Reordered INSERTs: departments → doctors → patients → children
--  4. Deferred departments.head_doctor FK update (AFTER doctors inserted)
--  5. Fixed vitals INSERT column list (was missing `recorded_at`)
--  6. Fixed medical_records INSERT column list (matches table definition)
--  7. Added SET FOREIGN_KEY_CHECKS wrappers for safe load ordering
-- ============================================================

DROP DATABASE IF EXISTS medicore_hms;
CREATE DATABASE medicore_hms;
USE medicore_hms;

SET FOREIGN_KEY_CHECKS = 0;

-- ── 1. USERS (login system) ───────────────────────────────────
CREATE TABLE IF NOT EXISTS users (
    user_id     INT AUTO_INCREMENT PRIMARY KEY,
    username    VARCHAR(100) NOT NULL UNIQUE,
    password    VARCHAR(255) NOT NULL,
    role        ENUM('admin','doctor','receptionist','nurse','patient') NOT NULL,
    is_active   BOOLEAN DEFAULT TRUE,
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- ── 2. DEPARTMENTS ────────────────────────────────────────────
-- head_doctor FK added AFTER doctors table is created (see below)
CREATE TABLE IF NOT EXISTS departments (
    dept_id     INT AUTO_INCREMENT PRIMARY KEY,
    name        VARCHAR(100) NOT NULL,
    head_doctor VARCHAR(10) DEFAULT NULL,
    location    VARCHAR(100),
    phone       VARCHAR(20)
);

-- ── 3. DOCTORS ────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS doctors (
    doctor_id        VARCHAR(10) PRIMARY KEY,
    user_id          INT,
    full_name        VARCHAR(150) NOT NULL,
    specialization   VARCHAR(100),
    qualification    VARCHAR(100),
    experience_yrs   INT DEFAULT 0,
    consultation_fee DECIMAL(8,2) DEFAULT 0,
    phone            VARCHAR(20),
    email            VARCHAR(150),
    dept_id          INT,
    status           ENUM('Active','On Leave','Inactive') DEFAULT 'Active',
    available_days   VARCHAR(100),
    created_at       DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id)  REFERENCES users(user_id)        ON DELETE SET NULL,
    FOREIGN KEY (dept_id)  REFERENCES departments(dept_id)  ON DELETE SET NULL
);

-- Add the circular FK on departments.head_doctor AFTER doctors is defined
ALTER TABLE departments
    ADD CONSTRAINT fk_dept_head
    FOREIGN KEY (head_doctor) REFERENCES doctors(doctor_id) ON DELETE SET NULL;

-- ── 4. DOCTOR AVAILABILITY SLOTS ─────────────────────────────
CREATE TABLE IF NOT EXISTS doctor_slots (
    slot_id   INT AUTO_INCREMENT PRIMARY KEY,
    doctor_id VARCHAR(10) NOT NULL,
    slot_time VARCHAR(10) NOT NULL,
    is_active BOOLEAN DEFAULT TRUE,
    FOREIGN KEY (doctor_id) REFERENCES doctors(doctor_id) ON DELETE CASCADE
);

-- ── 5. PATIENTS ───────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS patients (
    patient_id        VARCHAR(10) PRIMARY KEY,
    user_id           INT,
    first_name        VARCHAR(80)  NOT NULL,
    last_name         VARCHAR(80)  NOT NULL,
    date_of_birth     DATE,
    age               INT,
    gender            ENUM('Male','Female','Other'),
    blood_group       VARCHAR(5),
    phone             VARCHAR(20),
    email             VARCHAR(150),
    address           TEXT,
    emergency_contact VARCHAR(20),
    assigned_doctor   VARCHAR(10),
    patient_type      ENUM('Inpatient','Outpatient','Emergency') DEFAULT 'Outpatient',
    status            ENUM('admitted','outpatient','discharged','deceased') DEFAULT 'outpatient',
    ward              VARCHAR(50)  DEFAULT '-',
    admission_date    DATE,
    discharge_date    DATE,
    password_plain    VARCHAR(50)  DEFAULT 'demo-patient-only',
    created_at        DATETIME     DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id)         REFERENCES users(user_id)        ON DELETE SET NULL,
    FOREIGN KEY (assigned_doctor) REFERENCES doctors(doctor_id)    ON DELETE SET NULL
);

-- ── 6. APPOINTMENTS ───────────────────────────────────────────
CREATE TABLE IF NOT EXISTS appointments (
    appointment_id VARCHAR(10) PRIMARY KEY,
    patient_id     VARCHAR(10) NOT NULL,
    doctor_id      VARCHAR(10) NOT NULL,
    appt_date      DATE        NOT NULL,
    appt_time      VARCHAR(10) NOT NULL,
    appt_type      ENUM('Consultation','Follow-up','Check-up','Emergency','Surgery') DEFAULT 'Consultation',
    duration_min   INT         DEFAULT 30,
    status         ENUM('Confirmed','Pending','Cancelled','Completed') DEFAULT 'Pending',
    notes          TEXT,
    created_at     DATETIME    DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (patient_id) REFERENCES patients(patient_id) ON DELETE CASCADE,
    FOREIGN KEY (doctor_id)  REFERENCES doctors(doctor_id)   ON DELETE CASCADE
);

-- ── 7. WARDS & BEDS ───────────────────────────────────────────
CREATE TABLE IF NOT EXISTS wards (
    ward_id    INT AUTO_INCREMENT PRIMARY KEY,
    name       VARCHAR(100) NOT NULL,
    total_beds INT DEFAULT 0,
    ward_type  ENUM('General','ICU','Pediatric','Maternity','Emergency','Private') DEFAULT 'General',
    floor      INT DEFAULT 1,
    capacity   INT DEFAULT 20
);

CREATE TABLE IF NOT EXISTS beds (
    bed_id     INT AUTO_INCREMENT PRIMARY KEY,
    ward_id    INT NOT NULL,
    bed_number VARCHAR(10) NOT NULL,
    bed_type   ENUM('General','ICU','Private','Pediatric','Maternity') DEFAULT 'General',
    status     ENUM('available','occupied','reserved','maintenance') DEFAULT 'available',
    patient_id VARCHAR(10),
    FOREIGN KEY (ward_id)    REFERENCES wards(ward_id)        ON DELETE CASCADE,
    FOREIGN KEY (patient_id) REFERENCES patients(patient_id)  ON DELETE SET NULL
);

-- ── 8. MEDICAL RECORDS ────────────────────────────────────────
CREATE TABLE IF NOT EXISTS medical_records (
    record_id       INT AUTO_INCREMENT PRIMARY KEY,
    patient_id      VARCHAR(10) NOT NULL,
    doctor_id       VARCHAR(10) NOT NULL,
    record_date     DATE        NOT NULL,
    chief_complaint TEXT,
    diagnosis       TEXT,
    treatment_plan  TEXT,
    notes           TEXT,
    follow_up_date  DATE,
    created_at      DATETIME    DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (patient_id) REFERENCES patients(patient_id) ON DELETE CASCADE,
    FOREIGN KEY (doctor_id)  REFERENCES doctors(doctor_id)   ON DELETE CASCADE
);

-- ── 9. VITALS ─────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS vitals (
    vital_id          INT AUTO_INCREMENT PRIMARY KEY,
    patient_id        VARCHAR(10) NOT NULL,
    recorded_by       INT,
    recorded_at       DATETIME    DEFAULT CURRENT_TIMESTAMP,
    blood_pressure    VARCHAR(20),
    pulse             INT,
    temperature       DECIMAL(4,1),
    oxygen_saturation INT,
    weight_kg         DECIMAL(5,2),
    height_cm         DECIMAL(5,1),
    notes             TEXT,
    FOREIGN KEY (patient_id)  REFERENCES patients(patient_id) ON DELETE CASCADE,
    FOREIGN KEY (recorded_by) REFERENCES users(user_id)       ON DELETE SET NULL
);

-- ── 10. PRESCRIPTIONS ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS prescriptions (
    rx_id          VARCHAR(10) PRIMARY KEY,
    patient_id     VARCHAR(10) NOT NULL,
    doctor_id      VARCHAR(10) NOT NULL,
    rx_date        DATE        NOT NULL,
    diagnosis      VARCHAR(255),
    medicines_text TEXT,
    instructions   TEXT,
    follow_up_date DATE,
    created_at     DATETIME    DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (patient_id) REFERENCES patients(patient_id) ON DELETE CASCADE,
    FOREIGN KEY (doctor_id)  REFERENCES doctors(doctor_id)   ON DELETE CASCADE
);

-- ── 11. MEDICINES / PHARMACY ──────────────────────────────────
CREATE TABLE IF NOT EXISTS medicines (
    medicine_id    INT AUTO_INCREMENT PRIMARY KEY,
    name           VARCHAR(150) NOT NULL,
    category       VARCHAR(80),
    stock_quantity INT          DEFAULT 0,
    unit_price     DECIMAL(8,2),
    expiry_date    VARCHAR(10),
    status         ENUM('In Stock','Low Stock','Out of Stock') DEFAULT 'In Stock',
    reorder_level  INT          DEFAULT 50
);

-- ── 12. LAB TESTS ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS lab_tests (
    lab_id         VARCHAR(10) PRIMARY KEY,
    patient_id     VARCHAR(10) NOT NULL,
    doctor_id      VARCHAR(10) NOT NULL,
    test_name      VARCHAR(150) NOT NULL,
    sample_type    ENUM('Blood','Urine','Stool','Swab','Imaging') DEFAULT 'Blood',
    priority       ENUM('Normal','Urgent','STAT') DEFAULT 'Normal',
    requested_date DATE        NOT NULL,
    status         ENUM('Pending','In Process','Completed','Cancelled') DEFAULT 'Pending',
    report_ready   BOOLEAN     DEFAULT FALSE,
    result_notes   TEXT,
    created_at     DATETIME    DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (patient_id) REFERENCES patients(patient_id) ON DELETE CASCADE,
    FOREIGN KEY (doctor_id)  REFERENCES doctors(doctor_id)   ON DELETE CASCADE
);

-- ── 13. BILLING / INVOICES ────────────────────────────────────
CREATE TABLE IF NOT EXISTS bills (
    bill_id      VARCHAR(10) PRIMARY KEY,
    patient_id   VARCHAR(10) NOT NULL,
    total_amount DECIMAL(10,2) DEFAULT 0,
    paid_amount  DECIMAL(10,2) DEFAULT 0,
    status       ENUM('Pending','Paid','Partial','Cancelled') DEFAULT 'Pending',
    services     TEXT,
    bill_date    DATE         NOT NULL DEFAULT (CURDATE()),
    created_at   DATETIME     DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (patient_id) REFERENCES patients(patient_id) ON DELETE CASCADE
);

-- ── 14. NURSES ────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS nurses (
    nurse_id  INT AUTO_INCREMENT PRIMARY KEY,
    user_id   INT,
    full_name VARCHAR(150) NOT NULL,
    phone     VARCHAR(20),
    email     VARCHAR(150),
    ward_id   INT,
    shift     ENUM('Morning','Afternoon','Night') DEFAULT 'Morning',
    status    ENUM('Active','On Leave','Inactive') DEFAULT 'Active',
    FOREIGN KEY (user_id)  REFERENCES users(user_id)   ON DELETE SET NULL,
    FOREIGN KEY (ward_id)  REFERENCES wards(ward_id)   ON DELETE SET NULL
);

-- ── 15. RECEPTIONISTS ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS receptionists (
    recep_id  INT AUTO_INCREMENT PRIMARY KEY,
    user_id   INT,
    full_name VARCHAR(150) NOT NULL,
    phone     VARCHAR(20),
    email     VARCHAR(150),
    shift     ENUM('Morning','Afternoon','Night') DEFAULT 'Morning',
    status    ENUM('Active','Inactive') DEFAULT 'Active',
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE SET NULL
);

-- ── 16. MEDICINE ORDERS ───────────────────────────────────────
CREATE TABLE IF NOT EXISTS medicine_orders (
    order_id    INT AUTO_INCREMENT PRIMARY KEY,
    medicine_name VARCHAR(150) NOT NULL,
    quantity    INT NOT NULL,
    priority    ENUM('Normal','Urgent','STAT') DEFAULT 'Normal',
    supplier    VARCHAR(200),
    notes       TEXT,
    ordered_by  INT,
    status      ENUM('Pending','Approved','Ordered','Delivered','Cancelled') DEFAULT 'Pending',
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (ordered_by) REFERENCES users(user_id) ON DELETE SET NULL
);

SET FOREIGN_KEY_CHECKS = 1;

-- ══════════════════════════════════════════════════
--  SEED DATA  (insertion order respects FK deps)
--  Order: users → departments → doctors →
--         update dept heads → doctor_slots →
--         patients → appointments → wards →
--         medicines → lab_tests → prescriptions →
--         bills → vitals → medical_records →
--         nurses → receptionists
-- ══════════════════════════════════════════════════

-- 1. Users
INSERT INTO users (username, password, role) VALUES
('admin@demo.invalid',       'demo-admin-only',        'admin'),
('doctor01@demo.invalid',    'demo-doctor-only',       'doctor'),
('doctor02@demo.invalid',    'demo-doctor-only',       'doctor'),
('doctor03@demo.invalid',    'demo-doctor-only',       'doctor'),
('doctor04@demo.invalid',    'demo-doctor-only',       'doctor'),
('doctor05@demo.invalid',    'demo-doctor-only',       'doctor'),
('doctor06@demo.invalid',    'demo-doctor-only',       'doctor'),
('reception@demo.invalid',   'demo-receptionist-only', 'receptionist'),
('nurse@demo.invalid',       'demo-nurse-only',        'nurse'),
('PAT001',                   'demo-patient-only',      'patient'),
('PAT002',                   'demo-patient-only',      'patient'),
('PAT003',                   'demo-patient-only',      'patient'),
('PAT004',                   'demo-patient-only',      'patient'),
('PAT005',                   'demo-patient-only',      'patient'),
('PAT006',                   'demo-patient-only',      'patient');

-- 2. Departments (no head_doctor yet — doctors don't exist yet)
INSERT INTO departments (name, location, phone) VALUES
('Cardiology',       'Block A, Floor 2', '+91-80-1001'),
('Neurology',        'Block B, Floor 3', '+91-80-1002'),
('Pediatrics',       'Block C, Floor 1', '+91-80-1003'),
('Orthopedics',      'Block A, Floor 3', '+91-80-1004'),
('Dermatology',      'Block D, Floor 1', '+91-80-1005'),
('General Medicine', 'Block E, Floor 1', '+91-80-1006');

-- 3. Doctors
INSERT INTO doctors (doctor_id, full_name, specialization, qualification, experience_yrs, consultation_fee, phone, email, dept_id, status, available_days) VALUES
('D01','Dr. Demo One',      'Cardiology',      'MBBS,MD',  12, 800, '000-000-0001','doctor01@example.invalid', 1,'Active',   'Mon,Wed,Fri'),
('D02','Dr. Demo Two',      'Neurology',       'MBBS,DM',  8,  700, '000-000-0002','doctor02@example.invalid', 2,'Active',   'Tue,Thu,Sat'),
('D03','Dr. Demo Three',    'Pediatrics',      'MBBS,DCH', 6,  500, '000-000-0003','doctor03@example.invalid', 3,'Active',   'Mon,Tue,Wed,Thu'),
('D04','Dr. Demo Four',     'Orthopedics',     'MBBS,MS',  15, 900, '000-000-0004','doctor04@example.invalid', 4,'On Leave', 'Mon,Wed'),
('D05','Dr. Demo Five',     'Dermatology',     'MBBS,DVD', 4,  600, '000-000-0005','doctor05@example.invalid', 5,'Active',   'Mon,Tue,Fri'),
('D06','Dr. Demo Six',      'General Medicine','MBBS',     10, 400, '000-000-0006','doctor06@example.invalid', 6,'Active',   'Mon,Tue,Wed,Thu,Fri');

-- 4. Now assign department heads (doctors exist now)
UPDATE departments SET head_doctor = 'D01' WHERE dept_id = 1;
UPDATE departments SET head_doctor = 'D02' WHERE dept_id = 2;
UPDATE departments SET head_doctor = 'D03' WHERE dept_id = 3;
UPDATE departments SET head_doctor = 'D04' WHERE dept_id = 4;
UPDATE departments SET head_doctor = 'D05' WHERE dept_id = 5;
UPDATE departments SET head_doctor = 'D06' WHERE dept_id = 6;

-- 5. Doctor slots
INSERT INTO doctor_slots (doctor_id, slot_time) VALUES
('D01','09:00'),('D01','09:30'),('D01','10:00'),('D01','11:00'),('D01','14:00'),
('D02','10:00'),('D02','10:30'),('D02','11:30'),('D02','15:00'),
('D03','09:00'),('D03','10:00'),('D03','11:00'),('D03','14:30'),('D03','16:00'),
('D04','10:00'),('D04','14:00'),
('D05','09:30'),('D05','10:30'),('D05','11:30'),('D05','15:30'),
('D06','09:00'),('D06','09:30'),('D06','10:00'),('D06','11:00'),('D06','11:30'),('D06','14:00'),('D06','15:00'),('D06','16:00');

-- 6. Patients
--    FIX: removed `diagnosis` column (it does not exist in patients table)
INSERT INTO patients (patient_id, first_name, last_name, age, gender, blood_group, phone, email, assigned_doctor, patient_type, status, ward, admission_date, password_plain) VALUES
('PAT001','Demo', 'Patient 001', 34,'Male',  'B+',  '000-000-0001','patient001@example.invalid','D01','Inpatient', 'admitted',   'Ward A-102', CURDATE(),'demo-patient-only'),
('PAT002','Demo', 'Patient 002', 62,'Female','O+',  '000-000-0002','patient002@example.invalid','D02','Inpatient', 'admitted',   'Ward B-205', CURDATE(),'demo-patient-only'),
('PAT003','Demo', 'Patient 003',  8,'Male',  'A+',  '000-000-0003','patient003@example.invalid','D03','Outpatient','outpatient', '-',          CURDATE(),'demo-patient-only'),
('PAT004','Demo', 'Patient 004', 45,'Female','AB-', '000-000-0004','patient004@example.invalid','D04','Inpatient', 'admitted',   'Ward C-310', CURDATE(),'demo-patient-only'),
('PAT005','Demo', 'Patient 005', 27,'Male',  'O-',  '000-000-0005','patient005@example.invalid','D05','Outpatient','outpatient', '-',          CURDATE(),'demo-patient-only'),
('PAT006','Demo', 'Patient 006', 55,'Female','A-',  '000-000-0006','patient006@example.invalid','D06','Inpatient', 'discharged', '-',          CURDATE(),'demo-patient-only');

-- 7. Appointments
INSERT INTO appointments (appointment_id, patient_id, doctor_id, appt_date, appt_time, appt_type, duration_min, status, notes) VALUES
('APT001','PAT001','D01',CURDATE(),'09:00','Consultation',30,'Confirmed',''),
('APT002','PAT002','D02',CURDATE(),'10:30','Follow-up',   20,'Confirmed',''),
('APT003','PAT003','D03',CURDATE(),'11:00','Check-up',    30,'Pending',  'Bring previous reports'),
('APT004','PAT005','D05',CURDATE(),'14:00','Follow-up',   15,'Confirmed',''),
('APT005','PAT006','D06',CURDATE(),'15:30','Consultation',30,'Cancelled','');

-- 8. Wards (with floor and capacity)
INSERT INTO wards (name, total_beds, ward_type, floor, capacity) VALUES
('General Ward',   40, 'General',   1, 40),
('ICU',            10, 'ICU',       2, 10),
('Pediatric Ward', 20, 'Pediatric', 1, 20),
('Maternity Ward', 15, 'Maternity', 3, 15),
('Emergency Ward', 12, 'Emergency', 0, 12),
('Private Ward',    8, 'Private',   4,  8);

-- Beds for General Ward (ward_id=1)
INSERT INTO beds (ward_id, bed_number, bed_type, status, patient_id) VALUES
(1,'A-01','General','occupied','PAT001'),
(1,'A-02','General','available',NULL),
(1,'A-03','General','available',NULL),
(1,'A-04','General','occupied','PAT002'),
(1,'A-05','General','maintenance',NULL),
(1,'A-06','General','available',NULL),
(1,'A-07','General','reserved',NULL),
(1,'A-08','General','available',NULL);

-- Beds for ICU (ward_id=2)
INSERT INTO beds (ward_id, bed_number, bed_type, status, patient_id) VALUES
(2,'ICU-01','ICU','occupied','PAT004'),
(2,'ICU-02','ICU','available',NULL),
(2,'ICU-03','ICU','available',NULL),
(2,'ICU-04','ICU','occupied',NULL);

-- Beds for Pediatric (ward_id=3)
INSERT INTO beds (ward_id, bed_number, bed_type, status, patient_id) VALUES
(3,'P-01','Pediatric','occupied','PAT003'),
(3,'P-02','Pediatric','available',NULL),
(3,'P-03','Pediatric','available',NULL),
(3,'P-04','Pediatric','reserved',NULL);

-- Beds for Maternity (ward_id=4)
INSERT INTO beds (ward_id, bed_number, bed_type, status, patient_id) VALUES
(4,'M-01','Maternity','available',NULL),
(4,'M-02','Maternity','available',NULL),
(4,'M-03','Maternity','reserved',NULL);

-- Beds for Emergency Ward (ward_id=5)
INSERT INTO beds (ward_id, bed_number, bed_type, status, patient_id) VALUES
(5,'E-01','General','available',NULL),
(5,'E-02','General','available',NULL),
(5,'E-03','General','available',NULL);

-- Beds for Private Ward (ward_id=6)
INSERT INTO beds (ward_id, bed_number, bed_type, status, patient_id) VALUES
(6,'PR-01','Private','available',NULL),
(6,'PR-02','Private','available',NULL);

-- 9. Medicines (no FK dependency)
INSERT INTO medicines (name, category, stock_quantity, unit_price, expiry_date, status, reorder_level) VALUES
('Paracetamol 500mg',  'Analgesic',     540,  2.50, '2026-12', 'In Stock',     100),
('Amoxicillin 250mg',  'Antibiotic',    120,  8.00, '2026-06', 'In Stock',     50),
('Metformin 500mg',    'Antidiabetic',  30,   5.00, '2025-11', 'Low Stock',    50),
('Atorvastatin 20mg',  'Cardiac',       200, 12.00, '2026-09', 'In Stock',     50),
('Cetirizine 10mg',    'Antihistamine', 0,    3.00, '2025-08', 'Out of Stock', 50),
('Pantoprazole 40mg',  'Gastric',       85,   6.50, '2026-03', 'In Stock',     50),
('Amlodipine 5mg',     'Cardiac',       45,   4.00, '2026-01', 'Low Stock',    50);

-- 10. Lab Tests (depends on patients + doctors)
INSERT INTO lab_tests (lab_id, patient_id, doctor_id, test_name, priority, requested_date, status, report_ready) VALUES
('LAB001','PAT001','D01','CBC (Complete Blood Count)', 'Normal', CURDATE(), 'Completed',  TRUE),
('LAB002','PAT002','D02','MRI Brain',                  'Urgent', CURDATE(), 'In Process', FALSE),
('LAB003','PAT003','D03','Blood Culture',              'Normal', CURDATE(), 'Pending',    FALSE);

-- 11. Prescriptions (depends on patients + doctors)
INSERT INTO prescriptions (rx_id, patient_id, doctor_id, rx_date, diagnosis, medicines_text, instructions, follow_up_date) VALUES
('RX001','PAT001','D01',CURDATE(),'Hypertension','Amlodipine 5mg — 1 tab OD\nAtorvastatin 20mg — 1 tab OD','Low salt diet. Regular walks.',CURDATE());

-- 12. Bills (depends on patients)
INSERT INTO bills (bill_id, patient_id, total_amount, paid_amount, status, services, bill_date) VALUES
('INV-001','PAT001', 12400, 12400, 'Paid',    'Consultation, Room, Lab',     CURDATE()),
('INV-002','PAT002', 28900, 0,     'Pending', 'Room, Neurology, Medicine',   CURDATE()),
('INV-003','PAT004', 45000, 20000, 'Partial', 'Orthopedics, Surgery, Room',  CURDATE());

-- 13. Vitals (depends on patients)
--     FIX: column list matches table definition exactly
INSERT INTO vitals (patient_id, blood_pressure, pulse, temperature, oxygen_saturation, weight_kg, height_cm, notes) VALUES
('PAT001','140/90', 88, 37.2, 97, 72.0, 175.0, 'Elevated BP — monitoring'),
('PAT002','120/80', 76, 36.8, 98, 58.0, 160.0, 'Stable'),
('PAT004','118/78', 82, 37.0, 99, 65.0, 162.0, 'Post-surgery vitals normal');

-- 14. Medical Records (depends on patients + doctors)
--     FIX: column list matches table definition (removed non-existent columns)
INSERT INTO medical_records (patient_id, doctor_id, record_date, chief_complaint, diagnosis, treatment_plan, follow_up_date) VALUES
('PAT001','D01',CURDATE(),'Chest pain and breathlessness','Hypertension Stage 2',  'Medication + lifestyle change', CURDATE()),
('PAT002','D02',CURDATE(),'Sudden loss of consciousness', 'Ischemic stroke',        'Physiotherapy + medication',    CURDATE());

-- 15. Nurses (depends on wards)
INSERT INTO nurses (full_name, phone, email, ward_id, shift, status) VALUES
('Demo Nurse', '000-000-0007', 'nurse@example.invalid', 1, 'Morning', 'Active');

-- 16. Receptionists
INSERT INTO receptionists (full_name, phone, email, shift, status) VALUES
('Demo Receptionist', '000-000-0008', 'reception@example.invalid', 'Morning', 'Active');
