# Academic Administrative & Advising Web Application

Java Spring Boot web application with a Python AI microservice that assists with:

- Student queries & academic advising
- Academic documentation (certificates, NOCs, recommendation letters)
- Scheduling & academic notices
- Internal communication drafting
- Administrative systems overview

## Tech stack

- **Java** 17, **Spring Boot** 3 (REST API + static front-end)
- **Python** 3, **Flask** (AI-style rule-based engine)

## Project structure

- `pom.xml` – Maven configuration for the Java app
- `src/main/java/com/university/adminportal` – Spring Boot application and controllers
- `src/main/resources/static/index.html` – Single-page UI
- `src/main/resources/application.properties` – Configuration, including Python AI base URL
- `ai-service/app.py` – Python Flask AI microservice
- `ai-service/requirements.txt` – Python dependencies

## Running the Python AI service

1. Open a terminal and navigate to the AI folder:

   ```bash
   cd ai-service
   python -m venv .venv
   .venv\Scripts\activate  # on Windows PowerShell: .venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   python app.py
   ```

2. The AI service will listen on `http://localhost:8000`.

## Running the Java web application

1. Open another terminal at the project root (`d:\Python\project`) and run:

   ```bash
   mvn spring-boot:run
   ```

2. Open the web UI in your browser:

   - `http://localhost:8080/`

## Main features mapped to your tasks

- **Student Queries & Advising**
  - Front-end section: *AI Academic Advising*
  - Java endpoint: `POST /api/advising/plan`
  - Python AI endpoint: `POST /ai/advise`
  - Provides risk level, recommendations, and pathway steps.

- **Academic Documentation**
  - Front-end section: *Document Assistant*
  - Java endpoint: `POST /api/documentation/generate`
  - Python AI endpoint: `POST /ai/document-draft`
  - Generates textual drafts for bonafide, NOC, recommendation, or custom letters.

- **Scheduling & Notices**
  - Front-end section: *Scheduling & Notices*
  - Java endpoints:
    - `GET /api/scheduling/reminders`
    - `POST /api/scheduling/suggest` → calls `POST /ai/schedule-suggest` in Python

- **Internal Communication**
  - Front-end section: *Message Drafting*
  - Java endpoints:
    - `GET /api/communication/channels`
    - `POST /api/communication/draft`

- **Administrative Systems**
  - Front-end section: *Administrative Systems Overview*
  - Java endpoint: `GET /api/admin-systems/overview`

You can extend each controller and the Python `app.py` logic with more advanced AI models, database persistence, authentication, and integration with university systems (ERP, LMS, SIS) as needed.

