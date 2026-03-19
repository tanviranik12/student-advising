from __future__ import annotations

import io
import os
import smtplib
from dataclasses import dataclass
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import List, Dict, Any

from flask import Flask, jsonify, request, send_from_directory
from werkzeug.utils import secure_filename

try:
    import PyPDF2
    PDF_OK = True
except ImportError:
    PDF_OK = False

# Load .env file from the same directory as this script
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env")
except ImportError:
    pass

app = Flask(__name__)

# ── Upload folder ──────────────────────────────────────────────────────────────
UPLOAD_FOLDER = Path(__file__).parent / "uploads"
UPLOAD_FOLDER.mkdir(exist_ok=True)
ALLOWED_EXT = {"pdf", "docx", "doc", "txt", "xlsx", "csv", "png", "jpg", "jpeg"}

# ── Gmail credentials ──────────────────────────────────────────────────────────
GMAIL_USER = os.environ.get("GMAIL_USER", "").strip()
GMAIL_PASS = os.environ.get("GMAIL_APP_PASSWORD", "").strip()

# ── Gemini setup ───────────────────────────────────────────────────────────────
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
gemini_model = None

if GEMINI_API_KEY:
    try:
        import google.generativeai as genai
        genai.configure(api_key=GEMINI_API_KEY)
        gemini_model = genai.GenerativeModel("gemini-flash-lite-latest")
        print("[AI] Gemini 1.5 Flash loaded successfully.")
    except Exception as e:
        print(f"[AI] Gemini setup failed: {e}. Using rule-based fallback.")
else:
    print("[AI] No GEMINI_API_KEY found. Using rule-based fallback.")


def clean_text(text: str) -> str:
    """Remove markdown symbols so the output is plain readable text."""
    import re
    # Remove headers (# ## ###)
    text = re.sub(r'#{1,6}\s*', '', text)
    # Remove bold/italic (**text**, *text*, __text__, _text_)
    text = re.sub(r'\*{1,3}(.*?)\*{1,3}', r'\1', text)
    text = re.sub(r'_{1,3}(.*?)_{1,3}', r'\1', text)
    # Remove inline code `text`
    text = re.sub(r'`([^`]*)`', r'\1', text)
    # Remove code blocks ```...```
    text = re.sub(r'```[\s\S]*?```', '', text)
    # Replace markdown bullets (* - +) at line start with a dash
    text = re.sub(r'^\s*[\*\-\+]\s+', '- ', text, flags=re.MULTILINE)
    # Remove horizontal rules (--- or ***)
    text = re.sub(r'^[\-\*]{3,}\s*$', '', text, flags=re.MULTILINE)
    # Remove extra blank lines (more than 2 in a row)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def ask_gemini(prompt: str) -> str | None:
    if not gemini_model:
        return None
    clean_prompt = (
        "Reply in plain text only. No markdown, no asterisks, no hashtags, "
        "no bold, no headers, no special symbols. Use simple numbered points or "
        "plain sentences only.\n\n" + prompt
    )
    try:
        response = gemini_model.generate_content(clean_prompt)
        return clean_text(response.text)
    except Exception as e:
        print(f"[AI] Gemini call failed: {e}")
        return None


# ── Serve frontend HTML ────────────────────────────────────────────────────────
STATIC_DIR = Path(__file__).parent.parent / "src" / "main" / "resources" / "static"

@app.route("/")
def index():
    return send_from_directory(str(STATIC_DIR), "index.html")


# ── File Upload ────────────────────────────────────────────────────────────────

@app.post("/api/upload")
def upload_file():
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400
    f = request.files["file"]
    if not f.filename:
        return jsonify({"error": "Empty filename"}), 400
    ext = f.filename.rsplit(".", 1)[-1].lower() if "." in f.filename else ""
    if ext not in ALLOWED_EXT:
        return jsonify({"error": f"File type .{ext} not allowed. Allowed: {', '.join(sorted(ALLOWED_EXT))}"}), 400
    fname = secure_filename(f.filename)
    dest = UPLOAD_FOLDER / fname
    f.save(dest)
    size_kb = round(dest.stat().st_size / 1024, 1)
    return jsonify({"filename": fname, "sizeKB": size_kb,
                    "message": f"Uploaded: {fname} ({size_kb} KB) — stored successfully."})


# ── PDF Analyser ────────────────────────────────────────────────────────────────

@app.post("/api/pdf/analyse")
def analyse_pdf():
    if "file" not in request.files:
        return jsonify({"response": "No file uploaded."}), 400
    f = request.files["file"]
    if not f.filename.lower().endswith(".pdf"):
        return jsonify({"response": "Only PDF files are supported."}), 400
    if not PDF_OK:
        return jsonify({"response": "PDF library not installed on server. Run: pip install PyPDF2"}), 500

    raw = f.read()
    try:
        reader = PyPDF2.PdfReader(io.BytesIO(raw))
        pages = len(reader.pages)
        text = "\n".join(
            (p.extract_text() or "") for p in reader.pages
        ).strip()
    except Exception as e:
        return jsonify({"response": f"PDF read error: {e}"}), 500

    if not text:
        return jsonify({"response": "Could not extract text. The PDF may be image-based or scanned."}), 400

    mode = request.form.get("mode", "full")
    word_count = len(text.split())
    excerpt = text[:7000]  # stay within token limit

    prompts = {
        "summarize": f"Summarize this academic document clearly in 200-250 words:\n\n{excerpt}",
        "keypoints": f"List the 6 most important key points from this academic document:\n\n{excerpt}",
        "advice":    f"Read this academic document and give 5 specific, actionable academic recommendations:\n\n{excerpt}",
        "full":      (
            f"Analyse this academic document and provide:\n"
            f"1. Summary (3-4 sentences).\n"
            f"2. Key points (5 bullet items).\n"
            f"3. Academic advice or recommendations (3-4 points).\n"
            f"4. Overall assessment (1-2 sentences).\n\n{excerpt}"
        ),
    }
    result = ask_gemini(prompts.get(mode, prompts["full"]))
    return jsonify({
        "response": result or "Could not analyse content.",
        "pages": pages,
        "wordCount": word_count,
        "filename": secure_filename(f.filename),
    })


# ── Email Sender ────────────────────────────────────────────────────────────────

@app.post("/api/email/send")
def send_email():
    p = request.get_json(silent=True) or {}
    to_addr = p.get("to", "").strip()
    instruction = p.get("instruction", "").strip()
    context = p.get("context", "").strip()

    if not to_addr:
        return jsonify({"response": "Recipient email address is required."}), 400
    if not instruction:
        return jsonify({"response": "Please provide an instruction for the email."}), 400

    # AI writes the email
    ai_prompt = (
        f"You are a university professional drafting a formal email.\n"
        f"Instruction: {instruction}\n"
        f"Context: {context if context else 'University academic setting'}\n\n"
        f"Write the email using exactly this format (no markdown):\n"
        f"SUBJECT: [subject line here]\n"
        f"BODY:\n[full professional email body here]\n\n"
        f"Keep it professional, clear, and concise."
    )
    ai_text = ask_gemini(ai_prompt)
    if not ai_text:
        return jsonify({"response": "AI could not generate email content."}), 500

    # Parse SUBJECT and BODY from AI output
    subject, body = "", ai_text
    for line in ai_text.splitlines():
        if line.upper().startswith("SUBJECT:"):
            subject = line[8:].strip()
            body = ai_text[ai_text.index(line) + len(line):].strip()
            if body.upper().startswith("BODY:"):
                body = body[5:].strip()
            break
    if not subject:
        subject = f"University Communication — {instruction[:60]}"

    # Try real send
    sent = False
    send_error = None
    email_configured = bool(
        GMAIL_USER and GMAIL_PASS
        and not GMAIL_USER.startswith("your_")
        and not GMAIL_PASS.startswith("your_")
    )
    if email_configured:
        try:
            msg = MIMEMultipart()
            msg["From"] = GMAIL_USER
            msg["To"] = to_addr
            msg["Subject"] = subject
            msg.attach(MIMEText(body, "plain"))
            with smtplib.SMTP_SSL("smtp.gmail.com", 465) as srv:
                srv.login(GMAIL_USER, GMAIL_PASS)
                srv.send_message(msg)
            sent = True
        except Exception as e:
            send_error = str(e)

    status = (
        f"SENT to {to_addr}" if sent
        else f"PREVIEW ONLY — configure Gmail in .env to send real emails"
        + (f"\nError: {send_error}" if send_error else "")
    )
    return jsonify({
        "response": f"Status: {status}\n\nSubject: {subject}\n\n{body}",
        "sent": sent,
        "subject": subject,
        "to": to_addr,
    })


# ── Rule-based advising engine ─────────────────────────────────────────────────

@dataclass
class CourseLoadContext:
    current_semester: int
    gpa: float
    credits_completed: int
    planned_courses: int


def advise_academic_path(payload: Dict[str, Any]) -> Dict[str, Any]:
    current_semester = int(payload.get("currentSemester", 1))
    gpa = float(payload.get("gpa", 3.0))
    credits_completed = int(payload.get("creditsCompleted", (current_semester - 1) * 15))
    planned_courses = int(payload.get("plannedCourses", 5))

    ctx = CourseLoadContext(
        current_semester=current_semester,
        gpa=gpa,
        credits_completed=credits_completed,
        planned_courses=planned_courses,
    )

    messages: List[str] = []

    if ctx.gpa < 2.0:
        messages.append(
            "Your GPA is below 2.0. Strongly consider reducing course load, focusing on retaking "
            "failed or weak courses, and meeting an academic advisor to avoid probation."
        )
    elif ctx.gpa < 2.5:
        messages.append(
            "Your GPA is moderate. Be careful when combining heavy theory courses in the same term "
            "and ensure you allocate extra study time for core subjects."
        )
    else:
        messages.append(
            "Your GPA is healthy. You can generally follow the recommended pathway and optionally "
            "add internships or capstone preparation."
        )

    if ctx.planned_courses >= 7:
        messages.append(
            "You planned a heavy course load. Unless you are very confident, keep the number of "
            "courses at 5-6 to avoid burnout."
        )
    elif ctx.planned_courses <= 3:
        messages.append(
            "Your planned load is light. This is safe during difficult semesters or when managing "
            "work/internships."
        )

    if ctx.current_semester >= 6:
        messages.append(
            "You are in senior semesters. Prioritize capstone, internships, and remaining mandatory "
            "courses. Avoid delaying graduation-critical subjects."
        )

    pathway = []
    if ctx.current_semester <= 2:
        pathway = [
            "Complete foundational math and programming courses.",
            "Avoid overloading with electives; build strong basics first.",
        ]
    elif ctx.current_semester <= 4:
        pathway = [
            "Mix core departmental courses with 1-2 lighter electives.",
            "Start exploring domains of interest (e.g., AI, systems, web).",
        ]
    else:
        pathway = [
            "Ensure all core courses are completed or scheduled soon.",
            "Plan capstone/internship and align electives to your target domain.",
        ]

    risk = "LOW"
    if ctx.gpa < 2.0 or ctx.planned_courses >= 7:
        risk = "HIGH"
    elif ctx.gpa < 2.5 or ctx.planned_courses >= 6:
        risk = "MEDIUM"

    return {
        "riskLevel": risk,
        "summary": f"Semester {ctx.current_semester}, GPA {ctx.gpa:.2f}, planned courses {ctx.planned_courses}.",
        "recommendations": messages,
        "pathwaySteps": pathway,
    }


# ── /api/advising/query  (unified endpoint for all 7 sub-sections) ────────────

@app.post("/api/advising/query")
def advising_query():
    p = request.get_json(silent=True) or {}
    qtype = p.get("type", "general")

    if qtype == "course-selection":
        edu = p.get("education", "high-school")
        gpa = p.get("gpa", 3.0)
        interest = p.get("interest", "general")
        math_skill = p.get("mathSkill", "intermediate")
        prompt = (
            f"You are a university academic advisor. A student has the following profile:\n"
            f"- Education background: {edu}\n- Current GPA: {gpa}\n"
            f"- Area of interest: {interest}\n- Math skill level: {math_skill}\n\n"
            f"Recommend 4-5 specific courses they should take this semester, explain prerequisites "
            f"they must meet first, and give 2 practical tips for course selection. Use bullet points."
        )

    elif qtype == "academic-progression":
        sem = p.get("semester", 1)
        cred = p.get("completedCredits", 0)
        cnt = p.get("completedCourses", 0)
        rem = p.get("remainingCourses", "")
        pct = round(int(cred) / 120 * 100)
        risk = "HIGH" if pct < 40 and int(sem) > 4 else "MEDIUM" if pct < 60 and int(sem) > 5 else "LOW"
        prompt = (
            f"You are a university academic advisor. A student is in Semester {sem}, has completed "
            f"{cred} credits ({pct}% of a 120-credit programme) and {cnt} courses. "
            f"Remaining planned: {rem if rem else 'not specified'}.\n\n"
            f"Their graduation risk level is {risk}. Provide:\n"
            f"1. A brief progression assessment (2-3 sentences)\n"
            f"2. Key milestones they must hit to graduate on time\n"
            f"3. 3 actionable recommendations\nUse bullet points."
        )
        ai_text = ask_gemini(prompt)
        return jsonify({"response": ai_text or "Unable to analyse progression at this time.", "riskLevel": risk})

    elif qtype == "credit-management":
        ctype = p.get("creditType", "transfer")
        if ctype == "transfer":
            prompt = (
                f"A student wants to transfer the course '{p.get('course','?')}' ({p.get('credits','3')} credits, "
                f"grade {p.get('grade','B')}) to replace '{p.get('targetCourse','?')}'. "
                f"Explain: (1) eligibility criteria, (2) required documents, (3) typical timeline, "
                f"(4) likelihood of approval given the grade. Use numbered points."
            )
        elif ctype == "drop-add":
            prompt = (
                f"A student wants to drop '{p.get('dropCourse','?')}' and add '{p.get('addCourse','?')}' "
                f"in Week {p.get('week','2')} of semester. Reason: {p.get('reason','schedule conflict')}. "
                f"Explain: (1) deadline rules, (2) GPA impact, (3) financial implications, "
                f"(4) procedure steps. Use numbered points."
            )
        else:
            prompt = (
                f"A student wants to retake '{p.get('course','?')}' (previous grade: {p.get('grade','F')}, "
                f"attempt: {p.get('attempts','1')}, current GPA: {p.get('gpa','2.0')}). "
                f"Advise on: (1) eligibility and attempt limits, (2) GPA recalculation rules, "
                f"(3) study strategy for retake, (4) warning if this is a final attempt. Use numbered points."
            )

    elif qtype == "internship-projects":
        sub = p.get("subType", "internship")
        if sub == "internship":
            gpa = float(p.get("gpa", 2.5))
            sem = int(p.get("semester", 6))
            cred = int(p.get("credits", 90))
            eligible = gpa >= 2.5 and sem >= 5 and cred >= 80
            status = "ELIGIBLE" if eligible else "NOT YET ELIGIBLE"
            prompt = (
                f"A student in Semester {sem} with GPA {gpa} and {cred} credits completed wants a "
                f"{p.get('duration','16')}-week internship in {p.get('domain','industry')}. "
                f"Eligibility status: {status}.\n"
                f"Provide: (1) eligibility verdict with reasons, (2) required documents and approval process, "
                f"(3) 3 tips for securing an internship in {p.get('domain','their field')}, "
                f"(4) what to do if not yet eligible. Use numbered points."
            )
        elif sub == "capstone":
            prompt = (
                f"A student is proposing a capstone project: '{p.get('title','?')}' using {p.get('stack','?')} "
                f"with a team of {p.get('teamSize','3')}. Supervisor: {p.get('supervisor','not assigned')}. "
                f"Description: {p.get('description','not provided')}.\n"
                f"Provide: (1) project feasibility assessment, (2) suggested milestones timeline, "
                f"(3) key risks and mitigations, (4) recommendation on tech stack. Use numbered points."
            )
        else:
            prompt = (
                f"A student proposes a Final Year Project on '{p.get('area','?')}' using "
                f"{p.get('methodology','?')} methodology. Problem: {p.get('problem','not stated')}.\n"
                f"Provide: (1) research viability assessment, (2) suggested structure (chapters/phases), "
                f"(3) potential challenges, (4) recommended resources or datasets. Use numbered points."
            )

    elif qtype == "academic-advising":
        gpa = float(p.get("gpa", 2.5))
        sem = int(p.get("currentSemester", 1))
        planned = int(p.get("plannedCourses", 5))
        failed = int(p.get("failedCourses", 0))
        focus = p.get("focus", "all")
        pt = p.get("partTime", "no")

        risk = "LOW"
        if gpa < 2.0 or failed >= 3: risk = "HIGH"
        elif gpa < 2.5 or failed >= 1 or planned >= 7: risk = "MEDIUM"

        sections = []
        if focus in ("path", "all"):
            sections.append("Study Path: recommend a 2-semester course plan suited to their profile.")
        if focus in ("workload", "all"):
            sections.append(f"Workload Balancing: advise on managing {planned} courses{'while working' if pt != 'no' else ''}.")
        if focus in ("probation", "all"):
            sections.append(f"Probation Risk: assess risk given GPA {gpa} and {failed} failed courses.")

        prompt = (
            f"University academic advisor. Student profile: Semester {sem}, GPA {gpa}, "
            f"planned courses: {planned}, failed courses: {failed}, working status: {pt}. "
            f"Risk level: {risk}.\n\nAddress the following:\n" +
            "\n".join(f"{i+1}. {s}" for i, s in enumerate(sections)) +
            "\n\nBe concise, encouraging, and practical. Use bullet points within each section."
        )
        ai_text = ask_gemini(prompt)
        return jsonify({"response": ai_text or f"Risk Level: {risk}\nSeek advising for GPA {gpa} in semester {sem}.", "riskLevel": risk})

    elif qtype == "advising-support":
        sub = p.get("subType", "faq")
        if sub == "session":
            prompt = (
                f"A student '{p.get('student','?')}' wants to schedule an advising session with "
                f"{p.get('advisor','department advisor')} on {p.get('date','?')} at {p.get('time','?')}. "
                f"Reason: {p.get('reason','general advising')}.\n"
                f"Confirm the session booking, list 3 things the student should prepare before the session, "
                f"and suggest 2-3 questions they should ask the advisor based on their reason."
            )
        elif sub == "records":
            prompt = (
                f"A student (ID: {p.get('studentId','?')}) is requesting their advising records for "
                f"academic year {p.get('year','?')}. Explain: (1) how to access advising records officially, "
                f"(2) what is typically included in advising records, (3) student rights regarding these records."
            )
        else:
            q = p.get("query", "")
            prompt = (
                f"You are a university academic FAQ assistant. Answer this student question clearly and helpfully:\n"
                f"'{q}'\n\nProvide a clear answer with relevant policy details and next steps. "
                f"If the question needs to be escalated, say so."
            )

    elif qtype == "escalation":
        sub = p.get("subType", "detect")
        if sub == "detect":
            gpa = float(p.get("gpa", 1.4))
            failed = int(p.get("failedCourses", 3))
            sem = p.get("semester", 4)
            desc = p.get("description", "")
            risk = "CRITICAL" if gpa < 1.5 or failed >= 4 else "HIGH" if gpa < 2.0 or failed >= 2 else "MEDIUM"
            prompt = (
                f"Academic escalation assessment. Student in Semester {sem}, GPA {gpa}, failed courses: {failed}.\n"
                f"Additional context: {desc if desc else 'None provided'}.\n\n"
                f"Provide: (1) case severity assessment ({risk}), (2) specific risk factors identified, "
                f"(3) recommended immediate interventions, (4) who should be notified and why, "
                f"(5) suggested support resources. Use numbered points."
            )
            ai_text = ask_gemini(prompt)
            return jsonify({"response": ai_text or f"Case assessed as {risk}. Immediate faculty intervention recommended.", "riskLevel": risk})
        else:
            prompt = (
                f"Draft a formal academic escalation memo to {p.get('redirectTo','Programme Coordinator')} "
                f"with urgency level: {p.get('urgency','normal')}.\n"
                f"Reason: {p.get('reason','not specified')}.\n\n"
                f"Write a professional 3-4 sentence escalation memo that includes: the nature of the case, "
                f"urgency level, requested action, and expected response timeline."
            )
    else:
        prompt = f"Answer this academic advising question: {p.get('query', 'general advising inquiry')}"

    ai_text = ask_gemini(prompt)
    fallback = "AI advisor unavailable. Please contact your department advisor directly."
    return jsonify({"response": ai_text or fallback})


# ── /api/advising ──────────────────────────────────────────────────────────────

@app.get("/api/advising/faqs")
def get_faqs():
    return jsonify({
        "category": "Student Queries & Advising",
        "faqs": [
            "How do I select courses and check prerequisites?",
            "What are the rules for course add/drop and retake?",
            "How do I know if I'm at risk of academic probation?",
            "What are the guidelines for internship, capstone, and projects?",
        ],
    })


@app.post("/api/advising/plan")
def get_academic_plan():
    payload = request.get_json(silent=True) or {}
    result = advise_academic_path(payload)

    ai_text = ask_gemini(
        f"You are a university academic advisor. A student is in semester {payload.get('currentSemester', 1)} "
        f"with GPA {payload.get('gpa', 3.0)} and plans to take {payload.get('plannedCourses', 5)} courses. "
        f"Their risk level is {result['riskLevel']}. Give 3 concise, practical, encouraging academic tips "
        f"tailored to their situation. Use bullet points."
    )
    if ai_text:
        result["aiAdvice"] = ai_text

    return jsonify(result)


# ── /api/documentation ─────────────────────────────────────────────────────────

@app.get("/api/documentation/types")
def get_document_types():
    return jsonify({
        "category": "Academic Documentation",
        "forms": [
            "Course registration form",
            "Course withdrawal form",
            "Credit transfer / exemption request",
            "Internship approval form",
            "Capstone project approval form",
        ],
        "certificates": [
            "Bonafide certificate",
            "No Objection Certificate (NOC)",
            "Recommendation letter",
            "Custom academic letter",
        ],
    })


@app.post("/api/documentation/query")
def documentation_query():
    p = request.get_json(silent=True) or {}
    qtype = p.get("type", "general")

    if qtype == "form-processing":
        ft = p.get("formType", "registration")
        labels = {"registration":"Course Registration","withdrawal":"Course Withdrawal","credit-transfer":"Credit Transfer","exemption":"Course Exemption","internship":"Internship Approval","capstone":"Capstone Project Approval"}
        label = labels.get(ft, ft)
        details = ", ".join(f"{k}: {v}" for k, v in p.items() if k not in ("type","formType") and v)
        prompt = (
            f"You are a university document administrator. A student has submitted a {label} form.\n"
            f"Details: {details}.\n\n"
            f"Respond with:\n"
            f"1. Confirmation that the form has been received and what it means.\n"
            f"2. List of required supporting documents for this form type.\n"
            f"3. Expected processing timeline.\n"
            f"4. Next steps the student must take.\n"
            f"5. Any warnings or conditions that may affect approval.\n"
            f"Be concise and official in tone."
        )

    elif qtype == "cert-letter":
        dt = p.get("docType","bonafide")
        name = p.get("name","the student")
        prog = p.get("programme","the programme")
        purpose = p.get("purpose","general use")
        to = p.get("addressedTo","Whom It May Concern")
        prompt = (
            f"You are a university registrar. Generate a formal {dt} for student {name} "
            f"({p.get('studentId','')}) enrolled in {prog} for academic year {p.get('year','')}.\n"
            f"Purpose: {purpose}. Addressed to: {to}. Requested by: {p.get('requestedBy','student')}.\n\n"
            f"Write the full official document text. Include: institution letterhead placeholder [University Name], "
            f"date placeholder [Date], reference number placeholder [REF-XXXX], body of the document, "
            f"and closing with authorised signatory placeholder. Keep it formal and concise."
        )

    elif qtype == "student-records":
        action = p.get("action","profile")
        sid = p.get("studentId","?")
        name = p.get("name","the student")
        action_labels = {"profile":"student profile view","history":"academic history","results":"course and result records","gpa":"GPA/CGPA tracking","correction":"data correction"}
        prompt = (
            f"You are a university registrar handling a {action_labels.get(action,action)} request "
            f"for student {name} (ID: {sid}).\n"
            + (f"Current CGPA: {p.get('cgpa')}, Credits: {p.get('credits')}, Semester: {p.get('semester')}.\n" if action=="gpa" else "")
            + (f"Correction needed: field '{p.get('field')}', change: {p.get('correction')}.\n" if action=="correction" else "")
            + f"\nProvide:\n1. Confirmation of the request.\n2. What data is available or changed.\n"
            f"3. Verification steps required.\n4. Timeline for processing.\n5. Privacy and data policy note."
        )

    elif qtype == "doc-storage":
        op = p.get("operation","upload")
        op_labels = {"upload":"file upload","categorize":"document categorization","archive":"record archiving","access":"secure access configuration"}
        prompt = (
            f"You are a university document management system administrator.\n"
            f"Operation: {op_labels.get(op,op)}.\n"
            f"Document: {p.get('docName','?')}, Category: {p.get('category','?')}, "
            f"Student: {p.get('studentId','?')}, Year: {p.get('year','?')}, "
            f"Access Level: {p.get('accessLevel','?')}, Retention: {p.get('retention','?')}.\n\n"
            f"Respond with:\n1. Confirmation of the storage operation.\n2. Storage location and organisation structure.\n"
            f"3. Access control rules applied.\n4. Backup and retention policy details.\n5. Retrieval instructions."
        )

    elif qtype == "doc-search":
        prompt = (
            f"You are a university document retrieval system.\n"
            f"Search request: by {p.get('searchBy','?')} = '{p.get('value','?')}', "
            f"type filter: {p.get('typeFilter','all')}, status filter: {p.get('statusFilter','all')}.\n\n"
            f"Simulate a search result response:\n"
            f"1. Number of documents found (simulate a realistic count).\n"
            f"2. Summary of top 3 matching document records (use realistic placeholder data).\n"
            f"3. Available actions for each found document (view, download, share).\n"
            f"4. How to refine the search if too many or too few results.\n"
            f"Keep it realistic and helpful."
        )

    elif qtype == "query-support":
        st = p.get("supportType","query")
        if st == "status":
            prompt = (
                f"You are a university document tracking system. Student {p.get('studentId','?')} "
                f"is checking the status of request reference {p.get('referenceId','?')}.\n\n"
                f"Simulate a realistic status response:\n1. Current status (e.g. Under Review / Pending Approval / Approved).\n"
                f"2. Last action taken and who took it.\n3. Next expected step.\n4. Estimated completion date.\n5. Who to contact for urgent queries."
            )
        elif st == "faq":
            prompt = (
                f"You are a university documentation FAQ assistant. Answer this question clearly:\n"
                f"'{p.get('query','?')}'\n\nProvide a clear, step-by-step answer with:\n"
                f"1. Direct answer.\n2. Required documents or conditions.\n3. How to apply or where to go.\n4. Common mistakes to avoid."
            )
        else:
            prompt = (
                f"You are a university admin responding to a student query.\n"
                f"Student ID: {p.get('studentId','?')}, Reference: {p.get('referenceId','?')}.\n"
                f"Query: {p.get('query','?')}.\n\n"
                f"Provide an official admin response:\n1. Acknowledgement of the query.\n"
                f"2. Direct answer or clarification.\n3. Next steps for the student.\n4. Expected response timeline."
            )

    elif qtype == "compliance":
        ct = p.get("checkType","policy")
        prompt = (
            f"You are a university compliance officer.\n"
            f"Check type: {ct}. Document type: {p.get('docType','?')}, "
            f"Semester: {p.get('semester','?')}, Week: {p.get('week','?')}, "
            f"Student: {p.get('studentId','N/A')}.\n\n"
            f"Provide:\n1. Policy or deadline information relevant to this document type.\n"
            f"2. Whether the current timing (Week {p.get('week','?')} of Semester {p.get('semester','?')}) is within allowed window.\n"
            f"3. Consequences of missing the deadline.\n4. Any automatic reminders or approval steps involved.\n"
            f"5. University policy reference (use realistic placeholder like Policy Ref: ACA-2024-003)."
        )

    elif qtype == "ai-processing":
        mode = p.get("mode","validate")
        mode_labels = {"validate":"automatic validation","missing":"missing data detection","error":"error suggestion","extract":"data extraction"}
        content = p.get("content","(no content provided)")
        prompt = (
            f"You are an AI document processor performing {mode_labels.get(mode,mode)}.\n"
            f"Document type: {p.get('docType','?')}, Student: {p.get('studentId','?')}.\n"
            f"Content/Data: {content}\n\n"
            f"Perform the {mode_labels.get(mode,mode)} and report:\n"
            f"1. Overall document quality assessment.\n"
            f"2. List of issues found (or confirm all fields are correct).\n"
            f"3. Specific corrections or missing fields needed.\n"
            f"4. Whether the document is ready for submission or needs revision.\n"
            f"5. AI confidence score (e.g. 87% complete)."
        )

    elif qtype == "ai-generation":
        gt = p.get("genType","certificate")
        name = p.get("name","the student")
        prompt = (
            f"You are an AI document generation system. Generate a {gt} for:\n"
            f"Student: {name} (ID: {p.get('studentId','?')}), Programme: {p.get('programme','?')}, "
            f"Academic Year: {p.get('year','?')}, Purpose: {p.get('purpose','general')}, "
            f"Addressed to: {p.get('addressedTo','Whom It May Concern')}.\n\n"
            f"Generate the complete document text including:\n"
            f"[UNIVERSITY LETTERHEAD]\nReference: [AUTO-REF-XXXX]\nDate: [Current Date]\n\n"
            f"Then write the full document body formally and professionally. "
            f"Include all standard sections for this document type. "
            f"End with authorised signatory block and document control footer."
        )

    elif qtype == "ai-smart-search":
        prompt = (
            f"You are an AI-powered university document search engine.\n"
            f"Search mode: {p.get('mode','natural')}. Scope: {p.get('scope','all')}. Period: {p.get('period','This Semester')}.\n"
            f"Query: '{p.get('query','?')}'\n\n"
            f"Interpret this query and respond with:\n"
            f"1. Your interpretation of what the user is looking for.\n"
            f"2. Simulated search results (3-5 realistic document entries with ID, type, date, status).\n"
            f"3. Smart suggestions to narrow or expand the search.\n"
            f"4. Related documents or records the user might also need."
        )

    elif qtype == "chatbot":
        role = p.get("role","student")
        topic = p.get("topic","guidance")
        question = p.get("question","?")
        prompt = (
            f"You are a friendly university documentation AI assistant helping a {role}.\n"
            f"Help topic: {topic}. Student ID: {p.get('studentId','not provided')}.\n"
            f"Question: '{question}'\n\n"
            f"Reply in a helpful, conversational but professional tone:\n"
            f"1. Direct answer to the question.\n"
            f"2. Step-by-step guidance if a process is involved.\n"
            f"3. Any forms or documents needed.\n"
            f"4. Where to go or who to contact.\n"
            f"5. A helpful tip specific to the topic."
        )

    elif qtype == "access-control":
        prompt = (
            f"You are a university system access control administrator.\n"
            f"Action: {p.get('action','?')}, Role: {p.get('role','?')}, "
            f"User: {p.get('userId','?')}, Category: {p.get('category','?')}, "
            f"Permission requested: {p.get('permission','?')}.\n\n"
            f"Respond with:\n1. Access request assessment (approved/denied/conditional).\n"
            f"2. Permissions granted or reason for denial.\n"
            f"3. Role-based access policy for this role.\n"
            f"4. Audit log entry that would be created.\n"
            f"5. Security recommendations."
        )

    elif qtype == "notification":
        nt = p.get("notifType","email")
        msg = p.get("message","")
        prompt = (
            f"You are a university notification system. Draft a {nt} notification.\n"
            f"Recipient: {p.get('recipient','?')}, Student/Group: {p.get('studentId','?')}, "
            f"Subject: {p.get('subject','?')}, Deadline: {p.get('deadlineDate','N/A')}.\n"
            + (f"User message hint: {msg}\n" if msg else "")
            + f"\nWrite the complete notification:\n"
            f"1. Subject line.\n2. Salutation.\n3. Main message body (professional, clear, concise).\n"
            f"4. Call to action.\n5. Contact information placeholder.\n6. Closing."
        )

    elif qtype == "dashboard":
        prompt = (
            f"You are a university administrative analytics engine.\n"
            f"Report type: {p.get('reportType','overview')}, Period: {p.get('period','This Month')}, "
            f"Department: {p.get('department','All')}, Filter: {p.get('filter','all')}.\n\n"
            f"Generate a realistic analytics summary:\n"
            f"1. Total requests received (use realistic numbers).\n"
            f"2. Breakdown by document type (Certificate: X, Forms: X, Transcripts: X, etc.).\n"
            f"3. Approval statistics (Approved: X%, Pending: X%, Rejected: X%).\n"
            f"4. Average processing time.\n"
            f"5. Key trends or anomalies observed.\n"
            f"6. Recommendations for improving processing efficiency."
        )

    elif qtype == "verification":
        vt = p.get("verType","authenticity")
        prompt = (
            f"You are a university document verification system.\n"
            f"Verification type: {vt}. Document ID: {p.get('docId','?')}, "
            f"Student: {p.get('studentId','?')}, Document type: {p.get('docType','?')}, "
            f"Year: {p.get('year','?')}, Code: {p.get('code','not provided')}.\n\n"
            f"Perform the verification and respond with:\n"
            f"1. Verification result (VERIFIED / UNVERIFIED / PENDING).\n"
            f"2. Document details matched in the system.\n"
            f"3. Authenticity indicators checked.\n"
            f"4. Digital signature / QR status.\n"
            f"5. Official verification statement for third-party use."
        )

    else:
        prompt = f"Answer this university documentation question: {p.get('query','general query')}"

    ai_text = ask_gemini(prompt)
    return jsonify({"response": ai_text or "AI documentation assistant unavailable. Please contact the registrar's office."})


@app.post("/api/documentation/generate")
def generate_document():
    payload = request.get_json(silent=True) or {}
    student = payload.get("studentName", "Student")
    doc_type = payload.get("type", "custom-letter")

    type_labels = {
        "bonafide": "Bonafide Certificate",
        "noc": "No Objection Certificate (NOC)",
        "recommendation": "Recommendation Letter",
        "custom-letter": "Custom Academic Letter",
    }
    label = type_labels.get(doc_type, "Academic Letter")

    ai_text = ask_gemini(
        f"Write a formal university {label} for a student named '{student}'. "
        f"The letter should be professional, concise (3-4 sentences), and suitable for official use. "
        f"Include placeholders like [Department Name], [Date], [Principal/HOD Name] where appropriate. "
        f"Do not include a subject line or greetings header - start directly with the body."
    )

    if ai_text:
        draft = ai_text
    elif doc_type == "bonafide":
        draft = (
            f"This is to certify that {student} is a bonafide student of the department, "
            f"currently enrolled and fulfilling the academic requirements of the program."
        )
    elif doc_type == "noc":
        draft = (
            f"This is to state that the department has no objection to {student} undertaking "
            f"the specified activity, subject to university rules and regulations."
        )
    elif doc_type == "recommendation":
        draft = (
            f"I am pleased to recommend {student} based on their academic performance "
            f"and conduct in the department."
        )
    else:
        draft = (
            f"This letter confirms relevant academic details for {student}. "
            f"Please customize this draft according to the specific purpose."
        )

    return jsonify({"type": doc_type, "studentName": student, "draft": draft})


# ── /api/scheduling/query  (unified endpoint for all 8 sub-sections) ──────────

@app.post("/api/scheduling/query")
def scheduling_query():
    p = request.get_json(silent=True) or {}
    qtype = p.get("type", "general")

    if qtype == "schedule-management":
        st = p.get("schedType", "class")
        labels = {"class":"class schedule/routine","exam":"examination schedule","lab":"lab & resource booking","change":"schedule change","reschedule":"rescheduling request"}
        label = labels.get(st, st)
        details = ", ".join(f"{k}: {v}" for k, v in p.items() if k not in ("type","schedType") and v)
        prompt = (
            f"You are a university timetable administrator processing a {label}.\n"
            f"Details: {details}.\n\n"
            f"Respond with:\n"
            f"1. Confirmation of the schedule entry with all key details.\n"
            f"2. Check for any obvious conflicts or issues with this slot.\n"
            f"3. Notification plan: who should be informed and how.\n"
            f"4. Any university policy or room-booking rules that apply.\n"
            f"5. Next administrative steps required."
        )

    elif qtype == "notices":
        nt = p.get("noticeType","academic")
        content = p.get("content","")
        priority = p.get("priority","medium")
        prompt = (
            f"You are a university communications officer publishing a {nt} notice.\n"
            f"Title: {p.get('title','?')}, Audience: {p.get('audience','all students')}, "
            f"Priority: {priority}, Category: {p.get('category','Academic')}, "
            f"Publish: {p.get('publishDate','?')}, Expiry: {p.get('expiryDate','?')}.\n"
            + (f"User content: {content}\n" if content else "")
            + f"\nGenerate the complete notice:\n"
            f"1. Official notice heading (University / Department name placeholder, Date, Ref No).\n"
            f"2. Subject line.\n"
            f"3. Body of the notice (clear, professional, audience-appropriate).\n"
            f"4. Action required from recipients.\n"
            f"5. Contact details placeholder and authorised signatory.\n"
            f"Urgency tone should match priority level: {priority}."
        )

    elif qtype == "reminders":
        rt = p.get("reminderType","registration")
        prompt = (
            f"You are a university reminder system administrator.\n"
            f"Reminder type: {rt}, Title: {p.get('title','?')}, "
            f"Deadline: {p.get('deadlineDate','?')}, Days before: {p.get('daysBefore','7')}, "
            f"Target group: {p.get('targetGroup','all students')}, "
            f"Channel: {p.get('channel','All Channels')}, Frequency: {p.get('frequency','once')}.\n"
            f"Extra message: {p.get('message','none')}.\n\n"
            f"Provide:\n"
            f"1. Full reminder message text ready to send.\n"
            f"2. Recommended sending schedule (with specific dates based on deadline).\n"
            f"3. Escalation plan if no action is taken after the first reminder.\n"
            f"4. Channel-specific formatting notes (email subject, SMS shortening).\n"
            f"5. Estimated reach and impact."
        )

    elif qtype == "dissemination":
        mode = p.get("mode","broadcast")
        body = p.get("body","")
        prompt = (
            f"You are a university information dissemination officer.\n"
            f"Mode: {mode}, Channels: {p.get('channels','All')}, "
            f"Segment: {p.get('segment','all')} ({p.get('segmentDetail','')}), "
            f"Delivery: {p.get('deliveryTime','now')}, "
            f"Scheduled: {p.get('scheduledDateTime','N/A')}.\n"
            f"Title: {p.get('title','?')}.\n"
            + (f"Body: {body}\n" if body else "")
            + f"\nGenerate:\n"
            f"1. Complete message text for each channel (email version, SMS version, app push version).\n"
            f"2. Delivery confirmation plan.\n"
            f"3. Expected reach count (use realistic estimates).\n"
            f"4. Opt-out and accessibility considerations.\n"
            f"5. Follow-up action if delivery fails."
        )

    elif qtype == "archive":
        action = p.get("action","search")
        prompt = (
            f"You are a university archive and records management system.\n"
            f"Action: {action}, Keyword: '{p.get('keyword','?')}', "
            f"Date range: {p.get('dateFrom','?')} to {p.get('dateTo','?')}, "
            f"Category: {p.get('category','all')}, Group: {p.get('group','all')}, "
            f"Format: {p.get('format','View Summary')}.\n\n"
            f"Simulate an archive retrieval response:\n"
            f"1. Number of records found matching the criteria.\n"
            f"2. Top 4 matching notice/communication records (with realistic ID, date, title, type, status).\n"
            f"3. Export or download instructions.\n"
            f"4. Archive retention policy note for these records.\n"
            f"5. How to refine the search if needed."
        )

    elif qtype == "ai-scheduling":
        func = p.get("func","auto-gen")
        func_labels = {"auto-gen":"automatic schedule generation","conflict-detect":"conflict detection","conflict-resolve":"conflict resolution","resource-opt":"resource optimization"}
        constraints = p.get("constraints","none")
        prompt = (
            f"You are an AI university scheduling engine performing {func_labels.get(func,func)}.\n"
            f"Semester: {p.get('semester','?')}, Courses: {p.get('courses','?')}, "
            f"Lecturers: {p.get('lecturers','?')}, Rooms: {p.get('rooms','?')}, "
            f"Teaching days: {p.get('teachingDays','5')}/week, "
            f"Hours per day: {p.get('hoursPerDay','8')}.\n"
            f"Constraints: {constraints if constraints else 'none specified'}.\n\n"
            f"Perform the {func_labels.get(func,func)} and provide:\n"
            f"1. AI analysis of the scheduling parameters.\n"
            f"2. Generated schedule outline or conflict report (use realistic course/room placeholders).\n"
            f"3. Any detected clashes or bottlenecks.\n"
            f"4. Optimization recommendations.\n"
            f"5. Confidence score and alternative options if applicable."
        )

    elif qtype == "ai-announcement":
        mode = p.get("mode","auto-write")
        draft = p.get("draft","")
        lang = p.get("language","english")
        prompt = (
            f"You are an AI university announcement writer.\n"
            f"Mode: {mode}, Topic: {p.get('topic','?')}, Audience: {p.get('audience','All Students')}, "
            f"Tone: {p.get('tone','formal')}, Language: {lang}, "
            f"Key details: {p.get('details','none')}, Template: {p.get('template','Standard University Notice')}.\n"
            + (f"Rough draft to improve: {draft}\n" if draft else "")
            + f"\nGenerate:\n"
            f"1. Polished, complete announcement in {lang} (or both if bilingual requested).\n"
            f"2. Headline and subheading.\n"
            f"3. Full body text with proper tone and structure.\n"
            f"4. Call-to-action section.\n"
            f"5. Footer with contact and disclaimer placeholder."
        )

    elif qtype == "ai-smart-notif":
        mode = p.get("mode","smart-timing")
        pattern = p.get("pattern","unknown")
        priority = p.get("priority","medium")
        gpa = p.get("gpa",3.0)
        prompt = (
            f"You are an AI smart notification engine for a university.\n"
            f"Mode: {mode}, Target: {p.get('target','?')}, Topic: {p.get('topic','?')}, "
            f"Student GPA: {gpa}, Deadline: {p.get('deadline','?')}, "
            f"Behaviour pattern: {pattern}, Priority: {priority}.\n\n"
            f"Generate an intelligent notification plan:\n"
            f"1. Recommended notification timing and frequency based on behaviour pattern and deadline proximity.\n"
            f"2. Personalized message text tailored to the student's GPA and pattern ({pattern}).\n"
            f"3. Priority justification and urgency level.\n"
            f"4. Predictive risk: will this student likely miss the deadline? Why?\n"
            f"5. Suggested intervention if the student does not respond to notifications."
        )

    else:
        prompt = f"Answer this university scheduling question: {p.get('query', 'general scheduling inquiry')}"

    ai_text = ask_gemini(prompt)
    return jsonify({"response": ai_text or "AI scheduling assistant unavailable. Please contact the timetable office."})


# ── /api/scheduling ────────────────────────────────────────────────────────────

@app.get("/api/scheduling/reminders")
def get_reminders():
    return jsonify({
        "upcoming": [
            "Course registration deadline - Week 2",
            "Mid-semester exam period - Week 8",
            "Project submission - Week 12",
            "Final exam period - Week 16",
            "Add/drop deadline - End of Week 2",
        ]
    })


@app.post("/api/scheduling/suggest")
def schedule_suggest():
    payload = request.get_json(silent=True) or {}
    planned_courses = int(payload.get("plannedCourses", 5))

    risk = "LOW"
    if planned_courses >= 7:
        risk = "HIGH"
    elif planned_courses >= 6:
        risk = "MEDIUM"

    default_advice = "Your course load looks reasonable. You should manage your studies comfortably."
    if risk == "MEDIUM":
        default_advice = "Your course load is on the heavier side; ensure you have enough time for each subject and assessments."
    elif risk == "HIGH":
        default_advice = "Your course load is very heavy; consider dropping 1-2 courses or replacing with lighter electives."

    ai_text = ask_gemini(
        f"A university student is planning to take {planned_courses} courses this semester (risk level: {risk}). "
        f"Give 3 practical scheduling and time-management tips. Be concise and use bullet points."
    )

    return jsonify({
        "plannedCourses": planned_courses,
        "riskLevel": risk,
        "advice": ai_text if ai_text else default_advice,
    })


# ── /api/communication/query  (unified endpoint for all 9 sub-sections) ───────

@app.post("/api/communication/query")
def communication_query():
    p = request.get_json(silent=True) or {}
    qtype = p.get("type", "general")

    if qtype == "coordination":
        ct = p.get("commType", "faculty")
        labels = {"faculty":"faculty communication","admin":"administrative staff communication","students":"student communication","cross-dept":"cross-department communication"}
        msg = p.get("message", "")
        prompt = (
            f"You are a university communication coordinator handling {labels.get(ct, ct)}.\n"
            f"From: {p.get('from','?')}, To: {p.get('to','?')}, Department: {p.get('department','?')}, "
            f"Mode: {p.get('mode','Direct Message')}, Urgency: {p.get('urgency','normal')}, "
            f"Subject: {p.get('subject','?')}.\n"
            + (f"Message hint: {msg}\n" if msg else "")
            + f"\nGenerate:\n"
            f"1. A complete, professional communication message ready to send.\n"
            f"2. Recommended delivery channels based on urgency and audience.\n"
            f"3. Follow-up action required from the recipient.\n"
            f"4. Acknowledgement request or read-receipt recommendation.\n"
            f"5. Escalation path if no response within expected time."
        )

    elif qtype == "notice-memo":
        dt = p.get("docType", "memo")
        labels = {"notice":"Internal Notice","memo":"Formal Memo","instruction":"Instructions / Guidelines","priority":"Priority Message"}
        content = p.get("content", "")
        prompt = (
            f"You are a university administrative officer drafting a {labels.get(dt, dt)}.\n"
            f"Reference: {p.get('ref','[AUTO-REF]')}, To: {p.get('to','All Staff')}, "
            f"From: {p.get('from','Administration')}, Date: {p.get('date','[Date]')}, "
            f"Subject: {p.get('subject','?')}, Priority: {p.get('priority','normal')}.\n"
            + (f"Key content points: {content}\n" if content else "")
            + f"\nDraft the complete formal {labels.get(dt, dt)}:\n"
            f"1. Official header with reference number, date, and routing.\n"
            f"2. Subject line.\n"
            f"3. Body — clear, concise, and authoritative.\n"
            f"4. Action required and deadline.\n"
            f"5. Authorised signatory block and distribution list."
        )

    elif qtype == "meetings":
        action = p.get("action", "schedule")
        agenda = p.get("agenda", "")
        action_labels = {"schedule":"meeting scheduling","agenda":"agenda preparation","participants":"participant management","records":"meeting minutes/records"}
        prompt = (
            f"You are a university meeting coordinator handling {action_labels.get(action, action)}.\n"
            f"Meeting: {p.get('title','?')}, Type: {p.get('meetingType','Departmental')}, "
            f"Date: {p.get('date','?')}, Time: {p.get('time','?')}, Venue: {p.get('venue','?')}, "
            f"Duration: {p.get('duration','1')} hr(s), Organiser: {p.get('organiser','?')}, "
            f"Participants: {p.get('participants','?')}.\n"
            + (f"Agenda points / notes: {agenda}\n" if agenda else "")
            + f"\nProvide:\n"
            f"1. Meeting confirmation / formal invitation text.\n"
            f"2. Structured agenda (if agenda mode) or minutes (if records mode).\n"
            f"3. Participant roles and responsibilities.\n"
            f"4. Pre-meeting preparation checklist.\n"
            f"5. Post-meeting action items template."
        )

    elif qtype == "tasks":
        action = p.get("action", "assign")
        status = p.get("status", "not-started")
        priority = p.get("priority", "medium")
        action_labels = {"assign":"task assignment","progress":"progress tracking","followup":"follow-up","deadline":"deadline management"}
        prompt = (
            f"You are a university task management coordinator handling {action_labels.get(action, action)}.\n"
            f"Task: {p.get('title','?')}, Assigned to: {p.get('assignee','?')}, "
            f"Assigned by: {p.get('assignedBy','?')}, Due: {p.get('dueDate','?')}, "
            f"Priority: {priority}, Status: {status}.\n"
            f"Notes: {p.get('notes','none')}.\n\n"
            f"Provide:\n"
            f"1. Task assignment confirmation with all key details.\n"
            f"2. Progress assessment (based on current status: {status}).\n"
            f"3. Follow-up message to send to the assignee.\n"
            f"4. Escalation plan if task becomes overdue.\n"
            f"5. Recommended check-in schedule before the deadline."
        )

    elif qtype == "records":
        action = p.get("action", "search")
        action_labels = {"logs":"message logs","conversations":"documented conversations","search":"record search","archive":"archive management"}
        prompt = (
            f"You are a university communication records system handling {action_labels.get(action, action)}.\n"
            f"Keyword: '{p.get('keyword','?')}', Person: '{p.get('person','?')}', "
            f"Date range: {p.get('dateFrom','?')} to {p.get('dateTo','?')}, "
            f"Type: {p.get('commType','all')}, Department: {p.get('department','?')}.\n\n"
            f"Simulate a records retrieval response:\n"
            f"1. Number of records found.\n"
            f"2. Top 4 matching communication records (use realistic IDs, dates, subjects, senders).\n"
            f"3. Record retrieval and download options.\n"
            f"4. Data privacy and access control notes.\n"
            f"5. Archive retention policy for these records."
        )

    elif qtype == "external":
        ct = p.get("coordType", "department")
        labels = {"registrar":"Registrar's Office coordination","department":"inter-department coordination","approval":"approval request","info-exchange":"information exchange"}
        detail = p.get("detail", "")
        prompt = (
            f"You are a university external coordination officer managing {labels.get(ct, ct)}.\n"
            f"From: {p.get('from','?')}, To: {p.get('to','?')}, Subject: {p.get('subject','?')}, "
            f"Urgency: {p.get('urgency','normal')}, Reference: {p.get('reference','N/A')}, "
            f"Response needed by: {p.get('responseBy','?')}.\n"
            + (f"Details: {detail}\n" if detail else "")
            + f"\nGenerate:\n"
            f"1. Formal coordination request letter / memo.\n"
            f"2. Clear statement of what is needed and by when.\n"
            f"3. Supporting information or attachments to include.\n"
            f"4. Escalation path if no response is received.\n"
            f"5. Tracking reference and acknowledgement process."
        )

    elif qtype == "ai-smart":
        feature = p.get("feature", "platform")
        msg = p.get("message", "")
        feature_labels = {"platform":"smart messaging analysis","auto-reply":"automated reply generation","summarize":"message summarization","sentiment":"sentiment detection"}
        prompt = (
            f"You are an AI smart communication assistant performing {feature_labels.get(feature, feature)}.\n"
            f"Sender role: {p.get('role','?')}, Recipient: {p.get('to','?')}.\n"
            f"Message/Content: {msg if msg else '(no content provided)'}\n\n"
            + (
                "Summarize this message concisely, extract key action items, and identify the urgency level.\n"
                if feature == "summarize" else
                "Detect the sentiment (positive/neutral/negative/urgent/frustrated) and explain what it indicates about the sender's state.\n"
                if feature == "sentiment" else
                "Generate 3 appropriate automated reply options, ranging from brief acknowledgement to full formal response.\n"
                if feature == "auto-reply" else
                "Analyse this message and provide routing recommendation, urgency detection, and platform best practices.\n"
            )
            + "Provide:\n"
            f"1. Main AI output for {feature_labels.get(feature, feature)}.\n"
            f"2. Key insights or action items extracted.\n"
            f"3. Recommended next steps for the recipient.\n"
            f"4. Communication quality score or sentiment score.\n"
            f"5. Suggested improvements to the message if applicable."
        )

    elif qtype == "ai-meeting":
        mode = p.get("mode", "agenda-gen")
        notes = p.get("notes", "")
        mode_labels = {"auto-schedule":"automatic meeting scheduling","agenda-gen":"agenda generation","minutes-gen":"meeting minutes generation","followup-track":"post-meeting follow-up tracking"}
        prompt = (
            f"You are an AI meeting automation assistant performing {mode_labels.get(mode, mode)}.\n"
            f"Topic: {p.get('topic','?')}, Department: {p.get('department','?')}, "
            f"Participants: {p.get('participants','?')}, Duration: {p.get('duration','1')} hr(s), "
            f"Preferred time: {p.get('preferredTime','Flexible')}, Format: {p.get('format','Physical')}.\n"
            + (f"Notes/Raw content: {notes}\n" if notes else "")
            + f"\nGenerate:\n"
            f"1. Main output for {mode_labels.get(mode, mode)} (schedule / agenda / minutes / follow-up list).\n"
            f"2. Structured format with clear sections and numbering.\n"
            f"3. Time allocation per agenda item (if applicable).\n"
            f"4. Action items with owners and due dates.\n"
            f"5. Next meeting recommendation if applicable."
        )

    elif qtype == "ai-routing":
        mode = p.get("mode", "routing")
        msg = p.get("message", "")
        urgency = p.get("urgency", "auto")
        mode_labels = {"routing":"intelligent message routing","priority":"message priority detection","optimize":"notification optimization","workflow":"workflow automation"}
        prompt = (
            f"You are an AI message routing and prioritization engine performing {mode_labels.get(mode, mode)}.\n"
            f"Subject: {p.get('subject','?')}, Sender: {p.get('sender','?')}, "
            f"Intended audience: {p.get('audience','?')}, Urgency override: {urgency}.\n"
            f"Message: {msg if msg else '(no message content)'}\n\n"
            f"Perform the {mode_labels.get(mode, mode)} and provide:\n"
            f"1. AI-detected priority level (Critical / High / Medium / Low) with reasoning.\n"
            f"2. Recommended routing: who exactly should receive this message and why.\n"
            f"3. Suggested delivery channel and timing.\n"
            f"4. Notifications to suppress or batch to avoid alert fatigue.\n"
            f"5. Workflow automation suggestion: what should automatically happen next based on this message."
        )

    else:
        prompt = f"Answer this university communication question: {p.get('query', 'general communication inquiry')}"

    ai_text = ask_gemini(prompt)
    return jsonify({"response": ai_text or "AI communication assistant unavailable. Please contact the communications office."})


# ── /api/communication ─────────────────────────────────────────────────────────

@app.get("/api/communication/channels")
def get_channels():
    return jsonify({
        "category": "Internal Communication",
        "channels": [
            "Faculty announcements",
            "Student notices",
            "Administrative memos",
            "Meeting agendas and minutes",
        ],
    })


@app.post("/api/communication/draft")
def draft_message():
    payload = request.get_json(silent=True) or {}
    audience = payload.get("audience", "students")
    topic = payload.get("topic", "general update")

    ai_text = ask_gemini(
        f"Write a formal university internal announcement addressed to {audience} about the topic: '{topic}'. "
        f"Keep it professional, 3-4 sentences, suitable for an official academic notice. "
        f"Start with 'Dear {audience.capitalize()},'."
    )

    draft = ai_text if ai_text else (
        f"Dear {audience.capitalize()},\n\n"
        f"This is an official notice regarding: {topic}. "
        f"Please review the details carefully and take the necessary actions as required. "
        f"For further queries, contact the department office.\n\n"
        f"Regards,\nAcademic Administration"
    )

    return jsonify({"audience": audience, "topic": topic, "draft": draft})


# ── /api/admin-systems ─────────────────────────────────────────────────────────

@app.get("/api/admin-systems/overview")
def get_overview():
    return jsonify({
        "category": "Administrative Systems",
        "capabilities": [
            "Track service performance and turnaround times",
            "Generate administrative reports and dashboards",
            "Support audits, inspections, and compliance reporting",
        ],
    })


# ── /ai/status ─────────────────────────────────────────────────────────────────

@app.get("/ai/status")
def ai_status():
    return jsonify({
        "geminiEnabled": gemini_model is not None,
        "message": "Gemini AI active" if gemini_model else "Using rule-based fallback",
    })


if __name__ == "__main__":
    print("\n==============================================")
    print(" Academic Admin & Advising Portal")
    print(" Open in browser: http://localhost:8080")
    print("==============================================\n")
    app.run(host="0.0.0.0", port=8080, debug=True)
